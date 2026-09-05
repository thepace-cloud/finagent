def add(expr: str) -> str:
    """计算两个整数之和，输入格式如 '100+25'。"""
    left, right = expr.split("+")
    return str(int(left) + int(right))


def search(query: str) -> str:
    """模拟财经数据查询，返回演示数据。"""
    return f"【演示数据】关于「{query}」：放心借日利率 0.02%-0.05%，年化约 7.2%-18%。"


TOOLS = {
    "add": add,
    "search": search,
}


def dispatch(action: str, arg: str) -> str:
    return TOOLS[action](arg)


def docs() -> str:
    return "\n".join(f"- {name}: {func.__doc__}" for name, func in TOOLS.items())
