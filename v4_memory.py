"""V4-M1 记忆层 —— Redis 三 key 分层（设计要点：为什么是这三层）

  chat_history:{session_id}   LIST  会话原始历史（JSON 消息）。短期记忆：只留最近窗口，
                                 长度到了就 ltrim 裁掉最旧的——用长度裁剪而不是 TTL，
                                 因为我们要的是"窗口大小"这个语义，不是"过期时间"。
  profile:{user_id}           HASH  用户长期事实画像（name / 身份 / 意向产品…）。
                                 每轮增量写入新事实（hset 只动该字段），不整条重写。
  summary:{user_id}           STRING 压缩后的旧历史。当 chat_history 超阈值，
                                 把最旧一半交给 LLM 压成一段摘要，拼进旧摘要（滚动更新），
                                 然后裁掉那半——这样"能记住的"不随对话变长而无限膨胀。

三层为什么各管一摊（一句话版）：
  原始对话=要原样的近期；画像=跨会话稳定的身份事实；摘要=被压缩的远期——
  三者对"要不要保留细节"的回答不同，所以分三个 key、三种结构。
"""
import json

KEY_HISTORY = "chat_history:{session_id}"
KEY_PROFILE = "profile:{user_id}"
KEY_SUMMARY = "summary:{user_id}"


class Memory:
    def __init__(self, store, session_id: str, user_id: str):
        self._s = store
        self.session_id = session_id
        self.user_id = user_id
        self._history_key = KEY_HISTORY.format(session_id=session_id)
        self._profile_key = KEY_PROFILE.format(user_id=user_id)
        self._summary_key = KEY_SUMMARY.format(user_id=user_id)

    # ---------- chat_history（LIST）----------
    def add_message(self, role: str, content: str):
        """rpush 一条 JSON 消息到会话历史尾部。"""
        self._s.rpush(self._history_key, json.dumps(
            {"role": role, "content": content}, ensure_ascii=False))

    def recent(self, n: int = 6) -> list[dict]:
        """取最近 n 条（lrange 负数窗口），解码回消息 dict。"""
        rows = self._s.lrange(self._history_key, -n, -1)
        return [json.loads(x) for x in rows]

    def history_len(self) -> int:
        return self._s.llen(self._history_key)

    def drop_oldest(self, n: int):
        """裁掉最旧的 n 条——配合滚动摘要，丢的是"已被压缩"的半段。"""
        self._s.ltrim(self._history_key, n, -1)

    # ---------- profile（HASH，长期画像）----------
    def profile(self) -> dict:
        return self._s.hgetall(self._profile_key)

    def update_profile(self, **facts) -> int:
        """增量写入：hset 只更新给出的字段，不动已有字段。"""
        return self._s.hset(self._profile_key, {k: str(v) for k, v in facts.items()})

    # ---------- summary（STRING，滚动摘要）----------
    def summary(self) -> str | None:
        return self._s.get(self._summary_key)

    def set_summary(self, text: str):
        self._s.set(self._summary_key, text)

    # ---------- 拼装给模型的记忆上下文 ----------
    def memory_context(self) -> str:
        """把三层拼成一段可塞进 system 的文本：没有的空段就不出现。"""
        parts = []
        profile = self.profile()
        if profile:
            parts.append("【用户画像】" + "、".join(f"{k}:{v}" for k, v in profile.items()))
        summary = self.summary()
        if summary:
            parts.append(f"【更早对话摘要】{summary}")
        recent = self.recent(4)
        if recent:
            turns = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
            parts.append(f"【最近对话】\n{turns}")
        return "\n".join(parts)


def summarize_block(llm_chat, block: list[dict]) -> str:
    """把一段消息交给 LLM 压成几句要点——摘要写的也是人话，不是截断。"""
    text = "\n".join(f"{m['role']}: {m['content']}" for m in block)
    return llm_chat([
        {"role": "system", "content": "你是会话压缩器。把下面的对话压成 2-3 句要点，"
                                      "保留：用户身份事实、已确认的产品规则、待办。只输出摘要本身。"},
        {"role": "user", "content": text},
    ])


def maybe_roll_summary(memory: Memory, llm_chat, keep: int = 4):
    """滚动摘要（增量更新）：历史超过 2*keep 时，把最旧的 keep 条压缩进摘要再裁掉。

    keep=4 → 历史到 8 条才触发一次，之后永远在 [5, 8] 之间晃——摘要只在阈值
    跨越时更新一次，不是每轮都重算（省钱，也回答了"增量更新"怎么增量）。
    """
    if memory.history_len() < 2 * keep:
        return False
    history = memory.recent(memory.history_len())          # 全量
    oldest = history[:keep]                                # 最旧 keep 条 = 该退休的
    chunk = summarize_block(llm_chat, oldest)
    prev = memory.summary()
    memory.set_summary((prev + "\n" if prev else "") + f"- {chunk}")
    memory.drop_oldest(keep)
    return True
