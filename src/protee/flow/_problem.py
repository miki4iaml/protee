# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Flow problem: bounds, costs and supplies on a directed multigraph."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from protee.graph import Digraph

type Number = int | float
type Sense = Literal["min", "max"]


def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_number(x: object) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def _integers(name: str, values: Sequence[int], size: int) -> tuple[int, ...]:
    if len(values) != size:
        raise ValueError(f"{name}: expected {size} values, got {len(values)}")
    for i, x in enumerate(values):
        if not _is_int(x):
            raise TypeError(f"{name}[{i}] must be an integer, got {x!r}")
    return tuple(values)


def _uppers(values: Sequence[int | float | None], size: int) -> tuple[int | None, ...]:
    if len(values) != size:
        raise ValueError(f"upper: expected {size} values, got {len(values)}")
    out: list[int | None] = []
    for i, x in enumerate(values):
        if x is None or (isinstance(x, float) and x == math.inf):
            out.append(None)
        elif isinstance(x, int) and _is_int(x):
            out.append(x)
        else:
            raise TypeError(
                f"upper[{i}] must be an integer, None or math.inf, got {x!r}"
            )
    return tuple(out)


def _costs(values: Sequence[Number], size: int) -> tuple[Number, ...]:
    if len(values) != size:
        raise ValueError(f"cost: expected {size} values, got {len(values)}")
    for i, x in enumerate(values):
        if not _is_number(x):
            raise TypeError(f"cost[{i}] must be a finite number, got {x!r}")
    return tuple(values)


@dataclass(frozen=True, slots=True)
class FlowProblem:
    """Minimum or maximum cost flow with bounds and supplies.

    A flow ``x`` is feasible when ``lower[a] <= x[a] <= upper[a]`` on every
    arc and, at every node ``v``, outflow minus inflow equals
    ``supply[v]``. With all supplies at zero, the problem is a
    circulation. The objective is ``sum(cost[a] * x[a])``, minimized or
    maximized according to ``sense``.

    Parameters
    ----------
    graph : Digraph
    lower : sequence of int, optional
        Lower bounds, 0 by default.
    upper : sequence of int or None, optional
        Upper bounds; ``None`` (or ``math.inf``) means no bound, the
        default.
    cost : sequence of int or float, optional
        Arc costs, 0 by default. Integer costs give exact computations;
        float costs are compared with a tolerance.
    supply : sequence of int, optional
        Net supply of each node (positive: source, negative: demand), 0 by
        default. Supplies must sum to zero.
    sense : {"min", "max"}, optional
        Minimize (default) or maximize the cost.

    Raises
    ------
    ValueError
        If a size is wrong, a lower bound exceeds its upper bound, or the
        supplies do not sum to zero.
    TypeError
        If a bound or a supply is not an integer, or a cost not a finite
        number.

    Notes
    -----
    Integer bounds and supplies guarantee an integer optimal flow (the
    constraint matrix is totally unimodular); every method of
    :mod:`protee.flow` returns one.

    Provisional API (until version 1.0).
    """

    graph: Digraph
    lower: Sequence[int] = field(default=(), kw_only=True)
    upper: Sequence[int | None] = field(default=(), kw_only=True)
    cost: Sequence[Number] = field(default=(), kw_only=True)
    supply: Sequence[int] = field(default=(), kw_only=True)
    sense: Sense = field(default="min", kw_only=True)

    def __post_init__(self) -> None:
        g = self.graph
        lower = _integers("lower", self.lower or (0,) * g.m, g.m)
        upper = _uppers(self.upper or (None,) * g.m, g.m)
        cost = _costs(self.cost or (0,) * g.m, g.m)
        supply = _integers("supply", self.supply or (0,) * g.n, g.n)
        for a, (lo, hi) in enumerate(zip(lower, upper, strict=True)):
            if hi is not None and lo > hi:
                raise ValueError(f"arc {a}: lower bound {lo} exceeds upper bound {hi}")
        if sum(supply) != 0:
            raise ValueError(f"the supplies must sum to zero, not {sum(supply)}")
        if self.sense not in ("min", "max"):
            raise ValueError(f"sense must be 'min' or 'max', got {self.sense!r}")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "cost", cost)
        object.__setattr__(self, "supply", supply)

    @property
    def is_circulation(self) -> bool:
        """True when every supply is zero."""
        return not any(self.supply)

    @property
    def integral_costs(self) -> bool:
        """True when every cost is an integer: computations are exact."""
        return all(isinstance(c, int) for c in self.cost)

    def with_cost(
        self, cost: Sequence[Number], sense: Sense | None = None
    ) -> FlowProblem:
        """Same graph, bounds and supplies, with other costs (and sense)."""
        return replace(
            self, cost=tuple(cost), sense=self.sense if sense is None else sense
        )

    def objective(self, flow: Sequence[int]) -> Number:
        """Value ``sum(cost[a] * flow[a])`` of a flow."""
        return sum(c * x for c, x in zip(self.cost, flow, strict=True))

    def violations(self, flow: Sequence[int]) -> list[str]:
        """Describe every bound or conservation constraint a flow violates.

        Returns
        -------
        list of str
            Empty when the flow is feasible.
        """
        g = self.graph
        if len(flow) != g.m:
            return [f"expected {g.m} arc flows, got {len(flow)}"]
        found = []
        for a, x in enumerate(flow):
            hi = self.upper[a]
            if x < self.lower[a] or (hi is not None and x > hi):
                found.append(f"arc {a}: flow {x} outside [{self.lower[a]}, {hi}]")
        balance = [0] * g.n
        for a, x in enumerate(flow):
            balance[g.tails[a]] += x
            balance[g.heads[a]] -= x
        for v in range(g.n):
            if balance[v] != self.supply[v]:
                found.append(
                    f"node {v}: net outflow {balance[v]} instead of {self.supply[v]}"
                )
        return found
