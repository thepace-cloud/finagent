"""M3 线上验收探针 —— 本地/线上通用（BASE 用 argv 传入）

用法: python -X utf8 v5_m3_probe.py http://47.95.222.61:8000 [--save]

六连探（记忆可视化 = 画像可编辑 + 行为可见变化）：
  1. POST /profile 存画像（二套/乐享贷）→ GET 回读一致；非法值 400（白名单）
  2. 行为A  问「安居贷的利率」→ 答案含 4.45（画像=二套，定向补全生效）
  3. 行为A' 画像改回首套 → 同一问题答案含 3.95 —— 改画像，行为变
  4. 行为B  新会话问「申请条件是什么」（不点名产品、无上文）→ 乐享贷兜底
  5. 会话快照 GET /profile → 「它记得我」面板数据真实（消息数/提过的产品）
  6. 回归：compare 路由不伤 + 空画像用户 RAG 不变（等价性护栏）
"""
import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
SAVE = "--save" in sys.argv
U = "m3_probe"

results = {"base": BASE, "probes": []}
all_ok = True


def probe(name, fn):
    global all_ok
    ok, detail = fn()
    all_ok &= ok
    results["probes"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'✓' if ok else '✗'} {name}: {detail}")


def chat(session, msg, user=U, timeout=90):
    r = requests.post(f"{BASE}/chat", timeout=timeout, json={
        "user_id": user, "session_id": session, "message": msg})
    r.raise_for_status()
    return r.json()


def p1_profile_save():
    r = requests.post(f"{BASE}/profile", timeout=10, json={
        "user_id": U, "session_id": "m3s", "housing": "二套",
        "product": "乐享贷", "budget": "30万左右"})
    if r.status_code != 200:
        return False, f"保存失败 HTTP {r.status_code}: {r.text[:80]}"
    g = requests.get(f"{BASE}/profile", timeout=10,
                     params={"user_id": U, "session_id": "m3s"}).json()
    echo_ok = g["profile"] == {"housing": "二套", "product": "乐享贷",
                               "budget": "30万左右"}
    bad = requests.post(f"{BASE}/profile", timeout=10, json={
        "user_id": U, "housing": "三套"})
    return (echo_ok and bad.status_code == 400,
            f"回读一致={echo_ok}；白名单拦截三套="
            f"{'是' if bad.status_code == 400 else '否'}（HTTP {bad.status_code}）")


def p2_second_home():
    d = chat("m3a", "安居贷的利率是多少？")
    ok = "4.45" in d["answer"] and "[anju_loan P2]" in d["answer"]
    return ok, (f"route={d['route']} attempts={d['attempts']} "
                f"含4.45={'4.45' in d['answer']} "
                f"引用P2={'[anju_loan P2]' in d['answer']}")


def p3_first_home():
    r = requests.post(f"{BASE}/profile", timeout=10, json={
        "user_id": U, "session_id": "m3s", "housing": "首套",
        "product": "乐享贷", "budget": "30万左右"})
    if r.status_code != 200:
        return False, f"改画像失败 HTTP {r.status_code}"
    d = chat("m3b", "安居贷的利率是多少？")
    ok = "3.95" in d["answer"] and "[anju_loan P2]" in d["answer"]
    return ok, (f"同一问题含3.95={'3.95' in d['answer']} "
                f"引用P2={'[anju_loan P2]' in d['answer']}")


def p4_product_fallback():
    d = chat("m3c", "申请条件是什么？")   # 不点名、新会话 → 画像乐享贷兜底
    ok = d["route"] == "rag" and "[lexiang_loan" in d["answer"]
    return ok, (f"route={d['route']} "
                f"乐享贷兜底引用={'[lexiang_loan' in d['answer']}")


def p5_session_snapshot():
    g = requests.get(f"{BASE}/profile", timeout=10,
                     params={"user_id": U, "session_id": "m3a"}).json()
    s = g["session"]
    ok = s["messages"] >= 2 and "安居贷" in s["products_mentioned"]
    return ok, f"消息数={s['messages']} 提过的产品={s['products_mentioned']}"


def p6_regression():
    d1 = chat("m3d", "安居贷和兴旺贷的利率有什么区别？")
    d2 = chat("m3e", "兴旺贷的申请条件是什么？", user="m3_plain")
    ok = (d1["route"] == "compare" and d2["route"] == "rag"
          and "[xingwang_loan" in d2["answer"])
    return ok, (f"compare={d1['route']} 空画像RAG={d2['route']} "
                f"兴旺贷引用={'[xingwang_loan' in d2['answer']}")


t0 = time.time()
probe("画像存取+白名单", p1_profile_save)
probe("行为A: 二套→4.45%", p2_second_home)
probe("行为A': 首套→3.95%", p3_first_home)
probe("行为B: 新会话画像兜底", p4_product_fallback)
probe("会话快照(它记得我)", p5_session_snapshot)
probe("compare+RAG 回归", p6_regression)

m = requests.get(f"{BASE}/metrics", timeout=10).json()["counters"]
results["counters"] = {k: m.get(k) for k in
                       ("chat.total", "chat.compare", "chat.assess",
                        "profile.update")}
results["verdict"] = "PASS" if all_ok else "FAIL"
results["elapsed_s"] = round(time.time() - t0, 1)
print(f"\nM3 探针结论: {results['verdict']}（{results['elapsed_s']}s）"
      f"  profile.update={m.get('profile.update', 0)}")

if SAVE:
    with open("probe_m3_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("已落档 probe_m3_result.json")
