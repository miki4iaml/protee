# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Disjoint paths and flow diagnostics, against enumeration and NetworkX."""

import itertools

import networkx as nx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from oracles import all_flows, graphs, problems

from protee.flow import FlowProblem, Status, disjoint_paths, methods, solve
from protee.flow.diagnostics import flow_ranges, optimum_uniqueness, unattainable_bounds
from protee.graph import Digraph

METHODS = [info.name for info in methods()]


def simple_paths(graph: Digraph, s: int, t: int) -> list[tuple[int, ...]]:
    """Every simple path from s to t, as arc tuples (tiny graphs)."""
    found = []

    def walk(u: int, seen: set[int], path: list[int]) -> None:
        if u == t:
            found.append(tuple(path))
            return
        for a in graph.out_arcs(u):
            v = graph.heads[a]
            if v not in seen:
                walk(v, seen | {v}, [*path, a])

    walk(s, {s}, [])
    return found


def best_disjoint(
    graph: Digraph, cost: list[int], s: int, t: int, k: int, nodes: bool
) -> int | None:
    best = None
    for combo in itertools.combinations(simple_paths(graph, s, t), k):
        arcs = [a for p in combo for a in p]
        if len(arcs) != len(set(arcs)):
            continue
        if nodes:
            inner = [graph.heads[a] for p in combo for a in p[:-1]]
            if len(inner) != len(set(inner)):
                continue
        value = sum(cost[a] for a in arcs)
        best = value if best is None else min(best, value)
    return best


@st.composite
def instances(draw: st.DrawFn) -> tuple[Digraph, list[int], int, int, int]:
    g = draw(graphs(max_nodes=5, max_arcs=8))
    cost = [draw(st.integers(0, 5)) for _ in range(g.m)]
    s = draw(st.integers(0, g.n - 1))
    t = draw(st.integers(0, g.n - 1))
    return g, cost, s, t, draw(st.integers(1, 3))


@given(case=instances(), disjoint=st.sampled_from(["nodes", "arcs"]))
@settings(max_examples=120)
def test_disjoint_paths_match_enumeration(
    case: tuple[Digraph, list[int], int, int, int], disjoint: str
) -> None:
    graph, cost, s, t, k = case
    if s == t:
        return
    expected = best_disjoint(graph, cost, s, t, k, disjoint == "nodes")
    for method in METHODS:
        found = disjoint_paths(graph, cost, s, t, k, disjoint=disjoint, method=method)  # type: ignore[arg-type]
        if expected is None:
            assert found.status is Status.INFEASIBLE
            assert found.max_paths < k
            continue
        assert found.status is Status.OPTIMAL
        assert found.cost == expected
        assert len(found.paths) == k
        assert found.max_paths >= k
        for path in found.paths:
            assert graph.tails[path[0]] == s
            assert graph.heads[path[-1]] == t


def test_disjoint_paths_count_is_menger() -> None:
    g = nx.gnp_random_graph(9, 0.4, seed=3, directed=True)
    graph = Digraph.from_arcs(9, g.edges())
    found = disjoint_paths(
        graph,
        [1] * graph.m,
        0,
        8,
        1,
        disjoint="nodes",
        method="successive_shortest_paths",
    )
    assert found.max_paths == len(list(nx.node_disjoint_paths(g, 0, 8)))


def test_disjoint_paths_errors() -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    with pytest.raises(ValueError, match="disjoint"):
        disjoint_paths(g, [1], 0, 1, 1, disjoint="edges", method="cycle_canceling")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least 1"):
        disjoint_paths(g, [1], 0, 1, 0, disjoint="arcs", method="cycle_canceling")
    with pytest.raises(ValueError, match="distinct"):
        disjoint_paths(g, [1], 0, 0, 1, disjoint="arcs", method="cycle_canceling")
    with pytest.raises(ValueError, match="non-negative"):
        disjoint_paths(g, [-1], 0, 1, 1, disjoint="arcs", method="cycle_canceling")


def enumerate_ranges(
    problem: FlowProblem, optimal: bool
) -> tuple[list[int], list[int]] | None:
    flows = all_flows(problem)
    if not flows:
        return None
    if optimal:
        values = [problem.objective(x) for x in flows]
        best = min(values) if problem.sense == "min" else max(values)
        flows = [x for x, v in zip(flows, values, strict=True) if v == best]
    m = problem.graph.m
    return [min(x[a] for x in flows) for a in range(m)], [
        max(x[a] for x in flows) for a in range(m)
    ]


@pytest.mark.parametrize("method", METHODS)
@given(
    problem=problems(max_nodes=4, max_arcs=5, finite=True, span=2),
    at_optimum=st.booleans(),
)
@settings(max_examples=60)
def test_flow_ranges_match_enumeration(
    method: str, problem: FlowProblem, at_optimum: bool
) -> None:
    ranges = flow_ranges(problem, method=method, at_optimum=at_optimum)
    expected = enumerate_ranges(problem, at_optimum)
    if expected is None:
        assert ranges.status is Status.INFEASIBLE
        return
    assert (list(ranges.minimum or ()), list(ranges.maximum or ())) == expected


@given(problem=problems(max_nodes=4, max_arcs=5, finite=True, span=2))
@settings(max_examples=80)
def test_uniqueness_matches_enumeration(problem: FlowProblem) -> None:
    result = solve(problem, method="network_simplex")
    if not result.optimal:
        return
    flows = all_flows(problem)
    best = result.objective
    optimal = [x for x in flows if problem.objective(x) == best]
    found = optimum_uniqueness(problem, result)
    assert found.unique == (len(optimal) == 1)
    if not found.unique:
        assert found.direction is not None
        assert result.flow is not None
        moved = list(result.flow)
        for a, sign in found.direction:
            moved[a] += sign
        assert not problem.violations(moved)
        assert problem.objective(moved) == best


def test_unattainable_bounds() -> None:
    # Arc 0 allows 9 but arc 1 caps the cycle at 3; arc 1 needs at least 1.
    g = Digraph.from_arcs(2, [(0, 1), (1, 0)])
    p = FlowProblem(g, lower=(0, 1), upper=(9, 3))
    found = unattainable_bounds(p, method="network_simplex")
    assert (found.upper, found.lower) == ((0,), (0,))
    assert found.ranges.maximum == (3, 3)
    unbounded = unattainable_bounds(
        FlowProblem(g, upper=(None, None)), method="cycle_canceling"
    )
    assert unbounded.ranges.maximum == (None, None)
    infeasible = unattainable_bounds(
        FlowProblem(g, lower=(4, 0), upper=(5, 1)), method="network_simplex"
    )
    assert infeasible.status is Status.INFEASIBLE
    at_optimum = flow_ranges(
        FlowProblem(g, upper=(None, None), cost=(-1, 0)),
        method=METHODS[0],
        at_optimum=True,
    )
    assert at_optimum.status is Status.UNBOUNDED
    with pytest.raises(ValueError, match="not optimal"):
        optimum_uniqueness(
            p, solve(FlowProblem(g, lower=(4, 0), upper=(5, 1)), method=METHODS[0])
        )


def test_uniqueness_of_a_loop_and_of_parallel_arcs() -> None:
    loop = FlowProblem(Digraph.from_arcs(1, [(0, 0)]), upper=(2,))
    assert not optimum_uniqueness(loop, solve(loop, method="network_simplex")).unique
    parallel = FlowProblem(
        Digraph.from_arcs(2, [(0, 1), (0, 1)]), upper=(1, 1), supply=(1, -1)
    )
    r = solve(parallel, method="network_simplex")
    found = optimum_uniqueness(parallel, r)
    assert not found.unique
    assert sorted(a for a, _ in found.direction or ()) == [0, 1]
