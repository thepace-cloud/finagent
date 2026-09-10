"""V5-M3 冒烟测试 —— TestClient 打三条：health / 工具路径 / RAG 路径

为什么值得留档：一条请求打穿 Router → 路径 → Validator → 双写全链路，
这是「服务化集成跑通」的可审计证据（对齐 v4_demo_result.txt 的传统）。
"""
import json

from fastapi.testclient import TestClient

from v5_app import app

with TestClient(app) as client:   # with = 触发 lifespan（加载模型等重资源）
    print("=== /health ===")
    r = client.get("/health")
    print(r.status_code, r.json())

    print("\n=== /chat 工具路径（股价 → MCP）===")
    r = client.post("/chat", json={
        "user_id": "u-smoke", "session_id": "v5-smoke-1",
        "message": "帮我查一下 600519 贵州茅台的股价"})
    print(r.status_code)
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))

    print("\n=== /chat RAG 路径（产品规则 + 引用校验）===")
    r = client.post("/chat", json={
        "user_id": "u-smoke", "session_id": "v5-smoke-1",
        "message": "安居贷的首付比例和额度是多少"})
    print(r.status_code)
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
