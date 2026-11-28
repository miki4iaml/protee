# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A phase *derive* before *evaluate* in `protee.constraints`: the values
  on the side of the subject, derived from its description, each with its
  trace. A `Member` is described by its technical sheets, value sets of a
  rulebook of the new kind `RulebookKind.DESCRIPTION`; a `Group` holds
  members or groups with their counts, positive integers, nested to any
  depth (`Group.flatten` multiplies the counts along the path).
  `Group.from_counts` builds a group from a table of counts and declares
  what a row of count 0 does (`ZeroCount.REFUSE`, or `ZeroCount.DROP`,
  which records it); `Group.with_counts` makes a variant with other counts
  under its own identifier (`variant_of`), the base of a sensitivity
  analysis; `Group.without` a declared sub-group, each exclusion recorded
  with its reason.
- `aggregate`, the first derivation of the closed registry
  `derivations()` (`DerivationInfo`): the values of a group from those of
  its members, by a rule declared for each output parameter
  (`Aggregation`, `AggregateKind`): `max`, `min`, `strictest` in a
  declared order, `sum` and `mean` weighted by the counts, `count`, and
  `threshold_count`, the members beyond a threshold by a declared
  `Comparison` (`above`, `at_least`, `below`, `at_most`). The arithmetic is
  exact (a float read as the decimal it shows, the result rounded once):
  the result depends on the multiset of the members only. It returns
  `Derived`, a value set named after the group, which enters
  `resolve_values` like any other, with the tallies (`Tally`) of the
  inputs unknown, assumed and left out; `Derived.merge` joins the values of
  several calls on the same subject.
- Four states of a value (`ValueState`): known, unknown (to be set),
  assumed (by a derivation only) and not applicable, declared with its
  reason in `Value.not_applicable`, and the TOML key `not_applicable` of
  `protee-rulebook-values/0`. A requirement that needs a value not
  applicable is not applicable, with that reason, in `evaluate`,
  `check_inputs`, `verify_route` and `verify_flow`; a derivation leaves
  such an input out, under every policy.
- `OnUnknown`, the policy of a derivation for the inputs without a value,
  stated without default (`UnknownRule`): `propagate` (the value is to be
  set; only the last label of a `strictest` order, or the highest rank of
  a classification, decides despite unknown inputs), `known_only` (with
  its justification; refused for `sum`, `mean`, `threshold_count` and
  `column_length`, which it would shorten, and for `select_by_class`) and
  `assume` (a value chosen with its justification, recorded with the
  members it replaces).
- The trace of a derived value: `Origin.DERIVED`, and `Value.derivation`,
  a `Derivation` that holds the rule, the members that fix the value,
  every input with its source and state (`DerivationInput`), the
  assumptions (`Assumption`), the members left out (`LeftOut`,
  `LeftOutCause`), the unknown inputs and, for an envelope (`max`, `min`,
  `strictest`) or a classification to be set, the extreme of the known
  inputs as `bound`;
  `Conversion` records the conversion of an input into the unit of its
  parameter. A requirement whose derived value is to be set names the
  members without a value.
- `classify_by_thresholds`, a derivation of the registry: the class of a
  subject from thresholds on its characteristics (`Characteristic`), each
  taken from a value set of a text, with the comparison that crosses them
  declared without default (`above` keeps a value at the threshold in the
  lower class, `at_least` moves it up; `below` and `at_most` for a
  smaller value that is stronger). The rank of a characteristic is one plus
  the thresholds it crosses, exactly; the strongest characteristic decides,
  and the trace cites it with the thresholds and their sources. Under
  `propagate`, a characteristic at the highest rank decides despite unknown
  ones; otherwise the class is to be set, its derivation keeping the class
  of the known characteristics as `bound`. It reads a value set, resolved
  values or derived values, such as the envelope of a group.
- `select_by_class`, a derivation of the registry: the value a class
  selects in a table, with the class and the source of the value in its
  trace. A class without a value of its own (`NotApplicable`, with its
  reason) gives a value not applicable, never an infinite limit; a class
  absent from the table is refused, and `known_only` too.
- `column_length`, a derivation of the registry: the length a group
  occupies in a column, level by level, from the lengths of its members
  (`geometric`) or their number over a density (`density`), plus the gaps
  between its units (`Gap`), counted between units or one per unit
  (`GapCount`, without default), in distance or in time at a pace. The
  values of a group are read on it, else on its nearest ancestor, else in
  a context; a member whose length is not applicable is out of the
  column. `known_only` is refused: it would shorten the column.
- The optional extra `units` (pint 0.26 or later, imported on first use):
  a derivation converts an input in another unit than the one it must
  have into that unit, exactly (a factor such as 5/18 from km/h to m/s),
  and records each `Conversion`; a converted value is a float, rounded
  once, and comparisons stay exact. `aggregate` converts the values of
  the members, the value assumed and a threshold into the unit of their
  parameter; `classify_by_thresholds` converts each threshold into the
  unit of its characteristic (72 t is the 2nd category against a
  threshold of 72 000 kg); `select_by_class` converts the value selected
  into the unit of the output; `column_length` converts the lengths and
  the gaps in distance into the unit of the column, a density into its
  inverse, and a gap in time at a pace into a distance (a gap in min at a
  pace in km/h). A unit pint does not know, two units of different
  dimensions, a unit with an offset (`degC`) and a calendar convention (a
  year or a month, which pint counts as 365.25 days and a twelfth of it)
  are refused. Without the extra, an input in another unit is refused
  with an `ImportError` that names `protee[units]`; a value in the unit
  it must have never needs it. `readable` shows a value as a person reads
  it: a duration in days, hours and minutes (`"1 h 30 min"`), a length in
  km or m (`"12.4 km"`), `"no limit"`, `"to be set"`, `"not applicable"`;
  `RequirementRow.to_dict(readable=True)` adds it to each value as
  `"shown"`, and the default output does not depend on the extras
  installed.
- `capacity_admissibility`, a pattern of the closed registry: an arc is
  admissible when its demand (the depth of a ford, the grade of an
  approach) is at most the capacity of the subject (the depth it can
  ford, the grade it can climb), the mirror of `threshold_admissibility`:
  a verdict per arc, a pass at equality, `unknown` and counted without
  data, out of scope as any verdict; `verify_route`, `verify_flow` and
  `check_inputs` check it. The envelope of a group follows the direction
  of its requirement: a quantity by its maximum, a capacity by its
  minimum.
- The partial envelope in the admissibility patterns: when the value of
  a `threshold_admissibility`, `class_admissibility` or
  `capacity_admissibility` requirement is to be set by an envelope
  (`max`, `min` or `strictest` of `aggregate`, or
  `classify_by_thresholds`, under `propagate`), `evaluate` reads the
  `bound` of its known members: an arc the bound fails whatever the
  unknown members fails for certain (`Reason.VIOLATED`), every other arc
  in scope is `unknown` (the new `Reason.VALUE_TO_BE_SET`), counted and
  handled by the policy for the unknown of the search; without a known
  member, every arc in scope is `unknown`. This is the Kleene conjunction
  of the verdicts of the members, a tested property: the unknown is never
  presumed compatible. `verify_route` and `verify_flow` give
  `not_applied` or `partial` with the bound in their reason (`"... at
  least 3.5 m (B)"`), and `check_inputs` the arcs that fail already.
- The trace of derived values in the requirement table and the
  provenance. `RequirementRow.to_dict` gives each value, retained or
  discarded, the reason it is not applicable (`"not_applicable"`) and its
  `"derivation"`: name, rule, settings, the inputs that fix it, every
  input with its state and its value (each with its own derivation, so
  that a speed selected by a category, the category and the envelope it
  reads show whole), the assumptions, the inputs left out, the
  conversions, the unknown inputs, the bound of a value to be set, and a
  `"summary"` in words: the rule, the value and the member that fixes it
  with its source (`"max of 'width' over G: 3.5 m, fixed by B (Sheet B
  (2), p. 4)"`), the threshold a characteristic crosses, the bound of a
  value to be set and its members without a value, a decision despite
  unknown values, the assumptions, the inputs left out with their
  reasons, the conversions; `to_dict(readable=True)` adds `"shown"` at
  every depth. `Provenance.derivations` records, for each derived value
  used and those it reads in turn, its parameter, subject, derivation,
  rule and the inputs that fix it; the fingerprint of the inputs covers
  every input of every derivation, so that a member that fixes no value
  still changes it.

### Changed

- `Value` gains two fields after the others, `not_applicable` and
  `derivation`; a value is built as before. `Value.to_be_set` is false for
  a value not applicable. The fingerprints of value sets, resolved values,
  provenance records and every result whose inputs hold values differ from
  those of 0.3.0, the canonical form of a value having two more fields: a
  provenance recorded with 0.3.0 does not replay, as with any other
  version.
- `resolve_values`: a value not applicable and a value to be set of the
  same precedence disagree, and are refused. Migration: declare which one
  prevails by a precedence.
- `check_inputs`: `missing_values` lists the values missing or to be set,
  not those declared not applicable; the reason of a value without one is
  that of `evaluate`.
- `evaluate`: an admissibility requirement whose value is to be set by an
  envelope with a bound, or without any known member, is no longer an
  effect that does not apply: its arcs fail where the bound fails them,
  and are `unknown` elsewhere. `verify_route` and `verify_flow` give it
  `not_applied` or `partial` instead of `not_applicable`, `check_inputs`
  expects `not_applied` or `partial`, and `RouteSearch` and `FlowSearch`
  bar the arcs that fail and apply their policy for the unknown to the
  others, where the requirement was left out. A value to be set that is
  not derived, or derived by another rule (`sum`, `select_by_class`,
  `column_length`), still makes its requirement not applicable.
  Migration: a search that relied on such a requirement being ignored now
  meets its unknown arcs; choose the policy for the unknown that fits
  (`exclude`, `penalize`, `admit_and_count`), or set the value (a sheet
  for the members without one, or `OnUnknown.assume`).
- `RequirementRow.to_dict` gives each value two more keys,
  `"not_applicable"` and `"derivation"` (`None` for a value that is not
  derived), and `Provenance` a last field, `derivations`, empty by
  default. Migration: a comparison of a whole entry of the table, or of a
  provenance built field by field, takes them into account.
- The tables of the requirement model (`ValueSet.values`, `Rulebook.title`,
  `Parameter.aliases`, the mappings of `Requirement`, `ResolvedValues`) are
  frozen mappings (`FrozenMap`) instead of `types.MappingProxyType`: still
  read-only, they pickle and copy, so that value sets, requirement sets and
  resolved values can leave a worker process; rulebooks, parameters and
  requirements hash. Migration: a test
  `isinstance(x, types.MappingProxyType)` becomes
  `isinstance(x, collections.abc.Mapping)`.

## [0.3.0] - 2026-11-28

A common result model. Every method of protee returns a result built on
`protee.results.ResultCore`: a status (`optimal`, `feasible`,
`infeasible`, `unbounded`, `limit`), the certificate the status calls
for, the guarantee of the method, deterministic work counters, the
version and a fingerprint of the inputs. Each module lists its methods,
with their problem and guarantee, through `methods()`, and a conformity
suite runs every method of every registry. Conventions in
[docs/results.md](docs/results.md).

The API of 0.2 changes where a negative answer had no status: a missing
route is a result of status `infeasible` with its certificate instead of
`None`, `bellman_ford` always returns `ShortestPaths`, `k_shortest_paths`
and `replacement_paths` return iterable results, `check_feasibility`
takes its method explicitly, and the result types take keyword arguments
only. Each change comes with its migration below.

### Added

- The concept DOI of protee on Zenodo, `10.5281/zenodo.24619907`, which
  stands for all its versions: in `CITATION.cff`, and as a badge in the
  README.
- `protee.results`, the result model shared by every method: `Status`
  gains `feasible` and `limit`; `ResultCore` carries the status, the
  certificate it calls for, the guarantee of the method, a bound and its
  gap, the parameters, the counters, the version and the fingerprint of
  the inputs (`inputs`); `Guarantee` and `MethodInfo` describe the methods
  of a registry. A result is a value: it compares, hashes, pickles (a
  worker process can return it, its fingerprint kept) and copies; its
  `parameters` and `counters` are immutable mappings. A method reports the
  same counters whatever the outcome, at zero for the work it did not do.
  Equal fingerprints mean the same question on the same inputs (same
  status and, for an exact method, the same optimal value), not always the
  same solution: a warm-started problem may return another optimum, and
  neither the callables of conflicts and relaxations nor the decimal
  context of decimal weights are fingerprinted.
  Conventions in [docs/results.md](docs/results.md).
- `protee.constraints.fingerprint` reads fractions and decimals, each
  exactly: a decimal by its sign, digits and exponent, whatever the
  decimal context of the thread.
- `FlowResult` is built on `ResultCore`: it gains `guarantee`,
  `parameters` (the effective options, defaults included) and `inputs`.
  `MethodInfo` gains `problem` and `guarantee`.
- `protee.flow.methods(problem=None)` lists every method of `protee.flow`
  with its problem and guarantee: `min_cost_flow` (`network_simplex`,
  `cycle_canceling`, `successive_shortest_paths`), `max_flow` and
  `feasibility` (`dinic`, `edmonds_karp`), `disjoint_paths` (the three
  minimum cost flow methods), and the diagnostics `flow_ranges`,
  `unattainable_bounds` and `optimum_uniqueness`, each a method of its own;
  all are exact.
- `MaxFlowResult`, `Feasibility`, `DisjointPaths`, `FlowRanges`,
  `UnattainableBounds` and `Uniqueness` are built on `ResultCore`. An
  infeasible feasibility check, disjoint paths problem or flow range
  carries its violated cut; flow ranges at an unbounded optimum carry the
  improving cycle.
- `protee.results.SeparatingCut`, the certificate that no path leads from
  the sources to a target: the nodes reached through admitted arcs and the
  arcs that leave them, all barred; and `CrossedCuts`, two nodes neither of
  which reaches the other, for waypoints that no order can visit.
- `protee.paths.methods()` and `protee.routes.methods()`, the registries of
  the shortest path and route methods with their problem, guarantee,
  complexity and reference; `methods(problem)` selects one problem.
- The results of `protee.paths` and `protee.routes` are built on
  `ResultCore`, with deterministic counters (settled nodes and scanned arcs
  for Dijkstra, passes for Bellman-Ford, Dijkstra runs, candidate paths for
  Yen, states of the dynamic programming over waypoints).
- `KShortestPaths` and `ReplacementPaths`, returned by `k_shortest_paths`
  and `replacement_paths`; they iterate, index and measure like the
  sequences they replace.
- `protee.constraints.verify_route` accepts a route result
  (`WaypointRoute`, `ReliableRoute`, `RouteSearchResult`).
- `protee.constraints.methods(problem=None)`: the methods of
  `minimal_conflict`, `minimal_relaxation` and `relaxation_by_tiers`, each
  with its guarantee (`enumeration` exact, minimum cardinality;
  `deletion_filter` irreducible; `greedy` no relaxed requirement can be
  restored), its complexity in feasibility tests and its reference.
- `Conflict`, `Relaxation` and `TieredRelaxation` are built on
  `ResultCore`: status `optimal` with `enumeration`, `feasible` with
  `deletion_filter` or `greedy`; their fingerprint covers the problem, the
  method, the identifiers in their order and the tiers (the feasibility
  test and the cost function, callables, are not part of it).
- `protee.results.InfeasibleSubset`: when no tier is feasible,
  `relax_by_tiers` returns the status `infeasible` with, as certificate,
  the requirements that no tier allows to relax, tested infeasible
  together; `level` stays `None`. `FlowSearch.solve` gives it too (see
  Changed).
- `RouteSearchResult`, returned by `RouteSearch.solve`: status `optimal`
  with the route, or `infeasible` with the `SeparatingCut` of the arcs the
  active requirements bar; the method, guarantee and counters of the
  shortest path method run, and the active requirements.

### Changed

- `FlowResult` and `MethodInfo` take keyword arguments only.
- `protee.flow.methods()` lists the methods of every problem of the
  module: list the minimum cost flow methods with
  `methods("min_cost_flow")` (they still come first).
- `MaxFlowResult`, `Feasibility`, `DisjointPaths`, `FlowRanges`,
  `UnattainableBounds` and `Uniqueness` take keyword arguments only.
- `Feasibility.feasible` and `Feasibility.cut` are read-only properties
  derived from `status` and `certificate`; `Uniqueness.unique` is a
  read-only property, true when `direction` is `None`.
- The diagnostics are named after themselves: `FlowRanges.method` is
  `"flow_ranges"` (`"unattainable_bounds"`, `"optimum_uniqueness"` for the
  others), and the minimum cost flow method they run is the parameter
  `method`, the keyword argument of the call (which
  `flow_ranges(problem, **result.parameters)` replays): read
  `result.parameters["method"]` instead of `result.method`. The registry
  lists `method` (and `at_optimum`) as their options.
- Counters: `DisjointPaths` adds `max_flow_augmentations` and
  `max_flow_phases`; `FlowRanges` adds `solves`, `feasibility_augmentations`
  and `feasibility_phases` (zero at the optimum); `UnattainableBounds`
  (those of its ranges) and `Uniqueness` (`residual_edges`, `components`)
  gain counters. A minimum cost flow found unbounded, or infeasible before
  its method runs, reports the counters of the method at zero instead of
  none.
- `check_feasibility` takes its `method` without default (objective 2 of
  AGENTS.md). Migration: `check_feasibility(p)` becomes
  `check_feasibility(p, method="dinic")`. `Prepared.feasibility()` keeps
  its signature and runs Dinic.
- `FlowSearch.solve` returns a `FlowResult` instead of `None` when the
  bounds of the active requirements conflict on an arc: status
  `infeasible`, the counters of the method at zero, and as certificate an
  `InfeasibleSubset` of the active requirements that bound or bar those
  arcs, which conflict on their own. Migration: replace `result is None`
  with `result.status is Status.INFEASIBLE`. `problem_for` still returns
  `None` in that case.
- `disjoint_paths`, `flow_ranges` and `unattainable_bounds` refuse an
  unknown flow method before any computation.
- The fingerprint of the inputs of a result also covers its type: a method
  name may serve several problems.
- A list or tuple of floats only, or of 64-bit integers only, NumPy's
  included, is fingerprinted by its bytes in little-endian order: the first
  fingerprint of a Dijkstra on 577 019 arcs costs about 13 % of the
  computation, instead of more than the computation itself. The
  `TypeError` of an input without a canonical form lists the supported
  types (lists and tuples, not other sequences).
- The shortest path and route functions refuse, with a `ValueError`,
  weights whose absolute sum over the arcs not excluded is beyond the float
  range when one of them is not an int: a float sum along a path could
  overflow. `waypoint_route` refuses them when `k + 1` times that sum is
  beyond it, and `bellman_ford` when `n m` times the largest absolute
  weight is (the walks it sums on the way to a negative cycle), also for
  int weights with a positive `tolerance`, which compares the distances as
  floats. Python int weights otherwise sum and compare exactly, whatever
  their size.
- `FlowProblem` refuses, with a `ValueError`, float costs whose absolute
  sum is beyond the float range, and an int cost beyond it among float
  costs. Int costs alone are exact, whatever their size, in every method
  and in `verify_flow`.
- The cost of the route of `RouteSearch.solve` adds the weights of its
  arcs from left to right, as the search does, instead of their
  `math.fsum`: it is the distance of the target.
- `bellman_ford` always returns `ShortestPaths`: when a negative cycle is
  reachable from the sources, the status is `unbounded`, the certificate is
  the cycle, the nodes that negative cycles reach are at `-inf` and the
  others keep their exact distance. Migration: replace
  `isinstance(r, NegativeCycle)` with `r.status is Status.UNBOUNDED`, and
  read the cycle from `r.certificate`.
- `waypoint_route` returns a result of status `infeasible` instead of
  `None` when no route exists, with a `SeparatingCut` (or `CrossedCuts` in
  free order); its `order`, `legs`, `arcs` and `cost` are then `None`.
  Migration: replace `route is None` with
  `route.status is Status.INFEASIBLE`.
- `most_reliable_path` returns a result of status `infeasible` instead of
  `None` when the target cannot be reached, with a `SeparatingCut`; its
  `arcs` and `probability` are then `None`. Migration: replace
  `route is None` with `route.status is Status.INFEASIBLE`.
- `k_shortest_paths` returns `KShortestPaths` instead of a list; without
  any path, its status is `infeasible`, with a `SeparatingCut`. Migration:
  loops and indexing are unchanged; compare `len(r)` instead of `r == []`,
  and use `r.routes` or `list(r)` for a sequence.
- `replacement_paths` returns `ReplacementPaths` instead of a tuple.
  Migration: loops and indexing are unchanged; use `r.replacements` for the
  tuple.
- `ShortestPaths`, `LexicographicPaths`, `WaypointRoute` and
  `ReliableRoute` take keyword arguments only, with the fields of
  `ResultCore`.
- The shortest path and route functions refuse a target, start, end,
  waypoint or path arc that is not in the graph (`ValueError`), where they
  used to run on or fail later with an `IndexError`.
- `Conflict`, `Relaxation` and `TieredRelaxation` take keyword arguments
  only; their `evaluations` becomes the counter
  `counters["feasibility_tests"]`, and stays as a read-only property.
- `RouteSearch.solve` returns a `RouteSearchResult` instead of
  `Route | None`. Migration: replace `route is None` with
  `route.status is Status.INFEASIBLE`; `arcs` and `cost` read as before.
  `RouteSearch.methods()` returns the `MethodInfo` of its two methods
  instead of their names.
- `provenance()` takes the method, parameters, counters and version from a
  result built on `ResultCore`; `method` and `parameters` become optional
  for such a result, and the call style of 0.2 keeps working. Its `inputs`
  now also covers the fingerprint of the result's own inputs. A `method`
  other than the result's raises `ValueError`.
- An unknown method of `minimal_conflict`, `minimal_relaxation` and
  `relax_by_tiers` raises `ValueError` naming the problem and its methods.
- `Status`, `InfeasibleCut`, `NegativeCycle` and `MethodInfo` live in
  `protee.results`; `protee.flow` and `protee.paths` still export them
  (the same objects).
- `protee.constraints.fingerprint` hashes a graph by the fingerprint of
  its structure, computed once per graph: fingerprints differ from those of
  0.2.0.

### Fixed

- Finite float weights whose sum along a path overflowed to `inf`:
  `dijkstra` reported a reachable node out of reach, `k_shortest_paths`,
  `replacement_paths` and `waypoint_route` missed routes that exist, and
  `bellman_ford` could miss a negative cycle. Such weights are refused
  (see Changed).
- An int weight or cost beyond the float range raised an `OverflowError`
  (shortest paths, routes, `FlowProblem`): ints now sum exactly, whatever
  their size, and a `ValueError` refuses one only where floats are summed
  or compared (see Changed).
- `bellman_ford` compared int distances as floats, rounded beyond `2**53`,
  and could miss a shorter path; `verify_flow` converted int costs to
  floats, and could declare optimal a flow that a cycle improves. Both
  are exact on ints.
- `bellman_ford` refuses a negative or non-finite `tolerance`, which gave
  a false negative cycle (an arc `-1`, of weight zero) or lost reachable
  nodes.
- `k_shortest_paths` could list a route before a cheaper one: the first
  cost added the weights from left to right, as Dijkstra does, the next
  ones with `sum()`, which compensates the rounding of floats since Python
  3.12. Every route cost now adds its weights from left to right, and the
  costs do not decrease. `WaypointRoute.cost` adds its legs from left to
  right too, as the free order compares them.
- Fingerprints: a NumPy `float64` depended on NumPy's print options, and
  a list of them did not fingerprint like the list of the same floats;
  `numpy.longdouble` raised a `RecursionError` instead of a `TypeError`;
  a NumPy `datetime64` or `timedelta64` in nanoseconds fingerprinted like
  the int of its count, and in other units raised a `TypeError`. Dates and
  durations now count by their dtype, unit included, and their count of
  units.
- Docstrings: the tie rules of `k_shortest_paths` and of `waypoint_route`
  in free order are stated as implemented (the order of the routes does
  not change); `ShortestPaths` says that with `bellman_ford` a source can
  get a negative distance and a predecessor.
- The registry complexity of successive shortest paths (minimum cost
  flow) states the bound of the binary heap the implementation uses,
  `O((n + m) log n)` per Dijkstra run, instead of that of a Fibonacci
  heap.

## [0.2.0] - 2026-11-28

Rendering for the producers of node-link documents. The format
`protee-node-link/0` gains two optional keys, `mappings` and `locator`.
`protee.viz` gains:

- the contraction of the edges of a type, the matrix of a document (N²
  chart) and colour by vocabulary;
- light and dark themes, layout attributes, a legend at the left showing
  only the values present, and a footer image;
- orthogonal edges laid out in a separate process;
- a richer exploration page: tooltips on edges, formulas built from data,
  and the matrix coordinated with the graph.

Links and texts drawn in SVG are read as a browser reads them. The
version also brings a document on security, supply chain and compliance.

### Added

- Two optional keys in the `protee-node-link/0` format, which stays `/0`:
  `mappings` on a declared value of `graph.vocabulary`, its
  correspondences to terms of other vocabularies (as in SSSOM:
  `predicate`, `object`, optional `justification`), and `locator` on an
  edge, the place in the target that the edge points to (an equation
  number, an article, a clause). `protee.io.check_node_link` and the JSON
  Schema check them; the format documentation advises producers to prefix
  the keys that only they read.
- `protee.viz.contract`: the two ends of each edge of a type shown as one
  node, which keeps the attributes of the chosen end, completed by the
  other's, and the trace of the nodes it stands for; it undoes a split of
  nodes.
- `protee.viz.render_matrix_svg`: the matrix of a document (N² chart, or
  design structure matrix), written in SVG without Graphviz: the nodes
  ordered on the diagonal, a row gives and a column reads, the feedbacks
  below the diagonal, the inputs counted, ties and loops framed.
- Themes: `protee.viz.Theme`, with `LIGHT` and `DARK`, sets the background,
  the ink and a muted grey of `to_dot`, `render_svg`, `render_legend_svg`
  and `render_matrix_svg`.
- `attributes` of `to_dot`, `render_svg` and `render_legend_svg`: Graphviz
  attributes of the graph (layout only: `splines`, `ranksep`, `nodesep`,
  `pad`) and of all nodes and all edges, the legend included.
- Legend options: `legend="below-left"`, and `legend_values="present"` (in
  `render_legend_svg`, `values="present"`) for only the values that the
  document carries; a value with `mappings` lists them in its tooltip.
- A footer for `render_svg`: a PNG or SVG image, given as bytes, embedded
  under the figure at the right of the legend, at the height of the legend
  or at `footer_height` points.
- `protee.viz.mark_vocabularies`: each node with an `iri` marked with the
  vocabulary of that IRI (a declared prefix, or its authority), declared
  so that the default styles fill the nodes by vocabulary and the legend
  lists the vocabularies.
- Tooltips: `tooltip=` of `to_dot`, `render_svg` and `render_html` adds
  attributes to the tooltips of nodes and edges; an edge shows its
  `locator`.
- The exploration page (`render_html`) gains `attributes`, `theme`,
  `legend_values` and a `footer` image; tooltips on edges; formulas drawn
  from a MathML tree written as data (`math=`), built element by element
  from a closed list, never from markup; the matrix under the graph
  (`matrix=True`), coordinated with it; and groups by any node attribute
  (`group_by`).
- Orthogonal edges (`splines="ortho"`, in any case) are laid out in a
  child process of the same Python: when Graphviz stops in their routing,
  or the child cannot start, `render_svg` raises a `RuntimeError` instead
  of stopping the caller's process.
- `docs/security-and-compliance.md`: how protee runs, is developed and
  published, what it ships and under which licences, the regulatory
  landmarks, the known limits and a checklist, for those who assess its
  use on a network without Internet access.

### Changed

- The licence expression of the distribution declares the Licence Ouverte
  2.0 of the embedded value set (`BSD-3-Clause AND MIT AND etalab-2.0`),
  credited in its notice.
- A kind of element other than `node` or `edge` in `styles` raises a
  `ValueError`; it was ignored.
- `render_html` accepts any node attribute as `group_by`; an unknown one
  raised a `ValueError`.
- A text that XML cannot carry (a control character, half of a surrogate
  pair) in a label, a tooltip or a link raises a `ValueError` in `to_dot`:
  the SVG would not open.
- `protee.viz.CONTAINS` and `MEMBERS` name the nodes of the original
  document that a node stands for: the members of a group, and now the
  ends of contracted edges.

### Fixed

- The text on a filled node is black or white, whichever contrasts more
  with the fill (WCAG 2): it was white on vermilion, below a ratio of
  4.5:1.
- A node link written with a character reference (`javascript&#58;…`)
  reached the SVG, where the reader decodes it into a script link: links
  are checked as a browser reads them, and every `&` of a text is written
  `&amp;` in the DOT text, so that the SVG shows the text as given.
- A link to another host without a scheme (`//host`, `\\host`) is
  dropped: a page or figure opened from a file read it as `file://host`.
- The tooltips of the exploration page keep their line breaks.
- `collapse`: the values `true` and `1` make two groups.
- The identifiers of a legend drawn below, and the gradients that Graphviz
  numbers, are rewritten in the attributes of the SVG only, never in a
  label.

## [0.1.0] - 2026-11-22

First version. Graph and flow algorithms whose methods are named and
chosen by the caller, share one result (status, solution, certificates,
deterministic counters) and are tested against independent oracles;
requirements turned into traceable constraints on graphs, from their
source to a verified result and its provenance, on both reference
applications (life-cycle profiles, route planning); a node-link exchange
format, `protee-node-link/0`, with its JSON Schema, drawn in SVG and in a
page to explore offline with the optional extra `viz`.

### Added

- Project skeleton: the `protee` package (typed, version read from the
  installed distribution), Python 3.12 or later, BSD-3-Clause.
- Rules shared by contributors and coding agents (`AGENTS.md`), the
  contributing guide in English and French, and the security policy.
- Local checks (pre-commit hooks: formatting, lint, typing, tests,
  secrets, anonymity, image metadata, hidden characters and local-only
  files), replayed by CI on Ubuntu and Windows with Python 3.12, 3.13
  and 3.14, with an 80 % branch coverage floor.
- Release workflow: build checked, provenance and SBOM attested,
  publication through Trusted Publishing; the release procedure is in
  the contributing guide, and CI checks that `uv.lock` matches
  `pyproject.toml`.
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
  platform). Lower bounds: NumPy 2.3.2 and SciPy 1.16.1 up to Python
  3.14, the first releases with wheels for 3.14, kept for 3.12 and 3.13,
  whose first releases with wheels are past the support window of SPEC 0;
  NumPy 2.5.2 and SciPy 1.18.1 on Python 3.15. `import protee` does not
  import them.
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
- Node-link exchange format `protee-node-link/0` (`protee.io`), for
  typed graphs shared with other projects: a `graph` block with the
  format, the producer, an optional label, description and language tag,
  prefixes (an IRI, or null) and a declared vocabulary (the values of
  `type`, `status`, `role`… for nodes or for edges, a value used on both
  declared once for each); opaque node identifiers (an IRI is
  allowed) with an optional `iri`; integer edge keys. The format is
  written by `to_node_link` and `write_node_link` (with `attributes` and
  `multigraph`), read without loss by `from_node_link`, which keeps the
  `graph` block, the `multigraph` flag, the edge keys and the node
  identifiers (texts or integers, `Table.ids`, written back through the
  `ids` of `to_node_link`) in a read-only `Table`, and checked by
  `check_node_link`, which lists every departure from the format; the
  version of the producer is optional. Writing gives an edge without a key the smallest key
  free between its two nodes, writes no optional null, writes an infinite
  metric `"inf"` or `"-inf"`, refuses the columns that would replace `id`,
  `source` or `target`, and writes strict JSON with LF line ends;
  `read_node_link` refuses `NaN` and `Infinity`, which are not JSON.
- `protee.viz`, drawing of node-link documents, without dependency:
  `select` (the nodes reached from starting nodes up to a depth, filtered
  by type, family or metric, their neighbours outside the selection marked
  under `SELECTION`, drawn with a grey border and the label in italics,
  their own line kept, and the neighbours not shown counted), `collapse` (one node per family)
  and `to_dot` (Graphviz DOT text, with default styles drawn from the
  declared vocabulary and told apart without colours up to a few values
  of each attribute, a style table given
  by the caller, `order_by` for a numeric attribute, and a legend).
- `protee.viz.condense` (one node per loop: the strongly connected
  components of `protee.structure`) and `protee.viz.reduce` (the
  transitive reduction of one relation), without dependency.
- `protee.viz.render_html`: a page to explore a document, which opens
  offline: the layout and styles of `render_svg`, groups (families or
  loops) collapsed and expanded, filters by declared value and by family,
  a search in the labels, tooltips (description, `iri`, `url`), links that
  open no script, and the legend of `render_legend_svg`. It embeds
  cytoscape.js 3.35.0 and cytoscape-expand-collapse 4.1.1, under the MIT
  licence (`src/protee/_assets/NOTICE.md`); the distribution's licence
  expression is `BSD-3-Clause AND MIT`.
- Default drawing styles: no yellow lines, and a symmetric relation draws
  its head at both ends, so that symmetric relations are told apart
  without colours.
- `protee.viz.render_svg`: SVG drawing laid out by Graphviz, with the
  optional extra `viz` (pygraphviz, whose wheels bundle Graphviz); labels
  stay text in system fonts, links open no script, nothing is fetched,
  and the same document gives the same SVG with the same versions and
  fonts.
- Legend of the drawings: a node value that sets no shape is shown with
  the shape of the nodes that carry it, or as a rounded box when they have
  several or none carries it; `render_svg` takes `legend="right"`, `"below"` (laid out apart
  and drawn under the graph) or `None`; `protee.viz.render_legend_svg`
  draws the legend alone, one column per attribute and per kind of
  element. The labels of the
  edge swatches are set apart from their line.
- Public page of the format `protee-node-link/0`
  (`docs/node-link-format.md`), its JSON Schema (2020-12) shipped in the
  package and returned by `protee.io.node_link_schema()` (the structure
  of a document; `check_node_link` also checks the rules that cross its
  parts; tested against `jsonschema`, a development dependency), and a
  gallery of drawings written by a script
  (`docs/gallery/`). `check_node_link` takes a null optional key as an
  absent one, as the format states, in `graph.prefixes`,
  `graph.vocabulary`, `producer.version` and the `description` and
  `symmetric` of a declared value.
