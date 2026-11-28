# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Registry of :mod:`protee.flow`: every problem, its methods and their
guarantees.

A problem solved by a choice of method lists the methods to choose from:
the minimum cost flow methods, the maximum flow methods, and, for the
problems that reduce to one of them (feasibility, disjoint paths), the
methods they run. A diagnostic of :mod:`protee.flow.diagnostics` is a
method of its own, named after it: the minimum cost flow method it runs is
one of its parameters, ``method``, the keyword argument of the call.

The options of a method are the keyword arguments its function accepts,
and the names under which its results record them.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from protee.results import Guarantee, GuaranteeKind, MethodInfo


def _by_name(*infos: MethodInfo) -> Mapping[str, MethodInfo]:
    return MappingProxyType({info.name: info for info in infos})


def _exact(statement: str) -> Guarantee:
    return Guarantee(GuaranteeKind.EXACT, statement)


_OPTIMAL_FLOW = _exact("optimal flow and optimal potentials")
_MAX_FLOW = _exact("maximum flow, with a minimum cut")
_FEASIBILITY = _exact("a feasible flow, or a violated cut (Gale, Hoffman)")
_DISJOINT = _exact(
    "k disjoint paths of minimum total cost, or a cut of capacity below k (Menger)"
)
_AMO = "Ahuja, Magnanti, Orlin, Network Flows (1993)"

MIN_COST_FLOW: Mapping[str, MethodInfo] = _by_name(
    MethodInfo(
        name="network_simplex",
        problem="min_cost_flow",
        summary="Primal network simplex, strongly feasible trees (Cunningham), big-M start.",
        guarantee=_OPTIMAL_FLOW,
        complexity="finite (anti-cycling); pseudo-polynomial bounds in practice",
        reference=f"{_AMO}, ch. 11; Cunningham (1976)",
        warm_start=True,
        options=("pivot_rule",),
    ),
    MethodInfo(
        name="cycle_canceling",
        problem="min_cost_flow",
        summary="Feasible flow by maximum flow, then cancel negative residual cycles (Bellman-Ford).",
        guarantee=_OPTIMAL_FLOW,
        complexity="O(n m^2 C U)",
        reference="Klein (1967); Ahuja, Magnanti, Orlin (1993), section 9.6",
    ),
    MethodInfo(
        name="successive_shortest_paths",
        problem="min_cost_flow",
        summary="Augment along shortest paths with node potentials (Dijkstra on reduced costs).",
        guarantee=_OPTIMAL_FLOW,
        complexity=(
            "O(U (n + m) log n), U the total supply after saturation: at "
            "most U + 1 Dijkstra runs with a binary heap"
        ),
        reference="Edmonds, Karp (1972); Tomizawa (1971); Ahuja, Magnanti, Orlin (1993), section 9.7",
    ),
)

MAX_FLOW: Mapping[str, MethodInfo] = _by_name(
    MethodInfo(
        name="dinic",
        problem="max_flow",
        summary="Blocking flows on the level graph of the residual network.",
        guarantee=_MAX_FLOW,
        complexity="O(n^2 m)",
        reference=f"Dinic (1970); {_AMO}, ch. 7",
    ),
    MethodInfo(
        name="edmonds_karp",
        problem="max_flow",
        summary="Augment along shortest paths of the residual network (breadth-first search).",
        guarantee=_MAX_FLOW,
        complexity="O(n m^2)",
        reference=f"Edmonds, Karp (1972); {_AMO}, ch. 7",
    ),
)

FEASIBILITY: Mapping[str, MethodInfo] = _by_name(
    MethodInfo(
        name="dinic",
        problem="feasibility",
        summary=(
            "Lower bounds removed, supplies routed from a super-source to a "
            "super-sink by Dinic's maximum flow; the source side of a minimum "
            "cut is a violated cut."
        ),
        guarantee=_FEASIBILITY,
        complexity="O(n^2 m): one maximum flow on n + 2 nodes",
        reference=f"Gale (1957); Hoffman (1960); {_AMO}, ch. 6 (flows with lower bounds)",
    ),
    MethodInfo(
        name="edmonds_karp",
        problem="feasibility",
        summary=(
            "Lower bounds removed, supplies routed from a super-source to a "
            "super-sink by Edmonds-Karp's maximum flow; the source side of a "
            "minimum cut is a violated cut."
        ),
        guarantee=_FEASIBILITY,
        complexity="O(n m^2): one maximum flow on n + 2 nodes",
        reference=f"Gale (1957); Hoffman (1960); {_AMO}, ch. 6 (flows with lower bounds)",
    ),
)

_SUURBALLE = "Suurballe (1974); Suurballe, Tarjan (1984); Menger (1927)"
_DISJOINT_SUMMARY = (
    "Minimum cost flow of value k with unit capacities, nodes split for "
    "node-disjoint paths (Suurballe's problem), solved by {}; "
    "Dinic's maximum flow counts the disjoint paths (Menger)."
)

DISJOINT_PATHS: Mapping[str, MethodInfo] = _by_name(
    MethodInfo(
        name="network_simplex",
        problem="disjoint_paths",
        summary=_DISJOINT_SUMMARY.format("the network simplex"),
        guarantee=_DISJOINT,
        complexity=(
            "that of network_simplex on n nodes and m arcs "
            "(2n and m + n for node-disjoint paths), plus O(n^2 m)"
        ),
        reference=_SUURBALLE,
        options=("disjoint",),
    ),
    MethodInfo(
        name="cycle_canceling",
        problem="disjoint_paths",
        summary=_DISJOINT_SUMMARY.format("cycle canceling"),
        guarantee=_DISJOINT,
        complexity="O(n m^2 C) with unit capacities, plus O(n^2 m)",
        reference=_SUURBALLE,
        options=("disjoint",),
    ),
    MethodInfo(
        name="successive_shortest_paths",
        problem="disjoint_paths",
        summary=_DISJOINT_SUMMARY.format("successive shortest paths"),
        guarantee=_DISJOINT,
        complexity=(
            "O(k (n + m) log n): k augmentations of one unit, each a Dijkstra "
            "run with a binary heap, plus O(n^2 m)"
        ),
        reference=_SUURBALLE,
        options=("disjoint",),
    ),
)

FLOW_RANGES = MethodInfo(
    name="flow_ranges",
    problem="flow_ranges",
    summary=(
        "Least and greatest flow of each arc: two linear programs per arc on "
        "one prepared problem, solved by the minimum cost flow method given "
        "as method; at the optimum, over the optimal face given by "
        "complementary slackness."
    ),
    guarantee=_exact(
        "least and greatest flow of each arc, over the feasible or the optimal flows"
    ),
    complexity=(
        "2m solves of the minimum cost flow method (2m + 1 at the optimum), "
        "with a warm start for the network simplex"
    ),
    reference=f"{_AMO}, ch. 9 (optimality conditions)",
    options=("method", "at_optimum"),
)

UNATTAINABLE_BOUNDS = MethodInfo(
    name="unattainable_bounds",
    problem="unattainable_bounds",
    summary=(
        "Bounds that no feasible flow reaches, read from the flow ranges over "
        "the feasible flows."
    ),
    guarantee=_exact("every lower or upper bound that no feasible flow reaches"),
    complexity=(
        "that of flow_ranges over the feasible flows: 2m solves of the "
        "minimum cost flow method"
    ),
    reference=f"{_AMO}, ch. 9 (optimality conditions)",
    options=("method",),
)

OPTIMUM_UNIQUENESS = MethodInfo(
    name="optimum_uniqueness",
    problem="optimum_uniqueness",
    summary=(
        "Residual directions of zero reduced cost: the optimum is unique when, "
        "in each strongly connected component, every arc goes both ways and "
        "the arcs form a tree."
    ),
    guarantee=_exact(
        "whether the optimal flow is unique, and a direction towards another "
        "optimal flow when it is not (exact for integer costs)"
    ),
    complexity="O(n + m log m)",
    reference=f"{_AMO}, ch. 9 (reduced cost optimality); Tarjan (1972)",
)

_REGISTRY: tuple[MethodInfo, ...] = (
    *MIN_COST_FLOW.values(),
    *MAX_FLOW.values(),
    *FEASIBILITY.values(),
    *DISJOINT_PATHS.values(),
    FLOW_RANGES,
    UNATTAINABLE_BOUNDS,
    OPTIMUM_UNIQUENESS,
)

PROBLEMS: tuple[str, ...] = tuple(dict.fromkeys(info.problem for info in _REGISTRY))


def methods(problem: str | None = None) -> tuple[MethodInfo, ...]:
    """The methods of :mod:`protee.flow`, in a fixed order.

    Parameters
    ----------
    problem : str, optional
        Only the methods of this problem: ``"min_cost_flow"`` (:func:`solve`
        and :func:`prepare`), ``"max_flow"`` (:func:`max_flow`),
        ``"feasibility"`` (:func:`check_feasibility`), ``"disjoint_paths"``
        (:func:`disjoint_paths`), or a diagnostic of
        :mod:`protee.flow.diagnostics`: ``"flow_ranges"``,
        ``"unattainable_bounds"``, ``"optimum_uniqueness"``. Every method of
        every problem by default.

    Returns
    -------
    tuple of MethodInfo
        Each with its problem and its guarantee; the minimum cost flow
        methods come first.

    Raises
    ------
    ValueError
        If the problem is unknown.

    Examples
    --------
    >>> [info.name for info in methods("max_flow")]
    ['dinic', 'edmonds_karp']
    """
    if problem is None:
        return _REGISTRY
    if problem not in PROBLEMS:
        raise ValueError(
            f"unknown flow problem {problem!r}; choose among {list(PROBLEMS)}"
        )
    return tuple(info for info in _REGISTRY if info.problem == problem)


def min_cost_flow_method(name: str) -> MethodInfo:
    """The minimum cost flow method ``name``.

    Raises
    ------
    ValueError
        If the method is unknown.
    """
    if name not in MIN_COST_FLOW:
        raise ValueError(
            f"unknown flow method {name!r}; choose among {sorted(MIN_COST_FLOW)}"
        )
    return MIN_COST_FLOW[name]
