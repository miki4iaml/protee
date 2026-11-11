# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Maximum flow: Edmonds-Karp and Dinic on a residual network."""

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from protee.flow._problem import _is_int
from protee.graph import Digraph

type MaxFlowMethod = Literal["dinic", "edmonds_karp"]


class Residual:
    """Residual network: edge ``e`` and its reverse ``e ^ 1``."""

    __slots__ = ("adj", "cap", "head")

    def __init__(self, n: int) -> None:
        self.head: list[int] = []
        self.cap: list[int] = []
        self.adj: list[list[int]] = [[] for _ in range(n)]

    def add(self, u: int, v: int, capacity: int) -> int:
        """Add arc ``u -> v``; return the index of its forward edge."""
        e = len(self.head)
        self.head += (v, u)
        self.cap += (capacity, 0)
        self.adj[u].append(e)
        self.adj[v].append(e + 1)
        return e

    def reachable(self, s: int) -> list[bool]:
        """Nodes reachable from ``s`` through edges of positive capacity."""
        seen = [False] * len(self.adj)
        seen[s] = True
        queue = deque((s,))
        while queue:
            u = queue.popleft()
            for e in self.adj[u]:
                v = self.head[e]
                if self.cap[e] > 0 and not seen[v]:
                    seen[v] = True
                    queue.append(v)
        return seen


def edmonds_karp(net: Residual, s: int, t: int, counters: dict[str, int]) -> int:
    """Augment along shortest paths (BFS) until none is left."""
    value = 0
    n = len(net.adj)
    while True:
        parent = [-1] * n
        parent[s] = -2
        queue = deque((s,))
        while queue and parent[t] == -1:
            u = queue.popleft()
            for e in net.adj[u]:
                v = net.head[e]
                if net.cap[e] > 0 and parent[v] == -1:
                    parent[v] = e
                    queue.append(v)
        if parent[t] == -1:
            return value
        delta = None
        v = t
        while v != s:
            e = parent[v]
            delta = net.cap[e] if delta is None else min(delta, net.cap[e])
            v = net.head[e ^ 1]
        assert delta is not None
        v = t
        while v != s:
            e = parent[v]
            net.cap[e] -= delta
            net.cap[e ^ 1] += delta
            v = net.head[e ^ 1]
        value += delta
        counters["augmentations"] += 1


def dinic(net: Residual, s: int, t: int, counters: dict[str, int]) -> int:
    """Blocking flows on the level graph (Dinic), iterative search."""
    value = 0
    n = len(net.adj)
    while True:
        level = [-1] * n
        level[s] = 0
        queue = deque((s,))
        while queue:
            u = queue.popleft()
            for e in net.adj[u]:
                v = net.head[e]
                if net.cap[e] > 0 and level[v] < 0:
                    level[v] = level[u] + 1
                    queue.append(v)
        if level[t] < 0:
            return value
        counters["phases"] += 1
        pointer = [0] * n
        path: list[int] = []
        u = s
        while True:
            if u == t:
                delta = min(net.cap[e] for e in path)
                for e in path:
                    net.cap[e] -= delta
                    net.cap[e ^ 1] += delta
                value += delta
                counters["augmentations"] += 1
                first = next(i for i, e in enumerate(path) if net.cap[e] == 0)
                del path[first:]
                u = s if not path else net.head[path[-1]]
                continue
            adj = net.adj[u]
            while pointer[u] < len(adj):
                e = adj[pointer[u]]
                if net.cap[e] > 0 and level[net.head[e]] == level[u] + 1:
                    break
                pointer[u] += 1
            if pointer[u] < len(adj):
                e = adj[pointer[u]]
                path.append(e)
                u = net.head[e]
                continue
            if u == s:
                break
            level[u] = -1
            e = path.pop()
            u = net.head[e ^ 1]
            pointer[u] += 1


ALGORITHMS: dict[str, Callable[[Residual, int, int, dict[str, int]], int]] = {
    "dinic": dinic,
    "edmonds_karp": edmonds_karp,
}


def run(net: Residual, s: int, t: int, method: str) -> tuple[int, dict[str, int]]:
    """Run a named maximum flow method on ``net``."""
    if method not in ALGORITHMS:
        raise ValueError(
            f"unknown maximum flow method {method!r}; choose among {sorted(ALGORITHMS)}"
        )
    counters = {"augmentations": 0, "phases": 0}
    return ALGORITHMS[method](net, s, t, counters), counters


@dataclass(frozen=True, slots=True)
class MaxFlowResult:
    """Maximum flow and minimum cut.

    Attributes
    ----------
    value : int
        Value of the maximum flow.
    flow : tuple of int
        Flow on each arc.
    source_side : frozenset of int
        Nodes reachable from the source in the final residual network: the
        arcs leaving this set form a minimum cut.
    method : str
    counters : mapping of str to int
        ``augmentations``, and ``phases`` for Dinic.
    """

    value: int
    flow: tuple[int, ...]
    source_side: frozenset[int]
    method: str
    counters: MappingProxyType[str, int]


def max_flow(
    graph: Digraph,
    capacity: Sequence[int | None],
    source: int,
    target: int,
    *,
    method: MaxFlowMethod,
) -> MaxFlowResult:
    """Maximum flow from ``source`` to ``target``.

    Parameters
    ----------
    graph : Digraph
    capacity : sequence of int or None
        Non-negative integer capacities; ``None`` means unbounded.
    source, target : int
        Distinct nodes.
    method : {"dinic", "edmonds_karp"}
        Dinic's blocking flows, :math:`O(n^2 m)`, or Edmonds-Karp's
        shortest augmenting paths, :math:`O(n m^2)`.

    Returns
    -------
    MaxFlowResult

    Raises
    ------
    ValueError
        If a capacity is negative, the nodes are not distinct, or a path of
        unbounded arcs joins the source to the target.
    """
    if len(capacity) != graph.m:
        raise ValueError(f"expected {graph.m} capacities, got {len(capacity)}")
    if source == target or not (0 <= source < graph.n and 0 <= target < graph.n):
        raise ValueError("source and target must be two distinct nodes")
    finite = 0
    for a, c in enumerate(capacity):
        if c is not None:
            if not _is_int(c) or c < 0:
                raise ValueError(
                    f"capacity of arc {a} must be a non-negative integer, got {c!r}"
                )
            finite += c
    big = finite + 1
    net = Residual(graph.n)
    edges = [
        net.add(t, h, big if c is None else c)
        for (t, h), c in zip(graph.arcs(), capacity, strict=True)
    ]
    value, counters = run(net, source, target, method)
    if value >= big:
        raise ValueError(
            "unbounded: a path of arcs without capacity joins the source to the target"
        )
    flow = tuple(net.cap[e ^ 1] for e in edges)
    side = net.reachable(source)
    return MaxFlowResult(
        value,
        flow,
        frozenset(v for v in range(graph.n) if side[v]),
        method,
        MappingProxyType(counters),
    )
