# cvgen-check

来源：codex-minimax-h3-video-skill 的验收清单。不接首帧生图和外部剪辑器。

核对三件事：台词是否落在指定镜头，空间是否接上一条，规格是否在 1 到 15 秒和当前分辨率档位内。

新机器直接运行下载的可执行文件。先 `cvgen login`，网页批准后再操作。

操作：

- `cvgen inspect <成片>`
- `cvgen preview <成片>`
- `cvgen job show <任务>`
- 不通过就新建镜头或剪辑操作，不改已成功的任务。
