"""Build a multi-resolution .ico from one image, using only stdlib + System.Drawing.

A Windows shortcut only looks right at every zoom level if the .ico carries a
separate bitmap per size, so this renders frames with tools/icon-frames.ps1 and
packs them itself:

    16-64 px  DIB entries (BMP header + bottom-up BGRA + AND mask), the format
              every Windows version understands
    128/256   PNG entries, which keep the file small and are what Vista+ expects
              at the large sizes

Usage: python tools/make_icon.py assets/icon-source.jpg assets/codemode.ico
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile

DIB_SIZES = (16, 24, 32, 48, 64)
PNG_SIZES = (128, 256)
ALL_SIZES = DIB_SIZES + PNG_SIZES
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def render_frames(source: str, workdir: str) -> None:
    script = os.path.join(ROOT, "tools", "icon-frames.ps1")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
         "-Source", source, "-OutDir", workdir,
         "-Sizes", ",".join(str(s) for s in ALL_SIZES)],
        capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise SystemExit("icon frames failed: %s"
                         % (proc.stderr.strip() or proc.stdout.strip()))
    missing = [s for s in ALL_SIZES
               if not os.path.exists(os.path.join(workdir, "%d.bin" % s))]
    if missing:
        raise SystemExit("icon frames missing for: %s" % missing)


def dib_entry(size: int, bgra: bytes) -> bytes:
    """One ICO image as a 32bpp BMP: header, colour rows, then a zero AND mask."""
    header = struct.pack("<IiiHHIIiiII",
                         40, size, size * 2, 1, 32, 0,
                         len(bgra) + ((size + 31) // 32) * 4 * size,
                         0, 0, 0, 0)
    # ICO DIBs are bottom-up; the frames arrive top-down.
    stride = size * 4
    rows = b"".join(bgra[y * stride:(y + 1) * stride] for y in range(size - 1, -1, -1))
    mask_stride = ((size + 31) // 32) * 4  # 1bpp, rows padded to 4 bytes
    return header + rows + b"\x00" * (mask_stride * size)


def build_icon(source: str, target: str) -> list:
    with tempfile.TemporaryDirectory() as workdir:
        render_frames(source, workdir)
        images = []
        for size in DIB_SIZES:
            with open(os.path.join(workdir, "%d.bin" % size), "rb") as fh:
                images.append((size, dib_entry(size, fh.read())))
        for size in PNG_SIZES:
            with open(os.path.join(workdir, "%d.png" % size), "rb") as fh:
                images.append((size, fh.read()))

    offset = 6 + 16 * len(images)
    directory = b""
    payload = b""
    for size, data in images:
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                                 1, 32, len(data), offset)
        payload += data
        offset += len(data)

    os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, len(images)) + directory + payload)
    return [size for size, _ in images]


def main(argv: list) -> int:
    if len(argv) != 3:
        print("usage: make_icon.py <source-image> <out.ico>", file=sys.stderr)
        return 2
    source, target = argv[1], argv[2]
    sizes = build_icon(source, target)
    print("wrote %s (%d bytes, sizes %s)"
          % (target, os.path.getsize(target), ", ".join(str(s) for s in sizes)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
