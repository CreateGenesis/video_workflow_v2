# cvgen-product-ad

来源：极简产品广告。三张锚定图和一个主动作决定产品是否认得出来。自动节拍识别会切错，已舍弃。配乐走 `cvgen music`。

先写一句叙事脊柱：发布、功能触感，或色彩家族。多款只留一个主推款，其他款晚一点进入。每个节拍只有一个主动作。

三张锚定图必须分开入库，不能拼成一张宫格：

- 主视角：轮廓和开场方向。
- 细节：材质、开合、按钮或屏幕。
- 结尾：产品和已确认文案的位置。没有真实标识时不补假标识。

开头必须尽快给出产品动作。空镜、镜面白底、假界面和粒子不能占时间。

操作：

- 已有照片：`cvgen upload <文件>`，再 `cvgen entity add Reference '{"title":"主视角","role":"身份"}' --artifact <文件id>`，三张分别入库。
- 没有照片时 `cvgen image <镜头> --role 细节 --n 2`。要改镜头标题用 `cvgen entity set <镜头> '{"title":"..."}'`。
- `cvgen shot compose <镜头>` 后 `cvgen generate <镜头>`，`cvgen job wait <任务>`。
- 需要可控配乐时 `cvgen music <文案>`，再 `cvgen edit <成片...> --music <配乐成片> --export 768p横`。
- 这一套跑顺后按 `cvgen-workflow` 定型成工作流；产品广告示例工作流可以先 `cvgen workflow list` 看。
