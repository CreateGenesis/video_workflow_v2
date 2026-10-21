"""Write the two still references the Zero shot requires. No external image API."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def png(width: int, height: int, pixel) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel(x, y, width, height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def space(x: int, y: int, width: int, height: int) -> bytes:
    sky = int(40 + 80 * y / height)
    if y > height * 0.62:
        return bytes((210, 220, 230))
    if abs(x - width * 0.2) < 6 and y > height * 0.3:
        return bytes((230, 230, 235))
    return bytes((sky, sky + 20, 150))


def gauze(x: int, y: int, width: int, height: int) -> bytes:
    cx, cy = width / 2, height / 2
    dx, dy = (x - cx) / 40, (y - cy) / 18
    if dx * dx + dy * dy < 1:
        band = 230 if int(x / 3) % 2 == 0 else 245
        return bytes((band, band, band - 5))
    return bytes((186, 198, 210))


def write(root: Path) -> None:
    target = root / "references"
    target.mkdir(parents=True, exist_ok=True)
    (target / "zero-space.png").write_bytes(png(640, 360, space))
    (target / "zero-gauze.png").write_bytes(png(640, 360, gauze))


if __name__ == "__main__":
    write(Path(__file__).resolve().parents[1] / "assets")
