import os
import json
import sys
from dotenv import load_dotenv
from openai import OpenAI

# Windows 控制台默认 GBK，编不了 emoji（📋）等 Unicode 字符 → 统一用 UTF-8 输出
# 否则模型答案里一旦出现 emoji，print 就会 UnicodeEncodeError 崩溃
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# ────────────────────────────────────────────────────────────
# 工具 1：add —— 确定性计算工具
# ────────────────────────────────────────────────────────────
def add(a: int, b: int) -> int:
    return a + b

# ────────────────────────────────────────────────────────────
# 工具 2：search_loan_rates —— 数据查询工具
# ────────────────────────────────────────────────────────────
def search_loan_rates(
    loan_type: str,
    amount: float | None = None,
    term_months: int | None = None,
    bank_name: str | None = None,
) -> str:
    rates = {
        "mortgage": 3.45,
        "car": 4.20,
        "personal": 3.60,
        "business": 3.10,
    }

    # 查不到 → 返回"给模型看的错误提示"，而不是抛异常让程序崩
    if loan_type not in rates:
        return (
            f"查询失败：不支持的贷款类型 '{loan_type}'，可选类型：{list(rates.keys())}"
        )

    bank = bank_name or "主流银行"
    base_rate = rates[loan_type]

    # 期限溢价：term 越长，风险越高，利率按档位上浮
    premium = 0.0
    if term_months is not None:
        if term_months <= 12:
            premium = 0.00  # 1年及以内：不加点
        elif term_months <= 36:
            premium = 0.20  # 1到3年：加20个基点 (0.2%)
        elif term_months <= 60:
            premium = 0.45  # 3到5年：加45个基点 (0.45%)
        else:
            premium = 0.80  # 5年以上：加80个基点 (0.8%)

    # 最终利率 = 基础利率 + 期限溢价
    final_rate = base_rate + premium

    # 把可选参数拼进返回内容，形成信息闭环（模型能看到用户问的条件被用上了）
    conditions = []
    if amount is not None:
        conditions.append(f"金额 {amount} 万元")
    if term_months is not None:
        conditions.append(f"期限 {term_months} 个月")

    cond_str = f"（条件：{', '.join(conditions)})" if conditions else ""

    return f"{bank}【{loan_type}】{cond_str} 的参考年化利率为：{final_rate:.2f}%"

# ────────────────────────────────────────────────────────────
# 工具 3：calc_monthly_payment —— 确定性计算工具（等额本息）
# ────────────────────────────────────────────────────────────
def calc_monthly_payment(
    amount_wan: float,
    annual_rate: float,
    term_months: int,
) -> dict:
    """计算等额本息每月还款额（元）及总利息（元）

    :param amount_wan: 贷款金额（单位：万元）
    :param annual_rate: 年化利率百分数（例如 3.65 表示 3.65%）
    :param term_months: 贷款期限（单位：个月）
    :return: 包含每月还款额、总利息和总还款额的字典
    """
    if amount_wan <= 0 or term_months <= 0:
        return {"status": "error", "message": "贷款金额和期限必须大于 0"}

    # 1. 单位换算
    principal = amount_wan * 10000  # 万元 -> 元
    monthly_rate = annual_rate / 12 / 100  # 百分比年利率 -> 月利率小数

    # 2. 等额本息公式计算月供 M
    if monthly_rate == 0:
        # 特殊情况：0 利率（如免息贷款）
        monthly_payment = principal / term_months
    else:
        # M = P * r * (1+r)^n / ((1+r)^n - 1)
        rate_factor = (1 + monthly_rate) ** term_months
        monthly_payment = (
            principal * (monthly_rate * rate_factor) / (rate_factor - 1)
        )

    # 3. 计算总还款额与总利息
    total_payment = monthly_payment * term_months
    total_interest = total_payment - principal

    # 4. 返回精确定量结果（保留两位小数）
    return {
        "status": "success",
        "monthly_payment_yuan": round(monthly_payment, 2),  # 每月还款额（元）
        "total_interest_yuan": round(total_interest, 2),  # 总利息（元）
        "total_payment_yuan": round(total_payment, 2),  # 总还款本息（元）
        "inputs": {
            "amount_wan": amount_wan,
            "annual_rate_percent": annual_rate,
            "term_months": term_months,
        },
    }

# ────────────────────────────────────────────────────────────
# 工具注册表：给代码用。模型点名后，来这里取真正的函数
# ────────────────────────────────────────────────────────────
TOOLS = {
    "add": add,
    "search_loan_rates": search_loan_rates,
    "calc_monthly_payment": calc_monthly_payment,
}

# ────────────────────────────────────────────────────────────
# 工具 schema：给模型看的菜单。两个工具都要声明，模型才知道有这两个
# ────────────────────────────────────────────────────────────
tool_schemas = [
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "计算两个整数之和",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "第一个数"},
                    "b": {"type": "integer", "description": "第二个数"},
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_loan_rates",
            "description": "根据贷款类型、金额和期限等条件查询最新的银行或机构贷款利率",
            "parameters": {
                "type": "object",
                "properties": {
                    "loan_type": {
                        "type": "string",
                        "enum": ["mortgage", "car", "personal", "business"],
                        "description": "贷款类型：mortgage(按揭房贷)、car(车贷)、personal(个人消费贷)、business(企业/个人经营贷)",
                    },
                    "amount": {
                        "type": "number",
                        "description": "拟申请的贷款金额（单位：万元）",
                    },
                    "term_months": {
                        "type": "integer",
                        "description": "贷款期限（单位：个月），例如：12、36、360",
                    },
                    "bank_name": {
                        "type": "string",
                        "description": "可选，指定查询的具体银行或金融机构名称",
                    },
                },
                "required": ["loan_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc_monthly_payment",
            "description": "根据贷款金额、年利率和期限，计算等额本息贷款的每月还款额及总利息",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount_wan": {
                        "type": "number",
                        "description": "贷款金额（单位：万元，例如：50 表示 50 万元）",
                    },
                    "annual_rate": {
                        "type": "number",
                        "description": "年利率百分数（单位：%，例如：3.65 表示 3.65%）",
                    },
                    "term_months": {
                        "type": "integer",
                        "description": "贷款期限（单位：月，例如：360 表示 360 个月）",
                    },
                },
                "required": ["amount_wan", "annual_rate", "term_months"],
            },
        },
    },
]

max_steps = 8

# 换一句会触发 search 的话术（用户问利率，模型应该调 search_loan_rates）
messages = [{"role": "user", "content": "30 万、3 年期个人消费贷，月供和总利息多少？"}]

# ────────────────────────────────────────────────────────────
# 收成循环：问 → 判断 → 执行 → 回传 → 再问
# 注意：这个循环是【通用】的——不关心工具是 add 还是 search，
#       模型调几个、调哪个，循环代码都不用改。这就是注册表的价值。
# ────────────────────────────────────────────────────────────
for step in range(max_steps):
    resp = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL"),
        messages=messages,
        tools=tool_schemas,
        temperature=0.0,
    )
    msg = resp.choices[0].message

    if not msg.tool_calls:             # 模型不调工具了 → 出答案 → 停
        print(msg.content)
        break

    messages.append(msg.model_dump())  # assistant 原样回放（对象 → dict）
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)  # 拆密封信封
        # ── trace：模型每一步干了什么，必须可见，否则 agent 不可调试 ──
        print(f"[step {step}] 模型要调: {tc.function.name} 参数: {args}")
        result = TOOLS[tc.function.name](**args)  # 注册表取函数并执行
        print(f"[step {step}] 工具返回: {result}")
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,               # 配对：这次结果属于哪个调用
            "content": str(result),
        })
else:                                  # 8 圈跑完还没 break → 耗尽
    print(f"⚠️ 转满 {max_steps} 圈仍未得到答案，请检查或人工处理")
