# cvgen-music

来源：歌词卡点，加上托管音乐生成。超过 15 秒的单镜会挤掉动作。自动节拍识别会切错点，已舍弃。人指定切点。

先锁定歌词。用户给了歌词就用这份，不改词。没有歌词时，先把短歌词写进台词，确认后再生成。每段歌词只进对应镜头的台词字段，不写进画面提示词。

超过 15 秒时拆成多条不超过 15 秒的镜头。同一首歌、同一画幅、同一角色。同一场景的下一条用上一条尾帧做空间参考。硬切景保持服装和光线，不用淡入淡出掩盖跳变。

字幕只在用户明确要求歌词留在画面上时烧录。

操作：

- `cvgen music <歌词或文本> [--lyrics 歌词] [--duration 秒]`，`cvgen job wait <任务>` 后读取音频成片。
- 已拒绝，不再执行：`cvgen entity add Line '{"title":"副歌","text":"..."}'`
- 每条镜头 `cvgen generate <镜头>` 后 `cvgen inspect <成片>`，确认时长再拼接。
- `cvgen edit <成片...> --music <配乐成片>` 把配乐混到画面下。
- 只有明确要求贴字时才加 `--subtitle '["第一句","第二句"]'`。

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
