"""V4-M2 极简 MySQL —— 结构化冷存储 users / conversations / messages 三张表

Redis（热）与 MySQL（冷）的分工（拷问主线：数据模型匹配理由）：
  Redis 键值高速，但答不了"某用户最近 10 段会话"这种关系查询；
  关系库用外键把 user → conversation → message 串成树，回答"谁在什么时候说过什么"。
  所以：会话语义结构存 MySQL（冷、可查、跨会话），会话高频存取走 Redis（热、快）。
  写入是双写（编排层同时写两端），读优先 Redis，Redis 没有才回源 MySQL——
  面试口径一句话：热数据 Redis、结构化数据 MySQL，各用所长。

边界（路线图锁死）：三张表即可，不做索引优化 / 分库 / 迁移。
demo 环境没有 MySQL 服务 → DATABASE_URL 默认 sqlite:///finagent.db 顶着跑；
SQLAlchemy engine 抽象下，换 mysql+pymysql://user:pass@host:3306/finagent 就是真 MySQL，
业务代码一行不用改（拷问点：engine 一层把"换库"变成换一个 URL）。
"""
import os
from datetime import datetime, timezone

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import (declarative_base, relationship, selectinload,
                            sessionmaker)

Base = declarative_base()


def _now():
    # 统一存 UTC，展示层再转本地——避免不同时区写进库的时间口径不一致
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), unique=True, nullable=False)   # 与 Redis profile 的 user 同源
    name = Column(String(64))
    created_at = Column(DateTime, default=_now)

    conversations = relationship("Conversation", back_populates="user")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, nullable=False)  # 与 Redis chat_history 的 session 同源
    user_id = Column(String(64), ForeignKey("users.user_id"), nullable=False)
    title = Column(String(128))
    created_at = Column(DateTime, default=_now)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("conversations.session_id"), nullable=False)
    role = Column(String(16), nullable=False)      # user / assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)

    conversation = relationship("Conversation", back_populates="messages")


class FinDB:
    """三表的最小 CRUD 门面：上层只调 ensure_*/append/query，不碰 session 细节。"""

    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("DATABASE_URL", "sqlite:///finagent.db")
        # pool_pre_ping：从池里取连接前先 ping 一下，死连接（MySQL 隔夜掐线）
        # 自动丢弃重连——上线后第一个隔夜请求踩到的 "MySQL server has gone away"。
        # pool_recycle：连接最多活 1 小时主动换新，抢在 wait_timeout 前面。
        self.engine = create_engine(self.url, future=True,
                                    pool_pre_ping=True, pool_recycle=3600)
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)

    def ensure_user(self, user_id: str, name: str | None = None) -> User:
        """用户不存在就建，存在就返回——幂等，重复跑不炸。"""
        with self._Session() as s:
            u = s.query(User).filter_by(user_id=user_id).first()
            if u is None:
                u = User(user_id=user_id, name=name)
                s.add(u)
                s.commit()
            elif name and not u.name:
                u.name = name
                s.commit()
            return u

    def ensure_conversation(self, session_id: str, user_id: str,
                            title: str | None = None) -> Conversation:
        with self._Session() as s:
            c = s.query(Conversation).filter_by(session_id=session_id).first()
            if c is None:
                c = Conversation(session_id=session_id, user_id=user_id, title=title)
                s.add(c)
                s.commit()
            return c

    def append_message(self, session_id: str, role: str, content: str) -> Message:
        """冷端也存一条——编排层负责"热 Redis + 冷 MySQL"双写。"""
        with self._Session() as s:
            m = Message(session_id=session_id, role=role, content=content)
            s.add(m)
            s.commit()
            return m

    def messages_of(self, session_id: str) -> list[Message]:
        with self._Session() as s:
            return (s.query(Message).filter_by(session_id=session_id)
                    .order_by(Message.id).all())

    def conversations_of(self, user_id: str) -> list[Conversation]:
        with self._Session() as s:
            # selectinload：session 还开着就把每条会话的 messages 一次查出来，
            # 否则返回后再访问 c.messages 会触发懒加载 → session 已关 → DetachedInstanceError
            return (s.query(Conversation)
                    .options(selectinload(Conversation.messages))
                    .filter_by(user_id=user_id)
                    .order_by(Conversation.id).all())
