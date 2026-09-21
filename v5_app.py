"""V5-M3 FastAPI 服务 —— 把 Router / 路径 / Validator 焊成一个 HTTP 服务

架构（一条请求的一生，拷问主线）：
  POST /chat {user_id, session_id, message}
    → 可观测性开路：trace id 贯穿全程（一条请求的一生串得起来）
    → route() 确定性分叉（M1）
    → rag 路径：记忆补全 query → 混合检索（M6：BM25+RRF）→ 生成（套重试护栏）
      analysis 路径：agent_turn 工具循环（M2 之外的第三个模块 v5_analysis）
    → run_with_guard 出口质检（M2）：不过带反馈重试 1 次 → 仍不过降级
    → 双写（热 memory + 冷 FinDB）→ 返回 {route, answer, attempts, ...}

设计决策（拷问点）：
  - 端点用普通 def 不用 async def：整条链路是同步的，MCP 客户端里
    asyncio.run 不可重入——async 世界被同步外壳隔离后，服务层保持同步最诚实
  - 重资源（向量模型/矩阵/Redis/FinDB）在 lifespan 里起服务时加载一次，
    不是每请求加载——模型加载秒级，放请求里 = 每次白等
  - 会话状态不在服务进程里：Memory 每请求按 (session_id, user_id) 从 store
    重建——状态住在 Redis/dict 和 MySQL 里，服务本身无状态才能横向扩
  - 为什么不用 v4_demo 的 store_turn：它写死了模块级 SESSION_ID，
    服务要多会话，写入必须带请求自己的 session_id
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import HOST, LOG_LEVEL, LLM_RETRIES, LLM_RETRY_DELAY, PORT
from llm import chat
from sentence_transformers import SentenceTransformer
from v3_hybrid import BM25, hybrid_search
from v3_m3 import load
from v3_m4 import K, MODEL_PATH, SYSTEM_PROMPT, build_context
from v4_db import FinDB
from v4_demo import PRODUCT_WORDS, memory_text
from v4_memory import Memory
from v4_store import make_store
from v5_analysis import run_analysis
from v5_retry import with_retry
from v5_router import route
from v5_observability import inc, new_trace_id, observe, snapshot
from v5_validator import (DEGRADED_ANSWER, run_with_guard, validate_analysis,
                          validate_rag_factory)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("finagent.app")

chat_safe = with_retry(chat, "llm.chat", LLM_RETRIES, LLM_RETRY_DELAY)

# 重资源容器：lifespan 里填，请求里只读
_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起服务时加载一次重资源；停服务时收尾（现在没有需要收尾的）。"""
    store, backend = make_store()
    _state.update(
        store=store,
        backend=backend,
        db=FinDB(),
        model=SentenceTransformer(MODEL_PATH),
    )
    _state["chunk_by_id"], _state["ids"], _state["V"] = load()
    # BM25 索引也是重资源：和向量矩阵一起起服务时建一次（M6 混合检索）
    _state["bm25"] = BM25(
        [_state["chunk_by_id"][cid]["text"] for cid in _state["ids"]],
        _state["ids"])
    logger.info("启动完成 backend=%s db=%s", backend, _state["db"].url)
    yield


app = FastAPI(title="FinAgent V5", lifespan=lifespan)


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str


@app.get("/health")
def health():
    return {"status": "ok", "backend": _state.get("backend"),
            "db": _state["db"].url if "db" in _state else None}


@app.get("/metrics")
def metrics():
    """评测看板数据源：总请求/分路占比/护栏出口三档/延迟，进程内计数。

    重启清零是特性不是缺陷：它度量「本进程活着期间」的行为，一次评测窗口
    正合适；跨天的运营数字归 /stats（MySQL）管，两层数据两种归宿。
    """
    return snapshot()


@app.get("/cite")
def cite(doc: str, page: int):
    """引用点击查原文：返回该 (doc, page) 下的全部 chunk 文本。

    前端引用面板的数据源。纯内存过滤（chunk 才 20 条），不值得上检索；
    doc/page 由 URL 参数直接给出，FastAPI 自动做类型转换。
    """
    chunks = [c for c in _state["chunk_by_id"].values()
              if c["company"] == doc and c["page"] == page]
    return {"doc": doc, "page": page,
            "chunks": [{"chunk_id": c["chunk_id"], "text": c["text"]}
                       for c in chunks]}


@app.get("/")
def index():
    """最简聊天页（static/index.html）——单文件零构建，demo / 录 GIF 用。"""
    return FileResponse("static/index.html")


def _query_with_memory(user_msg: str, memory: Memory) -> str:
    """记忆补全（迁自 v4_demo，逻辑未动）：本轮没点名产品、上下文里有 → 拼回去。"""
    if any(w in user_msg for w in PRODUCT_WORDS):
        return user_msg
    hit = next((w for w in PRODUCT_WORDS if w in memory_text(memory)), None)
    return f"{user_msg} {hit}" if hit else user_msg


def _rag_gen_factory(query: str, hits):
    """造 RAG 路径的生成器：feedback 拼进 prompt = 重试带反馈的落点。"""
    context = build_context(hits, _state["chunk_by_id"])

    def gen(feedback):
        note = f"\n\n（上轮校验反馈：{feedback}）" if feedback else ""
        return chat_safe([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"context:\n{context}\n\n问题：{query}{note}"},
        ])

    return gen


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    trace_id = new_trace_id()
    t0 = time.perf_counter()
    logger.info("[trace=%s][req] user=%s session=%s msg=%r",
                trace_id, req.user_id, req.session_id, req.message)

    memory = Memory(_state["store"], session_id=req.session_id,
                    user_id=req.user_id)
    _state["db"].ensure_user(req.user_id)
    _state["db"].ensure_conversation(req.session_id, req.user_id)

    # ── M1：入口确定性分叉 ──
    route_name, hit = route(req.message)
    logger.info("[trace=%s][route] %s hit=%r", trace_id, route_name, hit)
    inc("chat.total")
    inc("chat." + route_name)      # chat.rag / chat.analysis：分路占比

    if route_name == "analysis":
        gen = lambda feedback: run_analysis(   # noqa: E731
            req.message + (f"\n（上轮校验反馈：{feedback}）" if feedback else ""))
        validate = validate_analysis
    else:
        q = _query_with_memory(req.message, memory)
        logger.info("[trace=%s][memory] 补全 query=%r", trace_id, q)
        hits = hybrid_search(_state["model"], _state["V"], _state["ids"],
                             _state["bm25"], q, k=K)
        gen = _rag_gen_factory(q, hits)
        validate = validate_rag_factory(hits, _state["chunk_by_id"])

    # ── M2：出口质检（不过→带反馈重试1次→降级）──
    answer, problems, attempts = run_with_guard(gen, validate)
    logger.info("[trace=%s][guard] attempts=%d problems=%s",
                trace_id, attempts, problems)
    # 护栏出口三档：一次过 / 重试后过 / 降级拒答——评测看板的三根柱
    if answer == DEGRADED_ANSWER:
        inc("guard.degraded")
    elif attempts > 1:
        inc("guard.retried")
    else:
        inc("guard.first_pass")

    # ── 双写（热 + 冷），带的是本请求自己的 session_id ──
    memory.add_message("user", req.message)
    memory.add_message("assistant", answer)
    _state["db"].append_message(req.session_id, "user", req.message)
    _state["db"].append_message(req.session_id, "assistant", answer)

    observe("chat.seconds", time.perf_counter() - t0)
    return {"route": route_name, "matched": hit, "answer": answer,
            "attempts": attempts, "problems": problems,
            "backend": _state["backend"], "trace_id": trace_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
