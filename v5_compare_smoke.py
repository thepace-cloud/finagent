"""M1 对比落地冒烟 —— 修没修好，探针三连说了算

2026-09-29 探针确诊：默认 RAG 路径下「这几款贷款哪个年龄限制更宽松？」
top-3 全被安居贷占位，另两款没进 context → 模型诚实说「无法比较」——
护栏没破，但对比功能静默失效。

本脚本验证 compare 路径三件事：
  1. detect_compare 检出正确的产品组合（含昨晚探针#3 用错名字的修正版）
  2. compare_search 分产品检索 → 每款产品都有座位（修 bug 的核心断言）
  3. 对照表生成 + 引用校验零编造
三题全绿 = M1 验收通过。
"""
from llm import chat
from sentence_transformers import SentenceTransformer
from v3_m3 import load
from v3_m4 import MODEL_PATH, build_context, check_citations
from v5_compare import (COMPARE_SYSTEM_PROMPT, build_compare_indexes,
                        compare_search)
from v5_router import detect_compare

# (问题, 期望检出的产品组合)；第三题是昨晚探针#3 的修正版——
# 昨晚把「兴旺贷」误写成「星网贷」，检索抓不到星网是模型的诚实而非 bug
PROBES = [
    ("安居贷和乐享贷的申请条件有什么区别？",
     {"anju_loan", "lexiang_loan"}),
    ("这几款贷款哪个年龄限制更宽松？",
     {"anju_loan", "lexiang_loan", "xingwang_loan"}),
    ("兴旺贷和安居贷的利率差别大吗？",
     {"anju_loan", "xingwang_loan"}),
]


def main():
    chunk_by_id, ids, V = load()
    model = SentenceTransformer(MODEL_PATH)
    cmp_idx = build_compare_indexes(chunk_by_id, ids, V)
    print("子索引块数:", {c: len(i["ids"]) for c, i in cmp_idx.items()})

    all_ok = True
    for q, expect in PROBES:
        print("\n" + "=" * 60 + f"\n问: {q}")

        companies = detect_compare(q)
        ok_route = companies is not None and set(companies) == expect
        print(f"  detect_compare: {companies}  "
              f"{'✓' if ok_route else '✗ 期望 ' + str(expect)}")

        hits = compare_search(model, cmp_idx, companies, q)
        hit_companies = {chunk_by_id[cid]["company"] for _, cid in hits}
        ok_cover = set(companies) <= hit_companies   # 核心断言：每款都有座位
        print(f"  hits: {[cid for _, cid in hits]}")
        print(f"  产品覆盖: {sorted(hit_companies)}  "
              f"{'✓ 每款都有座位' if ok_cover else '✗ 仍有产品缺席'}")

        context = build_context(hits, chunk_by_id)
        answer = chat([
            {"role": "system", "content": COMPARE_SYSTEM_PROMPT},
            {"role": "user", "content": f"context:\n{context}\n\n问题：{q}"},
        ])
        bogus = check_citations(answer, hits, chunk_by_id)
        has_table = any(line.strip().startswith("|") for line in answer.split("\n"))
        print(f"  表格输出: {'✓' if has_table else '✗ 无表格'}   "
              f"引用校验: {'✓ 零编造' if not bogus else '✗ ' + str(bogus)}")
        print(f"  答案开头: {answer[:100].replace(chr(10), ' ')}")

        ok = ok_route and ok_cover and not bogus and has_table
        all_ok &= ok
        print(f"  => {'PASS' if ok else 'FAIL'}")

    print(f"\nM1 冒烟结论: {'三题全绿 ✓' if all_ok else '存在红项 ✗'}")


if __name__ == "__main__":
    main()
