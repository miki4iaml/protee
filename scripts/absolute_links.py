# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Make the relative links of Markdown files absolute, for display off GitHub.

PyPI shows the README as the description of the package, outside the
repository: a relative link or image (``docs/display.md``) leads nowhere
there, nor on the page of a GitHub release. PyPA has no standard for
this, and the build backend (uv_build) copies the README as it is. The
release workflow therefore rewrites the README before building, pointing
every relative target at the files of the release's tag, then checks the
built distributions; the release notes go through the same rewriting.

Usage::

    python scripts/absolute_links.py rewrite --repo OWNER/NAME --ref v1.2.3 README.md
    python scripts/absolute_links.py check dist/*

``rewrite`` changes the files in place (in the release runner, never
committed): images point to ``raw.githubusercontent.com``, links to the
file on ``github.com``, both at ``--ref``. Targets are taken from the root
of the repository, as for its README and CHANGELOG. Code blocks and code
spans are left as they are. ``check`` lists the relative links left in
Markdown files and in the description of wheels and sdists, and fails if
there are any.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
import tarfile
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

#: A target with a scheme (https:, mailto:), an anchor of the page itself,
#: or a host (//host/path): already absolute.
_ABSOLUTE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|#|//)")

#: An inline link or image, ``[text](target "title")``; the text may hold
#: one level of brackets, an image inside a link (``[![badge](url)](target)``).
_INLINE = re.compile(
    r"(?P<bang>!?)\[(?P<text>(?:[^\[\]\n]|\[[^\[\]\n]*\])*)\]"
    r"\((?P<target>[^()\s]+)(?P<title>\s+\"[^\"\n]*\")?\)"
)

#: A link reference definition, ``[label]: target``.
_DEFINITION = re.compile(r"^(?P<head> {0,3}\[[^\]\n]+\]:[ \t]*)(?P<target>\S+)")

#: An HTML attribute holding a target: ``src`` and ``srcset`` of images,
#: ``href`` of links.
_ATTRIBUTE = re.compile(r"\b(?P<name>src|srcset|href)=\"(?P<value>[^\"]*)\"")

#: A code fence, opening or closing a code block.
_FENCE = re.compile(r"^ {0,3}(```|~~~)")

#: A code span, left as it is.
#: A code span or an inline link, whichever starts first: a code span in the
#: text of a link ([`protee`](docs/index.md)) stays in the link.
_PIECE = re.compile(rf"(?P<code>(?P<ticks>`+)[^`]*?(?P=ticks))|{_INLINE.pattern}")

Rewrite = Callable[[str, bool], str]


def absolute(target: str, image: bool, repo: str, ref: str) -> str:
    """The target, absolute: at ``ref`` of the repository ``repo``.

    An image is served raw, a link shows the file on GitHub; an absolute
    target is returned as it is.

    Raises
    ------
    ValueError
        If a relative target leaves the repository.
    """
    if _ABSOLUTE.match(target):
        return target
    path, mark, fragment = target.partition("#")
    resolved = posixpath.normpath(path.lstrip("/"))
    if resolved == ".." or resolved.startswith("../"):
        msg = f"{target!r} leaves the repository"
        raise ValueError(msg)
    if image:
        url = f"https://raw.githubusercontent.com/{repo}/{ref}/{resolved}"
    else:
        url = f"https://github.com/{repo}/blob/{ref}/{resolved}"
    return url + mark + fragment


def _srcset(value: str, rewrite: Rewrite) -> str:
    """A ``srcset``: each candidate's address rewritten, its descriptor kept."""
    candidates = []
    for candidate in value.split(","):
        address, space, descriptor = candidate.strip().partition(" ")
        candidates.append(rewrite(address, True) + space + descriptor)
    return ", ".join(candidates)


def _rewrite_text(text: str, rewrite: Rewrite) -> str:
    """Prose with every link, image and HTML target rewritten."""

    def inline(match: re.Match[str]) -> str:
        image = bool(match["bang"])
        inner = _rewrite_text(match["text"], rewrite)
        title = match["title"] or ""
        return f"{match['bang']}[{inner}]({rewrite(match['target'], image)}{title})"

    def attribute(match: re.Match[str]) -> str:
        name, value = match["name"], match["value"]
        if name == "srcset":
            value = _srcset(value, rewrite)
        else:
            value = rewrite(value, name == "src")
        return f'{name}="{value}"'

    text = _INLINE.sub(inline, text)
    return _ATTRIBUTE.sub(attribute, text)


def _prose(line: str) -> Iterator[tuple[str, bool]]:
    """The pieces of a line, each marked as prose or not (a code span)."""
    end = 0
    for piece in _PIECE.finditer(line):
        if piece["code"] is None:
            continue  # a link, prose with the rest of the line
        yield line[end : piece.start()], True
        yield piece.group(), False
        end = piece.end()
    yield line[end:], True


def transform(markdown: str, rewrite: Rewrite) -> str:
    """Markdown with the targets of its prose rewritten, code left as it is."""
    lines = []
    fenced = False
    for line in markdown.splitlines(keepends=True):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            definition = _DEFINITION.match(line)
            if definition:
                target = rewrite(definition["target"], False)
                line = definition["head"] + target + line[definition.end() :]
            else:
                line = "".join(
                    _rewrite_text(piece, rewrite) if prose else piece
                    for piece, prose in _prose(line)
                )
        lines.append(line)
    return "".join(lines)


def make_absolute(markdown: str, repo: str, ref: str) -> str:
    """Markdown with every relative target made absolute at ``ref``."""
    return transform(markdown, lambda target, image: absolute(target, image, repo, ref))


def relative_targets(markdown: str) -> list[str]:
    """The relative targets of the prose of some Markdown, in order."""
    found: list[str] = []

    def collect(target: str, image: bool) -> str:  # noqa: ARG001
        if not _ABSOLUTE.match(target):
            found.append(target)
        return target

    transform(markdown, collect)
    return found


def description(path: Path) -> str:
    """The text to check: a Markdown file, or the metadata of a distribution.

    Raises
    ------
    ValueError
        If a wheel or an sdist holds no metadata.
    """
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as wheel:
            for name in wheel.namelist():
                if name.endswith(".dist-info/METADATA"):
                    return wheel.read(name).decode("utf-8")
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as sdist:
            for member in sdist.getmembers():
                if member.name.count("/") == 1 and member.name.endswith("/PKG-INFO"):
                    extracted = sdist.extractfile(member)
                    if extracted is not None:
                        return extracted.read().decode("utf-8")
    else:
        return path.read_text(encoding="utf-8")
    msg = f"{path}: no metadata found"
    raise ValueError(msg)


def main(argv: list[str] | None = None) -> int:
    """Run the command line; return the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    rewrite = commands.add_parser("rewrite", help="make relative links absolute")
    rewrite.add_argument("--repo", required=True, help="OWNER/NAME on GitHub")
    rewrite.add_argument("--ref", required=True, help="tag or commit to point at")
    rewrite.add_argument("files", nargs="+", type=Path)
    check = commands.add_parser("check", help="fail on relative links left")
    check.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)

    if args.command == "rewrite":
        for path in args.files:
            text = path.read_text(encoding="utf-8")
            path.write_text(
                make_absolute(text, args.repo, args.ref), encoding="utf-8", newline=""
            )
        return 0
    left = 0
    for path in args.files:
        for target in relative_targets(description(path)):
            print(f"{path}: relative link {target!r}")
            left += 1
    if left:
        print(f"{left} relative link(s) left: they lead nowhere off GitHub.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
