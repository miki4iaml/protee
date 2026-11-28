# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Useful failure: conflicts, relaxations, tiers and impacts, on routes and
on life-cycle profiles."""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable

import pytest
from constraints_cases import (
    CLIENT,
    CLIENT_SRC,
    ELEMENTS,
    MASS,
    MIN_L03,
    OC_ALL,
    OC_L03,
    OCC_PARAMETERS,
    PARAMETERS,
    PROFILE,
    REG,
    RETURN,
    ROUTING,
    SRC,
    occurrence,
    profile,
    requirement,
    requirement_set,
    resolved,
    value,
    values,
)

from protee.constraints import (
    ArcData,
    Attribute,
    FlowSearch,
    Impact,
    InfeasibleSubset,
    Origin,
    Parameter,
    Requirement,
    RequirementSet,
    RequirementStatus,
    RouteSearch,
    Tier,
    UnknownPolicy,
    Value,
    ValueSet,
    minimal_conflict,
    minimal_relaxation,
    provenance,
    relax_by_tiers,
    requirement_table,
    resolve_values,
    verify_flow,
    verify_route,
)
from protee.flow import FlowProblem, solve
from protee.graph import Digraph
from protee.results import GuaranteeKind, Status

S = RequirementStatus

# Generic methods, against a family of minimal conflicts -----------------


def family(seed: int) -> tuple[tuple[str, ...], list[frozenset[str]]]:
    rng = random.Random(seed)
    ids = tuple(f"R{k}" for k in range(6))
    conflicts = [
        frozenset(rng.sample(ids, rng.randint(1, 3))) for _ in range(rng.randint(1, 3))
    ]
    return ids, conflicts


def holds(conflicts: list[frozenset[str]]) -> Callable[[frozenset[str]], bool]:
    def feasible(active: frozenset[str]) -> bool:
        return not any(c <= active for c in conflicts)

    return feasible


@pytest.mark.parametrize("seed", range(25))
def test_conflicts_and_relaxations_against_enumeration(seed: int) -> None:
    ids, conflicts = family(seed)
    feasible = holds(conflicts)
    smallest = min(len(c) for c in conflicts)
    exact = minimal_conflict(ids, feasible, method="enumeration")
    assert len(exact.requirements) == smallest
    assert not feasible(frozenset(exact.requirements))
    assert exact.status is Status.OPTIMAL
    assert exact.guarantee.kind is GuaranteeKind.EXACT
    irreducible = minimal_conflict(ids, feasible, method="deletion_filter")
    assert frozenset(irreducible.requirements) in conflicts
    assert irreducible.method == "deletion_filter"
    assert irreducible.status is Status.FEASIBLE
    assert irreducible.guarantee.kind is GuaranteeKind.PROPERTY
    assert irreducible.evaluations == irreducible.counters["feasibility_tests"]
    assert irreducible.evaluations <= len(ids) + 1
    hitting = [
        k
        for k in range(len(ids) + 1)
        for s in itertools.combinations(ids, k)
        if all(c & set(s) for c in conflicts)
    ]
    fewest = minimal_relaxation(ids, feasible, method="enumeration")
    assert len(fewest.requirements) == hitting[0]
    assert fewest.status is Status.OPTIMAL
    greedy = minimal_relaxation(ids, feasible, method="greedy")
    assert greedy.status is Status.FEASIBLE
    kept = frozenset(ids) - set(greedy.requirements)
    assert feasible(kept)
    for r in greedy.requirements:
        assert not feasible(kept | {r})


def test_generic_methods_edge_cases() -> None:
    ids = ("A", "B")

    def always(_active: frozenset[str]) -> bool:
        return True

    def never(_active: frozenset[str]) -> bool:
        return False

    with pytest.raises(ValueError, match="no conflict"):
        minimal_conflict(ids, always, method="enumeration")
    # Infeasible without any requirement: the empty conflict, found by
    # either method, with the status of the method.
    for method, status in (
        ("enumeration", Status.OPTIMAL),
        ("deletion_filter", Status.FEASIBLE),
    ):
        empty = minimal_conflict(ids, never, method=method)
        assert (empty.requirements, empty.status) == ((), status)
    # Already holding: the empty relaxation.
    for method, status in (
        ("enumeration", Status.OPTIMAL),
        ("greedy", Status.FEASIBLE),
    ):
        none = minimal_relaxation(ids, always, method=method)
        assert (none.requirements, none.status, none.evaluations) == ((), status, 1)
    with pytest.raises(ValueError, match="without any requirement"):
        minimal_relaxation(ids, never, method="greedy")
    with pytest.raises(ValueError, match="unknown method 'iis' for minimal_conflict"):
        minimal_conflict(ids, never, method="iis")
    with pytest.raises(ValueError, match="unknown method 'best'"):
        minimal_relaxation(ids, always, method="best")
    with pytest.raises(ValueError, match="unknown method 'greedy'"):
        minimal_conflict(ids, never, method="greedy")
    with pytest.raises(TypeError, match="expected requirement identifiers"):
        minimal_conflict(requirement_set(), never, method="enumeration")  # type: ignore[arg-type]


def test_tier_is_computed_from_the_conditions() -> None:
    # A7: the option needs works on a structure (tier 3); no label of the
    # data decides its tier.
    tiers = [
        Tier(1, "detour", frozenset({"DETOUR"})),
        Tier(3, "works on a structure", frozenset({"WORKS", "DETOUR"})),
    ]
    feasible = holds([frozenset({"WORKS"})])
    result = relax_by_tiers(["DETOUR", "WORKS"], feasible, tiers, method="greedy")
    assert result.level == 3
    assert result.relaxed == ("WORKS",)
    assert result.tried == ((1, False), (3, True))
    assert (result.method, result.cost) == ("greedy", None)
    assert (result.status, result.certificate) == (Status.FEASIBLE, None)
    exact = relax_by_tiers(["DETOUR", "WORKS"], feasible, tiers, method="enumeration")
    assert (exact.level, exact.relaxed, exact.status) == (3, ("WORKS",), Status.OPTIMAL)
    none_needed = relax_by_tiers(["DETOUR", "WORKS"], holds([]), tiers, method="greedy")
    assert (none_needed.level, none_needed.relaxed, none_needed.tried) == (0, (), ())
    assert none_needed.status is Status.FEASIBLE
    # No tier is feasible: infeasible, and the requirements that no tier
    # relaxes, infeasible together, are the certificate.
    hopeless = relax_by_tiers(
        ["DETOUR", "WORKS", "X"], holds([frozenset({"X"})]), tiers, method="greedy"
    )
    assert hopeless.level is None
    assert hopeless.status is Status.INFEASIBLE
    assert hopeless.tried == ((1, False), (3, False))
    assert hopeless.certificate == InfeasibleSubset(("X",))
    untiered = relax_by_tiers(
        ["A"], holds([frozenset({"A"})]), [], method="enumeration"
    )
    assert (untiered.status, untiered.tried) == (Status.INFEASIBLE, ())
    assert untiered.certificate == InfeasibleSubset(("A",))
    with pytest.raises(ValueError, match="share a level"):
        relax_by_tiers(
            ["DETOUR", "WORKS"], feasible, [tiers[0], tiers[0]], method="greedy"
        )
    with pytest.raises(ValueError, match=r"unknown requirements \['WORKS'\]"):
        relax_by_tiers(["DETOUR"], feasible, tiers, method="greedy")
    with pytest.raises(ValueError, match="unknown method"):
        relax_by_tiers(["DETOUR", "WORKS"], feasible, tiers, method="best")
    with pytest.raises(ValueError, match="positive integer"):
        Tier(0, "none", frozenset())


# Routes -------------------------------------------------------------------
#
#   a0: 0 -> 1 road       a1: 1 -> 3 bridge, 40 t, class C70
#   a2: 0 -> 2 road       a3: 2 -> 3 underpass, clearance unknown
#   a4: 0 -> 3 road, inside the zone
#
# Every arc is 100 km long at 100 km/h; the roads are capped at 50 km/h:
# one hour on the bridge and the underpass, two on a road.

ROADS = Digraph.from_arcs(4, [(0, 1), (1, 3), (0, 2), (2, 3), (0, 3)])
DATA = ArcData(
    5,
    (
        Attribute.categorical(
            "element", ["road", "bridge", "road", "underpass", "road"], ELEMENTS
        ),
        Attribute.numeric("mass_limit", [None, 40, None, None, None], source=SRC),
        Attribute.numeric("clearance", [None] * 5),
        Attribute.categorical(
            "load_class", [None, "C70", None, None, None], ("C30", "C50", "C70")
        ),
        Attribute.numeric("in_zone", [0, 0, 0, 0, 1]),
        Attribute.numeric("length", [100] * 5, unit="km"),
        Attribute.numeric("speed_limit", [100] * 5, unit="km/h"),
    ),
    element="element",
)


def search(policy: UnknownPolicy, method: str = "dijkstra") -> RouteSearch:
    return RouteSearch(
        requirement_set(),
        ROADS,
        DATA,
        resolved(),
        0,
        3,
        method=method,
        policy=policy,
        criterion="duration",
    )


def test_useful_failure_on_a_route() -> None:
    # A6: the bans cut the target off; the explanation names the
    # requirements, and the relaxations are proposed, never a silent
    # penalty.
    s = search(UnknownPolicy.EXCLUDE)
    assert s.solve().status is Status.INFEASIBLE
    assert s.ids == tuple(r.id for r in ROUTING)
    conflict = minimal_conflict(s.ids, s.feasible, method="deletion_filter")
    assert conflict.requirements == ("ADM-MASS", "ADM-HEIGHT", "ADM-ZONE")
    assert minimal_conflict(s.ids, s.feasible, method="enumeration").requirements == (
        "ADM-MASS",
        "ADM-HEIGHT",
        "ADM-ZONE",
    )
    assert minimal_relaxation(s.ids, s.feasible, method="enumeration").requirements == (
        "ADM-MASS",
    )
    assert minimal_relaxation(s.ids, s.feasible, method="greedy").requirements == (
        "ADM-ZONE",
    )
    route = s.solve(set(s.ids) - {"ADM-ZONE"})
    assert route is not None
    assert route.arcs == (4,)
    # The conflict carries its provenance, which a new search replays.
    p = provenance(
        inputs={"graph": ROADS, "data": DATA},
        requirements=s.requirements,
        values=s.values,
        result=conflict,
    )
    assert (p.method, dict(p.parameters), p.version) == (
        "deletion_filter",
        {},
        conflict.version,
    )
    assert dict(p.counters) == {"feasibility_tests": conflict.evaluations}
    again = search(UnknownPolicy.EXCLUDE)
    replay = provenance(
        inputs={"graph": ROADS, "data": DATA},
        requirements=again.requirements,
        values=again.values,
        result=minimal_conflict(again.ids, again.feasible, method="deletion_filter"),
    )
    assert p == replay
    assert p.replays(replay)


def test_impact_with_and_without() -> None:
    s = search(UnknownPolicy.ADMIT_AND_COUNT)
    zone = s.impact("ADM-ZONE")
    assert zone == Impact("ADM-ZONE", True, True, 3.0, 2.0, 1)
    assert zone.delta == 1.0
    # The speed cap changes the duration: two hours on a road, not one.
    assert s.impact("COST-SPEED") == Impact("COST-SPEED", True, True, 3.0, 2.0, 0)
    blocked = search(UnknownPolicy.EXCLUDE).impact("ADM-HEIGHT")
    assert (blocked.feasible_with, blocked.feasible_without) == (False, True)
    assert blocked.delta is None
    assert blocked.arcs_removed == 1
    view = s.view()
    route = s.solve()
    assert route is not None
    check = s.verify(route)
    assert check["COST-SPEED"].status is S.APPLIED
    rows = requirement_table(
        check, requirement_set(), resolved(), view=view, impacts={"ADM-ZONE": zone}
    )
    row = next(r for r in rows if r.id == "ADM-ZONE")
    assert row.impact is not None
    assert row.impact["delta"] == 1.0
    assert row.to_dict()["impact"]["cost_without"] == 2.0
    assert next(r for r in rows if r.id == "ADM-MASS").impact is None
    with pytest.raises(ValueError, match="unknown requirement 'ADM-NONE'"):
        s.impact("ADM-NONE")


def test_arcs_removed_is_a_difference_with_and_without() -> None:
    # Two identical requirements: removing one gives no arc back.
    twin = requirement(
        "ADM-MASS-2",
        "threshold_admissibility",
        parameters={"quantity": "vehicle_mass"},
        attributes={"limit": "mass_limit"},
        scope=["bridge"],
    )
    s = RouteSearch(
        requirement_set((MASS, twin)),
        ROADS,
        DATA,
        resolved(requirement_set((MASS, twin))),
        0,
        3,
        method="dijkstra",
        policy=UnknownPolicy.ADMIT_AND_COUNT,
        base=(1, 1, 1, 1, 1),
    )
    assert s.view().excluded == (1,)
    assert s.impact("ADM-MASS").arcs_removed == 0
    alone = RouteSearch(
        requirement_set((MASS,)),
        ROADS,
        DATA,
        resolved(requirement_set((MASS,))),
        0,
        3,
        method="dijkstra",
        policy=UnknownPolicy.ADMIT_AND_COUNT,
        base=(1, 1, 1, 1, 1),
    )
    assert alone.impact("ADM-MASS").arcs_removed == 1


def test_lexicographic_search_minimizes_unknowns_first() -> None:
    # A3: two routes, the shorter one through an arc of unknown membership.
    graph = Digraph.from_arcs(4, [(0, 1), (1, 3), (0, 2), (2, 3)])
    data = ArcData(4, (Attribute.numeric("in_zone", [0, None, 0, 0]),))
    zone = requirement("Z", "zone_exclusion", attributes={"inside": "in_zone"})
    reqs = requirement_set((zone,))
    base = (1.0, 1.0, 1.5, 1.5)
    plain = RouteSearch(
        reqs,
        graph,
        data,
        resolved(reqs),
        0,
        3,
        method="dijkstra",
        policy=UnknownPolicy.ADMIT_AND_COUNT,
        base=base,
    )
    lex = RouteSearch(
        reqs,
        graph,
        data,
        resolved(reqs),
        0,
        3,
        method="lexicographic_dijkstra",
        policy=UnknownPolicy.ADMIT_AND_COUNT,
        base=base,
    )
    assert plain.solve().status is Status.OPTIMAL
    assert plain.solve().arcs == (0, 1)
    assert lex.solve().arcs == (2, 3)
    assert lex.solve().cost == 3.0
    assert lex.view().unknown_count == 1
    assert lex.view().lexicographic_weights(base)[1] == (1, 1.0)
    assert lex.weights()[1] == (1, 1.0)
    with pytest.raises(ValueError, match="expected 4 weights"):
        lex.view().lexicographic_weights([1.0])


def test_route_search_checks_its_arguments() -> None:
    assert [i.name for i in RouteSearch.methods()] == [
        "dijkstra",
        "lexicographic_dijkstra",
    ]
    with pytest.raises(ValueError, match="unknown method"):
        search(UnknownPolicy.EXCLUDE, method="astar")
    with pytest.raises(ValueError, match="unknown requirements"):
        search(UnknownPolicy.EXCLUDE).solve(["ADM-NONE"])
    reqs, vals = requirement_set(), resolved()

    def route_search(data: ArcData, **options: object) -> RouteSearch:
        return RouteSearch(
            reqs,
            ROADS,
            data,
            vals,
            0,
            3,
            method="dijkstra",
            policy=UnknownPolicy.EXCLUDE,
            **options,  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="no base weights"):
        route_search(DATA, base=(1, 1, 1, 1, 1))
    bare = ArcData(5, DATA.attributes[:5], element="element")
    with pytest.raises(ValueError, match="need the attribute 'length'"):
        route_search(bare)
    unknown = ArcData(
        5,
        (*DATA.attributes[:6], Attribute.numeric("speed_limit", [100, None, 1, 1, 1])),
        element="element",
    )
    with pytest.raises(ValueError, match="derive the unknown ones"):
        route_search(unknown)
    verdicts = requirement_set((MASS,))
    with pytest.raises(ValueError, match="base weights are required"):
        RouteSearch(
            verdicts,
            ROADS,
            DATA,
            resolved(verdicts),
            0,
            3,
            method="dijkstra",
            policy=UnknownPolicy.EXCLUDE,
        )
    with pytest.raises(ValueError, match="expected 5 base weights"):
        RouteSearch(
            verdicts,
            ROADS,
            DATA,
            resolved(verdicts),
            0,
            3,
            method="dijkstra",
            policy=UnknownPolicy.EXCLUDE,
            base=(1.0,),
        )
    other = requirement(
        "COST-SPEED-2",
        "speed_cap",
        parameters={"maximum": "speed_max"},
        attributes={"length": "length", "speed": "in_zone"},
        scope=["road"],
    )
    both = requirement_set((*ROUTING, other))
    with pytest.raises(ValueError, match="different length and speed"):
        RouteSearch(
            both,
            ROADS,
            DATA,
            resolved(both),
            0,
            3,
            method="dijkstra",
            policy=UnknownPolicy.EXCLUDE,
        )


# The speed cap, applied and verified ---------------------------------------
#
#   a0: 0 -> 1 motorway, 100 km at 130 km/h, capped at 10 km/h
#   a1: 0 -> 1 road, 60 km at 50 km/h

CRITERION = Parameter("route_criterion")
OBJECTIVE = requirement("OBJ", "objective", parameters={"criterion": "route_criterion"})
CAP = requirement(
    "CAP",
    "speed_cap",
    parameters={"maximum": "speed_max"},
    attributes={"length": "length", "speed": "speed_limit"},
    scope=["motorway"],
)


def capped(method: str = "dijkstra") -> RouteSearch:
    reqs = RequirementSet((CAP, OBJECTIVE), (*PARAMETERS, CRITERION), (REG,))
    vs = ValueSet(
        "reg-a",
        "2006",
        {
            **values(speed=10.0).values,
            "route_criterion": value("duration"),
        },
    )
    data = ArcData(
        2,
        (
            Attribute.categorical("kind", ["motorway", "road"], ("motorway", "road")),
            Attribute.numeric("length", [100, 60], unit="km"),
            Attribute.numeric("speed_limit", [130, 50], unit="km/h"),
        ),
        element="kind",
    )
    return RouteSearch(
        reqs,
        Digraph.from_arcs(2, [(0, 1), (0, 1)]),
        data,
        resolve_values([vs], reqs),
        0,
        1,
        method=method,
        policy=UnknownPolicy.ADMIT_AND_COUNT,
        criterion="duration",
    )


def test_speed_cap_changes_the_route_and_its_duration() -> None:
    s = capped()
    route = s.solve()
    assert route is not None
    assert route.arcs == (1,)
    assert route.cost == pytest.approx(1.2)
    impact = s.impact("CAP")
    assert impact.cost_without == pytest.approx(100 / 130)
    assert impact.delta == pytest.approx(1.2 - 100 / 130)
    check = s.verify(route)
    assert check["CAP"].status is S.NOT_APPLICABLE
    assert check["OBJ"].status is S.APPLIED
    assert check["OBJ"].reason == (
        "objective 'duration', prescribed (rulebook); optimal (duration), "
        "checked by Bellman-Ford"
    )


def test_forgetful_route_solver_is_caught() -> None:
    # A1: the route of a solver that ignored the cap, verified with the
    # weights it used, is not applied; with the capped weights, it is not
    # optimal.
    s = capped()
    forgot = s.solve(["OBJ"])
    assert forgot is not None
    assert forgot.arcs == (0,)
    check = s.verify(forgot, ["OBJ"])
    assert check["CAP"].status is S.NOT_APPLIED
    assert check["CAP"].failing == (0,)
    assert check["OBJ"].status is S.APPLIED
    honest = s.verify(forgot)
    assert honest["CAP"].status is S.APPLIED
    assert honest["OBJ"].status is S.NOT_APPLIED
    assert honest["OBJ"].reason == "a route of weight 1.2 exists, this one weighs 10"


def test_objective_needs_the_weights_and_their_criterion() -> None:
    s = capped()
    route = (1,)
    args = (s.requirements, s.graph, s.data, s.values)
    bare = verify_route(route, *args)["OBJ"]
    assert bare.status is S.NOT_APPLIED
    assert bare.reason == (
        "an objective is checked with the view, weights, criterion of the "
        "computation, not given"
    )
    length = verify_route(
        route, *args, view=s.view(), weights=s.weights(), criterion="length"
    )["OBJ"]
    assert length.reason == "the weights measure 'length', not 'duration'"
    empty = verify_route(
        (), *args, view=s.view(), weights=s.weights(), criterion="duration"
    )
    assert empty["OBJ"].status is S.APPLIED
    lex = capped("lexicographic_dijkstra")
    found = lex.solve()
    assert found is not None
    assert "fewest unknown arcs first" in lex.verify(found)["OBJ"].reason
    assert lex.verify((0,))["OBJ"].reason == (
        "a route of weight (0, 1.2) exists, this one weighs (0, 10)"
    )


def test_objective_on_a_route_through_an_excluded_arc() -> None:
    zone = requirement("Z", "zone_exclusion", attributes={"inside": "in_zone"})
    reqs = RequirementSet((zone, OBJECTIVE), (*PARAMETERS, CRITERION), (REG,))
    vs = ValueSet(
        "reg-a", "2006", {**values().values, "route_criterion": value("length")}
    )
    graph = Digraph.from_arcs(2, [(0, 1), (0, 1)])
    data = ArcData(2, (Attribute.numeric("in_zone", [1, 0]),))
    s = RouteSearch(
        reqs,
        graph,
        data,
        resolve_values([vs], reqs),
        0,
        1,
        method="dijkstra",
        policy=UnknownPolicy.EXCLUDE,
        base=(1.0, 5.0),
        criterion="length",
    )
    check = s.verify((0,))["OBJ"]
    assert check.status is S.NOT_APPLIED
    assert check.reason == "the route uses 1 arcs the view excludes"
    negative = verify_route(
        (1,),
        reqs,
        graph,
        data,
        s.values,
        view=s.view(),
        weights=[1.0, -1.0],
        criterion="length",
    )
    assert negative["OBJ"].status is S.APPLIED


def test_objective_under_weights_with_a_negative_cycle() -> None:
    # No route is optimal when the weights admit a cycle of negative weight.
    reqs = RequirementSet((OBJECTIVE,), (*PARAMETERS, CRITERION), (REG,))
    vs = ValueSet(
        "reg-a", "2006", {**values().values, "route_criterion": value("length")}
    )
    vals = resolve_values([vs], reqs)
    graph = Digraph.from_arcs(2, [(0, 1), (1, 0)])
    data = ArcData(2, ())
    s = RouteSearch(
        reqs,
        graph,
        data,
        vals,
        0,
        1,
        method="dijkstra",
        policy=UnknownPolicy.EXCLUDE,
        base=(1.0, 1.0),
        criterion="length",
    )
    for weights in ([-1.0, -1.0], [(0, -1.0), (0, -1.0)]):
        check = verify_route(
            (0,),
            reqs,
            graph,
            data,
            vals,
            view=s.view(),
            weights=weights,
            criterion="length",
        )["OBJ"]
        assert check.status is S.NOT_APPLIED
        assert check.reason == (
            "the weights admit a cycle of negative weight: no route is optimal"
        )


# Life-cycle profiles ------------------------------------------------------


def flow_search(
    *requirements: Requirement, policy: UnknownPolicy = UnknownPolicy.ADMIT_AND_COUNT
) -> FlowSearch:
    reqs, data, vals = profile(*requirements)
    problem = FlowProblem(PROFILE, cost=[1] * 6, sense="max")
    return FlowSearch(
        reqs, problem, data, vals, method="network_simplex", policy=policy
    )


def test_overconstrained_profile_gives_its_conflict() -> None:
    s = flow_search(OC_ALL, OC_L03, MIN_L03, RETURN)
    assert s.problem_for() is None
    assert not s.feasible(s.ids)
    for method in ("enumeration", "deletion_filter"):
        assert minimal_conflict(s.ids, s.feasible, method=method).requirements == (
            "OC-L03",
            "MIN-L03",
        )
    assert minimal_relaxation(s.ids, s.feasible, method="enumeration").requirements == (
        "OC-L03",
    )


def test_conservation_conflict_is_found_by_the_solver() -> None:
    cut = occurrence("CUT-L01", "zero", ["L01"])
    s = flow_search(cut, RETURN)
    assert s.problem_for() is not None
    assert not s.feasible(s.ids)
    assert minimal_conflict(s.ids, s.feasible, method="enumeration").requirements == (
        "CUT-L01",
        "RETURN",
    )
    cut_impact = s.impact("CUT-L01")
    assert (cut_impact.feasible_with, cut_impact.cost_with) == (False, None)
    assert cut_impact.feasible_without


def test_profile_impact_of_a_maximum() -> None:
    s = flow_search(OC_ALL, OC_L03, RETURN)
    impact = s.impact("OC-L03")
    assert (impact.cost_with, impact.cost_without, impact.delta) == (8.0, 11.0, -3.0)
    assert impact.arcs_removed is None
    loose = flow_search(OC_L03, RETURN).impact("OC-L03")
    assert (loose.cost_with, loose.feasible_without, loose.cost_without) == (
        8.0,
        True,
        None,
    )


def test_admissibility_on_profiles_and_policies() -> None:
    zone = requirement("ZONE", "zone_exclusion", attributes={"inside": "in_zone"})
    excluded = flow_search(zone, RETURN, policy=UnknownPolicy.EXCLUDE)
    assert not excluded.feasible(excluded.ids)
    admitted = flow_search(zone, OC_ALL, RETURN)
    assert admitted.feasible(admitted.ids)
    result = admitted.solve()
    assert result is not None
    assert result.flow is not None
    assert result.flow[3] == 0
    with pytest.raises(ValueError, match="excludes or admits"):
        flow_search(zone, policy=UnknownPolicy.PENALIZE)
    reqs, data, vals = profile(RETURN)
    with pytest.raises(ValueError, match="unknown method"):
        FlowSearch(
            reqs,
            FlowProblem(PROFILE),
            data,
            vals,
            method="simplex",
            policy=UnknownPolicy.EXCLUDE,
        )
    with pytest.raises(ValueError, match="unknown requirement 'OC-NONE'"):
        admitted.impact("OC-NONE")


# Tiers on both reference applications, against brute force ----------------


def check_tiers(
    ids: tuple[str, ...],
    feasible: Callable[[frozenset[str]], bool],
    cost: Callable[[frozenset[str]], float | None],
    tiers: list[Tier],
    method: str,
) -> int | None:
    """Run :func:`relax_by_tiers` and check it by brute force; return the
    level."""
    result = relax_by_tiers(ids, feasible, tiers, method=method, cost=cost)
    allowed: set[str] = set()
    first = None
    for t in sorted(tiers, key=lambda t: t.level):
        allowed |= t.relaxable
        if feasible(frozenset(ids) - allowed):
            first = t.level, set(allowed)
            break
    if first is None:
        assert result.level is None
        assert result.status is Status.INFEASIBLE
        # The certificate is tested again.
        certificate = result.certificate
        assert isinstance(certificate, InfeasibleSubset)
        assert not feasible(frozenset(certificate.requirements))
        return None
    level, permitted = first
    assert result.level == level
    exact = method == "enumeration"
    assert result.status is (Status.OPTIMAL if exact else Status.FEASIBLE)
    relaxed = set(result.relaxed)
    assert relaxed <= permitted
    kept = frozenset(ids) - relaxed
    assert feasible(kept)
    assert result.cost == cost(kept)
    if method == "enumeration":
        fewest = min(
            k
            for k in range(len(permitted) + 1)
            for sub in itertools.combinations(sorted(permitted), k)
            if feasible(frozenset(ids) - set(sub))
        )
        assert len(relaxed) == fewest
    else:
        for r in relaxed:
            assert not feasible(kept | {r})
    return level


@pytest.mark.parametrize("method", ["enumeration", "greedy"])
def test_tiers_on_a_route_with_their_cost(method: str) -> None:
    s = search(UnknownPolicy.EXCLUDE)
    tiers = [
        Tier(1, "unknown clearance accepted", frozenset({"ADM-HEIGHT"})),
        Tier(2, "works on a structure", frozenset({"ADM-MASS", "ADM-CLASS"})),
        Tier(3, "crossing of the zone", frozenset({"ADM-ZONE"})),
    ]
    assert check_tiers(s.ids, s.feasible, s.cost, tiers, method) == 1
    result = relax_by_tiers(s.ids, s.feasible, tiers, method=method, cost=s.cost)
    assert result.relaxed == ("ADM-HEIGHT",)
    assert result.cost == 3.0
    late = [Tier(1, "zone", frozenset({"ADM-ZONE"}))]
    assert check_tiers(s.ids, s.feasible, s.cost, late, method) == 1
    nothing = [Tier(1, "class", frozenset({"ADM-CLASS"}))]
    assert check_tiers(s.ids, s.feasible, s.cost, nothing, method) is None


@pytest.mark.parametrize("method", ["enumeration", "greedy"])
def test_tiers_on_a_profile_with_their_cost(method: str) -> None:
    s = flow_search(OC_ALL, OC_L03, MIN_L03, RETURN)
    tiers = [
        Tier(1, "client minimum", frozenset({"MIN-L03"})),
        Tier(2, "client maximum", frozenset({"OC-L03"})),
    ]
    assert check_tiers(s.ids, s.feasible, s.cost, tiers, method) == 1
    result = relax_by_tiers(s.ids, s.feasible, tiers, method=method, cost=s.cost)
    assert (result.relaxed, result.cost) == (("MIN-L03",), 8.0)
    relaxation = minimal_relaxation(s.ids, s.feasible, method=method, cost=s.cost)
    assert relaxation.cost == s.cost(frozenset(s.ids) - set(relaxation.requirements))


def test_flow_search_verifies_its_objective() -> None:
    objective = requirement(
        "OBJ", "objective", parameters={"criterion": "route_criterion"}
    )
    reqs = RequirementSet(
        (OC_ALL, OC_L03, RETURN, objective),
        (*PARAMETERS, *OCC_PARAMETERS, CRITERION),
        (REG, CLIENT),
    )
    spec = ValueSet(
        "client",
        "1",
        {
            "occ_all": Value(4, CLIENT_SRC, Origin.STATEMENT),
            "occ_l03": Value(2, CLIENT_SRC, Origin.STATEMENT),
            "one": Value(1, CLIENT_SRC, Origin.STATEMENT),
        },
    )
    criterion = ValueSet("reg-a", "2006", {"route_criterion": value("occurrences")})
    _, data, _ = profile()
    vals = resolve_values([spec, criterion], reqs)

    def flows(cost: list[float], name: str | None) -> FlowSearch:
        problem = FlowProblem(PROFILE, cost=cost, sense="max")
        return FlowSearch(
            reqs,
            problem,
            data,
            vals,
            method="network_simplex",
            policy=UnknownPolicy.EXCLUDE,
            criterion=name,
        )

    s = flows([1] * 6, "occurrences")
    result = s.solve()
    assert result is not None
    assert s.cost(s.ids) == 8.0
    assert s.verify(result)["OBJ"].status is S.APPLIED
    # The least feasible flow, L01 -> L04 -> L06: an improving cycle exists.
    least = [1, 0, 0, 1, 0, 1]
    check = s.verify(least)["OBJ"]
    assert check.status is S.NOT_APPLIED
    assert check.reason.startswith("an improving cycle of ")
    assert s.verify([0] * 6)["OBJ"].reason == "the flow is not feasible"
    assert flows([1] * 6, None).verify(result)["OBJ"].status is S.NOT_APPLIED
    assert flows([1] * 6, "cost").verify(result)["OBJ"].reason == (
        "the costs measure 'cost', not 'occurrences'"
    )
    floats = flows([1.5] * 6, "occurrences")
    best = floats.solve()
    assert best is not None
    assert floats.verify(best)["OBJ"].status is S.APPLIED
    assert floats.verify(least)["OBJ"].status is S.NOT_APPLIED
    conflicting = flow_search(OC_ALL, OC_L03, MIN_L03, RETURN)
    with pytest.raises(ValueError, match="bounds of the active requirements conflict"):
        conflicting.verify([0] * 6)
    direct = verify_flow(
        result, reqs, s.problem_for() or s.problem, data, vals, criterion="occurrences"
    )
    assert direct["OBJ"].status is S.APPLIED
    assert math.isfinite(s.cost(s.ids) or math.inf)
    unbounded = flow_search(RETURN)
    assert unbounded.cost(unbounded.ids) is None
    assert solve(unbounded.problem, method="network_simplex").objective is None
