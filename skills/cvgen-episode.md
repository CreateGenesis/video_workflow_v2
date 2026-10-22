# cvgen-episode

来源：okaypic 的多角度定妆、每镜留版本、断点续跑，以及 i2v 的只重做失败镜头。付费接口和重复提交已成功镜头没有新画面，已舍弃。

定妆是 Appearance 加多张身份参考。同一镜头要第二版时，新建另一个镜头并注明来源。一个镜头最多两版。服务拒绝重复提交时，读任务状态，不要自己重发。

只重提未生成或失败的镜头。排队、已成片、提交不明都不重提。

操作：

- `cvgen entity add Appearance '{"title":"正面定妆","face":"...","costume":"..."}'`
- `cvgen link has_appearance <主体> <外形>`
- `cvgen image <镜头> --role 身份` 补侧面或背面定妆，再 `cvgen link references <镜头> <参考>`
- `cvgen batch show <作品>` 看哪些镜头还是“未生成”或“失败”
- 对这两类镜头逐条发 `cvgen generate <镜头>`
