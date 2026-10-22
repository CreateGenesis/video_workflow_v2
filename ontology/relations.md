# 关系

边是有方向的。组合时从镜头向外查，不把目标实体复制进镜头。

实体归属哪个作品由服务记录（作品 id），不再用关系表示。关系的目标可以是同一作品里的实体，也可以是素材库里钉死版本的素材。from 和 to 可以列多个类型，用逗号分隔。

## has_appearance
from: Subject
to: Appearance
label: 有一套外形

## wears
from: Subject
to: Appearance
label: 穿着这一套

## located_in
from: Shot
to: Place
label: 发生在这个空间

## holds
from: Shot
to: Detail
label: 这一镜要保住这个物件

## detail_of
from: Detail
to: Subject
label: 属于这个主体

## styled_as
from: Shot
to: Style
label: 使用这个风格

## shot_with
from: Shot
to: Camera
label: 使用这一种运镜

## voices
from: Shot
to: Line
label: 这一镜说这句

## voiced_by
from: Shot
to: Voice
label: 使用这个音色

## contrasts_with
from: Shot
to: Beat
label: 和上一拍形成反差

## continues
from: Shot
to: Shot
label: 接在上一镜之后

## references
from: Shot, Voice
to: Reference
label: 使用这张参考

## derived_from
from: Clip, Reference
to: Clip, Reference
label: 派生自已有成片或参考

## uses_clip
from: Edit
to: Clip
label: 时间线使用这条成片
