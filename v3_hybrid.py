"""V3-M6 混合检索 —— BM25（词面）+ 向量（语义），RRF 排名融合

为什么升级（评测实证，见 v3_eval_results.txt）：
  - 语义盲区：query 换成语料原词「下浮」，向量相似度反而全场最低（0.5514）——
    MiniLM 分不清「优惠 ≈ 下浮」这类同义改写
  - 稀释：500 字长块里只有一小节相关，整块向量被无关内容冲淡（整块 0.5121 vs 单节 0.6627）
  - 后果：多块 1/5（相似块互挤座位）、g05 回归探针红
BM25 是纯词面匹配：原词命中直接得分，「下浮」两个字就是最强信号——专治换原词反而漏。

RRF 融合的是排名不是分数：余弦有界（0~1）、BM25 无界，量纲不可比；
排名是两张榜唯一的公共货币。RRF_K=60 压平榜一霸权（V3-M1 拷问讲过的权重旋钮）。

拷问主线：
  - BM25 三个参数：IDF 稀有词更值钱 / k1 词频饱和（出现 3 次 ≠ 3 倍强）/
    b 长度归一（长块不因长而白占分）
  - 为什么手写不装 rank_bm25、jieba？（红线：讲得清每个细节；
    字符二元组是「中文无空格」的零依赖最小解）
  - 每路召回 RECALL=10、融合回 K=3：座位数没变，变的是谁入座——
    这不是给系统加座（那是 K 越界），是两路投票换更好的坐法
"""
import math
import re
from collections import Counter, defaultdict

from v3_m3 import search as vector_search

K1 = 1.5      # 词频饱和：命中次数的边际收益递减
B = 0.75      # 长度归一强度：0 完全不看长度，1 全看
RRF_K = 60    # 排名融合压平旋钮：榜一 1/60 vs 榜二 1/61，不当独裁者
RECALL = 10   # 每路候选池宽度（座位仍是调用方给的 k）


def tokenize(text: str) -> list[str]:
    """中文无空格 → 去标点空白后切字符二元组：『利率下浮』→ [利率, 率下, 下浮]"""
    text = re.sub(r"[^\w]", "", text)
    return [text[i:i + 2] for i in range(len(text) - 1)]


class BM25:
    """20 块语料的词面检索。
    score(q,d) = Σ_t IDF(t) · tf·(k1+1) / (tf + k1·(1 - b + b·|d|/avgdl))
    """

    def __init__(self, docs: list[str], ids: list[str], k1=K1, b=B):
        self.k1, self.b, self.ids = k1, b, ids
        self.tf = [Counter(tokenize(d)) for d in docs]
        self.dl = [sum(t.values()) for t in self.tf]
        self.avgdl = sum(self.dl) / len(self.dl)
        self.N = len(docs)
        df: Counter = Counter()
        for t in self.tf:
            df.update(t.keys())
        self.df = df

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1)

    def search(self, query: str, k: int) -> list[tuple[float, str]]:
        """返回 [(score, chunk_id)]——与 v3_m3.search 同形状，可互换。"""
        terms = set(tokenize(query))
        scored = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                norm = self.k1 * (1 - self.b + self.b * self.dl[i] / self.avgdl)
                s += self._idf(t) * f * (self.k1 + 1) / (f + norm)
            scored.append((s, self.ids[i]))
        scored.sort(reverse=True)
        return scored[:k]


def rrf_fuse(rankings: list[list[tuple[float, str]]],
             k: int = RRF_K, top: int = 3) -> list[tuple[float, str]]:
    """多路 [(score, cid)] 榜 → 融合成一个榜。
    每块得分 = Σ 各路 1/(k + 名次)。与单路同形状返回。
    """
    score: defaultdict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (_, cid) in enumerate(ranking):
            score[cid] += 1 / (k + rank)
    ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return [(s, cid) for cid, s in ranked]   # items() 吐 (cid, s)——翻回 (s, cid) 契约


def hybrid_search(model, V, ids, bm25: BM25, query: str,
                  k: int = 3, recall: int = RECALL):
    """向量 + BM25 各召回 recall 宽，RRF 融合回 k 个座位。"""
    vec = vector_search(model, V, ids, query, k=recall)
    lex = bm25.search(query, k=recall)
    return rrf_fuse([vec, lex], top=k)


if __name__ == "__main__":
    # 自检：语义盲区案「下浮」——向量丢的，BM25 应该捡回来
    from sentence_transformers import SentenceTransformer
    from v3_m3 import load
    from v3_m4 import MODEL_PATH

    chunk_by_id, ids, V = load()
    bm25 = BM25([chunk_by_id[cid]["text"] for cid in ids], ids)
    model = SentenceTransformer(MODEL_PATH)

    for q in ["利率能不能下浮", "利率能不能打折优惠"]:
        vec = [cid for _, cid in vector_search(model, V, ids, q, k=3)]
        lex = [cid for _, cid in bm25.search(q, k=3)]
        hyb = [cid for _, cid in hybrid_search(model, V, ids, bm25, q, k=3)]
        print(f"\n{q!r}\n  向量 top3: {vec}\n  BM25 top3: {lex}\n  融合 top3: {hyb}")
