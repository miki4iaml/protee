# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Internal standard form shared by the minimum cost flow methods.

``x = lower + y`` turns the problem into a minimum cost flow in ``y`` with
lower bounds 0, finite capacities and integer supplies. Arcs without an
upper bound get a capacity ``big`` that no optimal flow needs to reach,
once cycles of negative cost and unbounded capacity are ruled out.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from protee.flow._problem import FlowProblem
from protee.graph import Digraph
from protee.paths import NegativeCycle, bellman_ford

type Number = int | float


def tolerance_for(costs: Sequence[Number]) -> float:
    """Zero for integer costs (exact), relative tolerance for float costs."""
    if all(isinstance(c, int) for c in costs):
        return 0.0
    return 1e-9 * max(1.0, max((abs(c) for c in costs), default=0.0))


@dataclass(slots=True)
class Normal:
    """Minimum cost flow with lower bounds 0 and finite capacities."""

    n: int
    tails: tuple[int, ...]
    heads: tuple[int, ...]
    cap: list[int]
    cost: list[Number]
    supply: list[int]
    lower: tuple[int, ...]
    uncapacitated: tuple[bool, ...]
    big: int
    sign: int
    tolerance: float

    @property
    def m(self) -> int:
        return len(self.tails)

    def flow(self, y: Sequence[int]) -> tuple[int, ...]:
        """Flow of the original problem: ``lower + y``."""
        return tuple(lo + v for lo, v in zip(self.lower, y, strict=True))


def signed_costs(problem: FlowProblem) -> list[Number]:
    """Costs of the minimization form."""
    return list(problem.cost) if problem.sense == "min" else [-c for c in problem.cost]


def shifted_supply(problem: FlowProblem) -> list[int]:
    """Supplies of ``y`` once ``x = lower + y`` is substituted."""
    g = problem.graph
    supply = list(problem.supply)
    for a, (t, h) in enumerate(g.arcs()):
        supply[t] -= problem.lower[a]
        supply[h] += problem.lower[a]
    return supply


def normalize(problem: FlowProblem) -> Normal:
    """Standard form of ``problem`` (see the module docstring)."""
    g = problem.graph
    lower = tuple(problem.lower)
    supply = shifted_supply(problem)
    finite = [
        hi - lo for lo, hi in zip(lower, problem.upper, strict=True) if hi is not None
    ]
    big = sum(b for b in supply if b > 0) + sum(finite) + 1
    cap = [
        big if hi is None else hi - lo
        for lo, hi in zip(lower, problem.upper, strict=True)
    ]
    cost = signed_costs(problem)
    return Normal(
        n=g.n,
        tails=g.tails,
        heads=g.heads,
        cap=cap,
        cost=cost,
        supply=supply,
        lower=lower,
        uncapacitated=tuple(hi is None for hi in problem.upper),
        big=big,
        sign=1 if problem.sense == "min" else -1,
        tolerance=tolerance_for(cost),
    )


class UnboundedCheck:
    """Cycles of arcs without upper bound, for successive cost vectors.

    When the problem is feasible, a cycle of such arcs whose cost improves
    the objective makes it unbounded; without one, an optimum exists. The
    subgraph of these arcs is built once; each cost vector costs one
    Bellman-Ford.
    """

    def __init__(self, problem: FlowProblem) -> None:
        g = problem.graph
        self.keep = [a for a in range(g.m) if problem.upper[a] is None]
        self.graph = Digraph(
            g.n,
            tuple(g.tails[a] for a in self.keep),
            tuple(g.heads[a] for a in self.keep),
        )

    def cycle(self, cost: Sequence[Number]) -> NegativeCycle | None:
        """An improving cycle for ``cost`` (minimization form), or ``None``."""
        if not self.keep:
            return None
        weight = [cost[a] for a in self.keep]
        found = bellman_ford(self.graph, weight, tolerance=tolerance_for(weight))
        if isinstance(found, NegativeCycle):
            return NegativeCycle(tuple(self.keep[a] for a in found.arcs), found.weight)
        return None
