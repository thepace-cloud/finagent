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
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from config import HOST, LOG_LEVEL, LLM_RETRIES, LLM_RETRY_DELAY, PORT
from llm import chat, chat_stream
from sentence_transformers import SentenceTransformer
from v3_hybrid import BM25, hybrid_search
from v3_m3 import load
from v3_m4 import K, MODEL_PATH, SYSTEM_PROMPT, build_context
from v4_db import FinDB
from v4_demo import PRODUCT_WORDS, memory_text
from v4_memory import Memory
from v4_store import make_store
from v5_analysis import run_analysis
from v5_compare import (COMPARE_SYSTEM_PROMPT, build_compare_indexes,
                        compare_search)
from v5_retry import with_retry
from v5_router import detect_compare, route
from v5_observability import inc, new_trace_id, observe, snapshot
from v5_validator import (DEGRADED_ANSWER, MAX_RETRIES, feedback_text,
                          run_with_guard, validate_analysis,
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
    # 对比路径子索引：每款产品一份小 BM25 + 向量子矩阵（M1 对比落地）
    _state["cmp_idx"] = build_compare_indexes(
        _state["chunk_by_id"], _state["ids"], _state["V"])
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


@app.get("/stats")
def stats():
    """运营看板页：/metrics 数字的可视化门面（static/stats.html）。

    为什么单独一页而不是让评委读 JSON：演示需要一个一眼读懂的入口——
    请求量、路径占比、护栏三档、延迟，数字随提问实时跳动（页内 5 秒自刷）。
    数据口径与 /metrics 完全一致，本页只做展示，不做第二份统计。
    """
    return FileResponse("static/stats.html")


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


def _rag_messages(query: str, hits, feedback=None) -> list[dict]:
    """RAG 路径的 prompt 组装（流式/非流式共用同一配方，防两处漂移）。"""
    context = build_context(hits, _state["chunk_by_id"])
    note = f"\n\n（上轮校验反馈：{feedback}）" if feedback else ""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"context:\n{context}\n\n问题：{query}{note}"},
    ]


def _compare_messages(query: str, hits, feedback=None) -> list[dict]:
    """对比路径的 prompt：与 RAG 同一配方，只换对比系统提示词
    （先直接回答，再 markdown 表格逐维度对照 + 双侧引用 + 未提及如实说）。"""
    context = build_context(hits, _state["chunk_by_id"])
    note = f"\n\n（上轮校验反馈：{feedback}）" if feedback else ""
    return [
        {"role": "system", "content": COMPARE_SYSTEM_PROMPT},
        {"role": "user", "content": f"context:\n{context}\n\n问题：{query}{note}"},
    ]


def _make_gen(messages_fn):
    """生成器工厂（rag/compare 共用）：feedback 拼进 prompt = 重试带反馈的落点。"""
    def gen(feedback):
        return chat_safe(messages_fn(feedback))
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
    elif route_name == "compare":
        # 对比路径：分产品检索结构性保证每款都有座位（修 09-29 探针确诊的
        # top-K 单产品霸占）。不做记忆补全——对比对象由 detect_compare 决定，
        # 不需要从上文借产品名
        companies = detect_compare(req.message)
        logger.info("[trace=%s][compare] companies=%s", trace_id, companies)
        hits = compare_search(_state["model"], _state["cmp_idx"],
                              companies, req.message)
        logger.info("[trace=%s][compare] hits=%s",
                    trace_id, [cid for _, cid in hits])
        gen = _make_gen(lambda fb: _compare_messages(req.message, hits, fb))
        validate = validate_rag_factory(hits, _state["chunk_by_id"])
    else:
        q = _query_with_memory(req.message, memory)
        logger.info("[trace=%s][memory] 补全 query=%r", trace_id, q)
        hits = hybrid_search(_state["model"], _state["V"], _state["ids"],
                             _state["bm25"], q, k=K)
        gen = _make_gen(lambda fb: _rag_messages(q, hits, fb))
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


def _sse(obj: dict) -> str:
    """一条 SSE 事件：`data: 单行 JSON` + 空行 = 协议规定的消息分隔。"""
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@app.post("/chat/stream")
def chat_stream_endpoint(req: ChatRequest):
    """流式版 /chat：SSE 逐段外推，前端边收边上屏（打字机）。

    双端点并存的理由：/chat 契约稳定（评测/联调用），/chat/stream 管体验；
    护栏、双写、可观测性与 /chat 完全对齐，只是运输方式换了。

    为什么 POST + fetch 而不是原生 EventSource：EventSource 只支持 GET
    且带不了 JSON body（SSE 的历史包袱），fetch 流式读是业界主流同款。

    流式 × 护栏（拷问点）：第一遍边流边攒、攒完校验；不过 → retry 事件
    让前端清屏，带反馈重发第二遍（非流式一段 delta，重试是罕见路径）；
    仍不过 → refused 事件带降级文案，前端换红卡。宁拒不错不因流式打折。
    """
    trace_id = new_trace_id()
    t0 = time.perf_counter()
    logger.info("[trace=%s][req] stream user=%s msg=%r",
                trace_id, req.user_id, req.message)

    memory = Memory(_state["store"], session_id=req.session_id,
                    user_id=req.user_id)
    _state["db"].ensure_user(req.user_id)
    _state["db"].ensure_conversation(req.session_id, req.user_id)

    route_name, hit = route(req.message)
    logger.info("[trace=%s][route] %s hit=%r (stream)", trace_id, route_name, hit)
    inc("chat.total")
    inc("chat." + route_name)

    if route_name == "analysis":
        validate = validate_analysis
        msgs_fn = None                            # 工具路径不流式生成，用不到
    elif route_name == "compare":
        # 与 /chat 同一对比配方：分产品检索 + 对比提示词（流式体验不降级）
        companies = detect_compare(req.message)
        logger.info("[trace=%s][compare] companies=%s (stream)",
                    trace_id, companies)
        hits = compare_search(_state["model"], _state["cmp_idx"],
                              companies, req.message)
        validate = validate_rag_factory(hits, _state["chunk_by_id"])
        msgs_fn = lambda fb=None: _compare_messages(req.message, hits, fb)  # noqa: E731
    else:
        q = _query_with_memory(req.message, memory)
        logger.info("[trace=%s][memory] 补全 query=%r (stream)", trace_id, q)
        hits = hybrid_search(_state["model"], _state["V"], _state["ids"],
                             _state["bm25"], q, k=K)
        validate = validate_rag_factory(hits, _state["chunk_by_id"])
        msgs_fn = lambda fb=None: _rag_messages(q, hits, fb)               # noqa: E731

    def events():
        # 事件契约：meta → delta×N → [retry → delta×N] → [refused] → done
        yield _sse({"type": "meta", "route": route_name, "trace_id": trace_id})

        feedback = None
        problems: list = []
        answer = ""
        for attempts in range(1, MAX_RETRIES + 2):     # 与 run_with_guard 同一条纪律
            pieces = []
            if route_name == "analysis":
                # 工具循环是多轮结构化调用，中间没有可流的文本 → 整段一个 delta
                text = run_analysis(
                    req.message + (f"\n（上轮校验反馈：{feedback}）" if feedback else ""))
                pieces = [text]
                yield _sse({"type": "delta", "text": text})
            elif attempts == 1:
                # 首发：流式边发边攒
                for piece in chat_stream(msgs_fn()):
                    pieces.append(piece)
                    yield _sse({"type": "delta", "text": piece})
            else:
                # 重试：罕见路径，非流式一把梭（前端已在 retry 事件时清屏）
                text = chat_safe(msgs_fn(feedback))
                pieces = [text]
                yield _sse({"type": "delta", "text": text})
            answer = "".join(pieces)
            problems = validate(answer)
            if not problems:
                break
            if attempts <= MAX_RETRIES:                # 还有重试名额才预告重试
                yield _sse({"type": "retry",
                            "problems": [str(p) for p in problems]})
                feedback = feedback_text(problems)

        refused = bool(problems)
        if refused:
            answer = DEGRADED_ANSWER
            yield _sse({"type": "refused", "text": answer,
                        "problems": [str(p) for p in problems]})
        logger.info("[trace=%s][guard] stream attempts=%d refused=%s problems=%s",
                    trace_id, attempts, refused, problems)

        # 收尾三件事与 /chat 完全一致：护栏计数 → 双写 → 计时
        if refused:
            inc("guard.degraded")
        elif attempts > 1:
            inc("guard.retried")
        else:
            inc("guard.first_pass")
        memory.add_message("user", req.message)
        memory.add_message("assistant", answer)
        _state["db"].append_message(req.session_id, "user", req.message)
        _state["db"].append_message(req.session_id, "assistant", answer)
        observe("chat.seconds", time.perf_counter() - t0)
        yield _sse({"type": "done", "attempts": attempts, "refused": refused,
                    "route": route_name})

    return StreamingResponse(events(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
