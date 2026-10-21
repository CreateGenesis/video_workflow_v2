# cvgen-episode

来源：okaypic-video-skill 的多角度定妆、每镜留版本、断点续跑。不接它的付费接口。

定妆是 Appearance 加多张身份参考。同一镜头要第二版时，新建另一个镜头并注明来源，不重复提交已有任务的镜头。服务拒绝重复 POST 时，读任务状态，不要自己重发。

操作：

- `cvgen entity add Appearance '{"title":"正面定妆","face":"...","costume":"..."}'`
- `cvgen link has_appearance <主体> <外形>`
- `cvgen batch show <作品>` 看哪些镜头还是“未生成”
- 对未生成的镜头逐条发 `cvgen generate <镜头>`
