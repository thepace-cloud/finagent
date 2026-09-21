"""V5 可观测性 —— trace id + 进程内计数器 + 延迟计时：请求的「行车记录仪」

为什么要有这个文件（拷问主线）：
  某条回答被降级了，要能回答三个问题：是哪条请求？走了哪条路？护栏拦了几次？
  没有 trace id 的日志是一盘散沙——四行日志摆在那，串不到同一次请求上。
  计数器则把「评测窗口内的行为」变成可引用的数字：一次通过率、降级率、
  平均延迟——设计文档和 /metrics 看板的数据源。

设计决策（拷问点）：
  - 计数放进程内存，不放 Redis/MySQL：它度量「本进程活着期间」的行为，
    重启清零反而符合语义（一次评测一个进程）；跨天的运营数字是 /stats
    （MySQL）的职责——两层数据两种归宿，不混
  - 不用 prometheus_client：JSON 直读直演示，评委 curl 一下就能看到数字；
    零依赖、零框架是本项目的差异点
  - 必须加锁：FastAPI 的 def 端点跑在线程池里，是真并发——共享 dict
    不加锁计数会丢（读-改-写不是原子的）
  - trace id 取 uuid4 的前 8 位 hex：碰撞概率 1/43 亿，日志场景够用；
    不用全 32 位是因为太长，人眼 grep 不友好
"""
import threading
import uuid
from datetime import datetime

_lock = threading.Lock()
_counters = {}                     # 名字 -> 次数
_timers = {}                       # 名字 -> {count, sum, max}
_started_at = datetime.now().astimezone()


def new_trace_id() -> str:
    """8 位 hex：一次请求的身份号，日志四行靠它串成一条线。"""
    return uuid.uuid4().hex[:8]


def inc(name: str, n: int = 1) -> None:
    """计数器 +n。名字用点分层级（chat.total / guard.degraded）。"""
    with _lock:
        _counters[name] = _counters.get(name, 0) + n


def observe(name: str, seconds: float) -> None:
    """延迟观测：记次数、总耗时、最大值——平均值 = sum/count，快照时算。"""
    with _lock:
        t = _timers.setdefault(name, {"count": 0, "sum": 0.0, "max": 0.0})
        t["count"] += 1
        t["sum"] += seconds
        t["max"] = max(t["max"], seconds)


def snapshot() -> dict:
    """给 /metrics 的只读快照：拷贝着返回，调用方拿到的是定格照片。"""
    with _lock:
        timers = {
            name: {
                "count": t["count"],
                "avg": round(t["sum"] / t["count"], 3) if t["count"] else 0.0,
                "max": round(t["max"], 3),
            }
            for name, t in _timers.items()
        }
        return {
            "started_at": _started_at.isoformat(timespec="seconds"),
            "counters": dict(_counters),
            "timers": timers,
        }


if __name__ == "__main__":
    # 自测不依赖 FastAPI：三件套各走一遍（确定性测试确定性代码）
    inc("chat.total", 2)
    inc("chat.rag")
    observe("chat.seconds", 1.5)
    observe("chat.seconds", 0.5)
    snap = snapshot()
    assert snap["counters"] == {"chat.total": 2, "chat.rag": 1}
    t = snap["timers"]["chat.seconds"]
    assert t["count"] == 2 and t["avg"] == 1.0 and t["max"] == 1.5
    snap2 = snapshot()
    assert snap2 == snap, "快照必须是只读的：再拍一张不该有变化"
    print("可观测性自测通过：", snap)
