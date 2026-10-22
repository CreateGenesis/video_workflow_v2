# cvgen-edit

来源：后处理剪辑。命令只描述剪什么，服务执行。外部剪辑器不改变这里的成片，已舍弃。

默认硬切，结尾淡出 2 到 3 秒。不用淡入淡出掩盖不连续。旁白用已入库成音。音效或配乐约加 8 dB，限幅约 -1 dB，旁白出现时闪避。

字幕只在歌词或对白必须留在画面上时烧录。没有台词就不要烧。

操作：

- `cvgen edit join <成片甲> <成片乙>`
- `cvgen edit export <剪辑>` 导出已连成片和旁白的时间线
- `cvgen edit mix <剪辑>` 混入已入库配乐。剪辑要先写上 music，有旁白再写 narration
- `cvgen edit subtitle <剪辑>` 只在 lines 里有台词时使用
- `cvgen job show <任务>` 读取成片。需要等到结束时发 `cvgen job wait <任务>`
