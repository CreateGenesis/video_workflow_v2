# cvgen-library

素材库是工作区级的，带版本。作品里的实体只属于这个作品；要在别的作品或工作流里复用，先提升成素材。发布的工作流钉死版本，改素材只会产生新版本，不会悄悄改掉已发布的工作流。

操作：

- `cvgen asset list [--kind Style]`、`cvgen asset show <名称>` 看素材和所有版本。
- `cvgen asset promote <实体> <素材名> --note 说明`：把作品里的实体（连同文件）提升为素材的新版本。
- `cvgen asset save <名称> <类型> <JSON> [--artifact 文件id]`：直接写素材。类型是本体类型（Style、Subject、Appearance、Place、Detail、Camera、Beat、Voice、Reference）或 prompt、schema、comfy_template、media。
- 在作品里连素材：`cvgen link <关系> <镜头> asset:名称@版本`。

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
