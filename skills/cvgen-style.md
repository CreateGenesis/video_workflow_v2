# cvgen-style

来源：品牌宣传、极简产品广告、三维动画短片、手绘结合实拍、歌词卡点。纸艺定格和纸拼贴只作为禁止项。H3 会把定格写成正面要求，成片发呆。

可用预设：品牌宣传、极简产品广告、三维动画短片、手绘结合实拍、歌词卡点。

禁止写成正面风格：纸艺、定格、拼贴、停格组装。需要这些质感时，只在 ban 里写“禁止定格和拼贴停顿”。

操作：

- 已拒绝，不再执行：`cvgen entity add Style '{"title":"品牌宣传","medium":"真人电影感","grade":"统一光线和调色","ban":"禁止定格、拼贴、仿造标识、字幕和水印"}'`
- `cvgen link styled_as <镜头> <风格>`；风格定型后 `cvgen asset promote <风格> <素材名>`，以后直接连 `asset:素材名@版本`。
- 想从已有片子提取时 `cvgen inspect <成片> --mode style`，服务写回一个 Style 草稿，agent 再决定是否连到镜头。

已拒绝：本文件里的 `cvgen entity add`、`cvgen entity add Reference`、`cvgen link references` 以及会新建 Reference 或 references 的旧探索命令不再执行。当前步骤见 `skills/cvgen-index.md`：人物上传、补图、设定精确替换、漫剧缺项。
