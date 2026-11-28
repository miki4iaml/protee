# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Disjoint paths of minimum total cost, by minimum cost flow."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from protee.flow._maxflow import _max_flow
from protee.flow._methods import solve
from protee.flow._problem import FlowProblem
from protee.flow._registry import DISJOINT_PATHS, min_cost_flow_method
from protee.graph import Digraph
from protee.results import ResultCore

type Number = int | float


@dataclass(frozen=True, slots=True, kw_only=True)
class DisjointPaths(ResultCore):
    """Outcome of :func:`disjoint_paths`.

    On top of the fields of :class:`~protee.results.ResultCore`: the status
    is ``optimal``, or ``infeasible`` when fewer than ``k`` disjoint paths
    exist; ``method`` is the minimum cost flow method used, and
    ``parameters`` hold ``disjoint``.

    Attributes
    ----------
    paths : tuple of tuple of int
        The arcs of each path, from the source to the target; empty unless
        optimal.
    cost : int or float or None
        Total cost of the paths; ``None`` unless optimal.
    max_paths : int
        Largest number of disjoint paths (Menger's theorem), at least
        ``k`` when optimal.

    Notes
    -----
    ``certificate``, when infeasible: a cut of the unit-capacity flow
    network (:class:`~protee.results.InfeasibleCut`), of capacity
    ``max_paths``, below ``k``. With ``disjoint="arcs"``, the network is
    the graph, and the arcs leaving the cut separate the target from the
    source. With ``disjoint="nodes"``, each node ``v`` is split into an
    entry ``v`` and an exit ``n + v``, joined by the arc ``m + v``; arc
    ``a`` of the graph goes from the exit of its tail to the entry of its
    head; the paths leave the exit of the source and reach the entry of
    the target. A leaving arc ``m + v`` then stands for node ``v``, a
    leaving arc ``a < m`` for arc ``a``.

    ``counters``: those of the flow method, plus ``max_flow_augmentations``
    and ``max_flow_phases`` of the maximum flow (Dinic) that counts the
    disjoint paths.
    """

    paths: tuple[tuple[int, ...], ...] = ()
    cost: Number | None = None
    max_paths: int


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
        A minimum cost flow method, from
        ``protee.flow.methods("disjoint_paths")``.

    Returns
    -------
    DisjointPaths
        Status ``optimal`` with the paths, or ``infeasible`` with a cut of
        capacity below ``k``.

    Raises
    ------
    ValueError
        If a cost is negative, ``k < 1``, the nodes are not distinct, or
        the method is unknown.
    """
    if disjoint not in ("nodes", "arcs"):
        raise ValueError(f"disjoint must be 'nodes' or 'arcs', got {disjoint!r}")
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if source == target or not (0 <= source < graph.n and 0 <= target < graph.n):
        raise ValueError("source and target must be two distinct nodes")
    if len(cost) != graph.m or any(c < 0 for c in cost):
        raise ValueError(f"expected {graph.m} non-negative costs")
    info = DISJOINT_PATHS[min_cost_flow_method(method).name]
    network, weights, s, t = _network(graph, cost, source, target, disjoint)
    supply = [0] * network.n
    supply[s], supply[t] = k, -k
    problem = FlowProblem(network, upper=(1,) * network.m, cost=weights, supply=supply)
    result = solve(problem, method=method)
    most, _, _, work = _max_flow(network, (1,) * network.m, s, t, "dinic")
    counters = dict(result.counters)
    counters.update({f"max_flow_{name}": v for name, v in work.items()})
    paths: tuple[tuple[int, ...], ...] = ()
    total: Number | None = None
    if result.flow is not None:
        paths = tuple(_walks(graph, result.flow[: graph.m], source, target, k))
        total = sum(cost[a] for path in paths for a in path)
    return DisjointPaths(
        status=result.status,
        method=method,
        guarantee=info.guarantee,
        parameters={"disjoint": disjoint},
        counters=counters,
        certificate=result.certificate,
        paths=paths,
        cost=total,
        max_paths=most,
        _sources=(graph, tuple(cost), source, target, k),
    )
