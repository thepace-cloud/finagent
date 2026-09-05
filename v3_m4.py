"""V3-M4: RAG 闭环最后一块 —— 检索 top-k → 组装 context → LLM 生成 → [Px] 引用硬校验

防模型编页码不能只靠 prompt 里"求它"（自觉不可靠），
代码层还要硬校验：解析答案里所有引用，不在本次 context 真实来源里的 = 违规。
"""
import json
import re

from llm import chat
from sentence_transformers import SentenceTransformer

from v3_m3 import load, search  # 复用 M3 的加载与检索（不重复造轮子）

CHUNKS_FILE = "chunks.json"
MODEL_PATH = "models/pmml12"
RESULTS_FILE = "m4_results.txt"
K = 3

# 引用格式: [公司名 P页码]，例 [anju_loan P4]
CITE_RE = re.compile(r"\[([a-z_]+) P(\d+)\]")

SYSTEM_PROMPT = (
    "你是一家银行的贷款产品客服。用户会问产品规则问题。\n"
    "给你的是从产品说明书检索到的原文片段，每段标注来源格式为 [<文档名> P<页码>]。\n"
    "回答要求：\n"
    "1. 只依据 context 回答，context 里没有的不要编；\n"
    "2. 每个关键结论后标注来源，格式必须严格使用 [<文档名> P<页码>]（例如：[anju_loan P4]）；\n"
    "3. 标注的来源只能从 context 已有的标注里选，绝不允许自己发明页码或将尖括号作为字面量照抄。"
)

TEST_QUERIES = [
    "贷款逾期了会怎么样，罚息怎么算",
    "我想买房子首付差一点，能申请什么贷款周转",
    "提前把钱还了要不要交违约金",
    "利率能不能打折优惠",
]


def build_context(hits, chunk_by_id):
    """把命中的块拼成带来源标注的 context 文本。hits: [(score, chunk_id)]"""
    parts = []
    for score, cid in hits:
        chunk = chunk_by_id[cid]
        parts.append(f"[{chunk['company']} P{chunk['page']}]\n{chunk['text']}")
    return "\n\n".join(parts)


def check_citations(answer, hits, chunk_by_id):
    """硬校验：答案里每个引用都必须落在本次检索命中的 (company, page) 里。返回违规引用列表"""
    real = {(chunk_by_id[cid]["company"], chunk_by_id[cid]["page"]) for _, cid in hits}
    found = {(m.group(1), int(m.group(2))) for m in CITE_RE.finditer(answer)}
    return sorted(found - real)  # 引用了 context 里不存在的内容 = 编造


def main():
    chunk_by_id, ids, V = load()
    model = SentenceTransformer(MODEL_PATH)

    lines = []  # 收集这一轮全部输出，末尾一起落盘 → 可在编辑器里直接回看（打印一闪而过不叫可审计）

    for query in TEST_QUERIES:
        hits = search(model, V, ids, query, k=K)
        context = build_context(hits, chunk_by_id)

        block = [f"\n{'='*60}\n问: {query}", f"检索命中: {[cid for _, cid in hits]}"]

        answer = chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"context:\n{context}\n\n问题：{query}"},
        ])
        block.append(f"答: {answer}")

        bad = check_citations(answer, hits, chunk_by_id)
        block.append(f"⚠ 编造引用 {len(bad)} 处: {bad} —— 这些页不在本次检索命中的 context 里"
                     if bad else "✓ 引用校验通过：所有引用都落在 context 真实来源内")
        lines.extend(block)

    out = "\n".join(lines)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write(out + "\n")
    print(out)


if __name__ == "__main__":
    main()
