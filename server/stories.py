"""Seed the Zero carry scene as linked ontology, not a copied prompt."""

from __future__ import annotations

from .store import Store

ZERO_PARAGRAPHS = [
    {
        "size": "大远景",
        "angle": "平视",
        "motion": "缓慢横移",
        "action": "蓝色黄昏的雪原上，雷娜塔坐在倒伏白桦上，零号单膝跪在她面前，两个身影小得像黑点",
        "reverse": "不要让人物站起来走路，不要出现其他人物。",
    },
    {
        "size": "特写",
        "angle": "平视",
        "motion": "固定镜头",
        "action": "零号的双手在画面中央，把白纱布绕两圈，纱布边缘压住前一圈",
        "details": "只看见旧军大衣袖口和纱布，不看见脚面",
        "reverse": "不要拍脚部特写，不要出现血迹。",
    },
    {
        "size": "中近景",
        "angle": "略俯",
        "motion": "固定镜头",
        "action": "零号抬起头，眉头皱起又松开，撇嘴说：“女人就是嫩点，没办法咯，我背你吧。”嘴里呼出白气",
        "reverse": "这句只由零号说，雷娜塔不动嘴，零号不笑。",
    },
]


def seed_zero_carry(store: Store) -> dict:
    work = store.add_entity("Work", {"title": "你就叫零", "kind": "短片", "brief": "雪原上把她背起来"})
    place = store.add_entity("Place", {
        "title": "西伯利亚雪原",
        "facts": "稀疏白桦，倒伏白桦在左，积雪没过小腿，风从画面右侧吹来，地平线有一线暗橙",
    })
    detail = store.add_entity("Detail", {
        "title": "白纱布卷",
        "measure": "绕两圈，后一圈压住前一圈",
        "material": "白棉纱",
    })
    style = store.add_entity("Style", {
        "title": "雪原电影",
        "medium": "真人实拍电影质感，35mm 颗粒，浅景深",
        "grade": "蓝色黄昏，侧逆光，冷蓝雪白，地平线暗橙",
        "ban": "禁止定格、字幕、血迹、脚部特写和新增人物。",
    })
    camera = store.add_entity("Camera", {"title": "一段一镜", "move": "固定镜头", "amplitude": "小", "speed": "慢"})
    beat = store.add_entity("Beat", {"title": "嫌弃里的照料", "curve": "寒冷疲惫翻成粗声里的温柔", "turn": "抬眼时眉头松开"})
    space = store.add_entity("Reference", {
        "title": "空镜雪原",
        "role": "空间",
        "take": "雪原、白桦和蓝色黄昏",
        "ignore": "人物和动作",
    }, "references/zero-space.png")
    gauze = store.add_entity("Reference", {
        "title": "纱布卷",
        "role": "细节",
        "take": "白纱布的卷法和棉纱纹理",
        "ignore": "背景和人物",
    }, "references/zero-gauze.png")
    shot = store.add_entity("Shot", {
        "title": "背她之前",
        "size": "特写",
        "angle": "平视",
        "action": "零号用纱布包好，再抬头说要背她",
        "duration": 15,
        "sound": "风声、雪粉、纱布细响",
        "paragraphs": ZERO_PARAGRAPHS,
    })
    store.add_link("belongs_to", shot["id"], work["id"], "零的故事这一段")
    store.add_link("located_in", shot["id"], place["id"])
    store.add_link("holds", shot["id"], detail["id"], "纱布必须占一个特写")
    store.add_link("styled_as", shot["id"], style["id"])
    store.add_link("shot_with", shot["id"], camera["id"])
    store.add_link("contrasts_with", shot["id"], beat["id"], "嫌弃翻成照料")
    store.add_link("references", shot["id"], space["id"], "只锁雪原，动作重新开始")
    store.add_link("references", shot["id"], gauze["id"], "只锁纱布")
    return {"work_id": work["id"], "shot_id": shot["id"], "space_id": space["id"], "gauze_id": gauze["id"]}
