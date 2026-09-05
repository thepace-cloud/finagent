import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# 这就是「工具注册表」的雏形：一个描述 add 工具的 JSON Schema
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
    tools=tools,          # ← 关键：把工具清单传给模型
    temperature=0.0,
)

# 只看输出，观察 tool_calls 长什么样
print(resp.choices[0].message)

args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
print(args)

