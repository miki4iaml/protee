# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for the image metadata hook ``scripts/check_image_metadata.py``."""

import importlib.util
import struct
import zlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_image_metadata.py"
SPEC = importlib.util.spec_from_file_location("check_image_metadata", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

#: A value that must never appear in a message.
SECRET = "Zorglub, 48.8566 N 2.3522 E"


@pytest.fixture(autouse=True)
def in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def run(capsys: pytest.CaptureFixture[str], name: str, data: bytes) -> tuple[int, str]:
    Path(name).write_bytes(data)
    status = check.main([name])
    return status, capsys.readouterr().out


def chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body)
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def png(*extra: bytes) -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x00")
    signature: bytes = check.PNG_SIGNATURE
    return (
        signature
        + chunk(b"IHDR", header)
        + b"".join(extra)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def jpeg(*segments: tuple[int, bytes]) -> bytes:
    def segment(marker: int, body: bytes) -> bytes:
        return bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body

    jfif = segment(0xE0, b"JFIF\0\x01\x01\0\0\x01\0\x01\0\0")
    tables = segment(0xDB, b"\0" + bytes(64))
    frame = segment(0xC0, b"\x08\0\x01\0\x01\x01\x01\x11\0")
    scan = segment(0xDA, b"\x01\x01\0\0\x3f\0") + b"\x12\x34\xff\x00\x56"
    extra = b"".join(segment(marker, body) for marker, body in segments)
    return b"\xff\xd8" + jfif + extra + tables + frame + scan + b"\xff\xd9"


def gif(*extensions: bytes, palette: bool = True, local: bool = False) -> bytes:
    flags, colours = (b"\x80", bytes(6)) if palette else (b"\0", b"")
    screen = b"GIF89a" + struct.pack("<HH", 1, 1) + flags + b"\0\0" + colours
    image = b"\x2c" + struct.pack("<HHHH", 0, 0, 1, 1)
    image += b"\x80" + bytes(6) if local else b"\0"
    image += b"\x02\x02\x44\x01\0"
    return screen + b"".join(extensions) + image + b"\x3b"


def webp(*chunks: tuple[bytes, bytes]) -> bytes:
    body = b"".join(
        kind + struct.pack("<I", len(data)) + data + b"\0" * (len(data) & 1)
        for kind, data in chunks
    )
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def test_the_repository_images_carry_no_metadata() -> None:
    # Hidden and private folders (.git, .venv, _priv…) are not published.
    images: list[Path] = []
    for folder, folders, files in Path(__file__).parents[1].walk():
        folders[:] = [name for name in folders if not name.startswith((".", "_"))]
        images += [
            folder / name
            for name in files
            if Path(name).suffix.lower() in check.READERS
        ]
    for image in sorted(images):
        assert check.check_file(str(image)) == [], image.name


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("clean.png", png(chunk(b"pHYs", bytes(9)))),
        ("clean.jpg", jpeg()),
        ("clean.gif", gif(b"\x21\xf9\x04\0\0\0\0\0")),
        ("plain.gif", gif(palette=False, local=True)),
        ("loop.gif", gif(b"\x21\xff\x0bNETSCAPE2.0\x03\x01\0\0\0")),
        ("twice.jpg", b"\xff\xd8\xff\xd8\xff\xd9"),
        ("clean.webp", webp((b"VP8L", b"\x2f\0\0\0\0"))),
        (
            "clean.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><title>Plot</title></svg>',
        ),
        # Not an image: left to the other hooks.
        ("notes.txt", b"text"),
    ],
)
def test_images_without_metadata_pass(
    capsys: pytest.CaptureFixture[str], name: str, data: bytes
) -> None:
    assert run(capsys, name, data) == (0, "")


@pytest.mark.parametrize(
    ("name", "data", "block"),
    [
        ("text.png", png(chunk(b"tEXt", b"Author\0" + SECRET.encode())), "chunk tEXt"),
        ("exif.png", png(chunk(b"eXIf", SECRET.encode())), "chunk eXIf"),
        ("time.png", png(chunk(b"tIME", bytes(7))), "chunk tIME"),
        ("unknown.png", png(chunk(b"prVt", SECRET.encode())), "chunk prVt"),
        ("exif.jpg", jpeg((0xE1, b"Exif\0\0" + SECRET.encode())), "segment APP1"),
        ("iptc.jpg", jpeg((0xED, SECRET.encode())), "segment APP13"),
        ("comment.jpg", jpeg((0xFE, SECRET.encode())), "comment"),
        ("comment.gif", gif(b"\x21\xfe\x05" + b"Zorgl" + b"\0"), "comment extension"),
        ("text.gif", gif(b"\x21\x01\x05" + b"Zorgl" + b"\0"), "plain text extension"),
        ("other.gif", gif(b"\x21\x99\x01x\0"), "extension 0x99"),
        (
            "xmp.gif",
            gif(b"\x21\xff\x0b" + b"XMP DataXMP" + b"\x03abc\0"),
            "application extension",
        ),
        ("exif.webp", webp((b"VP8L", b"\0"), (b"EXIF", SECRET.encode())), "chunk EXIF"),
        ("xmp.webp", webp((b"VP8L", b"\0"), (b"XMP ", SECRET.encode())), "chunk XMP"),
        (
            "meta.svg",
            b"<svg><metadata>" + SECRET.encode() + b"</metadata></svg>",
            "metadata element",
        ),
        (
            "dc.svg",
            b'<svg xmlns:dc="http://purl.org/dc/elements/1.1/"/>',
            "Dublin Core metadata",
        ),
        ("editor.svg", b'<svg sodipodi:docname="plot.svg"/>', "editor attribute"),
        (
            "link.svg",
            b'<svg><image href="file:///plot.png"/></svg>',
            "link to a local file",
        ),
    ],
)
def test_metadata_is_refused_without_showing_it(
    capsys: pytest.CaptureFixture[str], name: str, data: bytes, block: str
) -> None:
    status, out = run(capsys, name, data)
    assert status == 1
    assert f"{name}: metadata ({block}): remove it" in out
    assert "Zorg" not in out
    assert "48.8566" not in out


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("photo.tiff", b"II*\0", "format not checked: use PNG or SVG"),
        ("broken.png", png()[:-5], "truncated"),
        ("open.png", png()[:-12], "truncated file"),
        ("fake.png", b"GIF89a", "not a PNG file"),
        ("broken.jpg", jpeg()[:-2], "no end of image"),
        ("marker.jpg", b"\xff\xd8\xff", "truncated marker"),
        ("segment.jpg", b"\xff\xd8\xff\xe0\x00", "truncated segment"),
        ("ended.jpg", b"\xff\xd8\xff\xe0\x00\x04ab", "no end of image"),
        ("fake.jpg", b"\x89PNG", "not a JPEG file"),
        ("broken.gif", gif()[:-1], "no trailer"),
        ("cut.gif", gif()[:-2], "truncated block"),
        ("image.gif", gif()[:19] + b"\x2c\0", "truncated image"),
        ("block.gif", gif()[:19] + b"\x55", "unknown block"),
        ("fake.gif", b"\xff\xd8", "not a GIF file"),
        ("broken.webp", webp((b"VP8L", b"\0\0\0\0"))[:-2], "truncated"),
        ("chunk.webp", webp((b"VP8L", b"\0\0")) + b"EX", "truncated chunk"),
        ("fake.webp", b"RIFF", "not a WebP file"),
        ("latin.svg", b"<svg>\xe9</svg>", "not UTF-8"),
    ],
)
def test_what_cannot_be_read_is_refused(
    capsys: pytest.CaptureFixture[str], name: str, data: bytes, message: str
) -> None:
    status, out = run(capsys, name, data)
    assert status == 1
    assert message in out
    assert out.rstrip().endswith("not checked") or "format not checked" in out


def test_an_unreadable_file_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main(["missing.png"]) == 1
    assert "missing.png: unreadable, not checked" in capsys.readouterr().out
