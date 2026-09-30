"""M2 适配测评冒烟 —— 三层断言说了算

  1. 公式校准：monthly_payment 对三份说明书 P3 自带的月供示例（100万/
     4.75%/360期≈5,216 等）——手册自己算好的数就是黄金测试向量；
  2. 画像断言：6 个代表性用户画像，硬门槛/推荐结果/月供估算逐一核对
     （含「三款全不适合」的诚实拒答路径——宁拒不错在测评路径同样成立）；
  3. 引用零编造：结果里每条 cite "doc PN" 必须真实存在于语料块——
     规则表挂错页码在这里当场爆炸，不会带病上线。
  另附确定性断言：同答案跑两遍，结果逐字节一致（LLM 做不到这一点）。
"""
from v3_m3 import load
from v5_assess import PRODUCTS, assess, monthly_payment


def check_formula() -> bool:
    """说明书 P3 示例即黄金向量（手册四舍五入到元，容差 ±5）。"""
    vectors = [  # (本金万, 年利率%, 期数, 手册月供, 出处)
        (100, 4.75, 360, 5216, "anju_loan P3"),
        (10, 6.70, 36, 3074, "lexiang_loan P3"),
        (50, 4.40, 36, 14851, "xingwang_loan P3"),
    ]
    ok = True
    for wan, rate, months, expect, cite in vectors:
        got = monthly_payment(wan * 10000, rate, months)
        hit = abs(got - expect) <= 5
        ok &= hit
        print(f"  {cite}: 算得 {got:,.0f} vs 手册 {expect:,} "
              f"{'✓' if hit else '✗'}")
    return ok


# (画像名, 答案, 断言函数)
def p_buyer(r):
    assert r["winner"] == "anju_loan", "购房青年应推安居贷"
    anju = next(p for p in r["products"] if p["company"] == "anju_loan")
    assert anju["score"] == 100, f"全维度命中应满分，得 {anju['score']}"
    assert anju["estimate"]["months"] == 360, "30年期估算"
    lex = next(p for p in r["products"] if p["company"] == "lexiang_loan")
    assert not lex["eligible"] and "购房" in lex["gates"][0]["text"]


def p_overage(r):
    assert r["winner"] is None, "56岁消费需求：乐享超龄，其余用途不符 → 全不适合"
    assert "均不适合" in r["headline"]


def p_biz_young(r):
    assert r["winner"] is None, "经营不满2年：兴旺被客群闸拦下 → 全不适合"
    xw = next(p for p in r["products"] if p["company"] == "xingwang_loan")
    assert "2年" in xw["gates"][0]["text"]


def p_big_consume(r):
    assert r["winner"] is None, "消费要20–100万：乐享上限20万 → 全不适合"
    lex = next(p for p in r["products"] if p["company"] == "lexiang_loan")
    assert "超出额度" in lex["gates"][0]["text"]


def p_boss(r):
    assert r["winner"] == "xingwang_loan", "经营满2年的企业主应推兴旺贷"
    est = next(p for p in r["products"] if p["company"] == "xingwang_loan")["estimate"]
    assert est["rate"] == 6.25, f"信用类5.80%+3-5年溢价0.45%=6.25%，得 {est['rate']}"
    assert 38000 < est["monthly"] < 40000, f"200万/5年/6.25% 月供≈3.89万，得 {est['monthly']}"


def p_minor(r):
    assert r["winner"] is None, "未满18岁：三款全部年龄闸拦下"


PROFILES = [
    ("购房青年", {"purpose": "buy", "age": "mid", "term": "over5",
                  "amount": "w100_300"}, p_buyer),
    ("56岁消费", {"purpose": "consume", "age": "b56_60", "term": "y1_3",
                  "amount": "lt10w"}, p_overage),
    ("经营不满2年", {"purpose": "business", "biz_years": "no", "age": "mid",
                     "term": "half", "amount": "w10_20"}, p_biz_young),
    ("大额消费", {"purpose": "consume", "age": "mid", "term": "y1_3",
                  "amount": "w20_100"}, p_big_consume),
    ("小微企业主", {"purpose": "business", "biz_years": "yes", "age": "mid",
                    "term": "y3_5", "amount": "w100_300"}, p_boss),
    ("未成年人", {"purpose": "consume", "age": "lt18", "term": "unsure",
                  "amount": "lt10w"}, p_minor),
]


def check_cites(r, known_pages) -> list[str]:
    """零编造断言：每条 cite 的 (doc, page) 必须真有对应语料块。"""
    bad = []

    def scan(items):
        for it in items:
            doc, pn = it["cite"].rsplit(" ", 1)
            if (doc, int(pn[1:])) not in known_pages:
                bad.append(it["cite"])

    for p in r["products"]:
        scan(p["reasons"] + p["concerns"] + p["gates"])
        if p.get("estimate"):
            scan([{"cite": p["estimate"]["cite"]},
                  {"cite": p["estimate"]["formula_cite"]}])
    return bad


def main():
    chunk_by_id, _, _ = load()
    known = {(c["company"], c["page"]) for c in chunk_by_id.values()}
    print(f"语料页锚点: {sorted(known)}")

    print("\n== 1) 公式校准（说明书 P3 示例）==")
    all_ok = check_formula()

    print("\n== 2) 画像断言 + 3) 引用零编造 ==")
    for name, answers, assert_fn in PROFILES:
        r1, r2 = assess(answers), assess(answers)
        assert r1 == r2, f"{name}: 确定性被破坏！"
        try:
            assert_fn(r1)
            bad = check_cites(r1, known)
            assert not bad, f"编造引用: {bad}"
            top = r1["products"][0]
            print(f"  {name}: {'✓ ' + r1['headline'] if r1['winner'] else '✓ 诚实全拒'}"
                  f"（首选 {top['name']} score={top['score']}）")
        except AssertionError as e:
            all_ok = False
            print(f"  {name}: ✗ {e}")

    print(f"\nM2 冒烟结论: {'全绿 ✓' if all_ok else '存在红项 ✗'}")


if __name__ == "__main__":
    main()
