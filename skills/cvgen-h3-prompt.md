# cvgen-h3-prompt

来源：h3-prompt-writing。这里保留四段中文结构。生成由 `cvgen generate` 托管。

一条镜头只写一个主动作，一种运镜，并写明幅度和速度。参考图按连接顺序编号，每张只写采用什么、不采用什么。空间参考必须写“动作从下文重新开始”。声音和音乐分开写。不要把旁白写进画面提示词。

首帧对齐 0.00 秒，尾帧对齐成片时长。这两句由 `cvgen shot compose` 写在提示词开头。

操作：

- `cvgen entity add Shot '{"title":"...","size":"中景","angle":"平视","action":"...","duration":5}'`
- 参考图：`cvgen upload <文件>`，再 `cvgen entity add Reference '{"title":"...","role":"细节","take":"...","ignore":"..."}' --artifact <文件id>`；素材库里的参考直接连 `asset:名称@版本`。
- `cvgen link references <镜头> <参考或asset:名称@版本>`
- `cvgen shot compose <镜头>`。有警告时先改实体（`cvgen entity set`）；确认警告可以接受再 `cvgen generate <镜头> --force`。
- `cvgen job wait <任务>` 等到结束，`cvgen job show <任务>` 读成片和接触表链接。
