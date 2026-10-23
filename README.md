# cvgen

由 agent 编排的视频工作流服务。

- **探索期**：agent 通过 `cvgen` 命令行搭角色、风格、分镜，生图、生视频、剪辑；人在网页上审计（看过程、看花费、审批、留意见）。
- **定型**：agent 把跑通的做法写成工作流 JSON，试跑后由审计员发布。
- **生产期**：人在网页上填灵感一键出片（可批量），其他服务通过 API v1 调用；生图走外部 API，视频可以排队跑在自部署的 ComfyUI GPU 机上。

设计方案：`docs/design/v2.md`。工作流规格：`server/workflows/workflow.v1.schema.json`，示例在 `docs/design/examples/`。

## 组成

| 部分 | 位置 |
|---|---|
| API（FastAPI，无状态） | `server/app.py`、`server/api/` |
| 任务队列与 worker（PostgreSQL，槽位、租约、找回） | `server/engine/`，启动：`python -m server.worker` |
| 工作流（校验、试跑、运行、闸门、预算） | `server/workflows/` |
| 供应商适配器（OpenAI Chat / Responses、Anthropic Messages、ComfyUI、autodl H3、生图和音频 API、模拟） | `server/providers/` |
| 本体（类型、关系、约束）与提示词组合 | `ontology/`、`server/compose.py` |
| 网页 | `web/` |
| agent 命令行（Rust） | `cvgen-cli/` |
| 操作手册（agent 读） | `skills/` |

## 本地开发

需要 Python 3.12+、ffmpeg、一个能建库的 PostgreSQL。

```bash
pip install -r requirements-dev.txt
# 起一套用模拟供应商的完整环境：建库、迁移、admin/adminpass1、示例工作流、API 和 worker
PG_ADMIN_URL=postgresql://postgres@127.0.0.1:5432/postgres scripts/dev-up.sh cvgen_dev 8080
cd web && npm install && npm run build      # 网页由 API 直接提供
scripts/dev-down.sh cvgen_dev
```

测试（每次会话新建一个临时库）：

```bash
CVGEN_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres python -m pytest -q
```

## 部署

应用机跑 PostgreSQL、RustFS、API 和 worker；GPU 机只跑 ComfyUI，并只允许应用机访问。

```bash
cp deploy/.env.example deploy/.env      # 填好每一项；CVGEN_SECRET_KEY 一旦使用不要再改
cd deploy && docker compose up -d --build
```

- 第一次打开网页会让你设置管理员；也可以 `docker compose exec api python -m server.manage create-user 账号 --role admin`。
- 忘记密码：`docker compose exec api python -m server.manage reset-password 账号`。
- 在“设置 → 供应商”登记大模型、生图、视频实例。GPU 机登记为 `video.comfy-gpu1`（协议 comfyui，实例组 `video.comfy`），资源池并发 1；多台 GPU 机用同一个实例组。
- worker 可以开多个：`docker compose up -d --scale worker=2`。
- 命令行包由 CI 构建（打 `cli-v*` 标签），放进 `tools/dist` 或 `CVGEN_RELEASES` 指向的目录，网页“工具下载”即可下载。
- 旧数据导入：`python -m server.manage import-legacy data/cvgen.sqlite`。

## 服务 API

OpenAPI 文档在 `/v1/docs`。管理员在“设置 → API 密钥”创建绑定工作区的密钥，然后：

```bash
curl -H "Authorization: Bearer $KEY" $BASE/v1/workflows
curl -H "Authorization: Bearer $KEY" -H "Idempotency-Key: order-42" -H "Content-Type: application/json" \
     -d '{"workflow_id":"wf_…","inputs":{"passage":"…"},"callback_url":"https://you/hook"}' $BASE/v1/runs
curl -H "Authorization: Bearer $KEY" $BASE/v1/runs/run_…/outputs
```

回调带 `X-CVGEN-Event`、`X-CVGEN-Timestamp` 和 `X-CVGEN-Signature: sha256=<HMAC-SHA256>`，签名内容是 `"<时间戳>.<请求体>"`。用 API 密钥发起的运行，用创建密钥时一并给出的 `webhook_secret` 签名；网页上发起的运行用全局回调密钥（`GET /api/admin/webhook-secret`，管理员可轮换）。接收方应拒绝时间戳超过 5 分钟的回调。
