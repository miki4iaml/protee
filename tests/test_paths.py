# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Shortest paths, against NetworkX."""

import math

import networkx as nx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from oracles import graphs

from protee.graph import Digraph
from protee.paths import NegativeCycle, ShortestPaths, bellman_ford, dijkstra


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
        path = sp.path(v)
        if sp.distance[v] == math.inf:
            assert path is None
            continue
        assert path is not None
        assert sum(weight[a] for a in path) == sp.distance[v]
        if path:
            assert graph.heads[path[-1]] == v
            assert graph.tails[path[0]] in sp.sources


@given(case=weighted())
def test_dijkstra_and_bellman_ford_match_networkx(
    case: tuple[Digraph, list[int], int],
) -> None:
    graph, weight, s = case
    expected = nx.single_source_dijkstra_path_length(nx_graph(graph, weight), s)
    for found in (dijkstra(graph, weight, s), bellman_ford(graph, weight, s)):
        assert isinstance(found, ShortestPaths)
        assert {v: d for v, d in enumerate(found.distance) if d != math.inf} == expected
        check_tree(graph, weight, found)


@given(case=weighted(low=-4))
def test_bellman_ford_finds_negative_cycles(
    case: tuple[Digraph, list[int], int],
) -> None:
    graph, weight, _ = case
    found = bellman_ford(graph, weight)
    has_cycle = nx.negative_edge_cycle(nx_graph(graph, weight))
    assert isinstance(found, NegativeCycle) == has_cycle
    if isinstance(found, NegativeCycle):
        assert found.weight < 0
        assert found.weight == sum(weight[a] for a in found.arcs)
        for a, b in zip(found.arcs, (*found.arcs[1:], found.arcs[0]), strict=True):
            assert graph.heads[a] == graph.tails[b]
    else:
        check_tree(graph, weight, found)


def test_several_sources_target_and_errors() -> None:
    g = Digraph.from_arcs(4, [(0, 1), (2, 1), (1, 3)])
    sp = dijkstra(g, [5, 1, 1], [0, 2])
    assert sp.distance == (0, 1, 0, 2)
    assert sp.path(3) == (1, 2)
    assert sp.path(0) == ()
    early = dijkstra(g, [5, 1, 1], 0, target=1)
    assert early.distance[1] == 5
    assert bellman_ford(Digraph.from_arcs(0, []), []) == ShortestPaths(
        (), (), (), (), ()
    )
    assert isinstance(bellman_ford(Digraph.from_arcs(1, [(0, 0)]), [-1]), NegativeCycle)
    with pytest.raises(ValueError, match="negative"):
        dijkstra(g, [1, -1, 1], 0)
    with pytest.raises(ValueError, match="not finite"):
        dijkstra(g, [1, math.inf, 1], 0)
    with pytest.raises(ValueError, match="expected 3 weights"):
        bellman_ford(g, [1], 0)
    with pytest.raises(ValueError, match="not a node"):
        dijkstra(g, [1, 1, 1], 9)
