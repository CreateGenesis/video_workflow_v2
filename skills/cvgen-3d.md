# cvgen-3d

来源：三维动画短片。风格锁、角色卡、场景卡和生成前镜头表减少跳变。画布节点和备用模型不改变这一条片子的画面，已舍弃。

风格默认写进 Style：风格化三维、块面清楚、边缘有细毛发、皮肤有透光、动作有预备和弹性。禁止写成真人摄影、扁平线条、塑料皮肤、僵硬解剖。

角色卡只锁身份、服装和比例。场景卡不放人物。镜头表在生成前自检：每镜一个主动作，时长 1 到 15 秒，下一镜空间接上一镜尾帧。

操作：

- 已拒绝，不再执行：`cvgen entity add Style '{"title":"三维动画短片","medium":"风格化三维","grade":"块面清楚，边缘有细毛发","ban":"禁止真人摄影、塑料皮肤和定格"}'`
- 已拒绝，不再执行：`cvgen entity add Appearance '{"title":"角色卡","face":"...","costume":"..."}'`
- `cvgen link has_appearance <主体> <外形>`
- `cvgen image <镜头> --role 身份` 出角色卡，`cvgen image <场景镜头> --role 空间` 出无人物场景卡。
- 角色卡和风格定下来后 `cvgen asset promote <实体> <素材名>`，以后的作品直接连 `asset:素材名@版本`。
- 镜头表确认后逐条 `cvgen generate <镜头>`。超过 15 秒拆成多条再 `cvgen edit <成片...>`。

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
