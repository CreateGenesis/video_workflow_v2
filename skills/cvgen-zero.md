# cvgen-zero

来源：已测过的「你就叫零」雪原段，加上 h3-prompt-writing 的镜头顺序和 okaypic 的分资产。旧稿把包扎、台词和背人挤在四段里，纱布没有自己的镜头。这里改成服务组合。

这一段演的是嫌弃翻成照料。15 秒只留三拍：远景建立、纱布特写、抬头说要背。背人的起身留给下一条，避免一段里两个主动作。

操作：

- 雪原段的地点、纱布、风格、运镜、两张参考已经在素材库：`cvgen asset list` 能看到 `style-snow-film`、`place-siberia-snow`、`detail-gauze-roll`、`camera-one-move`、`ref-zero-space`、`ref-zero-gauze`。
- 探索时：`cvgen work new 雪原`，`cvgen entity add Shot '{...}'`，再把镜头 `cvgen link` 到这些 `asset:名称@1`。
- `cvgen shot compose <镜头>` 读四段提示词。确认三拍、纱布特写和“动作从下文重新开始”。
- 警告为空后再 `cvgen generate <镜头>`，`cvgen job wait <任务>` 等到结束，再读成片和接触表。
- 定型后的版本是工作流“小说片段-雪原-15秒”：`cvgen workflow dry-run <工作流id> 1 '{"passage":"原文"}'` 不花钱看到完整提示词。
