# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause
"""Route-level algorithms, against exhaustive enumeration on small graphs."""

import itertools
import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from oracles import graphs

from protee.graph import Digraph
from protee.paths import dijkstra
from protee.routes import (
    MAX_FREE_WAYPOINTS,
    k_shortest_paths,
    most_reliable_path,
    overlap,
    replacement_paths,
    waypoint_route,
)

type Case = tuple[Digraph, list[int], int, int]


def simple_paths(
    graph: Digraph, s: int, t: int, banned: frozenset[int] = frozenset()
) -> list[tuple[int, ...]]:
    """Every loopless path from s to t, as tuples of arcs (exhaustive)."""
    found: list[tuple[int, ...]] = []

    def walk(u: int, seen: set[int], arcs: list[int]) -> None:
        if u == t:
            found.append(tuple(arcs))
            return
        for a in graph.out_arcs(u):
            v = graph.heads[a]
            if a in banned or v in seen:
                continue
            seen.add(v)
            arcs.append(a)
            walk(v, seen, arcs)
            arcs.pop()
            seen.discard(v)

    walk(s, {s}, [])
    return found


def is_path(graph: Digraph, s: int, t: int, arcs: tuple[int, ...]) -> bool:
    u = s
    for a in arcs:
        if graph.tails[a] != u:
            return False
        u = graph.heads[a]
    return u == t


@st.composite
def weighted(draw: st.DrawFn) -> Case:
    g = draw(graphs(max_nodes=6, max_arcs=11))
    w = [draw(st.integers(0, 9)) for _ in range(g.m)]
    s, t = draw(st.integers(0, g.n - 1)), draw(st.integers(0, g.n - 1))
    return g, w, s, t


def cost(w: list[int], arcs: tuple[int, ...]) -> int:
    return sum(w[a] for a in arcs)


# --- dijkstra with excluded arcs -------------------------------------------


@given(weighted(), st.data())
def test_excluded_arcs_are_as_if_removed(case: Case, data: st.DataObject) -> None:
    g, w, s, _ = case
    banned: set[int] = set()
    if g.m:
        banned = data.draw(st.sets(st.integers(0, g.m - 1), max_size=g.m))
    kept = [a for a in range(g.m) if a not in banned]
    sub = Digraph(g.n, tuple(g.tails[a] for a in kept), tuple(g.heads[a] for a in kept))
    expected = dijkstra(sub, [w[a] for a in kept], s).distance
    assert dijkstra(g, w, s, excluded=banned).distance == expected


def test_excluded_arc_must_exist() -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    with pytest.raises(ValueError, match="does not exist"):
        dijkstra(g, [1], 0, excluded=[3])


# --- k shortest paths ------------------------------------------------------


@given(weighted(), st.integers(1, 5))
def test_k_shortest_paths_are_the_k_cheapest_loopless_paths(case: Case, k: int) -> None:
    g, w, s, t = case
    routes = k_shortest_paths(g, w, s, t, k)
    every = sorted(cost(w, p) for p in simple_paths(g, s, t))
    assert [r.cost for r in routes] == every[:k]
    assert len({r.arcs for r in routes}) == len(routes)
    for r in routes:
        assert is_path(g, s, t, r.arcs)
        assert r.cost == cost(w, r.arcs)
        nodes = [s, *(g.heads[a] for a in r.arcs)]
        assert len(nodes) == len(set(nodes))


def test_k_shortest_paths_small_case_and_errors() -> None:
    # 0 -> 1 -> 3, 0 -> 2 -> 3, 0 -> 3 (direct), with a parallel arc 0 -> 3.
    g = Digraph.from_arcs(4, [(0, 1), (1, 3), (0, 2), (2, 3), (0, 3), (0, 3)])
    w = [1, 1, 1, 2, 4, 5]
    routes = k_shortest_paths(g, w, 0, 3, 10)
    assert [r.cost for r in routes] == [2, 3, 4, 5]
    assert routes[0].arcs == (0, 1)
    assert k_shortest_paths(g, w, 3, 0, 2) == []
    with pytest.raises(ValueError, match="at least 1"):
        k_shortest_paths(g, w, 0, 3, 0)


# --- waypoints -------------------------------------------------------------


@given(weighted(), st.data())
def test_waypoint_route_free_order_is_the_best_permutation(
    case: Case, data: st.DataObject
) -> None:
    g, w, s, t = case
    k = data.draw(st.integers(0, min(4, g.n)))
    wps = data.draw(st.lists(st.integers(0, g.n - 1), min_size=k, max_size=k))
    trees = {u: dijkstra(g, w, u) for u in {s, *wps}}
    best = math.inf
    for perm in itertools.permutations(range(k)):
        stops = [s, *(wps[i] for i in perm), t]
        total = sum(trees[a].distance[b] for a, b in itertools.pairwise(stops))
        best = min(best, total)
    r = waypoint_route(g, w, s, t, wps, order="free")
    if best == math.inf:
        assert r is None
        return
    assert r is not None
    assert r.cost == best
    assert sorted(r.order) == list(range(k))
    assert is_path(g, s, t, r.arcs)
    assert cost(w, r.arcs) == best
    assert set(wps) <= {s, *(g.heads[a] for a in r.arcs)}


@given(weighted(), st.data())
def test_waypoint_route_fixed_order_follows_the_given_order(
    case: Case, data: st.DataObject
) -> None:
    g, w, s, t = case
    wps = data.draw(st.lists(st.integers(0, g.n - 1), max_size=3))
    stops = [s, *wps, t]
    expected = sum(dijkstra(g, w, a).distance[b] for a, b in itertools.pairwise(stops))
    r = waypoint_route(g, w, s, t, wps, order="fixed")
    if expected == math.inf:
        assert r is None
        return
    assert r is not None
    assert r.order == tuple(range(len(wps)))
    assert r.cost == expected
    assert len(r.legs) == len(wps) + 1
    assert is_path(g, s, t, r.arcs)


def test_waypoint_route_errors() -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    with pytest.raises(ValueError, match="unknown order"):
        waypoint_route(g, [1], 0, 1, [], order="any")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at most"):
        waypoint_route(g, [1], 0, 1, [0] * (MAX_FREE_WAYPOINTS + 1), order="free")


# --- replacement paths -----------------------------------------------------


@given(weighted())
def test_replacement_paths_avoid_each_arc(case: Case) -> None:
    g, w, s, t = case
    path = dijkstra(g, w, s).path(t)
    if path is None:
        return
    for rep in replacement_paths(g, w, s, t, path):
        others = [cost(w, p) for p in simple_paths(g, s, t, frozenset({rep.arc}))]
        if not others:
            assert rep.route is None
            continue
        assert rep.route is not None
        assert rep.route.cost == min(others)
        assert rep.arc not in rep.route.arcs
        assert is_path(g, s, t, rep.route.arcs)


def test_replacement_paths_remove_whole_groups() -> None:
    # A road 0 - 1 - 2 in both directions, and a longer bypass 0 -> 2.
    g = Digraph.from_arcs(3, [(0, 1), (1, 0), (1, 2), (2, 1), (0, 2)])
    w = [1, 1, 1, 1, 5]
    key = ["a", "a", "b", "b", "c"]
    reps = replacement_paths(g, w, 0, 2, [0, 2], key=key)
    found = [(r.arc, r.route.cost if r.route else None) for r in reps]
    assert found == [(0, 5), (2, 5)]
    with pytest.raises(ValueError, match="keys"):
        replacement_paths(g, w, 0, 2, [0], key=["a"])


# --- overlap ---------------------------------------------------------------


def test_overlap_with_and_without_keys() -> None:
    w = [2, 3, 5, 2, 3]
    assert overlap(w, [0, 1, 2], [1, 2]) == pytest.approx(0.8)
    assert overlap(w, [0, 1], []) == 0.0
    assert overlap(w, [], [0]) == 0.0
    # Arcs 3 and 4 are the reverse directions of arcs 0 and 1.
    key = ["x", "y", "z", "x", "y"]
    assert overlap(w, [0, 1, 2], [3, 4], key=key) == pytest.approx(0.5)


# --- most reliable path ----------------------------------------------------


@given(weighted(), st.data())
def test_most_reliable_path_maximizes_the_product(
    case: Case, data: st.DataObject
) -> None:
    g, _, s, t = case
    p = [data.draw(st.sampled_from([0.0, 0.25, 0.5, 0.9, 1.0])) for _ in range(g.m)]
    r = most_reliable_path(g, p, s, t)
    products = [math.prod(p[a] for a in path) for path in simple_paths(g, s, t)]
    best = max(products, default=0.0)
    if best == 0.0:
        assert r is None
        return
    assert r is not None
    assert r.probability == pytest.approx(best)
    assert is_path(g, s, t, r.arcs)


def test_most_reliable_path_checks_its_input() -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    with pytest.raises(ValueError, match="reliabilities"):
        most_reliable_path(g, [], 0, 1)
    with pytest.raises(ValueError, match="not in"):
        most_reliable_path(g, [1.5], 0, 1)
    assert most_reliable_path(g, [0.0], 0, 1) is None
    r = most_reliable_path(g, [0.7], 0, 1)
    assert r is not None
    assert r.probability == pytest.approx(0.7)
