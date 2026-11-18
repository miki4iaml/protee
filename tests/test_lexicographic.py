# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Lexicographic shortest paths, against enumeration of simple paths."""

import random

import pytest
from constraints_cases import simple_paths

from protee.graph import Digraph
from protee.paths import dijkstra, lexicographic_dijkstra


def random_vectors(
    seed: int, n: int = 6, m: int = 14
) -> tuple[Digraph, list[tuple[int, int]]]:
    rng = random.Random(seed)
    arcs: list[tuple[int, int]] = []
    while len(arcs) < m:
        t, h = rng.randrange(n), rng.randrange(n)
        if t != h:
            arcs.append((t, h))
    weights = [(rng.randint(0, 1), rng.randint(1, 5)) for _ in arcs]
    return Digraph.from_arcs(n, arcs), weights


@pytest.mark.parametrize("seed", range(20))
def test_matches_enumeration(seed: int) -> None:
    graph, weights = random_vectors(seed)
    rng = random.Random(seed)
    s, t = rng.sample(range(graph.n), 2)
    excluded = {rng.randrange(graph.m)}
    best = min(
        (
            tuple(map(sum, zip(*(weights[a] for a in p), strict=True)))
            for p in simple_paths(graph, s, t)
            if not excluded & set(p)
        ),
        default=None,
    )
    lp = lexicographic_dijkstra(graph, weights, s, t, excluded=excluded)
    assert lp.distance[t] == best
    path = lp.path(t)
    if best is None:
        assert path is None
    else:
        assert path is not None
        assert tuple(map(sum, zip(*(weights[a] for a in path), strict=True))) == best


def test_fewest_unknowns_first_then_length() -> None:
    # Two routes: 0-1-3 is shorter with one unknown arc, 0-2-3 longer and known.
    graph = Digraph.from_arcs(4, [(0, 1), (1, 3), (0, 2), (2, 3)])
    weights = [(0, 1.0), (1, 1.0), (0, 2.0), (0, 2.0)]
    lp = lexicographic_dijkstra(graph, weights, 0)
    assert lp.path(3) == (2, 3)
    assert lp.distance == ((0, 0), (0, 1.0), (0, 2.0), (0, 4.0))
    assert lp.path(0) == ()
    plain = dijkstra(graph, [w for _, w in weights], 0)
    assert plain.path(3) == (0, 1)


def test_single_component_agrees_with_dijkstra() -> None:
    graph, weights = random_vectors(3)
    lp = lexicographic_dijkstra(graph, [(w,) for _, w in weights], [0, 1])
    sp = dijkstra(graph, [w for _, w in weights], [0, 1])
    assert lp.sources == (0, 1)
    assert [None if d is None else d[0] for d in lp.distance] == [
        None if d == float("inf") else d for d in sp.distance
    ]


def test_unreachable_and_errors() -> None:
    graph = Digraph.from_arcs(3, [(0, 1)])
    lp = lexicographic_dijkstra(graph, [(1, 1)], 0, 2)
    assert lp.distance[2] is None
    assert lp.path(2) is None
    assert lexicographic_dijkstra(Digraph.from_arcs(1, []), [], 0).distance == ((0,),)
    with pytest.raises(ValueError, match="expected 1 weight vectors"):
        lexicographic_dijkstra(graph, [], 0)
    with pytest.raises(ValueError, match="components"):
        lexicographic_dijkstra(
            Digraph.from_arcs(2, [(0, 1), (0, 1)]), [(1,), (1, 1)], 0
        )
    with pytest.raises(ValueError, match="components"):
        lexicographic_dijkstra(graph, [()], 0)
    with pytest.raises(ValueError, match="negative"):
        lexicographic_dijkstra(graph, [(0, -1)], 0)
    with pytest.raises(ValueError, match="not finite"):
        lexicographic_dijkstra(graph, [(0, float("inf"))], 0)
    with pytest.raises(ValueError, match="does not exist"):
        lexicographic_dijkstra(graph, [(0, 1)], 0, excluded=[4])
    with pytest.raises(ValueError, match="not a node"):
        lexicographic_dijkstra(graph, [(0, 1)], 7)
