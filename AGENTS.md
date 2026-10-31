# AGENTS.md — protee

Rules shared by all contributors and their coding agents, whatever the
tool. The practical guide (setup, hooks, pull request workflow) is in
[.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).

## Project

`protee` (Proteus) is a Python package for operations research and the
adaptive solving of life-cycle profile graphs. Its model, its solvers
and its design goals are defined in the first work items.

Structural constraint: the package must work on an offline workstation.
It may rely on well-supported, widely adopted dependencies, but never on
a solver, a service or an engine reachable only through the Internet.

## Design goals

To be defined in the first work items, with the maintainer. Each goal
will be a rule that holds for every part of the package, enforced by
the invariants below, the code and the tests.

## Architecture and invariants

- No core dependency yet: each one is chosen with the dependency grid
  and explicit approval (see Working rules).
- `import protee` stays light: submodules are imported on demand.
- Reference data is immutable: frozen structures (`frozen=True`), no
  mutation after construction.
- No mutable global state. The package must be safe in concurrent
  contexts; parallelism is the caller's business.
- Explicit public API (`__all__`). Only the public API is covered by
  semantic versioning.

## Conventions

- Language: English for everything versioned (code, docstrings,
  documentation, commits, pull requests). French translations:
  `README.fr.md`, `.github/CONTRIBUTING.fr.md`, and later the
  documentation; the English version is authoritative.
- Branches: `main` (released versions), `develop` (default branch,
  integration), and work branches prefixed with their Conventional
  Commits type (`feature/`, `fix/`, `docs/`, `ci/`, `chore/`…). Never
  commit directly to `main` or `develop`: always a branch, then a pull
  request against `develop`.
- Merges into `develop` are squash merges only; the pull request title
  becomes the commit message.
- Commit messages and pull request titles: Conventional Commits
  v1.0.0, optional scope, ASCII-only subject.
- Commits signed and verified by GitHub, required on every pull
  request.
- Versions: `0.x` until a `1.0.0` whose scope is still to be defined.
  Version declared only in `pyproject.toml`, read through
  `importlib.metadata`. Git tags prefixed with `v`.
- `requires-python = ">=3.14"`. Development on 3.14.
- Documentation: Sphinx, NumPy-style docstrings. A strict build will
  be a blocking CI check.
- License BSD-3-Clause. Every source file starts with:
  ```
  # SPDX-FileCopyrightText: 2026 Miki
  # SPDX-License-Identifier: BSD-3-Clause
  ```

## Releasing

1. Pull request against `develop` (squash): version bump in
   `pyproject.toml` and `CITATION.cff`, `[Unreleased]` section of
   `CHANGELOG.md` turned into `[x.y.z] - date`, titled
   `chore: release x.y.z`.
2. Pull request `develop` → `main`, merged with a merge commit (the
   only exception to squash: `main` must hold the exact history of
   `develop`, otherwise both branches diverge at every release).
3. Before tagging, check locally: `uv build` then
   `uvx --from twine twine check --strict dist/*`.
4. Signed tag `vx.y.z` on `main`, then publish a GitHub release from
   it, its notes the `CHANGELOG.md` section of the version, with links
   made absolute: `python scripts/absolute_links.py rewrite --repo
   miki4iaml/protee --ref vx.y.z notes.md`. The release workflow
   (`.github/workflows/release.yml`) checks that the tag matches the
   project version, makes the links of the README absolute at the tag
   (PyPI shows it outside the repository), builds once, checks that no
   relative link is left, attests the build provenance and the CycloneDX
   SBOM, and publishes exactly those files to PyPI through Trusted
   Publishing (OIDC, no stored token), after approval of the protected
   `pypi` environment.
5. Verify: `gh attestation verify <wheel> --repo miki4iaml/protee`.

Rehearsal: run the release workflow manually (`workflow_dispatch`). It
publishes a unique `x.y.z.devN` version to TestPyPI without creating a
release. Never publish a GitHub release just to test: each published
release also archives a permanent Zenodo DOI.

## Security

No safety rule is bypassed, including during project bootstrap.

- GitHub Actions pinned by commit SHA, never by a moving tag; the
  repository enforces it. Dependabot keeps the pins up to date.
- Workflow permissions read-only by default; elevated only in the job
  that needs it.
- No secret in the repository, no stored token: PyPI publication
  through OIDC trusted publishing.
- Local checks (pre-commit hooks): formatting, lint, secrets,
  anonymity and hidden characters before each commit; typing and tests
  on push. CI replays the same checks.
- Instruction files of coding agents are code. AGENTS.md lives at the
  root only; no other tool's instruction file, and nothing that stays
  local (`_priv/`, `.claude/`, `CLAUDE.md`, `.mcp.json`), is tracked;
  `scripts/check_integrity.py` refuses them, with hidden characters.
  A pull request from someone else is read as a diff (`gh pr diff`),
  never checked out in a working tree where a coding agent runs, which
  would load its instructions.
- Nothing personal or internal in what is published: no legal name,
  no internal path, no work email address, no customer name.

## Working rules

- Propose a plan before any change touching more than two files.
- No new dependency without explicit approval.
- The lowest supported versions of the dependencies are a goal, not a
  constraint: when keeping one would cost complexity, readability,
  maintainability or many more tests, propose raising it, stating why
  (its release date; SPEC 0 drops core packages two years after their
  release; who in the ecosystem still needs it), and record it in
  `CHANGELOG.md`.
- No public function without a test.
- Every user-visible change adds an entry under `[Unreleased]` in
  `CHANGELOG.md` (Keep a Changelog format).
- No new file at the repository root unless necessary.
- Portability: `pathlib`, explicit UTF-8 encoding on every file open,
  no hard-coded shell command, `importlib.resources` for embedded
  data.
- No tool attribution in commit messages or pull request descriptions
  (no Co-Authored-By, no "Generated with …"); the policy on coding
  agents is in CONTRIBUTING.
- Propose before executing anything hard to reverse or
  outward-facing.
- Verify before asserting: a version or a tool behavior can be
  checked.
- Challenge a false premise rather than answering beside the point.

## Settled decisions

- **CI matrix**: complete and blocking, Ubuntu and Windows × Python
  3.14 and 3.15: the minimum, on which development happens, and the
  next version as a canary, which shows breakages before users meet
  them. Portability and `requires-python >=3.14` are promises made to
  the package's users; a non-blocking cell ends up ignored and the
  promise stops being checked. The minimum version is to be confirmed
  in the first work items, with the first dependencies.
- **Contributor signatures**: a squash merge produces a commit signed
  by GitHub, which hides the commits of the pull request; the
  `signatures` CI job therefore requires each of them to be signed and
  verified.
- **`.vscode` partly versioned**: `settings.json`, `extensions.json`
  and `tasks.json` are shared (ruff and mypy from the environment,
  recommended and unwanted extensions, "Quality gates" task); the
  rest of the folder stays local. The interpreter is not set: the
  Python extension discovers `.venv` on its own. Do not reintroduce
  `python.defaultInterpreterPath` pointing to a folder: the Python
  extension resolves it for itself only, but passes it raw to the ruff
  and mypy extensions, which fail to launch it. An executable path
  would be OS-specific.
- **mypy at pre-push**: deliberate overlap with CI, so that failures
  happen locally rather than after the push. Keep an eye on push time.
- **Coverage**: branch coverage measured with coverage.py (no
  pytest-cov); an 80 % floor is enforced in every cell of the CI test
  matrix (Google's guideline rates 75 % commendable, 90 % exemplary).
  The pre-push hook runs plain pytest to stay fast; CI is authoritative
  for coverage.

## Commands

```
uv sync --all-extras                       # environment
uv run pytest                              # tests
uv run coverage run -m pytest && uv run coverage report   # coverage
uv run ruff check --fix && uv run ruff format
uv run mypy                                # strict typing
uv run --isolated --python 3.15 --all-extras pytest   # reproduce CI
uv run --isolated --resolution lowest-direct --all-extras pytest   # lower bounds
```

`--isolated` matters for the last two commands: without it, `uv run`
re-locks `uv.lock` with the requested resolution and replaces the
project's `.venv`.
