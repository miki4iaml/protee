# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Verification, input checks and the requirement table, end to end on
both reference applications: route planning and life-cycle profiles."""

from __future__ import annotations

import json
import math

import pytest
from constraints_cases import (
    DOC_SRC,
    ELEMENTS,
    MASS,
    MIN_L03,
    OC_ALL,
    OC_INF,
    OC_L03,
    PARAMETERS,
    PROFILE,
    REG,
    RETURN,
    ROUTING,
    SPEED,
    SRC,
    VERDICT_REQUIREMENTS,
    ZONE,
    best_admissible,
    endpoints,
    fording,
    occurrence,
    oracle_verdict,
    profile,
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
    RequirementSet,
    RequirementStatus,
    ResolvedValues,
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
from protee.routes import Route, most_reliable_path, waypoint_route

S = RequirementStatus

# Route planning ----------------------------------------------------------
#
#   a0: 0 -> 1 road       a1: 1 -> 3 bridge, 40 t, class C70
#   a2: 0 -> 2 road       a3: 2 -> 3 underpass, clearance unknown
#   a4: 0 -> 3 road, inside the zone
#
# Every arc is 100 km long at 100 km/h; the roads are capped at 50 km/h.

ROADS = Digraph.from_arcs(4, [(0, 1), (1, 3), (0, 2), (2, 3), (0, 3)])
LENGTH = [100.0] * 5
SPEEDS = [100.0] * 5
#: The labels declare a tunnel, which no arc is.
LABELS = (*ELEMENTS, "tunnel")


def roads_data(clearance: float | None = None) -> ArcData:
    return ArcData(
        5,
        (
            Attribute.categorical(
                "element", ["road", "bridge", "road", "underpass", "road"], LABELS
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
            Attribute.numeric("length", LENGTH, unit="km"),
            Attribute.numeric("speed_limit", SPEEDS, unit="km/h"),
        ),
        element="element",
    )


def routing_view(
    policy: UnknownPolicy, penalty: float | None = None
) -> ComputationView:
    data, vals = roads_data(), resolved()
    effects = [evaluate(r, ROADS, data, vals) for r in ROUTING]
    return compose(ROADS, effects, policy=policy, penalty=penalty)


def test_exclude_policy_leaves_no_route() -> None:
    # A6: a ban stays a ban; with unknowns excluded, the target is cut off,
    # and no penalty replaces the ban silently.
    view = routing_view(UnknownPolicy.EXCLUDE)
    assert view.excluded == (1, 3, 4)
    sp = dijkstra(ROADS, view.times(LENGTH, SPEEDS), 0, 3, excluded=view.excluded)
    assert sp.distance[3] == math.inf
    assert view.requirements_on(4) == ("ADM-ZONE", "COST-SPEED")
    assert view.requirements_on(1) == ("ADM-MASS",)


def test_admitted_unknown_is_counted_on_the_route() -> None:
    # A3: the unknown is admitted and counted, never presumed compatible.
    view = routing_view(UnknownPolicy.ADMIT_AND_COUNT)
    times = view.times(LENGTH, SPEEDS)
    assert times == (2.0, 1.0, 2.0, 1.0, 2.0)
    sp = dijkstra(ROADS, times, 0, 3, excluded=view.excluded)
    route = sp.path(3)
    assert route == (2, 3)
    check = verify_route(
        route, requirement_set(), ROADS, roads_data(), resolved(), weights=times
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
    assert check["COST-SPEED"].reason == "capped on 1 arcs"
    assert check.violations == ()


def test_plain_weights_refuse_a_capped_view() -> None:
    view = routing_view(UnknownPolicy.ADMIT_AND_COUNT)
    assert view.capped == (0, 2, 4)
    with pytest.raises(ValueError, match="use times"):
        view.weights([1.0] * 5)
    with pytest.raises(ValueError, match="2 unknown lengths or speeds"):
        view.times([None, 1, 1, 1, None], SPEEDS)  # type: ignore[list-item]
    with pytest.raises(ValueError, match="non-negative"):
        view.times([-1.0] * 5, SPEEDS)
    with pytest.raises(ValueError, match="positive and finite"):
        view.times(LENGTH, [0.0] * 5)
    with pytest.raises(ValueError, match="expected 5 speeds"):
        view.times(LENGTH, [1.0])


def test_forgetful_solver_is_caught_by_verification() -> None:
    # A1: the status comes from verification, whatever the solver says.
    data, vals = roads_data(), resolved()
    forgot = Route(arcs=(0, 1), cost=2)
    without_speed = compose(
        ROADS,
        [evaluate(r, ROADS, data, vals) for r in VERDICT_REQUIREMENTS],
        policy=UnknownPolicy.ADMIT_AND_COUNT,
    )
    # The solver timed the roads at their own speed, not at the cap.
    uncapped = without_speed.times(LENGTH, SPEEDS)
    check = verify_route(forgot, requirement_set(), ROADS, data, vals, weights=uncapped)
    assert check["ADM-MASS"].status is S.NOT_APPLIED
    assert check["ADM-MASS"].failing == (1,)
    assert check["ADM-MASS"].reason == "1 arcs violate it"
    assert check["ADM-CLASS"].status is S.APPLIED
    assert check["ADM-HEIGHT"].status is S.NOT_APPLICABLE
    assert check["COST-SPEED"].status is S.NOT_APPLIED
    assert check["COST-SPEED"].failing == (0,)
    assert check["COST-SPEED"].reason == "1 arcs timed faster than the cap allows"
    blind = verify_route(forgot, requirement_set(), ROADS, data, vals)
    assert blind["COST-SPEED"].status is S.NOT_APPLIED
    assert "not given" in blind["COST-SPEED"].reason
    capped = routing_view(UnknownPolicy.ADMIT_AND_COUNT).times(LENGTH, SPEEDS)
    honest = verify_route(forgot, requirement_set(), ROADS, data, vals, weights=capped)
    assert honest["COST-SPEED"].status is S.APPLIED


def test_speed_cap_without_length() -> None:
    reqs = requirement_set((SPEED,))
    data = ArcData(
        5,
        (
            Attribute.categorical("element", ["road"] * 5, ELEMENTS),
            Attribute.numeric("length", [None, 1, 1, 1, 1]),
            Attribute.numeric("speed_limit", [1] * 5),
        ),
        element="element",
    )
    check = verify_route((0, 1), reqs, ROADS, data, resolved(), weights=[9.0] * 5)
    assert check["COST-SPEED"].status is S.PARTIAL
    assert check["COST-SPEED"].unknown_arcs == (0,)
    assert check["COST-SPEED"].passed == 1
    bare = ArcData(5, (Attribute.categorical("element", ["road"] * 5, ELEMENTS),))
    absent = verify_route((0, 1), reqs, ROADS, bare, resolved(), weights=[9.0] * 5)
    assert absent["COST-SPEED"].status is S.NO_DATA


def test_penalty_prefers_known_arcs_at_equal_length() -> None:
    # A3: two parallel arcs of equal length, one of unknown membership.
    graph = Digraph.from_arcs(2, [(0, 1), (0, 1)])
    data = ArcData(2, (Attribute.numeric("in_zone", [None, 0]),))
    vals = resolved()
    effects = [evaluate(ZONE, graph, data, vals)]
    view = compose(graph, effects, policy=UnknownPolicy.PENALIZE, penalty=0.5)
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


def test_verify_route_checks_the_route_and_the_weights() -> None:
    reqs = requirement_set()
    with pytest.raises(ValueError, match="not consecutive"):
        verify_route((0, 3), reqs, ROADS, roads_data(), resolved())
    with pytest.raises(ValueError, match="out of range"):
        verify_route((9,), reqs, ROADS, roads_data(), resolved())
    with pytest.raises(ValueError, match="expected 5 weights"):
        verify_route((0,), reqs, ROADS, roads_data(), resolved(), weights=[1.0])
    with pytest.raises(ValueError, match="mix numbers"):
        verify_route(
            (0,),
            reqs,
            ROADS,
            roads_data(),
            resolved(),
            weights=[1.0, (0, 1.0), 1.0, 1.0, 1.0],  # type: ignore[arg-type]
        )


def test_verify_route_accepts_route_results() -> None:
    # The route through the underpass, as a waypoint route and as the most
    # reliable path: the same checks as for its arcs.
    reqs, data, vals = requirement_set(), roads_data(), resolved()
    expected = verify_route((2, 3), reqs, ROADS, data, vals).statuses
    through = waypoint_route(ROADS, [1.0] * 5, 0, 3, [2], order="fixed")
    assert verify_route(through, reqs, ROADS, data, vals).statuses == expected
    reliable = most_reliable_path(ROADS, [0.5, 0.5, 0.9, 0.9, 0.1], 0, 3)
    assert reliable.arcs == (2, 3)
    assert verify_route(reliable, reqs, ROADS, data, vals).statuses == expected
    cut_off = waypoint_route(ROADS, [1.0] * 5, 3, 0, [], order="fixed")
    with pytest.raises(ValueError, match=r"no route \(status infeasible\)"):
        verify_route(cut_off, reqs, ROADS, data, vals)
    with pytest.raises(TypeError, match="ShortestPaths holds no single route"):
        verify_route(dijkstra(ROADS, [1.0] * 5, 0), reqs, ROADS, data, vals)


def test_unresolved_scope_label_is_refused() -> None:
    # A8: an undeclared element is refused, never read as an empty scope.
    typo = requirement(
        "ADM-TYPO",
        "threshold_admissibility",
        parameters={"quantity": "vehicle_mass"},
        attributes={"limit": "mass_limit"},
        scope=["ferry"],
    )
    reqs = requirement_set((typo,))
    with pytest.raises(ValueError, match=r"scope labels \['ferry'\]"):
        verify_route((0, 1), reqs, ROADS, roads_data(), resolved(reqs))
    with pytest.raises(ValueError, match="not elements"):
        check_inputs(reqs, ROADS, roads_data(), resolved(reqs))


def test_flow_bounds_do_not_apply_to_routes() -> None:
    occ = requirement(
        "OC", "occurrence_bounds", parameters={"maximum": "occurrence_max"}
    )
    reqs = RequirementSet((occ,), PARAMETERS, (REG,))
    vals = resolve_values(
        [ValueSet("reg-a", "2006", {"occurrence_max": value(2)})], reqs
    )
    check = verify_route((0,), reqs, ROADS, roads_data(), vals)
    assert check["OC"].status is S.NOT_APPLICABLE
    assert check["OC"].reason == "flow bounds apply to flows, not to routes"


def test_speed_cap_out_of_scope_on_the_route() -> None:
    reqs = requirement_set((SPEED,))
    check = verify_route((3,), reqs, ROADS, roads_data(), resolved())
    assert check["COST-SPEED"].status is S.NOT_APPLICABLE


@pytest.mark.parametrize("seed", range(15))
@pytest.mark.parametrize("policy", list(UnknownPolicy))
def test_routes_match_enumeration_and_verify(seed: int, policy: UnknownPolicy) -> None:
    case = random_case(seed)
    data, vals, reqs = case.data(), resolved(), requirement_set()
    penalty = 0.5 if policy is UnknownPolicy.PENALIZE else None
    view = compose(
        case.graph,
        [evaluate(r, case.graph, data, vals) for r in ROUTING],
        policy=policy,
        penalty=penalty,
    )
    s, t = endpoints(seed, case.graph.n)
    verdicts = [oracle_verdict(case, a) for a in range(case.graph.m)]
    lowest = 2 if policy is UnknownPolicy.EXCLUDE else 1
    admissible = [v >= lowest for v in verdicts]
    oracle = [
        x + (0.5 if policy is UnknownPolicy.PENALIZE and v == 1 else 0.0)
        for x, v in zip(case.times(), verdicts, strict=True)
    ]
    expected = best_admissible(case, s, t, admissible, oracle)
    times = view.times(case.length, case.speed)
    sp = dijkstra(case.graph, times, s, t, excluded=view.excluded)
    assert math.isclose(sp.distance[t], expected) or sp.distance[t] == expected
    if math.isinf(expected):
        return
    route = sp.path(t)
    assert route is not None
    check = verify_route(route, reqs, case.graph, data, vals, view=view, weights=times)
    for c in check:
        assert c.status is not S.NOT_APPLIED
        assert c.failed == 0
    unknown_on_route = sum(verdicts[a] == 1 for a in set(route))
    assert int(view.unknown[list(route)].sum()) == unknown_on_route
    partial = any(c.status is S.PARTIAL for c in check)
    assert partial == (unknown_on_route > 0)
    assert max((c.unknown for c in check), default=0) <= unknown_on_route
    if policy is UnknownPolicy.EXCLUDE:
        assert unknown_on_route == 0


def test_random_cases_give_varied_routes() -> None:
    # The source and the target are drawn apart from the graph: the routes
    # of the seeds above are not all a single arc.
    lengths = []
    for seed in range(15):
        case = random_case(seed)
        s, t = endpoints(seed, case.graph.n)
        sp = dijkstra(case.graph, case.length, s, t)
        if (path := sp.path(t)) is not None:
            lengths.append(len(path))
    assert sum(k >= 2 for k in lengths) >= 5


# Input checks -------------------------------------------------------------


def test_check_inputs_says_what_can_be_proved() -> None:
    # A4: coverage by element type, provability against the threshold,
    # derived attributes, and the best status a result can reach.
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
    vals = resolve_values([_merged(extra)], reqs)
    report = check_inputs(reqs, ROADS, roads_data(), vals)
    assert len(report) == 7
    mass = report["ADM-MASS"]
    # 44 t on the only bridge, limited to 40 t: no arc can satisfy it.
    assert mass.expected is S.NOT_APPLIED
    assert (mass.known, mass.total) == (1, 1)
    assert mass.coverage == {"bridge": (1, 1)}
    assert mass.provable is False
    assert "cannot be proved on any arc" in mass.reason
    assert (
        verify_route((0, 1), reqs, ROADS, roads_data(), vals)["ADM-MASS"].status
        is mass.expected
    )
    height = report["ADM-HEIGHT"]
    # The clearance is unknown on the only underpass: partial at best.
    assert height.expected is S.PARTIAL
    assert height.provable is None
    assert height.derived == {"clearance": "estimated from imagery"}
    assert report["ADM-CLASS"].provable is True
    assert report["ADM-CLASS"].expected is S.APPLIED
    assert report["ADM-ZONE"].coverage == {
        "bridge": (1, 1),
        "road": (3, 3),
        "underpass": (1, 1),
    }
    speed = report["COST-SPEED"]
    assert speed.expected is S.APPLIED
    assert speed.reason == "data on 3 of the 3 arcs in scope"
    assert report["ADM-WIDTH"].expected is S.NO_DATA
    assert report["ADM-WIDTH"].missing_attributes == ("width_limit",)
    assert report["ADM-TUNNEL"].expected is S.NOT_APPLICABLE
    assert [c.requirement for c in report][-1] == "ADM-TUNNEL"
    to_set = check_inputs(reqs, ROADS, roads_data(), resolved(reqs, mass=None))
    assert to_set["ADM-MASS"].expected is S.NOT_APPLICABLE
    assert to_set["ADM-MASS"].missing_values == ("vehicle_mass",)
    with pytest.raises(ValueError, match="data for 5 arcs, graph of 1 arcs"):
        check_inputs(reqs, Digraph.from_arcs(2, [(0, 1)]), roads_data(), vals)


def test_capacity_statuses_on_routes_and_in_the_inputs() -> None:
    # A ford on each road: 0.5 m of water on a0, 0.9 m on a2, unknown on a4;
    # the vehicle fords 0.75 m. The bridge and the underpass are out of
    # scope.
    reqs, vals = fording(0.75)
    data = ArcData(
        5,
        (
            Attribute.categorical(
                "element", ["road", "bridge", "road", "underpass", "road"], LABELS
            ),
            Attribute.numeric("water_depth", [0.5, None, 0.9, None, None], unit="m"),
        ),
        element="element",
    )
    checks = {
        route: verify_route(route, reqs, ROADS, data, vals)["ADM-DEPTH"]
        for route in ((0, 1), (2, 3), (4,))
    }
    assert (checks[0, 1].status, checks[0, 1].reason) == (
        S.APPLIED,
        "verified on 1 arcs",
    )
    assert (checks[2, 3].status, checks[2, 3].failing) == (S.NOT_APPLIED, (2,))
    assert (checks[(4,)].status, checks[(4,)].unknown_arcs) == (S.PARTIAL, (4,))
    report = check_inputs(reqs, ROADS, data, vals)["ADM-DEPTH"]
    assert (report.expected, report.provable) == (S.APPLIED, True)
    assert (report.known, report.total) == (2, 3)
    assert report.coverage == {"road": (2, 3)}
    deeper = check_inputs(reqs, ROADS, data, fording(0.4)[1])["ADM-DEPTH"]
    assert (deeper.expected, deeper.provable) == (S.PARTIAL, False)


def _merged(extra: ValueSet) -> ValueSet:
    """The values of regulation A, with ``extra`` added."""
    return ValueSet("reg-a", "2006", {**values().values, **extra.values})


def test_expected_status_follows_the_coverage() -> None:
    # Partial coverage with a known passing arc: a route through it is
    # applied; a column without any known value: partial at best.
    reqs = requirement_set((MASS,))
    for limits, expected in (
        ([None, 60, None, None, None], S.APPLIED),
        ([None, None, None, None, None], S.PARTIAL),
    ):
        data = ArcData(
            5,
            (
                Attribute.categorical(
                    "element", ["road", "bridge", "road", "bridge", "road"], ELEMENTS
                ),
                Attribute.numeric("mass_limit", limits),
            ),
            element="element",
        )
        c = check_inputs(reqs, ROADS, data, resolved(reqs))["ADM-MASS"]
        assert c.expected is expected
        route = (0, 1) if expected is S.APPLIED else (2, 3)
        status = verify_route(route, reqs, ROADS, data, resolved(reqs))["ADM-MASS"]
        assert status.status is expected


def test_check_inputs_partial_coverage() -> None:
    case = random_case(5, unknown=0.5)
    report = check_inputs(requirement_set(), case.graph, case.data(), resolved())
    for c in report:
        assert sum(k for k, _ in c.coverage.values()) == c.known
        assert sum(t for _, t in c.coverage.values()) == c.total
        if c.expected is S.PARTIAL:
            assert c.known < c.total
            assert not c.provable
        if c.expected is S.APPLIED:
            assert c.provable
    assert any(0 < c.known < c.total for c in report)
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
    assert data[0]["values"][0]["parameter"] == "vehicle_mass"
    assert data[0]["verification"] == {"passed": 0, "failed": 1, "unknown": 0}
    assert data[0]["unknowns"] == {"count": 0, "policy": "admit_and_count"}
    assert data[0]["impact"] is None


def test_table_keeps_discarded_values_and_infinity() -> None:
    reqs = requirement_set()
    doctrine = ValueSet(
        "doc-b",
        "2019",
        {
            "vehicle_mass": Value(
                60.0, DOC_SRC, Origin.RULEBOOK, unit="t", precedence=1
            ),
            "speed_max": Value(
                math.inf,
                DOC_SRC,
                Origin.CHOICE,
                unit="km/h",
                precedence=1,
                justification="no cap",
            ),
        },
    )
    vals = resolve_values([values(), doctrine], reqs)
    check = verify_route((0, 1), reqs, ROADS, roads_data(), vals)
    rows = {r.id: r for r in requirement_table(check, reqs, vals)}
    mass = rows["ADM-MASS"].to_dict()["values"][0]
    assert mass["value"] == 60.0
    assert [d["value"] for d in mass["discarded"]] == [44.0]
    assert rows["COST-SPEED"].to_dict()["values"][0]["value"] == "inf"
    assert rows["ADM-MASS"].policy is None
    assert rows["ADM-MASS"].to_dict()["unknowns"]["policy"] is None
    with pytest.raises(ValueError, match="unchecked requirements"):
        requirement_table(check, reqs, vals, impacts={"ADM-NONE": None})  # type: ignore[dict-item]


def test_negative_infinity_keeps_its_sign_in_the_table() -> None:
    reqs = requirement_set((MASS,))
    vals = resolved(reqs, mass=-math.inf)
    check = verify_route((0, 1), reqs, ROADS, roads_data(), vals)
    assert check["ADM-MASS"].status is S.APPLIED
    row = requirement_table(check, reqs, vals)[0].to_dict()
    assert row["values"][0]["value"] == "-inf"


# Life-cycle profiles --------------------------------------------------------
#
#   a0 L01: 0 -> 1   a1 L02: 1 -> 2   a2 L03: 2 -> 1 (loop)
#   a3 L04: 1 -> 3   a4 L05: 2 -> 3   a5 L06: 3 -> 0 (return, 1..1)


def bounded(reqs: RequirementSet, data: ArcData, vals: ResolvedValues) -> FlowProblem:
    view = compose(
        PROFILE, [evaluate(r, PROFILE, data, vals) for r in reqs], policy="exclude"
    )
    lower, upper = view.flow_bounds()
    return FlowProblem(PROFILE, lower=lower, upper=upper, cost=[1] * 6, sense="max")


@pytest.mark.parametrize("method", [info.name for info in methods("min_cost_flow")])
def test_profile_bounds_come_from_sourced_requirements(method: str) -> None:
    reqs, data, vals = profile(OC_ALL, OC_L03, RETURN, OC_INF)
    problem = bounded(reqs, data, vals)
    assert problem.upper == (4, 4, 2, 4, 4, 1)
    assert problem.lower == (0, 0, 0, 0, 0, 1)
    result = solve(problem, method=method)
    assert brute_force(problem) == ("optimal", 8)
    assert result.objective == 8
    check = verify_flow(result, reqs, problem, data, vals)
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
    check = verify_flow(result, reqs, forgetful, data, vals)
    assert check.violations == ()
    assert check["OC-L03"].status is S.NOT_APPLIED
    assert check["OC-L03"].failing == (2,)
    assert check["OC-ALL"].status is S.APPLIED


def test_overconstrained_profile_shows_conflicting_bounds() -> None:
    reqs, data, vals = profile(OC_ALL, OC_L03, MIN_L03)
    view = compose(
        PROFILE, [evaluate(r, PROFILE, data, vals) for r in reqs], policy="exclude"
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
        verify_flow(through_l05, reqs, problem, data, vals)["ZONE"].status is S.PARTIAL
    )
    check = verify_flow(through_l04, reqs, problem, data, vals)
    assert check["ZONE"].status is S.NOT_APPLIED
    assert check["ZONE"].failing == (3,)
    broken = verify_flow([0, 0, 0, 0, 0, 0], reqs, problem, data, vals)
    assert broken.violations == ("arc 5: flow 0 outside [1, 1]",)
    assert broken["RETURN"].status is S.NOT_APPLIED
    idle = verify_flow(
        [0] * 6, requirement_set((ZONE,)), problem, roads_like(), resolved()
    )
    assert idle["ADM-ZONE"].status is S.NOT_APPLICABLE


def roads_like() -> ArcData:
    return ArcData(6, (Attribute.numeric("in_zone", [0] * 6),))


def test_cost_terms_and_values_to_be_set_on_flows() -> None:
    reqs = requirement_set((SPEED, MASS))
    problem = FlowProblem(PROFILE)
    check = verify_flow([0] * 6, reqs, problem, roads_like(), resolved(mass=None))
    assert check["COST-SPEED"].status is S.NOT_APPLICABLE
    assert check["COST-SPEED"].reason == "speed caps apply to routes, not to flows"
    assert check["ADM-MASS"].status is S.NOT_APPLICABLE


def test_undeclared_link_and_flow_errors() -> None:
    reqs, data, vals = profile(occurrence("OC-L99", "one", ["L99"]))
    problem = FlowProblem(PROFILE)
    with pytest.raises(ValueError, match=r"scope labels \['L99'\]"):
        verify_flow([0] * 6, reqs, problem, data, vals)
    reqs, data, vals = profile(OC_L03)
    with pytest.raises(ValueError, match="expected 6 arc flows"):
        verify_flow([0], reqs, problem, data, vals)
    stuck = FlowProblem(Digraph.from_arcs(2, [(0, 1)]), lower=[1], upper=[1])
    result = solve(stuck, method="network_simplex")
    with pytest.raises(ValueError, match="has no flow"):
        verify_flow(result, reqs, stuck, ArcData(1, ()), vals)


def test_unknown_element_is_restricted_but_never_forced() -> None:
    # A circulation 0 <-> 1 whose middle arc has an unknown element: the
    # maximum holds there too, the minimum is not imposed on a presumption,
    # and the arc is counted unknown.
    graph = Digraph.from_arcs(2, [(0, 1), (0, 1), (1, 0)])
    reqs, _, vals = profile(occurrence("OCC-A", "one", ["L01"], minimum="one"))
    data = ArcData(
        3,
        (Attribute.categorical("link", ["L01", None, "L02"], ("L01", "L02")),),
        element="link",
    )
    effect = evaluate(reqs["OCC-A"], graph, data, vals)
    assert effect.lower is not None
    assert effect.upper is not None
    assert effect.lower.tolist() == [1.0, 0.0, 0.0]
    assert effect.upper.tolist() == [1.0, 1.0, math.inf]
    problem = FlowProblem(graph)
    check = verify_flow([1, 0, 1], reqs, problem, data, vals)["OCC-A"]
    assert check.status is S.PARTIAL
    assert check.unknown_arcs == (1,)
    assert check.reason == "1 arcs of unknown element below the minimum"
    assert verify_flow([1, 1, 2], reqs, problem, data, vals)["OCC-A"].status is (
        S.APPLIED
    )
    assert verify_flow([1, 2, 3], reqs, problem, data, vals)["OCC-A"].failing == (1,)
    report = check_inputs(reqs, graph, data, vals)["OCC-A"]
    assert report.expected is S.APPLIED
    assert (report.known, report.total) == (1, 2)
    assert report.coverage == {"L01": (1, 1), None: (0, 1)}
    # Without a minimum, the maximum alone holds on an unknown element.
    reqs, _, vals = profile(occurrence("OCC-B", "one", ["L01"]))
    report = check_inputs(reqs, graph, data, vals)["OCC-B"]
    assert (report.known, report.total) == (2, 2)


def test_declared_link_without_arc_is_out_of_scope() -> None:
    reqs, _, vals = profile(occurrence("OC-L99", "one", ["L99"]))
    data = ArcData(
        6,
        (Attribute.categorical("link", ["L01"] * 6, ("L01", "L99")),),
        element="link",
    )
    check = verify_flow([0] * 6, reqs, FlowProblem(PROFILE), data, vals)["OC-L99"]
    assert check.status is S.NOT_APPLICABLE
    assert check.reason == "no arc in the scope"


def test_effects_of_every_profile_requirement_are_bounds() -> None:
    reqs, data, vals = profile(OC_ALL, OC_L03, RETURN)
    for r in reqs:
        e = evaluate(r, PROFILE, data, vals)
        assert isinstance(e, Effect)
        assert e.lower is not None


def test_empty_cases() -> None:
    empty = Digraph.from_arcs(1, [])
    view = compose(empty, [], policy="exclude")
    assert (view.m, view.excluded, view.capped) == (0, (), ())
    none = RequirementSet((), PARAMETERS, (REG,))
    assert len(verify_route((), none, ROADS, roads_data(), resolved(none))) == 0
    assert len(check_inputs(none, ROADS, roads_data(), resolved(none))) == 0
