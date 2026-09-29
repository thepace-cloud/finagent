"""V5 对比路径 —— 多产品问题的「分产品检索 + 对照表生成」配方

为什么单开一条路径（2026-09-29 探针实证）：
  「这几款贷款哪个年龄限制更宽松？」在默认 RAG 路径下翻车——
  混合检索在合并语料上排序，优化的是「整体最相关的 3 块」，不保证
  「每款产品都有代表」。top-3 全被安居贷占位时，另两款压根没进
  context，模型只能诚实说「无法比较」：护栏没破，但对比功能静默失效。

修法（结构性保证，不靠检索运气）：
  检索改为「分产品各取 top-k 再合并」——每款产品在自己的块池里排序，
  谁也不会被别人挤出座位。合并后的 hits 走与 RAG 完全相同的生成配方
  与出口护栏（引用白名单、带反馈重试、降级拒答一个不少）。

设计决策（拷问点）：
  - 为什么给每款产品建独立子索引而不是全库检索后过滤？
    先检索后过滤 = 先发 3 张 seat 再按产品挑，产品可能压根没进前 3——
    那正是要修的 bug。子索引从根上保证每款产品有座位。
  - 成本：语料 20 块，3 个 BM25 子索引 lifespan 里建一次（毫秒级）；
    V 子矩阵 fancy indexing 拷贝 ~3×7×384 float，可忽略。
    按当前规模做最诚实的事，语料涨百倍再谈向量库。
  - 合并榜按 RRF 分数排序只影响 context 拼接顺序；
    白名单校验看的是集合，顺序无关。
"""
from v3_hybrid import BM25, hybrid_search

# 每款产品各取几块。全局 RAG 是 K=3；对比要养活 ≥2 款产品，每款 3 块
# 实测定夺：k_per=2 时「这几款哪个年龄限制更宽松」漏掉乐享贷年龄块，
# 答案诚实说「未提及」——覆盖优先，宁可 context 长一点
K_PER_PRODUCT = 3

COMPARE_SYSTEM_PROMPT = (
    "你是一家银行的贷款产品对比助手。用户会问多个贷款产品之间的差异。\n"
    "给你的是从各产品说明书检索到的原文片段，每段标注来源格式为 [<文档名> P<页码>]。\n"
    "回答要求：\n"
    "1. 先用一两句话直接回答用户的问题（例如哪款更宽松、核心差异是什么）；\n"
    "2. 然后输出一个 markdown 表格逐维度对照：第一列是「对比维度」，"
    "其后每一列是一款产品（列名用产品中文名，从 context 内容判断）；\n"
    "3. 表格每个论断后标注来源，格式必须严格使用 [<文档名> P<页码>]"
    "（例如：[anju_loan P4]）；\n"
    "4. 某产品在某维度 context 里没有信息时，如实写「未检出」——"
    "不得写「说明书未提及」：本次检索没看到不等于说明书没写，"
    "缺证据不是证据缺失；绝不允许编造；\n"
    "5. 标注的来源只能从 context 已有的标注里选，绝不允许自己发明页码。"
)


def build_compare_indexes(chunk_by_id, ids, V):
    """按 company 把语料切成子索引：{company: {"ids", "V", "bm25"}}。

    ids 与 V 行号一一对齐（v3_m3.load 的契约），按 company 归拢行号后
    各建一份小 BM25——给每款产品一个「自己人里排名」的泳池。
    """
    pos_by_company: dict[str, list[int]] = {}
    for pos, cid in enumerate(ids):
        company = chunk_by_id[cid]["company"]
        pos_by_company.setdefault(company, []).append(pos)

    indexes = {}
    for company, positions in pos_by_company.items():
        sub_ids = [ids[p] for p in positions]
        indexes[company] = {
            "ids": sub_ids,
            "V": V[positions],            # fancy indexing：新矩阵，行序与 sub_ids 对齐
            "bm25": BM25([chunk_by_id[cid]["text"] for cid in sub_ids], sub_ids),
        }
    return indexes


def compare_search(model, cmp_indexes, companies, query, k_per=K_PER_PRODUCT):
    """每款产品各自 top-k_per（子索引内混合检索），合并成一个 hits 榜。

    返回形状与 hybrid_search 相同 [(score, chunk_id)]——下游 build_context、
    validate_rag_factory 零改动。companies 为空时返回空榜（交给上层拒答）。
    """
    merged = []
    for company in companies:
        idx = cmp_indexes[company]
        merged += hybrid_search(model, idx["V"], idx["ids"], idx["bm25"],
                                query, k=k_per)
    merged.sort(reverse=True)             # 只影响 context 拼接顺序，白名单看集合
    return merged
