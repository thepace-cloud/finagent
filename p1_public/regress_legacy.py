"""Run legacy 18-question policy without overwriting its existing result files."""
import json
import os
from pathlib import Path
import sys
import torch

torch.set_num_threads(2)
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
os.chdir(ROOT.parent)
os.environ["HF_HUB_OFFLINE"]="1"
from sentence_transformers import SentenceTransformer
import v3_eval as legacy
from v3_hybrid import BM25, hybrid_search
from v3_m3 import load

model=SentenceTransformer(str(ROOT.parent/"models/pmml12"),local_files_only=True)
chunks,ids,vectors=load()
legacy.CHUNK_BY_ID=chunks
bm25=BM25([chunks[c]["text"] for c in ids],ids)
rows,log=legacy.run_mode("hybrid",lambda q:hybrid_search(model,vectors,ids,bm25,q,k=3))
summary=legacy.summarize(rows,"unchanged legacy hybrid")
(ROOT/"results/legacy18.json").write_text(json.dumps({"scope":"Legacy scoring only: retrieval/citation whitelist/refusal keyword; not factual answer grading", "summary":summary,"rows":rows,"log":log},ensure_ascii=False,indent=2),encoding="utf-8")
print("\n".join(summary))
