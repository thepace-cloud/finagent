"""M4b 验收探针 —— 滚动摘要接线 + 检索/对比/流式回归（本地/线上通用）

用法: python -X utf8 v5_m4b_probe.py http://47.95.222.61:8000 [--save]

背景：本波原本给检索加查询同义扩展，评测闸门（13/16 持平）+ 控制实验
（真实问法 top-3 无变化）证伪后已回滚（v5_qexpand.py 留档）。保留下来的
改动是滚动摘要接线——v4 建好的机制服务端一直没接，summary key 永远是空的。

五连探：
  1. expand() 单元三查：命中拼词 / 无命原件原样 / 已有词不重拼（纯函数留档自检）
  2. 滚动摘要：同会话连聊 5 轮 → /history total=6 而非 10——第 4 轮末
     （8 条）把最旧 4 条压进 summary 并裁掉；新最旧条应是第 3 问（安居贷利率）
  3. RAG 回归：乐享贷申请条件 → route=rag + 引用 [lexiang_loan + 护栏一次过
     （attempts=1、problems 空）——滚动摘要接线后主链路依旧首答即合格
  4. compare 路由回归：年龄对比双产品 → route=compare + 双侧引用
     （分产品子索引路径，不受单索引稀释影响）
  5. 流式回归：「优惠」问安居贷 → SSE 出字到 done + 全文引用 [anju_loan
"""
import json
import sys
import time

import requests

from v5_qexpand import expand

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
SAVE = "--save" in sys.argv
U = "m4b_probe"

results = {"base": BASE, "probes": []}
all_ok = True


def probe(name, fn):
    global all_ok
    ok, detail = fn()
    all_ok &= ok
    results["probes"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'✓' if ok else '✗'} {name}: {detail}")


def p1_expand_unit():
    a = expand("对借款人年龄的要求")            # 命中「年龄」→ 拼「周岁」
    b = expand("提前还款有违约金吗")            # 无命中 → 原样返回
    c = expand("18周岁至60周岁的年龄范围")       # 扩展词已在 → 不重拼
    ok = (a == "对借款人年龄的要求 周岁" and b == "提前还款有违约金吗"
          and c == "18周岁至60周岁的年龄范围")
    return ok, (f"命中拼词: {a!r} | 无命中原样: {b == '提前还款有违约金吗'}"
                f" | 已有词不重拼: {c == '18周岁至60周岁的年龄范围'}")


def p2_rolling_summary():
    sid = f"m4b_roll_{int(time.time())}"        # 每次全新会话，历史从零起
    qs = ["兴旺贷的额度范围是多少？", "乐享贷的期限有哪些？",
          "安居贷的利率是多少？", "提前还款有违约金吗？", "兴旺贷需要什么申请条件？"]
    for q in qs:
        r = requests.post(f"{BASE}/chat", timeout=120, json={
            "user_id": U, "session_id": sid, "message": q})
        r.raise_for_status()
    h = requests.get(f"{BASE}/history", timeout=10,
                     params={"user_id": U, "session_id": sid}).json()
    m = h["messages"]
    # 5 轮 = 10 条原始；第 4 轮末 8 条触发 roll（压掉最旧 4 条）→ 第 5 轮末 6 条，
    # 剩余窗口 [q3,a3,q4,a4,q5,a5]——新最旧条是第 3 问（安居贷利率）
    rolled = h["total"] == 6 and len(m) == 6
    chronological = (m[0]["role"] == "user"
                     and "安居贷" in m[0]["content"]
                     and m[-1]["role"] == "assistant")
    return rolled and chronological, (f"total={h['total']}（10=没滚/6=已滚）"
                                      f" 新最旧条=第3问安居贷={'安居贷' in m[0]['content']}"
                                      f" 时序末条=assistant={m[-1]['role'] == 'assistant'}")


def p3_rag_regression():
    r = requests.post(f"{BASE}/chat", timeout=90, json={
        "user_id": U, "session_id": f"m4b_rag_{int(time.time())}",
        "message": "乐享贷的申请条件是什么？"})
    d = r.json()
    cited = "[lexiang_loan" in d.get("answer", "")
    clean = d.get("attempts") == 1 and not d.get("problems")
    return (r.status_code == 200 and d.get("route") == "rag" and cited
            and clean), (f"HTTP {r.status_code} route={d.get('route')} "
                         f"引用[lexiang_loan={cited} 护栏一次过={clean}")


def p4_compare_regression():
    r = requests.post(f"{BASE}/chat", timeout=120, json={
        "user_id": U, "session_id": f"m4b_cmp_{int(time.time())}",
        "message": "兴旺贷和乐享贷哪个对借款人年龄的要求更宽松？"})
    d = r.json()
    ans = d.get("answer", "")
    both = "[xingwang_loan" in ans and "[lexiang_loan" in ans
    return (r.status_code == 200 and d.get("route") == "compare" and both), \
        f"HTTP {r.status_code} route={d.get('route')} 双侧引用={both}"


def p5_stream_expand_g05():
    r = requests.post(f"{BASE}/chat/stream", timeout=120, stream=True, json={
        "user_id": U, "session_id": f"m4b_g05_{int(time.time())}",
        "message": "安居贷的利率有优惠吗？"})
    route, text, done = "", "", False
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            ev = json.loads(line[6:])
            if ev["type"] == "meta":
                route = ev["route"]
            elif ev["type"] == "delta":
                text += ev["text"]
            elif ev["type"] == "done":
                done = True
                break
    r.close()
    cited = "[anju_loan" in text
    return (r.status_code == 200 and route == "rag" and done and cited), \
        f"HTTP {r.status_code} route={route} done={done} 引用[anju_loan={cited}"


t0 = time.time()
probe("expand单元三查(留档自检)", p1_expand_unit)
probe("滚动摘要(5轮→total=6)", p2_rolling_summary)
probe("RAG回归(乐享贷+护栏一次过)", p3_rag_regression)
probe("compare路由回归(双产品年龄)", p4_compare_regression)
probe("流式回归(安居贷利率优惠)", p5_stream_expand_g05)

results["verdict"] = "PASS" if all_ok else "FAIL"
results["elapsed_s"] = round(time.time() - t0, 1)
print(f"\nM4b 探针结论: {results['verdict']}（{results['elapsed_s']}s）")

if SAVE:
    with open("probe_m4b_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("已落档 probe_m4b_result.json")
