# cvgen-check

来源：codex 的验收清单。规格错了就不能当已成片用。渲染命令成功不等于合格。

核对四件事：台词是否落在指定镜头，空间是否接上一条，时长是否在 1 到 15 秒，分辨率是否落在现有档位。现有档位没有 2K。

不通过就新建镜头或剪辑，不改已成功的任务。

操作：

- `cvgen check <成片>`，`cvgen job wait <任务>` 读 passed、problems 和接触表。
- `cvgen inspect <成片>` 量响度和声音。
- `cvgen media get <文件id> -o <路径>` 下载成片或接触表亲自看。
- 审计员的意见用 `cvgen review list` 读，处理完 `cvgen review resolve <意见id>`。

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
