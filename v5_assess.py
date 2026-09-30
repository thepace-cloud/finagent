"""V5 适配测评 —— 问卷 → 确定性打分 → 推荐卡（M2 · 2026-09-30）

为什么完全不走大模型（拷问点）：
  测评的每条结论都是「说明书条款 × 用户答案」的查表推论——年龄落在
  哪个区间、用途属于哪一类，规则代码翻表就能判定，没有需要语义生成
  的部分。让 LLM 做测评 = 把可验证的规则变成不可复现的口算，恰好违背
  作品「数字交给代码算」的主张。收益：零 API 成本、毫秒出卡、同答案
  永远同结果；每条结论挂说明书页码，出口即审计。

与主链路的关系：
  独立端点 GET/POST /assess，不进 route()——路由回答「一句话属于哪条
  路径」，测评是「用户主动开始的多步流程」，入口在前端按钮，不抢
  /chat 的关键词地盘（只做加法，不碰主链路）。

问卷为什么问这五项（口径纪律）：
  只问语料撑得住的问题。原计划的「月收入」被砍掉——三份说明书都只写
  「具备稳定收入来源」，没有数字门槛，问收入要么是摆设要么逼出编造；
  换成「贷款金额」，三家都有真实的上下限可硬校验 [各 P2]。

规则表口径（全部锚定语料；改说明书必须同步改这里）：
  年龄  安居 18–65 / 乐享 22–55 / 兴旺 18–60              [各 P1]
  用途  购房→安居；消费→乐享（P3 明文禁购房/经营）；经营→兴旺（乐享 P3 明文禁经营）
  期限  安居 1–30 年 / 乐享 3 个月–5 年 / 兴旺 6 个月–5 年 [各 P2]
  金额  安居 ≤500 万 / 乐享 0.5–20 万 / 兴旺 10–300 万     [各 P2]
  客群  兴旺要求企业正常经营满 2 年                        [兴旺 P1]
  月供  等额本息公式取自说明书 P3；三份手册各带一个算好的
        示例（100万/4.75%/30年→5,216 元等）——示例即冒烟测试的黄金校准值
"""

PRODUCTS = {
    "anju_loan": "安居贷",
    "lexiang_loan": "乐享贷",
    "xingwang_loan": "兴旺贷",
}

METHOD_NOTE = (
    "测评由规则代码确定性计算，未调用大模型；每条结论附说明书出处，"
    "实际额度与利率以银行审批为准。"
)

# ── 问卷定义（GET /assess 直接吐给前端，问卷文案与打分规则同源）──
QUESTIONS = [
    {
        "id": "purpose", "text": "您这笔贷款主要用来做什么？",
        "options": [
            {"value": "buy", "label": "购买住房"},
            {"value": "consume", "label": "装修、教育、旅游、医疗等个人消费"},
            {"value": "business", "label": "生产经营周转"},
        ],
    },
    {
        # 条件题：只有经营用途才问（兴旺贷客群硬条款 [xingwang_loan P1]）
        "id": "biz_years", "text": "您的企业/个体工商户正常经营满 2 年了吗？",
        "show_if": {"purpose": "business"},
        "options": [
            {"value": "yes", "label": "满了"},
            {"value": "no", "label": "还不满"},
        ],
    },
    {
        "id": "age", "text": "您的年龄段是？",
        "options": [
            {"value": "lt18", "label": "未满 18 周岁"},
            {"value": "lt22", "label": "18–21 周岁"},
            {"value": "mid", "label": "22–55 周岁"},
            {"value": "b56_60", "label": "56–60 周岁"},
            {"value": "b61_65", "label": "61–65 周岁"},
            {"value": "gt65", "label": "65 周岁以上"},
        ],
    },
    {
        "id": "term", "text": "期望的贷款期限？",
        "options": [
            {"value": "half", "label": "半年左右"},
            {"value": "y1_3", "label": "1–3 年"},
            {"value": "y3_5", "label": "3–5 年"},
            {"value": "over5", "label": "5 年以上"},
            {"value": "unsure", "label": "还没想好"},
        ],
    },
    {
        "id": "amount", "text": "大约需要贷多少？",
        "options": [
            {"value": "lt10w", "label": "10 万以下"},
            {"value": "w10_20", "label": "10–20 万"},
            {"value": "w20_100", "label": "20–100 万"},
            {"value": "w100_300", "label": "100–300 万"},
            {"value": "gt300w", "label": "300 万以上"},
        ],
    },
]

# ── 硬门槛表：band 与条款区间的边界判定 ──────────────────────────────
# 语义：band 完全落在条款区间内 → 过；band 低于下限 / 高于上限 → 硬失败。
# 边界值（恰好 22、恰好 20 万）按「含」处理——说明书用「不超过/最高」措辞。

AGE_BANDS = {                       # (下限, 上限)，None = 开区间
    "lt18": (None, 17), "lt22": (18, 21), "mid": (22, 55),
    "b56_60": (56, 60), "b61_65": (61, 65), "gt65": (66, None),
}
AGE_GATES = {                       # (下限, 上限, 条款原文摘要)，页码都是 P1
    "anju_loan": (18, 65, "年满18周岁且不超过65周岁"),
    "lexiang_loan": (22, 55, "年满22周岁且不超过55周岁"),
    "xingwang_loan": (18, 60, "年龄在18周岁至60周岁之间"),
}

# 用途是第一道闸：三款产品用途正交，选对用途基本就选定了产品。
# (verdict, 文案, 引用)：match = 主匹配；gate = 硬失败
PURPOSE = {
    "buy": {
        "anju_loan": ("match", "住房购置贷款，为首套/改善型购房设计", "anju_loan P1"),
        "lexiang_loan": ("gate", "说明书明文禁止贷款资金用于购房", "lexiang_loan P3"),
        "xingwang_loan": ("gate", "仅限企业生产经营用途", "xingwang_loan P1"),
    },
    "consume": {
        "anju_loan": ("gate", "为住房购置贷款，不适用于一般消费", "anju_loan P1"),
        "lexiang_loan": ("match", "个人消费贷款，覆盖装修/教育/旅游/医疗等场景", "lexiang_loan P1"),
        "xingwang_loan": ("gate", "仅限企业生产经营用途", "xingwang_loan P1"),
    },
    "business": {
        "anju_loan": ("gate", "为住房购置贷款，不适用于经营周转", "anju_loan P1"),
        "lexiang_loan": ("gate", "说明书明文禁止用于生产经营活动", "lexiang_loan P3"),
        "xingwang_loan": ("match", "小微企业经营贷款，为生产经营周转设计", "xingwang_loan P1"),
    },
}

TERM_BANDS = {                      # (下限年, 上限年)；over5 从 5.01 起 = 严格大于 5
    "half": (0.5, 0.5), "y1_3": (1, 3), "y3_5": (3, 5),
    "over5": (5.01, 30), "unsure": None,
}
TERM_GATES = {                      # (下限年, 上限年, 条款)，页码都是 P2
    "anju_loan": (1, 30, "期限最短1年、最长30年"),
    "lexiang_loan": (0.25, 5, "期限最短3个月、最长5年"),
    "xingwang_loan": (0.5, 5, "期限最短6个月、最长5年"),
}

AMOUNT_BANDS = {                    # (下限万, 上限万)；gt300w 从 301 起
    "lt10w": (0.5, 10), "w10_20": (10, 20), "w20_100": (20, 100),
    "w100_300": (100, 300), "gt300w": (301, 1000),
}
AMOUNT_GATES = {                    # (下限万, 上限万, 条款)，页码都是 P2
    "anju_loan": (None, 500, "单户贷款额度上限500万元"),
    "lexiang_loan": (0.5, 20, "额度最低5千元、最高20万元"),
    "xingwang_loan": (10, 300, "单户授信最低10万元、最高300万元"),
}

# 特色加分：各自说明书 P1 的产品特色，用途命中才加（不是普适加分）
FEATURE = {
    ("buy", "anju_loan"): ("期限最长可达30年，还款压力小", "anju_loan P1"),
    ("consume", "lexiang_loan"): ("纯信用线上办理，最快30分钟到账", "lexiang_loan P1"),
    ("business", "xingwang_loan"): ("随借随还、按日计息，授信内循环使用", "xingwang_loan P1"),
}

# ── 月供估算：公式取自说明书 P3，基准费率 + 期限溢价取自 P2 ──────────
RATE_BASE = {   # (基准年利率%, 口径说明) —— 三档里取最常见的普通档
    "anju_loan": (3.95, "首套基准"),
    "lexiang_loan": (6.50, "普通客户基准"),
    "xingwang_loan": (5.80, "信用类基准"),
}
TERM_PREMIUM = {                    # 三份手册 P2 的期限溢价表完全相同
    "half": (0.00, "6个月"), "y1_3": (0.20, "3年（区间上限）"),
    "y3_5": (0.45, "5年（区间上限）"), "over5": (0.80, "30年（上限）"),
}
EST_MONTHS = {"half": 6, "y1_3": 36, "y3_5": 60, "over5": 360}
EST_AMOUNT_WAN = {"lt10w": 8, "w10_20": 15, "w20_100": 60,
                  "w100_300": 200, "gt300w": 400}


def monthly_payment(principal_yuan: float, annual_rate_pct: float,
                    months: int) -> float:
    """等额本息月供——公式逐字取自各说明书 P3「6.1 等额本息还款法」。

    冒烟测试用手册自带示例校准：100万/4.75%/360期 ≈ 5,216 元
    [anju_loan P3]、10万/6.70%/36期 ≈ 3,074 元 [lexiang_loan P3]、
    50万/4.40%/36期 ≈ 14,851 元 [xingwang_loan P3]。
    """
    r = annual_rate_pct / 100 / 12
    f = (1 + r) ** months
    return principal_yuan * r * f / (f - 1)


def _band_fail(band, gate) -> str | None:
    """band (lo, hi) 对 gate (lo, hi) 的越界判定（冒烟抓过 bug：开区间 band）。

    low  两条路径：整段顶到下限以下（hi < g_lo，覆盖 lt18 这类开区间
         band——band 下界是 None，只看下界会漏判）；或段起点低于下限。
    high 一条路径：段起点已到上限（lo >= g_hi）——需求区间从上限起步
         就按硬失败（金融场景宁可拦错推荐，不可放行超额期望）；从上限
         之下跨过去的骑线区间（如 300 万以上 vs 安居 500 万上限）不拦，
         走 concerns「触及上限」如实告知。
    """
    lo, hi = band
    g_lo, g_hi = gate
    if hi is not None and g_lo is not None and hi < g_lo:
        return "low"
    if lo is not None and g_lo is not None and lo < g_lo:
        return "low"
    if lo is not None and lo >= g_hi:
        return "high"
    return None


def _validate(answers: dict) -> None:
    """答案合法性：值必须来自问卷选项；条件题按用途补查。"""
    allowed = {q["id"]: {o["value"] for o in q["options"]} for q in QUESTIONS}
    for key in ("purpose", "age", "term", "amount"):
        if answers.get(key) not in allowed[key]:
            raise ValueError(f"问卷答案不完整或非法：{key}")
    if answers["purpose"] == "business" and answers.get("biz_years") not in allowed["biz_years"]:
        raise ValueError("问卷答案不完整或非法：biz_years")


def _score_product(company: str, answers: dict) -> dict:
    """单产品：硬门槛（不过=不适合）→ 软评分 → 理由/顾虑清单。"""
    reasons: list[dict] = []
    concerns: list[dict] = []
    gates: list[dict] = []

    # 1) 用途（第一道闸）
    verdict, text, cite = PURPOSE[answers["purpose"]][company]
    if verdict == "gate":
        gates.append({"text": text, "cite": cite})
    else:
        reasons.append({"text": f"用途匹配：{text}", "cite": cite})

    # 2) 兴旺贷条件题：经营满 2 年
    if company == "xingwang_loan" and answers["purpose"] == "business":
        if answers["biz_years"] == "no":
            gates.append({"text": "要求企业正常经营满2年", "cite": "xingwang_loan P1"})
        else:
            reasons.append({"text": "企业经营已满2年，满足客群要求",
                            "cite": "xingwang_loan P1"})

    # 3) 年龄
    band = AGE_BANDS[answers["age"]]
    g_lo, g_hi, clause = AGE_GATES[company]
    fail = _band_fail(band, (g_lo, g_hi))
    if fail:
        side = "未达下限" if fail == "low" else "超出上限"
        gates.append({"text": f"年龄{side}（要求{clause}）", "cite": f"{company} P1"})
    else:
        reasons.append({"text": f"年龄符合要求（{clause}）", "cite": f"{company} P1"})

    # 4) 期限（「还没想好」不设闸，只少给分）
    t_band = TERM_BANDS[answers["term"]]
    t_g = TERM_GATES[company]
    if t_band is not None:
        fail = _band_fail(t_band, (t_g[0], t_g[1]))
        if fail:
            side = "短于最短期限" if fail == "low" else "超出最长期限"
            gates.append({"text": f"期望期限{side}（{t_g[2]}）", "cite": f"{company} P2"})
        else:
            reasons.append({"text": f"期望期限可满足（{t_g[2]}）", "cite": f"{company} P2"})

    # 5) 金额
    a_band = AMOUNT_BANDS[answers["amount"]]
    a_g = AMOUNT_GATES[company]
    fail = _band_fail(a_band, (a_g[0] if a_g[0] is not None else -1, a_g[1]))
    if fail == "high":
        gates.append({"text": f"需求金额超出额度（{a_g[2]}）", "cite": f"{company} P2"})
    elif fail == "low":
        gates.append({"text": f"需求金额低于起贷额（{a_g[2]}）", "cite": f"{company} P2"})
    else:
        reasons.append({"text": f"需求金额在额度范围内（{a_g[2]}）",
                        "cite": f"{company} P2"})
        if a_band[1] is not None and a_band[1] >= a_g[1]:
            concerns.append({"text": f"该区间已触及额度上限（{a_g[2]}）",
                             "cite": f"{company} P2"})

    if gates:                        # 硬门槛不过：不评分，只报不适合原因
        return {"company": company, "name": PRODUCTS[company], "eligible": False,
                "score": 0, "reasons": reasons, "concerns": concerns,
                "gates": gates}

    # ── 软评分：40 底分 + 五维（用途20/年龄15/期限15/金额10/特色5），封顶100 ──
    score = 40 + 20 + 15 + 10
    score += 15 if t_band is not None else 8      # 「还没想好」折半给分
    feat = FEATURE.get((answers["purpose"], company))
    if feat:
        score += 5
        reasons.append({"text": f"特色契合：{feat[0]}", "cite": feat[1]})
    # 如实告知：购房还有前置条件（不是打分项，是义务披露）
    if answers["purpose"] == "buy" and company == "anju_loan":
        concerns.append({"text": "需已签订购房合同并支付规定比例首付",
                         "cite": "anju_loan P1"})
    return {"company": company, "name": PRODUCTS[company], "eligible": True,
            "score": min(score, 100), "reasons": reasons,
            "concerns": concerns, "gates": []}


def _estimate(company: str, answers: dict) -> dict | None:
    """推荐产品的月供估算：期限未定就明说算不了，不硬凑。"""
    t, a = answers.get("term"), answers.get("amount")
    if not t or t == "unsure" or not a:
        return None
    base, base_note = RATE_BASE[company]
    prem, term_label = TERM_PREMIUM[t]
    rate = round(base + prem, 2)
    wan = EST_AMOUNT_WAN[a]
    return {
        "amount_wan": wan,
        "term_label": term_label,
        "rate": rate, "base": base, "premium": prem, "base_note": base_note,
        "monthly": round(monthly_payment(wan * 10000, rate, EST_MONTHS[t])),
        "months": EST_MONTHS[t],
        "cite": f"{company} P2",
        "formula_cite": f"{company} P3",
    }


def assess(answers: dict) -> dict:
    """主入口：硬门槛 → 软评分 → 排序 → 推荐卡数据（纯函数，可复现）。"""
    _validate(answers)
    results = [_score_product(c, answers) for c in PRODUCTS]
    eligible = sorted((r for r in results if r["eligible"]),
                      key=lambda r: (-r["score"], r["company"]))
    winner = eligible[0] if eligible else None
    if winner:
        winner["estimate"] = _estimate(winner["company"], answers)
    order = eligible + [r for r in results if not r["eligible"]]
    headline = (f"综合匹配度最高：{winner['name']}（{winner['score']}/100）"
                if winner else "按您的情况，三款产品目前均不适合")
    return {"headline": headline,
            "winner": winner["company"] if winner else None,
            "products": order, "method": METHOD_NOTE}
