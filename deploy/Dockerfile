# 已退役。默认镜像不再从这里构建。
# 平台镜像：deploy/Dockerfile.platform（复制 cvplatform/ 和网页，不安装 Agno）
# agent 镜像：deploy/Dockerfile.agent（只复制 agent/，安装 Agno 和 MCP）
# 两个镜像都不以 server.app 启动，也不登记 ComfyUI。
# 本文件保留，避免旧脚本静默用回 v2 的 server 镜像。
FROM python:3.12-slim
RUN echo "deploy/Dockerfile 已退役。请构建 deploy/Dockerfile.platform 或 deploy/Dockerfile.agent。" >&2 && exit 1
