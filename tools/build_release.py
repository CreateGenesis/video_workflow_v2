"""Zip native cvgen binaries plus the skill index."""

from __future__ import annotations

import argparse
import os
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTE = """cvgen 操作工具

解压后直接运行可执行文件。先读 skills/cvgen-index.md。
登录后用 cvgen skill show <名称> 读取正文。正文在服务端，不在这个压缩包里。
Linux / macOS：./cvgen login --base 服务地址
Windows：cvgen.exe login --base 服务地址

网页管理员批准设备码后，这台 cvgen 才会在线。同时只能有一台在线。
"""


def _add(archive: zipfile.ZipFile, name: str, payload: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name)
    mode = stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
    if not executable:
        mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
    info.external_attr = mode << 16
    archive.writestr(info, payload)


def package(out: Path, binaries: dict[str, Path]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    specs = {
        "cvgen-linux-x64.zip": ("cvgen", binaries["linux"]),
        "cvgen-macos.zip": ("cvgen", binaries["macos"]),
        "cvgen-windows-x64.zip": ("cvgen.exe", binaries["windows"]),
    }
    selected = os.environ.get("CVGEN_PACK_ONLY", "")
    written = []
    for filename, (name, source) in specs.items():
        platform = {"cvgen-linux-x64.zip": "linux", "cvgen-macos.zip": "macos", "cvgen-windows-x64.zip": "windows"}[filename]
        if selected and platform != selected:
            continue
        data = source.read_bytes()
        if name.endswith(".exe") and not data.startswith(b"MZ"):
            raise SystemExit(f"{source} 不是 Windows 可执行文件")
        if name == "cvgen" and filename.startswith("cvgen-linux") and not data.startswith(b"\x7fELF"):
            raise SystemExit(f"{source} 不是 Linux 可执行文件")
        if filename.startswith("cvgen-macos") and data[:4] not in {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"}:
            raise SystemExit(f"{source} 不是 macOS 可执行文件")
        dest = out / filename
        index = (ROOT / "skills" / "cvgen-index.md").read_bytes()
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            _add(archive, name, data, executable=True)
            _add(archive, "使用说明.txt", NOTE.encode("utf-8"))
            _add(archive, "skills/cvgen-index.md", index)
        written.append(dest)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "tools" / "dist")
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--macos", type=Path, required=True)
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument("--only", choices=["linux", "macos", "windows"], default="")
    args = parser.parse_args()
    os.environ["CVGEN_PACK_ONLY"] = args.only
    binaries = {"linux": args.linux, "macos": args.macos, "windows": args.windows}
    for path in package(args.out, binaries):
        print(path.name, path.stat().st_size)


if __name__ == "__main__":
    main()
