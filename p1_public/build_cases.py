"""Freeze 60 source-checked synthetic tasks, with intent-grouped dev/test split."""
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
P = {p["id"]: p for p in json.loads((ROOT / "passages.json").read_text(encoding="utf-8"))}
S = {s["id"]: s for s in json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))}
CASES = []


def add(category, group, question, refs, values, status="answered", missing=None):
    for ref in refs:
        assert ref in P, ref
    CASES.append({"id": f"q{len(CASES)+1:02d}", "category": category, "group": group,
                  "question": question, "gold": refs, "expected": values,
                  "status": status, "missing": missing or [],
                  "label_review": "AI checked against downloaded source; no human review"})


single = [
    ("national_student", "max_years", 10, "国家助学贷款的最长期限是多少年？", "22年"),
    ("overseas_student", "max_years", 8, "个人留学贷款最长期限是多少年？", "7年"),
    ("unsecured", "max_amount", 6, "个人无抵质押消费贷款的最高金额是多少万元？", "100万元"),
    ("mortgage_consumer", "max_years", 8, "个人抵押消费贷款最长期限是多少年？", "5年"),
    ("pledge_consumer", "min_amount", 6, "个人质押类消费贷款的起贷金额是多少元？", "1000元"),
    ("auto", "max_years", 8, "个人消费类汽车贷款最长期限是多少年？", "5年"),
    ("e_loan", "max_amount", 6, "中银E贷贷款金额上限是多少万元？", "30万元"),
    ("suixin", "max_amount", 6, "随心智贷的额度上限是多少万元？", "50万元"),
    ("commercial_property", "max_years", 6, "个人商业用房贷款最长期限是多少年？", "10年"),
    ("first_home", "rmb_max_years", 16, "个人一手住房人民币贷款最长期限是多少年？", "30年"),
]
for doc, attr, para, q, value in single:
    add("single", f"{doc}:{attr}", q, [f"{doc}:p{para}"], {f"{doc}.{attr}": value})

multi = [
    ("unsecured", 6, 8, "个人无抵质押消费贷款最高能贷多少万元、最长多少年？", {"max_amount": "100万元", "max_years": "5年"}),
    ("mortgage_consumer", 6, 8, "个人抵押消费贷款的金额上限和最长期限分别是多少？", {"max_amount": "100万元", "max_years": "5年"}),
    ("auto", 6, 8, "个人消费类汽车贷款的最高金额和最长期限分别是多少？", {"max_amount": "100万元", "max_years": "5年"}),
    ("overseas_student", 6, 8, "个人留学贷款单笔最高多少万元，最长期限多少年？", {"single_max": "30万元", "max_years": "7年"}),
    ("suixin", 6, 8, "随心智贷额度最高多少万元，单笔用款最长多少年？", {"max_amount": "50万元", "single_max_years": "5年"}),
    ("national_student", 8, 10, "国家助学贷款本专科生每年额度上限及贷款最长期限分别是多少？", {"undergrad_annual": "20000元", "max_years": "22年"}),
    ("pledge_consumer", 6, 8, "个人质押类消费贷款最低金额和最长期限分别是多少？", {"min_amount": "1000元", "max_years": "1年"}),
    ("e_loan", 6, 8, "中银E贷最高金额和额度有效期上限分别是多少？注意额度期限与单笔期限的区别。", {"max_amount": "30万元", "credit_max_years": "1年"}),
    ("commercial_property", 5, 6, "个人商业用房贷款金额最高占房价多少，最长借多少年？", {"max_ratio": "50%", "max_years": "10年"}),
    ("first_home", 16, 20, "按一手住房贷款说明页原文，其人民币最长期限和贷款比例上限分别是多少？保留监管变化时从其规定的限定。", {"rmb_max_years": "30年", "page_max_ratio": "70%"}),
]
for doc, a, b, q, values in multi:
    add("multi", f"{doc}:amount_term", q, [f"{doc}:p{a}", f"{doc}:p{b}"], {f"{doc}.{k}": v for k,v in values.items()})

pairs = [
    ("unsecured", "mortgage_consumer", "max_years", 8, 8, "5年", "5年"),
    ("auto", "overseas_student", "max_years", 8, 8, "5年", "7年"),
    ("suixin", "e_loan", "max_amount", 6, 6, "50万元", "30万元"),
    ("pledge_consumer", "commercial_property", "max_years", 8, 6, "1年", "10年"),
    ("national_student", "first_home", "max_years", 10, 16, "22年", "30年"),
    ("unsecured", "e_loan", "max_amount", 6, 6, "100万元", "30万元"),
    ("mortgage_consumer", "auto", "max_amount", 6, 6, "100万元", "100万元"),
    ("overseas_student", "e_loan", "max_years", 8, 8, "7年", "1年"),
    ("first_home", "commercial_property", "max_ratio", 20, 5, "70%", "50%"),
    ("suixin", "pledge_consumer", "max_years", 8, 8, "5年", "1年"),
]
for a,b,attr,pa,pb,va,vb in pairs:
    metric = {"max_years":"期限上限（中银E贷仅比较额度期限；一手住房仅比较人民币）", "max_amount":"金额上限", "max_ratio":"该说明页载明的贷款比例上限"}[attr]
    q = f"比较{S[a]['title']}与{S[b]['title']}的{metric}，分别列出，保留原文限定。"
    add("compare", f"compare:{a}:{b}:{attr}", q, [f"{a}:p{pa}",f"{b}:p{pb}"], {f"{a}.{attr}":va,f"{b}.{attr}":vb})

for i in range(10):
    field = ("annual_rate", "term_months", "principal")[i % 3]
    q = {"annual_rate":f"按等额本息算月供，本金{100000+i*10000}元，期限{12+i}个月，合同年利率没定。应先追问什么？",
         "term_months":f"按等额本息算月供，本金{100000+i*10000}元，合同年利率4%，期限没给。应先追问什么？",
         "principal":f"按等额本息算月供，期限{12+i}个月，合同年利率4%，借款金额没给。应先追问什么？"}[field]
    add("missing", f"missing:{field}", q, [], {}, "clarify", [field])

unknown = ["个人无抵质押消费贷款是否保证一天放款？", "个人抵押消费贷款的客服经理姓名是什么？", "中银E贷审核模型有多少参数？", "随心智贷对所有人执行的唯一固定利率是多少？", "个人质押类消费贷款的实时排队人数是多少？", "个人消费类汽车贷款的指定车牌号是什么？", "国家助学贷款下一年度一定会上调到多少元？", "个人留学贷款每个申请人的最终获批利率是多少？", "个人住房公积金贷款在未指定城市时全国统一的额度数字是多少？", "个人商业用房贷款下个月一定降息多少？"]
for i,q in enumerate(unknown):
    add("no_answer", f"unknown:{i}", q, [], {}, "insufficient")

noise = [
    ("unsecured", "guarantee", 16, "个人无抵质押消费贷款采用什么担保方式？不要套用个人抵押消费贷款的条款。", "信用"),
    ("mortgage_consumer", "guarantee", 16, "个人抵押消费贷款采用什么担保方式？不要用无抵质押消费贷款的规则。", "抵押"),
    ("pledge_consumer", "guarantee", 16, "个人质押类消费贷款的担保方式是什么？不是抵押消费贷款。", "质押"),
    ("e_loan", "guarantee", 16, "中银E贷采用什么担保方式？不要混入汽车贷款的要求。", "信用"),
    ("auto", "guarantee", 16, "个人消费类汽车贷款支持哪些担保方式？请勿套用中银E贷。", "保证、抵押或保证+抵押"),
    ("national_student", "postgrad_annual", 8, "国家助学贷款研究生每年上限是多少元？不要使用本专科生的额度。", "25000元"),
    ("overseas_student", "cumulative_max", 6, "个人留学贷款累计金额上限多少万元？注意不是单笔额度。", "180万元"),
    ("first_home", "fx_max_years", 16, "个人一手住房的外币贷款最长期限多少年？不是人民币期限。", "8年"),
    ("commercial_student", "living_multiplier", 6, "商业助学贷款生活费限额是所在城市年低保标准的几倍？不要回答国家助学额度。", "2倍"),
    ("suixin", "min_draw", 6, "随心智贷单笔用款最低多少元？注意不是额度上限。", "1000元"),
]
for doc, attr, para, q, value in noise:
    add("distractor", f"{doc}:{attr}", q, [f"{doc}:p{para}"], {f"{doc}.{attr}":value})

# All rewrites of a missing-field intent stay in one split; others grouped by intent.
for c in CASES:
    c["split"] = "dev" if int(sha256(c["group"].encode()).hexdigest(),16) % 2 == 0 else "test"
assert len(CASES) == 60
from decimal import Decimal, ROUND_HALF_UP
for i,(principal,rate,months) in enumerate([(100000,4,24),(200000,3.6,36),(50000,0,12),(80000,4.5,18),(120000,5,60),(60000,3,24)]):
    r = rate / 1200
    payment = principal / months if not rate else principal*r*(1+r)**months/((1+r)**months-1)
    value = str(Decimal(str(payment)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) + '元'
    add("calculation", f"calc:{i}", f"使用等额本息公式计算：本金{principal}元，合同年利率{rate}%，期限{months}个月。输出monthly_payment，单位元，四舍五入保留两位小数。这里利率已明确给出，不需查询产品利率。", [], {"monthly_payment":value})
    CASES[-1]["calculation"] = {"principal":principal,"annual_rate":rate,"term_months":months}
    CASES[-1]["split"] = "dev" if i % 2 == 0 else "test"
dest = ROOT / "cases_v2.json"
if dest.exists():
    raise SystemExit("Frozen cases exist; refuse overwrite")
dest.write_text(json.dumps(CASES,ensure_ascii=False,indent=2),encoding="utf-8")
(ROOT / "cases_v2.sha256").write_text(sha256(dest.read_bytes()).hexdigest(),encoding="ascii")
print({split:sum(c['split']==split for c in CASES) for split in ['dev','test']})
