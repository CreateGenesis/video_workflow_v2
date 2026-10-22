# cvgen-brand

来源：官方品牌宣传技能。画布手续和外部生图工具不改变成片，已舍弃。标识、产品和宣传事实必须核对，仿造会毁掉成片。

先核对三件事：用户给了真实标识或产品图，宣传句来自用户或已入库观察，15 秒只留五拍。五拍是钩子、场景、机制、证明、标识。没有真实标识时，结尾不补假标识。

观察来自已入库成片或参考。看不清的包装文字标成看不清，不按常识补全。

操作：

- `cvgen media upload <产品图> --kind image --role 细节`
- `cvgen entity add Style '{"title":"品牌宣传","medium":"真人电影感","grade":"统一光线和调色","ban":"禁止定格、仿造标识、字幕和水印"}'`
- `cvgen link styled_as <镜头> <风格>`
- `cvgen shot compose <镜头>` 确认五拍和主动作后再 `cvgen generate <镜头>`
- `cvgen check <成片>` 确认时长和分辨率，再进入剪辑
