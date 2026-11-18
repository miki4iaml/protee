# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Verification, input checks and the requirement table, end to end on
both reference applications: route planning and life-cycle profiles."""

import json
import math
import random

import pytest
from constraints_cases import (
    ELEMENTS,
    MASS,
    PARAMETERS,
    REG,
    ROUTING,
    SPEED,
    SRC,
    VERDICT_REQUIREMENTS,
    ZONE,
    best_admissible,
    oracle_verdict,
    random_case,
    requirement,
    requirement_set,
    resolved,
    value,
    values,
)
from oracles import brute_force

from protee.constraints import (
    ArcData,
    Attribute,
    ComputationView,
    Effect,
    Origin,
    Parameter,
    Requirement,
    RequirementSet,
    RequirementStatus,
    ResolvedValues,
    Rulebook,
    RulebookKind,
    Source,
    UnknownPolicy,
    Value,
    ValueSet,
    check_inputs,
    compose,
    evaluate,
    requirement_table,
    resolve_values,
    verify_flow,
    verify_route,
)
from protee.flow import FlowProblem, methods, solve
from protee.graph import Digraph
from protee.paths import dijkstra
from protee.routes import Route

S = RequirementStatus

# Route planning ----------------------------------------------------------
#
#   a0: 0 -> 1 road       a1: 1 -> 3 bridge, 40 t, class C70
#   a2: 0 -> 2 road       a3: 2 -> 3 underpass, clearance unknown
#   a4: 0 -> 3 road, inside the zone

ROADS = Digraph.from_arcs(4, [(0, 1), (1, 3), (0, 2), (2, 3), (0, 3)])


def roads_data(clearance: float | None = None) -> ArcData:
    return ArcData(
        5,
        (
            Attribute.categorical(
                "element", ["road", "bridge", "road", "underpass", "road"], ELEMENTS
            ),
            Attribute.numeric(
                "mass_limit", [None, 40, None, None, None], unit="t", source=SRC
            ),
            Attribute.numeric(
                "clearance",
                [None, None, None, clearance, None],
                unit="m",
                derived=True,
                quality="estimated from imagery",
            ),
            Attribute.categorical(
                "load_class", [None, "C70", None, None, None], ("C30", "C50", "C70")
            ),
            Attribute.numeric("in_zone", [0, 0, 0, 0, 1]),
        ),
        element="element",
    )


def routing_view(
    policy: UnknownPolicy, penalty: float | None = None
) -> ComputationView:
    data, vals = roads_data(), resolved()
    effects = [evaluate(r, ROADS, data, vals) for r in ROUTING]
    return compose(ROADS, effects, unknown=policy, penalty=penalty)


def test_exclude_policy_leaves_no_route() -> None:
    # A6: a ban stays a ban; with unknowns excluded, the target is cut off,
    # and no penalty replaces the ban silently.
    view = routing_view(UnknownPolicy.EXCLUDE)
    assert view.excluded == (1, 3, 4)
    sp = dijkstra(ROADS, view.weights([1] * 5), 0, 3, excluded=view.excluded)
    assert sp.distance[3] == math.inf
    assert view.requirements_on(4) == ("ADM-ZONE", "COST-SPEED")
    assert view.requirements_on(1) == ("ADM-MASS",)


def test_admitted_unknown_is_counted_on_the_route() -> None:
    # A3: the unknown is admitted and counted, never presumed compatible.
    view = routing_view(UnknownPolicy.ADMIT_AND_COUNT)
    sp = dijkstra(ROADS, view.weights([1] * 5), 0, 3, excluded=view.excluded)
    route = sp.path(3)
    assert route == (2, 3)
    check = verify_route(
        route, requirement_set(), ROADS, roads_data(), resolved(), view=view
    )
    assert check.statuses == {
        "ADM-MASS": S.NOT_APPLICABLE,
        "ADM-HEIGHT": S.PARTIAL,
        "ADM-CLASS": S.NOT_APPLICABLE,
        "ADM-ZONE": S.APPLIED,
        "COST-SPEED": S.APPLIED,
    }
    assert check["ADM-HEIGHT"].unknown == 1
    assert check["ADM-HEIGHT"].unknown_arcs == (3,)
    assert check["ADM-ZONE"].passed == 2
    assert check.violations == ()


def test_forgetful_solver_is_caught_by_verification() -> None:
    # A1: the status comes from verification, whatever the solver says.
    data, vals = roads_data(), resolved()
    forgot = Route(arcs=(0, 1), cost=2)
    without_speed = compose(
        ROADS,
        [evaluate(r, ROADS, data, vals) for r in VERDICT_REQUIREMENTS],
        unknown=UnknownPolicy.ADMIT_AND_COUNT,
    )
    check = verify_route(
        forgot, requirement_set(), ROADS, data, vals, view=without_speed
    )
    assert check["ADM-MASS"].status is S.NOT_APPLIED
    assert check["ADM-MASS"].failing == (1,)
    assert check["ADM-MASS"].reason == "1 arcs violate it"
    assert check["ADM-CLASS"].status is S.APPLIED
    assert check["ADM-HEIGHT"].status is S.NOT_APPLICABLE
    assert check["COST-SPEED"].status is S.NOT_APPLIED
    assert check["COST-SPEED"].failing == (0,)
    blind = verify_route(forgot, requirement_set(), ROADS, data, vals)
    assert blind["COST-SPEED"].status is S.NOT_APPLIED
    assert "not given" in blind["COST-SPEED"].reason


def test_penalty_prefers_known_arcs_at_equal_length() -> None:
    # A3: two parallel arcs of equal length, one of unknown membership.
    graph = Digraph.from_arcs(2, [(0, 1), (0, 1)])
    data = ArcData(2, (Attribute.numeric("in_zone", [None, 0]),))
    vals = resolved()
    effects = [evaluate(ZONE, graph, data, vals)]
    view = compose(graph, effects, unknown=UnknownPolicy.PENALIZE, penalty=0.5)
    sp = dijkstra(graph, view.weights([3, 3]), 0, 1, excluded=view.excluded)
    assert sp.path(1) == (1,)
    assert sp.distance[1] == 3


def test_verify_route_statuses_without_data_or_values() -> None:
    reqs = requirement_set()
    assert (
        verify_route((2, 3), reqs, ROADS, roads_data(), resolved(mass=None))[
            "ADM-MASS"
        ].status
        is S.NOT_APPLICABLE
    )
    bare = ArcData(
        5,
        (
            Attribute.categorical(
                "element", ["road", "bridge", "road", "underpass", "road"], ELEMENTS
            ),
        ),
        element="element",
    )
    check = verify_route((0, 1), reqs, ROADS, bare, resolved())
    assert check["ADM-MASS"].status is S.NO_DATA
    assert check["ADM-MASS"].reason == "attribute 'mass_limit' absent from the data"
    known = verify_route((2, 3), reqs, ROADS, roads_data(clearance=4.5), resolved())
    assert known["ADM-HEIGHT"].status is S.APPLIED
    assert known["ADM-HEIGHT"].reason == "verified on 1 arcs"
    assert len(known) == 5
    assert next(iter(known)).requirement == "ADM-MASS"


def test_verify_route_checks_the_route() -> None:
    reqs = requirement_set()
    with pytest.raises(ValueError, match="not consecutive"):
        verify_route((0, 3), reqs, ROADS, roads_data(), resolved())
    with pytest.raises(ValueError, match="out of range"):
        verify_route((9,), reqs, ROADS, roads_data(), resolved())


def test_flow_bounds_do_not_apply_to_routes() -> None:
    occ = requirement(
        "OC", "occurrence_bounds", parameters={"maximum": "occurrence_max"}
    )
    reqs = RequirementSet((occ,), PARAMETERS, (REG,))
    vals = resolve_values([ValueSet("reg-a", "1", {"occurrence_max": value(2)})], reqs)
    check = verify_route((0,), reqs, ROADS, roads_data(), vals)
    assert check["OC"].status is S.NOT_APPLICABLE


def test_speed_cap_out_of_scope_on_the_route() -> None:
    view = routing_view(UnknownPolicy.ADMIT_AND_COUNT)
    reqs = requirement_set((SPEED,))
    check = verify_route((3,), reqs, ROADS, roads_data(), resolved(), view=view)
    assert check["COST-SPEED"].status is S.NOT_APPLICABLE


@pytest.mark.parametrize("seed", range(15))
@pytest.mark.parametrize(
    "policy", [UnknownPolicy.EXCLUDE, UnknownPolicy.ADMIT_AND_COUNT]
)
def test_routes_match_enumeration_and_verify(seed: int, policy: UnknownPolicy) -> None:
    case = random_case(seed)
    data, vals, reqs = case.data(), resolved(), requirement_set()
    view = compose(
        case.graph,
        [evaluate(r, case.graph, data, vals) for r in ROUTING],
        unknown=policy,
    )
    rng = random.Random(seed)
    s, t = rng.sample(range(case.graph.n), 2)
    verdicts = [oracle_verdict(case, a) for a in range(case.graph.m)]
    lowest = 2 if policy is UnknownPolicy.EXCLUDE else 1
    admissible = [v >= lowest for v in verdicts]
    expected = best_admissible(case, s, t, admissible, case.length)
    sp = dijkstra(case.graph, view.weights(case.length), s, t, excluded=view.excluded)
    assert sp.distance[t] == expected
    if math.isinf(expected):
        return
    route = sp.path(t)
    assert route is not None
    check = verify_route(route, reqs, case.graph, data, vals, view=view)
    for c in check:
        assert c.status is not S.NOT_APPLIED
        assert c.failed == 0
    unknown_on_route = sum(verdicts[a] == 1 for a in set(route))
    if policy is UnknownPolicy.EXCLUDE:
        assert unknown_on_route == 0
        assert all(c.status is not S.PARTIAL for c in check)
    else:
        assert max((c.unknown for c in check), default=0) <= unknown_on_route


# Input checks -------------------------------------------------------------


def test_check_inputs_says_what_can_be_proved() -> None:
    # A4: coverage by element type, provability against the threshold,
    # derived attributes, and the expected status.
    width = requirement(
        "ADM-WIDTH",
        "threshold_admissibility",
        parameters={"quantity": "unused_width"},
        attributes={"limit": "width_limit"},
    )
    tunnel = requirement(
        "ADM-TUNNEL",
        "zone_exclusion",
        attributes={"inside": "in_zone"},
        scope=["tunnel"],
    )
    reqs = requirement_set((*ROUTING, width, tunnel))
    extra = ValueSet("reg-a", "2006", {"unused_width": value(2.5, "m")})
    vals = resolve_values([values(), extra], reqs)
    report = check_inputs(reqs, ROADS, roads_data(), vals)
    assert len(report) == 7
    mass = report["ADM-MASS"]
    assert mass.expected is S.APPLIED
    assert (mass.known, mass.total) == (1, 1)
    assert mass.coverage == {"bridge": (1, 1)}
    assert mass.provable is False
    assert "cannot be proved on any arc" in mass.reason
    height = report["ADM-HEIGHT"]
    assert height.expected is S.NO_DATA
    assert height.provable is None
    assert height.derived == {"clearance": "estimated from imagery"}
    assert report["ADM-CLASS"].provable is True
    assert report["ADM-ZONE"].coverage == {
        "bridge": (1, 1),
        "road": (3, 3),
        "underpass": (1, 1),
    }
    assert report["COST-SPEED"].expected is S.APPLIED
    assert report["COST-SPEED"].reason == "3 arcs in the scope, no data needed"
    assert report["ADM-WIDTH"].expected is S.NO_DATA
    assert report["ADM-WIDTH"].missing_attributes == ("width_limit",)
    assert report["ADM-TUNNEL"].expected is S.NOT_APPLICABLE
    assert [c.requirement for c in report][-1] == "ADM-TUNNEL"
    to_set = check_inputs(reqs, ROADS, roads_data(), resolved(reqs, mass=None))
    assert to_set["ADM-MASS"].expected is S.NOT_APPLICABLE
    assert to_set["ADM-MASS"].missing_values == ("vehicle_mass",)


def test_check_inputs_partial_coverage() -> None:
    case = random_case(5, unknown=0.5)
    report = check_inputs(requirement_set(), case.graph, case.data(), resolved())
    for c in report:
        if c.expected is S.PARTIAL:
            assert 0 < c.known < c.total
            assert sum(k for k, _ in c.coverage.values()) == c.known
            assert sum(t for _, t in c.coverage.values()) == c.total
    assert any(c.expected is S.PARTIAL for c in report)
    assert None in report["ADM-ZONE"].coverage


# Requirement table ---------------------------------------------------------


def test_table_is_generated_and_follows_the_values() -> None:
    # A9: the table follows a change of value without any change of text.
    view = routing_view(UnknownPolicy.ADMIT_AND_COUNT)
    reqs = requirement_set()
    for mass, status in ((40.0, S.APPLIED), (44.0, S.NOT_APPLIED)):
        vals = resolved(mass=mass)
        check = verify_route((0, 1), reqs, ROADS, roads_data(), vals, view=view)
        rows = requirement_table(check, reqs, vals, view=view)
        row = next(r for r in rows if r.id == "ADM-MASS")
        assert row.status is status
        assert row.values["vehicle_mass"].value == mass
        assert row.policy is UnknownPolicy.ADMIT_AND_COUNT
    data = [r.to_dict() for r in rows]
    text = json.dumps(data)
    assert '"status": "not_applied"' in text
    assert data[0]["family"] == "admissibility"
    assert data[0]["value"][0]["parameter"] == "vehicle_mass"
    assert data[0]["verification"] == {"pass": 0, "fail": 1, "unknown": 0}
    assert data[0]["unknowns"] == {"count": 0, "policy": "admit_and_count"}
    assert data[0]["impact"] is None


def test_table_keeps_discarded_values_and_infinity() -> None:
    reqs = requirement_set()
    doctrine = ValueSet(
        "doc-b",
        "2019",
        {
            "vehicle_mass": Value(60.0, SRC, Origin.RULEBOOK, unit="t", precedence=1),
            "speed_max": Value(math.inf, SRC, Origin.CHOICE, unit="km/h", precedence=1),
        },
    )
    vals = resolve_values([values(), doctrine], reqs)
    check = verify_route((0, 1), reqs, ROADS, roads_data(), vals)
    rows = {r.id: r for r in requirement_table(check, reqs, vals)}
    mass = rows["ADM-MASS"].to_dict()["value"][0]
    assert mass["value"] == 60.0
    assert [d["value"] for d in mass["discarded"]] == [44.0]
    assert rows["COST-SPEED"].to_dict()["value"][0]["value"] == "inf"
    assert rows["ADM-MASS"].policy is None
    assert rows["ADM-MASS"].to_dict()["unknowns"]["policy"] is None


# Life-cycle profiles --------------------------------------------------------
#
#   a0 L01: 0 -> 1   a1 L02: 1 -> 2   a2 L03: 2 -> 1 (loop)
#   a3 L04: 1 -> 3   a4 L05: 2 -> 3   a5 L06: 3 -> 0 (return, 1..1)

PROFILE = Digraph.from_arcs(4, [(0, 1), (1, 2), (2, 1), (1, 3), (2, 3), (3, 0)])
LINKS = ("L01", "L02", "L03", "L04", "L05", "L06")
CLIENT = Rulebook(
    "client", RulebookKind.CLIENT_SPECIFICATION, {"en": "Client specification"}, "1"
)
CLIENT_SRC = Source("Specification of use", rulebook="client", edition="1")
OCC_PARAMETERS = (
    Parameter("occ_all"),
    Parameter("occ_l03"),
    Parameter("occ_l02"),
    Parameter("one"),
    Parameter("three"),
)


def occurrence(
    id: str, maximum: str, scope: list[str] | None, minimum: str | None = None
) -> Requirement:
    params = {"maximum": maximum} | ({} if minimum is None else {"minimum": minimum})
    return requirement(id, "occurrence_bounds", parameters=params, scope=scope)


OC_ALL = occurrence("OC-ALL", "occ_all", None)
OC_L03 = occurrence("OC-L03", "occ_l03", ["L03"])
RETURN = occurrence("RETURN", "one", ["L06"], minimum="one")
OC_INF = occurrence("OC-L02", "occ_l02", ["L02"])
MIN_L03 = occurrence("MIN-L03", "three", ["L03"], minimum="three")


def profile(
    *requirements: Requirement,
) -> tuple[RequirementSet, ArcData, ResolvedValues]:
    reqs = RequirementSet(requirements, (*PARAMETERS, *OCC_PARAMETERS), (REG, CLIENT))
    spec = ValueSet(
        "client",
        "1",
        {
            "occ_all": Value(4, CLIENT_SRC, Origin.STATEMENT),
            "occ_l03": Value(2, CLIENT_SRC, Origin.STATEMENT),
            "occ_l02": Value(math.inf, CLIENT_SRC, Origin.STATEMENT),
            "one": Value(1, CLIENT_SRC, Origin.STATEMENT),
            "three": Value(3, CLIENT_SRC, Origin.STATEMENT),
        },
    )
    data = ArcData(
        6,
        (
            Attribute.categorical("link", list(LINKS), LINKS),
            Attribute.numeric("in_zone", [0, 0, 0, 1, None, 0]),
        ),
        element="link",
    )
    return reqs, data, resolve_values([spec], reqs)


def bounded(reqs: RequirementSet, data: ArcData, vals: ResolvedValues) -> FlowProblem:
    view = compose(
        PROFILE, [evaluate(r, PROFILE, data, vals) for r in reqs], unknown="exclude"
    )
    lower, upper = view.flow_bounds()
    return FlowProblem(PROFILE, lower=lower, upper=upper, cost=[1] * 6, sense="max")


@pytest.mark.parametrize("method", [info.name for info in methods()])
def test_profile_bounds_come_from_sourced_requirements(method: str) -> None:
    reqs, data, vals = profile(OC_ALL, OC_L03, RETURN, OC_INF)
    problem = bounded(reqs, data, vals)
    assert problem.upper == (4, 4, 2, 4, 4, 1)
    assert problem.lower == (0, 0, 0, 0, 0, 1)
    result = solve(problem, method=method)
    assert brute_force(problem) == ("optimal", 8)
    assert result.objective == 8
    check = verify_flow(result, problem, reqs, data, vals)
    assert check.violations == ()
    assert set(check.statuses.values()) == {S.APPLIED}
    assert check["OC-L03"].passed == 1
    assert check["OC-ALL"].passed == 6


def test_forgotten_bound_is_caught_on_the_flow() -> None:
    # A1 on flows: the solver dropped OC-L03; verification still sees it.
    reqs, data, vals = profile(OC_ALL, OC_L03, RETURN)
    forgetful = bounded(*profile(OC_ALL, RETURN))
    result = solve(forgetful, method="network_simplex")
    assert result.objective == 11
    check = verify_flow(result, forgetful, reqs, data, vals)
    assert check.violations == ()
    assert check["OC-L03"].status is S.NOT_APPLIED
    assert check["OC-L03"].failing == (2,)
    assert check["OC-ALL"].status is S.APPLIED


def test_overconstrained_profile_shows_conflicting_bounds() -> None:
    reqs, data, vals = profile(OC_ALL, OC_L03, MIN_L03)
    view = compose(
        PROFILE, [evaluate(r, PROFILE, data, vals) for r in reqs], unknown="exclude"
    )
    assert view.bound_conflicts == (2,)
    assert view.requirements_on(2) == ("MIN-L03", "OC-ALL", "OC-L03")


def test_admissibility_on_flows_and_problem_violations() -> None:
    zone = requirement("ZONE", "zone_exclusion", attributes={"inside": "in_zone"})
    reqs, data, vals = profile(zone, RETURN)
    problem = FlowProblem(PROFILE, lower=[0, 0, 0, 0, 0, 1], upper=[4, 4, 2, 4, 4, 1])
    through_l05 = [1, 3, 2, 0, 1, 1]
    through_l04 = [1, 2, 2, 1, 0, 1]
    assert (
        verify_flow(through_l05, problem, reqs, data, vals)["ZONE"].status is S.PARTIAL
    )
    check = verify_flow(through_l04, problem, reqs, data, vals)
    assert check["ZONE"].status is S.NOT_APPLIED
    assert check["ZONE"].failing == (3,)
    broken = verify_flow([0, 0, 0, 0, 0, 0], problem, reqs, data, vals)
    assert broken.violations == ("arc 5: flow 0 outside [1, 1]",)
    assert broken["RETURN"].status is S.NOT_APPLIED
    idle = verify_flow(
        [0] * 6, problem, requirement_set((ZONE,)), roads_like(), resolved()
    )
    assert idle["ADM-ZONE"].status is S.NOT_APPLICABLE


def roads_like() -> ArcData:
    return ArcData(6, (Attribute.numeric("in_zone", [0] * 6),))


def test_cost_terms_and_values_to_be_set_on_flows() -> None:
    reqs = requirement_set((SPEED, MASS))
    problem = FlowProblem(PROFILE)
    check = verify_flow([0] * 6, problem, reqs, roads_like(), resolved(mass=None))
    assert check["COST-SPEED"].status is S.NOT_APPLICABLE
    assert check["COST-SPEED"].reason == "cost terms are checked on routes"
    assert check["ADM-MASS"].status is S.NOT_APPLICABLE


def test_occurrence_out_of_scope_and_flow_errors() -> None:
    reqs, data, vals = profile(occurrence("OC-L99", "one", ["L99"]))
    problem = FlowProblem(PROFILE)
    assert (
        verify_flow([0] * 6, problem, reqs, data, vals)["OC-L99"].status
        is S.NOT_APPLICABLE
    )
    with pytest.raises(ValueError, match="expected 6 arc flows"):
        verify_flow([0], problem, reqs, data, vals)
    stuck = FlowProblem(Digraph.from_arcs(2, [(0, 1)]), lower=[1], upper=[1])
    result = solve(stuck, method="network_simplex")
    with pytest.raises(ValueError, match="has no flow"):
        verify_flow(result, stuck, reqs, ArcData(1, ()), vals)


def test_effects_of_every_profile_requirement_are_bounds() -> None:
    reqs, data, vals = profile(OC_ALL, OC_L03, RETURN)
    for r in reqs:
        e = evaluate(r, PROFILE, data, vals)
        assert isinstance(e, Effect)
        assert e.lower is not None
