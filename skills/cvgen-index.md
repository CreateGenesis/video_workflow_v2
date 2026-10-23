# cvgen 技能索引

下载包只带这份索引。登录后用 `cvgen skill list` 看目录，用 `cvgen skill show <名称>` 读取正文（原文输出）。正文在服务端。

先做三步：

1. `cvgen login --base 服务地址`：终端打印设备码和批准地址，请有权限的人在网页上批准。凭证只存在本机用户目录。
2. `cvgen workspace list`，然后 `cvgen workspace use <工作区id>`。
3. `cvgen work new <名称>` 新建作品（会自动设为当前作品），或 `cvgen work use <作品id>` 接着做已有作品。

之后的命令都作用在当前作品上。`cvgen --help` 列出全部命令和退出码，任何命令后加 `--help` 只看说明、不执行。
提交任务后用 `cvgen job wait <任务id>` 等结果，用 `cvgen media get <文件id> -o <路径>` 下载，用 `cvgen upload <文件>` 上传本机素材。

| 名称 | 什么时候读 |
| --- | --- |
| cvgen-modes | 写对齐句、统一参考标签、让描述时长等于请求时长 |
| cvgen-h3-prompt | 写四段中文提示词、一种运镜、空间参考 |
| cvgen-brand | 核对标识、产品和宣传事实，再按五拍生成 |
| cvgen-product-ad | 用三张锚定图和一个主动作做产品广告 |
| cvgen-3d | 锁风格、角色卡、场景卡，生成前自检镜头表 |
| cvgen-handdrawn | 手绘层和实拍层必须同时写进风格 |
| cvgen-music | 超过 15 秒拆镜，歌词放台词，量时长再拼接 |
| cvgen-episode | 定妆，每镜最多两版，只重提未生成或失败镜头 |
| cvgen-continuity | 上一镜尾帧接下一镜 |
| cvgen-reverse | 先复述再写提示词，声音没测到不编 |
| cvgen-check | 核对台词、衔接、时长和分辨率 |
| cvgen-edit | 硬切、淡出、旁白闪避、配乐混音、可选字幕 |
| cvgen-local | 上传本机图片、视频、音频再连接 |
| cvgen-learn | 让服务下载，agent 不自己下载 |
| cvgen-style | 锁定可用预设，避开定格和拼贴 |
| cvgen-zero | 已测过的 15 秒雪原段 |

纸艺、定格、拼贴只作为禁止项，不作为正面风格。
