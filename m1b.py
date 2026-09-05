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

messages = [{"role": "user", "content": "用工具算一下 137 加 89 等于多少"}]

resp = client.chat.completions.create(
    model=os.getenv("DEEPSEEK_MODEL"),
    messages=messages,
    tools=tools,
    temperature=0.0,
)

# ── 第 1 次回复：模型想调 add ──
msg = resp.choices[0].message
args = json.loads(msg.tool_calls[0].function.arguments)   # 字符串 → dict（你会的）
result = add(**args)                                      # 真算：226

# ── 回传：两件事必须都做 ──
messages.append(msg)                                      # ① 模型消息原样放回
messages.append({                                          # ② 工具结果回传
    "role": "tool",
    "tool_call_id": msg.tool_calls[0].id,                 # 必须用同一个 id
    "content": str(result),                               # 内容必须是字符串
})

# ── 第 2 次请求：模型看到 Observation，给出答案 ──
resp2 = client.chat.completions.create(
    model=os.getenv("DEEPSEEK_MODEL"),
    messages=messages,
    tools=tools,
    temperature=0.0,
)
print("模型最终回答：", resp2.choices[0].message.content)
