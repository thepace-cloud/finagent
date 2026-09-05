"""V4-M3 MCP Client —— 用官方 SDK 连上 server，动态发现工具并调用

演示完整 MCP 握手：spawn server 子进程(stdio) → initialize → list_tools（发现）
→ call_tool(get_stock_info, {symbol})（调用）。FinAgent 要的行情就从这个函数进来。
"""
import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))


async def _discover_and_call(symbol: str) -> str:
    params = StdioServerParameters(
        command="python",
        args=["v4_mcp_server.py"],
        cwd=HERE,  # 子进程在 finagent 目录起，才能 import 到 server 模块
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()          # 1. 协议握手
            tools = await session.list_tools()  # 2. 动态发现：问 server"你会什么"
            print(f"  [MCP 发现] server 暴露 {len(tools.tools)} 个工具: "
                  f"{[t.name for t in tools.tools]}")
            result = await session.call_tool("get_stock_info", {"symbol": symbol})
            # call_tool 返回结构化 content（text 块），不直接是 str——协议层就是这样
            return "".join(c.text for c in result.content)


def get_stock_via_mcp(symbol: str) -> str:
    """同步外壳：让上层（demo 主循环）不用碰 asyncio 就能拿行情。"""
    return asyncio.run(_discover_and_call(symbol))


if __name__ == "__main__":
    print(get_stock_via_mcp("600519"))
