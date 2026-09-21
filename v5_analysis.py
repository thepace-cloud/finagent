"""V5 Analysis 路径 —— Agent 工具循环（受控编排的「边界内自主」就在这个文件）

三个工具进一张注册表（闭集 = 边界）：
  search_loan_rates / calc_monthly_payment 迁自 V2 m2b（那里是脚本不可导入）；
  get_stock_info 是 V4 的 MCP 行情——同步外壳直接当普通函数收编进菜单。
  「MCP 进注册表」正是 MCP 的意义：client 眼里它就是个普通工具，不特殊。

拷问主线：
  - Agent 的自主在哪？调不调、调哪个、调几次，模型在循环里自己定
  - 边界在哪？菜单是闭集（TOOLS 之外调不到）、步数有上限（MAX_STEPS）、
    计算全在确定性函数里（模型只递参数）——V2 的确定性分离原样继承
  - 报错回传：工具返回错误字符串而不是抛异常，模型读得到、能自纠（V2 纪律）
"""
import json
import logging
import os

from config import LLM_RETRIES, LLM_RETRY_DELAY, MAX_STEPS
from llm import client
from v4_mcp_client import get_stock_via_mcp
from v5_retry import with_retry

logger = logging.getLogger("finagent.analysis")


# ── 工具 1：贷款利率查询（迁自 V2，逻辑未动）──
def search_loan_rates(loan_type: str, amount: float | None = None,
                      term_months: int | None = None,
                      bank_name: str | None = None) -> str:
    rates = {"mortgage": 3.45, "car": 4.20, "personal": 3.60, "business": 3.10}
    if loan_type not in rates:
        return f"查询失败：不支持的贷款类型 '{loan_type}'，可选：{list(rates.keys())}"

    bank = bank_name or "主流银行"
    base = rates[loan_type]
    premium = 0.0
    if term_months is not None:
        if term_months <= 12:
            premium = 0.00
        elif term_months <= 36:
            premium = 0.20
        elif term_months <= 60:
            premium = 0.45
        else:
            premium = 0.80
    return f"{bank}【{loan_type}】{term_months}个月期 参考年化利率 {base + premium:.2f}%"


# ── 工具 2：等额本息月供计算（迁自 V2，确定性公式未动）──
def calc_monthly_payment(amount_wan: float, annual_rate: float,
                         term_months: int) -> str:
    principal = amount_wan * 10000
    monthly_rate = annual_rate / 12 / 100
    if monthly_rate == 0:
        payment = principal / term_months
    else:
        factor = (1 + monthly_rate) ** term_months
        payment = principal * monthly_rate * factor / (factor - 1)
    total_interest = payment * term_months - principal
    return (f"每月还款 {payment:.2f} 元，总利息 {total_interest:.2f} 元，"
            f"总还款 {payment * term_months:.2f} 元")


# ── 工具 3：MCP 行情（V4 的同步外壳直接进菜单）──
def get_stock_info(symbol: str) -> str:
    return get_stock_via_mcp(symbol)


# ── 注册表（闭集）+ schema 菜单（给模型看）──
TOOLS = {
    "search_loan_rates": search_loan_rates,
    "calc_monthly_payment": calc_monthly_payment,
    "get_stock_info": get_stock_info,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_loan_rates",
        "description": "根据贷款类型和期限查询参考年化利率",
        "parameters": {"type": "object", "properties": {
            "loan_type": {"type": "string",
                          "enum": ["mortgage", "car", "personal", "business"],
                          "description": "贷款类型"},
            "term_months": {"type": "integer", "description": "期限（月），可选"},
        }, "required": ["loan_type"]},
    }},
    {"type": "function", "function": {
        "name": "calc_monthly_payment",
        "description": "等额本息：按金额(万)/年利率(%)/期限(月)算月供与总利息",
        "parameters": {"type": "object", "properties": {
            "amount_wan": {"type": "number", "description": "贷款金额（万元）"},
            "annual_rate": {"type": "number", "description": "年利率（%，如 3.65）"},
            "term_months": {"type": "integer", "description": "期限（月）"},
        }, "required": ["amount_wan", "annual_rate", "term_months"]},
    }},
    {"type": "function", "function": {
        "name": "get_stock_info",
        "description": "查询 A 股行情（最新价/涨跌幅），symbol 为 6 位代码",
        "parameters": {"type": "object", "properties": {
            "symbol": {"type": "string", "description": "6 位股票代码，如 600519"},
        }, "required": ["symbol"]},
    }},
]

# 带工具菜单的一次模型调用（复用 V1 的 OpenAI 客户端，套重试护栏）
_chat_with_tools = with_retry(
    lambda msgs: client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL"),
        messages=msgs,
        tools=TOOL_SCHEMAS,
        temperature=0.0,
    ),
    "llm.chat.tools", LLM_RETRIES, LLM_RETRY_DELAY,
)


def run_analysis(user_msg: str) -> str:
    """agent_turn 循环：模型在闭集菜单里自主决策，确定性代码执行。

    每一步的工具调用都进 log（可审计）；步数耗尽仍无答案 → 快速失败话术。
    """
    messages = [{"role": "user", "content": user_msg}]
    for step in range(MAX_STEPS):
        resp = _chat_with_tools(messages)
        msg = resp.choices[0].message.model_dump()
        if msg.get("content") is None:
            msg["content"] = ""                          # 回放时 content 不能是 None
        messages.append(msg)                             # assistant 原样回放

        if not msg.get("tool_calls"):                    # 不再调工具 → 出答案
            return msg["content"]

        for tc in msg["tool_calls"]:
            # 注意：model_dump 后 tool_calls 是嵌套 dict，用 [] 访问不是点号
            # （m2b 能用点号是因为它遍历的是 dump 前的原始对象）
            name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"])
            logger.info("[tool] step=%d %s %s", step, name, args)
            result = TOOLS[name](**args)                 # 闭集内取函数执行
            logger.info("[tool] -> %s", result)
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": str(result)})

    return (f"⚠ 工具循环转满 {MAX_STEPS} 步仍未得出答案，"
            "请换个问法或转人工。（Analysis 路径快速失败）")
