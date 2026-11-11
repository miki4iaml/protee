# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Components, degree-2 paths, spanning forests and cycle bases."""

import itertools
from collections.abc import Callable, Sequence
from typing import Any

import networkx as nx
from hypothesis import given
from hypothesis import strategies as st
from oracles import graphs

from protee import structure
from protee.graph import Digraph


def nx_graph(graph: Digraph) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_nodes_from(range(graph.n))
    g.add_edges_from(graph.arcs())
    return g


def partition(labels: tuple[int, ...]) -> set[frozenset[int]]:
    groups: dict[int, set[int]] = {}
    for v, c in enumerate(labels):
        groups.setdefault(c, set()).add(v)
    return {frozenset(s) for s in groups.values()}


@given(graph=graphs(max_nodes=8, max_arcs=12))
def test_components_match_networkx(graph: Digraph) -> None:
    g = nx_graph(graph)
    assert partition(structure.weak_components(graph)) == {
        frozenset(c) for c in nx.weakly_connected_components(g)
    }
    strong = structure.strong_components(graph)
    assert partition(strong) == {
        frozenset(c) for c in nx.strongly_connected_components(g)
    }
    for t, h in graph.arcs():
        assert strong[t] >= strong[h]  # reverse topological numbering
    assert structure.cyclomatic_number(
        graph
    ) == graph.m - graph.n + nx.number_weakly_connected_components(g)


@given(
    graph=graphs(max_nodes=8, max_arcs=12),
    mode=st.sampled_from(["series", "two_way"]),
    data=st.data(),
)
def test_degree2_paths_partition_the_arcs(
    graph: Digraph, mode: str, data: st.DataObject
) -> None:
    protected = data.draw(st.sets(st.integers(0, graph.n - 1)))
    paths = structure.degree2_paths(graph, protected=protected, mode=mode)  # type: ignore[arg-type]
    interior = structure.interior_nodes(graph, protected=protected, mode=mode)  # type: ignore[arg-type]
    assert sorted(a for p in paths for a in p) == list(range(graph.m))
    assert not interior & protected
    for p in paths:
        for a, b in itertools.pairwise(p):
            assert graph.heads[a] == graph.tails[b]
            assert graph.heads[a] in interior
    contraction = structure.contract_paths(graph, protected=protected, mode=mode)  # type: ignore[arg-type]
    assert contraction.graph.m == len(paths)
    assert all(v in interior or v in contraction.nodes for v in range(graph.n))
    assert contraction.expand(range(contraction.graph.m)) == contraction.arc_of
    for c, p in enumerate(contraction.paths):
        t, h = contraction.graph.arc(c)
        assert contraction.nodes[t] == graph.tails[p[0]]
        assert contraction.nodes[h] == graph.heads[p[-1]]


def test_contraction_aggregates_columns_and_keeps_labels() -> None:
    # Two-way road 0 - 1 - 2 - 3, and a one-way spur 2 -> 4.
    g = Digraph.from_arcs(
        5,
        [(0, 1), (1, 0), (1, 2), (2, 1), (2, 3), (3, 2), (2, 4)],
        labels=["a", "b", "c", "d", "e"],
    )
    columns: dict[str, tuple[Sequence[Any], Callable[[list[Any]], object]]] = {
        "length": ((1, 1, 2, 2, 3, 3, 9), sum),
        "gauge": ((4, 4, 3, 3, 5, 5, 2), min),
        "id": (("a1", "a2", "b1", "b2", "c1", "c2", "s"), list),
    }
    c = structure.contract_paths(g, mode="two_way", columns=columns)
    assert c.graph.labels == ("a", "c", "d", "e")
    assert c.paths == ((0, 2), (3, 1), (4,), (5,), (6,))
    assert dict(c.columns)["length"] == (3, 3, 3, 3, 9)
    assert dict(c.columns)["gauge"] == (3, 3, 5, 5, 2)
    assert dict(c.columns)["id"][0] == ["a1", "b1"]
    # In series mode, the dead ends "a" and "d" (one arc in, one out) are
    # interior: each two-way spur becomes a loop, which carries its flow.
    series = structure.contract_paths(g, mode="series")
    assert series.graph.labels == ("b", "c", "e")
    assert series.paths == ((1, 0), (2,), (3,), (4, 5), (6,))


def test_cycle_of_interior_nodes_becomes_a_loop() -> None:
    ring = Digraph.from_arcs(4, [(1, 2), (2, 3), (3, 0), (0, 1)])
    c = structure.contract_paths(ring)
    assert (c.graph.n, c.graph.arc(0), c.nodes) == (1, (0, 0), (0,))
    assert c.paths == ((0, 1, 2, 3),) or c.paths == ((3, 0, 1, 2),)


@given(graph=graphs(max_nodes=8, max_arcs=12))
def test_fundamental_cycles_are_a_cycle_basis(graph: Digraph) -> None:
    forest = structure.spanning_forest(graph)
    assert len(forest.roots) == len(set(structure.weak_components(graph)))
    assert len(forest.tree_arcs) == graph.n - len(forest.roots)
    cycles = structure.fundamental_cycles(graph, forest)
    assert len(cycles) == structure.cyclomatic_number(graph)
    for cycle in cycles:
        balance = [0] * graph.n
        for a, s in zip(cycle.arcs, cycle.signs, strict=True):
            balance[graph.tails[a]] += s
            balance[graph.heads[a]] -= s
        assert not any(balance)
        assert cycle.arcs[0] not in forest.tree_arcs
        assert all(a in forest.tree_arcs for a in cycle.arcs[1:])


def test_spanning_forest_uses_preferred_roots() -> None:
    g = Digraph.from_arcs(4, [(0, 1), (2, 3)])
    forest = structure.spanning_forest(g, roots=[3])
    assert forest.roots == (3, 0)
    assert forest.parent == (-1, 0, 3, -1)
    assert forest.depth == (0, 1, 1, 0)


def test_column_and_value_sizes_are_checked() -> None:
    import pytest

    g = Digraph.from_arcs(3, [(0, 1), (1, 2)])
    with pytest.raises(ValueError, match="column 'length'"):
        structure.contract_paths(g, columns={"length": ((1,), sum)})
    with pytest.raises(ValueError, match="expected 1 values"):
        structure.contract_paths(g).expand([1, 2])
