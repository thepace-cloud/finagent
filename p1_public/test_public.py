import json
from pathlib import Path
import unittest

from engine import ROOT, Engine, calculator, ground, monthly_payment
from evaluate import canonical, field_match, grade


class PublicTests(unittest.TestCase):
    def test_equivalent_bounds_and_units_without_wrong_numbers(self):
        self.assertTrue(field_match("不超过100万元","100万元","max_amount"))
        self.assertTrue(field_match("1000000元","100万元","max_amount"))
        self.assertTrue(field_match(5,"5年","max_years"))
        self.assertFalse(field_match("最高100万元，或200万元","100万元","max_amount"))
        self.assertFalse(field_match("5000元","100万元","max_amount"))
        self.assertTrue(field_match("抵押担保方式","抵押","product.guarantee"))
    def test_calculator_requires_each_parameter(self):
        result=calculator("按等额本息算月供，本金100000元，期限24个月，合同年利率没定")
        self.assertEqual(result["status"],"clarify")
        self.assertEqual(result["missing"],["annual_rate"])
        self.assertEqual(result["facts"],{})

    def test_calculator_zero_and_positive_rates(self):
        self.assertEqual(monthly_payment(12000,0,12),"1000.00元")
        self.assertEqual(monthly_payment(100000,4,24),"4342.49元")
        self.assertIsNone(calculator("个人留学贷款最长几年？"))
        with self.assertRaises(ValueError):
            monthly_payment(-1,4,24)

    def test_fake_citation_and_nonverbatim_quote_are_rejected(self):
        context=[{"id":"a:p1","text":"最高100万元"}]
        answer={"facts":{"a.amount":"100万元"},"evidence":{"a.amount":["b:p1"]},"quotes":{"a.amount":"最高100万元"}}
        self.assertTrue(ground(answer,context))
        answer["evidence"]["a.amount"]=["a:p1"]
        answer["quotes"]["a.amount"]="最高200万元"
        self.assertTrue(ground(answer,context))
        answer["quotes"]["a.amount"]="最高100万元"
        self.assertFalse(ground(answer,context))

    def test_valid_citation_does_not_make_wrong_number_pass(self):
        case={"status":"answered","expected":{"a.amount":"100万元"},"missing":[],"gold":["a:p1"]}
        answer={"status":"answered","facts":{"a.amount":"200万元"},"evidence":{"a.amount":["a:p1"]},"quotes":{"a.amount":"最高100万元"},"missing":[]}
        self.assertFalse(grade(case,answer,[{"id":"a:p1","text":"最高100万元"}])["automated_pass"])

    def test_dataset_group_isolation_and_source_integrity(self):
        cases=json.loads((ROOT/"cases_v2.json").read_text(encoding="utf-8"))
        passages={p["id"] for p in json.loads((ROOT/"passages.json").read_text(encoding="utf-8"))}
        groups={}
        for case in cases:
            groups.setdefault(case["group"],set()).add(case["split"])
            self.assertTrue(set(case["gold"])<=passages)
        self.assertTrue(all(len(splits)==1 for splits in groups.values()))
        self.assertEqual(len(cases),66)
        self.assertEqual(len({c["question"] for c in cases}),66)

    def test_product_and_facet_plan_stays_within_budget(self):
        engine=Engine.__new__(Engine)
        engine.aliases={"甲贷款":"a","乙贷款":"b"}
        engine.ranked=lambda query,group=None:[(1/(i+1),f"{group or 'all'}:{query}:{i}") for i in range(10)]
        hits,plan=engine.retrieve("比较甲贷款与乙贷款的金额和期限", "decomposed",k=6)
        self.assertEqual(len(hits),6)
        self.assertEqual(len({p for _,p in hits}),6)
        self.assertEqual({b["doc"] for b in plan["branches"]},{"a","b"})
        self.assertTrue(all("金额和期限" in b["query"] for b in plan["branches"]))

    def test_negated_distractor_is_not_a_target(self):
        engine=Engine.__new__(Engine)
        engine.aliases={"甲贷款":"a","乙贷款":"b"}
        engine.ranked=lambda query,group=None:[(1,f"{group}:p1")]
        _,plan=engine.retrieve("甲贷款担保方式是什么？不要套用乙贷款", "decomposed")
        self.assertEqual({b["doc"] for b in plan["branches"]},{"a"})


if __name__=="__main__":
    unittest.main()
