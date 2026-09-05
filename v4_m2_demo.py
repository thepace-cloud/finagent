"""V4-M2 demo：热/冷双写 + 关系查询读回

同一段对话：
  - 热端：Memory（chat_history）—— 会话中高频读
  - 冷端：FinDB（messages 表）—— 跨会话可查
写完两边各读一遍对照，再演示关系查询：列出该用户的所有会话。
"""
from v4_db import FinDB
from v4_memory import Memory
from v4_store import make_store


def main():
    store, backend = make_store()
    print(f"记忆后端: {backend}")

    db = FinDB()
    print(f"数据库  : {db.url}\n")

    user_id, session_id = "u-wangming", "sess-001"
    db.ensure_user(user_id, name="王明")
    db.ensure_conversation(session_id, user_id, title="贷款咨询")

    mem = Memory(store, session_id=session_id, user_id=user_id)
    turns = [
        ("user", "我想了解首套房贷款"),
        ("assistant", "安居贷覆盖首套，额度最高八成（[anju_loan P2]）"),
        ("user", "那利率多少"),
        ("assistant", "首套基准 3.95%，优质客户可下浮（[anju_loan P2]）"),
    ]
    for role, content in turns:
        mem.add_message(role, content)     # 热：写 Redis 语义的 chat_history
        db.append_message(session_id, role, content)  # 冷：写 MySQL 语义的 messages

    print("—— 热端读（memory.recent）——")
    for m in mem.recent():
        print(f"  {m['role']:>9}: {m['content']}")

    print("\n—— 冷端读（messages_of）——")
    for m in db.messages_of(session_id):
        print(f"  #{m.id:>3} {m.role:>9} @{m.created_at:%H:%M:%S}: {m.content}")

    print("\n—— 关系查询：该用户的所有会话 ——")
    for c in db.conversations_of(user_id):
        n = len(c.messages)
        print(f"  {c.session_id} | {c.title} | {n} 条消息 | 创建于 {c.created_at:%m-%d %H:%M}")


if __name__ == "__main__":
    main()
