# Contributing to protee

**English** | [Français](CONTRIBUTING.fr.md)

Thank you for your interest. This guide covers setup, checks and the
path of a contribution. Coding and architecture rules live in
[AGENTS.md](../AGENTS.md), which applies to humans and coding agents
alike.

## Ways to contribute

All of them are welcome: report a problem, propose an improvement in an
issue, or contribute code (setup, checks and workflow below). The
package is at its very beginning: its model and its solvers are being
designed.

## Prerequisites

- Python 3.12 or later.
- [uv](https://docs.astral.sh/uv/). It is required: the ruff, mypy and
  pytest hooks run through `uv run --frozen`, so they use exactly the
  versions locked in `uv.lock` (a single source of versions, locally
  and in CI). Without uv, these hooks fail.
- A commit signing key (see below).

## Setup

```
uv sync --all-extras
uv run pre-commit install
```

The first command also installs the optional extras, if any, which
the tests cover. The second command installs the hooks at all three
stages (pre-commit, commit-msg, pre-push).

On Windows without a C compiler: PyYAML, which pre-commit requires,
has no wheel for Python 3.15 yet. Setting the environment variable
`PYYAML_FORCE_LIBYAML=0` builds it in pure Python.

## Local checks

| Stage | Checks |
|---|---|
| pre-commit | file hygiene (whitespace, end of file, LF line endings, BOM, YAML, TOML, merge conflicts, large files), private keys, no direct commit to `main` or `develop`, `ruff check --fix` and `ruff format`, codespell (spelling), zizmor (workflow security audit), gitleaks, nbstripout, anonymity, image metadata, hidden characters and local-only files |
| commit-msg | anonymity of the message, Conventional Commits, ASCII-only subject |
| pre-push | strict mypy, pytest |

In VS Code, the "Quality gates" task runs ruff
check, ruff format --check, mypy and pytest in sequence.

### Anonymity

You do not need to be an expert to stay anonymous here: one command
sets it up, and the hook then checks every commit for you.

**Why.** Personal details leak into public repositories more easily
than one thinks: your home directory in a path copied from a terminal
or a notebook output, your employer's email domain, a project codename,
your legal name in a comment or in a file's metadata. Once pushed, they
stay in the history.

**How it works.** The `scripts/check_anonymity.py` hook rejects a
commit when a file content, a file path or the commit message matches
a *deny pattern*. It applies:

- generic patterns, versioned here (home directory paths);
- your personal patterns, read from a file that lives **outside** the
  repository, so that the list itself is never published.

The hook reports `file:line` only and never prints a pattern.

**Set it up in one command** (from the repository root):

```
uv run python scripts/check_anonymity.py --init
```

It creates `~/.config/anonymity/deny-patterns.txt` (under
`$XDG_CONFIG_HOME` if set), with instructions and commented examples.
Edit it to list what you want to keep private. Without this file, the
hook warns and applies the generic patterns only.

**One list for all your repositories.** The names belong to the tool,
not to this project: any repository using this hook reads the same
file, so you maintain your list once. To add project-specific patterns
(a client's codenames, the name of another account you keep separate),
set the `ANONYMITY_DENY_PATTERNS` environment variable to several
files, separated like `PATH` (`;` on Windows, `:` elsewhere), for
example `~/.config/anonymity/deny-patterns.txt;~/.config/anonymity/client.txt`.
Every listed file must exist: a typo fails the hook instead of being
silently skipped.

**Patterns for one repository only.** The environment variable applies
to every repository. To add a list for this repository only, write its
path in `.git/anonymity-deny-patterns` (inside the git directory, so
never committed): one path per line, absolute or relative to the
repository root, for example `../my-private-notes/protee-patterns.txt`.
The same rules apply: the file must exist and stay outside the
repository.

**Your personal folder.** A `_priv/` folder at the repository root is
ignored by git: keep your personal notes, analyses or assistant files
there, and back them up as you wish. Never put a patterns file in it:
patterns files must stay outside the repository.

**Writing good patterns.** One regular expression per line,
case-insensitive; blank lines and `#` comments are ignored.

- `\b` marks a word boundary: `\bdoe\b` matches "Doe" but not "Doerr".
- Escape dots: `example\.org` (a bare dot matches any character).
- No Unicode normalization: list accented and unaccented variants,
  for example `h[eé]l[eè]ne`.
- Do not list your public pseudonym if it appears on purpose in the
  repository (author field, URLs): every commit would be rejected.
- Avoid nested quantifiers such as `(a+)+`: they can make the hook
  hang.

**The list protects itself.** A patterns file inside the repository is
refused. The file created by `--init` starts with a marker line, and
any file containing it is rejected, even in CI: a copy of your list
cannot be committed by mistake. Keep that line; a partial copy without
it is not detected.

**Images and PDFs.** An image carries no metadata at all: the
`scripts/check_image_metadata.py` hook refuses text, EXIF (with the
place a photograph was taken), XMP, IPTC, comments, timestamps and
colour profiles, and any block it does not know, in PNG, JPEG, GIF,
WebP and SVG; other formats are refused as not checked. The message
names the block, never its contents. A PDF keeps its metadata (the
official authors of a reference): the anonymity hook searches it,
decompressed when it sits in a compressed stream.

**What the hook does not cover.** Compressed contents (docx, the pages
of a PDF), history that was already pushed, branch and tag names, and
anything typed on GitHub itself: pull request titles and descriptions,
issues, comments. Reread those before posting. The hook can also be
skipped locally (`git commit --no-verify`); CI then still applies the
generic patterns and the marker check, but never your personal ones,
which stay on your machine by design.

## Contribution workflow

1. Create a branch from `develop` (the default branch), prefixed with
   its Conventional Commits type, for example `feature/profile-graph`.
2. Signed commits, Conventional Commits format, ASCII-only subject:
   `feat: add the profile graph`.
3. Open a pull request against `develop`. Its title follows the same
   format: it becomes the commit message on squash merge.
4. CI must be green. Required checks:
   - `quality`: the hooks above, on the whole repository;
   - `tests`: Ubuntu and Windows × Python 3.12, 3.13 and 3.14, with an 80 %
     branch coverage floor;
   - `signatures`: every commit of the pull request is signed and
     verified.
5. The branch must be up to date with `develop` before merging.

### Signing commits

With an SSH key (the simplest option):

```
git config gpg.format ssh
git config user.signingkey ~/.ssh/my_key.pub
git config commit.gpgsign true
```

Then add the public key to GitHub as a *Signing key*
(Settings → SSH and GPG keys). Your commits should show the
"Verified" badge. A GPG key works too.

## Releasing

Versions are `0.x` until 1.0; the version is declared in
`pyproject.toml` only, and read through `importlib.metadata`. Follow
these steps in order.

### Before the first release

- PyPI and TestPyPI: declare the release workflow as a trusted
  publisher (environments `pypi` and `testpypi`). Its repository field
  takes the repository name alone (`protee`): the owner has a field of
  its own. A pending publisher does not reserve the name: the first
  upload does.
- Zenodo: enable the repository from the account of the publishing
  identity. After "Sync now", the list of repositories is updated only
  once the page is reloaded. `.zenodo.json` names the creator: without a
  name, the archive fails without an error message.

### Each version

1. A pull request against `develop` (squash), titled
   `chore: release x.y.z`:
   - the version in `pyproject.toml`, in `CITATION.cff` (with
     `date-released`) and in `uv.lock`, where only the `version` line of
     `protee` changes (`uv lock` may rewrite the whole file), checked by
     `uv lock --check`;
   - the `[Unreleased]` section of `CHANGELOG.md` turned into
     `[x.y.z] - date`, opening with what the version brings: it becomes
     the notes of the release;
   - `README.md` and `README.fr.md` updated for the version
     (installation from PyPI, extras).
2. A pull request `develop` → `main`, merged with a merge commit: the
   only exception to squash, so that `main` holds the exact history of
   `develop`.
3. Before tagging:
   - `uv build`, then `uvx --from twine twine check --strict dist/*`;
   - no advisory in the GitHub Advisory Database for the JavaScript
     embedded in the package (`src/protee/_assets/NOTICE.md`), which
     Dependabot does not watch.
4. A signed tag `vx.y.z` on `main`, then a GitHub release from it, its
   notes the `CHANGELOG.md` section of the version, with links made
   absolute: `python scripts/absolute_links.py rewrite --repo
   miki4iaml/protee --ref vx.y.z notes.md`. The release workflow
   (`.github/workflows/release.yml`) checks that the tag matches the
   project version, makes the links of the README absolute at the tag
   (PyPI shows it outside the repository), builds once, checks that no
   relative link is left, attests the build provenance and the CycloneDX
   SBOM, and publishes exactly those files to PyPI through Trusted
   Publishing (OIDC, no stored token), after approval of the protected
   `pypi` environment.

### After publication

- The PyPI page shows the README and its images; an address at the tag
  answers only once the tag is pushed.
- The Zenodo DOI of the version is published.
- The published wheel is downloaded (`pip download protee==x.y.z
  --no-deps`, or `curl -L`: without `-L`, the redirection of PyPI gives
  an empty file) and verified:
  `gh attestation verify <wheel> --repo miki4iaml/protee` for the build
  provenance, then with `--predicate-type https://cyclonedx.org/bom` for
  the SBOM, which the first command does not check.
- The published version installs in an isolated environment, with its
  extras, on the lowest and the highest supported Python:
  `uv run --isolated --no-project --refresh-package protee --python 3.12
  --with "protee[viz,units]==x.y.z" python -c "import protee.viz, pint"`,
  then the same with `3.14`. `--refresh-package protee` makes uv read the
  index again: just after a publication, its cache may still hold the
  former index, without the new version (found for 0.3.0).
- Conclude from PyPI, not from the state GitHub shows: a job may still
  show as pending when PyPI has the files.

### Rehearsal

Run the release workflow by hand (`workflow_dispatch`): it publishes a
unique `x.y.z.devN` version to TestPyPI, without a release. Never
publish a GitHub release to test: each published release also archives
a permanent Zenodo DOI.

## Security

Never report a vulnerability in a public issue: follow the
[security policy](SECURITY.md), which uses GitHub's private
vulnerability reporting.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
By participating, you agree to uphold it.

## Coding agents

This project uses coding agents; every contribution is reviewed and
signed by a human contributor. No tool attribution is added to commits
or pull requests: the human signature commits the contributor,
whatever the tool used.

Instruction files of coding agents are reviewed as code. AGENTS.md is
the only one tracked, at the root: the `check-integrity` hook refuses
an AGENTS.md in a subfolder, the instruction files of other tools
(`GEMINI.md`, `.cursorrules`, `.github/copilot-instructions.md`...),
files that stay local (`CLAUDE.md`, `.claude/`, `.mcp.json`) and hidden
characters (zero-width, bidirectional, tags, variation selectors,
control characters). A maintainer reads a pull request from someone else
as a diff, on GitHub or with `gh pr diff`, and never checks it out in a
working tree where a coding agent runs: the agent would load the
instructions it brings. `.github/CODEOWNERS` lists the paths whose
changes need the maintainer's review.

## License

By contributing, you agree that your contribution is published under
the project's [BSD-3-Clause](../LICENSE) license.
