"""Server-side administration: python -m server.manage <command>.

  migrate                         apply database migrations
  create-user NAME --role admin   create a person (password from --password or prompt)
  reset-password NAME             set a new password (replaces the old env "recovery password")
  seed-samples [--workspace ID]   load the sample assets and workflows from docs/design/examples
  import-legacy PATH              import works from a v1 SQLite file (data/cvgen.sqlite)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import insert, select, update

from . import db


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    from .config import ROOT

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "server" / "migrations"))
    command.upgrade(config, "head")


def _password(given: str) -> str:
    if given:
        return given
    first = getpass.getpass("新密码（至少 8 位）：")
    if first != getpass.getpass("再输入一次："):
        sys.exit("两次输入不一致")
    return first


def create_user(name: str, role: str, password: str, display_name: str = "") -> str:
    from .auth import ROLES
    from .security import hash_password

    if role not in ROLES:
        sys.exit(f"角色只能是 {'、'.join(ROLES)}")
    with db.tx() as conn:
        if conn.execute(select(db.users.c.id).where(db.users.c.username == name)).first():
            sys.exit("账号已存在")
        user_id = db.new_id("user")
        conn.execute(insert(db.users).values(id=user_id, username=name, display_name=display_name or name, role=role,
                                             password_hash=hash_password(_password(password))))
    return user_id


def reset_password(name: str, password: str) -> None:
    from .security import hash_password

    with db.tx() as conn:
        row = conn.execute(select(db.users.c.id).where(db.users.c.username == name)).first()
        if not row:
            sys.exit("没有这个账号")
        conn.execute(update(db.users).where(db.users.c.id == row.id).values(password_hash=hash_password(_password(password))))
        conn.execute(db.sessions.delete().where(db.sessions.c.user_id == row.id))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m server.manage")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    user = sub.add_parser("create-user")
    user.add_argument("name")
    user.add_argument("--role", default="producer")
    user.add_argument("--password", default="")
    user.add_argument("--display-name", default="")
    reset = sub.add_parser("reset-password")
    reset.add_argument("name")
    reset.add_argument("--password", default="")
    samples = sub.add_parser("seed-samples")
    samples.add_argument("--workspace", default="")
    samples.add_argument("--publish", action="store_true")
    legacy = sub.add_parser("import-legacy")
    legacy.add_argument("path")
    legacy.add_argument("--workspace", default="")
    args = parser.parse_args(argv)
    if args.command == "migrate":
        migrate()
        print("数据库已是最新")
    elif args.command == "create-user":
        print(create_user(args.name, args.role, args.password, args.display_name))
    elif args.command == "reset-password":
        reset_password(args.name, args.password)
        print("密码已更新，旧登录已失效")
    elif args.command == "seed-samples":
        from .samples import seed_samples

        print(seed_samples(args.workspace or None, publish=args.publish))
    elif args.command == "import-legacy":
        from .legacy import import_sqlite

        print(import_sqlite(args.path, args.workspace or None))


if __name__ == "__main__":
    main()
