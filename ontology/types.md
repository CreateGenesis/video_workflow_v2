# 实体类型

服务启动时读取这份原型。实例存在库里，类型不写死在表结构上。

## Work
label: 作品
summary: 短片或广告主题。批量生产只是把风格、运镜和镜头挂在这里。
field title 必填 名称
field brief 选填 主题
field kind 选填 短片或广告

## Subject
label: 主体
summary: 角色、产品或讲述者。
field title 必填 名称
field summary 选填 是谁或是什么
field age 选填 年龄或阶段

## Appearance
label: 外形
summary: 一套锁定的脸、服装、年龄和材质。
field title 必填 名称
field face 选填 脸和头发
field costume 选填 服装
field material 选填 材质

## Detail
label: 细节
summary: 必须单独保住的物件，例如锁、纱布、商标、门漆。
field title 必填 名称
field measure 选填 可测量的关系
field material 选填 颜色和材质

## Place
label: 空间
summary: 空镜、光线和左右陈设。每条镜头都重复这些事实。
field title 必填 名称
field facts 选填 门、家具、窗户、光线方向

## Style
label: 风格
summary: 固化的介质、调色、颗粒和禁止项。
field title 必填 名称
field medium 选填 介质
field grade 选填 调色和光线
field ban 选填 禁止项

## Camera
label: 运镜
summary: 一条镜头只用一种运动，并写明幅度和速度。
field title 必填 名称
field move 必填 运动或固定镜头
field amplitude 选填 幅度
field speed 选填 速度

## Beat
label: 情绪
summary: 这一拍的情绪。反差用关系表示，不堆在同一句里。
field title 必填 名称
field curve 选填 情绪曲线
field turn 选填 反转

## Shot
label: 镜头
summary: 一次生成意图。一个主动作，最多两个细节。
field title 必填 名称
field size 必填 景别
field angle 必填 角度
field action 必填 主动作
field details 选填 最多两个细节
field duration 选填 秒数，1 到 15
field paragraphs 选填 15 秒内最多四拍，每拍含景别、角度、运动、动作和反向
field dialogue 选填 这一个镜头的台词
field sound 选填 声音来源
field reverse 选填 这一镜最可能偷的懒
field ending 选填 结尾是正面或面部

## Line
label: 台词
summary: 对白或旁白。旁白不写进 H3 提示词。
field title 必填 名称
field text 必填 台词
field kind 选填 对白或旁白
field speaker 选填 说话人

## Voice
label: 音色
summary: IndexTTS2 的音色参考和情绪向量。
field title 必填 名称
field method 选填 与音色参考音频相同、使用情感参考音频、使用情感向量控制
field happy 选填 0 到 1.4
field angry 选填 0 到 1.4
field sad 选填 0 到 1.4
field afraid 选填 0 到 1.4
field disgusted 选填 0 到 1.4
field melancholic 选填 0 到 1.4
field surprised 选填 0 到 1.4
field calm 选填 0 到 1.4

## Reference
label: 参考
summary: 一张图、一段音或一条视频。每张图只有一个用途。
field title 必填 名称
field role 必填 身份、空间、细节、风格、分镜、音色、情感、首帧、尾帧
field take 选填 只采用什么
field ignore 选填 不采用什么
field source_url 选填 来源地址

## Clip
label: 成片
summary: 服务入库后的视频或声音。写了提示词不等于已成片。
field title 必填 名称
field duration 选填 秒
field resolution 选填 分辨率

## Observation
label: 观察
summary: ffmpeg 或网上片子测到的结果。
field title 必填 名称
field summary 选填 测量结论

## Edit
label: 剪辑
summary: 一条时间线。剪辑由服务执行。
field title 必填 名称
field note 选填 入出点和淡出
field narration 选填 旁白成片
field music 选填 配乐成片
field lines 选填 必须留在画面上的台词
