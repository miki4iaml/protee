# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Pre-commit hook: refuse hidden characters and files that must stay local.

Instruction files steer coding agents. A malicious change can hide in
characters a reviewer does not see (bidirectional controls, zero-width
characters, Unicode tags, variation selectors), and an instruction file
added in a subfolder, or meant for another tool, escapes the review of
AGENTS.md. The hook refuses, in the files it is given (every tracked file
in CI):

- hidden characters: the format (Cf), private use (Co) and unassigned
  (Cn) code points, the variation selectors, and the control characters
  other than tab and line ends (an escape sequence hides text in a
  terminal). The message names the file, the line and the code point,
  never the text. A file that is not valid UTF-8 (an image) is not
  checked for characters.
- files that must stay local: anything under ``_priv/`` or ``.claude/``,
  and files named ``CLAUDE.md``, ``CLAUDE.local.md`` or ``.mcp.json`` at
  any depth. Git ignores them; a tracked copy would overwrite the local
  one on checkout.
- instruction files of coding agents: ``AGENTS.md`` at the root only,
  where it is reviewed; the instruction files of other tools anywhere
  (:data:`AGENT_FILES`, with their sources).

No exception list: nothing in the repository needs one. If a file ever
does, the exception is declared here, with its reason.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

#: Categories of hidden code points: format, private use, unassigned.
HIDDEN_CATEGORIES = frozenset({"Cf", "Co", "Cn"})

#: Variation selectors, which change how the character before them looks.
VARIATION_SELECTORS = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))

#: Control characters a text file may hold: tab and line ends.
ALLOWED_CONTROLS = frozenset("\t\n\r")

#: Paths that stay on the workstation: a name matches a file at any depth,
#: a name ending with ``/`` a folder at any depth.
LOCAL_FILES = ("_priv/", ".claude/", "CLAUDE.md", "CLAUDE.local.md", ".mcp.json")

#: Instruction files of other coding agents, read by them on their own:
#: (path, tool, source). Checked on 2026-10-31; the official documentation
#: of Cursor, Windsurf, Cline and Junie was not reached, so their entries
#: rest on secondary sources, to check again at each release.
AGENT_FILES = (
    ("AGENTS.override.md", "Codex", "developers.openai.com/codex/guides/agents-md"),
    ("GEMINI.md", "Gemini CLI", "geminicli.com/docs/cli/gemini-md"),
    (
        ".github/copilot-instructions.md",
        "GitHub Copilot",
        "docs.github.com/en/copilot/concepts/prompting-and-context/custom-instructions",
    ),
    (
        ".github/instructions/",
        "GitHub Copilot",
        "same page: path-specific instructions",
    ),
    (".github/agents/", "GitHub Copilot", "same page: custom agents"),
    (
        ".github/prompts/",
        "VS Code",
        "code.visualstudio.com/docs/agent-customization/prompt-files",
    ),
    (
        ".vscode/mcp.json",
        "VS Code",
        "code.visualstudio.com/docs/copilot/guides/mcp-developer-guide",
    ),
    (".cursorrules", "Cursor", "secondary sources"),
    (".cursor/", "Cursor", "secondary sources"),
    (".windsurfrules", "Windsurf", "secondary sources"),
    (".windsurf/", "Windsurf", "secondary sources"),
    (".clinerules", "Cline", "secondary sources"),
    (".clinerules/", "Cline", "secondary sources"),
    (".cline/", "Cline", "secondary sources"),
    (".junie/", "JetBrains Junie", "secondary sources"),
)


def hidden(character: str) -> bool:
    """Whether a character is hidden: format, private use, unassigned, selector."""
    point = ord(character)
    category = unicodedata.category(character)
    return (
        category in HIDDEN_CATEGORIES
        or (category == "Cc" and character not in ALLOWED_CONTROLS)
        or any(low <= point <= high for low, high in VARIATION_SELECTORS)
    )


def _matches(path: str, entry: str) -> bool:
    """Whether a repository path matches an entry: a name, a path, a folder."""
    rooted = "/" + path
    if entry.endswith("/"):
        return "/" + entry in rooted
    return rooted.endswith("/" + entry)


def check_path(path: str) -> list[str]:
    """The reasons a path cannot be tracked, if any."""
    path = Path(path).as_posix().removeprefix("./")
    reasons = []
    if any(_matches(path, entry) for entry in LOCAL_FILES):
        reasons.append(f"{path}: stays local (ignored by git), never tracked")
    if path != "AGENTS.md" and _matches(path, "AGENTS.md"):
        reasons.append(
            f"{path}: AGENTS.md is accepted at the root only, where it is "
            "reviewed; coding agents would read this one on their own"
        )
    for entry, tool, _source in AGENT_FILES:
        if _matches(path, entry):
            reasons.append(f"{path}: instruction file of {tool}, refused")
            break
    return reasons


def check_text(path: str, text: str) -> list[str]:
    """One finding per hidden character: file, line, code point, category."""
    findings = []
    # Split on line feeds only: splitlines would swallow other controls.
    for number, line in enumerate(text.split("\n"), start=1):
        for character in line:
            if hidden(character):
                category = unicodedata.category(character)
                findings.append(
                    f"{path}:{number}: hidden character U+{ord(character):04X} "
                    f"(category {category})"
                )
    return findings


def check_file(name: str) -> list[str]:
    findings = check_path(name)
    try:
        text = Path(name).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return findings
    return findings + check_text(Path(name).as_posix(), text)


def main(argv: list[str]) -> int:
    findings = [finding for name in argv for finding in check_file(name)]
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
