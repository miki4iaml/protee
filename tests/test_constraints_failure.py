# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Useful failure: conflicts, relaxations, tiers and impacts, on routes and
on life-cycle profiles."""

import itertools
import random
from collections.abc import Callable

import pytest
from constraints_cases import (
    ELEMENTS,
    MIN_L03,
    OC_ALL,
    OC_L03,
    PROFILE,
    RETURN,
    ROUTING,
    SRC,
    occurrence,
    profile,
    requirement,
    requirement_set,
    resolved,
)

from protee.constraints import (
    ArcData,
    Attribute,
    FlowSearch,
    Impact,
    Requirement,
    RouteSearch,
    Tier,
    UnknownPolicy,
    minimal_conflict,
    minimal_relaxation,
    relax_by_tiers,
    requirement_table,
    verify_route,
)
from protee.flow import FlowProblem
from protee.graph import Digraph

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
    irreducible = minimal_conflict(ids, feasible, method="deletion_filter")
    assert frozenset(irreducible.requirements) in conflicts
    assert irreducible.method == "deletion_filter"
    assert irreducible.evaluations <= len(ids) + 1
    hitting = [
        k
        for k in range(len(ids) + 1)
        for s in itertools.combinations(ids, k)
        if all(c & set(s) for c in conflicts)
    ]
    fewest = minimal_relaxation(ids, feasible, method="enumeration")
    assert len(fewest.requirements) == hitting[0]
    greedy = minimal_relaxation(ids, feasible, method="greedy")
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
    assert minimal_conflict(ids, never, method="enumeration").requirements == ()
    assert minimal_relaxation(ids, always, method="greedy").requirements == ()
    with pytest.raises(ValueError, match="without any requirement"):
        minimal_relaxation(ids, never, method="greedy")
    with pytest.raises(ValueError, match="unknown method"):
        minimal_conflict(ids, never, method="iis")
    with pytest.raises(ValueError, match="unknown method"):
        minimal_relaxation(ids, always, method="best")


def test_tier_is_computed_from_the_conditions() -> None:
    # A7: the option needs works on a structure (tier 3); no label of the
    # data decides its tier.
    tiers = [
        Tier(1, "detour", frozenset({"DETOUR"})),
        Tier(3, "works on a structure", frozenset({"WORKS", "DETOUR"})),
    ]
    feasible = holds([frozenset({"WORKS"})])
    result = relax_by_tiers(["DETOUR", "WORKS"], feasible, tiers)
    assert result.level == 3
    assert result.relaxed == ("WORKS",)
    assert result.tried == ((1, False), (3, True))
    none_needed = relax_by_tiers(["DETOUR"], feasible, tiers)
    assert (none_needed.level, none_needed.relaxed) == (0, ())
    hopeless = relax_by_tiers(["X"], holds([frozenset({"X"})]), tiers)
    assert hopeless.level is None
    with pytest.raises(ValueError, match="share a level"):
        relax_by_tiers(["X"], feasible, [tiers[0], tiers[0]])
    with pytest.raises(ValueError, match="positive integer"):
        Tier(0, "none", frozenset())


# Routes -------------------------------------------------------------------
#
#   a0: 0 -> 1 road       a1: 1 -> 3 bridge, 40 t, class C70
#   a2: 0 -> 2 road       a3: 2 -> 3 underpass, clearance unknown
#   a4: 0 -> 3 road, inside the zone

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
        (1, 1, 1, 1, 1),
        policy,
        method,
    )


def test_useful_failure_on_a_route() -> None:
    # A6: the bans cut the target off; the explanation names the
    # requirements, and the relaxations are proposed, never a silent
    # penalty.
    s = search(UnknownPolicy.EXCLUDE)
    assert s.solve() is None
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


def test_impact_with_and_without() -> None:
    s = search(UnknownPolicy.ADMIT_AND_COUNT)
    zone = s.impact("ADM-ZONE")
    assert zone == Impact("ADM-ZONE", True, True, 2.0, 1.0, 1)
    assert zone.delta == 1.0
    assert s.impact("COST-SPEED").arcs_removed == 0
    blocked = search(UnknownPolicy.EXCLUDE).impact("ADM-HEIGHT")
    assert (blocked.feasible_with, blocked.feasible_without) == (False, True)
    assert blocked.delta is None
    assert blocked.arcs_removed == 1
    view = s.view()
    route = s.solve()
    assert route is not None
    check = verify_route(route, requirement_set(), ROADS, DATA, resolved(), view=view)
    rows = requirement_table(
        check, requirement_set(), resolved(), view=view, impacts={"ADM-ZONE": zone}
    )
    row = next(r for r in rows if r.id == "ADM-ZONE")
    assert row.impact is not None
    assert row.impact["delta"] == 1.0
    assert row.to_dict()["impact"]["cost_without"] == 1.0
    assert next(r for r in rows if r.id == "ADM-MASS").impact is None


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
        base,
        UnknownPolicy.ADMIT_AND_COUNT,
        "dijkstra",
    )
    lex = RouteSearch(
        reqs,
        graph,
        data,
        resolved(reqs),
        0,
        3,
        base,
        UnknownPolicy.ADMIT_AND_COUNT,
        "lexicographic_dijkstra",
    )
    assert plain.solve() is not None
    assert plain.solve().arcs == (0, 1)  # type: ignore[union-attr]
    assert lex.solve().arcs == (2, 3)  # type: ignore[union-attr]
    assert lex.solve().cost == 3.0  # type: ignore[union-attr]
    assert lex.view().unknown_count == 1
    assert lex.view().lexicographic_weights(base)[1] == (1, 1.0)
    with pytest.raises(ValueError, match="expected 4 base"):
        lex.view().lexicographic_weights([1.0])


def test_route_search_checks_its_arguments() -> None:
    with pytest.raises(ValueError, match="unknown method"):
        search(UnknownPolicy.EXCLUDE, method="astar")
    with pytest.raises(ValueError, match="unknown requirements"):
        search(UnknownPolicy.EXCLUDE).solve(["ADM-NONE"])


# Life-cycle profiles ------------------------------------------------------


def flow_search(
    *requirements: Requirement, policy: UnknownPolicy = UnknownPolicy.ADMIT_AND_COUNT
) -> FlowSearch:
    reqs, data, vals = profile(*requirements)
    problem = FlowProblem(PROFILE, cost=[1] * 6, sense="max")
    return FlowSearch(reqs, problem, data, vals, "network_simplex", policy)


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
        FlowSearch(reqs, FlowProblem(PROFILE), data, vals, "simplex")
