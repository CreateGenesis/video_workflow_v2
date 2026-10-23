# cvgen-handdrawn

来源：手绘结合实拍。只写一层时，另一层会丢。风格必须同时写手绘层和实拍层。

手绘层是蜡笔、粉笔或色粉，线条抖动，有涂抹和毛边。实拍层是同一空间里的手、桌面或墙。0 到 3 秒必须有一次清楚接触。同一个手绘实体连续变形，不突然换人。镜头慢半拍跟着走。禁止三维玩具感、均匀矢量线、恐怖牙齿和跳吓。

15 秒横屏只留一条主动作链：接触、变形、追逐、空间扩散。不要跳到另一个地点。

操作：

- `cvgen entity add Style '{"title":"手绘结合实拍","medium":"实拍空间里的手绘发光层","grade":"蜡笔毛边，同一实体连续变形","ban":"禁止三维玩具感、矢量线和跳吓"}'`
- `cvgen link styled_as <镜头> <风格>`
- 实拍参考：`cvgen upload <图片>`，再 `cvgen entity add Reference '{"title":"桌面","role":"空间"}' --artifact <文件id>`
- `cvgen shot compose <镜头>` 确认两层都在风格句里，再 `cvgen generate <镜头>`
