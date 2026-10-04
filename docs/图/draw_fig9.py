"""绘制参赛文档 图9：系统架构图（受控编排）

用法: python -X utf8 draw_fig9.py
输出: fig9-系统架构图.png（同目录，2880x2000px，白底，适配 Word 排版）

为什么用代码画而不用 draw.io：图即代码——可版本化、可复现、改文案只动一处。
术语与《参赛作品文档.md》四(1)节严格一致，文档与图不两张皮。
"""
import os

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#374151"          # 正文墨色
LINE = "#475569"         # 连线
DPI = 200

fig, ax = plt.subplots(figsize=(14.4, 10.0), dpi=DPI)
ax.set_xlim(0, 144)
ax.set_ylim(0, 100)
ax.set_aspect("equal")
ax.axis("off")


def box(x, y, w, h, title, lines=(), fc="#FFFFFF", ec="#334155",
        ts=10.2, bs=8.0, lw=1.4):
    """圆角框：标题置顶加粗（描边同色），正文居中"""
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0,rounding_size=0.7",
                                fc=fc, ec=ec, lw=lw))
    cx = x + w / 2
    if lines:
        ax.text(cx, y + h - 1.9, title, ha="center", va="center",
                fontsize=ts, fontweight="bold", color=ec)
        ax.text(cx, y + (h - 3.4) / 2, "\n".join(lines), ha="center",
                va="center", fontsize=bs, color=INK, linespacing=1.5)
    else:
        ax.text(cx, y + h / 2, title, ha="center", va="center",
                fontsize=ts, fontweight="bold", color=ec)


def arrow(p1, p2, color=LINE, both=False, lw=1.4):
    style = "<|-|>" if both else "-|>"
    ax.annotate("", xy=p2, xytext=p1,
                arrowprops=dict(arrowstyle=style, color=color,
                                lw=lw, mutation_scale=13))


def line(x1, y1, x2, y2, color=LINE, lw=1.3):
    ax.plot([x1, x2], [y1, y2], color=color, lw=lw, solid_capstyle="round")


# ── 顶部：用户 ──────────────────────────────────────────────
box(50, 92, 44, 7, "用户 · 手机浏览器／PC",
    ["响应式 Web · 免安装 · 深色／浅色双主题"],
    fc="#ECEFF4", ec="#64748B")
arrow((58, 91.8), (58, 81.3))
ax.text(56.5, 89.3, "提问 / 测评操作", ha="right", va="center",
        fontsize=7.8, color=LINE)
arrow((71.9, 53.0), (71.9, 91.8))          # 校验通过 → 流式回用户
ax.text(73.2, 89.3, "校验通过 → 流式回答 ＋ 引用徽章", ha="left",
        va="center", fontsize=7.8, color=LINE)

# ── 应用容器外框 ────────────────────────────────────────────
ax.add_patch(FancyBboxPatch((3, 28), 138, 58.5,
                            boxstyle="round,pad=0,rounding_size=0.8",
                            fc="#F8FAFC", ec="#94A3B8", lw=1.6))
ax.text(6, 84.2, "FastAPI 应用容器", ha="left", va="center",
        fontsize=10.5, fontweight="bold", color="#334155")
ax.text(19.5, 84.2, "受控编排 —— Workflow 提供边界，Agent 在边界内自主",
        ha="left", va="center", fontsize=9.5, color="#64748B")

# ── Task Router ─────────────────────────────────────────────
box(47, 74.5, 50, 6.5, "Task Router ｜ 确定性关键词规则",
    fc="#FFF7E6", ec="#D97706")
line(72, 74.5, 72, 72.3)                   # 分流主干：竖干 + 横干 + 四支
line(21.5, 72.3, 122.3, 72.3)
for cx in (21.5, 55.1, 88.7, 122.3):
    arrow((cx, 72.3), (cx, 69.7))

# ── 四条路径 ────────────────────────────────────────────────
box(6, 55.5, 31, 14, "① RAG 路径",
    ["混合检索：BM25 ＋ 向量", "（RRF 融合排序）",
     "→ DeepSeek 生成 · 页号引用"],
    fc="#EFF6FF", ec="#2563EB")
box(39.6, 55.5, 31, 14, "② 对比路径",
    ["每款产品独立检索", "逐维对照表 · 双侧覆盖",
     "缺证据如实标「未检出」"],
    fc="#F0FDFA", ec="#0D9488")
box(73.2, 55.5, 31, 14, "③ 工具路径",
    ["Agent 工具循环", "股价查询 · 月供计算",
     "数字由代码算，不让模型口算"],
    fc="#FAF5FF", ec="#7C3AED")
box(106.8, 55.5, 31, 14, "④ 适配测评",
    ["规则确定性打分（零 LLM）", "毫秒级推荐卡／诚实全拒",
     "结论逐条挂说明书引用"],
    fc="#F0FDF4", ec="#16A34A")

# 路径 ①②③ → 出口校验；④ 确定性结果绕过护栏直出
arrow((21.5, 55.5), (33, 53.3))
arrow((55.1, 55.5), (55, 53.3))
arrow((88.7, 55.5), (77, 53.3))
line(137.8, 62.5, 142.5, 62.5, color="#16A34A")
line(142.5, 62.5, 142.5, 95.5, color="#16A34A")
arrow((142.5, 95.5), (94, 95.5), color="#16A34A")
ax.text(141.4, 79, "适配测评 · 确定性直出", rotation=90, ha="center",
        va="center", fontsize=7.2, color="#16A34A")

# ── Validator 出口校验 ─────────────────────────────────────
box(14, 43.5, 82, 9.5, "Validator 出口校验 —— 反幻觉护栏",
    ["引用页码必须落在本次检索命中的真实白名单内",
     "违规 → 带反馈重试 → 仍不过 → 红卡降级拒答",
     "三档计数（一次通过／重试／拒答）实时上报 /metrics"],
    fc="#FEF2F2", ec="#DC2626")

# ── 记忆层 ─────────────────────────────────────────────────
box(6, 34, 132, 6.5, "记忆层",
    ["会话级三级补全（本轮点名 ＞ 上文产品 ＞ 画像意向）· "
     "跨会话画像（白名单可编辑）· 滚动摘要（≥8 条自动压缩最旧 4 条）"],
    fc="#FFFBEB", ec="#D97706", ts=9.5, bs=7.8)
arrow((12, 40.5), (12, 55.5), color="#D97706", both=True)  # 记忆 ↔ 检索
ax.text(10.9, 48, "画像补全 · 摘要注入", rotation=90, ha="center",
        va="center", fontsize=7.2, color="#D97706")

# ── 底层：三容器 + 知识库 + 外部 LLM ───────────────────────
box(6, 14, 28, 10, "Redis 容器", ["会话历史（热）", "每 IP 滑动窗口限流"],
    fc="#F1F5F9", ec="#475569")
box(38, 14, 28, 10, "MySQL 容器", ["会话／画像结构化", "持久化（冷）"],
    fc="#F1F5F9", ec="#475569")
box(70, 14, 28, 10, "DeepSeek API（外部）", ["答案生成", "滚动摘要压缩"],
    fc="#FAF5FF", ec="#7C3AED")
box(102, 13.5, 36, 10.5, "知识库（本地）",
    ["三份真实贷款说明书 → 分块", "BM25 索引＋向量索引",
     "sentence-transformers 本地推理"],
    fc="#EFF6FF", ec="#2563EB")
arrow((20, 28), (20, 24), both=True)
ax.text(21.3, 25.9, "双写", fontsize=7.2, color=LINE, va="center")
arrow((52, 28), (52, 24), both=True)
ax.text(53.3, 25.9, "双写", fontsize=7.2, color=LINE, va="center")
arrow((84, 28), (84, 24), both=True)
ax.text(85.3, 25.9, "生成／压缩调用", fontsize=7.2, color=LINE, va="center")
arrow((120, 24), (120, 28))
ax.text(121.3, 25.9, "检索召回", fontsize=7.2, color=LINE, va="center")

# ── 底部脚注条：部署与可观测 ────────────────────────────────
ax.add_patch(FancyBboxPatch((3, 3), 138, 8.5,
                            boxstyle="round,pad=0,rounding_size=0.7",
                            fc="#EEF2F7", ec="#CBD5E1", lw=1.1))
ax.text(72, 8.3, "部署：Docker Compose 三容器（App ＋ Redis ＋ MySQL）"
        "· 公网 http://47.95.222.61:8000 · 每 IP 滑动窗口限流",
        ha="center", va="center", fontsize=8.2, color=INK)
ax.text(72, 5.4, "可观测：/metrics 护栏三档计数 → /stats 看板（5 秒刷新）"
        "· trace_id 全链路日志回放 —— 用数字说话，而不是用形容词",
        ha="center", va="center", fontsize=8.2, color=INK)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "fig9-系统架构图.png")
fig.savefig(out, dpi=DPI, facecolor="white",
            bbox_inches="tight", pad_inches=0.15)
print(f"saved: {out}")
