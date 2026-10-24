"""Layered retrieval, oracle-evidence generation, grounding and calculation checks."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

import torch
torch.set_num_threads(2)
from engine import ROOT, Engine, calculator, generate, ground, SYSTEM


def canonical(value):
    text=str(value).replace(",", "").replace("，", "").strip()
    amount=re.fullmatch(r"([\d.]+)\s*(万元|元)",text)
    if amount:
        return str(round(float(amount[1])*(10000 if amount[2]=="万元" else 1),2))+"元"
    return re.sub(r"[\s、，。；;‘’“”\"()（）]", "",text)


def field_match(actual,expected,key):
    if isinstance(actual,(int,float)):
        number=re.match(r"([\d.]+)",str(expected))
        return bool(number) and abs(float(actual)-float(number[1]))<0.011
    expected=str(expected)
    text=str(actual)
    for a,b in (("一年","1年"),("五年","5年"),("两倍","2倍")):
        text=text.replace(a,b)
    numeric=re.fullmatch(r"([\d.]+)(万元|元|年|%|倍)",expected)
    if numeric:
        values=re.findall(r"([\d.]+)\s*(万元|元|年|%|倍)",text)
        if not values:
            return False
        target=canonical(expected)
        return all(canonical(n+u)==target for n,u in values)
    if key.endswith(".guarantee"):
        clean=lambda t:canonical(t).replace("采用","").replace("担保","").replace("方式","")
        return clean(text)==clean(expected)
    return canonical(actual)==canonical(expected)


def grade(case,answer,context):
    errors=ground(answer,context)
    facts=answer.get("facts",{})
    matched={key:field_match(facts.get(key,""),value,key) for key,value in case["expected"].items()}
    status_ok=answer.get("status")==case["status"]
    missing_ok=set(answer.get("missing",[]))==set(case["missing"])
    # Expected evidence is not passed to generation; check references separately here.
    for key in case["expected"]:
        if key=="monthly_payment":
            continue
        if not set(answer.get("evidence",{}).get(key,[])) & set(case["gold"]):
            errors.append(key+":wrong_source_for_expected_fact")
    return {"status_ok":status_ok,"missing_ok":missing_ok,"field_matches":matched,
            "grounding_errors":errors,
            "automated_pass":status_ok and missing_ok and all(matched.values()) and not errors
                             and (bool(facts) if case["status"]=="answered" else not facts)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--split",choices=["dev","test"],required=True)
    parser.add_argument("--generate",action="store_true")
    args=parser.parse_args()
    engine=Engine()
    cases=json.loads((ROOT/"cases_v2.json").read_text(encoding="utf-8"))
    cases=[c for c in cases if c["split"]==args.split]
    rows=[]
    for c in cases:
        for policy in ("baseline","decomposed","oracle"):
            start=time.perf_counter()
            if policy=="oracle":
                hits=[(1,p) for p in c["gold"]]
                plan={"policy":"oracle", "note":"diagnostic only; not a deployable retrieval policy"}
            else:
                hits,plan=engine.retrieve(c["question"],policy,k=6)
            ids=[pid for _,pid in hits]
            gold=set(c["gold"])
            ranks=[ids.index(pid)+1 for pid in gold if pid in ids]
            rows.append({"id":c["id"],"case":c,"policy":policy,"hits":ids,"plan":plan,
                         "retrieval_seconds":time.perf_counter()-start,
                         "recall":len(gold&set(ids))/len(gold) if gold else None,
                         "complete":gold.issubset(ids) if gold else None,
                         "mrr":1/min(ranks) if ranks else (0 if gold else None)})
    results_dir=ROOT/"results"
    results_dir.mkdir(exist_ok=True)
    def run(row):
        context=[engine.passages[p] for p in row["hits"]]
        c=row["case"]
        cache_key=sha256(json.dumps([SYSTEM,c["question"],list(c["expected"]),context,row["policy"],
                                     os.getenv("DEEPSEEK_MODEL"),"calculator-v1"],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        cache=results_dir/"cache"/(cache_key+".json")
        cache.parent.mkdir(exist_ok=True)
        start=time.perf_counter()
        if cache.exists():
            answer=json.loads(cache.read_text(encoding="utf-8"))
        else:
            answer=calculator(c["question"]) if row["policy"]=="decomposed" else None
            if answer is None:
                for attempt in range(3):
                    try:
                        answer=generate(c["question"],list(c["expected"]),context)
                        break
                    except Exception as exc:
                        if attempt==2:
                            row["error_type"]=type(exc).__name__
                            row["generation_seconds"]=time.perf_counter()-start
                            return row
                        time.sleep(1+attempt)
            cache.write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding="utf-8")
        row.update(answer=answer,grade=grade(c,answer,context),generation_seconds=time.perf_counter()-start)
        return row
    if args.generate:
        pending=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(run,row) for row in rows]
            for i,future in enumerate(as_completed(futures),1):
                pending.append(future.result())
                if i%10==0:
                    print("completed",i,"/",len(rows),flush=True)
                (results_dir/f"{args.split}_checkpoint.json").write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding="utf-8")
        rows=sorted(pending,key=lambda r:(r["id"],r["policy"]))
    summary={}
    for policy in ("baseline","decomposed","oracle"):
        part=[r for r in rows if r["policy"]==policy]
        retrieval=[r for r in part if r["complete"] is not None]
        summary[policy]={"evidence_complete":sum(r["complete"] for r in retrieval),
                         "retrieval_tasks":len(retrieval),
                         "macro_recall":sum(r["recall"] for r in retrieval)/len(retrieval),
                         "mrr":sum(r["mrr"] for r in retrieval)/len(retrieval),
                         "automated_pass":sum(r.get("grade",{}).get("automated_pass",False) for r in part) if args.generate else None,
                         "tasks":len(part),"api_errors":sum("error_type" in r for r in part)}
    report={"scope":"AI-authored source-checked synthetic tasks; automated field/quote checks, no human semantic grading",
            "split":args.split,"evidence_budget":6,"model":os.getenv("DEEPSEEK_MODEL"),
            "hashes":{f:sha256((ROOT/f).read_bytes()).hexdigest() for f in ["sources.json","passages.json","cases_v2.json","engine.py","evaluate.py"]},
            "summary":summary,"rows":rows}
    (results_dir/f"{args.split}.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
