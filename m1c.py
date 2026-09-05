import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

def add(a: int, b: int) -> int:          # ← 改过签名：和 schema 的 a,b 对上
    return a + b

# ── 工具注册表 ──────────────────────────────────────────────
# "add"(字符串) = 钥匙，add(不带括号的函数名) = 值。
# 模型在 schema 里看到 "add"，就会调用这个名字；
# 第 45 行 TOOLS[tc.function.name] 按这个名字来取函数。
TOOLS = {"add": add}

tools = [
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
    }
]

max_steps = 8                            # ← 循环上限：最多转 8 圈，防死循环

messages = [{"role": "user", "content": "用工具算一下 137 加 89 等于多少"}]
for step in range(max_steps):
    # model 必须用关键字传；create 不认 "messages, tools" 这种位置参数
    resp = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL"),
        messages=messages,
        tools=tools,
        temperature=0.0,
    )
    msg = resp.choices[0].message

    if not msg.tool_calls:             # ① 不调工具了 → 出答案 → 停
        print(msg.content)
        break

    messages.append(msg)               # ② 要调工具 → 执行 → 回传 → 转下一圈
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        result = TOOLS[tc.function.name](**args)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
