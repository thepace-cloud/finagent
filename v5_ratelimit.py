"""V5-M3.5 IP 限流 —— 滑动窗口，公网无鉴权演示服务的防烧钱闸门

为什么需要：服务公网裸奔（IP 直连、无登录），/chat 每次调用都烧 DeepSeek
额度。访问日志里已有云厂商扫描段（34.x/66.x/199.x）在敲门——真被脚本
扫到刷接口，烧的是真钱。加一道每 IP 滑动窗口，正常人类演示永远碰不到，
脚本洪水第一时间被掐。

为什么是进程内存而不是 Redis：限流和 /metrics 同一哲学——度量「本进程
存活期间」的行为，重启清零可接受；真要多实例部署再换 Redis 共享计数
（留决赛）。内存占用有界：每 IP 最多存 limit 个时间戳。

滑动窗口 vs 固定窗口：固定窗口在窗口边界会放过 2×limit 的突发（前窗
尾 + 后窗头）；滑动窗口看「过去 60s 内有几个时间戳」，没有边界漏洞。
代价是每 IP 存时间戳列表——演示规模下完全可忽略。
"""
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request


class RateLimiter:
    """每 IP 滑动窗口限流器。check 作为 FastAPI 依赖注入（自动拿到 Request）。"""

    def __init__(self, limit: int, window_s: float = 60.0, label: str = ""):
        self.limit = limit
        self.window_s = window_s
        self.label = label
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()   # FastAPI 同步端点跑线程池，deque 修剪+判长+追加
                               # 是三步非原子操作，必须整体持锁

    def check(self, request: Request):
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            q = self._hits[ip]
            while q and q[0] <= now - self.window_s:   # 窗口外的时间戳出队
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁（{self.label}每 IP 每分钟限 "
                           f"{self.limit} 次），请稍后再试",
                    headers={"Retry-After": "10"})
            q.append(now)


# 两档：贵的管紧（LLM 调用），便宜的管松（零 LLM，只防脚本洪水）
chat_limiter = RateLimiter(20, label="对话")
light_limiter = RateLimiter(60, label="测评")
