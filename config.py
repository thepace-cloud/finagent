"""V5 配置中心 —— 行为参数的唯一事实源（设计要点：为什么要有这个文件）

为什么密钥不在这里：
  API key 属于 .env（llm.py 读 DEEPSEEK_API_KEY），.env 进 .gitignore 不进 git——
  「密钥不进代码、不进版本库」是原则；config.py 只管「行为可调」的参数。

为什么参数要集中：
  之前 max_steps、重试次数这类数字散在各文件里，改一处忘一处。
  集中后：调参数 = 改这一个文件；「配置管理」说的就是
  密钥与行为分离、参数单一事实源这两条。
"""
import os

# ── 日志 ──
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")        # DEBUG/INFO/WARNING/ERROR

# ── LLM 稳定性 ──
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "2"))       # 失败最多重试 2 次
LLM_RETRY_DELAY = float(os.getenv("LLM_RETRY_DELAY", "1.0"))  # 重试间隔（秒）

# ── Agent 护栏 ──
MAX_STEPS = int(os.getenv("MAX_STEPS", "8"))      # 工具循环步数上限（V2 同款纪律）

# ── 服务 ──
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
