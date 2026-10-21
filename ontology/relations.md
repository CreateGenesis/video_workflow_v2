# 关系

边是有方向的。组合时从镜头向外查，不把目标实体复制进镜头。

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
from: Shot
to: Reference
label: 使用这张参考

## derived_from
from: Reference
to: Clip
label: 派生自这条成片

## uses_clip
from: Edit
to: Clip
label: 时间线使用这条成片

## belongs_to
from: Shot
to: Work
label: 属于这个作品
