# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Feasibility of a flow problem, with a violated cut as certificate."""

from dataclasses import dataclass
from types import MappingProxyType

from protee.flow import _maxflow
from protee.flow._maxflow import MaxFlowMethod, Residual
from protee.flow._normal import normalize
from protee.flow._problem import FlowProblem
from protee.flow._result import InfeasibleCut


@dataclass(frozen=True, slots=True)
class Feasibility:
    """Outcome of :func:`check_feasibility`.

    Attributes
    ----------
    feasible : bool
    flow : tuple of int or None
        A feasible flow, when there is one.
    cut : InfeasibleCut or None
        A violated cut, when there is no feasible flow.
    method : str
        The maximum flow method used.
    counters : mapping of str to int
    """

    feasible: bool
    flow: tuple[int, ...] | None
    cut: InfeasibleCut | None
    method: str
    counters: MappingProxyType[str, int]


def cut_of(problem: FlowProblem, nodes: frozenset[int]) -> InfeasibleCut:
    """The Gale-Hoffman inequality of a node set (violated or not)."""
    g = problem.graph
    out_arcs = tuple(
        a for a in range(g.m) if g.tails[a] in nodes and g.heads[a] not in nodes
    )
    in_arcs = tuple(
        a for a in range(g.m) if g.heads[a] in nodes and g.tails[a] not in nodes
    )
    capacity = 0
    for a in out_arcs:
        hi = problem.upper[a]
        if hi is None:
            raise ValueError(
                "an arc without upper bound leaves the set: the inequality is void"
            )
        capacity += hi
    capacity -= sum(problem.lower[a] for a in in_arcs)
    return InfeasibleCut(
        nodes, sum(problem.supply[v] for v in nodes), capacity, out_arcs, in_arcs
    )


def check_feasibility(
    problem: FlowProblem, *, method: MaxFlowMethod = "dinic"
) -> Feasibility:
    """Find a feasible flow, or prove that none exists.

    The lower bounds are removed (``x = lower + y``) and the supplies are
    routed from a super-source to a super-sink by a maximum flow. The flow
    saturates the super-source exactly when the problem is feasible;
    otherwise the source side of the minimum cut gives a node set whose
    supply cannot leave it (Gale's theorem; Hoffman's circulation theorem
    when all supplies are zero).

    Parameters
    ----------
    problem : FlowProblem
    method : {"dinic", "edmonds_karp"}, optional
        Maximum flow method, Dinic by default (a support computation, not a
        compared method).

    Returns
    -------
    Feasibility
    """
    normal = normalize(problem)
    n = normal.n
    s, t = n, n + 1
    net = Residual(n + 2)
    edges = [
        net.add(u, v, c)
        for u, v, c in zip(normal.tails, normal.heads, normal.cap, strict=True)
    ]
    total = 0
    for v, b in enumerate(normal.supply):
        if b > 0:
            net.add(s, v, b)
            total += b
        elif b < 0:
            net.add(v, t, -b)
    value, counters = _maxflow.run(net, s, t, method)
    if value == total:
        y = [net.cap[e ^ 1] for e in edges]
        return Feasibility(
            True, normal.flow(y), None, method, MappingProxyType(counters)
        )
    side = net.reachable(s)
    nodes = frozenset(v for v in range(n) if side[v])
    return Feasibility(
        False, None, cut_of(problem, nodes), method, MappingProxyType(counters)
    )
