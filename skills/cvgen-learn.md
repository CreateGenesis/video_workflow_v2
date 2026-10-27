# cvgen-learn

来源：视频阅读。平台登录在网页完成。agent 不自己下载，避免半截文件。

`cvgen learn` 把片子拉进存储，并留下观察。需要画面测量时再发 `cvgen reverse`。

操作：

- `cvgen pull <视频地址> --learn`
- `cvgen job wait <任务>` 读入库后的实体和观察
- 需要画面测量时 `cvgen inspect <实体> --mode reverse`

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
