# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Pre-commit hook: refuse metadata in images.

The project draws its images itself, so none needs metadata, and metadata
can carry what an image should never publish: a name, a path, the
software and the date of a machine, the place a photograph was taken
(EXIF GPS). An image passes only if every block it holds is on the
allow-list of its format; anything else is refused, unknown blocks
included. A format the hook cannot read is refused too: the hook never
succeeds without checking.

- PNG: image chunks only (IHDR, PLTE, IDAT, IEND, tRNS, gAMA, cHRM,
  sRGB, pHYs, bKGD, sBIT); text (tEXt, zTXt, iTXt), eXIf, tIME, iCCP...
  are refused.
- JPEG: image segments and the JFIF header (APP0); EXIF and XMP (APP1),
  IPTC (APP13), other APPn and comments are refused.
- GIF: images, graphic control and the loop extension; comments, plain
  text and other application extensions (XMP) are refused.
- WebP: VP8, VP8L, VP8X, ALPH, ANIM, ANMF; EXIF, XMP and ICCP are
  refused.
- SVG: the drawing; ``<metadata>``, RDF and Dublin Core, editor
  attributes (Inkscape, Sodipodi) and links to local files are refused.

The message names the file and the block, never its contents. PDF files
are not images: they keep their metadata (the official authors of a
reference) and the anonymity hook checks them.
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_ALLOWED = frozenset(
    {
        "IHDR",
        "PLTE",
        "IDAT",
        "IEND",
        "tRNS",
        "gAMA",
        "cHRM",
        "sRGB",
        "pHYs",
        "bKGD",
        "sBIT",
    }
)
#: JPEG markers without metadata: start and end of image, frames,
#: tables, restart interval, scan, restart markers, and APP0 (JFIF).
JPEG_ALLOWED = frozenset(
    {
        0xD8,
        0xD9,
        0xC4,
        0xCC,
        0xDB,
        0xDD,
        0xDA,
        0xE0,
        *range(0xC0, 0xD0),
        *range(0xD0, 0xD8),
    }
)
GIF_APPLICATIONS = frozenset({b"NETSCAPE2.0", b"ANIMEXTS1.0"})
WEBP_ALLOWED = frozenset({b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ANIM", b"ANMF"})
SVG_REFUSED = (
    (re.compile(r"<(?:\w+:)?metadata\b", re.IGNORECASE), "metadata element"),
    (re.compile(r"\brdf:RDF\b|\bxmlns:rdf\s*="), "RDF metadata"),
    (re.compile(r"\bxmlns:dc\s*=|<dc:\w+"), "Dublin Core metadata"),
    (re.compile(r"\b(?:sodipodi|inkscape):[\w-]+\s*="), "editor attribute"),
    (re.compile(r"""href\s*=\s*["']\s*file:""", re.IGNORECASE), "link to a local file"),
)
#: Formats the hook cannot read: refused rather than passed unchecked.
UNREAD = frozenset({".tif", ".tiff", ".bmp", ".ico", ".heic", ".heif", ".avif", ".jp2"})


class Unreadable(Exception):
    """The file does not follow its format: it cannot be checked."""


def png_blocks(data: bytes) -> list[str]:
    """Chunk types of a PNG file, in order."""
    if not data.startswith(PNG_SIGNATURE):
        raise Unreadable("not a PNG file")
    found, position = [], len(PNG_SIGNATURE)
    while position < len(data):
        if position + 8 > len(data):
            raise Unreadable("truncated chunk")
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8].decode("latin-1")
        found.append(kind)
        position += 12 + length
        if kind == "IEND":
            break
    if position > len(data) or not found or found[-1] != "IEND":
        raise Unreadable("truncated file")
    return found


def png_findings(data: bytes) -> list[str]:
    return sorted({f"chunk {k}" for k in png_blocks(data) if k not in PNG_ALLOWED})


def jpeg_findings(data: bytes) -> list[str]:
    """Metadata segments of a JPEG file."""
    if not data.startswith(b"\xff\xd8"):
        raise Unreadable("not a JPEG file")
    found: set[str] = set()
    position = 2
    while position < len(data):
        if data[position] != 0xFF:
            # Entropy-coded data of a scan: skip to the next marker.
            position = data.find(b"\xff", position)
            if position < 0:
                raise Unreadable("no end of image")
            continue
        marker = data[position + 1] if position + 1 < len(data) else None
        if marker is None:
            raise Unreadable("truncated marker")
        if marker in (0x00, 0xFF) or 0xD0 <= marker <= 0xD7:
            position += 1 if marker == 0xFF else 2
            continue
        if marker not in JPEG_ALLOWED:
            name = (
                f"APP{marker - 0xE0}" if 0xE0 <= marker <= 0xEF else f"0x{marker:02X}"
            )
            found.add("comment" if marker == 0xFE else f"segment {name}")
        if marker == 0xD9:
            return sorted(found)
        if marker == 0xD8:
            position += 2
            continue
        if position + 4 > len(data):
            raise Unreadable("truncated segment")
        (length,) = struct.unpack(">H", data[position + 2 : position + 4])
        position += 2 + length
    raise Unreadable("no end of image")


def gif_findings(data: bytes) -> list[str]:
    """Comment, plain text and application extensions of a GIF file."""
    if not data.startswith((b"GIF87a", b"GIF89a")) or len(data) < 13:
        raise Unreadable("not a GIF file")
    found: set[str] = set()
    position = 13
    if data[10] & 0x80:
        position += 3 * 2 ** ((data[10] & 0x07) + 1)

    def sub_blocks(start: int) -> int:
        while True:
            if start >= len(data):
                raise Unreadable("truncated block")
            size = data[start]
            start += 1 + size
            if size == 0:
                return start

    while position < len(data):
        introducer = data[position]
        if introducer == 0x3B:
            return sorted(found)
        if introducer == 0x2C:
            if position + 10 > len(data):
                raise Unreadable("truncated image")
            flags = data[position + 9]
            position += 10
            if flags & 0x80:
                position += 3 * 2 ** ((flags & 0x07) + 1)
            position = sub_blocks(position + 1)
        elif introducer == 0x21 and position + 1 < len(data):
            label = data[position + 1]
            if label == 0xFE:
                found.add("comment extension")
            elif label == 0x01:
                found.add("plain text extension")
            elif label == 0xFF:
                name = data[position + 3 : position + 14]
                if name not in GIF_APPLICATIONS:
                    found.add("application extension")
            elif label != 0xF9:
                found.add(f"extension 0x{label:02X}")
            position = sub_blocks(position + 2)
        else:
            raise Unreadable("unknown block")
    raise Unreadable("no trailer")


def webp_findings(data: bytes) -> list[str]:
    """Metadata chunks of a WebP file."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise Unreadable("not a WebP file")
    found: set[str] = set()
    position = 12
    while position < len(data):
        if position + 8 > len(data):
            raise Unreadable("truncated chunk")
        kind = data[position : position + 4]
        (size,) = struct.unpack("<I", data[position + 4 : position + 8])
        if kind not in WEBP_ALLOWED:
            found.add(f"chunk {kind.decode('latin-1').strip()}")
        position += 8 + size + (size & 1)
    if position != len(data):
        raise Unreadable("truncated file")
    return sorted(found)


def svg_findings(data: bytes) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Unreadable("not UTF-8") from None
    return [label for pattern, label in SVG_REFUSED if pattern.search(text)]


READERS = {
    ".png": png_findings,
    ".jpg": jpeg_findings,
    ".jpeg": jpeg_findings,
    ".gif": gif_findings,
    ".webp": webp_findings,
    ".svg": svg_findings,
}


def check_file(name: str) -> list[str]:
    """Findings for one image (empty if it carries no metadata)."""
    suffix = Path(name).suffix.lower()
    reader = READERS.get(suffix)
    if reader is None:
        if suffix in UNREAD:
            return [f"{name}: format not checked: use PNG or SVG"]
        return []
    try:
        data = Path(name).read_bytes()
        found = reader(data)
    except OSError:
        return [f"{name}: unreadable, not checked"]
    except Unreadable as exc:
        return [f"{name}: {exc}, not checked"]
    return [f"{name}: metadata ({item}): remove it" for item in found]


def main(argv: list[str]) -> int:
    findings = [finding for name in argv for finding in check_file(name)]
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
