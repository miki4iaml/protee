# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause
"""Route-level algorithms built on shortest paths.

- :func:`waypoint_route`: a route through given waypoints, in a free
  order (exact, Held-Karp dynamic programming over the waypoints) or in
  a fixed order;
- :func:`k_shortest_paths`: the ``k`` shortest loopless paths (Yen);
- :func:`replacement_paths`: for each arc of a path, the shortest path
  that avoids it; the arc whose loss costs the most is the most vital
  one, which measures the resilience of a route;
- :func:`overlap`: the share of a route that another one also uses;
- :func:`most_reliable_path`: the path that maximizes the product of
  independent arc reliabilities, for networks whose arcs are uncertain
  (extracted from images, for example).

Every function takes ``excluded`` arcs, ignored as if removed. Weights
are non-negative, as for :func:`protee.paths.dijkstra`; results are
deterministic.

Every function that solves (all but :func:`overlap`) returns a result
built on :class:`~protee.results.ResultCore` (see :func:`methods`). When
no route exists, its status is ``infeasible``, its certificate a
:class:`SeparatingCut` (or :class:`CrossedCuts` for waypoints in free
order), and its route fields are ``None``.

Provisional API (until version 1.0).
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Collection, Hashable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, overload

from protee.graph import Digraph
from protee.paths import (
    _check_nonnegative,
    _dijkstra,
    _node,
    _reached,
    _registry,
    _Run,
    _separating_cut,
    _skip,
    _sum_along,
    _walk,
)
from protee.results import (
    CrossedCuts,
    Guarantee,
    GuaranteeKind,
    MethodInfo,
    ResultCore,
    SeparatingCut,
    Status,
)

__all__ = [
    "CrossedCuts",
    "KShortestPaths",
    "ReliableRoute",
    "Replacement",
    "ReplacementPaths",
    "Route",
    "SeparatingCut",
    "WaypointRoute",
    "k_shortest_paths",
    "methods",
    "most_reliable_path",
    "overlap",
    "replacement_paths",
    "waypoint_route",
]

type Number = int | float

#: Largest number of waypoints in free order (the dynamic programming
#: takes time and memory in ``2**k``).
MAX_FREE_WAYPOINTS = 16

_EXACT = GuaranteeKind.EXACT

_METHODS: Mapping[str, MethodInfo] = MappingProxyType(
    {
        "waypoint_route": MethodInfo(
            name="waypoint_route",
            problem="waypoint_route",
            summary="Shortest legs between the terminals (one Dijkstra run from "
            "the start and from each distinct waypoint), in the given order or "
            "in the best one, by dynamic programming over the waypoints.",
            guarantee=Guarantee(
                _EXACT,
                "shortest route through every waypoint: in the given order, or "
                "over every order (Held-Karp)",
            ),
            complexity="k + 1 Dijkstra runs, then O(2^k k^2) in free order, "
            "k the number of waypoints",
            reference="Held, Karp (1962); Bellman (1962)",
            options=("order",),
        ),
        "k_shortest_paths": MethodInfo(
            name="k_shortest_paths",
            problem="k_shortest_paths",
            summary="Yen's deviations: each new path leaves a previous one at a "
            "spur node, the root before it being kept.",
            guarantee=Guarantee(
                _EXACT,
                "the k shortest loopless paths by increasing cost, all of them "
                "when fewer exist",
            ),
            complexity="O(k n (n + m) log n): at most k n Dijkstra runs with a "
            "binary heap",
            reference="Yen (1971)",
            options=("k",),
        ),
        "replacement_paths": MethodInfo(
            name="replacement_paths",
            problem="replacement_paths",
            summary="One Dijkstra run per arc of the path, without the arc and "
            "its group.",
            guarantee=Guarantee(
                _EXACT,
                "for each arc of the path, the shortest path that avoids it, or "
                "none when its removal disconnects the target",
            ),
            complexity="O(L (n + m) log n), L the number of arcs of the path",
            reference="Malik, Mittal, Gupta (1989)",
        ),
        "most_reliable_path": MethodInfo(
            name="most_reliable_path",
            problem="most_reliable_path",
            summary="Dijkstra on the weights -log p, which turn the product of "
            "the reliabilities into a sum.",
            guarantee=Guarantee(
                _EXACT, "path of greatest product of the arc reliabilities"
            ),
            complexity="O((n + m) log n)",
            reference="Dijkstra (1959), on the weights -log p",
        ),
    }
)


def methods(problem: str | None = None) -> tuple[MethodInfo, ...]:
    """The route methods, in a fixed order.

    Each route problem has one method, named after its function.

    Parameters
    ----------
    problem : str, optional
        ``"waypoint_route"``, ``"k_shortest_paths"``,
        ``"replacement_paths"`` or ``"most_reliable_path"``; every method of
        the module by default.

    Returns
    -------
    tuple of MethodInfo

    Raises
    ------
    ValueError
        If ``problem`` is not one of this module.
    """
    return _registry(_METHODS.values(), problem)


@dataclass(frozen=True, slots=True)
class Route:
    """A path and its cost.

    Attributes
    ----------
    arcs : tuple of int
        The arcs in order; the head of each arc is the tail of the next.
    cost : int or float
        Sum of the weights of the arcs, from left to right, as Dijkstra
        adds them: the distance of the end of the path.
    """

    arcs: tuple[int, ...]
    cost: Number


@dataclass(frozen=True, slots=True)
class Replacement:
    """Shortest path avoiding one arc of a route.

    Attributes
    ----------
    arc : int
        The arc removed (with every arc of the same group when a ``key``
        is given).
    route : Route or None
        The shortest path without it, or ``None`` when the target can no
        longer be reached.
    """

    arc: int
    route: Route | None


@dataclass(frozen=True, slots=True, kw_only=True)
class WaypointRoute(ResultCore):
    """A route through waypoints.

    On top of the fields of :class:`~protee.results.ResultCore`:

    Attributes
    ----------
    order : tuple of int or None
        Indices of the waypoints, in the order they are visited; ``None``
        when no route exists.
    legs : tuple of Route or None
        The ``k + 1`` legs: start to first waypoint, …, last waypoint to
        end; ``None`` when no route exists.

    Notes
    -----
    ``infeasible``: the certificate is a :class:`SeparatingCut` (a leg
    whose end is out of reach), or :class:`CrossedCuts` in free order (two
    waypoints, neither reaching the other).

    ``counters``: ``dijkstra_runs``, ``settled_nodes`` and ``scanned_arcs``
    (summed over the runs), and ``states`` of the dynamic programming over
    the waypoints (0 without it). ``inputs`` covers the graph, the weights,
    the start, the end, the waypoints and the excluded arcs.
    """

    order: tuple[int, ...] | None = None
    legs: tuple[Route, ...] | None = None

    @property
    def arcs(self) -> tuple[int, ...] | None:
        """All the arcs, leg after leg; ``None`` when no route exists."""
        if self.legs is None:
            return None
        return tuple(a for leg in self.legs for a in leg.arcs)

    @property
    def cost(self) -> Number | None:
        """Total cost of the legs, added from the first to the last, as the
        free order compares them; ``None`` when no route exists."""
        if self.legs is None:
            return None
        return _sum_along(leg.cost for leg in self.legs)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReliableRoute(ResultCore):
    """The most reliable path.

    On top of the fields of :class:`~protee.results.ResultCore`:

    Attributes
    ----------
    arcs : tuple of int or None
        The arcs in order; ``None`` when the target cannot be reached.
    probability : float or None
        Product of the reliabilities of its arcs: the probability that
        every arc is usable, when arcs fail independently; ``None`` when
        the target cannot be reached.

    Notes
    -----
    ``infeasible``: the certificate is a :class:`SeparatingCut`, whose
    arcs are excluded or of zero reliability.

    ``counters``: ``dijkstra_runs``, ``settled_nodes`` and
    ``scanned_arcs``. ``inputs`` covers the graph, the reliabilities, the
    source, the target and the excluded arcs.
    """

    arcs: tuple[int, ...] | None = None
    probability: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class KShortestPaths(ResultCore):
    """The ``k`` shortest loopless paths.

    On top of the fields of :class:`~protee.results.ResultCore`; iterates,
    indexes and measures like the tuple of its routes.

    Attributes
    ----------
    routes : tuple of Route
        At most ``k`` distinct paths, by non-decreasing cost (ties as
        :func:`k_shortest_paths` states); fewer when fewer exist (the status
        stays ``optimal``), none when the target is out of reach
        (``infeasible``, with a :class:`SeparatingCut`).

    Notes
    -----
    ``counters``: ``dijkstra_runs``, ``settled_nodes``, ``scanned_arcs``
    and ``candidates`` (distinct candidate paths). ``inputs`` covers the
    graph, the weights, the source, the target and the excluded arcs.
    """

    routes: tuple[Route, ...] = ()

    def __iter__(self) -> Iterator[Route]:
        return iter(self.routes)

    def __len__(self) -> int:
        return len(self.routes)

    @overload
    def __getitem__(self, index: int) -> Route: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Route, ...]: ...

    def __getitem__(self, index: int | slice) -> Route | tuple[Route, ...]:
        return self.routes[index]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplacementPaths(ResultCore):
    """For each arc of a path, the shortest path that avoids it.

    On top of the fields of :class:`~protee.results.ResultCore`; iterates,
    indexes and measures like the tuple of its replacements.

    Attributes
    ----------
    replacements : tuple of Replacement
        One per distinct arc of the path, in path order; the route of a
        replacement is ``None`` when the removal disconnects the target.
        The status is ``optimal``: each replacement is exact.

    Notes
    -----
    ``counters``: ``dijkstra_runs``, ``settled_nodes`` and
    ``scanned_arcs``. ``inputs`` covers the graph, the weights, the
    source, the target, the arcs of the path, the keys and the excluded
    arcs.
    """

    replacements: tuple[Replacement, ...] = ()

    def __iter__(self) -> Iterator[Replacement]:
        return iter(self.replacements)

    def __len__(self) -> int:
        return len(self.replacements)

    @overload
    def __getitem__(self, index: int) -> Replacement: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Replacement, ...]: ...

    def __getitem__(self, index: int | slice) -> Replacement | tuple[Replacement, ...]:
        return self.replacements[index]


# --- kernels -----------------------------------------------------------------


def _work() -> dict[str, int]:
    return {"dijkstra_runs": 0, "settled_nodes": 0, "scanned_arcs": 0}


def _run(
    graph: Digraph,
    weight: Sequence[Number],
    source: int,
    target: int | None,
    skip: Sequence[bool],
    work: dict[str, int],
    start: Number = 0,
) -> _Run:
    """One Dijkstra run, counted in ``work``; ``source`` starts at distance
    ``start``."""
    run = _dijkstra(graph, weight, (source,), target, skip, start)
    work["dijkstra_runs"] += 1
    work["settled_nodes"] += run.settled
    work["scanned_arcs"] += run.scanned
    return run


def _cut(graph: Digraph, run: _Run, source: int, target: int) -> SeparatingCut:
    return _separating_cut(graph, _reached(run.distance), (source,), target)


def _held_karp(
    trees: dict[int, _Run],
    start: int,
    end: int,
    waypoints: Sequence[int],
    work: dict[str, int],
) -> tuple[int, ...] | None:
    k = len(waypoints)

    def d(a: int, b: int) -> Number:
        return trees[a].distance[b]

    full = (1 << k) - 1
    best: dict[tuple[int, int], tuple[Number, int]] = {}
    for j in range(k):
        best[(1 << j, j)] = (d(start, waypoints[j]), -1)
    for mask in range(1, full + 1):
        for j in range(k):
            if not mask >> j & 1 or (mask, j) not in best:
                continue
            cost, _ = best[(mask, j)]
            if cost == math.inf:
                continue
            for nxt in range(k):
                if mask >> nxt & 1:
                    continue
                key = (mask | 1 << nxt, nxt)
                new = cost + d(waypoints[j], waypoints[nxt])
                if key not in best or new < best[key][0]:
                    best[key] = (new, j)
    work["states"] = len(best)
    total, last = math.inf, -1
    for j in range(k):
        if (full, j) in best:
            c = best[(full, j)][0] + d(waypoints[j], end)
            if c < total:
                total, last = c, j
    if total == math.inf:
        return None
    sequence, mask = [], full
    while last != -1:
        sequence.append(last)
        prev = best[(mask, last)][1]
        mask &= ~(1 << last)
        last = prev
    sequence.reverse()
    return tuple(sequence)


def _no_order(
    graph: Digraph,
    trees: dict[int, _Run],
    start: int,
    end: int,
    waypoints: Sequence[int],
) -> SeparatingCut | CrossedCuts:
    """Why no order of the waypoints gives a route.

    Reachability is transitive: a route exists unless the start misses a
    terminal, a waypoint misses the end, or two waypoints miss each other.
    """

    def reaches(a: int, b: int) -> bool:
        return trees[a].distance[b] != math.inf

    for b in (*waypoints, end):
        if not reaches(start, b):
            return _cut(graph, trees[start], start, b)
    for a in waypoints:
        if not reaches(a, end):
            return _cut(graph, trees[a], a, end)
    a, b = next(
        (a, b)
        for i, a in enumerate(waypoints)
        for b in waypoints[i + 1 :]
        if not reaches(a, b) and not reaches(b, a)
    )
    return CrossedCuts(_cut(graph, trees[a], a, b), _cut(graph, trees[b], b, a))


# --- public functions --------------------------------------------------------


def waypoint_route(
    graph: Digraph,
    weight: Sequence[Number],
    start: int,
    end: int,
    waypoints: Sequence[int],
    *,
    order: Literal["free", "fixed"],
    excluded: Collection[int] = (),
) -> WaypointRoute:
    """Shortest route from ``start`` to ``end`` through every waypoint.

    Parameters
    ----------
    graph : Digraph
    weight : sequence of int or float
        One non-negative weight per arc.
    start, end : int
    waypoints : sequence of int
        Nodes to visit.
    order : {"free", "fixed"}
        ``"fixed"``: in the given order. ``"free"``: in the order of least
        total cost, found exactly by dynamic programming (Held-Karp) over
        the shortest distances between the terminals.
    excluded : collection of int, optional
        Arcs to ignore.

    Returns
    -------
    WaypointRoute
        Status ``optimal`` with the order and the legs, or ``infeasible``
        when no order reaches every waypoint and the end: ``order``,
        ``legs``, ``arcs`` and ``cost`` are then ``None``, and the
        certificate is a :class:`SeparatingCut` (a terminal out of reach of
        the one before it) or, in free order, :class:`CrossedCuts` (two
        waypoints, neither reaching the other). Parameters: ``order``.
        Counters: ``dijkstra_runs``, ``settled_nodes``, ``scanned_arcs``
        (summed over the runs) and ``states`` (states of the dynamic
        programming, 0 without it).

    Raises
    ------
    ValueError
        If ``order`` is unknown, more than ``MAX_FREE_WAYPOINTS``
        waypoints are given in free order, a weight is negative or not
        finite, ``k + 1`` times the sum of the absolute weights of the arcs
        not excluded is beyond the float range when one of them is not an
        int (the float cost of a route of ``k + 1`` legs could overflow;
        ints sum exactly, whatever their size), or a terminal or an
        excluded arc does not exist.

    Notes
    -----
    One Dijkstra run from the start and from each distinct waypoint; the
    free order then costs :math:`O(2^k k^2)`. A route may pass through a
    node or an arc several times: the legs are independent shortest
    paths. Each leg costs the distance of its end, and the cost of the
    route adds the legs in order, as the free order compares them. In
    free order, ties between orders of equal cost are broken from the end
    of the order: the last waypoint visited has the lowest index possible,
    then the one before it, and so on. When every order costs the same,
    the order is therefore the reverse of the given one.
    """
    if order not in ("free", "fixed"):
        raise ValueError(f"unknown order {order!r}: use 'free' or 'fixed'")
    k = len(waypoints)
    if order == "free" and k > MAX_FREE_WAYPOINTS:
        raise ValueError(f"{k} waypoints in free order: at most {MAX_FREE_WAYPOINTS}")
    skip = _skip(graph, excluded)
    total = _check_nonnegative(graph, weight, skip)
    if total is not None and not math.isfinite((k + 1) * total):
        raise ValueError(
            f"{k + 1} legs times the sum of the absolute weights is beyond the "
            "float range: the cost of a route could overflow"
        )
    stops = tuple(waypoints)
    _node(graph, start, "start")
    _node(graph, end, "end")
    for v in stops:
        _node(graph, v, "waypoint")
    work = _work()
    work["states"] = 0
    trees = {
        t: _run(graph, weight, t, None, skip, work)
        for t in dict.fromkeys([start, *stops])
    }

    def result(
        certificate: SeparatingCut | CrossedCuts | None = None,
        sequence: tuple[int, ...] | None = None,
        legs: tuple[Route, ...] | None = None,
    ) -> WaypointRoute:
        return WaypointRoute(
            status=Status.INFEASIBLE if legs is None else Status.OPTIMAL,
            method="waypoint_route",
            guarantee=_METHODS["waypoint_route"].guarantee,
            parameters={"order": order},
            counters=work,
            certificate=certificate,
            order=sequence,
            legs=legs,
            _sources=(graph, tuple(weight), start, end, stops, frozenset(excluded)),
        )

    sequence: tuple[int, ...] | None
    if order == "fixed" or k <= 1:
        sequence = tuple(range(k))
    else:
        sequence = _held_karp(trees, start, end, stops, work)
        if sequence is None:
            return result(_no_order(graph, trees, start, end, stops))
    terminals = [start, *(stops[i] for i in sequence), end]
    legs = []
    for a, b in itertools.pairwise(terminals):
        tree = trees[a]
        if tree.distance[b] == math.inf:
            return result(_cut(graph, tree, a, b))
        legs.append(Route(_walk(tree.predecessor, graph.tails, b), tree.distance[b]))
    return result(None, sequence, tuple(legs))


def _yen(
    graph: Digraph,
    weight: Sequence[Number],
    source: int,
    target: int,
    k: int,
    skip: Sequence[bool],
    work: dict[str, int],
) -> tuple[list[Route], SeparatingCut | None]:
    """Yen's algorithm: the routes, or the cut when there is none.

    Every cost adds the weights of its route from left to right, as
    Dijkstra does: the search from a spur node starts from the cost of the
    root before it, so that its distances are the costs of whole routes.
    Each new route is then the cheapest one not yet found, by these very
    costs, and the costs do not decrease, even where floats round.
    """
    first = _run(graph, weight, source, target, skip, work)
    if first.distance[target] == math.inf:
        return [], _cut(graph, first, source, target)
    found = [
        Route(_walk(first.predecessor, graph.tails, target), first.distance[target])
    ]
    seen = {found[0].arcs}
    candidates: list[tuple[Number, int, tuple[int, ...]]] = []
    while len(found) < k:
        last = found[-1].arcs
        nodes = [source, *(graph.heads[a] for a in last)]
        root_cost: Number = 0
        for i in range(len(last)):
            if i:
                root_cost += weight[last[i - 1]]
            root = last[:i]
            barred = list(skip)
            for path in found:
                if path.arcs[:i] == root and len(path.arcs) > i:
                    barred[path.arcs[i]] = True
            for v in nodes[:i]:
                for a in (*graph.out_arcs(v), *graph.in_arcs(v)):
                    barred[a] = True
            tree = _run(graph, weight, nodes[i], target, barred, work, root_cost)
            cost = tree.distance[target]
            if cost == math.inf:
                continue
            candidate = root + _walk(tree.predecessor, graph.tails, target)
            if candidate not in seen:
                seen.add(candidate)
                work["candidates"] += 1
                heapq.heappush(candidates, (cost, len(candidate), candidate))
        if not candidates:
            break
        cost, _, arcs = heapq.heappop(candidates)
        found.append(Route(arcs, cost))
    return found, None


def k_shortest_paths(
    graph: Digraph,
    weight: Sequence[Number],
    source: int,
    target: int,
    k: int,
    *,
    excluded: Collection[int] = (),
) -> KShortestPaths:
    """The ``k`` shortest loopless paths from ``source`` to ``target`` (Yen).

    Parameters
    ----------
    graph : Digraph
    weight : sequence of int or float
        One non-negative weight per arc.
    source, target : int
    k : int
        Number of paths wanted, at least 1.
    excluded : collection of int, optional
        Arcs to ignore.

    Returns
    -------
    KShortestPaths
        At most ``k`` distinct paths, by non-decreasing cost; fewer when
        fewer exist, with the status ``optimal`` (the enumeration is
        exhaustive); none when the target is out of reach, with the status
        ``infeasible`` and a :class:`SeparatingCut`. It iterates like the
        tuple of its routes. Parameters: ``k``. Counters:
        ``dijkstra_runs``, ``settled_nodes``, ``scanned_arcs`` and
        ``candidates`` (distinct candidate paths).

    Raises
    ------
    ValueError
        If ``k`` is less than 1, a weight is negative or not finite, the
        absolute weights of the arcs not excluded sum beyond the float
        range when one of them is not an int (a float sum along a path
        could overflow; ints sum exactly, whatever their size), or a node
        or an excluded arc does not exist.

    Notes
    -----
    Yen (1971): each new path deviates from a previous one at a spur
    node, the root before it being kept. At most :math:`k \\cdot L`
    Dijkstra runs, with :math:`L` the number of arcs of the longest
    path found. Parallel arcs give distinct paths.

    The cost of every route adds its weights from left to right, as
    :func:`protee.paths.dijkstra` does: the first route costs the distance
    of the target, and the costs do not decrease even where floats round
    (``sum()``, which compensates the rounding, can give another float).

    Ties are broken deterministically, but not by the number of arcs
    across the whole list. The first route is the path to the target in
    the tree of :func:`protee.paths.dijkstra`. Each next route is, among
    the candidate deviations found so far, the least by cost, then number
    of arcs, then arc indices (compared as tuples). Since candidates are
    found lazily, a route of equal cost and fewer arcs may come later.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    skip = _skip(graph, excluded)
    _check_nonnegative(graph, weight, skip)
    _node(graph, source, "source")
    _node(graph, target, "target")
    work = _work()
    work["candidates"] = 0
    routes, cut = _yen(graph, weight, source, target, k, skip, work)
    return KShortestPaths(
        status=Status.OPTIMAL if routes else Status.INFEASIBLE,
        method="k_shortest_paths",
        guarantee=_METHODS["k_shortest_paths"].guarantee,
        parameters={"k": k},
        counters=work,
        certificate=cut,
        routes=tuple(routes),
        _sources=(graph, tuple(weight), source, target, frozenset(excluded)),
    )


def _groups(graph: Digraph, key: Sequence[Hashable] | None) -> list[list[int]] | None:
    if key is None:
        return None
    if len(key) != graph.m:
        raise ValueError(f"expected {graph.m} keys, got {len(key)}")
    members: dict[Hashable, list[int]] = {}
    for a, kv in enumerate(key):
        members.setdefault(kv, []).append(a)
    return [members[kv] for kv in key]


def _replacements(
    graph: Digraph,
    weight: Sequence[Number],
    source: int,
    target: int,
    path: Sequence[int],
    groups: list[list[int]] | None,
    skip: Sequence[bool],
    work: dict[str, int],
) -> list[Replacement]:
    out = []
    for a in dict.fromkeys(path):
        barred = list(skip)
        for b in groups[a] if groups is not None else (a,):
            barred[b] = True
        tree = _run(graph, weight, source, target, barred, work)
        route = None
        if tree.distance[target] != math.inf:
            arcs = _walk(tree.predecessor, graph.tails, target)
            route = Route(arcs, tree.distance[target])
        out.append(Replacement(a, route))
    return out


def replacement_paths(
    graph: Digraph,
    weight: Sequence[Number],
    source: int,
    target: int,
    arcs: Sequence[int],
    *,
    key: Sequence[Hashable] | None = None,
    excluded: Collection[int] = (),
) -> ReplacementPaths:
    """For each arc of a path, the shortest path that avoids it.

    Parameters
    ----------
    graph : Digraph
    weight : sequence of int or float
        One non-negative weight per arc.
    source, target : int
    arcs : sequence of int
        The arcs of a path from ``source`` to ``target``.
    key : sequence of hashable, optional
        One key per arc of the graph; removing an arc removes every arc
        with the same key (for example the two directions of one road
        section). The keys are inputs of the result: with a key of a type
        that the fingerprint does not support (``bytes``, an instance of an
        ordinary class...), the computation succeeds but reading
        ``inputs`` raises ``TypeError``. Integers, strings, and tuples of
        them are supported (see ``protee.constraints.fingerprint``).
    excluded : collection of int, optional
        Arcs to ignore in every computation.

    Returns
    -------
    ReplacementPaths
        One :class:`Replacement` per distinct arc of the path, in path
        order; it iterates like the tuple of its replacements. Status
        ``optimal``. Counters: ``dijkstra_runs``, ``settled_nodes`` and
        ``scanned_arcs``.

    Raises
    ------
    ValueError
        If the keys do not match the arcs, a weight is negative or not
        finite, the absolute weights of the arcs not excluded sum beyond
        the float range when one of them is not an int (a float sum along
        a path could overflow; ints sum exactly, whatever their size), or
        a node, an arc of the path or an excluded arc does not exist.

    Notes
    -----
    One Dijkstra run per arc of the path; the cost of a replacement is
    the distance of the target. The most vital arc is the one whose
    replacement costs the most (``None`` meaning disconnection).
    """
    groups = _groups(graph, key)
    skip = _skip(graph, excluded)
    _check_nonnegative(graph, weight, skip)
    _node(graph, source, "source")
    _node(graph, target, "target")
    path = tuple(arcs)
    for a in path:
        if not 0 <= a < graph.m:
            raise ValueError(f"arc {a} of the path does not exist")
    work = _work()
    found = _replacements(graph, weight, source, target, path, groups, skip, work)
    return ReplacementPaths(
        status=Status.OPTIMAL,
        method="replacement_paths",
        guarantee=_METHODS["replacement_paths"].guarantee,
        counters=work,
        replacements=tuple(found),
        _sources=(
            graph,
            tuple(weight),
            source,
            target,
            path,
            None if key is None else tuple(key),
            frozenset(excluded),
        ),
    )


def overlap(
    weight: Sequence[Number],
    first: Sequence[int],
    second: Sequence[int],
    *,
    key: Sequence[Hashable] | None = None,
) -> float:
    """Share of the weight of ``first`` that ``second`` also uses.

    Parameters
    ----------
    weight : sequence of int or float
        One weight per arc (lengths, for a share of the distance).
    first, second : sequence of int
        Two paths (or any sets of arcs).
    key : sequence of hashable, optional
        One key per arc; arcs with the same key count as the same element
        (the two directions of one road section, for example).

    Returns
    -------
    float
        Between 0 and 1; 0 when ``first`` has no weight.
    """

    def k(a: int) -> Hashable:
        return a if key is None else key[a]

    used = {k(a) for a in second}
    total = sum(weight[a] for a in first)
    if total == 0:
        return 0.0
    shared = sum(weight[a] for a in first if k(a) in used)
    return shared / total


def most_reliable_path(
    graph: Digraph,
    reliability: Sequence[float],
    source: int,
    target: int,
    *,
    excluded: Collection[int] = (),
) -> ReliableRoute:
    """Path of greatest reliability, arcs failing independently.

    Parameters
    ----------
    graph : Digraph
    reliability : sequence of float
        Probability, between 0 and 1, that each arc is usable. Arcs of
        reliability 0 are never used.
    source, target : int
    excluded : collection of int, optional
        Arcs to ignore.

    Returns
    -------
    ReliableRoute
        Status ``optimal`` with the arcs and their probability, or
        ``infeasible`` when the target cannot be reached: ``arcs`` and
        ``probability`` are then ``None``, and the certificate is a
        :class:`SeparatingCut` whose arcs are excluded or of reliability
        0. Counters: ``dijkstra_runs``, ``settled_nodes`` and
        ``scanned_arcs``.

    Raises
    ------
    ValueError
        If a reliability is outside [0, 1], or a node or an excluded arc
        does not exist.

    Notes
    -----
    A shortest path for the weights :math:`-\\log p`, which turns the
    product of probabilities into a sum. The same weights, scaled and
    added to lengths or times, trade cost against reliability.
    """
    if len(reliability) != graph.m:
        raise ValueError(f"expected {graph.m} reliabilities, got {len(reliability)}")
    for a, p in enumerate(reliability):
        if not 0 <= p <= 1:
            raise ValueError(f"the reliability of arc {a} is not in [0, 1]: {p}")
    _node(graph, source, "source")
    _node(graph, target, "target")
    skip = _skip(graph, excluded)
    for a, p in enumerate(reliability):
        if p == 0:
            skip[a] = True
    weight = [-math.log(p) if p > 0 else 0.0 for p in reliability]
    work = _work()
    run = _run(graph, weight, source, target, skip, work)
    arcs: tuple[int, ...] | None = None
    probability: float | None = None
    cut: SeparatingCut | None = None
    if run.distance[target] == math.inf:
        cut = _cut(graph, run, source, target)
    else:
        arcs = _walk(run.predecessor, graph.tails, target)
        probability = math.prod(reliability[a] for a in arcs)
    return ReliableRoute(
        status=Status.INFEASIBLE if arcs is None else Status.OPTIMAL,
        method="most_reliable_path",
        guarantee=_METHODS["most_reliable_path"].guarantee,
        counters=work,
        certificate=cut,
        arcs=arcs,
        probability=probability,
        _sources=(graph, tuple(reliability), source, target, frozenset(excluded)),
    )
