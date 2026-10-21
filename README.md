# cvgen

云端视频系统。`cvgen` 只发操作，服务完成生成、入库、理解和剪辑。网页只供观察和授权。

```bash
pip install -r requirements.txt
uvicorn server.app:app --port 8080
```

操作端下载网页上的可执行文件。Linux 和 macOS 运行 `./cvgen login --base 服务地址`，Windows 运行 `cvgen.exe login --base 服务地址`。解压后直接运行，先登录，再由网页管理员批准。

本体在 `ontology/`。技能在 `skills/`，正文只写 `cvgen` 操作。部署见 `deploy/docker-compose.yml`：镜像内构建网页，API 与 RustFS 同栈。没有对象存储时，媒体落在 `CVGEN_DATA` 本地目录。

零的雪原段用 `cvgen story` 写入本体，再 `cvgen shot compose` 组合 15 秒提示词。旧稿四拍无参考图，新稿三拍并带雪原和纱布参考。背人的起身留给下一条。
