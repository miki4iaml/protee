# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The result model shared by every method of the package.

Every method of a problem returns the same result type, built on
:class:`ResultCore`: a :class:`Status`, the certificate the status calls
for, the :class:`Guarantee` of the method, a bound and its gap when one is
known, deterministic work counters, the name of the method, its
parameters, the version of protee and a fingerprint of the inputs.

- :class:`Status`: optimal, feasible, infeasible, unbounded, or a work
  limit reached;
- certificates: :class:`InfeasibleCut` (Gale, Hoffman) and
  :class:`NegativeCycle`;
- :class:`Guarantee` and :class:`MethodInfo`: what a method of a registry
  promises, and how it is described.

The module is light: it imports neither NumPy nor SciPy.

Provisional API (until version 1.0).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from protee import __version__
from protee._fingerprint import freeze, inputs_fingerprint

__all__ = [
    "Certificate",
    "Guarantee",
    "GuaranteeKind",
    "InfeasibleCut",
    "MethodInfo",
    "NegativeCycle",
    "ResultCore",
    "Status",
]

type Number = int | float


class Status(StrEnum):
    """Outcome of a computation, shared by every problem.

    - ``optimal``: an optimum is proven, or a problem without objective is
      answered exactly;
    - ``feasible``: a feasible solution, whose optimality is not proven;
    - ``infeasible``: no solution exists (with a certificate);
    - ``unbounded``: the objective is unbounded (with a certificate);
    - ``limit``: a work limit was reached, measured by a counter, never by
      the clock.
    """

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    LIMIT = "limit"


@dataclass(frozen=True, slots=True)
class NegativeCycle:
    """A directed cycle of negative total weight: the certificate of an
    unbounded problem.

    Attributes
    ----------
    arcs : tuple of int
        The arcs of the cycle, in order: the head of each arc is the tail
        of the next one, and the head of the last is the tail of the first.
    weight : int or float
        Total weight of the cycle (negative).
    """

    arcs: tuple[int, ...]
    weight: Number


@dataclass(frozen=True, slots=True)
class InfeasibleCut:
    """Certificate of infeasibility of a flow problem (Gale, Hoffman).

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


class GuaranteeKind(StrEnum):
    """What a method promises about its result.

    - ``exact``: the result is optimal (or exhaustive) when the status is
      ``optimal``;
    - ``bounded``: a feasible result comes with a bound and its gap;
    - ``property``: the result has a stated property (irreducible,
      maximal…), without a computable bound;
    - ``none``: no promise beyond feasibility.
    """

    EXACT = "exact"
    BOUNDED = "bounded"
    PROPERTY = "property"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Guarantee:
    """The guarantee of a method.

    Attributes
    ----------
    kind : GuaranteeKind
    statement : str
        What is guaranteed, in a few words (``"optimal flow and
        potentials"``, ``"irreducible"``, ``"factor 2"``).
    """

    kind: GuaranteeKind
    statement: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", GuaranteeKind(self.kind))
        if not self.statement.strip():
            raise ValueError("a guarantee states what it guarantees")


@dataclass(frozen=True, slots=True, kw_only=True)
class MethodInfo:
    """Description of a method of a registry.

    Attributes
    ----------
    name : str
        The name to pass as ``method``, or the name of the function.
    problem : str
        The problem the method solves (``"min_cost_flow"``…).
    summary : str
    guarantee : Guarantee
    complexity : str
        Worst-case bound, with ``n`` nodes, ``m`` arcs, ``U`` the largest
        capacity and ``C`` the largest absolute cost.
    reference : str
    warm_start : bool
        Whether a prepared problem reuses the previous solution after a
        change of costs.
    options : tuple of str
        Keyword options the method accepts.
    """

    name: str
    problem: str
    summary: str
    guarantee: Guarantee
    complexity: str
    reference: str
    warm_start: bool = False
    options: tuple[str, ...] = ()


_NEEDS_CERTIFICATE = frozenset({Status.INFEASIBLE, Status.UNBOUNDED})


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultCore:
    """The fields every result of the package carries.

    Each result type inherits from it and adds its solution.

    Attributes
    ----------
    status : Status
    method : str
        Name of the method that produced the result.
    guarantee : Guarantee
        The guarantee of the method, as its registry declares it.
    parameters : mapping of str to object
        The options of the method, frozen (lists become tuples, mappings
        read-only).
    counters : mapping of str to int
        Deterministic work counters, comparable between runs and machines.
    version : str
        Version of protee that produced the result.
    bound : int or float, optional
        A bound on the optimal value, when the method computes one.
    gap : int or float, optional
        The absolute gap between the value of the result and ``bound``.
    certificate : InfeasibleCut or NegativeCycle, optional
        Why there is no solution: required when the status is
        ``infeasible`` or ``unbounded``.

    Raises
    ------
    ValueError
        If the status calls for a certificate and there is none, if a
        bounded method returns a feasible result without its bound and gap,
        or if the gap is negative.
    """

    status: Status
    method: str
    guarantee: Guarantee
    parameters: Mapping[str, object] = field(default_factory=dict)
    counters: Mapping[str, int] = field(default_factory=dict)
    version: str = __version__
    bound: Number | None = None
    gap: Number | None = None
    certificate: Certificate | None = None
    _sources: tuple[object, ...] = field(default=(), repr=False, compare=False)
    _inputs: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "status", Status(self.status))
        set_(self, "parameters", freeze(dict(self.parameters)))
        set_(self, "counters", MappingProxyType(dict(self.counters)))
        set_(self, "_sources", tuple(self._sources))
        if self.status in _NEEDS_CERTIFICATE and self.certificate is None:
            raise ValueError(f"an {self.status} result needs a certificate")
        if (
            self.status is Status.FEASIBLE
            and self.guarantee.kind is GuaranteeKind.BOUNDED
            and (self.bound is None or self.gap is None)
        ):
            raise ValueError("a bounded method returns a bound and its gap")
        if self.gap is not None and self.gap < 0:
            raise ValueError(f"a gap is not negative, got {self.gap}")

    @property
    def inputs(self) -> str:
        """Fingerprint (SHA-256) of the inputs, the method and its parameters.

        Computed at the first reading and kept; the fingerprint of a graph
        is computed once per graph. Two results with the same fingerprint
        and the same version come from the same computation.
        """
        found = self._inputs
        if not found:
            found = inputs_fingerprint(self.method, self.parameters, self._sources)
            object.__setattr__(self, "_inputs", found)
        return found
