# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project skeleton: the `protee` package (typed, version read from the
  installed distribution), Python 3.14 or later, BSD-3-Clause.
- Rules shared by contributors and coding agents (`AGENTS.md`), the
  contributing guide in English and French, and the security policy.
- Local checks (pre-commit hooks: formatting, lint, typing, tests,
  secrets, anonymity, image metadata, hidden characters and local-only
  files), replayed by CI on Ubuntu and Windows with Python 3.14 and
  3.15, with an 80 % branch coverage floor.
- Release workflow: build checked, provenance and SBOM attested,
  publication through Trusted Publishing.
- First algorithms, pure Python, provisional API until version 1.0
  (`import protee` loads the subpackages on demand):
  - `protee.graph`: immutable directed multigraph (parallel arcs and
    loops), topology only;
  - `protee.paths`: Dijkstra, and Bellman-Ford with a negative cycle as
    certificate;
  - `protee.flow`: maximum flow (Dinic, Edmonds-Karp) with a minimum cut;
    feasibility with a violated cut as certificate (Gale, Hoffman);
    minimum or maximum cost flow with bounds and supplies by three named
    methods, always chosen by the caller (`network_simplex` with strongly
    feasible trees and a warm start on new costs, `cycle_canceling`,
    `successive_shortest_paths`), sharing one result: status, integer
    flow, potentials, certificate, deterministic counters; `k` node- or
    arc-disjoint paths of minimum total cost;
  - `protee.flow.diagnostics`: least and greatest flow of each arc (over
    the feasible or the optimal flows), unattainable bounds, exact test
    of the uniqueness of an optimum;
  - `protee.structure`: weak and strong components, degree-2 paths and
    their contraction (protected nodes, per-attribute aggregation,
    expansion), spanning forest, fundamental cycles;
  - `protee.transforms`: reversible transformations of flow problems
    (lower bounds removed, node splitting, subdivision, super-source and
    super-sink with a return arc, path contraction);
  - `protee.io`: node-link JSON, CSV table of arcs, DIMACS minimum cost
    flow format.
- Route-level algorithms in `protee.routes`: a route through waypoints in
  free order (exact, Held-Karp) or fixed order; the `k` shortest loopless
  paths (Yen); replacement paths, one per arc of a route, to find its most
  vital arc; the overlap of two routes, with arcs grouped by key; the most
  reliable path for independent arc reliabilities. `protee.paths.dijkstra`
  takes `excluded` arcs.
- Tests against independent oracles (NetworkX, HiGHS, enumeration) and
  reproducible property-based tests (Hypothesis).
- Runtime dependencies NumPy and SciPy (wheels for every supported
  platform). Lower bounds are the first releases with wheels for each
  Python version: NumPy 2.3.2 and SciPy 1.16.1 on Python 3.14, NumPy
  2.5.2 and SciPy 1.18.1 on Python 3.15. `import protee` does not import
  them.
- `protee.constraints`: requirements (normalized statements taken from a
  source, never package dependencies) turned into traceable constraints
  on graphs, provisional API until version 1.0:
  - model: sources, rulebooks, values with origin and declared
    precedence, each keeping the rulebook and edition of its value set
    (`resolve_values` refuses an unknown parameter, an undeclared
    disagreement or two value sets of the same rulebook and edition, and
    reports unused values), parameters with units and aliases,
    requirements checked as a set (unique identifiers, every cited
    identifier resolved), qualified correspondences between rulebooks;
  - a closed registry of patterns (`patterns`): `threshold_admissibility`,
    `class_admissibility`, `zone_exclusion`, `speed_cap`,
    `occurrence_bounds`;
  - arc attributes with an explicit unknown (`ArcData`, `Attribute`), one
    source per column, derived columns with their quality; a scope label
    must be a declared element, and an arc of unknown element is presumed
    in scope for a restriction, never for a minimum;
  - `evaluate`: one immutable effect per requirement, with three-valued
    verdicts and their reasons, speed caps or flow bounds;
  - `compose`: a computation view independent of the order of the
    effects, with the policy for the unknown stated by the caller
    (`exclude`, `penalize`, `admit_and_count`) and applied once; under a
    speed cap, the view computes the travel times from the length and
    speed of each arc (`ComputationView.times`), and refuses plain
    weights that would ignore the cap;
  - `verify_route` and `verify_flow`: the status of each requirement
    (`applied`, `partial`, `not_applied`, `no_data`, `not_applicable`)
    comes from verification, never from the solver; a speed cap is
    verified on the weights the route was computed with, so that a
    solver that forgot it is caught;
  - `check_inputs`: what the data allow to prove before solving, and the
    best status a result can reach;
  - `requirement_table`: rows generated from the verification.
- `protee.paths.lexicographic_dijkstra`: exact shortest paths for weight
  vectors compared in lexicographic order, for instance the number of
  unknown arcs first, then the length, with no scaling by a large
  constant.
- Useful failure in `protee.constraints`:
  - `minimal_conflict` (methods `enumeration` and `deletion_filter`) and
    `minimal_relaxation` (methods `enumeration` and `greedy`) explain why
    requirements cannot hold together and what to relax, with the cost of
    the result once relaxed;
  - `relax_by_tiers`: declared tiers tried in order, the requirements to
    relax chosen by a named method within the first feasible tier, the
    tier of an option computed from the requirements it relaxes;
  - `RouteSearch` and `FlowSearch` solve under any subset of the
    requirements, with a named method and a stated policy for the unknown
    (keyword arguments without default), and give their `Impact` (result
    with and without a requirement), reported in the requirement table;
    an identifier that names no requirement is refused.
- Declared objective: the `objective` pattern, prescribed by a text or
  chosen with a mandatory justification, verified on the result: the
  criterion of its weights or costs, and its optimality, recomputed
  independently of the solver (Bellman-Ford; for a lexicographic search,
  the fewest unknown arcs first).
- Provenance: `fingerprint` (SHA-256 of a canonical form that tells
  apart the types JSON would confuse) and `provenance` (method, frozen
  parameters, version, requirements, values retained and set aside with
  their rulebook and edition, fingerprints of the inputs and of the
  result), to reuse a result and report a replay that differs.
- `RulebookValues`: rulebooks and their values read from TOML, strictly
  (an unknown or missing key is refused, the notice is required); first
  embedded value set, taken from a public text: the categories (art. 3)
  and maximum speeds (art. 14) of the French order of 4 May 2006 on
  exceptional transport, reused from Legifrance under the Licence Ouverte
  2.0.
- Tests of the whole chain on both reference applications: from the
  embedded values to a verified route, its table and its provenance; nine
  hand-built reference life-cycle profiles, with edge cases (non-zero
  minimum, zero or infinite maxima, unattainable or non-binding maxima,
  overconstrained system, multiple optima).
