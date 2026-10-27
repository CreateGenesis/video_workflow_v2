# cvgen 技能索引

登录目标是平台：`cvgen login --base 平台地址`。凭证只存在本机用户目录。之后的命令都打已登录的平台，不再另给 `--base`。

当前步骤：

1. 上传人物：`cvgen character add --name <名称> --image <图片> --setting <设定文件> --voice <音频>`。`--image` 可以重复，至少一张。
2. 补图：先 `cvgen character get <id>`，再 `cvgen character image add <id> --image <图片> --revision <修订号>`。只追加，不替换已有图片。
3. 设定精确替换：先 `cvgen character get <id>` 读到原文和修订号，再 `cvgen character setting <id> --revision <修订号> --old <原文> --new <替换>`。`old` 必须正好出现一次。
4. 漫剧缺项：`cvgen comic missing --episode <集id>`。输出停在哪一闸门、缺哪一项。客户端不在本地拼 H3。

已拒绝，不是当前步骤：

- `cvgen entity add`、`cvgen entity add Reference`、`cvgen entity add references`、`cvgen link references`。这些命令会新建 Reference 或 references，调用时客户端拒绝。
- 旧探索流：`work new`、实体、关系、工作流 JSON、`generate`、`pull`、`frame`。目录里没有这些命令。

| 名称 | 什么时候读 |
| --- | --- |
| cvgen-modes | 只读对齐句。里面的 `entity add Reference` 已拒绝 |
| cvgen-h3-prompt | 只读六段式约束。不执行旧的 `entity add` |
| cvgen-local | 上传文件后交给人物命令，不建 Reference |
