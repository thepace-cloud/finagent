import os
from dotenv import load_dotenv
from openai import OpenAI

# 1. 先加载 .env 里的变量（模块顶层只做"配置"这类无副作用的事）
load_dotenv()

# 2. 创建客户端，模块级只创建一次
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)


def chat(messages: list[dict], stop: list[str] | None = None) -> str:
    """给模型发消息，返回模型回复的文本。

    messages: 对话历史（每项是 {"role": ..., "content": ...}）
    stop:     stop 序列，模型输出到这些词就被掐断（ReAct 用它防自问自答）
    """
    resp = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL"),
        messages=messages,
        stop=stop,
        temperature=0.0,
    )
    return resp.choices[0].message.content


def chat_stream(messages: list[dict]):
    """流式版 chat：模型每想出一段就 yield 一段（/chat/stream 的水源）。

    为什么不给它套 with_retry：一个函数只背一种保险——
    质量护栏归 Validator 管（攒完再校验），网络重试归非流式 chat_safe 管；
    流式首答要的是"立刻见字"，断了让前端报错即可，半截流重试反而画蛇添足。
    """
    resp = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL"),
        messages=messages,
        temperature=0.0,
        stream=True,
    )
    for chunk in resp:
        piece = chunk.choices[0].delta.content
        if piece:                       # keep-alive 等空块直接跳过
            yield piece
