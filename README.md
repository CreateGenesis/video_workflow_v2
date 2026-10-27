# cvgen

平台和 agent 分成两个进程。网页和 `cvgen` 只打平台。agent 只领取任务，不写业务表。

设计方案：`docs/design/v3.md`。

## 组成

| 部分 | 位置 |
|---|---|
| 平台 API，托管网页 | `cvplatform/`，启动：`python -m cvplatform` |
| agent | `agent/`，启动：`python -m agent` |
| 网页 | `web/`，由平台提供 |
| 命令行 | `cvgen-cli/` |
| 手册 | `skills/cvgen-index.md` |
| 旧 v2 代码 | `server/` 留在树里，不进入新镜像，也不再是默认启动 |

平台依赖在 `requirements-platform.txt`，不含 Agno。agent 依赖在 `requirements-agent.txt`，含 Agno 和 MCP。

## 部署

一套编排里只有 PostgreSQL、`platform-api`、`agent-worker`。

```bash
cd deploy && docker compose up -d --build
```

- 平台：`http://127.0.0.1:8093`。健康响应是 `process=platform`。
- agent：`http://127.0.0.1:8094`。健康响应是 `process=agent`。
- `cvgen login --base http://127.0.0.1:8093` 登录的就是平台。
- `deploy/v2-compose.retired.yml` 是退役说明，不是默认启动方式。

## 测试

```bash
CVGEN_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q tests/v3
```
