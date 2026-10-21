# cvgen-edit

来源：awesome-minimax-h3 的 ffmpeg 后处理。命令只描述剪什么，服务执行。

默认硬切，结尾淡出 2 到 3 秒。旁白用已入库的 IndexTTS2 成音。音效约加 8 dB，限幅到 -1 dB，并在人声下闪避。

操作：

- `cvgen edit join <成片甲> <成片乙>`
- `cvgen job show <任务>` 读取成片
- 封装不够时，确认透传已打开，再发 `cvgen ffmpeg -- <参数>`
