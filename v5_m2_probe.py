"""M2 线上验收探针 —— 本地/线上通用（BASE 用 argv 传入）

用法: python -X utf8 v5_m2_probe.py http://47.95.222.61:8000 [--save]

四连探：
  1. GET  /assess          问卷下发（5 题含条件题、3 产品）
  2. POST /assess 购房青年  推荐安居贷 + 月供估算 + 引用零编造
  3. POST /assess 56岁消费  诚实全拒（宁拒不错在测评路径的形态）
  4. GET  /metrics          chat.assess 计数器在跳
附 1 条 /chat RAG 回归（确认 M2 接线没碰伤主链路）。
"""
import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
SAVE = "--save" in sys.argv
# 语料页锚点（12 块）：引用零编造的判定依据，与语料文件同步
KNOWN_PAGES = {(d, p) for d in
               ("anju_loan", "lexiang_loan", "xingwang_loan")
               for p in (1, 2, 3, 4)}

results = {"base": BASE, "probes": []}
all_ok = True


def probe(name, fn):
    global all_ok
    ok, detail = fn()
    all_ok &= ok
    results["probes"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'✓' if ok else '✗'} {name}: {detail}")


def cites_valid(result) -> list:
    bad = []

    def scan(items):
        for it in items:
            doc, pn = it["cite"].rsplit(" ", 1)
            if (doc, int(pn[1:])) not in KNOWN_PAGES:
                bad.append(it["cite"])

    for p in result["products"]:
        scan(p["reasons"] + p["concerns"] + p["gates"])
        if p.get("estimate"):
            scan([{"cite": p["estimate"]["cite"]},
                  {"cite": p["estimate"]["formula_cite"]}])
    return bad


def p1_questionnaire():
    d = requests.get(f"{BASE}/assess", timeout=10).json()
    n = len(d["questions"])
    cond = any(q.get("show_if") for q in d["questions"])
    return (n == 5 and cond and len(d["products"]) == 3,
            f"{n} 题（含条件题 {cond}）、{len(d['products'])} 产品")


def p2_buyer():
    r = requests.post(f"{BASE}/assess", timeout=10, json={"answers": {
        "purpose": "buy", "age": "mid", "term": "over5",
        "amount": "w100_300"}}).json()
    win = next(p for p in r["products"] if p["company"] == r["winner"])
    est = win.get("estimate") or {}
    bad = cites_valid(r)
    ok = (r["winner"] == "anju_loan" and win["score"] == 100
          and est.get("monthly", 0) > 0 and not bad)
    return ok, (f"winner={r['winner']} score={win['score']} "
                f"月供≈¥{est.get('monthly')}/月（{est.get('amount_wan')}万·"
                f"{est.get('months')}期·{est.get('rate')}%）"
                f" 引用失锚={bad or '无'}")


def p3_overage():
    r = requests.post(f"{BASE}/assess", timeout=10, json={"answers": {
        "purpose": "consume", "age": "b56_60", "term": "y1_3",
        "amount": "lt10w"}}).json()
    lex = next(p for p in r["products"] if p["company"] == "lexiang_loan")
    bad = cites_valid(r)
    ok = r["winner"] is None and "均不适合" in r["headline"] and not bad
    return ok, f"{r['headline']}；乐享贷被拦：{lex['gates'][0]['text']}"


def p4_metrics():
    m = requests.get(f"{BASE}/metrics", timeout=10).json()
    n = m["counters"].get("chat.assess", 0)
    return n >= 2, f"chat.assess={n}"


def p5_rag_regression():
    r = requests.post(f"{BASE}/chat", timeout=60, json={
        "user_id": "m2_probe", "session_id": "m2_probe",
        "message": "安居贷的申请条件是什么？"})
    d = r.json()
    ok = d["route"] == "rag" and "[anju_loan P1]" in d["answer"]
    return ok, f"route={d['route']} attempts={d['attempts']} 引用P1={'有' if ok else '无'}"


t0 = time.time()
probe("问卷下发", p1_questionnaire)
probe("购房青年→安居贷+月供", p2_buyer)
probe("56岁消费→诚实全拒", p3_overage)
probe("测评计数器", p4_metrics)
probe("RAG 主链路回归", p5_rag_regression)

results["verdict"] = "PASS" if all_ok else "FAIL"
results["elapsed_s"] = round(time.time() - t0, 1)
print(f"\nM2 探针结论: {results['verdict']}（{results['elapsed_s']}s）")

if SAVE:
    with open("probe_m2_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("已落档 probe_m2_result.json")
