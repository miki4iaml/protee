# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for the release script ``scripts/absolute_links.py``."""

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "absolute_links.py"
SPEC = importlib.util.spec_from_file_location("absolute_links", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
links = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(links)

REPO = "owner/name"
RAW = "https://raw.githubusercontent.com/owner/name/v1.0.0/"
BLOB = "https://github.com/owner/name/blob/v1.0.0/"

SOURCE = """\
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/dark.svg">
  <img alt="logo" src="docs/light.svg" width="480">
</picture>

[Français](README.fr.md) and [the guide](docs/guide.md#a-section "Guide").
![Figure](docs/images/figure.png)
[![License](https://img.shields.io/badge.svg)](LICENSE)
[![Local badge](docs/badge.svg)](https://example.org)
<a href="CONTRIBUTING.md">contribute</a>, [up](#top), [mail](mailto:a@b.c).
Code spans stay: `[x](not/a/link)` and `f[0](y)`.
A link whose text is code: [`plot`](docs/display.md).

```python
table[0](docs/not_a_link.py)
```

[ref]: docs/reference.md
[web]: https://example.org/page
"""

EXPECTED = f"""\
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="{RAW}docs/dark.svg">
  <img alt="logo" src="{RAW}docs/light.svg" width="480">
</picture>

[Français]({BLOB}README.fr.md) and [the guide]({BLOB}docs/guide.md#a-section "Guide").
![Figure]({RAW}docs/images/figure.png)
[![License](https://img.shields.io/badge.svg)]({BLOB}LICENSE)
[![Local badge]({RAW}docs/badge.svg)](https://example.org)
<a href="{BLOB}CONTRIBUTING.md">contribute</a>, [up](#top), [mail](mailto:a@b.c).
Code spans stay: `[x](not/a/link)` and `f[0](y)`.
A link whose text is code: [`plot`]({BLOB}docs/display.md).

```python
table[0](docs/not_a_link.py)
```

[ref]: {BLOB}docs/reference.md
[web]: https://example.org/page
"""


def test_relative_targets_become_absolute_at_the_ref() -> None:
    assert links.make_absolute(SOURCE, REPO, "v1.0.0") == EXPECTED
    assert links.relative_targets(EXPECTED) == []
    assert links.relative_targets(SOURCE) == [
        "docs/dark.svg",
        "docs/light.svg",
        "README.fr.md",
        "docs/guide.md#a-section",
        "docs/images/figure.png",
        "LICENSE",
        "docs/badge.svg",
        "CONTRIBUTING.md",
        "docs/display.md",
        "docs/reference.md",
    ]


def test_paths_are_taken_from_the_root_of_the_repository() -> None:
    assert links.absolute("./docs/../LICENSE", False, REPO, "abc123") == (
        "https://github.com/owner/name/blob/abc123/LICENSE"
    )
    assert links.absolute("/docs/a.png", True, REPO, "v1") == (
        "https://raw.githubusercontent.com/owner/name/v1/docs/a.png"
    )
    raw = "https://raw.githubusercontent.com/owner/name/v1/"
    assert links.make_absolute('<img srcset="a.png 1x, b.png 2x">', REPO, "v1") == (
        f'<img srcset="{raw}a.png 1x, {raw}b.png 2x">'
    )
    with pytest.raises(ValueError, match="leaves the repository"):
        links.absolute("../elsewhere.md", False, REPO, "v1")


def test_rewrite_then_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(SOURCE, encoding="utf-8")
    assert links.main(["check", str(readme)]) == 1
    out = capsys.readouterr().out
    assert "relative link 'docs/light.svg'" in out
    assert "10 relative link(s) left" in out
    args = ["rewrite", "--repo", REPO, "--ref", "v1.0.0", str(readme)]
    assert links.main(args) == 0
    assert readme.read_text(encoding="utf-8") == EXPECTED
    assert links.main(["check", str(readme)]) == 0


def test_check_reads_the_description_of_distributions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metadata = "Metadata-Version: 2.4\nName: name\n\n[guide](docs/guide.md)\n"
    wheel = tmp_path / "name-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("name/__init__.py", "")
        archive.writestr("name-1.0.dist-info/METADATA", metadata)
    sdist = tmp_path / "name-1.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        data = metadata.encode("utf-8")
        member = tarfile.TarInfo("name-1.0/PKG-INFO")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    assert links.main(["check", str(wheel), str(sdist)]) == 1
    assert capsys.readouterr().out.count("'docs/guide.md'") == 2
    empty = tmp_path / "empty-1.0-py3-none-any.whl"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("empty/__init__.py", "")
    with pytest.raises(ValueError, match="no metadata"):
        links.description(empty)


@pytest.mark.parametrize("name", ["README.md", "README.fr.md"])
def test_relative_links_of_the_readmes_lead_to_files(name: str) -> None:
    # Rewritten at the release's tag, they must find their files there.
    text = (ROOT / name).read_text(encoding="utf-8")
    targets = links.relative_targets(text)
    assert targets, name
    for target in targets:
        assert (ROOT / target.partition("#")[0]).exists(), target
    assert links.relative_targets(links.make_absolute(text, REPO, "v1")) == []
