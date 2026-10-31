# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for the anonymity hook ``scripts/check_anonymity.py``."""

import importlib.util
import os
import sys
import zlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_anonymity.py"
SPEC = importlib.util.spec_from_file_location("check_anonymity", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
check_anonymity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_anonymity)

# Fictitious personal pattern. Generic paths are assembled at run time
# so that this file does not trigger the hook itself.
SECRET = "zorglub"
UNIX_HOME = "/" + "home/someone/project"


@pytest.fixture(autouse=True)
def in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # pre-commit passes paths relative to the repository; an absolute
    # path to the temporary directory would contain the home directory.
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def config_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # Outside the working directory, which stands for the repository:
    # a patterns file inside the repository is refused.
    return tmp_path_factory.mktemp("config")


@pytest.fixture
def patterns_file(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = config_dir / "patterns.txt"
    path.write_text(f"# comment\n{SECRET}\n", encoding="utf-8")
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(path))
    return path


def run(capsys: pytest.CaptureFixture[str], *args: str | Path) -> tuple[int, str, str]:
    names = [str(a.relative_to(Path.cwd())) if isinstance(a, Path) else a for a in args]
    status = check_anonymity.main(names)
    out, err = capsys.readouterr()
    return status, out, err


def test_clean_file_passes(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "ok.txt"
    f.write_text("nothing to report\n", encoding="utf-8")
    assert run(capsys, f) == (0, "", "")


def test_personal_pattern_reported_without_copying_it(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "doc.txt"
    f.write_text("line 1\nsigned: Zorglub\n", encoding="utf-8")
    status, out, _ = run(capsys, f)
    assert status == 1
    assert ":2: personal or internal information" in out
    assert SECRET not in out.lower()


def test_generic_pattern_reported(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "conf.txt"
    f.write_text(f"root = {UNIX_HOME}\n", encoding="utf-8")
    status, out, _ = run(capsys, f)
    assert status == 1
    assert "someone" not in out


def test_placeholder_path_passes(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "doc.txt"
    f.write_text("/home/<user>/project\n", encoding="utf-8")
    assert run(capsys, f)[0] == 0


def test_non_utf8_file_fails(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "latin1.txt"
    f.write_bytes("café\n".encode("latin-1"))
    status, out, _ = run(capsys, f)
    assert status == 1
    assert "not UTF-8, not checked" in out


def test_utf16_file_fails(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "utf16.txt"
    f.write_bytes("texte\n".encode("utf-16"))
    status, out, _ = run(capsys, f)
    assert status == 1
    assert "not UTF-8" in out


def test_unreadable_file_fails(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _ = run(capsys, tmp_path / "absent.txt")
    assert status == 1
    assert "unreadable, not checked" in out


def test_binary_with_pattern_fails(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\0\0\0Author\0ZORGLUB\0\xff\xfe")
    status, out, _ = run(capsys, f)
    assert status == 1
    assert "binary" in out
    assert SECRET not in out.lower()


def test_binary_without_pattern_passes(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\0\0\0\xff\xfe\x00")
    assert run(capsys, f)[0] == 0


def pdf(*objects: bytes) -> bytes:
    """A minimal PDF holding the given objects."""
    body = b"".join(
        b"%d 0 obj\n" % number + obj + b"\nendobj\n"
        for number, obj in enumerate(objects, start=1)
    )
    return b"%PDF-1.7\n" + body + b"%%EOF\n"


def flate_stream(header: bytes, content: bytes) -> bytes:
    packed = zlib.compress(content)
    return (
        b"<< "
        + header
        + b" /Filter /FlateDecode /Length %d >>\nstream\n" % len(packed)
        + packed
        + b"\nendstream"
    )


@pytest.mark.parametrize(
    "objects",
    [
        # XMP metadata, compressed: invisible in the raw bytes.
        (
            flate_stream(
                b"/Type /Metadata /Subtype /XML", b"<dc:creator>Zorglub</dc:creator>"
            ),
        ),
        # The document information, in a compressed object stream.
        (flate_stream(b"/Type /ObjStm /N 1 /First 4", b"2 0 << /Author (Zorglub) >>"),),
        # A UTF-16 string of the document information.
        (b"<< /Author (\xfe\xff\x00Z\x00o\x00r\x00g\x00l\x00u\x00b) >>",),
        (b"<< /Author <FEFF005A006F00720067006C00750062> >>",),
    ],
)
def test_pdf_metadata_is_checked(
    tmp_path: Path,
    patterns_file: Path,
    capsys: pytest.CaptureFixture[str],
    objects: tuple[bytes, ...],
) -> None:
    f = tmp_path / "reference.pdf"
    f.write_bytes(pdf(*objects))
    status, out, _ = run(capsys, f)
    assert status == 1
    assert "PDF" in out
    assert SECRET not in out.lower()


def test_pdf_keeps_its_official_authors(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Metadata that no pattern names pass: a reference keeps its authors.
    f = tmp_path / "reference.pdf"
    xmp = flate_stream(
        b"/Type /Metadata /Subtype /XML", b"<dc:creator>Bolton</dc:creator>"
    )
    page = flate_stream(b"/Length1 10", b"\x00\x01zorglub\x02")
    f.write_bytes(pdf(xmp, b"<< /Author (D. Bolton) /Title (Equivalent) >>", page))
    # The content of a page is not searched: only metadata is.
    assert run(capsys, f)[0] == 0


def test_pdf_metadata_that_cannot_be_decoded_fails(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "reference.pdf"
    broken = (
        b"<< /Type /Metadata /Filter /FlateDecode /Length 3 >>\nstream\nabc\nendstream"
    )
    other = (
        b"<< /Type /Metadata /Filter /LZWDecode /Length 3 >>\nstream\nabc\nendstream"
    )
    for obj in (broken, other):
        f.write_bytes(pdf(obj))
        status, out, _ = run(capsys, f)
        assert status == 1
        assert "PDF metadata not decoded" in out
    plain = b"<< /Type /Metadata /Length 9 >>\nstream\nno person\nendstream"
    f.write_bytes(pdf(plain))
    assert run(capsys, f)[0] == 0


def test_path_is_checked_and_masked(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / f"report-{SECRET}"
    folder.mkdir()
    f = folder / "notes.txt"
    f.write_text("nothing\n", encoding="utf-8")
    status, out, _ = run(capsys, f)
    assert status == 1
    assert "path" in out
    assert "***" in out
    assert SECRET not in out.lower()


def test_configured_but_missing_patterns_file_fails(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(config_dir / "missing.txt"))
    f = tmp_path / "ok.txt"
    f.write_text("nothing\n", encoding="utf-8")
    status, _, err = run(capsys, f)
    assert status == 2
    assert "missing file" in err


def test_default_patterns_file_missing_warns(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(check_anonymity.ENV_VAR, raising=False)
    monkeypatch.setattr(check_anonymity, "DEFAULT_PATTERNS_FILE", config_dir / "x.txt")
    f = tmp_path / "ok.txt"
    f.write_text("nothing\n", encoding="utf-8")
    status, _, err = run(capsys, f)
    assert status == 0
    assert "no personal patterns file" in err


def test_empty_patterns_file_warns(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = config_dir / "patterns.txt"
    path.write_text("# nothing\n\n", encoding="utf-8")
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(path))
    f = tmp_path / "ok.txt"
    f.write_text("nothing\n", encoding="utf-8")
    status, _, err = run(capsys, f)
    assert status == 0
    assert "empty" in err


def test_invalid_pattern_fails_without_copying_it(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = config_dir / "patterns.txt"
    path.write_text(f"ok\n({SECRET}\n", encoding="utf-8")
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(path))
    status, _, err = run(capsys, tmp_path)
    assert status == 2
    assert "line 2" in err
    assert SECRET not in err.lower()


def test_non_utf8_patterns_file_fails(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = config_dir / "patterns.txt"
    path.write_bytes("é\n".encode("latin-1"))
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(path))
    status, _, err = run(capsys, tmp_path)
    assert status == 2
    assert "unreadable" in err


def test_commit_msg_ignores_comments_and_diff(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(
        f"feat: add\n\n# Author: {SECRET}\n{check_anonymity.SCISSORS}\n+ {SECRET}\n",
        encoding="utf-8",
    )
    assert run(capsys, "--commit-msg", f)[0] == 0


def test_commit_msg_body_is_checked(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(f"feat: add\n\nthanks to {SECRET}\n", encoding="utf-8")
    status, out, _ = run(capsys, "--commit-msg", f)
    assert status == 1
    assert ":3: personal or internal information" in out


def test_patterns_file_inside_repository_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "patterns.txt"
    path.write_text(f"{SECRET}\n", encoding="utf-8")
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(path))
    status, _, err = run(capsys, path)
    assert status == 2
    assert "outside the repository" in err


def test_canary_reported_without_personal_patterns(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(check_anonymity.ENV_VAR, raising=False)
    monkeypatch.setattr(check_anonymity, "DEFAULT_PATTERNS_FILE", config_dir / "x.txt")
    f = tmp_path / "shared.txt"
    f.write_text(f"# {check_anonymity.CANARY}\nsomething\n", encoding="utf-8")
    status, out, _ = run(capsys, f)
    assert status == 1
    assert check_anonymity.CANARY_FINDING in out


def test_canary_reported_in_binary(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "archive.bin"
    f.write_bytes(b"\0\0" + check_anonymity.CANARY.encode("ascii") + b"\0")
    status, out, _ = run(capsys, f)
    assert status == 1
    assert check_anonymity.CANARY_FINDING in out


def test_init_creates_starter_that_protects_itself(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = config_dir / "sub" / "deny-patterns.txt"
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(path))
    status, out, _ = run(capsys, "--init")
    assert status == 0
    assert "created" in out
    text = path.read_text(encoding="utf-8")
    assert check_anonymity.CANARY in text.splitlines()[0]
    # The starter only holds comments: no pattern applies until adapted.
    assert "empty" in run(capsys, tmp_path)[2]
    # A copy about to be committed is reported.
    copy = tmp_path / "copy.txt"
    copy.write_text(text, encoding="utf-8")
    status, out, _ = run(capsys, copy)
    assert status == 1
    assert check_anonymity.CANARY_FINDING in out


def test_init_never_overwrites(
    patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = patterns_file.read_text(encoding="utf-8")
    status, _, err = run(capsys, "--init")
    assert status == 2
    assert "already exists" in err
    assert patterns_file.read_text(encoding="utf-8") == before


def test_init_refuses_inside_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "deny-patterns.txt"
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(path))
    status, _, err = run(capsys, "--init")
    assert status == 2
    assert "inside the repository" in err
    assert not path.exists()


def test_control_characters_in_names_are_neutralized() -> None:
    findings = check_anonymity.check_file("bad\x1b[31mname.txt", [])
    assert findings == ["bad?[31mname.txt: unreadable, not checked"]


def test_several_patterns_files_all_apply(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shared = config_dir / "shared.txt"
    shared.write_text(f"{SECRET}\n", encoding="utf-8")
    project = config_dir / "project.txt"
    project.write_text("codename\n", encoding="utf-8")
    # Empty entries (doubled or trailing separators) are ignored.
    value = os.pathsep.join((str(shared), "", str(project), ""))
    monkeypatch.setenv(check_anonymity.ENV_VAR, value)
    f = tmp_path / "doc.txt"
    f.write_text(f"{SECRET}\nCodename\nnothing\n", encoding="utf-8")
    status, out, _ = run(capsys, f)
    assert status == 1
    assert ":1: personal" in out
    assert ":2: personal" in out


def test_one_missing_file_among_several_fails(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shared = config_dir / "shared.txt"
    shared.write_text(f"{SECRET}\n", encoding="utf-8")
    value = os.pathsep.join((str(shared), str(config_dir / "typo.txt")))
    monkeypatch.setenv(check_anonymity.ENV_VAR, value)
    status, _, err = run(capsys, tmp_path)
    assert status == 2
    assert "missing file" in err


def test_one_file_inside_repository_among_several_fails(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shared = config_dir / "shared.txt"
    shared.write_text(f"{SECRET}\n", encoding="utf-8")
    inside = tmp_path / "project.txt"
    inside.write_text("codename\n", encoding="utf-8")
    monkeypatch.setenv(
        check_anonymity.ENV_VAR, os.pathsep.join((str(shared), str(inside)))
    )
    status, _, err = run(capsys, tmp_path)
    assert status == 2
    assert "outside the repository" in err


def test_config_home_honors_absolute_xdg_only(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    assert check_anonymity.config_home() == config_dir
    # The XDG specification says relative values must be ignored.
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/dir")
    assert check_anonymity.config_home() == Path.home() / ".config"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert check_anonymity.config_home() == Path.home() / ".config"


def test_repository_root_found_from_a_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    path = tmp_path / "patterns.txt"
    path.write_text(f"{SECRET}\n", encoding="utf-8")
    monkeypatch.setenv(check_anonymity.ENV_VAR, str(path))
    status, _, err = run(capsys, sub)
    assert status == 2
    assert "outside the repository" in err


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive paths")
def test_inside_repository_ignores_case_on_windows(tmp_path: Path) -> None:
    path = Path(str(tmp_path / "patterns.txt").upper())
    assert check_anonymity.inside_repository(path)


def declare_for_clone(root: Path, *entries: str) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(exist_ok=True)
    text = "# project-specific lists\n\n" + "".join(f"{e}\n" for e in entries)
    (git_dir / check_anonymity.CLONE_DECLARATION).write_text(text, encoding="utf-8")


def test_clone_declaration_adds_project_patterns(
    tmp_path: Path,
    patterns_file: Path,
    config_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = config_dir / "project.txt"
    project.write_text("codename\n", encoding="utf-8")
    declare_for_clone(tmp_path, str(project))
    f = tmp_path / "doc.txt"
    f.write_text(f"{SECRET}\nCodename\nnothing\n", encoding="utf-8")
    status, out, _ = run(capsys, f)
    assert status == 1
    assert ":1: personal" in out
    assert ":2: personal" in out


def test_clone_declaration_accepts_paths_relative_to_the_root(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A sibling of the repository root, like a private repository clone.
    project = tmp_path.parent / f"{tmp_path.name}-private-list.txt"
    project.write_text("codename\n", encoding="utf-8")
    declare_for_clone(tmp_path, f"../{project.name}")
    f = tmp_path / "doc.txt"
    f.write_text("codename\n", encoding="utf-8")
    assert run(capsys, f)[0] == 1


def test_clone_declaration_applies_without_default_file(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(check_anonymity.ENV_VAR, raising=False)
    monkeypatch.setattr(check_anonymity, "DEFAULT_PATTERNS_FILE", config_dir / "x.txt")
    project = config_dir / "project.txt"
    project.write_text("codename\n", encoding="utf-8")
    declare_for_clone(tmp_path, str(project))
    f = tmp_path / "doc.txt"
    f.write_text("codename\n", encoding="utf-8")
    status, _, err = run(capsys, f)
    assert status == 1
    assert "no personal patterns file" in err


def test_clone_declaration_missing_file_fails(
    tmp_path: Path,
    patterns_file: Path,
    config_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare_for_clone(tmp_path, str(config_dir / "typo.txt"))
    status, _, err = run(capsys, tmp_path)
    assert status == 2
    assert f".git/{check_anonymity.CLONE_DECLARATION} points to a missing file" in err


def test_clone_declaration_inside_repository_fails(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inside = tmp_path / "project.txt"
    inside.write_text("codename\n", encoding="utf-8")
    declare_for_clone(tmp_path, "project.txt")
    status, _, err = run(capsys, tmp_path)
    assert status == 2
    assert "outside the repository" in err


def test_clone_declaration_followed_through_a_worktree_gitdir(
    tmp_path: Path,
    patterns_file: Path,
    config_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real_git_dir = config_dir / "worktree-gitdir"
    real_git_dir.mkdir()
    project = config_dir / "project.txt"
    project.write_text("codename\n", encoding="utf-8")
    (real_git_dir / check_anonymity.CLONE_DECLARATION).write_text(
        f"{project}\n", encoding="utf-8"
    )
    (tmp_path / ".git").write_text(f"gitdir: {real_git_dir}\n", encoding="utf-8")
    f = tmp_path / "doc.txt"
    f.write_text("codename\n", encoding="utf-8")
    assert run(capsys, f)[0] == 1


def test_unrecognized_git_file_means_no_clone_declaration(
    tmp_path: Path, patterns_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".git").write_text("not a gitdir line\n", encoding="utf-8")
    f = tmp_path / "doc.txt"
    f.write_text("codename\n", encoding="utf-8")
    assert run(capsys, f)[0] == 0
