# cvgen-continuity

来源：codex、i2v 和歌词片里的首尾帧续拍。下一镜的空间必须接上一镜的真实尾帧，不能靠文字假装接上。

同一场景：抽上一镜尾帧，用途写成空间或首帧，再连到下一镜。提示词写动作从下文重新开始。硬切到新场景时，不把尾帧当空间，只保持服装、光线和角色卡。

只重做中间时，同时连首帧和尾帧。`cvgen shot compose` 会把首帧放在 0.00 秒、尾帧放在成片时长。

操作：

- `cvgen frame <上一镜成片> --at last --role 空间`，`cvgen job wait <任务>` 拿到参考实体 id。
- 已拒绝，不再执行：`cvgen link references <下一镜> <抽出的参考>`
- 需要锁结尾时 `cvgen frame <目标成片> --at last --role 尾帧`，或上传一张尾帧。
- `cvgen shot compose <下一镜>` 确认对齐句后 `cvgen generate <下一镜>`
- 定型成工作流时，视频节点写 `"continuity": "previous_last_frame"`，服务会自动串行并接上尾帧。

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
