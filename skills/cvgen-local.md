# cvgen-local

来源：cheercheung、Evolink 和本机上传需求。本机已经做好的图、视频、音频不应在云端重画，重画会丢质量。安装脚本和密钥检查不改变素材，已舍弃。

图片入库为参考。视频或音频入库为成片。上传后再连接，不在对话里描述文件内容就算已入库。

操作：

- `cvgen media upload <图片> --kind image --role 身份`
- `cvgen media upload <视频> --kind video`
- `cvgen media upload <音频> --kind audio`
- `cvgen link references <镜头> <参考>`，或把视频成片放进剪辑
- 已有 `cvgen reference upload` 仍可用于参考图
