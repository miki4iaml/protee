# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Conformity of the shortest path and route methods to the common result
model, with their certificates verified by NetworkX."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Collection, Sequence

import networkx as nx
import pytest
from conformity import check_core, check_registry
from hypothesis import given
from hypothesis import strategies as st
from oracles import graphs

from protee import paths, results, routes
from protee.graph import Digraph
from protee.results import (
    CrossedCuts,
    GuaranteeKind,
    MethodInfo,
    NegativeCycle,
    ResultCore,
    SeparatingCut,
    Status,
)

INFOS = {info.name: info for info in (*paths.methods(), *routes.methods())}

type Case = tuple[Digraph, list[int], int, int, frozenset[int]]


# --- independent checks of the certificates --------------------------------


def admitted_reach(
    graph: Digraph, sources: Sequence[int], barred: Collection[int]
) -> set[int]:
    """The nodes reached from ``sources`` through arcs not barred (NetworkX)."""
    g = nx.MultiDiGraph()
    g.add_nodes_from(range(graph.n))
    g.add_edges_from((t, h) for a, (t, h) in enumerate(graph.arcs()) if a not in barred)
    found = set(sources)
    return found.union(*(nx.descendants(g, s) for s in sources))


def check_separating_cut(
    graph: Digraph, cut: object, barred: Collection[int]
) -> SeparatingCut:
    """The cut is the reach of its sources, its target lies outside, and
    the arcs leaving it are exactly the listed ones, all barred."""
    assert isinstance(cut, SeparatingCut)
    assert cut.nodes == admitted_reach(graph, cut.sources, barred)
    assert cut.target not in cut.nodes
    leaving = [
        a
        for a, (t, h) in enumerate(graph.arcs())
        if t in cut.nodes and h not in cut.nodes
    ]
    assert cut.arcs == tuple(leaving)
    assert set(cut.arcs) <= set(barred)
    return cut


def check_crossed_cuts(
    graph: Digraph, cuts: object, barred: Collection[int]
) -> tuple[int, int]:
    """Two cuts, each from one node of a pair to the other."""
    assert isinstance(cuts, CrossedCuts)
    forward = check_separating_cut(graph, cuts.forward, barred)
    backward = check_separating_cut(graph, cuts.backward, barred)
    assert forward.sources == (backward.target,)
    assert backward.sources == (forward.target,)
    return backward.target, forward.target


def check_negative_cycle(
    graph: Digraph, weight: Sequence[int], cycle: object, sources: Sequence[int]
) -> None:
    """A closed walk of negative weight, reachable from the sources."""
    assert isinstance(cycle, NegativeCycle)
    assert cycle.weight == sum(weight[a] for a in cycle.arcs) < 0
    for a, b in zip(cycle.arcs, (*cycle.arcs[1:], cycle.arcs[0]), strict=True):
        assert graph.heads[a] == graph.tails[b]
    assert graph.tails[cycle.arcs[0]] in admitted_reach(graph, sources, ())


# --- instances ---------------------------------------------------------------


@st.composite
def instances(draw: st.DrawFn, low: int = 0) -> Case:
    g = draw(graphs(max_nodes=6, max_arcs=11))
    w = [draw(st.integers(low, 9)) for _ in range(g.m)]
    s, t = draw(st.integers(0, g.n - 1)), draw(st.integers(0, g.n - 1))
    excluded: frozenset[int] = frozenset()
    if g.m:
        excluded = frozenset(draw(st.sets(st.integers(0, g.m - 1), max_size=3)))
    return g, w, s, t, excluded


def conforms[R: ResultCore](run: Callable[[], R], name: str) -> R:
    result = run()
    check_core(result, INFOS[name], run)
    return result


# --- registries --------------------------------------------------------------


def test_registries() -> None:
    check_registry(paths.methods())
    check_registry(routes.methods())
    for info in INFOS.values():
        assert info.guarantee.kind is GuaranteeKind.EXACT
    assert [i.name for i in paths.methods("shortest_paths")] == [
        "dijkstra",
        "bellman_ford",
    ]
    assert [i.name for i in paths.methods("lexicographic_shortest_paths")] == [
        "lexicographic_dijkstra"
    ]
    assert [i.problem for i in routes.methods()] == [
        "waypoint_route",
        "k_shortest_paths",
        "replacement_paths",
        "most_reliable_path",
    ]
    assert routes.methods("k_shortest_paths") == (INFOS["k_shortest_paths"],)
    with pytest.raises(ValueError, match="unknown problem 'max_flow'"):
        paths.methods("max_flow")
    with pytest.raises(ValueError, match="unknown problem"):
        routes.methods("shortest_paths")


def test_certificates_are_shared() -> None:
    assert paths.SeparatingCut is results.SeparatingCut
    assert routes.SeparatingCut is results.SeparatingCut
    assert routes.CrossedCuts is results.CrossedCuts
    assert isinstance(INFOS["dijkstra"], MethodInfo)


# --- shortest paths ----------------------------------------------------------


def admitted_distances(
    graph: Digraph, weight: Sequence[int], source: int, barred: Collection[int]
) -> dict[int, int]:
    g = nx.MultiDiGraph()
    g.add_nodes_from(range(graph.n))
    for a, (t, h) in enumerate(graph.arcs()):
        if a not in barred:
            g.add_edge(t, h, key=a, weight=weight[a])
    return dict(nx.single_source_dijkstra_path_length(g, source))


@given(case=instances(), early=st.booleans())
def test_dijkstra_conforms(case: Case, early: bool) -> None:
    g, w, s, t, excluded = case
    target = t if early else None
    r = conforms(lambda: paths.dijkstra(g, w, s, target, excluded=excluded), "dijkstra")
    assert r.status is Status.OPTIMAL
    assert r.certificate is None
    assert dict(r.parameters) == {}
    assert set(r.counters) == {"settled_nodes", "scanned_arcs"}
    expected = admitted_distances(g, w, s, excluded)
    assert r.distance[t] == expected.get(t, math.inf)
    if not early:
        assert {v: d for v, d in enumerate(r.distance) if d != math.inf} == expected


@given(case=instances(low=-3))
def test_bellman_ford_conforms(case: Case) -> None:
    g, w, s, _, _ = case
    r = conforms(lambda: paths.bellman_ford(g, w, s), "bellman_ford")
    assert dict(r.parameters) == {"tolerance": 0.0}
    assert set(r.counters) == {"passes"}
    if r.status is Status.UNBOUNDED:
        check_negative_cycle(g, w, r.certificate, (s,))
    else:
        assert r.status is Status.OPTIMAL
        assert r.certificate is None


@given(case=instances())
def test_exact_shortest_path_methods_agree(case: Case) -> None:
    g, w, s, _, _ = case
    by_dijkstra = paths.dijkstra(g, w, s)
    by_bellman_ford = paths.bellman_ford(g, w, s)
    lexicographic = paths.lexicographic_dijkstra(g, [(x,) for x in w], s)
    assert by_dijkstra.distance == by_bellman_ford.distance
    assert [None if d == math.inf else (d,) for d in by_dijkstra.distance] == list(
        lexicographic.distance
    )


@given(case=instances())
def test_lexicographic_dijkstra_conforms(case: Case) -> None:
    g, w, s, t, excluded = case
    vectors = [(x % 2, x) for x in w]
    r = conforms(
        lambda: paths.lexicographic_dijkstra(g, vectors, s, t, excluded=excluded),
        "lexicographic_dijkstra",
    )
    assert r.status is Status.OPTIMAL
    assert set(r.counters) == {"settled_nodes", "scanned_arcs"}
    reach = admitted_reach(g, (s,), excluded)
    assert (r.distance[t] is None) == (t not in reach)


# --- routes ------------------------------------------------------------------

ROUTE_COUNTERS = {"dijkstra_runs", "settled_nodes", "scanned_arcs"}


@given(case=instances(), data=st.data(), order=st.sampled_from(["free", "fixed"]))
def test_waypoint_route_conforms(case: Case, data: st.DataObject, order: str) -> None:
    g, w, s, t, excluded = case
    wps = tuple(data.draw(st.lists(st.integers(0, g.n - 1), max_size=3)))
    free = order == "free"
    r = conforms(
        lambda: routes.waypoint_route(
            g, w, s, t, wps, order="free" if free else "fixed", excluded=excluded
        ),
        "waypoint_route",
    )
    assert dict(r.parameters) == {"order": order}
    assert set(r.counters) == {*ROUTE_COUNTERS, "states"}
    assert r.counters["dijkstra_runs"] == len({s, *wps})
    if r.status is Status.OPTIMAL:
        assert r.certificate is None
        assert r.order is not None
        assert r.legs is not None
        return
    assert r.status is Status.INFEASIBLE
    assert (r.order, r.legs, r.arcs, r.cost) == (None, None, None, None)
    stops = (s, *wps, t)
    if isinstance(r.certificate, CrossedCuts):
        assert free
        pair = check_crossed_cuts(g, r.certificate, excluded)
        assert set(pair) <= set(wps)
        return
    cut = check_separating_cut(g, r.certificate, excluded)
    (a,) = cut.sources
    if not free or len(wps) <= 1:
        assert (a, cut.target) in set(itertools.pairwise(stops))
    elif a == s:
        assert cut.target in (*wps, t)
    else:
        assert (a, cut.target) in {(v, t) for v in wps}


@given(case=instances(), k=st.integers(1, 4))
def test_k_shortest_paths_conforms(case: Case, k: int) -> None:
    g, w, s, t, excluded = case
    r = conforms(
        lambda: routes.k_shortest_paths(g, w, s, t, k, excluded=excluded),
        "k_shortest_paths",
    )
    assert dict(r.parameters) == {"k": k}
    assert set(r.counters) == {*ROUTE_COUNTERS, "candidates"}
    assert len(r) <= k
    if r.status is Status.INFEASIBLE:
        assert len(r) == 0
        cut = check_separating_cut(g, r.certificate, excluded)
        assert (cut.sources, cut.target) == ((s,), t)
    else:
        assert r.status is Status.OPTIMAL
        assert len(r) >= 1
        assert r.certificate is None


@given(case=instances())
def test_replacement_paths_conforms(case: Case) -> None:
    g, w, s, t, excluded = case
    path = paths.dijkstra(g, w, s, excluded=excluded).path(t)
    arcs = () if path is None else path
    r = conforms(
        lambda: routes.replacement_paths(g, w, s, t, arcs, excluded=excluded),
        "replacement_paths",
    )
    assert r.status is Status.OPTIMAL
    assert set(r.counters) == ROUTE_COUNTERS
    assert r.counters["dijkstra_runs"] == len(set(arcs))
    assert [rep.arc for rep in r] == list(dict.fromkeys(arcs))
    for rep in r:
        reach = admitted_reach(g, (s,), excluded | {rep.arc})
        assert (rep.route is None) == (t not in reach)


@given(case=instances(), data=st.data())
def test_most_reliable_path_conforms(case: Case, data: st.DataObject) -> None:
    g, _, s, t, excluded = case
    p = [data.draw(st.sampled_from([0.0, 0.5, 0.9, 1.0])) for _ in range(g.m)]
    r = conforms(
        lambda: routes.most_reliable_path(g, p, s, t, excluded=excluded),
        "most_reliable_path",
    )
    assert set(r.counters) == ROUTE_COUNTERS
    if r.status is Status.OPTIMAL:
        assert r.arcs is not None
        assert r.probability is not None
        assert r.probability > 0
        return
    assert r.status is Status.INFEASIBLE
    assert (r.arcs, r.probability) == (None, None)
    barred = excluded | {a for a in range(g.m) if p[a] == 0}
    cut = check_separating_cut(g, r.certificate, barred)
    assert (cut.sources, cut.target) == ((s,), t)


# --- fingerprints and parameters ---------------------------------------------


def test_fingerprint_follows_the_inputs() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    same = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    base = paths.dijkstra(g, (1, 1, 3), 0, 2)
    assert paths.dijkstra(same, [1, 1, 3], [0], 2).inputs == base.inputs
    assert paths.dijkstra(g, (1, 1, 2), 0, 2).inputs != base.inputs
    assert paths.dijkstra(g, (1, 1, 3), 0).inputs != base.inputs
    assert paths.dijkstra(g, (1, 1, 3), 0, 2, excluded=[2]).inputs != base.inputs
    assert paths.dijkstra(g, (1, 1, 3.0), 0, 2).inputs != base.inputs
    assert paths.bellman_ford(g, (1, 1, 3), 0).inputs != (
        paths.bellman_ford(g, (1, 1, 3), 0, tolerance=1e-9).inputs
    )
    assert paths.bellman_ford(g, (1, 1, 3)).inputs == (
        paths.bellman_ford(g, (1, 1, 3), [0, 1, 2]).inputs
    )
    k2 = routes.k_shortest_paths(g, (1, 1, 3), 0, 2, 2)
    assert routes.k_shortest_paths(g, (1, 1, 3), 0, 2, 3).inputs != k2.inputs
    free = routes.waypoint_route(g, (1, 1, 3), 0, 2, [1], order="free")
    fixed = routes.waypoint_route(g, (1, 1, 3), 0, 2, [1], order="fixed")
    assert free.inputs != fixed.inputs
    keyed = routes.replacement_paths(g, (1, 1, 3), 0, 2, (0, 1), key="aab")
    assert keyed.inputs != routes.replacement_paths(g, (1, 1, 3), 0, 2, (0, 1)).inputs


# --- what a known client relies on -------------------------------------------


def test_client_uses_keep_working() -> None:
    # A road 0 - 1 - 2, a bypass 0 -> 2, and a spur 2 -> 3 (a bridge).
    g = Digraph.from_arcs(4, [(0, 1), (1, 2), (0, 2), (2, 3)])
    w = [1.0, 1.0, 5.0, 1.0]
    sp = paths.dijkstra(g, w, 0, 3, excluded={2})
    assert sp.distance[3] == 3.0
    assert sp.path(3) == (0, 1, 3)
    assert paths.dijkstra(g, w, 3, 0).path(0) is None
    assert [r.arcs for r in routes.k_shortest_paths(g, w, 0, 3, 3)] == [
        (0, 1, 3),
        (2, 3),
    ]
    found = {}
    for rep in routes.replacement_paths(g, w, 0, 3, (0, 1, 3)):
        found[rep.arc] = None if rep.route is None else (rep.route.cost, rep.route.arcs)
    assert found == {0: (6.0, (2, 3)), 1: (6.0, (2, 3)), 3: None}
    route = routes.waypoint_route(g, w, 0, 3, [1], order="free")
    assert route.status is Status.OPTIMAL
    assert (route.order, route.arcs) == ((0,), (0, 1, 3))
