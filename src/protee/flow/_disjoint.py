# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Disjoint paths of minimum total cost, by minimum cost flow."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from protee.flow._maxflow import max_flow
from protee.flow._methods import solve
from protee.flow._problem import FlowProblem
from protee.flow._result import Status
from protee.graph import Digraph

type Number = int | float


@dataclass(frozen=True, slots=True)
class DisjointPaths:
    """Outcome of :func:`disjoint_paths`.

    Attributes
    ----------
    status : Status
        Optimal, or infeasible when fewer than ``k`` disjoint paths exist.
    paths : tuple of tuple of int
        The arcs of each path, from the source to the target; empty unless
        optimal.
    cost : int or float or None
        Total cost of the paths; ``None`` unless optimal.
    max_paths : int
        Largest number of disjoint paths (Menger's theorem), at least
        ``k`` when optimal.
    method : str
        The flow method used.
    counters : mapping of str to int
    """

    status: Status
    paths: tuple[tuple[int, ...], ...]
    cost: Number | None
    max_paths: int
    method: str
    counters: Mapping[str, int]


def _network(
    graph: Digraph, cost: Sequence[Number], source: int, target: int, disjoint: str
) -> tuple[Digraph, list[Number], int, int]:
    """Unit-capacity network; with node splitting for node-disjoint paths.

    The first ``m`` arcs of the network are the arcs of ``graph``, in order.
    """
    if disjoint == "arcs":
        return graph, list(cost), source, target
    n = graph.n
    # Node v is split into v (entry) and n + v (exit).
    tails = [n + t for t in graph.tails]
    heads = list(graph.heads)
    for v in range(n):
        tails.append(v)
        heads.append(n + v)
    return (
        Digraph(2 * n, tuple(tails), tuple(heads)),
        list(cost) + [0] * n,
        n + source,
        target,
    )


def _walks(
    graph: Digraph, flow: Sequence[int], source: int, target: int, k: int
) -> list[tuple[int, ...]]:
    """Decompose a 0/1 flow into ``k`` simple paths, dropping cycles."""
    used = [x == 0 for x in flow]
    pointer = [0] * graph.n
    paths = []
    for _ in range(k):
        path: list[int] = []
        position = {source: 0}
        u = source
        while u != target:
            arcs = graph.out_arcs(u)
            while used[arcs[pointer[u]]]:
                pointer[u] += 1
            a = arcs[pointer[u]]
            used[a] = True
            v = graph.heads[a]
            if v in position:
                for b in path[position[v] :]:
                    del position[graph.heads[b]]
                del path[position[v] :]
            else:
                path.append(a)
                position[v] = len(path)
            u = v
        paths.append(tuple(path))
    return paths


def disjoint_paths(
    graph: Digraph,
    cost: Sequence[Number],
    source: int,
    target: int,
    k: int,
    *,
    disjoint: Literal["nodes", "arcs"],
    method: str,
) -> DisjointPaths:
    """``k`` disjoint paths from ``source`` to ``target`` of minimum total cost.

    The paths share no arc (``disjoint="arcs"``) or no node other than the
    source and the target (``disjoint="nodes"``, by node splitting). The
    problem is a minimum cost flow of value ``k`` with unit capacities
    (Suurballe's problem); it is solved by the named flow method.

    Parameters
    ----------
    graph : Digraph
    cost : sequence of int or float
        Non-negative arc costs.
    source, target : int
        Distinct nodes.
    k : int
        Number of paths, at least 1.
    disjoint : {"nodes", "arcs"}
    method : str
        A flow method of :func:`protee.flow.methods`.

    Returns
    -------
    DisjointPaths

    Raises
    ------
    ValueError
        If a cost is negative, ``k < 1``, or the nodes are not distinct.
    """
    if disjoint not in ("nodes", "arcs"):
        raise ValueError(f"disjoint must be 'nodes' or 'arcs', got {disjoint!r}")
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if source == target or not (0 <= source < graph.n and 0 <= target < graph.n):
        raise ValueError("source and target must be two distinct nodes")
    if len(cost) != graph.m or any(c < 0 for c in cost):
        raise ValueError(f"expected {graph.m} non-negative costs")
    network, weights, s, t = _network(graph, cost, source, target, disjoint)
    supply = [0] * network.n
    supply[s], supply[t] = k, -k
    problem = FlowProblem(network, upper=(1,) * network.m, cost=weights, supply=supply)
    result = solve(problem, method=method)
    if result.flow is None:
        most = max_flow(network, (1,) * network.m, s, t, method="dinic").value
        return DisjointPaths(Status.INFEASIBLE, (), None, most, method, result.counters)
    flow = result.flow[: graph.m]
    paths = _walks(graph, flow, source, target, k)
    total = sum(cost[a] for path in paths for a in path)
    most = max_flow(network, (1,) * network.m, s, t, method="dinic").value
    return DisjointPaths(
        Status.OPTIMAL, tuple(paths), total, most, method, result.counters
    )
