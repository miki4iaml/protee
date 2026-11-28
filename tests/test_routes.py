# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause
"""Route-level algorithms, against exhaustive enumeration on small graphs."""

from __future__ import annotations

import itertools
import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from oracles import graphs
from test_conformity_paths import check_crossed_cuts, check_separating_cut

from protee.graph import Digraph
from protee.paths import dijkstra
from protee.results import CrossedCuts, SeparatingCut, Status
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
    assert (routes.status is Status.OPTIMAL) == bool(every)
    if not every:
        check_separating_cut(g, routes.certificate, ())
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
    assert routes[1:3] == routes.routes[1:3]
    assert len(routes) == 4
    # The first run, two spurs from (0, 1), two from (2, 3), one from each
    # direct arc; the candidates (2, 3), (4,) and (5,).
    assert dict(routes.counters) == {
        "dijkstra_runs": 7,
        "settled_nodes": 14,
        "scanned_arcs": 25,
        "candidates": 3,
    }
    none = k_shortest_paths(g, w, 3, 0, 2)
    assert none.status is Status.INFEASIBLE
    assert (list(none), len(none), bool(none)) == ([], 0, False)
    assert none.certificate == SeparatingCut(frozenset({3}), (3,), 0, ())
    cut_off = k_shortest_paths(g, w, 0, 3, 2, excluded=[1, 3, 4, 5])
    assert cut_off.certificate == SeparatingCut(
        frozenset({0, 1, 2}), (0,), 3, (1, 3, 4, 5)
    )
    with pytest.raises(ValueError, match="at least 1"):
        k_shortest_paths(g, w, 0, 3, 0)
    with pytest.raises(ValueError, match="target 7 is not a node"):
        k_shortest_paths(g, w, 0, 7, 1)


def test_k_shortest_paths_meet_a_candidate_twice() -> None:
    # 0 -> 1 -> 2 -> 3, a shortcut 1 -> 3 and a direct arc 0 -> 3: the
    # direct arc is found again from the second path, and counted once.
    g = Digraph.from_arcs(4, [(0, 1), (1, 2), (2, 3), (1, 3), (0, 3)])
    routes = k_shortest_paths(g, [1, 1, 1, 5, 10], 0, 3, 3)
    assert [r.arcs for r in routes] == [(0, 1, 2), (0, 3), (4,)]
    assert routes.counters["candidates"] == 2


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
        assert r.status is Status.INFEASIBLE
        assert (r.order, r.legs, r.arcs, r.cost) == (None, None, None, None)
        if isinstance(r.certificate, CrossedCuts):
            check_crossed_cuts(g, r.certificate, ())
        else:
            check_separating_cut(g, r.certificate, ())
        return
    assert r.status is Status.OPTIMAL
    assert r.order is not None
    assert r.arcs is not None
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
        assert r.status is Status.INFEASIBLE
        cut = check_separating_cut(g, r.certificate, ())
        assert (*cut.sources, cut.target) in set(itertools.pairwise(stops))
        return
    assert r.status is Status.OPTIMAL
    assert r.order == tuple(range(len(wps)))
    assert r.cost == expected
    assert r.legs is not None
    assert r.arcs is not None
    assert len(r.legs) == len(wps) + 1
    assert is_path(g, s, t, r.arcs)


def test_waypoint_route_certificates() -> None:
    # 0 -> 1 -> 3 and 0 -> 2 -> 3: waypoints 1 and 2 never reach each other.
    g = Digraph.from_arcs(5, [(0, 1), (1, 3), (0, 2), (2, 3), (3, 4)])
    w = [1] * 5
    crossed = waypoint_route(g, w, 0, 3, [1, 2], order="free")
    assert crossed.status is Status.INFEASIBLE
    assert crossed.certificate == CrossedCuts(
        SeparatingCut(frozenset({1, 3, 4}), (1,), 2, ()),
        SeparatingCut(frozenset({2, 3, 4}), (2,), 1, ()),
    )
    assert check_crossed_cuts(g, crossed.certificate, ()) == (1, 2)
    assert dict(crossed.counters) == {
        "dijkstra_runs": 3,
        "settled_nodes": 11,
        "scanned_arcs": 9,
        "states": 4,
    }
    with pytest.raises(TypeError):
        tuple(crossed.arcs)  # type: ignore[arg-type]
    # The start misses a waypoint, a waypoint misses the end.
    missed = waypoint_route(g, w, 1, 4, [3, 0], order="free")
    assert missed.certificate == SeparatingCut(frozenset({1, 3, 4}), (1,), 0, ())
    late = waypoint_route(g, w, 0, 1, [3, 2], order="free")
    assert late.certificate == SeparatingCut(frozenset({3, 4}), (3,), 1, ())
    # In a fixed order, the first leg out of reach.
    fixed = waypoint_route(g, w, 0, 4, [2, 1], order="fixed", excluded=[3])
    assert fixed.certificate == SeparatingCut(frozenset({2}), (2,), 1, (3,))
    assert dict(fixed.counters)["states"] == 0


def test_waypoint_route_errors() -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    with pytest.raises(ValueError, match="unknown order"):
        waypoint_route(g, [1], 0, 1, [], order="any")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at most"):
        waypoint_route(g, [1], 0, 1, [0] * (MAX_FREE_WAYPOINTS + 1), order="free")
    with pytest.raises(ValueError, match="waypoint 5 is not a node"):
        waypoint_route(g, [1], 0, 1, [5], order="free")
    with pytest.raises(ValueError, match="end 2 is not a node"):
        waypoint_route(g, [1], 0, 2, [], order="fixed")


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
    assert reps.status is Status.OPTIMAL
    assert (len(reps), reps[0].arc, reps[:1]) == (2, 0, reps.replacements[:1])
    # Without group a: 0 and 2 settle; without group b: 0, 1 and 2.
    assert dict(reps.counters) == {
        "dijkstra_runs": 2,
        "settled_nodes": 5,
        "scanned_arcs": 6,
    }
    with pytest.raises(ValueError, match="keys"):
        replacement_paths(g, w, 0, 2, [0], key=["a"])
    with pytest.raises(ValueError, match="arc 9 of the path does not exist"):
        replacement_paths(g, w, 0, 2, [9])


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
        assert r.status is Status.INFEASIBLE
        assert (r.arcs, r.probability) == (None, None)
        zero = {a for a in range(g.m) if p[a] == 0}
        check_separating_cut(g, r.certificate, zero)
        return
    assert r.status is Status.OPTIMAL
    assert r.arcs is not None
    assert r.probability == pytest.approx(best)
    assert is_path(g, s, t, r.arcs)


def test_most_reliable_path_checks_its_input() -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    with pytest.raises(ValueError, match="reliabilities"):
        most_reliable_path(g, [], 0, 1)
    with pytest.raises(ValueError, match="not in"):
        most_reliable_path(g, [1.5], 0, 1)
    unusable = most_reliable_path(g, [0.0], 0, 1)
    assert unusable.status is Status.INFEASIBLE
    assert unusable.certificate == SeparatingCut(frozenset({0}), (0,), 1, (0,))
    r = most_reliable_path(g, [0.7], 0, 1)
    assert r.status is Status.OPTIMAL
    assert r.probability == pytest.approx(0.7)
    assert dict(r.counters) == {
        "dijkstra_runs": 1,
        "settled_nodes": 2,
        "scanned_arcs": 1,
    }


def test_k_shortest_paths_tie_rule() -> None:
    # Pinned: a known client relies on this order. The first route is the
    # path of the Dijkstra tree, even when a path of equal cost has fewer
    # arcs.
    g = Digraph.from_arcs(5, [(0, 1), (1, 2), (2, 3), (0, 4), (4, 3)])
    w = [0, 0, 2, 1, 1]
    found = k_shortest_paths(g, w, 0, 3, 2)
    assert [(r.arcs, r.cost) for r in found] == [((0, 1, 2), 2), ((3, 4), 2)]
    assert [r.arcs for r in k_shortest_paths(g, w, 0, 3, 1)] == [(0, 1, 2)]
    # Each next route is the least candidate found so far by cost, then
    # number of arcs: the deviation at node 1 (two arcs) comes before the
    # one at node 0 (three arcs), found first.
    h = Digraph.from_arcs(5, [(0, 1), (1, 4), (0, 2), (2, 3), (3, 4), (1, 4)])
    found = k_shortest_paths(h, [1, 1, 1, 1, 1, 2], 0, 4, 3)
    assert [(r.arcs, r.cost) for r in found] == [
        ((0, 1), 2),
        ((0, 5), 3),
        ((2, 3, 4), 3),
    ]


def test_waypoint_route_tie_rule() -> None:
    # Pinned: among orders of equal cost, the last waypoint visited has the
    # lowest index possible, then the one before it, and so on.
    complete = Digraph.from_arcs(3, [(0, 1), (1, 0), (0, 2), (2, 0), (1, 2), (2, 1)])
    zero = [0] * complete.m
    assert waypoint_route(complete, zero, 0, 0, [1, 2], order="free").order == (1, 0)
    every = waypoint_route(complete, zero, 0, 0, [1, 2, 1], order="free")
    assert every.order == (2, 1, 0)
    # Waypoint 0 (node 1) costs more as the last one: waypoint 1 is last.
    arcs = [(u, v) for u in range(4) for v in range(4) if u != v]
    four = Digraph.from_arcs(4, arcs)
    unit = [1] * four.m
    assert waypoint_route(four, unit, 0, 0, [1, 2, 3], order="free").order == (2, 1, 0)
    late = [5 if arc == (1, 0) else 1 for arc in arcs]
    assert waypoint_route(four, late, 0, 0, [1, 2, 3], order="free").order == (2, 0, 1)


def test_route_weights_that_could_overflow_are_refused() -> None:
    # Before, the sum overflowed to inf: a reachable target was reported
    # out of reach with a false cut, or the free order crashed.
    line = Digraph.from_arcs(3, [(0, 1), (1, 2)])
    for run in (
        lambda w: k_shortest_paths(line, w, 0, 2, 1),
        lambda w: replacement_paths(line, w, 0, 2, (0, 1)),
        lambda w: waypoint_route(line, w, 0, 2, [], order="fixed"),
    ):
        with pytest.raises(ValueError, match="beyond the float range"):
            run([1e308, 1e308])
        with pytest.raises(ValueError, match="arc 0 is beyond the float range"):
            run([10**400, 1])
    # A route of k + 1 legs, each a path: k + 1 times the total must fit.
    cycle = Digraph.from_arcs(3, [(0, 1), (1, 2), (2, 0)])
    with pytest.raises(ValueError, match="3 legs times the sum"):
        waypoint_route(cycle, [6e307, 0.0, 6e307], 0, 0, [1, 2], order="free")
    fits = waypoint_route(cycle, [2e307, 0.0, 2e307], 0, 0, [1, 2], order="free")
    assert fits.status is Status.OPTIMAL
    assert fits.cost == 4e307
