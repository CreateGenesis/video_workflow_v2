# cvgen-workflow

探索跑顺之后，把做法定型成工作流：一份 JSON 规格，人发布后谁都能填灵感一键出片，其他服务也能调用。agent 只能提交草稿和试跑，不能发布。

规格格式见服务上的 `docs/design/v2.md` 第 4 节和示例工作流（`cvgen workflow list`，`cvgen workflow show <id> 1`）。要点：

- 锁定的东西进素材库并钉版本：风格、角色和外形、场景、参考图、提示模板（prompt）、输出 schema（schema）、ComfyUI 模板。用 `cvgen asset promote` 或 `cvgen asset save`。
- 灵感走 `inputs`；大模型节点（llm）用提示模板把灵感写成镜头，`materialize` 把输出写成本体实体并连到素材。
- 输出 schema 的每个字段都列进 required，可选值用 null；范围和字数由服务端再校验。
- 视频前想让人先挑关键帧，加 gate 节点；没有 gate 就全程自动。
- 按次计费的视频供应商不能写 retry。

操作：

- `cvgen workflow draft spec.json --notes "说明"`：提交草稿，返回校验结果。
- `cvgen workflow update <id> <版本> spec.json` 改草稿；`cvgen workflow validate <id> <版本>` 再校验。
- `cvgen workflow dry-run <id> <版本> inputs.json`：不花钱，用样例输出编译全部提示词和估算。
- `cvgen workflow dry-run <id> <版本> inputs.json --level llm`：只真实调用大模型，`cvgen run wait <运行id>` 后读 outputs.compiled。
- `cvgen workflow fixtures <id> <版本> --from-run <运行id>`：把这次大模型输出存成试跑样例。
- `cvgen workflow trial <id> <版本> inputs.json`：完整试跑一次（会花钱），`cvgen run wait <运行id>`。
- 试跑满意后，请审计员在网页上看差异、提示词和产物，然后发布。
