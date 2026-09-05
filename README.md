# FinAgent —— 手写的财经问答 Agent（V1→V4）

一个**从零手写、不套 Agent 框架**的财经智能问答系统：基于三类贷款产品（安居贷 / 乐享贷 / 兴旺贷）的带页码语料，回答产品规则时可**溯源到原文页码**、**跨轮记住用户**、并能通过 **MCP 调用外部财经数据工具**。

> 简历承诺的每一条都能在代码里找到：Git 逐里程碑提交，可审计 demo 输出见下文。

---

## 版本演进（每个里程碑一次 git commit）

| 版本 | 一句话 | 关键代码 |
|---|---|---|
| **V1** | 手写最小 ReAct 循环（Thought→Action→Observation），用 stop 序列截断防模型自问自答 | `react.py` |
| **V2** | 原生 Tool Calling + **确定性分离**：两个财经计算工具（贷款期限溢价 / 等额本息月供）由确定性代码执行，模型只决定"调不调" | `m2b.py`、`tools.py` |
| **V3** | RAG 问答 + **页级引用**：500 字分块/50 字重叠/页码映射 → 多语言向量化(384维) → top-k 检索 → LLM 生成强制 `[产品 P页码]` → **宽进严出白名单校验**防编页码 | `v3_m1~m4.py` |
| **V4** | 系统集成：**Redis 三 key 分层记忆** + **SQLAlchemy 三表持久化** + **MCP 财经数据工具**，同一条对话可审计 | `v4_*.py` |

**V5（规划中）**：Task Router + Validator 受控编排收口，把 RAG/工具路径装进确定性边界。

---

## 目录

```
├── llm.py                 # LLM 客户端（DeepSeek，OpenAI 兼容）
├── react.py  m2b.py       # V1 ReAct / V2 工具调用
├── chunks.json            # V3 分块语料（20 块，含页码映射）
├── embeddings.json        # V3 向量库（chunk_id + 384 维向量）
├── v3_m1.py ~ v3_m4.py    # V3 分块/向量化/检索/RAG 闭环
├── v3_golden.json         # 评估集 golden 样例
├── v4_store.py            # 存储抽象：真 Redis / dict 降级同接口
├── v4_memory.py           # 记忆三 key：chat_history / profile / summary
├── v4_db.py               # SQLAlchemy 三表 users/conversations/messages
├── v4_mcp_server.py       # MCP Server：get_stock_info
├── v4_mcp_client.py       # MCP Client：initialize→list_tools→call_tool
├── v4_demo.py             # V4 集成 demo（一条会记忆的对话）
├── m4_results.txt         # V3 跑分输出（含故意留的回归坏例）
└── v4_demo_result.txt     # V4 集成 demo 输出（可审计）
```

---

## 怎么跑

### 1. 依赖与密钥

```bash
pip install -r requirements.txt
# 复制 .env.example 为 .env，填入 DeepSeek key
```

### 2. 向量模型（本仓库不含，按 README 下载）

V3/V4 运行时加载本地向量模型（多语言 MiniLM，384 维）。从 ModelScope 下载
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 到 `models/pmml12/`，
或重跑 `v3_m2.py` 用你选的模型重建 `embeddings.json`（同时需改 `v3_m4.py` 的 `MODEL_PATH`）。

### 3. 复现

```bash
python v3_m4.py    # RAG 闭环四问 → 写 m4_results.txt
python v4_demo.py  # V4 集成：一条跨轮对话 → 写 v4_demo_result.txt
```

---

## 诚实的技术边界

- **V3 检索是纯向量 top-k**（`V @ q` 点积）。BM25 双路 + RRF 融合是"为什么纯向量不够"的演进方向，尚未实现——评估集里留了回归探针（见 `v3_golden.json` 的 g05）。
- **V4 记忆/持久化按生产语义真写**（`redis-py` / SQLAlchemy），demo 环境无 Redis/MySQL 服务时**同接口降级**为进程内 dict / SQLite——接口一行不省，分别设 `REDIS_URL` / `DATABASE_URL` 即切真库。
- **MCP demo 数据是本地样例**，协议链路真实（spawn server → 握手 → 发现 → 调用）；生产接行情 API。

---

## 演示亮点（v4_demo_result.txt）

一条跨 4 轮对话同时验证：画像抽取（`profile` 增量写）→ RAG 引用回答 → MCP 查行情 →
**跨轮指代消解**——第 2 问「那利率多少」没点名产品，靠记忆补全检索词命中利率块，答出首套 3.95% + 期限溢价，全程引用通过白名单校验、热冷双写可核对。
