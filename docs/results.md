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
| `infeasible` | no solution exists | required: for a flow, a violated cut (`InfeasibleCut`); for a path, the nodes reached from the sources and the arcs leaving them, all barred (`SeparatingCut`), or two such cuts when no order visits two waypoints (`CrossedCuts`); for requirements that no declared tier can relax enough, the subset tested infeasible together, and for a flow search whose active requirements give an arc a lower bound above its upper bound, the requirements that bound or bar such arcs (`InfeasibleSubset`) |
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

`inputs` is computed at its first reading and kept, a pickled result
included. The structure of a graph is hashed once per graph, and kept in
it; the metric (bounds, costs, weights) is hashed with the method, its
parameters and the type of the result, since a method name may serve
several problems. The docstring of each result type lists the inputs its
fingerprint covers. `protee.constraints.provenance` records the full
provenance of a result built from requirements.

What a fingerprint tells:

- **Determinism.** The same call on the same inputs gives the same
  result, counters included, on every machine.
- **Same fingerprint, same question.** Two results with the same `inputs`
  and the same `version` answer the same question on the same inputs: they
  have the same status and, for an exact method, the same optimal value.
- **Not always the same answer.** Their solution and counters may still
  differ after a warm start: a problem prepared once
  (`protee.flow.prepare`) and solved again starts from its previous
  solution and, when several optima exist, may return another one, with
  other counters.
- **Callables are left out.** The feasibility test and the cost function
  of conflicts and relaxations (`minimal_conflict`, `minimal_relaxation`,
  `relax_by_tiers`) are not part of the fingerprint: two calls with
  different tests share it, and their results may differ in anything the
  test decides. Likewise, a route search fingerprints the weights and the
  excluded arcs its active requirements give, not the requirements.
- **The decimal context is left out.** Arithmetic on `decimal.Decimal`
  weights follows the decimal context of the caller's thread (precision,
  rounding), which the fingerprint does not cover: the same inputs under
  two contexts share a fingerprint, and their distances may differ. Such
  a result replays only under the same context.

The fingerprint reads `None`, booleans, strings, numbers (`int`, `float`,
`fractions.Fraction`, `decimal.Decimal`, each exactly, a decimal by its
sign, digits and exponent, whatever the decimal context), enumerations,
mappings, lists and tuples, sets, dataclasses, graphs and NumPy arrays. A
NumPy boolean, integer or float (`float32` included) counts as the Python
number of the same value, alone or in a list: NumPy weights fingerprint
like the list of the same numbers. A NumPy `datetime64` or `timedelta64`
counts by its dtype, unit included, and its number of units, never as a
number. An input of another type (a `range` or another sequence, a
`bytes` key of `replacement_paths`, an instance of an ordinary class, a
`numpy.longdouble`) does not prevent the computation, but reading
`inputs` then raises a `TypeError` that names the type.

A result is a value: it compares by its fields (not by `inputs`), hashes,
pickles (it can be returned by a worker process) and copies; its
`parameters` and `counters` are immutable mappings.

## Counters

Counters count the work of a method in its own units. They are integers,
identical on every run: comparisons between methods use them rather than
timings. A method reports the same counters whatever the outcome: a
counter of work the method did not do is zero (a minimum cost flow found
unbounded before the method runs, or infeasible by the feasibility check
that comes first).

| Methods | Counters |
|---|---|
| minimum cost flow | `pivots`, `degenerate_pivots`, `bound_flips` (network simplex); `cycles_canceled`, `bellman_ford_runs` (cycle canceling); `augmentations`, `dijkstra_runs` (successive shortest paths) |
| maximum flow, feasibility | `augmentations`, `phases` (Dinic) |
| disjoint paths | the counters of the flow method, `max_flow_augmentations`, `max_flow_phases` |
| `dijkstra`, `lexicographic_dijkstra` | `settled_nodes`, `scanned_arcs` |
| `bellman_ford` | `passes` |
| routes | `dijkstra_runs`, `settled_nodes`, `scanned_arcs`; `states` of the dynamic programming over waypoints, `candidates` of Yen |
| `flow_ranges`, `unattainable_bounds` | `solves`, the counters of the flow method they run, `feasibility_augmentations`, `feasibility_phases` |
| `optimum_uniqueness` | `residual_edges`, `components` |
| conflicts, relaxations, tiers | `feasibility_tests`: the distinct sets of requirements tested |

The docstring of each result type names its counters.

The fingerprint itself is cheap: a list or tuple of floats only, or of
integers only (NumPy's included), is hashed by its bytes in little-endian
order. On a graph of 577 019 arcs, the first reading of
`inputs` (the structure included) took about 13 % of the time of a
Dijkstra in pure Python, the next readings on the same graph about 5 %; a
result that is never asked for its fingerprint pays nothing.
