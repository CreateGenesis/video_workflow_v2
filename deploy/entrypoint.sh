#!/bin/sh
# 已退役。v3 镜像直接运行 python -m cvplatform 或 python -m agent。
# 不再迁移 server，也不再启动 server.app / server.worker。
echo "deploy/entrypoint.sh 已退役。平台用 python -m cvplatform，agent 用 python -m agent。" >&2
exit 1
