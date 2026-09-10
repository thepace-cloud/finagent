# V5-M4 服务镜像 —— python:3.12-slim + CPU torch
# 为什么先单独装 CPU torch：默认源给 linux 拉的是捆绑 CUDA 的完整版（数 GB），
# 本项目推理只在 CPU —— 先从官方 CPU 源装，后面 sentence-transformers 见 torch
# 已满足就不会再拉 CUDA 版（镜像体积从 ~6GB 级压到 ~2GB 级）。
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# 代码 + 小工件（chunks/embeddings/golden）；models/ 被 .dockerignore 挡住走挂载
COPY . .

# 容器里 127.0.0.1 是容器自己——服务必须绑 0.0.0.0 才能被端口映射打到
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000

# MCP 客户端 spawn 的子进程也是 "python v4_mcp_server.py"、cwd=/app —— 同镜像自给自足
CMD ["python", "v5_app.py"]
