# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Conformity of the flow methods to the common result model.

Every method of ``protee.flow.methods()``, for every problem of the
module, returns a result built on the common model; its certificate is
verified by a computation independent of the method.
"""

from __future__ import annotations

import itertools
from collections import Counter, deque
from collections.abc import Sequence
from typing import Literal

import pytest
from conformity import check_core, check_registry
from hypothesis import example, given, settings
from hypothesis import strategies as st
from oracles import (
    all_flows,
    check_certificate,
    check_cut,
    disjoint_cases,
    networks,
    networkx_oracle,
    problems,
    same_value,
)

from protee.flow import (
    DisjointPaths,
    Feasibility,
    FlowProblem,
    FlowResult,
    InfeasibleCut,
    MaxFlowResult,
    Status,
    check_feasibility,
    disjoint_paths,
    max_flow,
    methods,
    prepare,
    solve,
)
from protee.flow.diagnostics import (
    FlowRanges,
    UnattainableBounds,
    Uniqueness,
    flow_ranges,
    optimum_uniqueness,
    unattainable_bounds,
)
from protee.graph import Digraph
from protee.results import GuaranteeKind

INFOS = {(info.problem, info.name): info for info in methods()}
MIN_COST = [info.name for info in methods("min_cost_flow")]
MAX_FLOW = [info.name for info in methods("max_flow")]
VARIANTS = [
    ("network_simplex", {"pivot_rule": "block_search"}),
    ("network_simplex", {"pivot_rule": "dantzig"}),
    ("cycle_canceling", {}),
    ("successive_shortest_paths", {}),
]
TRIANGLE = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
EXAMPLE = FlowProblem(TRIANGLE, upper=(2, 2, 1), cost=(1, 1, 3), supply=(3, 0, -3))
# Two arc-disjoint paths from 0 to 2, both through node 1.
BOTTLENECK = Digraph.from_arcs(3, [(0, 1), (0, 1), (1, 2), (1, 2)])


def test_registry() -> None:
    check_registry(methods())
    expected = {
        "min_cost_flow": [
            "network_simplex",
            "cycle_canceling",
            "successive_shortest_paths",
        ],
        "max_flow": ["dinic", "edmonds_karp"],
        "feasibility": ["dinic", "edmonds_karp"],
        "disjoint_paths": [
            "network_simplex",
            "cycle_canceling",
            "successive_shortest_paths",
        ],
        "flow_ranges": ["flow_ranges"],
        "unattainable_bounds": ["unattainable_bounds"],
        "optimum_uniqueness": ["optimum_uniqueness"],
    }
    found = {problem: [info.name for info in methods(problem)] for problem in expected}
    assert found == expected
    assert methods() == tuple(info for p in expected for info in methods(p))
    for info in methods():
        assert info.guarantee.kind is GuaranteeKind.EXACT
    with pytest.raises(ValueError, match="unknown flow problem 'shortest_paths'"):
        methods("shortest_paths")


# Minimum cost flow


@pytest.mark.parametrize(("method", "options"), VARIANTS)
@given(problem=problems())
@settings(max_examples=60)
def test_every_method_conforms(
    method: str, options: dict[str, str], problem: FlowProblem
) -> None:
    def run() -> FlowResult:
        return solve(problem, method=method, **options)

    result = solve(problem, method=method, **options)
    check_core(result, INFOS["min_cost_flow", method], run)
    if result.status is Status.OPTIMAL:
        assert result.certificate is None
    else:
        check_certificate(problem, result)


@given(problem=problems())
@settings(max_examples=60)
def test_exact_methods_agree(problem: FlowProblem) -> None:
    results = [solve(problem, method=m, **o) for m, o in VARIANTS]
    first = results[0]
    for other in results[1:]:
        assert other.status is first.status
        if first.status is Status.OPTIMAL:
            assert same_value(other.objective, first.objective)


def test_parameters_are_the_effective_options() -> None:
    default = solve(EXAMPLE, method="network_simplex")
    dantzig = solve(EXAMPLE, method="network_simplex", pivot_rule="dantzig")
    assert dict(default.parameters) == {"pivot_rule": "block_search"}
    assert dict(dantzig.parameters) == {"pivot_rule": "dantzig"}
    assert default.inputs != dantzig.inputs
    assert dict(solve(EXAMPLE, method="cycle_canceling").parameters) == {}


def test_fingerprint_follows_the_inputs() -> None:
    p = EXAMPLE
    same = FlowProblem(
        Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)]),
        upper=[2, 2, 1],
        cost=[1, 1, 3],
        supply=[3, 0, -3],
    )
    base = solve(p, method="cycle_canceling")
    assert solve(same, method="cycle_canceling").inputs == base.inputs
    assert solve(p, method="successive_shortest_paths").inputs != base.inputs
    assert solve(p.with_cost((1, 1, 2)), method="cycle_canceling").inputs != (
        base.inputs
    )
    assert solve(p.with_cost(p.cost, "max"), method="cycle_canceling").inputs != (
        base.inputs
    )


def test_prepared_results_carry_the_costs_they_solved() -> None:
    p = EXAMPLE
    prepared = prepare(p, method="network_simplex")
    first = prepared.solve()
    second = prepared.solve((1, 1, 0))
    assert first.inputs == solve(p, method="network_simplex").inputs
    assert second.inputs == (
        solve(p.with_cost((1, 1, 0)), method="network_simplex").inputs
    )
    assert first.inputs != second.inputs


# Maximum flow


def check_minimum_cut(
    graph: Digraph,
    capacity: Sequence[int | None],
    source: int,
    target: int,
    result: MaxFlowResult,
) -> None:
    """The flow is feasible and the cut has its value: both are optimal
    (max-flow min-cut), recomputed from the graph."""
    balance = [0] * graph.n
    for (u, v), x, c in zip(graph.arcs(), result.flow, capacity, strict=True):
        assert 0 <= x <= (x if c is None else c)
        balance[u] += x
        balance[v] -= x
    assert balance[source] == result.value == -balance[target]
    assert all(balance[v] == 0 for v in range(graph.n) if v not in (source, target))
    side = result.source_side
    assert source in side
    assert target not in side
    leaving = [
        c
        for (u, v), c in zip(graph.arcs(), capacity, strict=True)
        if u in side and v not in side
    ]
    assert None not in leaving
    assert sum(c or 0 for c in leaving) == result.value


@pytest.mark.parametrize("method", MAX_FLOW)
@given(case=networks())
@settings(max_examples=60)
def test_max_flow_conforms(
    method: str, case: tuple[Digraph, list[int | None], int, int]
) -> None:
    graph, capacity, s, t = case
    if s == t:
        return

    def run() -> MaxFlowResult:
        return max_flow(graph, capacity, s, t, method=method)  # type: ignore[arg-type]

    result = run()
    check_core(result, INFOS["max_flow", method], run)
    assert result.status is Status.OPTIMAL
    assert result.certificate is None
    assert dict(result.parameters) == {}
    assert set(result.counters) == {"augmentations", "phases"}
    check_minimum_cut(graph, capacity, s, t, result)


def test_max_flow_fingerprint_and_counters() -> None:
    dinic = max_flow(TRIANGLE, [2, 2, 1], 0, 2, method="dinic")
    again = max_flow(
        Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)]), (2, 2, 1), 0, 2, method="dinic"
    )
    assert again.inputs == dinic.inputs
    karp = max_flow(TRIANGLE, [2, 2, 1], 0, 2, method="edmonds_karp")
    assert karp.inputs != dinic.inputs
    assert max_flow(TRIANGLE, [2, 2, 2], 0, 2, method="dinic").inputs != dinic.inputs
    assert max_flow(TRIANGLE, [2, 2, 1], 0, 1, method="dinic").inputs != dinic.inputs
    assert (dinic.value, karp.value) == (3, 3)
    assert dict(karp.counters) == {"augmentations": 2, "phases": 0}
    assert dinic.counters["phases"] == 2


# Feasibility


@pytest.mark.parametrize("method", MAX_FLOW)
@given(problem=problems())
@settings(max_examples=60)
def test_feasibility_conforms(method: str, problem: FlowProblem) -> None:
    def run() -> Feasibility:
        return check_feasibility(problem, method=method)  # type: ignore[arg-type]

    result = run()
    check_core(result, INFOS["feasibility", method], run)
    assert result.feasible == (result.status is Status.OPTIMAL)
    assert result.cut is result.certificate
    if result.feasible:
        assert result.certificate is None
        assert result.flow is not None
        assert not problem.violations(result.flow)
    else:
        assert result.flow is None
        check_certificate(problem, result)
    zero = problem.with_cost((0,) * problem.graph.m, "min")
    assert (networkx_oracle(zero)[0] == "optimal") == result.feasible


def test_feasibility_fingerprint() -> None:
    dinic = check_feasibility(EXAMPLE, method="dinic")
    assert check_feasibility(EXAMPLE).inputs == dinic.inputs
    assert check_feasibility(EXAMPLE, method="edmonds_karp").inputs != dinic.inputs
    tighter = FlowProblem(TRIANGLE, upper=(1, 1, 1), supply=(3, 0, -3))
    assert check_feasibility(tighter).inputs != dinic.inputs
    assert dinic.inputs != solve(EXAMPLE, method="network_simplex").inputs


# Disjoint paths


def unit_network(
    graph: Digraph, source: int, target: int, k: int, disjoint: str
) -> FlowProblem:
    """The flow problem of ``k`` disjoint paths, as the documentation of
    :class:`DisjointPaths` lays it out: entry ``v`` and exit ``n + v`` of
    each node, arc ``m + v`` between them."""
    n = graph.n
    if disjoint == "arcs":
        arcs, size, s, t = list(graph.arcs()), n, source, target
    else:
        arcs = [(n + u, v) for u, v in graph.arcs()] + [(v, n + v) for v in range(n)]
        size, s, t = 2 * n, n + source, target
    supply = [0] * size
    supply[s], supply[t] = k, -k
    return FlowProblem(
        Digraph.from_arcs(size, arcs), upper=(1,) * len(arcs), supply=supply
    )


def separates(
    graph: Digraph, source: int, target: int, arcs: set[int], nodes: set[int]
) -> bool:
    """Whether removing ``arcs`` and ``nodes`` leaves no path from
    ``source`` to ``target``."""
    seen = {source}
    queue = deque((source,))
    while queue:
        u = queue.popleft()
        for a in graph.out_arcs(u):
            v = graph.heads[a]
            if a not in arcs and v not in nodes and v not in seen:
                seen.add(v)
                queue.append(v)
    return target not in seen


@pytest.mark.parametrize("method", MIN_COST)
@given(case=disjoint_cases(), disjoint=st.sampled_from(["nodes", "arcs"]))
@example(case=(TRIANGLE, [1, 1, 3], 0, 2, 2), disjoint="nodes")
@example(case=(TRIANGLE, [1, 1, 3], 0, 2, 3), disjoint="arcs")
@example(case=(BOTTLENECK, [1, 1, 1, 1], 0, 2, 2), disjoint="arcs")
@example(case=(BOTTLENECK, [1, 1, 1, 1], 0, 2, 2), disjoint="nodes")
@settings(max_examples=60)
def test_disjoint_paths_conform(
    method: str, case: tuple[Digraph, list[int], int, int, int], disjoint: str
) -> None:
    graph, cost, s, t, k = case
    if s == t:
        return

    def run() -> DisjointPaths:
        return disjoint_paths(graph, cost, s, t, k, disjoint=disjoint, method=method)  # type: ignore[arg-type]

    result = run()
    check_core(result, INFOS["disjoint_paths", method], run)
    assert dict(result.parameters) == {"disjoint": disjoint}
    assert result.counters["max_flow_augmentations"] == result.max_paths
    if result.status is Status.OPTIMAL:
        assert result.certificate is None
        assert len(result.paths) == k <= result.max_paths
        used = [a for path in result.paths for a in path]
        assert len(used) == len(set(used))
        if disjoint == "nodes":
            inner = [graph.heads[a] for path in result.paths for a in path[:-1]]
            assert len(inner) == len(set(inner))
        assert result.cost == sum(cost[a] for a in used)
        return
    assert result.status is Status.INFEASIBLE
    assert (result.paths, result.cost) == ((), None)
    cut = result.certificate
    assert isinstance(cut, InfeasibleCut)
    check_cut(unit_network(graph, s, t, k, disjoint), cut)
    assert cut.capacity == result.max_paths < k
    m = graph.m
    assert separates(
        graph,
        s,
        t,
        {a for a in cut.out_arcs if a < m},
        {a - m for a in cut.out_arcs if a >= m},
    )


def test_disjoint_paths_fingerprint() -> None:
    def run(k: int, disjoint: Literal["nodes", "arcs"], method: str) -> DisjointPaths:
        return disjoint_paths(
            TRIANGLE, [1, 1, 3], 0, 2, k, disjoint=disjoint, method=method
        )

    base = run(2, "arcs", "network_simplex")
    assert base.status is Status.OPTIMAL
    assert run(2, "arcs", "network_simplex").inputs == base.inputs
    assert run(1, "arcs", "network_simplex").inputs != base.inputs
    assert run(2, "nodes", "network_simplex").inputs != base.inputs
    assert run(2, "arcs", "cycle_canceling").inputs != base.inputs
    assert set(base.counters) == {
        "pivots",
        "degenerate_pivots",
        "bound_flips",
        "max_flow_augmentations",
        "max_flow_phases",
    }


# Diagnostics


@pytest.mark.parametrize("flow_method", MIN_COST)
@given(problem=problems(max_nodes=4, max_arcs=5), at_optimum=st.booleans())
@settings(max_examples=40)
def test_flow_ranges_conform(
    flow_method: str, problem: FlowProblem, at_optimum: bool
) -> None:
    def run() -> FlowRanges:
        return flow_ranges(problem, method=flow_method, at_optimum=at_optimum)

    result = run()
    check_core(result, INFOS["flow_ranges", "flow_ranges"], run)
    assert dict(result.parameters) == {
        "flow_method": flow_method,
        "at_optimum": at_optimum,
    }
    if result.status is not Status.OPTIMAL:
        assert (result.minimum, result.maximum) == (None, None)
        check_certificate(problem, result)
        return
    assert result.certificate is None
    m = problem.graph.m
    assert result.counters["solves"] == 2 * m + at_optimum
    assert result.minimum is not None
    assert result.maximum is not None
    for a in range(m):
        top = result.maximum[a]
        assert problem.lower[a] <= result.minimum[a]
        assert top is None or result.minimum[a] <= top


@given(problem=problems(max_nodes=4, max_arcs=5), at_optimum=st.booleans())
@settings(max_examples=40)
def test_diagnostics_agree_whatever_the_flow_method(
    problem: FlowProblem, at_optimum: bool
) -> None:
    ranges = [flow_ranges(problem, method=m, at_optimum=at_optimum) for m in MIN_COST]
    bounds = [unattainable_bounds(problem, method=m) for m in MIN_COST]
    for other in ranges[1:]:
        assert other.status is ranges[0].status
        assert (other.minimum, other.maximum) == (ranges[0].minimum, ranges[0].maximum)
    for found in bounds[1:]:
        assert (found.status, found.upper, found.lower) == (
            bounds[0].status,
            bounds[0].upper,
            bounds[0].lower,
        )


@pytest.mark.parametrize("flow_method", MIN_COST)
@given(problem=problems(max_nodes=4, max_arcs=5, finite=True, span=2))
@settings(max_examples=40)
def test_unattainable_bounds_conform(flow_method: str, problem: FlowProblem) -> None:
    def run() -> UnattainableBounds:
        return unattainable_bounds(problem, method=flow_method)

    result = run()
    check_core(result, INFOS["unattainable_bounds", "unattainable_bounds"], run)
    assert dict(result.parameters) == {"flow_method": flow_method}
    assert result.status is result.ranges.status
    assert dict(result.counters) == dict(result.ranges.counters)
    flows = all_flows(problem)
    if result.status is not Status.OPTIMAL:
        assert not flows
        check_certificate(problem, result)
        return
    m = problem.graph.m
    upper = tuple(
        a for a in range(m) if all(x[a] < (problem.upper[a] or 0) for x in flows)
    )
    lower = tuple(a for a in range(m) if all(x[a] > problem.lower[a] for x in flows))
    assert (result.upper, result.lower) == (upper, lower)


@pytest.mark.parametrize("flow_method", MIN_COST)
@given(problem=problems(max_nodes=4, max_arcs=5, finite=True, span=2))
@settings(max_examples=40)
def test_optimum_uniqueness_conforms(flow_method: str, problem: FlowProblem) -> None:
    optimum = solve(problem, method=flow_method)
    if not optimum.optimal:
        return

    def run() -> Uniqueness:
        return optimum_uniqueness(problem, optimum)

    result = run()
    check_core(result, INFOS["optimum_uniqueness", "optimum_uniqueness"], run)
    assert result.status is Status.OPTIMAL
    assert result.certificate is None
    assert dict(result.parameters) == {}
    assert set(result.counters) == {"residual_edges", "components"}
    optimal = [
        x for x in all_flows(problem) if problem.objective(x) == optimum.objective
    ]
    assert result.unique == (len(optimal) == 1)
    assert result.unique == (result.direction is None)
    if result.direction is not None:
        assert optimum.flow is not None
        moved = list(optimum.flow)
        for a, sign in result.direction:
            moved[a] += sign
        assert tuple(moved) in optimal


def test_diagnostics_are_methods_of_their_own() -> None:
    g = Digraph.from_arcs(2, [(0, 1), (1, 0)])
    p = FlowProblem(g, lower=(0, 1), upper=(9, 3))
    ranges = flow_ranges(p, method="cycle_canceling", at_optimum=False)
    bounds = unattainable_bounds(p, method="cycle_canceling")
    optimal_ranges = flow_ranges(p, method="cycle_canceling", at_optimum=True)
    optimum = solve(p, method="cycle_canceling")
    unique = optimum_uniqueness(p, optimum)
    assert (ranges.method, bounds.method, unique.method) == (
        "flow_ranges",
        "unattainable_bounds",
        "optimum_uniqueness",
    )
    # Named after the diagnostic, a result never shares the fingerprint of
    # a solve of the same problem by its flow method.
    fingerprints = {r.inputs for r in (ranges, bounds, optimal_ranges, optimum, unique)}
    assert len(fingerprints) == 5
    other = flow_ranges(p, method="network_simplex", at_optimum=False)
    assert other.inputs != ranges.inputs


def test_counters_of_a_diagnostic_add_up_its_solves() -> None:
    g = Digraph.from_arcs(2, [(0, 1), (1, 0)])
    p = FlowProblem(g, lower=(0, 1), upper=(9, 3))
    for at_optimum in (False, True):
        ranges = flow_ranges(p, method="cycle_canceling", at_optimum=at_optimum)
        expected: Counter[str] = Counter()
        if at_optimum:
            expected.update(solve(p, method="cycle_canceling").counters)
        else:
            check = check_feasibility(p, method="dinic")
            expected.update({f"feasibility_{k}": v for k, v in check.counters.items()})
        # Zero costs: every feasible flow is optimal, the face is ``p``.
        prepared = prepare(p.with_cost((0, 0)), method="cycle_canceling")
        for a, sense in itertools.product(range(g.m), ("min", "max")):
            unit = [0] * g.m
            unit[a] = 1
            expected.update(prepared.solve(unit, sense).counters)  # type: ignore[arg-type]
        expected["solves"] = 2 * g.m + at_optimum
        assert dict(ranges.counters) == dict(expected)


def test_uniqueness_counters_and_fingerprint() -> None:
    loop = FlowProblem(Digraph.from_arcs(1, [(0, 0)]), upper=(2,))
    optimum = solve(loop, method="network_simplex")
    found = optimum_uniqueness(loop, optimum)
    assert not found.unique
    assert dict(found.counters) == {"residual_edges": 1, "components": 1}
    # The fingerprint follows the flow and the potentials, not the method
    # that found them.
    other = solve(loop, method="cycle_canceling")
    same = (other.flow, other.potentials) == (optimum.flow, optimum.potentials)
    assert (optimum_uniqueness(loop, other).inputs == found.inputs) == same
    wider = FlowProblem(Digraph.from_arcs(1, [(0, 0)]), upper=(3,))
    widened = solve(wider, method="network_simplex")
    assert optimum_uniqueness(wider, widened).inputs != found.inputs
