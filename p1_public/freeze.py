"""Select a policy using development metrics only and freeze implementation hashes."""
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
out=ROOT/"selection.json"
if out.exists():
    raise SystemExit("Selection already frozen; refuse overwrite")
dev=json.loads((ROOT/"results/dev.json").read_text(encoding="utf-8"))["summary"]
a,b=dev["baseline"],dev["decomposed"]
selected="decomposed" if b["evidence_complete"]>=a["evidence_complete"] and b["automated_pass"]>a["automated_pass"] else "baseline"
manifest={"selected":selected,"selection_data":"dev only", "dev_metrics":dev,
          "frozen_before_test":True,"hashes":{name:sha256((ROOT/name).read_bytes()).hexdigest() for name in ["engine.py","evaluate.py","cases_v2.json","sources.json","passages.json"]}}
out.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
print(selected)
