"""V4-M1 demo：验证记忆层三 key 机制本身（还没接 RAG 主循环）

跑 8 轮假对话，观察：
  1. chat_history 增长到阈值触发滚动摘要 → 最旧半段压缩进 summary 后被裁掉；
  2. profile 增量写入：同一个 user 新开 session，画像还在（跨会话长期）；
  3. 运行在什么后端（真 Redis / dict 降级）会打出来。
"""
from llm import chat
from v4_memory import Memory, maybe_roll_summary
from v4_store import make_store


def main():
    store, backend = make_store()
    print(f"后端: {backend}\n")

    mem = Memory(store, session_id="sess-001", user_id="u-wangming")
    mem.update_profile(name="王明", identity="首套购房者")

    turns = [
        "我想了解首套房贷款",
        "首付能贷几成",
        "那利率是多少",
        "贷款期限最长几年",
        "还款方式有哪些",
        "提前还款麻烦吗",
        "逾期会怎么样",
        "材料要准备什么",
    ]
    # 每轮给个假的 assistant 回复，只测记忆不测回答质量
    fake_reply = "（本轮答复要点……）"

    for i, q in enumerate(turns, 1):
        mem.add_message("user", q)
        mem.add_message("assistant", fake_reply)
        rolled = maybe_roll_summary(mem, chat, keep=4)
        print(f"第{i:>2}轮后 | 历史条数={mem.history_len():>2} | "
              f"{'触发滚动摘要 → summary 更新' if rolled else ''}")

    print(f"\n滚动后 summary: {mem.summary()}")
    print(f"画像: {mem.profile()}")

    # 新会话、同一用户：画像跨会话还在（长期事实不随会话结束而丢）
    mem2 = Memory(store, session_id="sess-002", user_id="u-wangming")
    print(f"\n新会话 sess-002 读同一用户画像: {mem2.profile()}")
    print(f"新会话的记忆上下文:\n{mem2.memory_context()}")


if __name__ == "__main__":
    main()
