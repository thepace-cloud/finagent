"""V5-M1 Task Router —— 把 v4_demo 里那句 if re.search 换成结构化路由表

受控编排（拷问主线）：Workflow 提供边界，Agent 在边界内自主。
Router 就是边界本身，所以必须是确定性代码、不是 LLM 判断：
  1. 成本：LLM 路由 = 每轮多一次模型调用，白烧 token
  2. 延迟：规则匹配微秒级；LLM 判断加几百毫秒起步
  3. 可测性：规则能逐条写单测；LLM 判断会飘，路由错了难复现、难归因
Agent 的自主性不删，只是收进路径内部——Analysis 路径里的 agent_turn 循环
（调哪个工具、调几次）仍由模型自己决定。

设计决策（拷问点）：
  - 数据驱动：加一条路径 = 在 ROUTES 加一行，分发逻辑零改动（对照 V2 的 TOOLS 注册表）
  - 顺序即优先级：按表从上往下 first-match-wins，越具体的越靠前
  - 默认路由兜底：没命中也必须有确定去路（RAG 主路径），不能悬空抛异常
  - 决策可审计：返回值带命中词，log 出来就能回答"这句为什么走了这条路"

诚实边界：关键词规则会漏同义表述（"多少钱一股"不含"股价"）。
升级路径是"确定性优先、模型兜底"：第一道规则，miss 了才让小分类器/LLM 补判——
这本身就是受控编排的思想，不是把分叉口整个交给模型。
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    """一条路由：name 是路径标识，patterns 是关键词（命中任一即走这条）。"""
    name: str
    patterns: tuple[str, ...]
    description: str = ""


ROUTES: tuple[Route, ...] = (
    # 越具体的越靠前（first-match-wins，顺序即优先级）
    Route(
        "analysis",
        (r"月供", r"总利息", r"利息", r"股价", r"行情"),
        "Agent 工具路径：计算/行情走 agent_turn 循环（V2 工具 + MCP），边界内自主",
    ),
    # RAG 是默认兜底路径，不写 patterns，由 DEFAULT_ROUTE 指定
)

DEFAULT_ROUTE = "rag"

# ── 对比意图（M1 对比落地）─────────────────────────────────────────
# 产品别名 → 语料 company 键（与 chunks.json / /cite 接口同一套键）。
# 别名成对出现：全称「安居贷」+ 简称「安居」（用户嘴里的真实说法）
COMPANY_ALIASES: tuple[tuple[str, str], ...] = (
    ("安居贷", "anju_loan"), ("安居", "anju_loan"),
    ("乐享贷", "lexiang_loan"), ("乐享", "lexiang_loan"),
    ("兴旺贷", "xingwang_loan"), ("兴旺", "xingwang_loan"),
)
COMPARE_WORDS = (r"对比", r"区别", r"相比", r"差异", r"不同", r"哪个", r"哪家",
                 r"更宽松", r"更划算")
ALL_PRODUCTS_WORDS = (r"这几款", r"这三款", r"三款", r"各款", r"所有", r"分别")


def detect_compare(user_msg: str) -> tuple[str, ...] | None:
    """对比意图检测（确定性）：命中返回要对比的 company 元组，否则 None。

    为什么不走 ROUTES 表：表能表达「命中一个关键词」，表达不了
    「数出两个不同产品」这种结构性条件——所以独立成函数，
    但同样确定性、可单测、决策可审计（返回值就是审计记录）。

    规则（保守优先，宁可漏到 RAG 也不误伤单产品问题）：
      1. 点名 ≥2 款产品 → 对比（产品都摆上桌了，意图不言自明）；
      2. 比较词 + 全体指代词（这几款/三款/分别…）且没点名 → 三款全比；
      3. 只点名 1 款 + 比较词 → 不算（「安居贷哪个城市能申请」是单产品题）。
    """
    companies: list[str] = []
    for alias, company in COMPANY_ALIASES:
        if alias in user_msg and company not in companies:
            companies.append(company)
    if len(companies) >= 2:
        return tuple(companies)
    if (any(re.search(p, user_msg) for p in COMPARE_WORDS)
            and any(re.search(p, user_msg) for p in ALL_PRODUCTS_WORDS)):
        all_companies: list[str] = []
        for _, company in COMPANY_ALIASES:
            if company not in all_companies:
                all_companies.append(company)
        return tuple(all_companies)
    return None


def route(user_msg: str) -> tuple[str, str | None]:
    """确定性分发：按 ROUTES 顺序匹配，返回 (路由名, 命中的词)。

    命中的词可能为 None（走了默认路由）——审计日志靠它解释每一次分叉。
    """
    # 对比先于路由表：结构性条件表表达不了（见 detect_compare）；
    # 且「安居贷和乐享贷的利息差多少」应按产品条款对比，不该被
    # 「利息」关键词抢去工具路径算月供
    prods = detect_compare(user_msg)
    if prods:
        return "compare", "+".join(prods)
    for r in ROUTES:
        for p in r.patterns:
            if re.search(p, user_msg):
                return r.name, p
    return DEFAULT_ROUTE, None


if __name__ == "__main__":
    # 自测：每类至少一句，覆盖 命中工具路径 / 默认 RAG 两种结局
    TEST_MSGS = [
        "30 万、3 年期个人消费贷，月供和总利息多少？",   # → analysis（月供）
        "帮我查一下 600519 贵州茅台的股价",              # → analysis（股价）
        "那利率是多少",                                  # → rag 默认（注意："利率"不含"利息"）
        "安居贷首付和额度是多少",                        # → rag 默认
        "提前还款收不收违约金",                          # → rag 默认
        "安居贷和乐享贷的申请条件有什么区别",             # → compare（点名两款）
        "这几款贷款哪个年龄限制更宽松",                  # → compare（比较词+全体指代，2026-09-29 探针翻车题）
        "安居贷哪个城市能申请",                          # → rag 默认（单产品+比较词 ≠ 对比）
    ]
    for msg in TEST_MSGS:
        name, hit = route(msg)
        print(f"[route] {name:<8} hit={hit!r:<10} <- {msg}")
