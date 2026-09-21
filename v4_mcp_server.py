"""V4-M3 MCP Server —— 一个财经数据 server，暴露 get_stock_info（极小范围，锁死）

MCP 是什么（拷问主线）：
  让"工具提供方"（server）按一套公开协议把能力暴露出去，"工具消费方"（client）
  可以动态发现（list_tools）并调用（call_tool）—— 不用提前在进程里 import 对方的函数。
  对比 Function Calling：那是在同一个进程里把函数注册给 LLM 硬编码调用；
  MCP 是把工具做成**标准协议服务**，跨进程、跨语言、可被发现。

本 demo 数据是本地样例（生产接行情源），只做协议链路真实——这是面试要讲清的分寸：
"工具用 MCP 协议暴露是真的，数据是样例是 Demo 取舍，不是假装接了行情。"
"""
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="fin-mcp", version="0.1.0")

# 本地样例行情：symbol -> {名称, 最新价, 涨跌幅%}（生产环境换成行情 API/数据源）
STOCKS = {
    "600519": {"name": "贵州茅台", "price": 1480.50, "change_pct": 0.62},
    "000001": {"name": "平安银行", "price": 11.32, "change_pct": -0.35},
    "300750": {"name": "宁德时代", "price": 192.80, "change_pct": 1.12},
}


@server.tool()
def get_stock_info(symbol: str) -> str:
    """查询 A 股行情。symbol 是 6 位股票代码，如 600519。返回名称、最新价与涨跌幅。"""
    if symbol not in STOCKS:
        covered = "、".join(STOCKS)
        return f"未收录 {symbol} 的行情。当前 demo 数据覆盖：{covered}"
    s = STOCKS[symbol]
    return f"{s['name']}({symbol}) 最新价 {s['price']:.2f} 元，涨跌幅 {s['change_pct']:+.2f}%"


if __name__ == "__main__":
    server.run()  # 默认 stdio 传输
