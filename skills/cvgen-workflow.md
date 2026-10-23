# cvgen-workflow

探索跑顺之后，把做法定型成工作流：一份 JSON 规格，人发布后谁都能填灵感一键出片，其他服务也能调用。agent 负责写、试跑、改；人只审计和发布。agent 不能发布，也不能改已发布的版本。

规格怎么写：`cvgen skill show cvgen-workflow-spec`（字段说明），`cvgen workflow schema`（结构校验用的 JSON Schema），示例用 `cvgen workflow list` 找到后 `cvgen workflow show <id> <版本>` 看 `spec`。

要点：

- 锁定的东西进素材库并钉版本：风格、角色和外形、场景、参考图、提示模板（prompt）、输出 schema（schema）、ComfyUI 模板。用 `cvgen asset promote` 或 `cvgen asset save`。
- 灵感走 `inputs`；大模型节点（llm）用提示模板把灵感写成镜头，`materialize` 把输出写成本体实体并连到素材。
- 输出 schema 的每个字段都列进 required，可选值用 null；范围和字数由服务端再校验。
- 视频前想让人先挑关键帧，加 gate 节点；没有 gate 就全程自动。
- 按次计费的视频供应商不能写 retry。

## 先跑通

1. `cvgen workflow draft spec.json --notes "说明" --from-work <作品id>`：提交草稿，返回 `workflow_id`、`version` 和校验结果。`errors` 不为空先改。同名工作流再 draft 会追加一个新版本。
2. 准备输入：`inputs.json` 按规格的 `inputs` 写；上传类字段先 `cvgen upload <文件>`，填返回的文件 id。
3. `cvgen workflow dry-run <id> <版本> @inputs.json --level llm`：只真实调用大模型，`cvgen run wait <运行id>` 后读 `outputs.compiled`：每镜的最终提示词、参考图、花费估算和 `problems`。
4. `cvgen workflow fixtures <id> <版本> --from-run <运行id>`：把这次大模型输出存成样例。之后改规格只要 `cvgen workflow dry-run <id> <版本> @inputs.json`（compile 级，不花钱、立刻返回）。
5. `cvgen workflow trial <id> <版本> @inputs.json`：完整试跑一次（会花钱），然后 `cvgen run wait <运行id>`。

试跑停在闸门（退出码 4）时，这是你自己的试跑，自己处理：

- 看候选：`cvgen run show <运行id>`，在 `nodes` 里找 image 节点每条的 `output.candidates`，`cvgen media get <文件id> -o 目录` 下载看。
- 通过并选图：`cvgen run gate <运行id> approve --pick '{"keyframes:000": "<候选实体id>"}'`；不写 `--pick` 用每条的第一张。
- 只重抽几条：`cvgen run gate <运行id> reject --redo 001 --note "构图偏了"`，重抽完闸门会再停一次。
- 不想停：`cvgen workflow trial … --auto-gates`。

## 逐步矫正

- 某一条不好：`cvgen run rerun <运行id> <节点id> <条目>`（条目是 000、001…，单条节点不写），下游会跟着重跑。先确认是不是规格的问题，是就改规格，不要靠反复重跑碰运气。
- 改规格：草稿用 `cvgen workflow update <id> <版本> spec.json`；已发布的版本不能改，再 `cvgen workflow draft spec.json` 出新版本。`cvgen workflow diff <id> <旧> <新>` 看差异。
- 每次改完先 compile 级 dry-run 看提示词，满意再 trial。大模型步骤的写法改了要重新 `--level llm` 并更新样例。
- 生产运行的结果也能看：`cvgen run list --status failed,needs_attention`、`cvgen run show <运行id>`；审计员的意见用 `cvgen review list` 看，处理完 `cvgen review resolve <意见id>`。

## 交给人

试跑满意后，告诉审计员工作流 id 和版本、试跑运行 id、改了什么。审计员在网页上看差异、提示词和产物后发布。发布后：

- 网页「运行」里填灵感一键出片，也可以批量。
- 其他服务用 API 密钥调 `POST /v1/runs`（`auto_gates: true` 全程不等人），完成后回调 `callback_url`。
