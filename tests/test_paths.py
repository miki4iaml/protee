# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Shortest paths, against NetworkX, enumeration and Floyd-Warshall."""

from __future__ import annotations

import math
from collections.abc import Iterable

import networkx as nx
import pytest
from constraints_cases import simple_paths
from hypothesis import given
from hypothesis import strategies as st
from oracles import graphs

from protee.graph import Digraph
from protee.paths import NegativeCycle, ShortestPaths, bellman_ford, dijkstra
from protee.results import Status


def nx_graph(graph: Digraph, weight: list[int]) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_nodes_from(range(graph.n))
    for a, (t, h) in enumerate(graph.arcs()):
        g.add_edge(t, h, key=a, weight=weight[a])
    return g


@st.composite
def weighted(draw: st.DrawFn, low: int = 0) -> tuple[Digraph, list[int], int]:
    g = draw(graphs(max_nodes=7, max_arcs=14))
    weight = [draw(st.integers(low, 9)) for _ in range(g.m)]
    return g, weight, draw(st.integers(0, g.n - 1))


def check_tree(graph: Digraph, weight: list[int], sp: ShortestPaths) -> None:
    for v in range(graph.n):
        if sp.distance[v] == -math.inf:
            continue
        path = sp.path(v)
        if sp.distance[v] == math.inf:
            assert path is None
            continue
        assert path is not None
        assert sum(weight[a] for a in path) == sp.distance[v]
        if path:
            assert graph.heads[path[-1]] == v
            assert graph.tails[path[0]] in sp.sources


def check_cycle(graph: Digraph, weight: list[int], cycle: object) -> None:
    """A negative cycle, walked again."""
    assert isinstance(cycle, NegativeCycle)
    assert cycle.weight < 0
    assert cycle.weight == sum(weight[a] for a in cycle.arcs)
    for a, b in zip(cycle.arcs, (*cycle.arcs[1:], cycle.arcs[0]), strict=True):
        assert graph.heads[a] == graph.tails[b]


@given(case=weighted())
def test_dijkstra_and_bellman_ford_match_networkx(
    case: tuple[Digraph, list[int], int],
) -> None:
    graph, weight, s = case
    expected = nx.single_source_dijkstra_path_length(nx_graph(graph, weight), s)
    for found in (dijkstra(graph, weight, s), bellman_ford(graph, weight, s)):
        assert found.status is Status.OPTIMAL
        assert found.certificate is None
        assert {v: d for v, d in enumerate(found.distance) if d != math.inf} == expected
        check_tree(graph, weight, found)


@given(case=weighted(low=-4))
def test_bellman_ford_finds_negative_cycles(
    case: tuple[Digraph, list[int], int],
) -> None:
    graph, weight, _ = case
    found = bellman_ford(graph, weight)
    has_cycle = nx.negative_edge_cycle(nx_graph(graph, weight))
    assert (found.status is Status.UNBOUNDED) == has_cycle
    if has_cycle:
        check_cycle(graph, weight, found.certificate)
    else:
        assert found.certificate is None
        check_tree(graph, weight, found)


def on_negative_cycle(graph: Digraph, weight: list[int]) -> list[bool]:
    """Whether a closed walk of negative weight passes through each node
    (Floyd-Warshall, independent of Bellman-Ford)."""
    n = graph.n
    d = [[math.inf] * n for _ in range(n)]
    for a, (t, h) in enumerate(graph.arcs()):
        d[t][h] = min(d[t][h], weight[a])
    for k in range(n):
        for i in range(n):
            for j in range(n):
                d[i][j] = min(d[i][j], d[i][k] + d[k][j])
    return [d[v][v] < 0 for v in range(n)]


def reached(graph: Digraph, sources: Iterable[int]) -> set[int]:
    g = nx_graph(graph, [0] * graph.m)
    found = set(sources)
    return found.union(*(nx.descendants(g, s) for s in found))


@given(case=weighted(low=-4), every=st.booleans())
def test_unbounded_distances(case: tuple[Digraph, list[int], int], every: bool) -> None:
    graph, weight, s = case
    found = bellman_ford(graph, weight, None if every else s)
    sources = range(graph.n) if every else (s,)
    negative = on_negative_cycle(graph, weight)
    cycles = {c for c in reached(graph, sources) if negative[c]}
    below = reached(graph, cycles)
    assert (found.status is Status.UNBOUNDED) == bool(cycles)
    if cycles:
        check_cycle(graph, weight, found.certificate)
    for v in range(graph.n):
        if v in below:
            assert found.distance[v] == -math.inf
            assert found.predecessor[v] == -1
            with pytest.raises(ValueError, match="negative cycle"):
                found.path(v)
            continue
        # No negative cycle on the way: the best walk is a simple path.
        lengths = [
            sum(weight[a] for a in p)
            for u in sources
            for p in simple_paths(graph, u, v)
        ]
        assert found.distance[v] == min(lengths, default=math.inf)
    check_tree(graph, weight, found)


def test_several_sources_target_counters_and_errors() -> None:
    g = Digraph.from_arcs(4, [(0, 1), (2, 1), (1, 3)])
    sp = dijkstra(g, [5, 1, 1], [0, 2])
    assert sp.distance == (0, 1, 0, 2)
    assert sp.path(3) == (1, 2)
    assert sp.path(0) == ()
    assert dict(sp.counters) == {"settled_nodes": 4, "scanned_arcs": 3}
    early = dijkstra(g, [5, 1, 1], 0, 1)
    assert early.distance[1] == 5
    assert dict(early.counters) == {"settled_nodes": 2, "scanned_arcs": 1}
    empty = bellman_ford(Digraph.from_arcs(0, []), [])
    assert empty.status is Status.OPTIMAL
    assert (empty.sources, empty.distance, empty.predecessor) == ((), (), ())
    assert dict(empty.counters) == {"passes": 0}
    loop = bellman_ford(Digraph.from_arcs(1, [(0, 0)]), [-1])
    assert loop.status is Status.UNBOUNDED
    assert loop.certificate == NegativeCycle((0,), -1)
    assert loop.distance == (-math.inf,)
    assert dict(loop.counters) == {"passes": 1}
    # A negative cycle 1 <-> 2 behind node 1; node 3 stays out of its reach.
    mixed = bellman_ford(
        Digraph.from_arcs(4, [(0, 1), (1, 2), (2, 1), (0, 3)]), [1, -1, -1, 2], 0
    )
    assert mixed.status is Status.UNBOUNDED
    assert mixed.distance == (0, -math.inf, -math.inf, 2)
    assert mixed.predecessor == (-1, -1, -1, 3)
    assert mixed.path(3) == (3,)
    with pytest.raises(ValueError, match="negative"):
        dijkstra(g, [1, -1, 1], 0)
    with pytest.raises(ValueError, match="not finite"):
        dijkstra(g, [1, math.inf, 1], 0)
    with pytest.raises(ValueError, match="expected 3 weights"):
        bellman_ford(g, [1], 0)
    with pytest.raises(ValueError, match="source 9 is not a node"):
        dijkstra(g, [1, 1, 1], 9)
    with pytest.raises(ValueError, match="target 9 is not a node"):
        dijkstra(g, [1, 1, 1], 0, 9)
