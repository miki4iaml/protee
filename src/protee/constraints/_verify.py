# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Verification of a route or a flow against requirements."""

import itertools
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

import numpy as np
import numpy.typing as npt

from protee.constraints._compose import ComputationView
from protee.constraints._data import ArcData
from protee.constraints._effects import Effect, Reason, Verdict, evaluate
from protee.constraints._model import (
    Origin,
    Requirement,
    RequirementSet,
    ResolvedValues,
)
from protee.constraints._patterns import PATTERNS, EffectKind
from protee.flow import FlowProblem, FlowResult
from protee.graph import Digraph
from protee.routes import Route

__all__ = [
    "RequirementCheck",
    "RequirementStatus",
    "Verification",
    "verify_flow",
    "verify_route",
]


class RequirementStatus(StrEnum):
    """Status of a requirement in a result, computed by verification only.

    - ``applied``: verified on every element in scope;
    - ``partial``: no violation, but elements without data, admitted and
      counted;
    - ``not_applied``: violated, or not verifiable as applied, with the
      reason;
    - ``no_data``: the data cannot support the requirement (an attribute is
      absent);
    - ``not_applicable``: a value is to be set, or no element of the result
      is in scope.
    """

    APPLIED = "applied"
    PARTIAL = "partial"
    NOT_APPLIED = "not_applied"
    NO_DATA = "no_data"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class RequirementCheck:
    """Verification of one requirement on a result.

    Attributes
    ----------
    requirement : str
    status : RequirementStatus
    reason : str
    passed, failed, unknown : int
        Number of elements in scope (arcs of a route, arcs with flow) that
        pass, fail, or lack data.
    failing : tuple of int
        The arcs that fail.
    unknown_arcs : tuple of int
        The arcs without data.
    """

    requirement: str
    status: RequirementStatus
    reason: str
    passed: int = 0
    failed: int = 0
    unknown: int = 0
    failing: tuple[int, ...] = ()
    unknown_arcs: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Verification:
    """The verification of a result, one check per requirement.

    Attributes
    ----------
    checks : tuple of RequirementCheck
        In the order of the requirement set.
    violations : tuple of str
        Bound and conservation violations of a flow; empty for a route.
    """

    checks: tuple[RequirementCheck, ...]
    violations: tuple[str, ...] = ()
    _by_id: Mapping[str, RequirementCheck] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "_by_id", MappingProxyType({c.requirement: c for c in self.checks})
        )

    def __iter__(self) -> Iterator[RequirementCheck]:
        return iter(self.checks)

    def __len__(self) -> int:
        return len(self.checks)

    def __getitem__(self, requirement: str) -> RequirementCheck:
        """The check of the requirement of identifier ``requirement``."""
        return self._by_id[requirement]

    @property
    def statuses(self) -> Mapping[str, RequirementStatus]:
        """The status of each requirement."""
        return MappingProxyType({c.requirement: c.status for c in self.checks})


def _absent(requirement: Requirement, data: ArcData) -> list[str]:
    return [name for name in requirement.attributes.values() if name not in data]


def _verdict_check(
    requirement: Requirement,
    effect: Effect,
    arcs: npt.NDArray[np.int64],
    data: ArcData,
    what: str,
) -> RequirementCheck:
    rid = requirement.id
    if absent := _absent(requirement, data):
        return RequirementCheck(
            rid,
            RequirementStatus.NO_DATA,
            f"attribute {absent[0]!r} absent from the data",
        )
    assert effect.verdict is not None
    assert effect.reasons is not None
    in_scope = arcs[effect.reasons[arcs] != Reason.OUT_OF_SCOPE]
    if in_scope.size == 0:
        return RequirementCheck(
            rid, RequirementStatus.NOT_APPLICABLE, f"no {what} in the scope"
        )
    v = effect.verdict[in_scope]
    failing = tuple(int(a) for a in in_scope[v == Verdict.FAIL])
    unknown = tuple(int(a) for a in in_scope[v == Verdict.UNKNOWN])
    passed = int((v == Verdict.PASS).sum())
    counts = {"passed": passed, "failed": len(failing), "unknown": len(unknown)}
    if failing:
        status, reason = (
            RequirementStatus.NOT_APPLIED,
            f"{len(failing)} arcs violate it",
        )
    elif unknown:
        status, reason = RequirementStatus.PARTIAL, f"{len(unknown)} arcs without data"
    else:
        status, reason = RequirementStatus.APPLIED, f"verified on {passed} arcs"
    return RequirementCheck(
        rid, status, reason, **counts, failing=failing, unknown_arcs=unknown
    )


def _route_arcs(graph: Digraph, route: Route | Sequence[int]) -> npt.NDArray[np.int64]:
    arcs = tuple(route.arcs if isinstance(route, Route) else route)
    for a in arcs:
        if not 0 <= a < graph.m:
            raise ValueError(f"arc {a} out of range")
    for a, b in itertools.pairwise(arcs):
        if graph.heads[a] != graph.tails[b]:
            raise ValueError(f"arcs {a} and {b} are not consecutive")
    return np.unique(np.array(arcs, dtype=np.int64))


def verify_route(
    route: Route | Sequence[int],
    requirements: RequirementSet,
    graph: Digraph,
    data: ArcData,
    values: ResolvedValues,
    *,
    view: ComputationView | None = None,
) -> Verification:
    """Status of each requirement on a route, whatever method produced it.

    Each requirement is evaluated again on the arcs of the route; the
    status never comes from the solver.

    Parameters
    ----------
    route : Route or sequence of int
        The arcs of the route, in order.
    requirements : RequirementSet
    graph : Digraph
    data : ArcData
    values : ResolvedValues
    view : ComputationView, optional
        The view the route was computed with. A cost term (a speed cap)
        leaves no trace on the arcs: it is checked against this view, and
        is ``not_applied`` without it.

    Returns
    -------
    Verification

    Raises
    ------
    ValueError
        If an arc is out of range, or two arcs are not consecutive.
    """
    arcs = _route_arcs(graph, route)
    checks = []
    for r in requirements:
        effect = evaluate(r, graph, data, values)
        kind = PATTERNS[r.pattern].effect_kind
        if effect.not_applicable is not None:
            check = RequirementCheck(
                r.id, RequirementStatus.NOT_APPLICABLE, effect.not_applicable
            )
        elif kind is EffectKind.VERDICT:
            check = _verdict_check(r, effect, arcs, data, "arc of the route")
        elif kind is EffectKind.COST_TERM:
            check = _cost_check(r, effect, arcs[data.in_scope(r.scope)[arcs]], view)
        elif kind is EffectKind.OBJECTIVE:
            check = _objective_check(r, effect, values, view)
        else:
            check = RequirementCheck(
                r.id, RequirementStatus.NOT_APPLICABLE, "flow bounds apply to flows"
            )
        checks.append(check)
    return Verification(tuple(checks))


def _cost_check(
    requirement: Requirement,
    effect: Effect,
    in_scope: npt.NDArray[np.int64],
    view: ComputationView | None,
) -> RequirementCheck:
    rid = requirement.id
    assert effect.cap is not None
    if in_scope.size == 0:
        return RequirementCheck(
            rid, RequirementStatus.NOT_APPLICABLE, "no arc of the route in the scope"
        )
    if view is None:
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            "a cost term is checked against the computation view, not given",
        )
    over = in_scope[view.cap[in_scope] > effect.cap[in_scope]]
    if over.size:
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            f"the view does not cap {over.size} arcs",
            passed=int(in_scope.size - over.size),
            failed=int(over.size),
            failing=tuple(int(a) for a in over),
        )
    return RequirementCheck(
        rid,
        RequirementStatus.APPLIED,
        f"capped on {in_scope.size} arcs",
        passed=int(in_scope.size),
    )


def verify_flow(
    flow: FlowResult | Sequence[int],
    problem: FlowProblem,
    requirements: RequirementSet,
    data: ArcData,
    values: ResolvedValues,
    *,
    view: ComputationView | None = None,
) -> Verification:
    """Status of each requirement on a flow, whatever method produced it.

    The bounds and the conservation of ``problem`` are checked too
    (:attr:`Verification.violations`). An admissibility requirement is
    checked on the arcs that carry flow; flow bounds on the arcs in scope.

    Parameters
    ----------
    flow : FlowResult or sequence of int
        A result with a flow, or one flow per arc.
    problem : FlowProblem
    requirements : RequirementSet
    data : ArcData
    values : ResolvedValues
    view : ComputationView, optional
        The view the flow was computed with, for its objective.

    Returns
    -------
    Verification

    Raises
    ------
    ValueError
        If the result has no flow, or the flow has another size.
    """
    if isinstance(flow, FlowResult):
        if flow.flow is None:
            raise ValueError(f"the result has no flow (status {flow.status})")
        x = flow.flow
    else:
        x = tuple(flow)
    graph = problem.graph
    if len(x) != graph.m:
        raise ValueError(f"expected {graph.m} arc flows, got {len(x)}")
    carried = np.flatnonzero(np.asarray(x) > 0).astype(np.int64)
    checks = []
    for r in requirements:
        effect = evaluate(r, graph, data, values)
        kind = PATTERNS[r.pattern].effect_kind
        if effect.not_applicable is not None:
            check = RequirementCheck(
                r.id, RequirementStatus.NOT_APPLICABLE, effect.not_applicable
            )
        elif kind is EffectKind.VERDICT:
            check = _verdict_check(r, effect, carried, data, "arc with flow")
        elif kind is EffectKind.BOUND:
            check = _bound_check(r, effect, np.asarray(x, dtype=np.float64), data)
        elif kind is EffectKind.OBJECTIVE:
            check = _objective_check(r, effect, values, view)
        else:
            check = RequirementCheck(
                r.id,
                RequirementStatus.NOT_APPLICABLE,
                "cost terms are checked on routes",
            )
        checks.append(check)
    return Verification(tuple(checks), tuple(problem.violations(x)))


def _objective_check(
    requirement: Requirement,
    effect: Effect,
    values: ResolvedValues,
    view: ComputationView | None,
) -> RequirementCheck:
    rid = requirement.id
    if view is None:
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            "an objective is checked against the computation view, not given",
        )
    if view.objective != effect.objective:
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            f"the view optimizes {view.objective!r}, not {effect.objective!r}",
        )
    value = values.get(requirement.parameters["criterion"])
    assert value is not None
    if value.origin is Origin.CHOICE:
        how = f"chosen: {value.justification}"
    else:
        how = f"prescribed ({value.origin})"
    return RequirementCheck(
        rid, RequirementStatus.APPLIED, f"objective {effect.objective!r}, {how}"
    )


def _bound_check(
    requirement: Requirement,
    effect: Effect,
    x: npt.NDArray[np.float64],
    data: ArcData,
) -> RequirementCheck:
    assert effect.lower is not None
    assert effect.upper is not None
    in_scope = np.flatnonzero(data.in_scope(requirement.scope))
    if in_scope.size == 0:
        return RequirementCheck(
            requirement.id, RequirementStatus.NOT_APPLICABLE, "no arc in the scope"
        )
    lo, hi, v = effect.lower[in_scope], effect.upper[in_scope], x[in_scope]
    out = in_scope[(v < lo) | (v > hi)]
    passed = int(in_scope.size - out.size)
    if out.size:
        return RequirementCheck(
            requirement.id,
            RequirementStatus.NOT_APPLIED,
            f"{out.size} arcs outside their bounds",
            passed=passed,
            failed=int(out.size),
            failing=tuple(int(a) for a in out),
        )
    return RequirementCheck(
        requirement.id,
        RequirementStatus.APPLIED,
        f"within bounds on {passed} arcs",
        passed=passed,
    )
