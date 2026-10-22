# cvgen-reverse

来源：gnipbao 的视频反推。先看懂，再写提示词。确认留在人和 agent 的对话里。这条技能不提交生成。

先复述：我看见了什么，我怎样理解，目标保留什么。等确认后再写提示词。沉默不算确认。

声音没测到就写没测到，不编歌词、音色或曲风。看不清的字标成看不清。单帧不能证明速度和接触顺序。接触表生成了不等于已经看过。

操作：

- 本机片子用 `cvgen media upload <文件> --kind video`，网上片子用 `cvgen learn <地址>`
- `cvgen job show <任务>` 拿到入库后的实体
- `cvgen reverse <实体>`
- 读草案和接触表。确认后再按 `cvgen-h3-prompt` 写镜头
