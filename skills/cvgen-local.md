# cvgen-local

来源：cheercheung、Evolink 和本机上传需求。本机已经做好的图、视频、音频不应在云端重画，重画会丢质量。安装脚本和密钥检查不改变素材，已舍弃。

图片入库为参考。视频或音频入库为成片。上传后再连接，不在对话里描述文件内容就算已入库。

操作：

- `cvgen upload <文件> [--label 名称]` 上传，返回文件 id。大文件流式上传，不占内存。
- 图片作为参考：`cvgen entity add Reference '{"title":"...","role":"身份","take":"...","ignore":"..."}' --artifact <文件id>`
- 视频或音频作为成片：`cvgen entity add Clip '{"title":"..."}' --artifact <文件id>`
- `cvgen link references <镜头> <参考>`，或把成片放进 `cvgen edit`
