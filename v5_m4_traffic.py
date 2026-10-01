"""M4 截图前造流量 —— 给 /metrics 喂 20+ 条真实请求，看板数字有血有肉

用法: python -X utf8 v5_m4_traffic.py http://47.95.222.61:8000

为什么存在：/metrics 是进程内计数（重启清零是特性——度量本进程存活期间）。
截图前跑一遍，看板呈现：总请求 20+、三路径占比全有值、测评次数、护栏三档。
全部是真实链路请求（RAG 走检索+生成+校验），不是刷数字的假调用。

注意：中途部署重启过容器就重跑一遍（计数清零）。
"""
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://47.95.222.61:8000"

# 贷款小白口吻，贴近前端快捷问题——截图里的历史记录本身也是演示素材
RAG_QS = [
    "安居贷的申请条件是什么？",
    "乐享贷最多能借多少？",
    "兴旺贷的期限有哪些选择？",
    "安居贷利率是多少？",
    "乐享贷需要什么申请材料？",
    "兴旺贷对经营年限有要求吗？",
    "安居贷的年龄限制是多少？",
    "乐享贷可以提前还款吗？",
    "兴旺贷的额度范围是多少？",
    "安居贷最长能贷多少年？",
]
CMP_QS = [
    "安居贷和乐享贷的申请条件有什么区别？",
    "这几款贷款哪个年龄限制更宽松？",
    "兴旺贷和安居贷的利率差别大吗？",
]
ANA_QS = [
    "查一下贵州茅台的股价",
    "贷款100万，年利率4.75%，30年，月供是多少？",
]
ASSESS_ANSWERS = [
    {"purpose": "buy", "age": "mid", "term": "over5", "amount": "w100_300"},
    {"purpose": "business", "age": "mid", "term": "y1_3", "amount": "w20_100",
     "biz_years": "ge2"},
]

ok = fail = 0


def hit(name, fn):
    global ok, fail
    try:
        fn()
        ok += 1
        print(f"✓ {name}")
    except Exception as e:
        fail += 1
        print(f"✗ {name}: {e}")


def chat(sid, msg):
    r = requests.post(f"{BASE}/chat", timeout=90, json={
        "user_id": "demo_traffic", "session_id": sid, "message": msg})
    r.raise_for_status()
    assert r.json().get("answer"), "空回答"


def assess(answers):
    r = requests.post(f"{BASE}/assess", timeout=30, json={"answers": answers})
    r.raise_for_status()
    assert r.json().get("products"), "空结果"


t0 = time.time()
for i, q in enumerate(RAG_QS):
    hit(f"rag{i+1} {q[:14]}", lambda q=q, i=i: chat(f"m4rag{i}", q))
for i, q in enumerate(CMP_QS):
    hit(f"cmp{i+1} {q[:14]}", lambda q=q, i=i: chat(f"m4cmp{i}", q))
for i, q in enumerate(ANA_QS):
    hit(f"ana{i+1} {q[:14]}", lambda q=q, i=i: chat(f"m4ana{i}", q))
for i, a in enumerate(ASSESS_ANSWERS):
    hit(f"assess{i+1}", lambda a=a: assess(a))

m = requests.get(f"{BASE}/metrics", timeout=10).json()
c = m["counters"]
print(f"\n完成 {ok} 成功 / {fail} 失败（{round(time.time() - t0)}s）")
print(f"看板口径：chat.total={c.get('chat.total', 0)} "
      f"rag={c.get('chat.rag', 0)} compare={c.get('chat.compare', 0)} "
      f"analysis={c.get('chat.analysis', 0)} assess={c.get('chat.assess', 0)} "
      f"guard 三档 fp={c.get('guard.first_pass', 0)} "
      f"rt={c.get('guard.retried', 0)} dg={c.get('guard.degraded', 0)}")
print("现在可以截图了（聊天页历史 + /stats 看板）。")
