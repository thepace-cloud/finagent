"""V4 存储后端抽象 —— 对上层暴露最小 KV 接口，真 Redis 与进程内 dict 都能跑。

为什么要有这层：
  记忆层（v4_memory）只关心"往 key 里 push 一条 / 读最近 N 条 / 写画像字段"，
  不关心背后是 Redis 还是内存。接口命令语义对齐 redis-py（rpush/lrange/ltrim/hset...），
  这样本机没有 Redis 服务时降级成 dict 跑通 demo，设计口径 = 代码按真 Redis 写、
  生产环境一行 REDIS_URL 切过去，不需要改记忆层一行。

Redis 命令对照（冷知识可复盘）：
  rpush  往 LIST 尾部塞元素        lrange(key, 0, -1) 取整条
  ltrim  只保留区间内的元素        hset/hgetall 管 HASH（画像就是一条 HASH）
  set/get 管 STRING（滚动摘要就是一条 STRING）
"""
import os

try:
    import redis as _redis
except ImportError:  # redis-py 没装：直接降级，不炸
    _redis = None


class Store:
    """接口基类。每个方法语义和 redis-py 同名命令一致。"""

    def rpush(self, key, *values): raise NotImplementedError
    def lrange(self, key, start, end): raise NotImplementedError
    def ltrim(self, key, start, end): raise NotImplementedError
    def llen(self, key): raise NotImplementedError
    def hset(self, key, mapping): raise NotImplementedError
    def hgetall(self, key): raise NotImplementedError
    def set(self, key, value): raise NotImplementedError
    def get(self, key): raise NotImplementedError
    def delete(self, key): raise NotImplementedError


class RedisStore(Store):
    """真 Redis：每个方法直接转发给 redis-py（decode_responses=True 拿回 str）。"""

    def __init__(self, url=None, host="127.0.0.1", port=6379, db=0):
        # 一条连接从 url 建（from_url 解析密码/选库/协议）；没给 url 才退回默认本机。
        # 上层拿到的就是这一个客户端——不是"探针连了 A、真用连了 B"两条连接。
        if url:
            self._r = _redis.Redis.from_url(url, decode_responses=True)
        else:
            self._r = _redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self._r.ping()  # 连不上立刻抛 ConnectionError，让 make_store 捕获降级

    def rpush(self, key, *values): return self._r.rpush(key, *values)
    def lrange(self, key, start, end): return self._r.lrange(key, start, end)
    def ltrim(self, key, start, end): return self._r.ltrim(key, start, end)
    def llen(self, key): return self._r.llen(key)
    def hset(self, key, mapping): return self._r.hset(key, mapping=mapping)
    def hgetall(self, key): return self._r.hgetall(key)
    def set(self, key, value): return self._r.set(key, value)
    def get(self, key): return self._r.get(key)
    def delete(self, key): return self._r.delete(key)


class DictStore(Store):
    """进程内降级实现：命令语义与 Redis 一致，只是数据不跨进程、进程结束即失。

    文档可说明：这是"接口真、引擎换"，不是假装用了 Redis——
    demo 环境没有服务器，逻辑（三 key 分层、裁剪、滚动）一行没省。
    """

    def __init__(self):
        self._lists = {}
        self._hashes = {}
        self._strings = {}

    def rpush(self, key, *values):
        lst = self._lists.setdefault(key, [])
        lst.extend(values)
        return len(lst)

    def lrange(self, key, start, end):
        lst = self._lists.get(key, [])
        return lst[start:] if end == -1 else lst[start:end + 1]

    def ltrim(self, key, start, end):
        lst = self._lists.get(key, [])
        kept = lst[start:] if end == -1 else lst[start:end + 1]
        if kept:
            self._lists[key] = kept
        else:
            self._lists.pop(key, None)
        return True

    def llen(self, key):
        return len(self._lists.get(key, []))

    def hset(self, key, mapping):
        h = self._hashes.setdefault(key, {})
        h.update(mapping)
        return len(mapping)

    def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    def set(self, key, value):
        self._strings[key] = value
        return True

    def get(self, key):
        return self._strings.get(key)

    def delete(self, key):
        n = sum(1 for k in (key,) if k in self._strings or k in self._hashes or k in self._lists)
        self._strings.pop(key, None); self._hashes.pop(key, None); self._lists.pop(key, None)
        return n


def make_store(redis_url=None):
    """选择后端：给 url（或 REDIS_URL，或默认 127.0.0.1:6379）能连上 → 真 Redis；否则 dict 降级。

    连接只用一条：RedisStore(url=url) 里建的那条，它 ping 通、上层就写它。
    不再先拿一条连接去探活、再另起一条真用——两条不是同一台时，会静默写进错误的后端。
    返回 (store, backend_desc)。backend_desc 打印出来，demo 可审计自己跑在哪个后端上。
    """
    if _redis is None:
        return DictStore(), "dict 降级（redis-py 未安装）"
    url = redis_url or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379"
    try:
        store = RedisStore(url=url)
        return store, url
    except Exception as exc:
        return DictStore(), f"dict 降级（连不上 Redis: {exc.__class__.__name__}）"
