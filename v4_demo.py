"""V4-M4 集成 demo —— 一条带记忆、会持久化、能调 MCP 的对话

把 V1-V4 焊成一体展示：
  - 记忆（M1）：profile 画像增量写、chat_history 滚动摘要、跨轮不丢上文
  - 持久化（M2）：每轮热(memory)+冷(FinDB)双写
  - MCP（M3）：查股价走 get_stock_info 工具
  - RAG（V3）：产品规则问答走检索→context→[Px] 引用硬校验

关键架构选择：
  记忆不塞进生成 prompt，只用来**补全检索 query**——上一轮确认的产品名 + 画像身份
  拼进本轮检索词，解决"那利率多少"这类指代。记忆帮召回，不污染生成。
  这里 if 股价→MCP 只是 demo 分发脚本；正式 Task Router 是 V5 的活，不混进 V4。
"""
import json
import re

from sentence_transformers import SentenceTransformer

from llm import chat
from v3_m3 import load, search
from v3_m4 import (K, MODEL_PATH, SYSTEM_PROMPT, build_context, check_citations)
from v4_db import FinDB
from v4_mcp_client import get_stock_via_mcp
from v4_memory import Memory, maybe_roll_summary
from v4_store import make_store

RESULTS_FILE = "v4_demo_result.txt"
USER_ID = "u-wangming"
SESSION_ID = "sess-003"

# 记忆补全要认的产品词：user/assistant/画像/摘要里谁出现过，就把它带回本轮 query
PRODUCT_WORDS = ["安居贷", "安居", "乐享贷", "乐享", "兴旺贷", "兴旺"]

PROFILE_SYSTEM = (
    "你是用户画像抽取器。从用户这句话抽取能长期记住的事实，只输出 JSON，格式："
    '{"name": "", "scene": ""}（scene 取值如：首套购房者/二套购房者/企业主）。'
    "没有的字段留空字符串，不要编造。"
)


def extract_profile(user_msg: str) -> dict:
    """用 LLM 从用户第一句话抽画像字段，解析失败就返回空（不炸流程）。"""
    try:
        raw = chat([
            {"role": "system", "content": PROFILE_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0))
        return {k: v for k, v in data.items() if v}
    except Exception:
        return {}


def memory_text(memory: Memory) -> str:
    """把画像 + 摘要 + 最近对话拼成一段文本，供产品词扫描用。"""
    chunks = [m["content"] for m in memory.recent(6)]
    chunks += list(memory.profile().values())
    if memory.summary():
        chunks.append(memory.summary())
    return " ".join(chunks)


def query_with_memory(user_msg: str, memory: Memory) -> str:
    """记忆补全：本轮问题里没有产品词，但上下文/画像里有 → 把它拼回去。"""
    if any(w in user_msg for w in PRODUCT_WORDS):
        return user_msg  # 已点名产品，不需要补
    hit = next((w for w in PRODUCT_WORDS if w in memory_text(memory)), None)
    return f"{user_msg} {hit}" if hit else user_msg


def rag_answer(model, chunk_by_id, ids, V, query):
    """V3 链路原样复用：检索 → context → LLM → 引用硬校验。"""
    hits = search(model, V, ids, query, k=K)
    context = build_context(hits, chunk_by_id)
    answer = chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"context:\n{context}\n\n问题：{query}"},
    ])
    bad = check_citations(answer, hits, chunk_by_id)
    return hits, answer, bad


def store_turn(memory, db, role, content):
    """热+冷双写一条消息；返回本轮写入后是否触发了滚动摘要。"""
    memory.add_message(role, content)
    db.append_message(SESSION_ID, role, content)
    return maybe_roll_summary(memory, chat, keep=3)


def main():
    store, backend = make_store()
    db = FinDB()
    db.ensure_user(USER_ID, name="王明")
    db.ensure_conversation(SESSION_ID, USER_ID, title="V4 集成演示")

    chunk_by_id, ids, V = load()
    model = SentenceTransformer(MODEL_PATH)
    memory = Memory(store, session_id=SESSION_ID, user_id=USER_ID)

    out = []
    def log(s=""):
        print(s)
        out.append(s)

    log(f"记忆后端: {backend}   数据库: {db.url}")
    log("=" * 72)

    turns = [
        "我叫王明，是首套购房者，想申请安居贷，首付和额度是多少",
        "那利率是多少",
        "帮我查一下 600519 贵州茅台的股价",
        "提前还款收不收违约金",
    ]

    for i, user_msg in enumerate(turns, 1):
        log(f"\n—— 第{i}轮 ——")
        log(f"用户: {user_msg}")

        # 第 1 轮顺带抽画像（增量写 profile，后续轮不重复抽）
        if i == 1:
            facts = extract_profile(user_msg)
            if facts:
                memory.update_profile(**facts)
                log(f"[记忆] 抽取画像: {facts}")

        if re.search(r"股价|行情", user_msg):
            log("→ 路由: MCP 工具路径（demo 分发，正式 Router 在 V5）")
            tool_result = get_stock_via_mcp("600519")
            log(f"[MCP] get_stock_info → {tool_result}")
            answer = f"已通过财经数据工具 get_stock_info 查到行情：{tool_result}"
            bad = []
        else:
            q = query_with_memory(user_msg, memory)
            if q != user_msg:
                log(f"[记忆] 补全检索 query: 「{user_msg}」→「{q}」(上下文提到过产品)")
            hits, answer, bad = rag_answer(model, chunk_by_id, ids, V, q)
            log(f"检索命中: {[cid for _, cid in hits]}")

        log(f"助理: {answer}")
        if bad:
            log(f"⚠ 编造引用 {len(bad)} 处: {bad} —— 本轮打回")

        # 双写 + 滚动摘要（第 3 轮后历史到 6 条触发一次）
        store_turn(memory, db, "user", user_msg)
        rolled = store_turn(memory, db, "assistant", answer)
        if rolled:
            log(f"[记忆] 历史超阈值 → 滚动摘要更新（当前历史 {memory.history_len()} 条）")

    log("\n" + "=" * 72)
    log("—— 收尾核对 ——")
    log(f"画像: {memory.profile()}")
    log(f"滚动摘要: {memory.summary()}")
    log(f"冷端可查: 会话 {SESSION_ID} 共 "
        f"{len(db.messages_of(SESSION_ID))} 条消息落库 "
        f"(conversations 行: {len(db.conversations_of(USER_ID))})")
    log(f"热端最近 2 条: {[(m['role'], m['content'][:20]) for m in memory.recent(2)]}")

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
