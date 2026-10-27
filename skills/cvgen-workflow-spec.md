# cvgen-workflow-spec

工作流规格 v1 的字段说明。结构以 `cvgen workflow schema` 为准；引用是否存在、步骤图是否无环、本体约束由服务端校验（`cvgen workflow validate`）。完整示例：`cvgen workflow show <示例工作流id> 1` 的 `spec`。

## 顶层

| 字段 | 说明 |
|---|---|
| `schema` | 固定 `cvgen.workflow/v1` |
| `name` | 工作流名称。同名再 draft 会追加版本 |
| `inputs` | 对象型 JSON Schema，生成网页表单和服务 API 的输入校验。字段要有 `title`；`format: multiline` 多行文字；`format: asset-upload` 上传文件，`x-role` 写参考用途（身份、空间、细节…） |
| `assets` | 别名 → `asset:名称@版本`，版本必须钉死。节点里写 `{{assets.别名}}` |
| `defaults` | `resolution`、`duration_seconds`（1–15）、`priority` |
| `budget` | 必填 `max_yuan`；可选 `max_video_seconds`、`max_gpu_minutes`、`max_llm_tokens` |
| `policy` | `batch_barrier`；`gpu_order`：run_first（一条跑完再下一条）或 round_robin；`on_budget_exceeded`：pause 或 fail |
| `nodes` | 步骤列表 |
| `outputs` | 交付名 → 节点路径，例如 `"video": "final.export"`、`"clips": "clips"` |

## 取值 `{{路径}}`

- 根是 `inputs`、`assets`、`run`、`item` 或某个节点 id。没有条件和循环。
- 在文字里：提示模板素材取正文，实体取标题，`{{assets.style.medium}}` 取字段，列表用“、”连接。
- 在 `links.to`、`references`、`attach_to` 里：解析成实体或素材引用，列表展开成多条。
- `for_each: "script.shots"` 时每个镜头一个任务，用 `{{item}}`、`{{item.action}}`。
- 依赖 = `after` + 模板和 `for_each` 里引用到的节点。两个节点对同一个列表 `for_each` 时按条目一一对应：第 2 镜的视频只等第 2 镜的关键帧。闸门要等 `after` 的节点全部完成。

## 节点

每个节点都有 `id`、`kind`，可选 `title`、`after`、`for_each`、`priority`、`timeout_seconds`、`retry`（`max_attempts`、`backoff_seconds`；按次计费的视频供应商不能写）。`provider` 写供应商实例名或组名，如 `llm.default`、`image.default`、`video.comfy`。

| kind | 必填 | 其他字段 |
|---|---|---|
| `llm` | `provider`、`prompt.user`、`output_schema` | `prompt.system`；`materialize`；`repair`（0–3，校验或组合警告时让模型自己修）；`params.temperature`、`params.max_tokens` |
| `image` | `provider`、`prompt`、`role` | `references`（最多 9）；`candidates`（1–4）；`select`：first 或 gate（交给闸门挑）；`attach_to`（选中的图连到哪个实体，通常 `{{item}}`） |
| `video` | `provider`、`for_each` | `template`（ComfyUI 必填）；`prompt`：默认 `compose`（由镜头、风格、参考组合四段式）；`resolution`；`continuity`：none 或 previous_last_frame（上一镜尾帧接下一镜，自动串行）；`allow_warnings` |
| `tts` | `provider`、`for_each`、`voice` | `text`（默认 `{{item.text}}`） |
| `music` | `provider`、`prompt` | `lyrics`、`duration_seconds`（5–300） |
| `check` | `for_each`、`rules` | rules：duration、resolution、loudness、contact_sheet、last_frame、dialogue；`on_fail`：fail、flag、rerun_upstream；`max_reruns`（0–2） |
| `edit` | `ops` | `clips`（节点路径）；ops：`join`（`fade_seconds`）、`mix`（`music`、`narration`、`duck`、`music_gain_db`）、`subtitle`（`lines`、`burn`）、`export`（`resolution`、`format`、`name`） |
| `gate` | `after`、`show` | `approvers`：reviewer、producer、admin；`auto_approve`；`allow_redo`；`timeout_hours`；`on_timeout`：wait、approve、reject |

## materialize

`"materialize": {"shots": {"type": "Shot", "links": [...]}}`：把大模型输出的 `shots` 字段写成实体，列表每项一个、保留顺序。

- `type`：Shot、Line、Beat、Detail、Subject、Appearance、Place。必填字段见 `cvgen ontology`。
- `fields`：实体字段 → 模板；不写按同名字段拷贝。
- `links`：`{"name": 关系, "to": 模板, "note": 说明}`。关系：has_appearance、wears、located_in、holds、detail_of、styled_as、shot_with、voices、voiced_by、contrasts_with、continues、references、derived_from、uses_clip。`contains`、`belongs_to` 由服务维护，不能写。
- `children`：嵌套字段 → 子规则，子规则必须写 `parent_link`。

## 常见校验错误

- 素材或版本不存在：先 `cvgen asset list` / `cvgen asset show <名称>`。
- 供应商不存在或能力不对：问管理员在「设置 → 供应商」里配，名字要和规格一致。
- 一个镜头最多一种运镜；时长 1–15 的整数；分辨率只能是 480p横、480p竖、768p横、768p竖、480p(1:1)、768p(1:1)；参考用途只能是 身份、空间、细节、风格、分镜、音色、情感、首帧、尾帧。
- 输出 schema 的每个字段都要列进 required，可选值用 null。

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
