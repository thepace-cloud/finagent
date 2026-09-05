import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

def add(a: int, b: int) -> int:
    return a + b

# ── 工具注册表（给代码用）────────────────────────────────────
TOOLS = {"add": add}

# ── 工具 schema（给模型看的菜单）─────────────────────────────
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
    }
]

max_steps = 8

messages = [{"role": "user", "content": "用工具算一下 137 加 89 等于多少"}]
for step in range(max_steps):
    resp = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL"),
        messages=messages,
        tools=tool_schemas,
        temperature=0.0,
    )
    msg = resp.choices[0].message

    if not msg.tool_calls:             # ① 模型不调工具了 → 出答案 → 停
        print(msg.content)
        break

    messages.append(msg.model_dump())  # ③ 修复：对象 → 纯 dict（满足 wire 协议）
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        result = TOOLS[tc.function.name](**args)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
else:                                  # ② 修复：循环没被 break、正常走完才执行这里
    print(f"⚠️ 转满 {max_steps} 圈仍未得到答案，请检查或人工处理")
