"""Package standalone cvgen binaries. The compile step is tools/build_nuitka.sh."""

from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTE = """cvgen 操作工具

这是独立可执行文件，不需要安装 Python，也不需要虚拟环境。

Linux 包适用于 x86_64，系统 glibc 不低于 2.31。
可直接运行的范围包括 Ubuntu 20.04 及更新、Debian 11 及更新、CentOS 8 / Rocky 8 / Alma 8 及更新、OpenCloudOS 9。
它不能在只提供 musl 的 Alpine 上直接运行。
macOS 与 Windows 包同样是对应系统的可执行文件；页面显示尚未构建时，表示还没有在该系统上编译。

用法：
Linux / macOS：./cvgen login --base 服务地址
Windows：cvgen.exe login --base 服务地址

网页管理员批准设备码后，这台 cvgen 才会在线。同时只能有一台在线。
"""

PACKAGES = {
    "linux": ("cvgen-linux-x64.zip", "cvgen"),
    "macos": ("cvgen-macos.zip", "cvgen"),
    "windows": ("cvgen-windows-x64.zip", "cvgen.exe"),
}


def package(out: Path, binaries: dict[str, Path]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for platform, binary in binaries.items():
        filename, inner = PACKAGES[platform]
        dest = out / filename
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            info = zipfile.ZipInfo(inner)
            info.external_attr = (stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH) << 16
            archive.writestr(info, Path(binary).read_bytes())
            archive.writestr("使用说明.txt", NOTE)
        written.append(dest)
    return written


def package_built(out: Path, binary_root: Path) -> list[Path]:
    found = {}
    for platform, (_filename, inner) in PACKAGES.items():
        path = binary_root / platform / inner
        if path.is_file():
            found[platform] = path
    return package(out, found)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "tools" / "dist")
    parser.add_argument("--binaries", type=Path, default=ROOT / "tools" / "bin")
    args = parser.parse_args()
    paths = package_built(args.out, args.binaries)
    if not paths:
        raise SystemExit("没有可打包的二进制。先运行 tools/build_nuitka.sh")
    for path in paths:
        print(path.name, path.stat().st_size)


if __name__ == "__main__":
    main()
