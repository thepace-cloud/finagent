"""M3.5 线上验收探针 —— 会话回放 + IP 限流（本地/线上通用）

用法: python -X utf8 v5_m35_probe.py http://47.95.222.61:8000 [--save]

五连探：
  1. 历史回放：问两句 → GET /history 时序还回 4 条、角色/内容对得上
  2. 空会话历史：新 session → messages=[] total=0（不炸不编）
  3. 限流·轻档：同 IP 连打 65 发 /profile 非法体（400 不污染计数器）
     → 前 60 发过闸（400），之后 429 + Retry-After 头
  4. 限流·贵档未误伤：风暴后正常 /chat 一次 200（chat 与 light 是独立桶）
  5. 流式回归：/chat/stream SSE 首事件 meta 正常（前端打字机的命脉）
"""
import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
SAVE = "--save" in sys.argv
U = "m35_probe"

results = {"base": BASE, "probes": []}
all_ok = True


def probe(name, fn):
    global all_ok
    ok, detail = fn()
    all_ok &= ok
    results["probes"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'✓' if ok else '✗'} {name}: {detail}")


def p1_history_roundtrip():
    for msg in ("兴旺贷的额度范围是多少？", "期限有哪些选择？"):
        r = requests.post(f"{BASE}/chat", timeout=90, json={
            "user_id": U, "session_id": "m35a", "message": msg})
        r.raise_for_status()
    h = requests.get(f"{BASE}/history", timeout=10,
                     params={"user_id": U, "session_id": "m35a"}).json()
    m = h["messages"]
    ok = (h["total"] == 4 and len(m) == 4
          and m[0]["role"] == "user" and "额度" in m[0]["content"]
          and m[1]["role"] == "assistant" and "旺" in m[1]["content"]
          and m[-1]["role"] == "assistant")          # 时序：最后一条是助手
    return ok, (f"total={h['total']} 取回={len(m)} 首={m[0]['role']} "
                f"末={m[-1]['role']} 时序对={ok}")


def p2_history_empty():
    h = requests.get(f"{BASE}/history", timeout=10,
                     params={"user_id": U, "session_id": "m35_never"}).json()
    ok = h["messages"] == [] and h["total"] == 0
    return ok, f"messages={h['messages']} total={h['total']}"


def p3_rate_limit_light():
    """65 发非法 /profile：过闸的得 400（校验拦下，计数器零污染），超闸的 429。

    为什么用非法体打：合法保存会 inc(profile.update)，把看板数字刷假；
    限流依赖在端点校验之前执行——400 与 429 的分界就是闸门位置。
    """
    codes = []
    for _ in range(65):
        r = requests.post(f"{BASE}/profile", timeout=10,
                          json={"user_id": "spam", "housing": "spam"})
        codes.append(r.status_code)
        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            assert ra, "429 缺 Retry-After 头"
    n400, n429 = codes.count(400), codes.count(429)
    ok = n400 >= 55 and n429 >= 1 and (n400 + n429) == 65
    return ok, (f"过闸400={n400} 掐流429={n429}（限 60/min）"
                f" Retry-After={'有' if n429 else '—'}")


def p4_rate_limit_chat_unharmed():
    time.sleep(1)                       # 给轻档风暴收尾，别和它抢连接
    r = requests.post(f"{BASE}/chat", timeout=90, json={
        "user_id": U, "session_id": "m35b",
        "message": "乐享贷的申请条件是什么？"})
    d = r.json()
    ok = (r.status_code == 200 and d["route"] == "rag"
          and "[lexiang_loan" in d["answer"])
    return ok, f"HTTP {r.status_code} route={d.get('route')} 引用={'[lexiang_loan' in d.get('answer', '')}"


def p5_stream_regression():
    r = requests.post(f"{BASE}/chat/stream", timeout=90, stream=True, json={
        "user_id": U, "session_id": "m35c",
        "message": "安居贷的利率是多少？"})
    first, got_delta = "", False
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            ev = json.loads(line[6:])
            if ev["type"] == "meta":
                first = ev["route"]
            if ev["type"] == "delta":
                got_delta = True
                break                       # 见到打字机出字即可收工
    r.close()
    ok = r.status_code == 200 and first == "rag" and got_delta
    return ok, f"HTTP {r.status_code} 首事件route={first} 出字={got_delta}"


t0 = time.time()
probe("历史回放(两句→四条时序)", p1_history_roundtrip)
probe("空会话历史不炸", p2_history_empty)
probe("限流·轻档(65发/60每分)", p3_rate_limit_light)
probe("限流·贵档未误伤", p4_rate_limit_chat_unharmed)
probe("流式SSE回归", p5_stream_regression)

results["verdict"] = "PASS" if all_ok else "FAIL"
results["elapsed_s"] = round(time.time() - t0, 1)
print(f"\nM3.5 探针结论: {results['verdict']}（{results['elapsed_s']}s）")

if SAVE:
    with open("probe_m35_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("已落档 probe_m35_result.json")
