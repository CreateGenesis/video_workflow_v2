"""Zip native cvgen binaries with the operator index and write tools/dist/VERSION.

CI builds each platform and calls this with --only; the server serves whatever is in the releases
directory (CVGEN_RELEASES, default tools/dist).
"""

from __future__ import annotations

import argparse
import re
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = {"linux": ("cvgen-linux-x64.zip", "cvgen"), "macos": ("cvgen-macos.zip", "cvgen"),
            "windows": ("cvgen-windows-x64.zip", "cvgen.exe")}
MAGIC = {"linux": (b"\x7fELF",), "windows": (b"MZ",),
         "macos": (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")}
NOTE = """cvgen {version} 操作工具

1. 解压后运行可执行文件，先登录：
   Linux / macOS：./cvgen login --base 服务地址
   Windows：cvgen.exe login --base 服务地址
   终端会显示一个设备码和链接。登录网页后打开链接批准，这台设备就归属批准它的人。
2. 选择工作区和作品：cvgen workspace list → cvgen workspace use <id> → cvgen work new <名称>
3. 读 skills/cvgen-index.md；正文用 cvgen skill show <名称> 读取。

cvgen --help 列出全部命令；任何命令后加 --help 只显示用法，不会执行。
"""


def cli_version() -> str:
    text = (ROOT / "cvgen-cli" / "Cargo.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def _add(archive: zipfile.ZipFile, name: str, payload: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name)
    info.flag_bits |= 0x800
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED)


def package(out: Path, binaries: dict[str, Path], version: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    index = (ROOT / "skills" / "cvgen-index.md").read_bytes()
    written = []
    for platform, source in binaries.items():
        filename, name = ARCHIVES[platform]
        data = source.read_bytes()
        if not data.startswith(MAGIC[platform]):
            raise SystemExit(f"{source} 不是 {platform} 可执行文件")
        dest = out / filename
        with zipfile.ZipFile(dest, "w") as archive:
            _add(archive, name, data, executable=True)
            _add(archive, "使用说明.txt", NOTE.format(version=version).encode("utf-8"))
            _add(archive, "skills/cvgen-index.md", index)
        written.append(dest)
    (out / "VERSION").write_text(version + "\n", encoding="utf-8")
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "tools" / "dist")
    parser.add_argument("--version", default="")
    for platform in ARCHIVES:
        parser.add_argument(f"--{platform}", type=Path)
    args = parser.parse_args()
    binaries = {platform: getattr(args, platform) for platform in ARCHIVES if getattr(args, platform)}
    if not binaries:
        raise SystemExit("至少给一个平台的可执行文件：--linux / --macos / --windows")
    for path in package(args.out, binaries, args.version or cli_version()):
        print(path.name, path.stat().st_size)


if __name__ == "__main__":
    main()
