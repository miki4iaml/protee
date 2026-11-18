# AGENTS.md — protee

Rules shared by all contributors and their coding agents, whatever the
tool. The practical guide (setup, hooks, pull request workflow) is in
[.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).

## Project

`protee` (Proteus) is a Python package of graph and operations research
algorithms whose methods are chosen explicitly, compared, and backed by
certificates and diagnostics. Its design goals, scope and invariants
follow; its model and its solvers are refined over the 0.x versions.

Structural constraint: the package must work on an offline workstation.
It may rely on well-supported, widely adopted dependencies, but never on
a solver, a service or an engine reachable only through the Internet.

## Design goals

Each goal holds for every part of the package; the invariants below, the
code and the tests enforce it.

1. **Reference applications.** For now, two applications guide and
   validate the generic core: life-cycle profiles (small graphs, bounded
   circulations, partially specified bounds) and route planning on large
   road networks. Each feature states what it brings to both, and is
   tested on both when it applies. Other applications may join, provided
   they serve the same aim: translating needs into constraints on a
   graph, with traceability and reproducibility.
2. **Explicit choice of method.** Every problem has named methods; the
   caller chooses one, by the function's name or by a `method` argument
   without default. A helper may recommend a method, never pick one
   silently. The package exists to show the comparative merits of
   algorithms: exact and approximate methods side by side, with their gap.
3. **Comparable and verifiable results.** All methods of a problem
   return the same result type: status, solution, certificates,
   deterministic work counters, the method's name and the package
   version; a shared conformity suite runs every method of the registry
   on the same instances. A negative answer comes with a certificate (a
   violated cut for infeasibility, an improving cycle for unboundedness);
   an optimum comes with its dual values; a heuristic result comes with a
   bound and its gap. Public `verify_*` functions check a result against
   the stated constraints, independently of the method that produced it.
4. **Provenance.** A result records its method, parameters, package
   version and a fingerprint of its inputs, so that it can be replayed.
5. **A traceable chain from requirement to result.** Each constraint
   comes from a requirement and keeps its source: source, normalized
   requirement, named constraint pattern, values, named method, proof.
   Constraint patterns have explicit, generic names; their values come
   from value sets, each value with its source, edition and precedence.
   The package ships only value sets taken from public texts, as
   examples and for end-to-end tests. A constraint never modifies the
   graph: it returns an immutable effect (a verdict, a cost term or a
   forbidden transition per element) that carries the requirement's
   identifier and source. Effects compose independently of their order;
   conflicting values are settled by the declared precedence, never by
   the order of application.
6. **Explicit unknown.** A missing attribute is unknown, never presumed
   compatible: verdicts have three values, the caller states the policy
   for the unknown (exclude, penalize, admit and count), and every result
   counts its unknowns.
7. **Useful failure.** An infeasible problem returns its explanation (a
   cut, a minimal set of conflicting constraints) and, when asked, its
   relaxations, one at a time or by declared levels, each with its cost.
8. **Structure separate from metric.** A graph holds the topology only;
   bounds, costs and supplies live in the problems. A problem is prepared
   once and solved for many cost vectors, with a warm start when the
   method allows it.
9. **Reversible transformations.** Transformations (node splitting,
   subdivision, lower bound removal, super-terminals, path contraction,
   and later the line graph) are explicit objects that map solutions back
   to the original problem; they are support functions of the methods,
   not hidden steps.
10. **Representation separate from visualization.** The core computes and
    represents; drawing belongs to optional extras, imported lazily.
11. **Offline and light.** The core works on an offline workstation and
    relies only on widely adopted packages with wheels for every
    supported platform; solvers, geometry and rendering are optional
    extras, imported lazily; nothing is reachable only through the
    Internet. Working offline is a property of the package, not a limit
    on its use: a client application may run it on a server or in a
    cloud environment and serve its results online.
12. **Provisional formalization until 1.0.** Problem statements and APIs
    evolve with the feedback of the 0.x versions; version 1.0 commits to
    them.

## Scope

protee solves graph and operations research problems on data the caller
provides. It does not:

- acquire data (downloads, online services);
- process raw geographic data (GIS formats, reprojection, topological
  cleaning, rasters);
- read maps or images;
- decide the values of a domain (regulations, operating rules): it
  provides named constraint patterns, and the values come from value
  sets tied to their sources;
- provide an application (user interface, server, real time);
- rely on a remote solver or service.

The core has no geometry: it receives relations computed elsewhere
(conflicting pairs of arcs, turn radii, arcs inside a zone). An optional
`geo` extra, planned after the core, will compute such relations from
geometries.

Time is in scope, in a module separate from the rest of the package. The
other problems are static: a route uses an arc or not. The time module
starts from computed routes, speeds, column lengths and departure times,
and answers when each vehicle column occupies each arc and node: it
returns the occupation intervals, the conflicts between them, the
minimal delays that remove the conflicts for a given priority order,
and the resulting schedule.

## Architecture and invariants

- Layers: `protee.graph` (model) → `protee.structure` (computed once) →
  methods (`protee.paths`, `protee.routes`, `protee.flow`) → diagnostics
  (`protee.flow.diagnostics`); `protee.transforms` supports the methods;
  `protee.io` reads and writes the formats.
- Requirements go through fixed phases: evaluate (one effect per
  requirement) → compose (a computation view: mask and cost vector, with
  links back to the effects) → transform (protected nodes, mapping back)
  → solve → verify → explain. Topology transformations come after the
  effects; route-level constraints act during the search.
- Core dependencies: NumPy and SciPy, chosen with the dependency grid;
  each lower bound is the first release with wheels for the Python
  version. Any other one needs explicit approval (see Working rules).
- `import protee` stays light: subpackages are imported on demand
  (PEP 562); NumPy and SciPy are imported only by the subpackages that
  use them.
- Reference data is immutable: frozen structures (`frozen=True`), inputs
  copied into tuples or read-only arrays, no mutation after
  construction.
- Integer bounds and supplies give integer optimal flows; float costs are
  compared with an explicit tolerance, never with exact equality.
- Determinism: the same input gives the same output and the same counters
  on every machine; randomness only with an explicit seed.
- The method registries are closed until 1.0: a new method comes with its
  reference, its complexity, its guarantee and its place in the
  conformity suite.
- Every method is tested against at least one independent oracle
  (another library, enumeration on small instances); property-based
  tests are reproducible (derandomized, no example database). The order
  independence of the composition is a tested property.
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
  promise stops being checked. The minimum is confirmed with the first
  dependencies: NumPy and SciPy publish wheels for 3.14 and 3.15 on
  both systems.
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
