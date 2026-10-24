"""Exercise real model + retrieval via the ASGI application lifespan."""
import json
import torch
torch.set_num_threads(2)
from fastapi.testclient import TestClient
from app import app
from engine import ROOT

records=[]
with TestClient(app) as client:
    health=client.get("/health")
    assert health.status_code==200 and health.json()["sources"]==12
    for request in [
        {"question":"比较随心智贷与中银E贷的额度上限，分别是多少万元？", "requested_fields":["suixin.max_amount","e_loan.max_amount"]},
        {"question":"按等额本息算月供，本金100000元，期限24个月，合同年利率没定。"},
        {"question":"按等额本息算月供，本金100000元，合同年利率4%，期限24个月。", "requested_fields":["monthly_payment"]},
    ]:
        response=client.post("/answer",json=request)
        assert response.status_code==200
        records.append({"request":request,"response":response.json()})
    assert records[0]["response"]["answer"]["status"]=="answered"
    assert len(records[0]["response"]["sources"])>=2
    assert records[1]["response"]["answer"]["status"]=="clarify"
    assert records[2]["response"]["answer"]["facts"]["monthly_payment"]=="4342.49元"
(ROOT/"results/api_smoke.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
print("Live ASGI integration: 3 requests passed")
