"""V3 评估 runner —— 全量跑 v3_golden.json，双层计分 + A/B 检索对比

计分规则（两层归因，检索层先行）：
  检索层：golden 是否全部进 top-K（K=3）。没进 → 该题红，责任在检索
          （「无米下锅，先查检索别怪模型」）。
  生成层：检索达标的题才考生成——答案里的引用必须全在本次命中集内
          （check_citations 白名单），编造即红。
  零块题：golden=[]，检索层跳过；看生成是否编造引用（有引用即红）
          + 是否拒答（软信号，最终人工看原文）。

A/B 模式（M6 起）：
  vector = 纯向量（M5 基线）   hybrid = BM25+RRF（M6 候选）
  两路各跑全量 → 逐题对比。g05 是回归探针：纯向量在「利率优惠」上
  稀释+语义盲区预期红，hybrid 应转绿——它就是为度量这次修复而存在的。

输出：控制台汇总 + 对比表 + v3_eval_results.txt 全量留档（可审计传统）。
"""
import json
import sys
import time

from sentence_transformers import SentenceTransformer

# Windows 控制台默认 GBK：打印「✓」会 UnicodeEncodeError 杀掉整跑——
# 换成 ? 只伤显示，不伤落盘（结果文件本身是 utf-8）
sys.stdout.reconfigure(errors="replace")

from llm import chat
from v3_hybrid import BM25, hybrid_search
from v3_m3 import load, search
from v3_m4 import K, MODEL_PATH, SYSTEM_PROMPT, build_context, check_citations

QUESTIONS = json.load(open("v3_golden.json", encoding="utf-8"))
RESULT_FILE = "v3_eval_results.txt"


def generate(query: str, hits) -> str:
    context = build_context(hits, CHUNK_BY_ID)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"context:\n{context}\n\n问题：{query}"},
    ]
    # 长批评测最怕瞬时断连一发入魂：temperature=0 重试结果不变，幂等安全
    for attempt in range(3):
        try:
            return chat(messages)
        except Exception:  # 评测脚本只求活到终点，第三次仍失败才向上抛
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def run_mode(label: str, hits_fn):
    """跑一种检索模式的全量评测，返回 (rows, log)。"""
    rows, log = [], []
    for q in QUESTIONS:
        hits = hits_fn(q["query"])
        hit_ids = [cid for _, cid in hits]        # search 返回 (score, id) 元组，先剥出 id
        covered = set(q["golden"]).issubset(set(hit_ids))

        if q["category"] == "zero":
            answer = generate(q["query"], hits)
            bogus = check_citations(answer, hits, CHUNK_BY_ID)
            refused = any(w in answer for w in
                          ["无法", "未提及", "抱歉", "没有相关", "不涉及", "无法回答"])
            rows.append((q["id"], "zero", "—",
                         "PASS" if (not bogus and refused) else
                         ("citation红" if bogus else "未拒答?")))
            log.append(f"[{q['id']}] zero  引用编造={bool(bogus)} 拒答信号={refused}\n"
                       f"  answer: {answer}\n  top3={hits}\n")
        elif covered:
            answer = generate(q["query"], hits)
            bogus = check_citations(answer, hits, CHUNK_BY_ID)
            rows.append((q["id"], q["category"], "hit", "PASS" if not bogus else "citation红"))
            log.append(f"[{q['id']}] {q['category']}  检索✓  编造引用={bogus}\n"
                       f"  answer: {answer}\n  top3={hits}\n")
        else:
            missed = set(q["golden"]) - set(hit_ids)
            rows.append((q["id"], q["category"], "MISS", f"漏召回 {sorted(missed)}"))
            log.append(f"[{q['id']}] {q['category']}  检索✗  漏召回={sorted(missed)}\n"
                       f"  top3={hits}\n（无米下锅，跳过生成）\n")
    log.append("=" * 60)
    return rows, log


def summarize(rows, label):
    """单模式汇总行。"""
    def rate(part):
        got = [r for r in rows if r[1] == part]
        return f"{sum(1 for r in got if r[3] == 'PASS')}/{len(got)}"

    retr = [r for r in rows if r[1] in ("single", "multi")]
    retr_hit = sum(1 for r in retr if r[2] == "hit")
    gen = [r for r in rows if r[2] == "hit"]
    gen_pass = sum(1 for r in gen if r[3] == "PASS")
    return [
        f"── {label} ──",
        f"检索层命中：{retr_hit}/{len(retr)}（零块不考检索）",
        f"  ├ 单块：{rate('single')}",
        f"  └ 多块：{rate('multi')}",
        f"生成层（检索达标题）：{gen_pass}/{len(gen)}",
        f"零块拒答：{rate('zero')}",
    ]


if __name__ == "__main__":
    model = SentenceTransformer(MODEL_PATH)
    CHUNK_BY_ID, ids, V = load()
    bm25 = BM25([CHUNK_BY_ID[cid]["text"] for cid in ids], ids)

    modes = [
        ("vector", lambda query: search(model, V, ids, query, k=K)),
        ("hybrid", lambda query: hybrid_search(model, V, ids, bm25, query, k=K)),
    ]
    results = {}
    for label, fn in modes:
        results[label] = run_mode(label, fn)

    # ── 汇总 ──
    summary = ["=" * 60, f"V3 评估 A/B：{len(QUESTIONS)} 题  K={K}  RECALL=10  RRF_K=60"]
    for label, _ in modes:
        summary += summarize(results[label][0], label)
    print("\n".join(summary))

    # ── 逐题对比表：一眼看谁翻绿、谁翻红 ──
    vec = {r[0]: r for r in results["vector"][0]}
    hyb = {r[0]: r for r in results["hybrid"][0]}
    print(f"\n{'id':<6}{'类':<7}{'vector':<22}{'hybrid'}")
    changed = []
    for qid in vec:
        v = vec[qid][3] if vec[qid][2] == "MISS" else "检索✓ " + vec[qid][3]
        h = hyb[qid][3] if hyb[qid][2] == "MISS" else "检索✓ " + hyb[qid][3]
        mark = ""
        if (vec[qid][2] == "hit") != (hyb[qid][2] == "hit"):
            mark = "  ← 翻" + ("绿" if hyb[qid][2] == "hit" else "红") + "!"
            changed.append(qid)
        print(f"{qid:<6}{vec[qid][1]:<7}{v:<22}{h}{mark}")

    open(RESULT_FILE, "w", encoding="utf-8").write(
        "\n".join(summary) + "\n\n── 逐题对比 ──\n"
        + "\n".join(f"{qid}: vector={vec[qid]} | hybrid={hyb[qid]}" for qid in vec)
        + "\n\n" + "\n".join(results["vector"][1]) + "\n" + "\n".join(results["hybrid"][1]))
    print(f"\n翻动题目：{changed if changed else '无'}")
    print(f"全量明细已写入 {RESULT_FILE}")
