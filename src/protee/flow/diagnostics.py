# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Diagnostics of flow problems and of their optima.

- :func:`flow_ranges`: least and greatest flow of each arc, over the
  feasible flows or over the optimal ones;
- :func:`unattainable_bounds`: bounds that no feasible flow reaches;
- :func:`optimum_uniqueness`: whether an optimal flow is the only one,
  with an exact test (no perturbation), and a direction of alternative
  optima when it is not.

Each diagnostic returns a result built on the common result model of
:mod:`protee.results`. A diagnostic is a method of its own, listed by
``protee.flow.methods`` under its name: ``method`` is the name of the
diagnostic, and the minimum cost flow method it runs, the ``method``
argument, is the parameter ``flow_method``. The counters add up the
work of every inner solve, under the names of the flow method, and count
the solves.

Provisional API (until version 1.0).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from protee.flow._feasibility import _feasible_flow
from protee.flow._methods import prepare, solve
from protee.flow._normal import signed_costs, tolerance_for
from protee.flow._problem import FlowProblem
from protee.flow._registry import (
    FLOW_RANGES,
    OPTIMUM_UNIQUENESS,
    UNATTAINABLE_BOUNDS,
    min_cost_flow_method,
)
from protee.flow._result import FlowResult
from protee.graph import Digraph
from protee.results import Certificate, ResultCore, Status
from protee.structure import strong_components

__all__ = [
    "FlowRanges",
    "UnattainableBounds",
    "Uniqueness",
    "flow_ranges",
    "optimum_uniqueness",
    "reduced_costs",
    "unattainable_bounds",
]

type Number = int | float


def reduced_costs(
    problem: FlowProblem, potentials: Sequence[Number]
) -> tuple[Number, ...]:
    """``c[a] - pi[tail] + pi[head]``, costs of the minimization form."""
    g = problem.graph
    cost = signed_costs(problem)
    return tuple(
        cost[a] - potentials[t] + potentials[h] for a, (t, h) in enumerate(g.arcs())
    )


def _tolerance(problem: FlowProblem) -> float:
    return tolerance_for(problem.cost) * (problem.graph.n + 2)


@dataclass(frozen=True, slots=True, kw_only=True)
class FlowRanges(ResultCore):
    """Outcome of :func:`flow_ranges`.

    On top of the fields of :class:`~protee.results.ResultCore`: the status
    is ``optimal`` when the ranges were computed; otherwise that of the
    problem, with its certificate: ``infeasible`` with a violated cut, or,
    for ranges at the optimum, ``unbounded`` with an improving cycle.
    ``method`` is ``"flow_ranges"``; ``parameters`` hold ``flow_method``
    and ``at_optimum``.

    Attributes
    ----------
    minimum : tuple of int or None
        Least flow of each arc; ``None`` unless optimal.
    maximum : tuple of int or None, or None
        Greatest flow of each arc, ``None`` for an arc whose flow has no
        upper limit; ``None`` unless optimal.

    Notes
    -----
    ``counters``: ``solves``, the number of minimum cost flow solves (two
    per arc, one more at the optimum), and the counters of the flow method
    summed over them; over the feasible flows, ``feasibility_augmentations``
    and ``feasibility_phases`` of the feasibility check (Dinic).
    """

    minimum: tuple[int, ...] | None = None
    maximum: tuple[int | None, ...] | None = None


def _optimal_face(problem: FlowProblem, result: FlowResult) -> FlowProblem:
    """Fix the arcs whose reduced cost is not zero at their bound.

    By complementary slackness with the optimal potentials, the remaining
    feasible flows are exactly the optimal flows.
    """
    assert result.flow is not None
    assert result.potentials is not None
    tol = _tolerance(problem)
    lower = list(problem.lower)
    upper = list(problem.upper)
    for a, rc in enumerate(reduced_costs(problem, result.potentials)):
        if abs(rc) > tol:
            lower[a] = upper[a] = result.flow[a]
    return FlowProblem(problem.graph, lower=lower, upper=upper, supply=problem.supply)


def flow_ranges(problem: FlowProblem, *, method: str, at_optimum: bool) -> FlowRanges:
    """Least and greatest flow of each arc.

    Two linear programs per arc (minimize, then maximize its flow), solved
    by the named method on one prepared problem: the network simplex
    reuses its tree from one arc to the next.

    Parameters
    ----------
    problem : FlowProblem
    method : str
        A minimum cost flow method, from
        ``protee.flow.methods("min_cost_flow")``; the result records it as
        the parameter ``flow_method``.
    at_optimum : bool
        ``False``: over all feasible flows (the maximum is then the
        greatest number of occurrences an arc can reach).
        ``True``: over the optimal flows only.

    Returns
    -------
    FlowRanges

    Raises
    ------
    ValueError
        If the method is unknown.
    """
    min_cost_flow_method(method)
    counters: dict[str, int] = {"solves": 0}

    def add(result: FlowResult) -> None:
        counters["solves"] += 1
        for k, v in result.counters.items():
            counters[k] = counters.get(k, 0) + v

    def ranges(
        status: Status,
        certificate: Certificate | None = None,
        minimum: tuple[int, ...] | None = None,
        maximum: tuple[int | None, ...] | None = None,
    ) -> FlowRanges:
        return FlowRanges(
            status=status,
            method=FLOW_RANGES.name,
            guarantee=FLOW_RANGES.guarantee,
            parameters={"flow_method": method, "at_optimum": at_optimum},
            counters=counters,
            certificate=certificate,
            minimum=minimum,
            maximum=maximum,
            _sources=(problem,),
        )

    base = problem
    if at_optimum:
        optimum = solve(problem, method=method)
        add(optimum)
        if not optimum.optimal:
            return ranges(optimum.status, optimum.certificate)
        base = _optimal_face(problem, optimum)
    else:
        _, cut, work = _feasible_flow(problem, "dinic")
        counters.update({f"feasibility_{k}": v for k, v in work.items()})
        if cut is not None:
            return ranges(Status.INFEASIBLE, cut)
    m = problem.graph.m
    prepared = prepare(base.with_cost((0,) * m, "min"), method=method)
    low: list[int] = []
    high: list[int | None] = []
    for a in range(m):
        unit = [0] * m
        unit[a] = 1
        least = prepared.solve(unit, "min")
        add(least)
        assert least.flow is not None  # the lower bound limits the minimum
        low.append(least.flow[a])
        most = prepared.solve(unit, "max")
        add(most)
        high.append(None if most.flow is None else most.flow[a])
    return ranges(Status.OPTIMAL, None, tuple(low), tuple(high))


@dataclass(frozen=True, slots=True, kw_only=True)
class UnattainableBounds(ResultCore):
    """Outcome of :func:`unattainable_bounds`.

    On top of the fields of :class:`~protee.results.ResultCore`: the status
    is ``optimal`` when computed, ``infeasible`` otherwise, with a violated
    cut; ``method`` is ``"unattainable_bounds"``; ``parameters`` hold
    ``flow_method``; ``counters`` are those of ``ranges``.

    Attributes
    ----------
    upper : tuple of int
        Arcs with a finite upper bound that no feasible flow reaches.
    lower : tuple of int
        Arcs whose lower bound no feasible flow reaches.
    ranges : FlowRanges
        The ranges over the feasible flows.
    """

    upper: tuple[int, ...] = ()
    lower: tuple[int, ...] = ()
    ranges: FlowRanges


def unattainable_bounds(problem: FlowProblem, *, method: str) -> UnattainableBounds:
    """Bounds that no feasible flow reaches.

    An unattainable upper bound is a maximum that the rest of the problem
    already prevents: the bound can be
    tightened to the greatest feasible flow without changing anything.

    Parameters
    ----------
    problem : FlowProblem
    method : str
        A minimum cost flow method, from
        ``protee.flow.methods("min_cost_flow")``; the result records it as
        the parameter ``flow_method``.

    Returns
    -------
    UnattainableBounds

    Raises
    ------
    ValueError
        If the method is unknown.
    """
    ranges = flow_ranges(problem, method=method, at_optimum=False)
    upper: tuple[int, ...] = ()
    lower: tuple[int, ...] = ()
    if ranges.minimum is not None and ranges.maximum is not None:
        upper = tuple(
            a
            for a, (hi, top) in enumerate(
                zip(problem.upper, ranges.maximum, strict=True)
            )
            if hi is not None and top is not None and top < hi
        )
        lower = tuple(
            a
            for a, (lo, bottom) in enumerate(
                zip(problem.lower, ranges.minimum, strict=True)
            )
            if bottom > lo
        )
    return UnattainableBounds(
        status=ranges.status,
        method=UNATTAINABLE_BOUNDS.name,
        guarantee=UNATTAINABLE_BOUNDS.guarantee,
        parameters={"flow_method": method},
        counters=ranges.counters,
        certificate=ranges.certificate,
        upper=upper,
        lower=lower,
        ranges=ranges,
        _sources=(problem,),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Uniqueness(ResultCore):
    """Outcome of :func:`optimum_uniqueness`.

    On top of the fields of :class:`~protee.results.ResultCore`: the status
    is ``optimal`` (the question is answered exactly); ``method`` is
    ``"optimum_uniqueness"``.

    Attributes
    ----------
    direction : tuple of (int, int) or None
        When the optimal flow is not the only one: a cycle of
        ``(arc, sign)`` pairs, ``sign`` being +1 to increase the arc's flow
        and -1 to decrease it. Pushing one unit along the cycle gives
        another optimal flow. ``None`` when the optimum is unique.

    Notes
    -----
    ``counters``: ``residual_edges``, the residual directions of zero
    reduced cost, and ``components``, their strongly connected components.
    """

    direction: tuple[tuple[int, int], ...] | None = None

    @property
    def unique(self) -> bool:
        """True when the optimal flow is the only one."""
        return self.direction is None


def _residual_zero(
    problem: FlowProblem, result: FlowResult
) -> tuple[Digraph, list[tuple[int, int]]]:
    """Residual edges of zero reduced cost: directions keeping optimality."""
    assert result.flow is not None
    assert result.potentials is not None
    tol = _tolerance(problem)
    g = problem.graph
    tails: list[int] = []
    heads: list[int] = []
    edges: list[tuple[int, int]] = []
    for a, rc in enumerate(reduced_costs(problem, result.potentials)):
        if abs(rc) > tol:
            continue
        t, h = g.arc(a)
        x, hi = result.flow[a], problem.upper[a]
        if hi is None or x < hi:
            tails.append(t)
            heads.append(h)
            edges.append((a, 1))
        if x > problem.lower[a]:
            tails.append(h)
            heads.append(t)
            edges.append((a, -1))
    return Digraph(g.n, tuple(tails), tuple(heads)), edges


def _path(
    graph: Digraph,
    start: int,
    goal: int,
    allowed: set[int],
    banned_arc: int,
    edges: list[tuple[int, int]],
) -> list[int]:
    """Edges of a shortest path from ``start`` to ``goal`` inside ``allowed``."""
    pred = {start: -1}
    queue = deque((start,))
    while queue and goal not in pred:
        u = queue.popleft()
        for e in graph.out_arcs(u):
            v = graph.heads[e]
            if v in allowed and v not in pred and edges[e][0] != banned_arc:
                pred[v] = e
                queue.append(v)
    path = []
    v = goal
    while pred[v] != -1:
        e = pred[v]
        path.append(e)
        v = graph.tails[e]
    path.reverse()
    return path


def _find(parent: dict[int, int], v: int) -> int:
    """Root of ``v`` in a union-find forest, with path halving."""
    while parent[v] != v:
        parent[v] = parent[parent[v]]
        v = parent[v]
    return v


def optimum_uniqueness(problem: FlowProblem, result: FlowResult) -> Uniqueness:
    """Test whether an optimal flow is the only optimal flow.

    Another optimal flow differs by a circulation made of residual
    directions of zero reduced cost. The optimum is unique exactly when
    these directions contain no cycle other than going back and forth on
    one arc: in each strongly connected component, that means every arc
    is usable in both directions and the arcs form a tree. The test is
    exact for integer costs, whatever the degeneracy; it replaces the
    detection of multiple optima by cost perturbation.

    Parameters
    ----------
    problem : FlowProblem
    result : FlowResult
        An optimal result of ``problem``, with its potentials.

    Returns
    -------
    Uniqueness
        Status ``optimal``; ``direction`` is ``None`` when the optimum is
        unique.

    Raises
    ------
    ValueError
        If ``result`` is not optimal.
    """
    if not result.optimal:
        raise ValueError("the result is not optimal")
    graph, edges = _residual_zero(problem, result)
    comp = strong_components(graph)
    return Uniqueness(
        status=Status.OPTIMAL,
        method=OPTIMUM_UNIQUENESS.name,
        guarantee=OPTIMUM_UNIQUENESS.guarantee,
        counters={"residual_edges": graph.m, "components": len(set(comp))},
        direction=_direction(problem, graph, edges, comp),
        _sources=(problem, result.flow, result.potentials),
    )


def _direction(
    problem: FlowProblem,
    graph: Digraph,
    edges: list[tuple[int, int]],
    comp: Sequence[int],
) -> tuple[tuple[int, int], ...] | None:
    """A cycle of residual directions of zero reduced cost, other than
    going back and forth on one arc; ``None`` if there is none."""
    members: dict[int, set[int]] = {}
    for v, c in enumerate(comp):
        members.setdefault(c, set()).add(v)
    inside: dict[int, list[int]] = {}
    for e in range(graph.m):
        t, h = graph.arc(e)
        if comp[t] == comp[h]:
            inside.setdefault(comp[t], []).append(e)
    for c, es in inside.items():
        nodes = members[c]
        for e in es:
            if graph.tails[e] == graph.heads[e]:
                return (edges[e],)
        directions: dict[int, set[int]] = {}
        for e in es:
            directions.setdefault(edges[e][0], set()).add(edges[e][1])
        for e in es:
            a = edges[e][0]
            if len(directions[a]) == 1:
                back = _path(graph, graph.heads[e], graph.tails[e], nodes, a, edges)
                return (edges[e], *(edges[f] for f in back))
        if len(directions) >= len(nodes):
            # All arcs go both ways and close an undirected cycle.
            parent = {v: v for v in nodes}
            for a in sorted(directions):
                t, h = problem.graph.arc(a)
                if _find(parent, t) == _find(parent, h):
                    forward = next(e for e in es if edges[e] == (a, 1))
                    back = _path(graph, h, t, nodes, a, edges)
                    return (edges[forward], *(edges[f] for f in back))
                parent[_find(parent, t)] = _find(parent, h)
    return None
