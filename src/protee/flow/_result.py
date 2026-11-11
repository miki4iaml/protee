# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Result shared by every flow method, and its certificates."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from protee.paths import NegativeCycle

type Number = int | float


class Status(StrEnum):
    """Outcome of a flow computation."""

    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"


@dataclass(frozen=True, slots=True)
class InfeasibleCut:
    """Certificate of infeasibility (Gale, Hoffman).

    For a node set ``X``, every feasible flow satisfies
    ``supply(X) = x(out) - x(in) <= upper(out) - lower(in)``, where ``out``
    and ``in`` are the arcs leaving and entering ``X``. This set violates
    the inequality, so no feasible flow exists.

    Attributes
    ----------
    nodes : frozenset of int
        The set ``X``.
    supply : int
        Net supply of ``X``.
    capacity : int
        ``upper(out) - lower(in)``: the most ``X`` can send out.
    out_arcs, in_arcs : tuple of int
        Arcs leaving and entering ``X``.
    """

    nodes: frozenset[int]
    supply: int
    capacity: int
    out_arcs: tuple[int, ...]
    in_arcs: tuple[int, ...]

    @property
    def excess(self) -> int:
        """``supply - capacity``, positive: the supply that cannot leave."""
        return self.supply - self.capacity


type Certificate = InfeasibleCut | NegativeCycle


@dataclass(frozen=True, slots=True)
class FlowResult:
    """Result of a minimum or maximum cost flow method.

    Attributes
    ----------
    status : Status
    method : str
        Name of the method that produced the result.
    objective : int or float or None
        Optimal value, in the sense of the problem; ``None`` unless optimal.
    flow : tuple of int or None
        Optimal flow, one integer per arc; ``None`` unless optimal.
    potentials : tuple of int or float or None
        Optimal node potentials ``pi`` of the minimization form (costs
        negated when the problem maximizes): the reduced cost
        ``c[a] - pi[tail] + pi[head]`` is non-negative on arcs below their
        upper bound and non-positive on arcs above their lower bound
        (convention of Ahuja, Magnanti and Orlin). ``None`` unless optimal.
    certificate : InfeasibleCut or NegativeCycle or None
        Why there is no optimum: a violated cut when infeasible, a cycle of
        improving cost and unbounded capacity when unbounded.
    counters : mapping of str to int
        Deterministic work counters of the method (pivots, augmentations…),
        comparable between runs and machines.
    version : str
        Version of protee that produced the result.
    """

    status: Status
    method: str
    objective: Number | None
    flow: tuple[int, ...] | None
    potentials: tuple[Number, ...] | None
    certificate: Certificate | None
    counters: Mapping[str, int]
    version: str

    @property
    def optimal(self) -> bool:
        """True when the status is optimal."""
        return self.status is Status.OPTIMAL
