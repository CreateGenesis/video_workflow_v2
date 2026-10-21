# cvgen-reverse

来源：gnipbao/minimax-h3-video-reverse-skill。先看懂，再写提示词。确认留在人和 agent 的对话里。

服务用 ffmpeg 抽接触表、首尾帧和音轨。封装不够时，人可以打开透传，agent 再发 `cvgen ffmpeg`。这条技能不提交生成。

操作：

- `cvgen pull <地址>` 或 `cvgen learn <地址>`
- `cvgen job show <任务>` 拿到入库后的实体
- `cvgen reverse <实体>`
- 读草案和接触表，用人能改的复述核对镜头、动作和声音
