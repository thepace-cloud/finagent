"""V5-M2 Validator —— 路径出口的确定性质检：不过 → 带反馈重试一次 → 降级拒答

受控编排（拷问主线）：Router 守入口，Validator 守出口，中间才是 Agent 的地盘。
为什么 Validator 也是确定性代码、不是让另一个 LLM 当裁判：
  规则校验零成本、可单测、可复现；LLM-judge 每次判定自己要烧 token 且会飘——
  裁判自己会犯错，就等于没人守门。LLM-as-judge 是谈资，不是这里的方案。

设计决策（拷问点）：
  - 校验器签名统一 validate(answer) -> list[str]（问题列表，空 = 通过）
    ——统一签名，编排层才能拿同一个 run_with_guard 通用处理所有路径
  - RAG 路径直接复用 V3 的 check_citations（旧资产进新边界，不重写）
  - 重试有上限：只重试 1 次——和 V2 的 max_steps 同一条纪律：护栏防死循环烧 token
  - 重试必须带反馈：把"你上次编造了 [x P9]"回喂给模型，不然重试是闭眼重掷
  - 降级 = 安全侧倒：财经场景宁拒不错——利率答错比"答不了"严重一个量级
"""
from v3_m4 import check_citations

MAX_RETRIES = 1  # 校验不过最多重试一次

DEGRADED_ANSWER = (
    "抱歉，这条回答未通过出口校验，已被拦截。"
    "请换个问法，或转人工客服。（Validator 降级：宁拒不错）"
)


def validate_rag_factory(hits, chunk_by_id):
    """造一个 RAG 校验器：闭包捕获本次检索命中的白名单，签名对齐 validate(answer)。

    复用 V3 的 check_citations——引用必须落在本次命中块的真实 (company, page) 里。
    """
    def validate(answer: str) -> list:
        return check_citations(answer, hits, chunk_by_id)
    return validate


def validate_analysis(answer: str) -> list:
    """工具路径（计算/行情）的确定性体检。

    两条规则，各有明确理由：
      1. 过短 → 大概率是半截话或空转
      2. 不含任何数字 → 行情/利率/月供的回答必然带数字；
         没有数字说明工具结果没被真正用上（模型在自由发挥 = 危险）
    """
    problems = []
    if len(answer.strip()) < 10:
        problems.append("回答过短，疑似半截话")
    if not any(ch.isdigit() for ch in answer):
        problems.append("工具路径回答不含任何数字，工具结果疑似未被使用")
    return problems


def run_with_guard(gen, validate, max_retries: int = MAX_RETRIES):
    """出口守卫循环：生成 → 校验 → 不过带反馈重试 → 仍不过 → 降级。

    gen:       callable(feedback) -> answer    重试时把失败原因喂回去
    validate:  callable(answer) -> list        空 = 通过
    返回 (answer, problems, attempts)——attempts 进 log，重试行为可审计。
    """
    feedback = None
    problems = []
    for attempt in range(1, max_retries + 2):        # 1 次首发 + N 次重试
        answer = gen(feedback)
        problems = validate(answer)
        if not problems:
            return answer, [], attempt
        feedback = ("上次回答未通过出口校验：" + "；".join(str(p) for p in problems)
                    + "。请只基于给定资料/工具结果重新生成，不要编造。")
    return DEGRADED_ANSWER, problems, max_retries + 1


if __name__ == "__main__":
    # 自测不用 LLM：用假生成器把三条出路全部演一遍（确定性测试确定性代码）
    fake_chunks = {"c01": {"company": "anjudai", "page": 3, "text": "首套房贷利率 3.95%"}}
    fake_hits = [(0.92, "c01")]
    rag_validate = validate_rag_factory(fake_hits, fake_chunks)

    print("=== 场景1: RAG 一次通过 ===")
    def good_gen(feedback):
        return "首套房贷利率 3.95%，详见 [anjudai P3]。"
    ans, bad, n = run_with_guard(good_gen, rag_validate)
    print(f"attempts={n} problems={bad}\n{ans}\n")

    print("=== 场景2: RAG 首发编页码，反馈后修正（重试的价值）===")
    state = {"n": 0}
    def flaky_gen(feedback):
        state["n"] += 1
        if state["n"] == 1:
            return "首套房贷利率 3.95%，详见 [anjudai P9]。"   # P9 不在命中页 → 编造
        return f"（收到反馈：{feedback}）修正 → 首套房贷利率 3.95%，详见 [anjudai P3]。"
    ans, bad, n = run_with_guard(flaky_gen, rag_validate)
    print(f"attempts={n} problems={bad}\n{ans}\n")

    print("=== 场景3: RAG 永远编造 → 降级拒答（宁拒不错）===")
    def liar_gen(feedback):
        return "首套房贷利率 3.95%，详见 [anjudai P9]。"
    ans, bad, n = run_with_guard(liar_gen, rag_validate)
    print(f"attempts={n} problems={bad}\n{ans}\n")

    print("=== 场景4: 工具路径不含数字 → 被拦 ===")
    def no_digit_gen(feedback):
        return "平安银行行情还不错。"   # 无数字：工具结果疑似没被用上
    ans, bad, n = run_with_guard(no_digit_gen, validate_analysis)
    print(f"attempts={n} problems={bad}\n{ans}")
