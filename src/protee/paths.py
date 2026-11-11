# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Shortest paths on a :class:`~protee.graph.Digraph`.

Two named methods, chosen explicitly by the caller:

- :func:`dijkstra`, for non-negative arc weights;
- :func:`bellman_ford`, for any weights, which returns a
  :class:`NegativeCycle` certificate when distances are unbounded.

Provisional API (until version 1.0).
"""

import heapq
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from protee.graph import Digraph

__all__ = ["NegativeCycle", "ShortestPaths", "bellman_ford", "dijkstra"]

type Number = int | float


@dataclass(frozen=True, slots=True)
class NegativeCycle:
    """A directed cycle of negative total weight.

    Attributes
    ----------
    arcs : tuple of int
        The arcs of the cycle, in order: the head of each arc is the tail
        of the next one, and the head of the last is the tail of the first.
    weight : int or float
        Total weight of the cycle (negative).
    """

    arcs: tuple[int, ...]
    weight: Number


@dataclass(frozen=True, slots=True)
class ShortestPaths:
    """Shortest path tree from one or several sources.

    Attributes
    ----------
    sources : tuple of int
        The sources, at distance 0.
    distance : tuple of float
        Distance of each node, ``math.inf`` when it is unreachable.
    predecessor : tuple of int
        Last arc of a shortest path to each node, ``-1`` for a source or an
        unreachable node.
    """

    sources: tuple[int, ...]
    distance: tuple[Number, ...]
    predecessor: tuple[int, ...]
    _heads: tuple[int, ...]
    _tails: tuple[int, ...]

    def path(self, target: int) -> tuple[int, ...] | None:
        """Arcs of a shortest path from a source to ``target``.

        Returns
        -------
        tuple of int or None
            The arcs in order (empty when ``target`` is a source), or
            ``None`` when ``target`` is unreachable.
        """
        if self.distance[target] == math.inf:
            return None
        arcs: list[int] = []
        v = target
        while (a := self.predecessor[v]) != -1:
            arcs.append(a)
            v = self._tails[a]
        arcs.reverse()
        return tuple(arcs)


def _sources(graph: Digraph, source: int | Iterable[int]) -> tuple[int, ...]:
    found = (source,) if isinstance(source, int) else tuple(dict.fromkeys(source))
    for s in found:
        if not 0 <= s < graph.n:
            raise ValueError(f"source {s} is not a node")
    return found


def _check_weights(graph: Digraph, weight: Sequence[Number]) -> None:
    if len(weight) != graph.m:
        raise ValueError(f"expected {graph.m} weights, got {len(weight)}")
    for a, w in enumerate(weight):
        if not math.isfinite(w):
            raise ValueError(f"the weight of arc {a} is not finite: {w}")


def dijkstra(
    graph: Digraph,
    weight: Sequence[Number],
    source: int | Iterable[int],
    target: int | None = None,
) -> ShortestPaths:
    """Shortest paths with non-negative weights (Dijkstra, binary heap).

    Parameters
    ----------
    graph : Digraph
    weight : sequence of int or float
        One non-negative weight per arc.
    source : int or iterable of int
        One source, or several sources all at distance 0.
    target : int, optional
        Stop as soon as the distance of ``target`` is final. Nodes not yet
        settled then keep a provisional distance, at least the true one.

    Returns
    -------
    ShortestPaths

    Raises
    ------
    ValueError
        If a weight is negative or not finite, or a source is not a node.

    Notes
    -----
    Complexity :math:`O((n + m) \\log n)`.
    """
    _check_weights(graph, weight)
    for a, w in enumerate(weight):
        if w < 0:
            raise ValueError(
                f"the weight of arc {a} is negative ({w}): use bellman_ford"
            )
    sources = _sources(graph, source)
    dist: list[Number] = [math.inf] * graph.n
    pred = [-1] * graph.n
    done = [False] * graph.n
    heap: list[tuple[Number, int]] = []
    for s in sources:
        dist[s] = 0
        heap.append((0, s))
    heapq.heapify(heap)
    while heap:
        d, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        if u == target:
            break
        for a in graph.out_arcs(u):
            v = graph.heads[a]
            new_dist = d + weight[a]
            if new_dist < dist[v]:
                dist[v] = new_dist
                pred[v] = a
                heapq.heappush(heap, (new_dist, v))
    return ShortestPaths(sources, tuple(dist), tuple(pred), graph.heads, graph.tails)


def _negative_cycle_from(
    graph: Digraph, weight: Sequence[Number], pred: list[int], start: int
) -> NegativeCycle:
    """Walk back the predecessors from a node relaxed in round n."""
    v = start
    for _ in range(graph.n):
        v = graph.tails[pred[v]]
    arcs = [pred[v]]
    u = graph.tails[pred[v]]
    while u != v:
        arcs.append(pred[u])
        u = graph.tails[pred[u]]
    arcs.reverse()
    return NegativeCycle(tuple(arcs), sum(weight[a] for a in arcs))


def bellman_ford(
    graph: Digraph,
    weight: Sequence[Number],
    source: int | Iterable[int] | None = None,
    *,
    tolerance: float = 0.0,
) -> ShortestPaths | NegativeCycle:
    """Shortest paths with any weights, or a negative cycle (Bellman-Ford).

    Parameters
    ----------
    graph : Digraph
    weight : sequence of int or float
        One weight per arc.
    source : int or iterable of int, optional
        The sources. Without a source, every node starts at distance 0, as
        if a virtual source reached each of them: any negative cycle of the
        graph is then found.
    tolerance : float, optional
        A distance improves only by more than ``tolerance``; for float
        weights, it keeps rounding errors from showing a false cycle.

    Returns
    -------
    ShortestPaths or NegativeCycle
        The shortest paths, or a cycle of negative weight reachable from
        the sources.

    Notes
    -----
    Complexity :math:`O(nm)`.
    """
    _check_weights(graph, weight)
    if source is None:
        sources = tuple(range(graph.n))
        dist: list[Number] = [0] * graph.n
    else:
        sources = _sources(graph, source)
        dist = [math.inf] * graph.n
        for s in sources:
            dist[s] = 0
    pred = [-1] * graph.n
    changed = -1
    for _ in range(graph.n):
        changed = -1
        for a, (u, v) in enumerate(graph.arcs()):
            if dist[u] != math.inf and dist[u] + weight[a] < dist[v] - tolerance:
                dist[v] = dist[u] + weight[a]
                pred[v] = a
                changed = v
        if changed == -1:
            break
    if changed == -1:
        return ShortestPaths(
            sources, tuple(dist), tuple(pred), graph.heads, graph.tails
        )
    return _negative_cycle_from(graph, weight, pred, changed)
