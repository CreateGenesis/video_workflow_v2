"""Workspace and work ownership. Positions never become relations."""

from __future__ import annotations

SHOT_LINKS = {
    "located_in",
    "holds",
    "styled_as",
    "shot_with",
    "voices",
    "voiced_by",
    "contrasts_with",
    "continues",
    "references",
}
FOLLOW_LINKS = {"has_appearance", "wears", "detail_of"}
RETRYABLE = {"failed", "unknown"}
BLOCKED_RETRY = {"queued", "running", "succeeded"}


def ensure_scope(store) -> dict:
    """Every work belongs to exactly one workspace. Existing works join the first one."""
    workspaces = store.list_entities("Workspace")
    if not workspaces:
        workspace = store.add_entity("Workspace", {"title": "默认工作区"})
        workspaces = [workspace]
    first = workspaces[0]
    for work in store.list_entities("Work"):
        owners = [
            link for link in store.all_links()
            if link["name"] == "contains" and link["target_id"] == work["id"]
        ]
        if not owners:
            store.add_link("contains", first["id"], work["id"], "归入第一个工作区")
    return {"workspace_id": first["id"]}


def work_of_shot(store, shot_id: str) -> str:
    links = [link for link in store.links(shot_id, "belongs_to")]
    if not links:
        raise ValueError("镜头还没有属于作品")
    return links[0]["target_id"]


def workspace_of_work(store, work_id: str) -> str:
    owners = [
        link for link in store.all_links()
        if link["name"] == "contains" and link["target_id"] == work_id
    ]
    if not owners:
        raise ValueError("作品还没有工作区")
    return owners[0]["source_id"]


def require_selection(store) -> tuple[str, str]:
    workspace_id = store.setting("selected_workspace")
    work_id = store.setting("selected_work")
    if not workspace_id or not work_id:
        raise ValueError("先选择工作区和作品")
    workspace_of_work(store, work_id)
    if workspace_of_work(store, work_id) != workspace_id:
        raise ValueError("当前作品不在选中的工作区")
    return workspace_id, work_id


def owner_of(store, entity_id: str) -> str | None:
    try:
        return _owner(store, entity_id)
    except (KeyError, ValueError):
        return None


def stamp_work(data: dict, work_id: str) -> dict:
    """Record the selected work at create time. Relations cannot invent an owner later."""
    stamped = dict(data)
    stamped["work_id"] = work_id
    return stamped


def in_selected_work(store, entity_id: str, work_id: str) -> bool:
    try:
        entity = store.get_entity(entity_id)
    except KeyError:
        return False
    if entity["type"] == "Workspace":
        return False
    if entity["type"] == "Work":
        return entity_id == work_id
    stamped = entity["data"].get("work_id")
    if stamped and stamped != work_id:
        return False
    if entity_id in work_scope(store, work_id):
        return True
    if stamped == work_id:
        return True
    return False


def same_work(store, left_id: str, right_id: str) -> bool:
    return _owner(store, left_id) == _owner(store, right_id)


def _owner(store, entity_id: str) -> str:
    entity = store.get_entity(entity_id)
    if entity["type"] == "Work":
        return entity_id
    if entity["type"] == "Shot":
        return work_of_shot(store, entity_id)
    for link in store.all_links():
        if link["target_id"] == entity_id and link["name"] in SHOT_LINKS | FOLLOW_LINKS | {"uses_clip", "derived_from"}:
            try:
                return _owner(store, link["source_id"])
            except (KeyError, ValueError):
                continue
        if link["source_id"] == entity_id and link["name"] == "belongs_to":
            return link["target_id"]
    raise ValueError("实体不在当前作品")


def can_retry(job: dict) -> tuple[bool, str]:
    status = job.get("status")
    if status in BLOCKED_RETRY:
        return False, "排队、执行中或已成功的任务不能重试"
    if status not in RETRYABLE:
        return False, "这个任务不能重试"
    detail = job.get("detail") or {}
    if status == "unknown" and detail.get("provider_task"):
        return False, "已有上游任务号，不重发"
    if job.get("kind") == "generate" and status == "unknown" and detail.get("submitted") and detail.get("provider_task"):
        return False, "已有上游任务号，不重发"
    return True, ""


def restore_prompt(versions: list[dict], index: int, text: str) -> list[dict]:
    """Restore writes a new version. Older versions stay."""
    if index < 0 or index >= len(versions):
        raise ValueError("没有这一版")
    chosen = versions[index]["text"]
    if chosen != text and not versions:
        raise ValueError("没有这一版")
    return [*versions, {"text": chosen}]


def tidy_positions(nodes: list[dict]) -> dict[str, dict[str, int]]:
    grouped: dict[str, list[dict]] = {}
    for node in nodes:
        grouped.setdefault(node["type"], []).append(node)
    positions = {}
    for column, type_name in enumerate(sorted(grouped)):
        for row, node in enumerate(grouped[type_name]):
            positions[node["id"]] = {"x": column * 260, "y": row * 150}
    return positions


def work_scope(store, work_id: str) -> set[str]:
    """Entities that belong on this work's canvas. Other works stay out."""
    ids = {work_id}
    ids.update(
        entity["id"] for entity in store.list_entities()
        if entity["data"].get("work_id") == work_id
    )
    shots = [
        link["source_id"] for link in store.all_links()
        if link["name"] == "belongs_to" and link["target_id"] == work_id
    ]
    ids.update(shots)
    changed = True
    while changed:
        changed = False
        for link in store.all_links():
            if link["source_id"] in ids and link["name"] in SHOT_LINKS | FOLLOW_LINKS | {"uses_clip", "derived_from", "voices"}:
                if link["target_id"] not in ids:
                    ids.add(link["target_id"])
                    changed = True
            if link["target_id"] in ids and link["name"] in FOLLOW_LINKS and link["source_id"] not in ids:
                ids.add(link["source_id"])
                changed = True
    return ids
