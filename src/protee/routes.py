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

Provisional API (until version 1.0).
"""

import heapq
import itertools
import math
from collections.abc import Collection, Hashable, Sequence
from dataclasses import dataclass
from typing import Literal

from protee.graph import Digraph
from protee.paths import ShortestPaths, dijkstra

__all__ = [
    "ReliableRoute",
    "Replacement",
    "Route",
    "WaypointRoute",
    "k_shortest_paths",
    "most_reliable_path",
    "overlap",
    "replacement_paths",
    "waypoint_route",
]

type Number = int | float

#: Largest number of waypoints in free order (the dynamic programming
#: takes time and memory in ``2**k``).
MAX_FREE_WAYPOINTS = 16


@dataclass(frozen=True, slots=True)
class Route:
    """A path and its cost.

    Attributes
    ----------
    arcs : tuple of int
        The arcs in order; the head of each arc is the tail of the next.
    cost : int or float
        Sum of the weights of the arcs.
    """

    arcs: tuple[int, ...]
    cost: Number


@dataclass(frozen=True, slots=True)
class WaypointRoute:
    """A route through waypoints.

    Attributes
    ----------
    order : tuple of int
        Indices of the waypoints, in the order they are visited.
    legs : tuple of Route
        The ``k + 1`` legs: start to first waypoint, …, last waypoint to
        end.
    """

    order: tuple[int, ...]
    legs: tuple[Route, ...]

    @property
    def arcs(self) -> tuple[int, ...]:
        """All the arcs, leg after leg."""
        return tuple(a for leg in self.legs for a in leg.arcs)

    @property
    def cost(self) -> Number:
        """Total cost of the legs."""
        return sum(leg.cost for leg in self.legs)


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


@dataclass(frozen=True, slots=True)
class ReliableRoute:
    """The most reliable path.

    Attributes
    ----------
    arcs : tuple of int
        The arcs in order.
    probability : float
        Product of the reliabilities of its arcs: the probability that
        every arc is usable, when arcs fail independently.
    """

    arcs: tuple[int, ...]
    probability: float


def _cost(weight: Sequence[Number], arcs: Sequence[int]) -> Number:
    return sum(weight[a] for a in arcs)


def _route(tree: ShortestPaths, target: int) -> Route | None:
    arcs = tree.path(target)
    return None if arcs is None else Route(arcs, tree.distance[target])


def waypoint_route(
    graph: Digraph,
    weight: Sequence[Number],
    start: int,
    end: int,
    waypoints: Sequence[int],
    *,
    order: Literal["free", "fixed"],
    excluded: Collection[int] = (),
) -> WaypointRoute | None:
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
    WaypointRoute or None
        ``None`` when no order reaches every waypoint and the end.

    Raises
    ------
    ValueError
        If ``order`` is unknown, or more than ``MAX_FREE_WAYPOINTS``
        waypoints are given in free order.

    Notes
    -----
    One Dijkstra run from the start and from each distinct waypoint; the
    free order then costs :math:`O(2^k k^2)`. A route may pass through a
    node or an arc several times: the legs are independent shortest
    paths. Ties are broken towards the lowest waypoint indices.
    """
    if order not in ("free", "fixed"):
        raise ValueError(f"unknown order {order!r}: use 'free' or 'fixed'")
    k = len(waypoints)
    if order == "free" and k > MAX_FREE_WAYPOINTS:
        raise ValueError(f"{k} waypoints in free order: at most {MAX_FREE_WAYPOINTS}")
    trees = {
        t: dijkstra(graph, weight, t, excluded=excluded)
        for t in dict.fromkeys([start, *waypoints])
    }
    sequence: list[int] | None
    if order == "fixed" or k <= 1:
        sequence = list(range(k))
    else:
        sequence = _held_karp(trees, start, end, list(waypoints))
    if sequence is None:
        return None
    stops = [start, *(waypoints[i] for i in sequence), end]
    legs = []
    for a, b in itertools.pairwise(stops):
        leg = _route(trees[a], b)
        if leg is None:
            return None
        legs.append(leg)
    return WaypointRoute(tuple(sequence), tuple(legs))


def _held_karp(
    trees: dict[int, ShortestPaths], start: int, end: int, waypoints: list[int]
) -> list[int] | None:
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
    return sequence


def k_shortest_paths(
    graph: Digraph,
    weight: Sequence[Number],
    source: int,
    target: int,
    k: int,
    *,
    excluded: Collection[int] = (),
) -> list[Route]:
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
    list of Route
        At most ``k`` distinct paths, by increasing cost (ties: fewer
        arcs, then smaller arc indices); fewer when fewer exist.

    Raises
    ------
    ValueError
        If ``k`` is less than 1.

    Notes
    -----
    Yen (1971): each new path deviates from a previous one at a spur
    node, the root before it being kept. At most :math:`k \\cdot L`
    Dijkstra runs, with :math:`L` the number of arcs of the longest
    path found. Parallel arcs give distinct paths.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    first = _route(dijkstra(graph, weight, source, target, excluded=excluded), target)
    if first is None:
        return []
    found = [first]
    seen = {first.arcs}
    candidates: list[tuple[Number, int, tuple[int, ...]]] = []
    while len(found) < k:
        last = found[-1].arcs
        nodes = [source, *(graph.heads[a] for a in last)]
        for i in range(len(last)):
            root = last[:i]
            removed = set(excluded)
            for path in found:
                if path.arcs[:i] == root and len(path.arcs) > i:
                    removed.add(path.arcs[i])
            for v in nodes[:i]:
                removed.update(graph.out_arcs(v))
                removed.update(graph.in_arcs(v))
            tree = dijkstra(graph, weight, nodes[i], target, excluded=removed)
            spur = tree.path(target)
            if spur is None:
                continue
            candidate = root + spur
            if candidate not in seen:
                seen.add(candidate)
                heapq.heappush(
                    candidates, (_cost(weight, candidate), len(candidate), candidate)
                )
        if not candidates:
            break
        cost, _, arcs = heapq.heappop(candidates)
        found.append(Route(arcs, cost))
    return found


def _groups(graph: Digraph, key: Sequence[Hashable] | None) -> list[list[int]] | None:
    if key is None:
        return None
    if len(key) != graph.m:
        raise ValueError(f"expected {graph.m} keys, got {len(key)}")
    members: dict[Hashable, list[int]] = {}
    for a, kv in enumerate(key):
        members.setdefault(kv, []).append(a)
    return [members[kv] for kv in key]


def replacement_paths(
    graph: Digraph,
    weight: Sequence[Number],
    source: int,
    target: int,
    arcs: Sequence[int],
    *,
    key: Sequence[Hashable] | None = None,
    excluded: Collection[int] = (),
) -> tuple[Replacement, ...]:
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
        section).
    excluded : collection of int, optional
        Arcs to ignore in every computation.

    Returns
    -------
    tuple of Replacement
        One per distinct arc of the path, in path order.

    Notes
    -----
    One Dijkstra run per arc of the path. The most vital arc is the one
    whose replacement costs the most (``None`` meaning disconnection).
    """
    groups = _groups(graph, key)
    out = []
    for a in dict.fromkeys(arcs):
        removed = set(excluded)
        removed.update(groups[a] if groups is not None else (a,))
        tree = dijkstra(graph, weight, source, target, excluded=removed)
        out.append(Replacement(a, _route(tree, target)))
    return tuple(out)


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
) -> ReliableRoute | None:
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
    ReliableRoute or None
        ``None`` when the target cannot be reached.

    Raises
    ------
    ValueError
        If a reliability is outside [0, 1].

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
    weight = [-math.log(p) if p > 0 else 0.0 for p in reliability]
    removed = set(excluded) | {a for a, p in enumerate(reliability) if p == 0}
    arcs = dijkstra(graph, weight, source, target, excluded=removed).path(target)
    if arcs is None:
        return None
    return ReliableRoute(arcs, math.prod(reliability[a] for a in arcs))
