# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Useful failure: minimal conflicts, relaxations, tiers and impacts."""

import itertools
import math
import operator
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np

from protee.constraints._compose import ComputationView, UnknownPolicy, compose
from protee.constraints._data import ArcData
from protee.constraints._effects import Effect, Verdict, evaluate
from protee.constraints._model import RequirementSet, ResolvedValues
from protee.flow import FlowProblem, FlowResult, Status, methods, solve
from protee.graph import Digraph
from protee.paths import dijkstra, lexicographic_dijkstra
from protee.routes import Route

__all__ = [
    "Conflict",
    "FlowSearch",
    "Impact",
    "Relaxation",
    "RouteSearch",
    "Tier",
    "TieredRelaxation",
    "minimal_conflict",
    "minimal_relaxation",
    "relax_by_tiers",
]

type Feasible = Callable[[frozenset[str]], bool]


class _Counted:
    """A feasibility test with a memory and a deterministic call counter."""

    def __init__(self, feasible: Feasible) -> None:
        self._feasible = feasible
        self._seen: dict[frozenset[str], bool] = {}

    def __call__(self, active: Iterable[str]) -> bool:
        key = frozenset(active)
        if key not in self._seen:
            self._seen[key] = bool(self._feasible(key))
        return self._seen[key]

    @property
    def calls(self) -> int:
        return len(self._seen)


def _ids(requirements: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(requirements))


@dataclass(frozen=True, slots=True)
class Conflict:
    """Requirements that cannot hold together.

    Attributes
    ----------
    requirements : tuple of str
        Infeasible together; with ``deletion_filter``, feasible as soon as
        one is removed; with ``enumeration``, as few as possible.
    method : str
    evaluations : int
        Number of distinct subsets tested.
    """

    requirements: tuple[str, ...]
    method: str
    evaluations: int


@dataclass(frozen=True, slots=True)
class Relaxation:
    """Requirements to relax so that the others hold together.

    Attributes
    ----------
    requirements : tuple of str
        With ``greedy``, none can be kept; with ``enumeration``, as few as
        possible.
    method : str
    evaluations : int
    """

    requirements: tuple[str, ...]
    method: str
    evaluations: int


def minimal_conflict(
    requirements: Iterable[str], feasible: Feasible, *, method: str
) -> Conflict:
    """A minimal set of requirements that cannot hold together.

    Parameters
    ----------
    requirements : iterable of str
        Identifiers, infeasible together.
    feasible : callable
        Whether a set of requirement identifiers holds together; adding a
        requirement never makes an infeasible set feasible.
    method : {"enumeration", "deletion_filter"}
        ``enumeration``: the smallest conflict, by subsets of increasing
        size (exponential, for a few requirements). ``deletion_filter``: an
        irreducible conflict, removing each requirement in turn when the
        rest stays infeasible (Chinneck and Dravnieks, 1991): linear in the
        number of requirements, but not always the smallest.

    Returns
    -------
    Conflict
        Empty when the problem is infeasible without any requirement.

    Raises
    ------
    ValueError
        If the requirements hold together, or the method is unknown.
    """
    ids = _ids(requirements)
    f = _Counted(feasible)
    if method not in ("enumeration", "deletion_filter"):
        raise ValueError(f"unknown method {method!r}")
    if f(ids):
        raise ValueError("the requirements hold together: there is no conflict")
    if method == "enumeration":
        # The whole set is infeasible: the search always ends.
        smallest = next(
            subset
            for k in range(len(ids) + 1)
            for subset in itertools.combinations(ids, k)
            if not f(subset)
        )
        return Conflict(smallest, method, f.calls)
    kept = list(ids)
    for r in ids:
        trial = [x for x in kept if x != r]
        if not f(trial):
            kept = trial
    return Conflict(tuple(kept), method, f.calls)


def minimal_relaxation(
    requirements: Iterable[str], feasible: Feasible, *, method: str
) -> Relaxation:
    """A minimal set of requirements to relax so that the others hold.

    Parameters
    ----------
    requirements : iterable of str
    feasible : callable
        As for :func:`minimal_conflict`.
    method : {"enumeration", "greedy"}
        ``enumeration``: the fewest requirements to relax, by subsets of
        increasing size. ``greedy``: relax every requirement, then keep
        each one again, in the given order, when the problem stays
        feasible; no requirement of the result can be kept.

    Returns
    -------
    Relaxation
        Empty when the requirements already hold together.

    Raises
    ------
    ValueError
        If the problem is infeasible even without any requirement, or the
        method is unknown.
    """
    ids = _ids(requirements)
    f = _Counted(feasible)
    if method not in ("enumeration", "greedy"):
        raise ValueError(f"unknown method {method!r}")
    if f(ids):
        return Relaxation((), method, f.calls)
    if not f(()):
        raise ValueError("infeasible even without any requirement")
    if method == "enumeration":
        # Relaxing every requirement is feasible: the search always ends.
        fewest = next(
            subset
            for k in range(1, len(ids) + 1)
            for subset in itertools.combinations(ids, k)
            if f(set(ids) - set(subset))
        )
        return Relaxation(fewest, method, f.calls)
    relaxed = list(ids)
    for r in ids:
        trial = [x for x in relaxed if x != r]
        if f(set(ids) - set(trial)):
            relaxed = trial
    return Relaxation(tuple(relaxed), method, f.calls)


@dataclass(frozen=True, slots=True)
class Tier:
    """A declared level of relaxation.

    Attributes
    ----------
    level : int
        Positive; tiers are tried by increasing level.
    name : str
        What the level means (for instance, works on a structure).
    relaxable : frozenset of str
        Requirements this level allows to relax, on top of the lower ones.
    """

    level: int
    name: str
    relaxable: frozenset[str]

    def __post_init__(self) -> None:
        if type(self.level) is not int or self.level < 1:
            raise ValueError(f"a tier level is a positive integer, got {self.level!r}")
        object.__setattr__(self, "relaxable", frozenset(self.relaxable))


@dataclass(frozen=True, slots=True)
class TieredRelaxation:
    """The first feasible tier, and what it relaxes.

    Attributes
    ----------
    level : int or None
        Computed from the requirements the option relaxes (0 when none),
        never taken from a label of the data; ``None`` when no tier is
        feasible.
    relaxed : tuple of str
        Requirements relaxed; none of them can be kept.
    tried : tuple of (int, bool)
        Each tier tried, with its feasibility.
    evaluations : int
    """

    level: int | None
    relaxed: tuple[str, ...]
    tried: tuple[tuple[int, bool], ...]
    evaluations: int


def _level(relaxed: Iterable[str], tiers: Sequence[Tier]) -> int:
    """The lowest tier whose relaxations, with the lower ones', cover
    ``relaxed`` (a feasible tier always covers what it relaxes)."""
    need = set(relaxed)
    covered = itertools.accumulate((t.relaxable for t in tiers), operator.or_)
    return next(
        t.level for t, allowed in zip(tiers, covered, strict=True) if need <= allowed
    )


def relax_by_tiers(
    requirements: Iterable[str], feasible: Feasible, tiers: Iterable[Tier]
) -> TieredRelaxation:
    """Try the declared tiers in order and keep the first feasible one.

    Each tier relaxes its requirements on top of the lower tiers'. In the
    first feasible tier, the requirements that can be kept again (in the
    given order) are kept; the level of the option is then computed from
    the requirements it still relaxes.

    Raises
    ------
    ValueError
        If two tiers share a level.
    """
    ids = _ids(requirements)
    ordered = sorted(tiers, key=lambda t: t.level)
    if len({t.level for t in ordered}) != len(ordered):
        raise ValueError("two tiers share a level")
    f = _Counted(feasible)
    if f(ids):
        return TieredRelaxation(0, (), ((0, True),), f.calls)
    tried: list[tuple[int, bool]] = []
    allowed: set[str] = set()
    for tier in ordered:
        allowed |= tier.relaxable
        relaxed = [r for r in ids if r in allowed]
        ok = f(set(ids) - set(relaxed))
        tried.append((tier.level, ok))
        if ok:
            for r in list(relaxed):
                trial = [x for x in relaxed if x != r]
                if f(set(ids) - set(trial)):
                    relaxed = trial
            return TieredRelaxation(
                _level(relaxed, ordered), tuple(relaxed), tuple(tried), f.calls
            )
    return TieredRelaxation(None, (), tuple(tried), f.calls)


@dataclass(frozen=True, slots=True)
class Impact:
    """What one requirement changes to the result: with and without it.

    Attributes
    ----------
    requirement : str
    feasible_with, feasible_without : bool
    cost_with, cost_without : float or None
        Cost of the result, ``None`` when there is none (infeasible, or
        unbounded flow).
    arcs_removed : int or None
        Arcs the requirement alone takes away from the solver (routes).
    """

    requirement: str
    feasible_with: bool
    feasible_without: bool
    cost_with: float | None
    cost_without: float | None
    arcs_removed: int | None = None

    @property
    def delta(self) -> float | None:
        """``cost_with - cost_without``, when both exist."""
        if self.cost_with is None or self.cost_without is None:
            return None
        return self.cost_with - self.cost_without

    def as_dict(self) -> dict[str, float | bool | None]:
        """The impact as plain data."""
        return {
            "feasible_with": self.feasible_with,
            "feasible_without": self.feasible_without,
            "cost_with": self.cost_with,
            "cost_without": self.cost_without,
            "delta": self.delta,
            "arcs_removed": self.arcs_removed,
        }


ROUTE_METHODS = ("dijkstra", "lexicographic_dijkstra")


def _active(all_ids: tuple[str, ...], active: Iterable[str] | None) -> frozenset[str]:
    chosen = frozenset(all_ids if active is None else active)
    if unknown := chosen - set(all_ids):
        raise ValueError(f"unknown requirements {sorted(unknown)}")
    return chosen


@dataclass(frozen=True, slots=True, eq=False)
class RouteSearch:
    """Routes from ``source`` to ``target`` under subsets of the requirements.

    The effects are evaluated once; each query composes those of the
    active requirements and solves with the named method.

    Attributes
    ----------
    requirements : RequirementSet
    graph : Digraph
    data : ArcData
    values : ResolvedValues
    source, target : int
    base : tuple of float
        Base weight of each arc (length, time).
    unknown : UnknownPolicy
    method : {"dijkstra", "lexicographic_dijkstra"}
        ``lexicographic_dijkstra`` minimizes the number of unknown arcs
        first, then the weight.
    penalty : float, optional
        For the ``penalize`` policy.
    """

    requirements: RequirementSet
    graph: Digraph
    data: ArcData
    values: ResolvedValues
    source: int
    target: int
    base: tuple[float, ...]
    unknown: UnknownPolicy
    method: str
    penalty: float | None = None
    _effects: Mapping[str, Effect] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.method not in ROUTE_METHODS:
            raise ValueError(f"unknown method {self.method!r}; one of {ROUTE_METHODS}")
        object.__setattr__(self, "unknown", UnknownPolicy(self.unknown))
        object.__setattr__(self, "base", tuple(float(x) for x in self.base))
        effects = {
            r.id: evaluate(r, self.graph, self.data, self.values)
            for r in self.requirements
        }
        object.__setattr__(self, "_effects", MappingProxyType(effects))

    @property
    def ids(self) -> tuple[str, ...]:
        """Identifiers of the requirements, in the order of the set."""
        return tuple(self._effects)

    def view(self, active: Iterable[str] | None = None) -> ComputationView:
        """The computation view of the active requirements (all by default)."""
        chosen = _active(self.ids, active)
        return compose(
            self.graph,
            [e for rid, e in self._effects.items() if rid in chosen],
            unknown=self.unknown,
            penalty=self.penalty,
        )

    def solve(self, active: Iterable[str] | None = None) -> Route | None:
        """The route under the active requirements, ``None`` if there is none.

        Its cost is the sum of the weights of the view.
        """
        view = self.view(active)
        weights = view.weights(self.base)
        path: tuple[int, ...] | None
        if self.method == "dijkstra":
            path = dijkstra(
                self.graph, weights, self.source, self.target, excluded=view.excluded
            ).path(self.target)
        else:
            path = lexicographic_dijkstra(
                self.graph,
                view.lexicographic_weights(self.base),
                self.source,
                self.target,
                excluded=view.excluded,
            ).path(self.target)
        if path is None:
            return None
        return Route(arcs=path, cost=math.fsum(weights[a] for a in path))

    def feasible(self, active: Iterable[str]) -> bool:
        """Whether a route exists under the active requirements."""
        return self.solve(active) is not None

    def impact(self, requirement: str) -> Impact:
        """The route with and without ``requirement``."""
        with_ = self.solve()
        without = self.solve(set(self.ids) - {requirement})
        effect = self._effects[requirement]
        removed = 0
        if effect.verdict is not None:
            out = effect.verdict == Verdict.FAIL
            if self.unknown is UnknownPolicy.EXCLUDE:
                out |= effect.verdict == Verdict.UNKNOWN
            removed = int(out.sum())
        return Impact(
            requirement,
            with_ is not None,
            without is not None,
            None if with_ is None else float(with_.cost),
            None if without is None else float(without.cost),
            removed,
        )


@dataclass(frozen=True, slots=True, eq=False)
class FlowSearch:
    """Flows of a problem under subsets of the requirements.

    The bounds of the active requirements tighten those of ``problem``;
    an arc whose verdict fails (or is unknown, under the ``exclude``
    policy) carries no flow.

    Attributes
    ----------
    requirements : RequirementSet
    problem : FlowProblem
        Graph, base bounds, costs, supplies and sense.
    data : ArcData
    values : ResolvedValues
    method : str
        A flow method of the registry (see :func:`protee.flow.methods`).
    unknown : UnknownPolicy
        ``exclude`` or ``admit_and_count`` (the default).
    """

    requirements: RequirementSet
    problem: FlowProblem
    data: ArcData
    values: ResolvedValues
    method: str
    unknown: UnknownPolicy = UnknownPolicy.ADMIT_AND_COUNT
    _effects: Mapping[str, Effect] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        names = [info.name for info in methods()]
        if self.method not in names:
            raise ValueError(f"unknown method {self.method!r}; one of {names}")
        policy = UnknownPolicy(self.unknown)
        if policy is UnknownPolicy.PENALIZE:
            raise ValueError("a flow search excludes or admits unknown arcs")
        object.__setattr__(self, "unknown", policy)
        g = self.problem.graph
        effects = {
            r.id: evaluate(r, g, self.data, self.values) for r in self.requirements
        }
        object.__setattr__(self, "_effects", MappingProxyType(effects))

    @property
    def ids(self) -> tuple[str, ...]:
        """Identifiers of the requirements, in the order of the set."""
        return tuple(self._effects)

    def problem_for(self, active: Iterable[str] | None = None) -> FlowProblem | None:
        """The problem under the active requirements, ``None`` when their
        bounds conflict on an arc."""
        chosen = _active(self.ids, active)
        p = self.problem
        view = compose(
            p.graph,
            [e for rid, e in self._effects.items() if rid in chosen],
            unknown=self.unknown,
        )
        base_upper = np.array([math.inf if u is None else u for u in p.upper])
        lower = np.maximum(np.asarray(p.lower, dtype=np.float64), view.lower)
        upper = np.minimum(base_upper, view.upper)
        upper = np.where(view.admitted, upper, 0.0)
        if (lower > upper).any():
            return None
        return FlowProblem(
            p.graph,
            lower=[int(x) for x in lower],
            upper=[None if math.isinf(x) else int(x) for x in upper],
            cost=p.cost,
            supply=p.supply,
            sense=p.sense,
        )

    def solve(self, active: Iterable[str] | None = None) -> FlowResult | None:
        """The result under the active requirements, ``None`` when their
        bounds conflict."""
        problem = self.problem_for(active)
        return None if problem is None else solve(problem, method=self.method)

    def feasible(self, active: Iterable[str]) -> bool:
        """Whether a feasible flow exists under the active requirements."""
        result = self.solve(active)
        return result is not None and result.status is not Status.INFEASIBLE

    def impact(self, requirement: str) -> Impact:
        """The optimum with and without ``requirement``."""

        def outcome(result: FlowResult | None) -> tuple[bool, float | None]:
            if result is None or result.status is Status.INFEASIBLE:
                return False, None
            if result.status is Status.UNBOUNDED or result.objective is None:
                return True, None
            return True, float(result.objective)

        ok_with, cost_with = outcome(self.solve())
        ok_without, cost_without = outcome(self.solve(set(self.ids) - {requirement}))
        return Impact(requirement, ok_with, ok_without, cost_with, cost_without)
