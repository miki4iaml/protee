# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Cycle canceling and successive shortest paths, on the standard form.

Both work on the residual network of the standard form: arc ``a`` gives a
forward residual edge while ``y[a] < cap[a]`` (cost ``cost[a]``) and a
backward one while ``y[a] > 0`` (cost ``-cost[a]``).
"""

import heapq
import math
from collections.abc import Sequence

from protee.flow._normal import Normal
from protee.graph import Digraph
from protee.paths import NegativeCycle, ShortestPaths, bellman_ford

type Number = int | float


def _residual(
    normal: Normal, y: Sequence[int]
) -> tuple[Digraph, list[Number], list[tuple[int, int]]]:
    """Residual graph, its costs, and (arc, direction) of each residual edge."""
    tails: list[int] = []
    heads: list[int] = []
    cost: list[Number] = []
    edge: list[tuple[int, int]] = []
    for a in range(normal.m):
        t, h = normal.tails[a], normal.heads[a]
        if y[a] < normal.cap[a]:
            tails.append(t)
            heads.append(h)
            cost.append(normal.cost[a])
            edge.append((a, 1))
        if y[a] > 0:
            tails.append(h)
            heads.append(t)
            cost.append(-normal.cost[a])
            edge.append((a, -1))
    return Digraph(normal.n, tuple(tails), tuple(heads)), cost, edge


def cycle_canceling(
    normal: Normal, y: list[int], counters: dict[str, int]
) -> list[Number]:
    """Cancel negative cycles of the residual network (Klein, 1967).

    ``y`` is a feasible flow of the standard form, made optimal in place.
    Returns optimal potentials.
    """
    while True:
        graph, cost, edge = _residual(normal, y)
        found = bellman_ford(graph, cost, tolerance=normal.tolerance)
        counters["bellman_ford_runs"] += 1
        if isinstance(found, ShortestPaths):
            return [-d for d in found.distance]
        assert isinstance(found, NegativeCycle)
        delta = min(
            normal.cap[a] - y[a] if d == 1 else y[a]
            for a, d in (edge[e] for e in found.arcs)
        )
        for e in found.arcs:
            a, d = edge[e]
            y[a] += d * delta
        counters["cycles_canceled"] += 1


def successive_shortest_paths(
    normal: Normal, counters: dict[str, int]
) -> tuple[list[int], list[Number]] | None:
    """Augment along shortest paths with reduced costs and potentials.

    Starts from ``y`` = capacity on arcs of negative cost, 0 elsewhere, so
    that zero potentials make every residual reduced cost non-negative;
    Dijkstra then applies (Edmonds and Karp, 1972; Tomizawa, 1971).
    Returns the optimal flow and potentials, or ``None`` when the supplies
    cannot be routed (infeasible).
    """
    n, m = normal.n, normal.m
    y = [normal.cap[a] if normal.cost[a] < 0 else 0 for a in range(m)]
    rest = list(normal.supply)  # supply still to send (negative: still to receive)
    for a in range(m):
        rest[normal.tails[a]] -= y[a]
        rest[normal.heads[a]] += y[a]
    out: list[list[int]] = [[] for _ in range(n)]
    for a in range(m):
        out[normal.tails[a]].append(2 * a)
        out[normal.heads[a]].append(2 * a + 1)
    pot: list[Number] = [0] * n
    while True:
        sources = [v for v in range(n) if rest[v] > 0]
        if not sources:
            return y, pot
        counters["dijkstra_runs"] += 1
        dist: list[Number] = [math.inf] * n
        pred = [-1] * n
        done = [False] * n
        heap: list[tuple[Number, int]] = []
        for s in sources:
            dist[s] = 0
            heap.append((0, s))
        heapq.heapify(heap)
        target = -1
        while heap:
            d, u = heapq.heappop(heap)
            if done[u]:
                continue
            done[u] = True
            if rest[u] < 0:
                target = u
                break
            for e in out[u]:
                a = e >> 1
                if e & 1:
                    if y[a] == 0:
                        continue
                    v = normal.tails[a]
                    rc = -normal.cost[a] - pot[u] + pot[v]
                elif y[a] < normal.cap[a]:
                    v = normal.heads[a]
                    rc = normal.cost[a] - pot[u] + pot[v]
                else:
                    continue
                new_dist = d + max(rc, 0)
                if new_dist < dist[v]:
                    dist[v] = new_dist
                    pred[v] = e
                    heapq.heappush(heap, (new_dist, v))
        if target == -1:
            return None
        limit = dist[target]
        for v in range(n):
            pot[v] -= min(dist[v], limit)
        delta = -rest[target]
        v = target
        path = []
        while pred[v] != -1:
            e = pred[v]
            a = e >> 1
            path.append(e)
            delta = min(delta, y[a] if e & 1 else normal.cap[a] - y[a])
            v = normal.heads[a] if e & 1 else normal.tails[a]
        delta = min(delta, rest[v])
        for e in path:
            y[e >> 1] += -delta if e & 1 else delta
        rest[v] -= delta
        rest[target] += delta
        counters["augmentations"] += 1
