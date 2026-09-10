"""V5-M4 HTTP 冒烟 —— 打真部署，不进进程（区别于 v5_smoke.py 的 TestClient）

TestClient 验的是代码；本文件验的是部署：容器里起的服务、真 Redis/MySQL、
跨进程 HTTP。三组断言：
  1. /health 显示真库后端（redis:// + mysql，不再是 dict/sqlite 降级）
  2. RAG 两轮：第二轮不点名产品，验记忆补全跨请求真的活着（Redis 里）
  3. analysis：MCP 子进程在容器里 spawn 得起来

用法：docker compose up -d 起服务后，在宿主机跑本文件。
"""
import sys

import httpx

BASE = "http://127.0.0.1:8000"

# trust_env=False：不打本机服务不该走系统代理（httpx 默认信 HTTP_PROXY 环境变量，
# 会把 127.0.0.1 也发给代理 → 拿回代理的错误页）
with httpx.Client(timeout=180, trust_env=False) as c:
    print("=== /health ===")
    r = c.get(f"{BASE}/health")
    print(r.status_code, r.json())
    assert "redis://" in r.json()["backend"], f"Redis 没连上：{r.json()['backend']}"
    assert "mysql" in r.json()["db"], f"MySQL 没连上：{r.json()['db']}"

    print("\n=== RAG 第 1 轮（点名产品）===")
    r = c.post(f"{BASE}/chat", json={
        "user_id": "u_http", "session_id": "s_http_1",
        "message": "我想申请安居贷，先介绍一下"})
    body = r.json()
    print(r.status_code, "route=", body["route"], "attempts=", body["attempts"])
    print(body["answer"][:150])
    assert r.status_code == 200 and body["route"] == "rag"

    print("\n=== RAG 第 2 轮（不点名，验 Redis 记忆补全跨请求）===")
    r = c.post(f"{BASE}/chat", json={
        "user_id": "u_http", "session_id": "s_http_1",
        "message": "它的首付比例和额度是多少"})
    body = r.json()
    print(r.status_code, "route=", body["route"], "attempts=", body["attempts"])
    print(body["answer"][:150])
    assert r.status_code == 200 and "[anju_loan" in body["answer"], \
        f"记忆补全疑似没生效，答非安居贷：{body['answer'][:100]}"

    print("\n=== analysis（MCP 工具循环，容器内子进程）===")
    r = c.post(f"{BASE}/chat", json={
        "user_id": "u_http", "session_id": "s_http_2",
        "message": "贵州茅台的股价怎么样"})
    body = r.json()
    print(r.status_code, "route=", body["route"], "attempts=", body["attempts"])
    print(body["answer"][:150])
    assert r.status_code == 200 and body["route"] == "analysis"

print("\nHTTP 冒烟全过：compose 三容器 + 真库双写 + 跨进程记忆 + 容器内 MCP")
sys.exit(0)
