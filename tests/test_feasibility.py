# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Maximum flow, minimum cut and feasibility certificates."""

import networkx as nx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from oracles import all_flows, graphs, problems

from protee.flow import FlowProblem, check_feasibility, max_flow
from protee.flow._feasibility import cut_of
from protee.graph import Digraph


@st.composite
def networks(draw: st.DrawFn) -> tuple[Digraph, list[int | None], int, int]:
    g = draw(graphs(max_nodes=7, max_arcs=14))
    cap: list[int | None] = [draw(st.integers(0, 6)) for _ in range(g.m)]
    s = draw(st.integers(0, g.n - 1))
    t = draw(st.integers(0, g.n - 1).filter(lambda v: v != s)) if g.n > 1 else s
    return g, cap, s, t


@given(case=networks())
def test_max_flow_matches_networkx_and_its_cut(
    case: tuple[Digraph, list[int | None], int, int],
) -> None:
    graph, cap, s, t = case
    if s == t:
        return
    nxg: nx.DiGraph = nx.DiGraph()
    nxg.add_nodes_from(range(graph.n))
    for (u, v), c in zip(graph.arcs(), cap, strict=True):
        if u != v:
            old = nxg.get_edge_data(u, v, {"capacity": 0})["capacity"]
            nxg.add_edge(u, v, capacity=old + c)
    expected = nx.maximum_flow_value(nxg, s, t)
    for method in ("dinic", "edmonds_karp"):
        r = max_flow(graph, cap, s, t, method=method)
        assert r.value == expected
        assert s in r.source_side
        assert t not in r.source_side
        crossing = sum(
            c or 0
            for (u, v), c in zip(graph.arcs(), cap, strict=True)
            if u in r.source_side and v not in r.source_side
        )
        assert crossing == r.value
        balance = [0] * graph.n
        for (u, v), x in zip(graph.arcs(), r.flow, strict=True):
            balance[u] += x
            balance[v] -= x
        assert balance[s] == r.value
        assert all(balance[v] == 0 for v in range(graph.n) if v not in (s, t))


def test_max_flow_errors() -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    with pytest.raises(ValueError, match="unbounded"):
        max_flow(g, [None], 0, 1, method="dinic")
    with pytest.raises(ValueError, match="distinct"):
        max_flow(g, [1], 0, 0, method="dinic")
    with pytest.raises(ValueError, match="non-negative"):
        max_flow(g, [-1], 0, 1, method="dinic")
    with pytest.raises(ValueError, match="expected 1"):
        max_flow(g, [], 0, 1, method="dinic")
    with pytest.raises(ValueError, match="unknown maximum flow method"):
        max_flow(g, [1], 0, 1, method="push_relabel")  # type: ignore[arg-type]
    assert max_flow(g, [None], 1, 0, method="edmonds_karp").value == 0


@given(problem=problems(max_nodes=4, max_arcs=6, finite=True, span=2))
@settings(max_examples=80)
def test_feasibility_matches_enumeration(problem: FlowProblem) -> None:
    exists = bool(all_flows(problem))
    for method in ("dinic", "edmonds_karp"):
        found = check_feasibility(problem, method=method)
        assert found.feasible == exists
        if found.flow is not None:
            assert not problem.violations(found.flow)
        else:
            assert found.cut is not None
            assert found.cut.excess > 0


@given(problem=problems())
def test_infeasibility_certificates_are_violated_inequalities(
    problem: FlowProblem,
) -> None:
    found = check_feasibility(problem)
    if found.cut is not None:
        recomputed = cut_of(problem, found.cut.nodes)
        assert recomputed == found.cut
        assert found.cut.supply > found.cut.capacity


def test_hoffman_circulation() -> None:
    # A cycle whose lower bound on one arc exceeds the upper bound on another.
    g = Digraph.from_arcs(2, [(0, 1), (1, 0)])
    p = FlowProblem(g, lower=(3, 0), upper=(5, 2))
    found = check_feasibility(p)
    assert not found.feasible
    assert found.cut is not None
    assert found.cut.excess == 1
    with pytest.raises(ValueError, match="void"):
        cut_of(FlowProblem(g), frozenset({0}))
