"""CLI catalog served at GET /api/cli. The client executes these generically.

Commands that create Reference or references are absent. The client rejects those names
even when an older cache still lists them.
"""

from __future__ import annotations

SCHEMA_VERSION = 2
MIN_CLIENT = "0.2.0"


def flag(name: str, flag_name: str, *, into: str = "query", type: str = "string", required: bool = False, help: str = "") -> dict:
    return {
        "name": name,
        "source": "flag",
        "flag": flag_name,
        "in": into,
        "type": type,
        "required": required,
        "help": help,
    }


def cmd(name: str, usage: str, summary: str, method: str, path: str, args: list[dict] | None = None) -> dict:
    return {
        "name": name,
        "usage": usage,
        "summary": summary,
        "method": method,
        "path": path,
        "args": args or [],
        "body": {},
        "local": False,
    }


COMMANDS = [
    cmd(
        "comic missing",
        "cvgen comic missing --episode <集id>",
        "查看停在哪一闸门、缺哪一项。只问平台，不在本地拼 H3",
        "GET",
        "/api/comic/missing",
        [flag("episode_id", "--episode", required=True, help="集 id")],
    ),
]

REMOVED = (
    "entity add",
    "entity add Reference",
    "entity add references",
    "link references",
)


def catalog() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "min_client": MIN_CLIENT,
        "commands": COMMANDS,
        "removed": list(REMOVED),
    }
