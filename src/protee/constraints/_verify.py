# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Verification of a route or a flow against requirements."""

from __future__ import annotations

import itertools
import math
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
from protee.paths import _bellman_ford
from protee.results import NegativeCycle, ResultCore
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
    - ``not_applicable``: a value is to be set, no element of the result is
      in scope, or the pattern does not apply to this kind of result (flow
      bounds on a route, a speed cap on a flow).
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

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "status", RequirementStatus(self.status))
        set_(self, "failing", tuple(self.failing))
        set_(self, "unknown_arcs", tuple(self.unknown_arcs))


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
        checks = tuple(self.checks)
        object.__setattr__(self, "checks", checks)
        object.__setattr__(self, "violations", tuple(self.violations))
        object.__setattr__(
            self, "_by_id", MappingProxyType({c.requirement: c for c in checks})
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


def _no_data(requirement: Requirement, absent: list[str]) -> RequirementCheck:
    return RequirementCheck(
        requirement.id,
        RequirementStatus.NO_DATA,
        f"attribute {absent[0]!r} absent from the data",
    )


def _outcome(
    requirement: Requirement,
    passed: int,
    failing: tuple[int, ...],
    unknown: tuple[int, ...],
    reasons: tuple[str, str, str],
) -> RequirementCheck:
    """The check from its counts: a failure prevails, then the unknown.

    ``reasons`` gives the text of each status, formatted with the number of
    arcs that fail, lack data, or pass.
    """
    if failing:
        status, reason = RequirementStatus.NOT_APPLIED, reasons[0].format(len(failing))
    elif unknown:
        status, reason = RequirementStatus.PARTIAL, reasons[1].format(len(unknown))
    else:
        status, reason = RequirementStatus.APPLIED, reasons[2].format(passed)
    return RequirementCheck(
        requirement.id,
        status,
        reason,
        passed=passed,
        failed=len(failing),
        unknown=len(unknown),
        failing=failing,
        unknown_arcs=unknown,
    )


def _verdict_check(
    requirement: Requirement,
    effect: Effect,
    arcs: npt.NDArray[np.int64],
    data: ArcData,
    what: str,
) -> RequirementCheck:
    rid = requirement.id
    if absent := _absent(requirement, data):
        return _no_data(requirement, absent)
    assert effect.verdict is not None
    assert effect.reasons is not None
    in_scope = arcs[effect.reasons[arcs] != Reason.OUT_OF_SCOPE]
    if in_scope.size == 0:
        return RequirementCheck(
            rid, RequirementStatus.NOT_APPLICABLE, f"no {what} in the scope"
        )
    v = effect.verdict[in_scope]
    return _outcome(
        requirement,
        int((v == Verdict.PASS).sum()),
        tuple(int(a) for a in in_scope[v == Verdict.FAIL]),
        tuple(int(a) for a in in_scope[v == Verdict.UNKNOWN]),
        ("{} arcs violate it", "{} arcs without data", "verified on {} arcs"),
    )


def _route_arcs(
    graph: Digraph, route: Route | ResultCore | Sequence[int]
) -> tuple[int, ...]:
    if isinstance(route, ResultCore):
        if not hasattr(route, "arcs"):
            raise TypeError(f"a {type(route).__name__} holds no single route")
        found = route.arcs
        if found is None:
            raise ValueError(f"the result has no route (status {route.status})")
        arcs = tuple(found)
    else:
        arcs = tuple(route.arcs if isinstance(route, Route) else route)
    for a in arcs:
        if not 0 <= a < graph.m:
            raise ValueError(f"arc {a} out of range")
    for a, b in itertools.pairwise(arcs):
        if graph.heads[a] != graph.tails[b]:
            raise ValueError(f"arcs {a} and {b} are not consecutive")
    return arcs


type _Weights = tuple[npt.NDArray[np.float64], npt.NDArray[np.int64] | None]


def _weights(
    weights: Sequence[float] | Sequence[tuple[int, float]] | None, m: int
) -> _Weights | None:
    """The weights a route was computed with: the weight of each arc, and
    the count of unknown arcs that comes first for lexicographic ones."""
    if weights is None:
        return None
    items = list(weights)
    if len(items) != m:
        raise ValueError(f"expected {m} weights, got {len(items)}")
    pairs = [x for x in items if isinstance(x, tuple)]
    if not pairs:
        return np.asarray(items, dtype=np.float64), None
    if len(pairs) != m:
        raise ValueError("weights mix numbers and (count, weight) pairs")
    return (
        np.array([float(w) for _, w in pairs], dtype=np.float64),
        np.array([int(u) for u, _ in pairs], dtype=np.int64),
    )


def verify_route(
    route: Route | ResultCore | Sequence[int],
    requirements: RequirementSet,
    graph: Digraph,
    data: ArcData,
    values: ResolvedValues,
    *,
    view: ComputationView | None = None,
    weights: Sequence[float] | Sequence[tuple[int, float]] | None = None,
    criterion: str | None = None,
) -> Verification:
    """Status of each requirement on a route, whatever method produced it.

    Each requirement is evaluated again on the arcs of the route; the
    status never comes from the solver.

    Parameters
    ----------
    route : Route, route result or sequence of int
        The arcs of the route, in order: a :class:`~protee.routes.Route`, a
        result that holds one route (:class:`~protee.routes.WaypointRoute`,
        :class:`~protee.routes.ReliableRoute`, or any result with
        ``arcs``), or the arcs themselves.
    requirements : RequirementSet
    graph : Digraph
    data : ArcData
    values : ResolvedValues
    view : ComputationView, optional
        The view the route was computed with: its excluded arcs bound the
        routes an objective is compared with.
    weights : sequence of float, or of (int, float), optional
        The weight of each arc the route was computed with, as the solver
        used it; pairs (count of unknown arcs, weight) for a lexicographic
        search. A speed cap holds on an arc when its weight is at least its
        length divided by the cap (the unit of the length divided by the
        unit of the speed): a solver that forgot the cap is caught. An
        objective holds when no admitted route is lighter, by an
        independent computation (Bellman-Ford). Without weights, both are
        ``not_applied``.
    criterion : str, optional
        What the weights measure (``"duration"``, ``"length"``), compared
        with the declared objective.

    Returns
    -------
    Verification

    Raises
    ------
    ValueError
        If the result has no route (status ``infeasible``), an arc is out
        of range, two arcs are not consecutive, the weights have another
        size, or a requirement does not fit the data (see
        :func:`evaluate`).
    TypeError
        If a result holds no single route (a shortest path tree), or a
        value does not fit its pattern (see :func:`evaluate`).
    """
    path = _route_arcs(graph, route)
    arcs = np.unique(np.array(path, dtype=np.int64))
    used = _weights(weights, graph.m)
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
            check = _cost_check(r, effect, arcs, data, used)
        elif kind is EffectKind.OBJECTIVE:
            check = _route_objective(
                r, effect, values, graph, path, view, used, criterion
            )
        else:
            check = RequirementCheck(
                r.id,
                RequirementStatus.NOT_APPLICABLE,
                "flow bounds apply to flows, not to routes",
            )
        checks.append(check)
    return Verification(tuple(checks))


def _tolerance(x: float) -> float:
    return 1e-9 * max(1.0, abs(x))


def _cost_check(
    requirement: Requirement,
    effect: Effect,
    arcs: npt.NDArray[np.int64],
    data: ArcData,
    used: _Weights | None,
) -> RequirementCheck:
    rid = requirement.id
    if absent := _absent(requirement, data):
        return _no_data(requirement, absent)
    assert effect.cap is not None
    in_scope = arcs[data.in_scope(requirement.scope)[arcs]]
    if in_scope.size == 0:
        return RequirementCheck(
            rid, RequirementStatus.NOT_APPLICABLE, "no arc of the route in the scope"
        )
    if used is None:
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            "a speed cap is checked on the weights the route was computed "
            "with, not given",
        )
    length = data[requirement.attributes["length"]].values
    failing, unknown, passed = [], [], 0
    for a in in_scope:
        if math.isnan(length[a]):
            unknown.append(int(a))
            continue
        # The time at the cap is the least time the cap allows.
        least = float(length[a] / effect.cap[a])
        if used[0][a] >= least - _tolerance(least):
            passed += 1
        else:
            failing.append(int(a))
    return _outcome(
        requirement,
        passed,
        tuple(failing),
        tuple(unknown),
        (
            "{} arcs timed faster than the cap allows",
            "{} arcs without length",
            "capped on {} arcs",
        ),
    )


def _declared(requirement: Requirement, effect: Effect, values: ResolvedValues) -> str:
    value = values.get(requirement.parameters["criterion"])
    assert value is not None
    if value.origin is Origin.CHOICE:
        how = f"chosen: {value.justification}"
    else:
        how = f"prescribed ({value.origin})"
    return f"objective {effect.objective!r}, {how}"


def _objective_inputs(
    requirement: Requirement,
    effect: Effect,
    given: Mapping[str, object],
    criterion: str | None,
    what: str,
) -> RequirementCheck | None:
    """The check when the inputs of the objective are missing or measure
    another criterion; ``None`` when they can be checked."""
    if missing := [name for name, x in given.items() if x is None]:
        return RequirementCheck(
            requirement.id,
            RequirementStatus.NOT_APPLIED,
            f"an objective is checked with the {', '.join(missing)} of the "
            "computation, not given",
        )
    if criterion != effect.objective:
        return RequirementCheck(
            requirement.id,
            RequirementStatus.NOT_APPLIED,
            f"the {what} measure {criterion!r}, not {effect.objective!r}",
        )
    return None


def _route_objective(
    requirement: Requirement,
    effect: Effect,
    values: ResolvedValues,
    graph: Digraph,
    path: tuple[int, ...],
    view: ComputationView | None,
    used: _Weights | None,
    criterion: str | None,
) -> RequirementCheck:
    rid = requirement.id
    given = {"view": view, "weights": used, "criterion": criterion}
    if (
        early := _objective_inputs(requirement, effect, given, criterion, "weights")
    ) is not None:
        return early
    assert view is not None
    assert used is not None
    declared = _declared(requirement, effect, values)
    if not path:
        return RequirementCheck(
            rid, RequirementStatus.APPLIED, f"{declared}; empty route"
        )
    if barred := sorted(set(path) & set(view.excluded)):
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            f"the route uses {len(barred)} arcs the view excludes",
            failed=len(barred),
            failing=tuple(barred),
        )
    weight, unknown = used
    best = _best_route(
        graph, graph.tails[path[0]], graph.heads[path[-1]], view.excluded, used
    )
    found_w = math.fsum(float(weight[a]) for a in path)
    found_u = 0 if unknown is None else int(sum(int(unknown[a]) for a in path))
    if best is None:
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            "the weights admit a cycle of negative weight: no route is optimal",
        )
    best_u, best_w = best
    if (found_u, found_w) > (best_u, best_w + _tolerance(best_w)):
        lighter = f"{best_w:g}" if unknown is None else f"({best_u}, {best_w:g})"
        heavy = f"{found_w:g}" if unknown is None else f"({found_u}, {found_w:g})"
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            f"a route of weight {lighter} exists, this one weighs {heavy}",
        )
    first = "" if unknown is None else "fewest unknown arcs first, then "
    return RequirementCheck(
        rid,
        RequirementStatus.APPLIED,
        f"{declared}; optimal ({first}{criterion}), checked by Bellman-Ford",
    )


def _best_route(
    graph: Digraph,
    source: int,
    target: int,
    excluded: tuple[int, ...],
    used: _Weights,
) -> tuple[int, float] | None:
    """The least weight from ``source`` to ``target`` on the admitted arcs,
    by Bellman-Ford, independently of the solver; for lexicographic weights,
    the fewest unknown arcs first, then the least weight on the arcs of the
    routes that reach that count."""
    weight, unknown = used
    barred = set(excluded)
    keep = [a for a in range(graph.m) if a not in barred]
    count = 0
    if unknown is not None:
        # Unknown counts are non-negative: no negative cycle.
        count_to = _distances(graph, keep, [int(unknown[a]) for a in keep], source)
        assert count_to is not None
        # The route reaches the target on admitted arcs.
        count = int(count_to[target])
        keep = [
            a
            for a in keep
            if count_to[graph.tails[a]] + int(unknown[a]) == count_to[graph.heads[a]]
        ]
    dist = _distances(graph, keep, [float(weight[a]) for a in keep], source)
    if dist is None:
        return None
    return count, float(dist[target])


def _distances(
    graph: Digraph, keep: list[int], weight: Sequence[float], source: int
) -> tuple[float, ...] | None:
    sub = Digraph.from_arcs(graph.n, [(graph.tails[a], graph.heads[a]) for a in keep])
    found = _bellman_ford(sub, weight, (source,), 0.0)
    if found.cycle is not None:
        return None
    return tuple(float(d) for d in found.distance)


def verify_flow(
    flow: FlowResult | Sequence[int],
    requirements: RequirementSet,
    problem: FlowProblem,
    data: ArcData,
    values: ResolvedValues,
    *,
    criterion: str | None = None,
) -> Verification:
    """Status of each requirement on a flow, whatever method produced it.

    The bounds and the conservation of ``problem`` are checked too
    (:attr:`Verification.violations`). An admissibility requirement is
    checked on the arcs that carry flow; flow bounds on the arcs in scope.

    Parameters
    ----------
    flow : FlowResult or sequence of int
        A result with a flow, or one flow per arc.
    requirements : RequirementSet
    problem : FlowProblem
        The problem the flow was computed for.
    data : ArcData
    values : ResolvedValues
    criterion : str, optional
        What the costs of ``problem`` measure, compared with the declared
        objective. The objective holds when the flow is feasible and no
        improving cycle exists in its residual network (Bellman-Ford,
        independently of the solver); it is ``not_applied`` without a
        criterion.

    Returns
    -------
    Verification

    Raises
    ------
    ValueError
        If the result has no flow, the flow has another size, or a
        requirement does not fit the data (see :func:`evaluate`).
    TypeError
        If a value does not fit its pattern (see :func:`evaluate`).
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
    violations = tuple(problem.violations(x))
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
            check = _bound_check(
                r, effect, np.asarray(x, dtype=np.float64), data, values
            )
        elif kind is EffectKind.OBJECTIVE:
            check = _flow_objective(
                r, effect, values, problem, x, violations, criterion
            )
        else:
            check = RequirementCheck(
                r.id,
                RequirementStatus.NOT_APPLICABLE,
                "speed caps apply to routes, not to flows",
            )
        checks.append(check)
    return Verification(tuple(checks), violations)


def _flow_objective(
    requirement: Requirement,
    effect: Effect,
    values: ResolvedValues,
    problem: FlowProblem,
    x: Sequence[int],
    violations: tuple[str, ...],
    criterion: str | None,
) -> RequirementCheck:
    rid = requirement.id
    given = {"criterion": criterion}
    if (
        early := _objective_inputs(requirement, effect, given, criterion, "costs")
    ) is not None:
        return early
    if violations:
        return RequirementCheck(
            rid, RequirementStatus.NOT_APPLIED, "the flow is not feasible"
        )
    cycle = _improving_cycle(problem, x)
    if cycle is not None:
        return RequirementCheck(
            rid,
            RequirementStatus.NOT_APPLIED,
            f"an improving cycle of {len(cycle.arcs)} arcs exists "
            f"(cost {_shown(cycle.weight)})",
        )
    return RequirementCheck(
        rid,
        RequirementStatus.APPLIED,
        f"{_declared(requirement, effect, values)}; optimal ({problem.sense} "
        f"{criterion}), no improving cycle (Bellman-Ford)",
    )


def _shown(x: float) -> str:
    """``x`` in the short form ``g``; an int beyond the float range, which
    that form cannot write, in full."""
    try:
        return f"{x:g}"
    except OverflowError:
        return str(x)


def _improving_cycle(problem: FlowProblem, x: Sequence[int]) -> NegativeCycle | None:
    """A cycle of the residual network whose cost improves the flow, in the
    minimization form of the problem; exact for int costs, whatever their
    size."""
    g = problem.graph
    sign = 1 if problem.sense == "min" else -1
    arcs: list[tuple[int, int]] = []
    cost: list[int | float] = []
    for a, (u, v) in enumerate(g.arcs()):
        c = sign * problem.cost[a]
        hi = problem.upper[a]
        if hi is None or x[a] < hi:
            arcs.append((u, v))
            cost.append(c)
        if x[a] > problem.lower[a]:
            arcs.append((v, u))
            cost.append(-c)
    scale = max((abs(c) for c in cost), default=0.0)
    exact = all(isinstance(c, int) for c in problem.cost)
    return _bellman_ford(
        Digraph.from_arcs(g.n, arcs),
        cost,
        None,
        0.0 if exact else 1e-9 * max(1.0, scale) * max(1, g.n),
    ).cycle


def _bound_check(
    requirement: Requirement,
    effect: Effect,
    x: npt.NDArray[np.float64],
    data: ArcData,
    values: ResolvedValues,
) -> RequirementCheck:
    assert effect.lower is not None
    assert effect.upper is not None
    in_scope = np.flatnonzero(data.in_scope(requirement.scope))
    if in_scope.size == 0:
        return RequirementCheck(
            requirement.id, RequirementStatus.NOT_APPLICABLE, "no arc in the scope"
        )
    lo, hi, v = effect.lower[in_scope], effect.upper[in_scope], x[in_scope]
    out = (v < lo) | (v > hi)
    # The minimum is not imposed on an arc of unknown element: below it,
    # the membership of the arc decides, and the arc is counted unknown.
    name = requirement.parameters.get("minimum")
    least = None if name is None else values.get(name)
    minimum = least.value if least is not None else 0
    assert isinstance(minimum, (int, float))
    presumed = data.scope_unknown(requirement.scope)[in_scope]
    doubt = presumed & (v < minimum) & ~out
    return _outcome(
        requirement,
        int((~out & ~doubt).sum()),
        tuple(int(a) for a in in_scope[out]),
        tuple(int(a) for a in in_scope[doubt]),
        (
            "{} arcs outside their bounds",
            "{} arcs of unknown element below the minimum",
            "within bounds on {} arcs",
        ),
    )
