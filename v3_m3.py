"""V3-M3: 检索 —— query 向量化 → 与全部 chunk 向量算余弦相似度 → top-k → 回查文本

手写检索（邪修纪律：无 FAISS / Chroma）。向量在 M2 已归一化
→ 余弦相似度 == 点积 == 一次矩阵乘算完所有 chunk。
"""
import json

import numpy as np
from sentence_transformers import SentenceTransformer

CHUNKS_FILE = "chunks.json"
EMBEDDINGS_FILE = "embeddings.json"
MODEL_PATH = "models/pmml12"

K = 3

TEST_QUERIES = [
    "贷款逾期了会怎么样，罚息怎么算",
    "我想买房子首付差一点，能申请什么贷款周转",
    "提前把钱还了要不要交违约金",
    "利率能不能打折优惠",
]


def load():
    """加载两个文件，建好两件东西：id→chunk 的回查表、id 列表 + 向量矩阵 V(20,384)"""
    with open(CHUNKS_FILE, encoding="utf-8") as f:
        chunks = json.load(f)
    with open(EMBEDDINGS_FILE, encoding="utf-8") as f:
        embeddings = json.load(f)

    chunk_by_id = {c["chunk_id"]: c for c in chunks}
    ids = [e["chunk_id"] for e in embeddings]
    # 把 20 个向量按固定顺序堆成矩阵：每行一个 chunk 的坐标
    V = np.array([e["vector"] for e in embeddings])
    return chunk_by_id, ids, V


def search(model, V, ids, query, k=K):
    """query → 向量 → 点积得 20 个相似度 → 取前 k 的下标 → 返回 (score, chunk_id)"""
    q = model.encode([query], normalize_embeddings=True)[0]
    scores = V @ q                       # (20,384) × (384,) → (20,)：一次算完所有点积
    top_idx = np.argsort(scores)[::-1][:k]  # 降序排列，取前 k 个位置
    return [(float(scores[i]), ids[i]) for i in top_idx]


def main():
    chunk_by_id, ids, V = load()
    model = SentenceTransformer(MODEL_PATH)

    for query in TEST_QUERIES:
        print(f"\n=== 问: {query} ===")
        for rank, (score, cid) in enumerate(search(model, V, ids, query), start=1):
            chunk = chunk_by_id[cid]
            print(f"  #{rank} [{cid}] 相似度 {score:.4f}  [P{chunk['page']}] "
                  f"{chunk['text'][:70].replace(chr(10), ' ')}...")


if __name__ == "__main__":
    main()
