# cvgen-modes

来源：h3-prompt-writing 的 T2VA、I2VA、FL2VA、L2VA、Ref2VA，以及 cheercheung、Evolink 里保留的写法。外部安装、密钥检查和余额查询不改变画面，已舍弃。

五种写法决定参考图怎么咬住时间。没有对齐句时，图生视频会从参考图漂开。

- 纯文字：没有图，直接写三段画面、声音、音乐。这个工作流仍要求至少一张参考，纯文字不能提交。
- 首帧：开头写“对于目标成片，在 0.00 秒，参考图 N 被完整采用。”动作从这张图往前发展。
- 首尾帧：开头写“参考图 A 对齐 0.00 秒；参考图 B 对齐成片时长。”中间只写从首帧走到尾帧的连续路径。
- 尾帧：开头写参考图对齐成片时长。先写一个说得通的前态，再收到这张图。
- 全参考：同一张图在全文用同一个标签。人物、场景、动作、声音分开定义。标签中途不能改义。

时长必须等于镜头请求的秒数，范围是 1 到 15 秒。描述短于请求，动作会被拉空；长于请求，主动作会被挤掉。

操作：

- 首帧或尾帧参考：`cvgen upload <文件>` 拿到文件 id，再 `cvgen entity add Reference '{"title":"首帧","role":"首帧","take":"构图和主体位置","ignore":"多余文字"}' --artifact <文件id>`。
- 上一镜已经入库时，`cvgen frame <成片> --at last --role 空间` 抽真实尾帧。
- 已拒绝，不再执行：`cvgen link references <镜头> <参考>` 后再 `cvgen shot compose <镜头>`。确认对齐句在提示词开头，再 `cvgen generate <镜头>`，`cvgen job wait <任务>` 等到结束。

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
