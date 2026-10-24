from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import app as api


class APITests(unittest.TestCase):
    def setUp(self):
        api.app.state.engine=SimpleNamespace(
            sources=[{"id":"a"}],passages={"a:p1":{"id":"a:p1","doc_id":"a","text":"最高100万元","source_url":"https://example.com"}},
            retrieve=lambda *args,**kwargs:([(1,"a:p1")],{"policy":"decomposed"}))
        self.client=TestClient(api.app)

    def test_calculation_does_not_call_llm(self):
        with patch.object(api,"generate",side_effect=AssertionError("should not call LLM")):
            result=self.client.post("/answer",json={"question":"等额本息月供，本金12000元，合同年利率0%，期限12个月"})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()["answer"]["facts"]["monthly_payment"],"1000.00元")

    def test_invalid_citation_is_not_returned_as_answer(self):
        fake={"status":"answered","facts":{"a.amount":"100万元"},"evidence":{"a.amount":["fake:p9"]},"quotes":{"a.amount":"最高100万元"}}
        with patch.object(api,"generate",return_value=fake):
            result=self.client.post("/answer",json={"question":"最高金额？"}).json()
        self.assertEqual(result["answer"]["status"],"insufficient")
        self.assertEqual(result["answer"]["facts"],{})
        self.assertEqual(result["sources"],[])

    def test_valid_answer_includes_resolved_source(self):
        fake={"status":"answered","facts":{"a.amount":"100万元"},"evidence":{"a.amount":["a:p1"]},"quotes":{"a.amount":"最高100万元"}}
        with patch.object(api,"generate",return_value=fake):
            result=self.client.post("/answer",json={"question":"最高金额？"}).json()
        self.assertEqual(result["sources"][0]["id"],"a:p1")

    def test_wrong_number_with_real_quote_is_blocked(self):
        fake={"status":"answered","facts":{"a.amount":"200万元"},"evidence":{"a.amount":["a:p1"]},"quotes":{"a.amount":"最高100万元"}}
        with patch.object(api,"generate",return_value=fake):
            result=self.client.post("/answer",json={"question":"最高金额？"}).json()
        self.assertEqual(result["answer"]["status"],"insufficient")


if __name__=="__main__":
    unittest.main()
