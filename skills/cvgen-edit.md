# cvgen-edit

来源：后处理剪辑。命令只描述剪什么，服务执行。外部剪辑器不改变这里的成片，已舍弃。

默认硬切，结尾淡出 2 到 3 秒。不用淡入淡出掩盖不连续。旁白用已入库成音。音效或配乐约加 8 dB，限幅约 -1 dB，旁白出现时闪避。

字幕只在歌词或对白必须留在画面上时烧录。没有台词就不要烧。

操作：

- 拼接：`cvgen edit <成片甲> <成片乙> --fade 2.5 --title 名称`
- 混配乐：加 `--music <配乐成片或asset:名称@版本>`，有旁白再加 `--narration <旁白成片>`
- 贴字：加 `--subtitle '["台词一","台词二"]'`，只在台词必须留在画面上时使用
- 导出到档位：加 `--export 768p横`
- `cvgen job wait <任务>` 等到结束，读成片链接；`cvgen media get <文件id> -o 成片.mp4` 下载

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
