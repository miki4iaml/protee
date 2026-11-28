# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Conformity of the methods that explain a failure to the common result
model.

Every method of :func:`protee.constraints.methods` runs on the same
instances: families of conflicts drawn by Hypothesis, random road networks
and a life-cycle profile. The guarantee of each method is verified by an
independent computation: the conflict is tested again, without each of its
requirements too; each relaxed requirement is restored; every subset is
enumerated for the smallest conflict and the fewest relaxations; the work
stays within the complexity the registry states.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import partial

import networkx as nx
import pytest
from conformity import check_core, check_registry
from constraints_cases import (
    MIN_L03,
    OC_ALL,
    OC_L03,
    PROFILE,
    RETURN,
    endpoints,
    occurrence,
    profile,
    random_case,
    requirement,
    requirement_set,
    resolved,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from test_conformity_paths import check_separating_cut

from protee import flow
from protee.constraints import (
    Conflict,
    FlowSearch,
    InfeasibleSubset,
    Relaxation,
    Requirement,
    RequirementStatus,
    RouteSearch,
    Tier,
    TieredRelaxation,
    UnknownPolicy,
    methods,
    minimal_conflict,
    minimal_relaxation,
    relax_by_tiers,
)
from protee.flow import FlowProblem
from protee.results import GuaranteeKind, MethodInfo, Status

type Test = Callable[[frozenset[str]], bool]
type Cost = Callable[[frozenset[str]], float | None]

INFOS = {(info.problem, info.name): info for info in methods()}
CONFLICT = [name for (p, name) in INFOS if p == "minimal_conflict"]
RELAXATION = [name for (p, name) in INFOS if p == "minimal_relaxation"]
TIERS = [name for (p, name) in INFOS if p == "relaxation_by_tiers"]


def test_registry() -> None:
    check_registry(methods())
    kinds = {key: info.guarantee.kind for key, info in INFOS.items()}
    exact, prop = GuaranteeKind.EXACT, GuaranteeKind.PROPERTY
    assert kinds == {
        ("minimal_conflict", "enumeration"): exact,
        ("minimal_conflict", "deletion_filter"): prop,
        ("minimal_relaxation", "enumeration"): exact,
        ("minimal_relaxation", "greedy"): prop,
        ("relaxation_by_tiers", "enumeration"): exact,
        ("relaxation_by_tiers", "greedy"): prop,
    }
    for problem in ("minimal_conflict", "minimal_relaxation", "relaxation_by_tiers"):
        assert methods(problem) == tuple(
            info for info in methods() if info.problem == problem
        )
    assert all(info.options == () for info in methods())
    assert all("feasibility tests" in info.complexity for info in methods())
    with pytest.raises(ValueError, match="unknown problem 'shortest_paths'"):
        methods("shortest_paths")


def test_each_function_takes_the_methods_of_its_problem() -> None:
    def never(_active: frozenset[str]) -> bool:
        return False

    def always(_active: frozenset[str]) -> bool:
        return True

    tiers = [Tier(1, "all", frozenset({"A"}))]
    calls: dict[str, Callable[[str], object]] = {
        "minimal_conflict": lambda m: minimal_conflict(["A"], never, method=m),
        "minimal_relaxation": lambda m: minimal_relaxation(["A"], always, method=m),
        "relaxation_by_tiers": lambda m: relax_by_tiers(["A"], always, tiers, method=m),
    }
    every = {info.name for info in methods()}
    for problem, call in calls.items():
        own = {info.name for info in methods(problem)}
        for name in sorted(own):
            call(name)
        for name in sorted(every - own):
            with pytest.raises(ValueError, match=f"unknown method {name!r}"):
                call(name)


# Oracles: every subset, and the bounds of the registry ---------------------


def subsets(items: Iterable[str]) -> list[frozenset[str]]:
    """Every subset of ``items``, by increasing size."""
    pool = sorted(set(items))
    return [
        frozenset(c)
        for k in range(len(pool) + 1)
        for c in itertools.combinations(pool, k)
    ]


def smallest_conflict(ids: Sequence[str], feasible: Test) -> int:
    return min(len(s) for s in subsets(ids) if not feasible(s))


def fewest_relaxed(ids: Sequence[str], allowed: Iterable[str], feasible: Test) -> int:
    return min(len(s) for s in subsets(allowed) if feasible(frozenset(ids) - s))


@dataclass
class Recorder:
    """A feasibility test that records the sets it is called with."""

    feasible: Test
    calls: list[frozenset[str]]

    def __call__(self, active: frozenset[str]) -> bool:
        self.calls.append(active)
        return self.feasible(active)

    def check(self, tests: int) -> None:
        """The counter is the number of calls, each with a distinct set."""
        assert tests == len(self.calls) == len(set(self.calls))


def expected_status(info: MethodInfo) -> Status:
    exact = info.guarantee.kind is GuaranteeKind.EXACT
    return Status.OPTIMAL if exact else Status.FEASIBLE


def check_conflict(ids: Sequence[str], feasible: Test, method: str) -> None:
    info = INFOS["minimal_conflict", method]
    if feasible(frozenset(ids)):
        with pytest.raises(ValueError, match="no conflict"):
            minimal_conflict(ids, feasible, method=method)
        return
    recorder = Recorder(feasible, [])
    result = minimal_conflict(ids, recorder, method=method)
    check_core(result, info, lambda: minimal_conflict(ids, feasible, method=method))
    assert isinstance(result, Conflict)
    assert result.status is expected_status(info)
    assert result.certificate is None
    tests = result.counters["feasibility_tests"]
    recorder.check(tests)
    assert result.evaluations == tests
    found = frozenset(result.requirements)
    assert len(found) == len(result.requirements)
    assert found <= set(ids)
    # Tested again: infeasible, and irreducible (both methods).
    assert not feasible(found)
    for r in found:
        assert feasible(found - {r})
    k = len(ids)
    if method == "enumeration":
        assert len(found) == smallest_conflict(ids, feasible)
        assert tests <= 2**k
    else:
        assert tests <= k + 1


def check_relaxation(
    ids: Sequence[str], feasible: Test, cost: Cost, method: str
) -> None:
    info = INFOS["minimal_relaxation", method]
    if not feasible(frozenset()):
        with pytest.raises(ValueError, match="without any requirement"):
            minimal_relaxation(ids, feasible, method=method)
        return
    recorder = Recorder(feasible, [])
    result = minimal_relaxation(ids, recorder, method=method, cost=cost)
    check_core(
        result,
        info,
        lambda: minimal_relaxation(ids, feasible, method=method, cost=cost),
    )
    assert isinstance(result, Relaxation)
    assert result.status is expected_status(info)
    assert result.certificate is None
    tests = result.counters["feasibility_tests"]
    recorder.check(tests)
    assert result.evaluations == tests
    relaxed = frozenset(result.requirements)
    kept = frozenset(ids) - relaxed
    # The others hold, and no relaxed requirement can be restored.
    assert feasible(kept)
    for r in relaxed:
        assert not feasible(kept | {r})
    assert result.cost == cost(kept)
    k = len(ids)
    if method == "enumeration":
        assert len(relaxed) == fewest_relaxed(ids, ids, feasible)
        assert tests <= 2**k
    else:
        assert tests <= k + 2


def check_tiers(
    ids: Sequence[str], feasible: Test, cost: Cost, tiers: Sequence[Tier], method: str
) -> None:
    info = INFOS["relaxation_by_tiers", method]
    recorder = Recorder(feasible, [])
    result = relax_by_tiers(ids, recorder, tiers, method=method, cost=cost)
    check_core(
        result,
        info,
        lambda: relax_by_tiers(ids, feasible, tiers, method=method, cost=cost),
    )
    assert isinstance(result, TieredRelaxation)
    tests = result.counters["feasibility_tests"]
    recorder.check(tests)
    assert result.evaluations == tests
    if feasible(frozenset(ids)):
        assert (result.level, result.relaxed, result.tried) == (0, (), ())
        assert result.status is expected_status(info)
        assert result.cost == cost(frozenset(ids))
        return
    # The first tier whose relaxations, with the lower ones', make the
    # others hold.
    allowed: set[str] = set()
    tried: list[tuple[int, bool]] = []
    for tier in sorted(tiers, key=lambda t: t.level):
        allowed |= tier.relaxable
        tried.append((tier.level, feasible(frozenset(ids) - allowed)))
        if tried[-1][1]:
            break
    assert result.tried == tuple(tried)
    c = len(allowed)
    if not tried or not tried[-1][1]:
        assert result.status is Status.INFEASIBLE
        assert (result.level, result.relaxed, result.cost) == (None, (), None)
        certificate = result.certificate
        assert isinstance(certificate, InfeasibleSubset)
        # Tested again: the requirements no tier relaxes do not hold.
        assert set(certificate.requirements) == set(ids) - allowed
        assert not feasible(frozenset(certificate.requirements))
        assert tests <= len(tiers) + 1
        return
    assert result.status is expected_status(info)
    assert result.certificate is None
    assert result.level == tried[-1][0]
    relaxed = frozenset(result.relaxed)
    kept = frozenset(ids) - relaxed
    assert relaxed <= allowed
    assert feasible(kept)
    for r in relaxed:
        assert not feasible(kept | {r})
    assert result.cost == cost(kept)
    if method == "enumeration":
        assert len(relaxed) == fewest_relaxed(ids, allowed, feasible)
        assert tests <= len(tiers) + 2**c
    else:
        assert tests <= len(tiers) + c + 1


def ladders(ids: Sequence[str]) -> list[list[Tier]]:
    """Tiers for an instance: one requirement per tier, from the last; and
    a single tier for the first half of the requirements."""
    one_by_one = [
        Tier(level, f"relax {r}", frozenset({r}))
        for level, r in enumerate(reversed(ids), start=1)
    ]
    half = [Tier(2, "first half", frozenset(ids[: len(ids) // 2]))]
    return [one_by_one, half, []]


# Families of conflicts, drawn by Hypothesis ---------------------------------


@st.composite
def families(draw: st.DrawFn) -> tuple[tuple[str, ...], tuple[frozenset[str], ...]]:
    """Identifiers in any order and the minimal conflicts of a monotone
    test; an empty conflict makes the problem infeasible without any
    requirement."""
    k = draw(st.integers(0, 6))
    ids = tuple(draw(st.permutations([f"R{i}" for i in range(k)])))
    conflicts = draw(st.lists(parts(ids), max_size=3))
    return ids, tuple(conflicts)


def parts(ids: tuple[str, ...]) -> st.SearchStrategy[frozenset[str]]:
    """Subsets of at most three identifiers, the empty one included."""
    if not ids:
        return st.just(frozenset())
    return st.frozensets(st.sampled_from(ids), max_size=3)


def holds(conflicts: Iterable[frozenset[str]]) -> Test:
    found = tuple(conflicts)

    def feasible(active: frozenset[str]) -> bool:
        return not any(c <= active for c in found)

    return feasible


def size(active: frozenset[str]) -> float:
    return float(len(active))


@pytest.mark.parametrize("method", CONFLICT)
@given(family=families())
@settings(max_examples=80)
def test_conflict_methods_conform(
    method: str, family: tuple[tuple[str, ...], tuple[frozenset[str], ...]]
) -> None:
    ids, conflicts = family
    check_conflict(ids, holds(conflicts), method)


@pytest.mark.parametrize("method", RELAXATION)
@given(family=families())
@settings(max_examples=80)
def test_relaxation_methods_conform(
    method: str, family: tuple[tuple[str, ...], tuple[frozenset[str], ...]]
) -> None:
    ids, conflicts = family
    check_relaxation(ids, holds(conflicts), size, method)


@st.composite
def tiered(
    draw: st.DrawFn,
) -> tuple[tuple[str, ...], tuple[frozenset[str], ...], list[Tier]]:
    ids, conflicts = draw(families())
    levels = draw(st.lists(st.integers(1, 5), unique=True, max_size=3))
    tiers = [Tier(level, f"tier {level}", draw(parts(ids))) for level in levels]
    return ids, conflicts, tiers


@pytest.mark.parametrize("method", TIERS)
@given(case=tiered())
@settings(max_examples=80)
def test_tier_methods_conform(
    method: str,
    case: tuple[tuple[str, ...], tuple[frozenset[str], ...], list[Tier]],
) -> None:
    ids, conflicts, tiers = case
    check_tiers(ids, holds(conflicts), size, tiers, method)


@given(family=families())
@settings(max_examples=60)
def test_exact_and_property_methods_agree(
    family: tuple[tuple[str, ...], tuple[frozenset[str], ...]],
) -> None:
    # The smallest conflict is never larger than an irreducible one, the
    # fewest relaxations never more than a greedy one.
    ids, conflicts = family
    feasible = holds(conflicts)
    if not feasible(frozenset(ids)):
        exact = minimal_conflict(ids, feasible, method="enumeration")
        irreducible = minimal_conflict(ids, feasible, method="deletion_filter")
        assert len(exact.requirements) <= len(irreducible.requirements)
        assert len(exact.requirements) == min(len(c) for c in conflicts)
    if feasible(frozenset()):
        fewest = minimal_relaxation(ids, feasible, method="enumeration")
        greedy = minimal_relaxation(ids, feasible, method="greedy")
        assert len(fewest.requirements) <= len(greedy.requirements)


# The two reference applications ---------------------------------------------


@dataclass(frozen=True)
class Instance:
    ids: tuple[str, ...]
    feasible: Test
    cost: Cost


def route(seed: int, policy: UnknownPolicy) -> Instance:
    case = random_case(seed)
    s, t = endpoints(seed, case.graph.n)
    search = RouteSearch(
        requirement_set(),
        case.graph,
        case.data(),
        resolved(),
        s,
        t,
        method="dijkstra",
        policy=policy,
    )
    return Instance(search.ids, search.feasible, search.cost)


def life_cycle(*requirements: Requirement, policy: UnknownPolicy) -> Instance:
    reqs, data, vals = profile(*requirements)
    search = FlowSearch(
        reqs,
        FlowProblem(PROFILE, cost=[1] * 6, sense="max"),
        data,
        vals,
        method="network_simplex",
        policy=policy,
    )
    return Instance(search.ids, search.feasible, search.cost)


ZONE = requirement("ZONE", "zone_exclusion", attributes={"inside": "in_zone"})
INSTANCES: dict[str, Callable[[], Instance]] = {
    **{
        f"route-{seed}-{policy}": partial(route, seed, policy)
        for seed in range(8)
        for policy in (UnknownPolicy.EXCLUDE, UnknownPolicy.ADMIT_AND_COUNT)
    },
    "profile-overconstrained": lambda: life_cycle(
        OC_ALL, OC_L03, MIN_L03, RETURN, policy=UnknownPolicy.ADMIT_AND_COUNT
    ),
    "profile-cut": lambda: life_cycle(
        occurrence("CUT-L01", "zero", ["L01"]),
        RETURN,
        policy=UnknownPolicy.ADMIT_AND_COUNT,
    ),
    "profile-zone": lambda: life_cycle(
        ZONE, OC_ALL, RETURN, policy=UnknownPolicy.EXCLUDE
    ),
}


@pytest.mark.parametrize("name", sorted(INSTANCES))
def test_every_method_conforms_on_the_reference_applications(name: str) -> None:
    instance = INSTANCES[name]()
    ids, feasible, cost = instance.ids, instance.feasible, instance.cost
    for method in CONFLICT:
        check_conflict(ids, feasible, method)
    for method in RELAXATION:
        check_relaxation(ids, feasible, cost, method)
    for tiers in ladders(ids):
        for method in TIERS:
            check_tiers(ids, feasible, cost, tiers, method)


def test_the_reference_applications_cover_every_outcome() -> None:
    # The instances reach conflicts, relaxations, tiers infeasible and
    # requirements that already hold.
    outcomes: set[str] = set()
    for make in INSTANCES.values():
        instance = make()
        ids, feasible = instance.ids, instance.feasible
        outcomes.add("conflict" if not feasible(frozenset(ids)) else "holds")
        for tiers in ladders(ids):
            result = relax_by_tiers(ids, feasible, tiers, method="greedy")
            outcomes.add(str(result.status))
    assert outcomes == {"conflict", "holds", "feasible", "infeasible"}


# Fingerprint of the inputs ---------------------------------------------------


def test_fingerprint_follows_the_inputs() -> None:
    ids = ("A", "B", "C")
    feasible = holds([frozenset({"A", "B"})])
    base = minimal_conflict(ids, feasible, method="deletion_filter")
    assert dict(base.parameters) == {}
    assert minimal_conflict(list(ids), feasible, method="deletion_filter").inputs == (
        base.inputs
    )
    # The order of the identifiers is an input of the method.
    reordered = minimal_conflict(("B", "A", "C"), feasible, method="deletion_filter")
    assert reordered.inputs != base.inputs
    assert minimal_conflict(ids, feasible, method="enumeration").inputs != base.inputs
    # The same method name in two problems.
    assert (
        minimal_relaxation(ids, feasible, method="enumeration").inputs
        != minimal_conflict(ids, feasible, method="enumeration").inputs
    )
    # The feasibility test, a callable, is not part of the fingerprint.
    other = holds([frozenset({"A", "C"})])
    assert minimal_conflict(ids, other, method="deletion_filter").inputs == (
        base.inputs
    )
    tiers = [Tier(1, "a", frozenset({"A"})), Tier(2, "b", frozenset({"B"}))]
    first = relax_by_tiers(ids, feasible, tiers, method="greedy")
    assert first.level == 1

    def again(declared: list[Tier]) -> str:
        return relax_by_tiers(ids, feasible, declared, method="greedy").inputs

    # Tiers are tried by level: their order is not an input, their content is.
    assert again(tiers[::-1]) == first.inputs
    assert again([Tier(1, "a", frozenset({"A", "C"})), tiers[1]]) != first.inputs
    assert again([Tier(1, "first", frozenset({"A"})), tiers[1]]) != first.inputs


# The route of a search -----------------------------------------------------


def oracle_cost(search: RouteSearch, active: frozenset[str]) -> float:
    """Shortest weight from the source to the target, by NetworkX, on the
    arcs the view admits."""
    view = search.view(active)
    weights = search.weights(active)
    barred = set(view.excluded)
    g = nx.MultiDiGraph()
    g.add_nodes_from(range(search.graph.n))
    for a, (u, v) in enumerate(search.graph.arcs()):
        if a not in barred:
            g.add_edge(u, v, weight=weights[a])
    try:
        return float(
            nx.dijkstra_path_length(g, search.source, search.target, weight="weight")
        )
    except nx.NetworkXNoPath:
        return math.inf


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize(
    "policy", [UnknownPolicy.EXCLUDE, UnknownPolicy.ADMIT_AND_COUNT]
)
def test_route_search_conforms(seed: int, policy: UnknownPolicy) -> None:
    case = random_case(seed)
    s, t = endpoints(seed, case.graph.n)
    infos = {info.name: info for info in RouteSearch.methods()}
    check_registry(tuple(infos.values()))
    seen = set()
    for method, info in infos.items():
        search = RouteSearch(
            requirement_set(),
            case.graph,
            case.data(),
            resolved(),
            s,
            t,
            method=method,
            policy=policy,
        )
        for active in (frozenset(search.ids), frozenset()):
            result = search.solve(active)
            check_core(result, info, lambda: search.solve(active))  # noqa: B023
            assert result.active == tuple(r for r in search.ids if r in active)
            seen.add(result.status)
            if result.status is Status.INFEASIBLE:
                assert result.route is None
                assert (result.arcs, result.cost) == (None, None)
                check_separating_cut(
                    case.graph, result.certificate, search.view(active).excluded
                )
                assert not search.feasible(active)
                assert search.cost(active) is None
            else:
                assert result.route is not None
                assert search.feasible(active)
                if method == "dijkstra":
                    assert math.isclose(result.route.cost, oracle_cost(search, active))
                # The verification agrees with the search: no active
                # requirement is violated; an unknown arc is admitted and
                # counted only under that policy.
                verification = search.verify(result, active)
                allowed = {RequirementStatus.APPLIED, RequirementStatus.NOT_APPLICABLE}
                if policy is UnknownPolicy.ADMIT_AND_COUNT:
                    allowed.add(RequirementStatus.PARTIAL)
                for rid in active:
                    assert verification[rid].status in allowed, verification[rid]
    assert seen <= {Status.OPTIMAL, Status.INFEASIBLE}


def test_route_search_meets_both_outcomes() -> None:
    statuses = set()
    for seed in range(8):
        case = random_case(seed)
        s, t = endpoints(seed, case.graph.n)
        search = RouteSearch(
            requirement_set(),
            case.graph,
            case.data(),
            resolved(),
            s,
            t,
            method="dijkstra",
            policy=UnknownPolicy.EXCLUDE,
        )
        statuses.add(search.solve().status)
    assert statuses == {Status.OPTIMAL, Status.INFEASIBLE}


# The flow of a search -------------------------------------------------------

FLOW_INFOS = {info.name: info for info in flow.methods("min_cost_flow")}
MIN_L04 = occurrence("MIN-L04", "one", ["L04"], minimum="one")
MIN_L05 = occurrence("MIN-L05", "one", ["L05"], minimum="one")
PROFILES = {
    # A maximum and a minimum on L03 that cannot both hold.
    "bounds": ((OC_ALL, OC_L03, MIN_L03, RETURN), UnknownPolicy.ADMIT_AND_COUNT),
    # L04 lies in the zone: the zone bars the arc a minimum needs.
    "bar": ((ZONE, MIN_L04, OC_ALL, RETURN), UnknownPolicy.ADMIT_AND_COUNT),
    # Whether L05 lies in the zone is unknown: barred under ``exclude``.
    "unknown": ((ZONE, MIN_L05, RETURN), UnknownPolicy.EXCLUDE),
}


@pytest.mark.parametrize("method", sorted(FLOW_INFOS))
@pytest.mark.parametrize("name", sorted(PROFILES))
def test_flow_search_conforms(method: str, name: str) -> None:
    # Under every subset of the requirements: the result of the flow
    # method, or, when the bounds conflict, an infeasible result whose
    # certificate is tested again: its requirements alone conflict.
    requirements, policy = PROFILES[name]
    reqs, data, vals = profile(*requirements)
    search = FlowSearch(
        reqs,
        FlowProblem(PROFILE, cost=[1] * 6, sense="max"),
        data,
        vals,
        method=method,
        policy=policy,
    )
    info = FLOW_INFOS[method]
    conflicts = 0
    for k in range(len(search.ids) + 1):
        for active in itertools.combinations(search.ids, k):
            result = search.solve(active)
            check_core(result, info, lambda: search.solve(active))  # noqa: B023
            problem = search.problem_for(active)
            if problem is not None:
                assert result == flow.solve(problem, method=method)
                continue
            conflicts += 1
            assert result.status is Status.INFEASIBLE
            assert (result.flow, result.objective) == (None, None)
            assert set(result.counters.values()) == {0}
            assert not search.feasible(active)
            assert search.cost(active) is None
            certificate = result.certificate
            assert isinstance(certificate, InfeasibleSubset)
            assert set(certificate.requirements) <= set(active)
            assert certificate.requirements == tuple(
                r for r in search.ids if r in certificate.requirements
            )
            assert search.problem_for(certificate.requirements) is None
            assert not search.feasible(certificate.requirements)
    assert conflicts > 0
