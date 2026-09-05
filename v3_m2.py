"""V3-M2: chunks.json → embeddings.json
每个 chunk 的文本变成一个 384 维向量（embedding），只存 chunk_id + vector。
文本不回存 —— 回查文本仍然走 chunks.json（chunk_id 是桥）。
"""
import json

from sentence_transformers import SentenceTransformer

CHUNKS_FILE = "chunks.json"
OUTPUT_FILE = "embeddings.json"

# 语料是中文 → 材料同款 all-MiniLM-L6-v2 是英文模型，改用同家族多语言版
# 本机 HuggingFace/hf-mirror 均不通 → 从 ModelScope 拉取，本地路径加载
MODEL_NAME = "models/pmml12"


def main():
    with open(CHUNKS_FILE, encoding="utf-8") as f:
        chunks = json.load(f)

    model = SentenceTransformer(MODEL_NAME)

    texts = [c["text"] for c in chunks]
    # normalize_embeddings=True: 每个向量长度拉成 1 → 余弦相似度 == 点积
    vectors = model.encode(texts, normalize_embeddings=True)

    # 只留 chunk_id + 向量（384 个小数）。text 不在这里，回查靠 chunks.json
    embeddings = [
        {"chunk_id": c["chunk_id"], "vector": vectors[i].tolist()}
        for i, c in enumerate(chunks)
    ]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(embeddings, f, ensure_ascii=False, indent=2)

    first = embeddings[0]
    print(f"共 {len(embeddings)} 个向量，维度 {len(first['vector'])}，已写入 {OUTPUT_FILE}")
    print(f"示例: {first['chunk_id']} → vector 前 5 个数: "
          f"{[round(x, 4) for x in first['vector'][:5]]}")


if __name__ == "__main__":
    main()
