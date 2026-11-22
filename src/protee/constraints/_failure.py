# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Useful failure: minimal conflicts, relaxations, tiers and impacts."""

from __future__ import annotations

import itertools
import math
import operator
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from types import MappingProxyType

import numpy as np

from protee.constraints._compose import ComputationView, UnknownPolicy, compose
from protee.constraints._data import ArcData
from protee.constraints._effects import Effect, evaluate
from protee.constraints._model import RequirementSet, ResolvedValues
from protee.constraints._verify import Verification, verify_flow, verify_route
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


class _Counted:
    """A feasibility test with a memory and a deterministic call counter."""

    def __init__(self, feasible: Callable[[frozenset[str]], bool]) -> None:
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


def _ids(ids: Iterable[str]) -> tuple[str, ...]:
    items = tuple(ids)
    for x in items:
        if not isinstance(x, str):
            raise TypeError(f"expected requirement identifiers, got {type(x).__name__}")
    return tuple(dict.fromkeys(items))


def _cost(
    cost: Callable[[frozenset[str]], float | None] | None, active: Iterable[str]
) -> float | None:
    return None if cost is None else cost(frozenset(active))


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
    cost : float or None
        Cost of the result under the requirements kept, when a cost
        function is given (see :meth:`RouteSearch.cost`).
    """

    requirements: tuple[str, ...]
    method: str
    evaluations: int
    cost: float | None = None


def minimal_conflict(
    ids: Iterable[str], feasible: Callable[[frozenset[str]], bool], *, method: str
) -> Conflict:
    """A minimal set of requirements that cannot hold together.

    Parameters
    ----------
    ids : iterable of str
        Requirement identifiers, infeasible together.
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
    TypeError
        If an identifier is not a string.
    """
    names = _ids(ids)
    f = _Counted(feasible)
    if method not in ("enumeration", "deletion_filter"):
        raise ValueError(f"unknown method {method!r}")
    if f(names):
        raise ValueError("the requirements hold together: there is no conflict")
    if method == "enumeration":
        # The whole set is infeasible: the search always ends.
        smallest = next(
            subset
            for k in range(len(names) + 1)
            for subset in itertools.combinations(names, k)
            if not f(subset)
        )
        return Conflict(smallest, method, f.calls)
    kept = list(names)
    for r in names:
        trial = [x for x in kept if x != r]
        if not f(trial):
            kept = trial
    return Conflict(tuple(kept), method, f.calls)


def _relax(
    names: tuple[str, ...], candidates: Sequence[str], f: _Counted, method: str
) -> tuple[str, ...]:
    """Requirements among ``candidates`` to relax so that the others hold,
    knowing that relaxing every candidate is enough."""
    if method == "enumeration":
        return next(
            subset
            for k in range(len(candidates) + 1)
            for subset in itertools.combinations(candidates, k)
            if f(set(names) - set(subset))
        )
    relaxed = list(candidates)
    for r in candidates:
        trial = [x for x in relaxed if x != r]
        if f(set(names) - set(trial)):
            relaxed = trial
    return tuple(relaxed)


_RELAXATION_METHODS = ("enumeration", "greedy")


def minimal_relaxation(
    ids: Iterable[str],
    feasible: Callable[[frozenset[str]], bool],
    *,
    method: str,
    cost: Callable[[frozenset[str]], float | None] | None = None,
) -> Relaxation:
    """A minimal set of requirements to relax so that the others hold.

    Parameters
    ----------
    ids : iterable of str
    feasible : callable
        As for :func:`minimal_conflict`.
    method : {"enumeration", "greedy"}
        ``enumeration``: the fewest requirements to relax, by subsets of
        increasing size. ``greedy``: relax every requirement, then keep
        each one again, in the given order, when the problem stays
        feasible; no requirement of the result can be kept.
    cost : callable, optional
        The cost of the result under a set of requirements
        (:meth:`RouteSearch.cost`, :meth:`FlowSearch.cost`).

    Returns
    -------
    Relaxation
        Empty when the requirements already hold together.

    Raises
    ------
    ValueError
        If the problem is infeasible even without any requirement, or the
        method is unknown.
    TypeError
        If an identifier is not a string.
    """
    names = _ids(ids)
    f = _Counted(feasible)
    if method not in _RELAXATION_METHODS:
        raise ValueError(f"unknown method {method!r}")
    if f(names):
        return Relaxation((), method, f.calls, _cost(cost, names))
    if not f(()):
        raise ValueError("infeasible even without any requirement")
    relaxed = _relax(names, names, f, method)
    return Relaxation(relaxed, method, f.calls, _cost(cost, set(names) - set(relaxed)))


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
        Requirements relaxed.
    tried : tuple of (int, bool)
        Each tier tried, with its feasibility; empty when the requirements
        hold together.
    method : str
    evaluations : int
    cost : float or None
        Cost of the result under the requirements kept, when a cost
        function is given.
    """

    level: int | None
    relaxed: tuple[str, ...]
    tried: tuple[tuple[int, bool], ...]
    method: str
    evaluations: int
    cost: float | None = None


def _level(relaxed: Iterable[str], tiers: Sequence[Tier]) -> int:
    """The lowest tier whose relaxations, with the lower ones', cover
    ``relaxed`` (a feasible tier always covers what it relaxes)."""
    need = set(relaxed)
    covered = itertools.accumulate((t.relaxable for t in tiers), operator.or_)
    return next(
        t.level for t, allowed in zip(tiers, covered, strict=True) if need <= allowed
    )


def relax_by_tiers(
    ids: Iterable[str],
    feasible: Callable[[frozenset[str]], bool],
    tiers: Iterable[Tier],
    *,
    method: str,
    cost: Callable[[frozenset[str]], float | None] | None = None,
) -> TieredRelaxation:
    """Try the declared tiers in order and keep the first feasible one.

    Each tier relaxes its requirements on top of the lower tiers'. In the
    first feasible tier, the requirements to relax are chosen by ``method``
    among those the tier allows; the level of the option is then computed
    from the requirements it relaxes.

    Parameters
    ----------
    ids : iterable of str
        Requirement identifiers.
    feasible : callable
        As for :func:`minimal_conflict`.
    tiers : iterable of Tier
        Distinct levels; every requirement they allow to relax is one of
        ``ids``.
    method : {"enumeration", "greedy"}
        Within the first feasible tier, as for :func:`minimal_relaxation`.
    cost : callable, optional
        The cost of the result under a set of requirements.

    Returns
    -------
    TieredRelaxation

    Raises
    ------
    ValueError
        If two tiers share a level, a tier names an unknown requirement, or
        the method is unknown.
    TypeError
        If an identifier is not a string.
    """
    names = _ids(ids)
    if method not in _RELAXATION_METHODS:
        raise ValueError(f"unknown method {method!r}")
    ordered = sorted(tiers, key=lambda t: t.level)
    if len({t.level for t in ordered}) != len(ordered):
        raise ValueError("two tiers share a level")
    for t in ordered:
        if unknown := sorted(t.relaxable - set(names)):
            raise ValueError(f"tier {t.level} names unknown requirements {unknown}")
    f = _Counted(feasible)
    if f(names):
        return TieredRelaxation(0, (), (), method, f.calls, _cost(cost, names))
    tried: list[tuple[int, bool]] = []
    allowed: set[str] = set()
    for tier in ordered:
        allowed |= tier.relaxable
        candidates = [r for r in names if r in allowed]
        ok = f(set(names) - set(candidates))
        tried.append((tier.level, ok))
        if ok:
            relaxed = _relax(names, candidates, f, method)
            return TieredRelaxation(
                _level(relaxed, ordered),
                relaxed,
                tuple(tried),
                method,
                f.calls,
                _cost(cost, set(names) - set(relaxed)),
            )
    return TieredRelaxation(None, (), tuple(tried), method, f.calls)


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
        Arcs the solver may use without the requirement and not with it
        (routes).
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

    def to_dict(self) -> dict[str, float | bool | None]:
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


def _without(all_ids: tuple[str, ...], requirement: str) -> frozenset[str]:
    if requirement not in all_ids:
        raise ValueError(f"unknown requirement {requirement!r}")
    return frozenset(all_ids) - {requirement}


def _evaluated(
    requirements: RequirementSet, graph: Digraph, data: ArcData, values: ResolvedValues
) -> Mapping[str, Effect]:
    return MappingProxyType(
        {r.id: evaluate(r, graph, data, values) for r in requirements}
    )


@dataclass(frozen=True, slots=True, eq=False)
class RouteSearch:
    """Routes from ``source`` to ``target`` under subsets of the requirements.

    The effects are evaluated once; each query composes those of the
    active requirements and solves with the named method.

    The weight of an arc is a travel time when the requirements include a
    speed cap: its length divided by the least of its speed and the cap,
    computed by the view (:meth:`ComputationView.times`) from the length
    and speed attributes the caps bind, under every subset of the
    requirements. Otherwise it comes from ``base``.

    Attributes
    ----------
    requirements : RequirementSet
    graph : Digraph
    data : ArcData
    values : ResolvedValues
    source, target : int
    method : {"dijkstra", "lexicographic_dijkstra"}
        Keyword only, as all that follows. ``lexicographic_dijkstra``
        minimizes the number of unknown arcs first, then the weight.
    policy : UnknownPolicy
        The policy for the unknown; no default.
    base : tuple of float, optional
        Base weight of each arc (a length, a time); required without a
        speed cap, refused with one.
    criterion : str, optional
        What the weights measure (``"duration"``, ``"length"``), compared
        with a declared objective by :meth:`verify`.
    penalty : float, optional
        For the ``penalize`` policy.

    Raises
    ------
    ValueError
        If the method is unknown, ``base`` is missing or refused, the speed
        caps bind different attributes, or a length or a speed is absent or
        unknown on an arc.
    """

    requirements: RequirementSet
    graph: Digraph
    data: ArcData
    values: ResolvedValues
    source: int
    target: int
    _: KW_ONLY
    method: str
    policy: UnknownPolicy
    base: tuple[float, ...] | None = None
    criterion: str | None = None
    penalty: float | None = None
    _effects: Mapping[str, Effect] = field(init=False, repr=False)
    _time: tuple[tuple[float, ...], tuple[float, ...]] | None = field(
        init=False, repr=False
    )

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        if self.method not in ROUTE_METHODS:
            raise ValueError(f"unknown method {self.method!r}; one of {ROUTE_METHODS}")
        set_(self, "policy", UnknownPolicy(self.policy))
        bound = {
            (r.attributes["length"], r.attributes["speed"])
            for r in self.requirements
            if r.pattern == "speed_cap"
        }
        if len(bound) > 1:
            raise ValueError(
                f"the speed caps bind different length and speed attributes: "
                f"{sorted(bound)}"
            )
        time = None
        if bound:
            if self.base is not None:
                raise ValueError(
                    "with a speed cap, the weights are travel times from the "
                    "length and speed attributes: no base weights"
                )
            columns = []
            for name in next(iter(bound)):
                if name not in self.data:
                    raise ValueError(f"the speed caps need the attribute {name!r}")
                column = self.data[name]
                if column.labels is not None or not column.known.all():
                    raise ValueError(
                        f"attribute {name!r}: a travel time needs a known number "
                        "on every arc; derive the unknown ones explicitly"
                    )
                columns.append(tuple(float(x) for x in column.values))
            time = (columns[0], columns[1])
        elif self.base is None:
            raise ValueError("base weights are required without a speed cap")
        else:
            base = tuple(float(x) for x in self.base)
            if len(base) != self.graph.m:
                raise ValueError(f"expected {self.graph.m} base weights")
            set_(self, "base", base)
        set_(self, "_time", time)
        set_(
            self,
            "_effects",
            _evaluated(self.requirements, self.graph, self.data, self.values),
        )
        self.view()

    @staticmethod
    def methods() -> tuple[str, ...]:
        """The names of the route methods."""
        return ROUTE_METHODS

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
            policy=self.policy,
            penalty=self.penalty,
        )

    def _scalar(self, view: ComputationView) -> tuple[float, ...]:
        if self._time is not None:
            return view.times(*self._time)
        assert self.base is not None
        return view.weights(self.base)

    def weights(
        self, active: Iterable[str] | None = None
    ) -> tuple[float, ...] | tuple[tuple[int, float], ...]:
        """The weights the method minimizes under the active requirements:
        pairs (unknown arc, weight) for ``lexicographic_dijkstra``."""
        view = self.view(active)
        w = self._scalar(view)
        if self.method == "dijkstra":
            return w
        return view.lexicographic_weights(w)

    def solve(self, active: Iterable[str] | None = None) -> Route | None:
        """The route under the active requirements, ``None`` if there is none.

        Its cost is the sum of the weights of its arcs (penalties
        included).
        """
        view = self.view(active)
        w = self._scalar(view)
        path: tuple[int, ...] | None
        if self.method == "dijkstra":
            path = dijkstra(
                self.graph, w, self.source, self.target, excluded=view.excluded
            ).path(self.target)
        else:
            path = lexicographic_dijkstra(
                self.graph,
                view.lexicographic_weights(w),
                self.source,
                self.target,
                excluded=view.excluded,
            ).path(self.target)
        if path is None:
            return None
        return Route(arcs=path, cost=math.fsum(w[a] for a in path))

    def cost(self, active: Iterable[str]) -> float | None:
        """The cost of the route under the active requirements, ``None``
        if there is none."""
        route = self.solve(active)
        return None if route is None else float(route.cost)

    def feasible(self, active: Iterable[str]) -> bool:
        """Whether a route exists under the active requirements."""
        return self.solve(active) is not None

    def verify(
        self, route: Route | Sequence[int], active: Iterable[str] | None = None
    ) -> Verification:
        """Verify every requirement on ``route``, computed under the active
        requirements: :func:`verify_route` with the view, the weights and
        the criterion of the search."""
        return verify_route(
            route,
            self.requirements,
            self.graph,
            self.data,
            self.values,
            view=self.view(active),
            weights=self.weights(active),
            criterion=self.criterion,
        )

    def impact(self, requirement: str) -> Impact:
        """The route with and without ``requirement``.

        Raises
        ------
        ValueError
            If ``requirement`` is not one of :attr:`ids`.
        """
        without = _without(self.ids, requirement)
        route_with, route_without = self.solve(), self.solve(without)
        removed = set(self.view().excluded) - set(self.view(without).excluded)
        return Impact(
            requirement,
            route_with is not None,
            route_without is not None,
            None if route_with is None else float(route_with.cost),
            None if route_without is None else float(route_without.cost),
            len(removed),
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
        Keyword only, as all that follows. A flow method of the registry
        (see :func:`protee.flow.methods`).
    policy : UnknownPolicy
        ``exclude`` or ``admit_and_count``; no default.
    criterion : str, optional
        What the costs of ``problem`` measure, compared with a declared
        objective by :meth:`verify`.
    """

    requirements: RequirementSet
    problem: FlowProblem
    data: ArcData
    values: ResolvedValues
    _: KW_ONLY
    method: str
    policy: UnknownPolicy
    criterion: str | None = None
    _effects: Mapping[str, Effect] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        names = [info.name for info in methods()]
        if self.method not in names:
            raise ValueError(f"unknown method {self.method!r}; one of {names}")
        policy = UnknownPolicy(self.policy)
        if policy is UnknownPolicy.PENALIZE:
            raise ValueError("a flow search excludes or admits unknown arcs")
        object.__setattr__(self, "policy", policy)
        object.__setattr__(
            self,
            "_effects",
            _evaluated(self.requirements, self.problem.graph, self.data, self.values),
        )

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
            policy=self.policy,
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

    def cost(self, active: Iterable[str]) -> float | None:
        """The optimal value under the active requirements, ``None`` when
        there is none (conflicting bounds, infeasible or unbounded)."""
        result = self.solve(active)
        if result is None or result.objective is None:
            return None
        return float(result.objective)

    def feasible(self, active: Iterable[str]) -> bool:
        """Whether a feasible flow exists under the active requirements."""
        result = self.solve(active)
        return result is not None and result.status is not Status.INFEASIBLE

    def verify(
        self, flow: FlowResult | Sequence[int], active: Iterable[str] | None = None
    ) -> Verification:
        """Verify every requirement on ``flow``, computed under the active
        requirements: :func:`verify_flow` with the problem they give and the
        criterion of the search.

        Raises
        ------
        ValueError
            If the bounds of the active requirements conflict.
        """
        problem = self.problem_for(active)
        if problem is None:
            raise ValueError("the bounds of the active requirements conflict")
        return verify_flow(
            flow,
            self.requirements,
            problem,
            self.data,
            self.values,
            criterion=self.criterion,
        )

    def impact(self, requirement: str) -> Impact:
        """The optimum with and without ``requirement``.

        Raises
        ------
        ValueError
            If ``requirement`` is not one of :attr:`ids`.
        """
        without = _without(self.ids, requirement)

        def outcome(result: FlowResult | None) -> tuple[bool, float | None]:
            if result is None or result.status is Status.INFEASIBLE:
                return False, None
            if result.status is Status.UNBOUNDED or result.objective is None:
                return True, None
            return True, float(result.objective)

        ok_with, cost_with = outcome(self.solve())
        ok_without, cost_without = outcome(self.solve(without))
        return Impact(requirement, ok_with, ok_without, cost_with, cost_without)
