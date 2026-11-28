# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Feasibility of a flow problem, with a violated cut as certificate."""

from __future__ import annotations

from dataclasses import dataclass

from protee.flow import _maxflow
from protee.flow._maxflow import MaxFlowMethod, Residual
from protee.flow._normal import normalize
from protee.flow._problem import FlowProblem
from protee.flow._registry import FEASIBILITY
from protee.results import InfeasibleCut, ResultCore, Status


@dataclass(frozen=True, slots=True, kw_only=True)
class Feasibility(ResultCore):
    """Outcome of :func:`check_feasibility`.

    On top of the fields of :class:`~protee.results.ResultCore`: the status
    is ``optimal`` when a feasible flow exists (the question is answered
    exactly), ``infeasible`` otherwise, with a violated cut
    (:class:`~protee.results.InfeasibleCut`) as ``certificate``; ``method``
    is the maximum flow method used.

    Attributes
    ----------
    flow : tuple of int or None
        A feasible flow, when there is one.

    Notes
    -----
    ``counters``: ``augmentations`` and ``phases`` of the maximum flow (see
    :class:`~protee.flow.MaxFlowResult`). ``inputs`` covers the problem.
    """

    flow: tuple[int, ...] | None = None

    @property
    def feasible(self) -> bool:
        """True when a feasible flow exists (status ``optimal``)."""
        return self.status is Status.OPTIMAL

    @property
    def cut(self) -> InfeasibleCut | None:
        """The violated cut, when there is no feasible flow."""
        found = self.certificate
        return found if isinstance(found, InfeasibleCut) else None


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


def _feasible_flow(
    problem: FlowProblem, method: str
) -> tuple[tuple[int, ...] | None, InfeasibleCut | None, dict[str, int]]:
    """A feasible flow or a violated cut, and the counters of the maximum
    flow: the kernel of :func:`check_feasibility`, for the callers of the
    package."""
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
        return normal.flow(y), None, counters
    side = net.reachable(s)
    nodes = frozenset(v for v in range(n) if side[v])
    return None, cut_of(problem, nodes), counters


def check_feasibility(problem: FlowProblem, *, method: MaxFlowMethod) -> Feasibility:
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
    method : {"dinic", "edmonds_karp"}
        Maximum flow method (see ``protee.flow.methods("feasibility")``);
        there is no default: the choice of the method stays the caller's.

    Returns
    -------
    Feasibility
        Status ``optimal`` with a feasible flow, or ``infeasible`` with a
        violated cut.

    Raises
    ------
    ValueError
        If the method is unknown.
    """
    flow, cut, counters = _feasible_flow(problem, method)
    return Feasibility(
        status=Status.OPTIMAL if cut is None else Status.INFEASIBLE,
        method=method,
        guarantee=FEASIBILITY[method].guarantee,
        counters=counters,
        certificate=cut,
        flow=flow,
        _sources=(problem,),
    )
