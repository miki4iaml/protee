# The common result model

Every method of protee returns a result built on
`protee.results.ResultCore`. Whatever the problem, a result says what was
found, how far it can be trusted, and how to replay it. This page states
the conventions; the docstrings give the fields of each result type.

## Fields shared by every result

| Field | Meaning |
|---|---|
| `status` | `optimal`, `feasible`, `infeasible`, `unbounded` or `limit` (below) |
| `method` | the name of the method, as its registry lists it |
| `guarantee` | what the method promises (below), copied from its registry |
| `parameters` | the options of the method, frozen; the defaults are included |
| `counters` | deterministic work counters: the same on every run and every machine |
| `version` | the version of protee that produced the result |
| `bound`, `gap` | a bound on the optimal value and the absolute gap to it, when the method computes one |
| `certificate` | why there is no solution, when the status is `infeasible` or `unbounded` |
| `inputs` | SHA-256 fingerprint of the inputs, the method and its parameters, and the type of the result |

## Statuses and the certificates they call for

| Status | Meaning | Certificate |
|---|---|---|
| `optimal` | an optimum is proven, or a problem without objective is answered exactly | dual values when the problem has some (potentials, distances); otherwise the exactness of the method |
| `feasible` | a feasible solution whose optimality is not proven | a bound and its gap when the method is `bounded`; otherwise the property the method guarantees |
| `infeasible` | no solution exists | required: for a flow, a violated cut (`InfeasibleCut`); for a path, the nodes reached from the sources and the arcs leaving them, all barred (`SeparatingCut`), or two such cuts when no order visits two waypoints (`CrossedCuts`); for requirements that no declared tier can relax enough, the subset tested infeasible together (`InfeasibleSubset`) |
| `unbounded` | the objective is unbounded | required: an improving cycle (`NegativeCycle`); the shortest distances of the nodes it reaches are `-inf` |
| `limit` | a work limit was reached, measured by a counter, never by the clock | the best solution found, if any, with its bound when it is known |

A result that breaks these rules cannot be built: `ResultCore` refuses an
`infeasible` or `unbounded` result without a certificate, and a `feasible`
result of a `bounded` method without its bound and gap.

## Guarantees

Each method of a registry (`methods()` of a module) declares its
guarantee: a kind and a short statement.

| Kind | Promise |
|---|---|
| `exact` | an `optimal` result is optimal, or exhaustive |
| `bounded` | a `feasible` result comes with a bound and its gap |
| `property` | the result has the stated property (for instance, an irreducible conflict), without a computable bound |
| `none` | nothing beyond feasibility |

`gap` is absolute: the distance between the value of the result and
`bound`. A relative gap, where a result type offers one, is
`gap / max(1, |value|)`; solvers do not all use the same denominator, and
this one stays defined when the value is zero.

## Fingerprint of the inputs

`inputs` is computed at its first reading and kept. The structure of a
graph is hashed once per graph, and kept in it; the metric (bounds, costs,
weights) is hashed with the method, its parameters and the type of the
result, since a method name may serve several problems. Two results with the
same `inputs` and the same `version` come from the same computation: one
can stand for the other. `protee.constraints.provenance` records the full
provenance of a result built from requirements.

## Counters

Counters count the work of a method in its own units. They are integers,
identical on every run: comparisons between methods use them rather than
timings. For instance:

| Methods | Counters |
|---|---|
| minimum cost flow | `pivots`, `degenerate_pivots`, `bound_flips` (network simplex); `cycles_canceled`, `bellman_ford_runs`; `augmentations`, `dijkstra_runs` |
| maximum flow, feasibility | `augmentations`, `phases` (Dinic) |
| `dijkstra`, `lexicographic_dijkstra` | `settled_nodes`, `scanned_arcs` |
| `bellman_ford` | `passes` |
| routes | `dijkstra_runs`, `settled_nodes`, `scanned_arcs`; `states` of the dynamic programming over waypoints, `candidates` of Yen |
| flow diagnostics | `solves`, and the counters of the flow method they run |
| conflicts, relaxations, tiers | `feasibility_tests`: the distinct sets of requirements tested |

The docstring of each result type names its counters.

The fingerprint itself is cheap: a sequence of floats only, or of integers
only, is hashed by its bytes in little-endian order. On a graph of 577 019
arcs, the first reading of `inputs` (the structure included) took about
13 % of the time of a Dijkstra in pure Python, the next readings on the
same graph about 5 %; a result that is never asked for its fingerprint
pays nothing.
