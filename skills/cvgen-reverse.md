# cvgen-reverse

来源：gnipbao 的视频反推。先看懂，再写提示词。确认留在人和 agent 的对话里。这条技能不提交生成。

先复述：我看见了什么，我怎样理解，目标保留什么。等确认后再写提示词。沉默不算确认。

声音没测到就写没测到，不编歌词、音色或曲风。看不清的字标成看不清。单帧不能证明速度和接触顺序。接触表生成了不等于已经看过。

操作：

- 本机片子：`cvgen upload <文件>`，再 `cvgen entity add Clip '{"title":"参考片"}' --artifact <文件id>`；网上片子：`cvgen pull <地址> --learn`。
- `cvgen inspect <实体> --mode reverse`，`cvgen job wait <任务>` 读草案、测量和接触表链接（`cvgen media get <文件id> -o 接触表.jpg` 下载来看）。
- 确认后再按 `cvgen-h3-prompt` 写镜头。
