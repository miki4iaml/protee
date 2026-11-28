# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Result shared by every minimum or maximum cost flow method."""

from __future__ import annotations

from dataclasses import dataclass

from protee.results import Certificate, InfeasibleCut, ResultCore, Status

__all__ = ["Certificate", "FlowResult", "InfeasibleCut", "Status"]

type Number = int | float


@dataclass(frozen=True, slots=True, kw_only=True)
class FlowResult(ResultCore):
    """Result of a minimum or maximum cost flow method.

    On top of the fields of :class:`~protee.results.ResultCore` (status,
    method, guarantee, parameters, counters, version, certificate and the
    fingerprint of the inputs):

    Attributes
    ----------
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

    Notes
    -----
    ``certificate`` is a violated cut (:class:`InfeasibleCut`) when the
    problem is infeasible, a cycle of improving cost and unbounded capacity
    (:class:`~protee.results.NegativeCycle`) when it is unbounded.
    """

    objective: Number | None = None
    flow: tuple[int, ...] | None = None
    potentials: tuple[Number, ...] | None = None

    @property
    def optimal(self) -> bool:
        """True when the status is optimal."""
        return self.status is Status.OPTIMAL
