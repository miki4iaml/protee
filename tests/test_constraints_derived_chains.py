# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Derived values from end to end, through the API only: the bound of a
partial envelope in the admissibility patterns, a group that crosses fords,
an equipment in several packagings in a life-cycle profile, and what the
table and the provenance show of each derived value.

No value is computed in a test: the derivations, the evaluation and the
searches of protee compute them, and the expected values are literals or
come from the verdicts of the members taken one by one.
"""

from __future__ import annotations

import json
import math
import pickle
import re
from collections.abc import Callable
from dataclasses import replace

import numpy as np
import pytest
from constraints_cases import LINKS, PROFILE
from derive_cases import (
    ALIAS_BOOK,
    CATEGORIES,
    CLASSES,
    KNOWN_ONLY,
    MASS,
    NA,
    PARAMETERS,
    PROPAGATE,
    VOCABULARY,
    WIDTH,
    A,
    B,
    C,
    D,
    chosen,
    classify,
    derive,
    measure,
    member,
    plan,
    regulation,
    select,
    sheet,
)
from hypothesis import given
from hypothesis import strategies as st

from protee.constraints import (
    Aggregation,
    ArcData,
    Attribute,
    Comparison,
    Conversion,
    Derivation,
    DerivationInput,
    Derived,
    FlowSearch,
    Gap,
    GapCount,
    Group,
    Member,
    OnUnknown,
    Origin,
    Parameter,
    Reason,
    Requirement,
    RequirementCheck,
    RequirementSet,
    RequirementStatus,
    ResolvedValues,
    RouteSearch,
    Rulebook,
    RulebookKind,
    Source,
    UnknownPolicy,
    Value,
    ValueSet,
    ValueState,
    Verdict,
    Verification,
    ZeroCount,
    aggregate,
    check_inputs,
    evaluate,
    provenance,
    requirement_table,
    resolve_values,
    select_by_class,
    verify_flow,
    verify_route,
)
from protee.constraints._table import _value
from protee.flow import FlowProblem
from protee.graph import Digraph

S = RequirementStatus
FAIL, UNKNOWN, PASS = int(Verdict.FAIL), int(Verdict.UNKNOWN), int(Verdict.PASS)

# A group that crosses fords -------------------------------------------------
#
# The depth a ford demands must be at most the depth each vehicle can ford
# (capacity_admissibility): the envelope of the group is the minimum. The
# width a vehicle needs must be at most the width of the ford
# (threshold_admissibility): the envelope is the maximum.

FORD = (Parameter("fording_depth", unit="m"), Parameter("crossing_width", unit="m"))
DOCTRINE = Rulebook("doc-f", RulebookKind.DOCTRINE, {"en": "Crossing doctrine F"}, "1")
DOCTRINE_SRC = Source(
    "Crossing doctrine F", rulebook="doc-f", edition="1", locator="table 2"
)
DEPTH = Requirement(
    "FORD-DEPTH",
    "capacity_admissibility",
    {"en": "The water of a ford is no deeper than every vehicle can ford."},
    DOCTRINE_SRC,
    parameters={"capacity": "fording_depth"},
    attributes={"demand": "water_depth"},
    scope=frozenset({"ford"}),
)
BREADTH = Requirement(
    "FORD-WIDTH",
    "threshold_admissibility",
    {"en": "A ford is as wide as every vehicle needs."},
    DOCTRINE_SRC,
    parameters={"quantity": "crossing_width"},
    attributes={"limit": "ford_width"},
    scope=frozenset({"ford"}),
)
FORDS = RequirementSet((DEPTH, BREADTH), FORD, (DOCTRINE,))


def vehicle(id: str, **values: float | NA) -> Member:
    """An invented vehicle, described by its technical sheet; a parameter
    not given is unknown."""
    source = Source(f"Technical sheet of {id}", locator="p. 3")
    sheet_ = {
        k: Value(None, source, Origin.STATEMENT, unit="m", not_applicable=x.reason)
        if isinstance(x, NA)
        else Value(x, source, Origin.STATEMENT, unit="m")
        for k, x in values.items()
    }
    return Member(id, (ValueSet(f"sheet-{id}", "1", sheet_),))


#: truck-b fords the least; the depth of carrier-c is unknown; load-d,
#: carried by carrier-c, neither fords nor needs a width of its own.
COLUMN = Group(
    "column",
    (
        (vehicle("truck-a", fording_depth=0.75, crossing_width=2.5), 3),
        (vehicle("truck-b", fording_depth=0.5, crossing_width=3.0), 2),
        (vehicle("carrier-c", crossing_width=3.6), 1),
        (
            vehicle(
                "load-d",
                fording_depth=NA("carried by carrier-c"),
                crossing_width=NA("carried by carrier-c"),
            ),
            1,
        ),
    ),
)
ENVELOPE = {
    "fording_depth": Aggregation.min("fording_depth"),
    "crossing_width": Aggregation.max("crossing_width"),
}
#: The depth of carrier-c, assumed by the planner.
ASSUMED = OnUnknown.assume(
    {
        "fording_depth": Value(
            0.6,
            Source("Planning note"),
            Origin.CHOICE,
            unit="m",
            justification="no sheet: the depth of a carrier of its class",
        )
    }
)
#   a0: 0 -> 1 road, 2 km          a1: 1 -> 3 ford, 0.6 m deep, 4 m wide
#   a2: 0 -> 2 road, 2 km          a3: 2 -> 3 ford, 0.4 m deep, 3 m wide
#   a4: 0 -> 3 ford, 0.3 m deep, 5 m wide, 6 km
#   a5: 0 -> 4 road, 5 km          a6: 4 -> 3 road, 5 km
CROSSING = Digraph.from_arcs(
    5, [(0, 1), (1, 3), (0, 2), (2, 3), (0, 3), (0, 4), (4, 3)]
)
CROSSING_DATA = ArcData(
    7,
    (
        Attribute.categorical(
            "element",
            ["road", "ford", "road", "ford", "ford", "road", "road"],
            ("road", "ford"),
        ),
        Attribute.numeric(
            "water_depth", [None, 0.6, None, 0.4, 0.3, None, None], unit="m"
        ),
        Attribute.numeric(
            "ford_width", [None, 4.0, None, 3.0, 5.0, None, None], unit="m"
        ),
    ),
    element="element",
)
KM = (2.0, 2.0, 2.0, 2.0, 6.0, 5.0, 5.0)


def crossing(
    unknown: OnUnknown, policy: UnknownPolicy
) -> tuple[Derived, ResolvedValues, RouteSearch]:
    d = aggregate(COLUMN, ENVELOPE, parameters=FORD, unknown=unknown, edition="1")
    values = resolve_values([d.values], FORDS)
    search = RouteSearch(
        FORDS,
        CROSSING,
        CROSSING_DATA,
        values,
        0,
        3,
        method="dijkstra",
        policy=policy,
        base=KM,
    )
    return d, values, search


def test_the_group_avoids_the_fords_its_known_members_cannot_cross() -> None:
    d, values, search = crossing(PROPAGATE, UnknownPolicy.ADMIT_AND_COUNT)
    depth = d["fording_depth"]
    assert depth.to_be_set
    assert depth.derivation is not None
    assert (depth.derivation.bound, depth.derivation.bound_fixed_by) == (
        0.5,
        ("truck-b",),
    )
    assert d.unknown["fording_depth"].names == ("carrier-c",)
    assert d["crossing_width"].value == 3.6
    # A1: a1 is deeper than truck-b fords, whatever the depth of carrier-c;
    # a3 is narrower than carrier-c needs. a4 stays unknown: carrier-c may
    # ford less than the 0.3 m of water of a4.
    view = search.view()
    assert view.excluded == (1, 3)
    assert view.unknown.tolist() == [False] * 4 + [True] + [False] * 2
    route = search.solve()
    assert (route.arcs, route.cost) == ((4,), 6.0)
    # Without the depth, a1 would be taken: 4 km instead of 6.
    impact = search.impact("FORD-DEPTH")
    assert (impact.cost_with, impact.cost_without) == (6.0, 4.0)
    check = search.verify(route)
    undecided = (
        "value of 'fording_depth' to be set: no value for carrier-c; at most "
        "0.5 m (truck-b)"
    )
    assert (check["FORD-DEPTH"].status, check["FORD-DEPTH"].reason) == (
        S.PARTIAL,
        f"1 arcs unknown; {undecided}",
    )
    assert check["FORD-WIDTH"].status is S.APPLIED
    through = verify_route((0, 1), FORDS, CROSSING, CROSSING_DATA, values)
    assert (through["FORD-DEPTH"].status, through["FORD-DEPTH"].reason) == (
        S.NOT_APPLIED,
        f"1 arcs violate it; {undecided}",
    )
    report = check_inputs(FORDS, CROSSING, CROSSING_DATA, values)["FORD-DEPTH"]
    assert (report.expected, report.missing_values) == (S.PARTIAL, ("fording_depth",))
    assert report.reason == (
        f"{undecided}; data on 3 of the 3 arcs in scope, 1 fail at the bound"
    )
    # The table cites the member that fixes each value, or its bound.
    rows = {
        r.id: r.to_dict()
        for r in requirement_table(check, FORDS, values, view=search.view())
    }
    shown = rows["FORD-DEPTH"]["values"][0]
    assert (shown["value"], shown["not_applicable"]) == (None, None)
    assert shown["derivation"]["bound"] == 0.5
    assert shown["derivation"]["bound_fixed_by"] == ["truck-b"]
    assert shown["derivation"]["summary"] == (
        "min of 'fording_depth' over column: unknown, at most 0.5 m (fixed by "
        "truck-b (Technical sheet of truck-b (1), p. 3)); 1 member without a "
        "value: carrier-c; left out: load-d (not applicable: carried by "
        "carrier-c)"
    )
    assert rows["FORD-WIDTH"]["values"][0]["derivation"]["summary"] == (
        "max of 'crossing_width' over column: 3.6 m, fixed by carrier-c "
        "(Technical sheet of carrier-c (1), p. 3); left out: load-d (not "
        "applicable: carried by carrier-c)"
    )
    assert rows["FORD-DEPTH"]["unknowns"] == {
        "count": 1,
        "policy": "admit_and_count",
    }
    json.dumps(list(rows.values()))


def test_excluding_the_unknown_leaves_every_ford() -> None:
    _, _, search = crossing(PROPAGATE, UnknownPolicy.EXCLUDE)
    assert search.view().excluded == (1, 3, 4)
    route = search.solve()
    assert (route.arcs, route.cost) == ((5, 6), 10.0)
    check = search.verify(route)
    assert {c.status for c in check} == {S.NOT_APPLICABLE}
    assert check["FORD-DEPTH"].reason == "no arc of the route in the scope"


def test_an_assumed_depth_is_declared_and_decides() -> None:
    d, values, search = crossing(ASSUMED, UnknownPolicy.EXCLUDE)
    depth = d["fording_depth"]
    assert depth.value == 0.5
    assert d.assumed["fording_depth"].names == ("carrier-c",)
    assert search.view().excluded == (1, 3)
    route = search.solve()
    assert route.arcs == (4,)
    check = search.verify(route)
    assert {c.status for c in check} == {S.APPLIED}
    (row,) = (
        r for r in requirement_table(check, FORDS, values) if r.id == "FORD-DEPTH"
    )
    assert row.to_dict()["values"][0]["derivation"]["summary"] == (
        "min of 'fording_depth' over column: 0.5 m, fixed by truck-b (Technical "
        "sheet of truck-b (1), p. 3); assumed for carrier-c: 0.6 m (no sheet: "
        "the depth of a carrier of its class); left out: load-d (not "
        "applicable: carried by carrier-c)"
    )


def test_the_provenance_records_the_derivations_set_aside_too() -> None:
    # The assumed depth prevails by its precedence; the propagated one is
    # set aside, and both derivations are recorded.
    assumed = aggregate(
        COLUMN, ENVELOPE, parameters=FORD, unknown=ASSUMED, edition="2", precedence=1
    )
    propagated = aggregate(
        COLUMN, ENVELOPE, parameters=FORD, unknown=PROPAGATE, edition="1"
    )
    values = resolve_values([assumed.values, propagated.values], FORDS)
    record = provenance(
        "dijkstra", {}, inputs={}, requirements=FORDS, values=values, result=()
    )
    assert ("fording_depth", "column", "2", True) in record.values
    assert ("fording_depth", "column", "1", False) in record.values
    assert record.derivations == (
        ("crossing_width", "column", "aggregate", "max", ("carrier-c",)),
        ("fording_depth", "column", "aggregate", "min", ()),
        ("fording_depth", "column", "aggregate", "min", ("truck-b",)),
    )


# The bound of a partial envelope (A1) ----------------------------------------


def parallel(attribute: Attribute) -> tuple[Digraph, ArcData]:
    """Parallel arcs, one per value of ``attribute``."""
    m = len(attribute.values)
    return Digraph.from_arcs(2, [(0, 1)] * m), ArcData(m, (attribute,))


def verdicts(
    requirement: Requirement, graph: Digraph, data: ArcData, values: ResolvedValues
) -> list[int]:
    effect = evaluate(requirement, graph, data, values)
    assert effect.verdict is not None
    return [int(v) for v in effect.verdict]


def kleene(columns: list[list[int]]) -> list[int]:
    """The Kleene conjunction of the verdicts of several members."""
    return [min(column) for column in zip(*columns, strict=True)]


def alike(columns: list[list[int]]) -> list[int]:
    """The verdicts that every column gives alike, unknown where they
    differ: the verdicts of a value that may be any of those of the
    columns (a member without a value, all the completions of a chain)."""
    return [
        column[0] if len(set(column)) == 1 else UNKNOWN
        for column in zip(*columns, strict=True)
    ]


def depth_values(x: float) -> ResolvedValues:
    stated = Value(x, Source("Statement"), Origin.STATEMENT, unit="m")
    return resolve_values([ValueSet("stated", "1", {"fording_depth": stated})], FORDS)


DEPTHS = st.lists(
    st.one_of(st.none(), st.sampled_from([0.0, 0.3, 0.5, 0.75, 1.2, math.inf])),
    min_size=1,
    max_size=4,
)
WATERS = st.lists(
    st.one_of(st.none(), st.sampled_from([-1.0, 0.0, 0.3, 0.5, 0.6, 1.2, math.inf])),
    min_size=1,
    max_size=6,
)


@given(DEPTHS, WATERS)
def test_the_minimum_of_a_capacity_is_its_kleene_conjunction(
    depths: list[float | None], waters: list[float | None]
) -> None:
    # The verdict of the minimum is the conjunction of the verdicts of the
    # members; a member without a depth decides an arc only where every
    # depth decides it alike, the least and the largest.
    graph, data = parallel(Attribute.numeric("water_depth", waters, unit="m"))
    req = Requirement(
        "DEPTH",
        "capacity_admissibility",
        {"en": "Every member fords the water."},
        DOCTRINE_SRC,
        parameters={"capacity": "fording_depth"},
        attributes={"demand": "water_depth"},
    )
    reqs = RequirementSet((req,), FORD, (DOCTRINE,))
    group = Group(
        "G",
        tuple(
            (vehicle(f"m{k}") if x is None else vehicle(f"m{k}", fording_depth=x), 1)
            for k, x in enumerate(depths)
        ),
    )
    known = [x for x in depths if x is not None]
    each = [verdicts(req, graph, data, depth_values(x)) for x in known]
    if len(known) < len(depths):
        ends = (-math.inf, math.inf)
        each.append(alike([verdicts(req, graph, data, depth_values(x)) for x in ends]))
    d = aggregate(
        group,
        {"fording_depth": Aggregation.min("fording_depth")},
        parameters=FORD,
        unknown=PROPAGATE,
        edition="1",
    )
    found = verdicts(req, graph, data, resolve_values([d.values], reqs))
    assert found == kleene(each)


ARC_CLASSES = st.lists(st.one_of(st.none(), st.sampled_from(CLASSES)), min_size=1)
LABELS = st.lists(
    st.one_of(st.none(), st.sampled_from(CLASSES)), min_size=1, max_size=4
)
LOAD_CLASS = Requirement(
    "LOAD-CLASS",
    "class_admissibility",
    {"en": "Every bridge carries the class of every member."},
    Source("Regulation C", locator="art. 2"),
    parameters={"required_class": "load_class"},
    attributes={"class": "arc_class"},
)
LOAD_CLASSES = RequirementSet((LOAD_CLASS,), PARAMETERS, (ALIAS_BOOK,))


def label_values(name: str, label: str) -> ResolvedValues:
    stated = Value(label, Source("Statement"), Origin.STATEMENT)
    reqs = LOAD_CLASSES if name == "load_class" else CATEGORY_REQS
    return resolve_values([ValueSet("stated", "1", {name: stated})], reqs)


@given(LABELS, ARC_CLASSES)
def test_the_strictest_class_is_its_kleene_conjunction(
    labels: list[str | None], arcs: list[str | None]
) -> None:
    graph, data = parallel(Attribute.categorical("arc_class", arcs, CLASSES))
    group = Group(
        "G",
        tuple(
            (member(f"m{k}") if x is None else member(f"m{k}", load_class=x), 1)
            for k, x in enumerate(labels)
        ),
    )
    # A member without a class may be of any class of the order: an arc
    # that admits the strictest one passes whatever its class.
    known = [x for x in labels if x is not None]
    each = [
        verdicts(LOAD_CLASS, graph, data, label_values("load_class", x)) for x in known
    ]
    if len(known) < len(labels):
        each.append(
            alike(
                [
                    verdicts(LOAD_CLASS, graph, data, label_values("load_class", c))
                    for c in CLASSES
                ]
            )
        )
    d = derive(group, {"load_class": Aggregation.strictest("load_class", CLASSES)})
    found = verdicts(LOAD_CLASS, graph, data, resolve_values([d.values], LOAD_CLASSES))
    assert found == kleene(each)


CATEGORY = Requirement(
    "CATEGORY",
    "class_admissibility",
    {"en": "Every road admits the category of the subject."},
    Source("Regulation C", locator="art. 9"),
    parameters={"required_class": "category"},
    attributes={"class": "arc_category"},
)
CATEGORY_REQS = RequirementSet((CATEGORY,), VOCABULARY, (ALIAS_BOOK,))
CHARACTERISTIC_VALUES = {
    "width": st.one_of(st.none(), st.sampled_from([2.5, 3.0, 3.5, 4.5])),
    "mass": st.one_of(st.none(), st.sampled_from([10.0, 30.0, 40.0, 50.0])),
}


@given(
    CHARACTERISTIC_VALUES["width"],
    CHARACTERISTIC_VALUES["mass"],
    st.lists(st.one_of(st.none(), st.sampled_from(CATEGORIES)), min_size=1),
)
def test_a_partial_class_is_the_kleene_conjunction_of_its_characteristics(
    width: float | None, mass: float | None, arcs: list[str | None]
) -> None:
    # The characteristics are the members of a classification: the class
    # of each known one alone gives its verdicts; an unknown one may be of
    # any class.
    graph, data = parallel(Attribute.categorical("arc_category", arcs, CATEGORIES))
    given_ = {k: x for k, x in (("width", width), ("mass", mass)) if x is not None}
    each = []
    for row in (WIDTH, MASS):
        if row.parameter in given_:
            alone = classify(
                sheet("sheet-S", **{row.parameter: given_[row.parameter]}),
                characteristics=[row],
            )
            label = alone["category"].value
            assert isinstance(label, str)
            each.append(
                verdicts(CATEGORY, graph, data, label_values("category", label))
            )
    if len(given_) < 2:
        each.append(any_category(graph, data))
    d = classify(sheet("sheet-S", **given_))
    found = verdicts(CATEGORY, graph, data, resolve_values([d.values], CATEGORY_REQS))
    assert found == kleene(each)


def any_category(graph: Digraph, data: ArcData) -> list[int]:
    """The verdicts of a category that may be any."""
    return alike(
        [
            verdicts(CATEGORY, graph, data, label_values("category", c))
            for c in CATEGORIES
        ]
    )


# Chains whose inputs are partial envelopes -----------------------------------

#: Widths that reach every category and its thresholds (3 m and 4 m, "up
#: to"): what a member without a width may be.
ANY_WIDTH = (-math.inf, 2.5, 3.0, 3.5, 4.0, 4.5, math.inf)


def chain_verdicts(
    widths: list[float | None], graph: Digraph, data: ArcData
) -> list[int]:
    """The verdicts of the category of the envelope of a group of the given
    widths (``None`` unknown): max, then classification, under propagate."""
    group = Group(
        "G",
        tuple(
            (member(f"m{k}") if w is None else member(f"m{k}", width=w), 1)
            for k, w in enumerate(widths)
        ),
    )
    envelope = derive(group, {"width": Aggregation.max("width")})
    category = classify(envelope, characteristics=[WIDTH])
    return verdicts(
        CATEGORY, graph, data, resolve_values([category.values], CATEGORY_REQS)
    )


@given(
    st.lists(st.one_of(st.none(), st.sampled_from(ANY_WIDTH[1:-1])), min_size=1),
    st.lists(st.one_of(st.none(), st.sampled_from(CATEGORIES)), min_size=1),
)
def test_a_class_of_a_partial_envelope_is_exact(
    widths: list[float | None], arcs: list[str | None]
) -> None:
    # The envelope of a group with members without a width, classified,
    # then compared with the category of each arc: an arc is decided when
    # every completion of the unknown widths decides it alike. The maximum
    # depends on the largest of them: one width for all covers every case.
    graph, data = parallel(Attribute.categorical("arc_category", arcs, CATEGORIES))
    found = chain_verdicts(widths, graph, data)
    completions = [
        chain_verdicts([x if w is None else w for w in widths], graph, data)
        for x in ANY_WIDTH
    ]
    assert found == alike(completions)


#: What a vehicle described by its width and its mass may be, by category
#: (the first value of each is of the first category, and so on).
WIDTH_BY_RANK = (2.5, 3.5, 4.5)
MASS_BY_RANK = (10.0, 30.0, 50.0)


def nested_verdicts(
    vehicles: list[tuple[float | None, float | None]], graph: Digraph, data: ArcData
) -> list[int]:
    """The verdicts of the strictest category of a group of vehicles, each
    classified by its own width and mass (``None`` unknown), under
    propagate: the category of a vehicle may be partial itself."""
    members = []
    for k, (width, mass) in enumerate(vehicles):
        given_ = {n: x for n, x in (("width", width), ("mass", mass)) if x is not None}
        own = classify(sheet(f"sheet-v{k}", **given_)).values
        members.append((Member(f"v{k}", (own,)), 1))
    d = aggregate(
        Group("G", tuple(members)),
        {"category": Aggregation.strictest("category", CATEGORIES)},
        parameters=VOCABULARY,
        unknown=PROPAGATE,
        edition="1",
    )
    return verdicts(CATEGORY, graph, data, resolve_values([d.values], CATEGORY_REQS))


VEHICLE = st.tuples(
    st.one_of(st.none(), st.sampled_from(WIDTH_BY_RANK)),
    st.one_of(st.none(), st.sampled_from(MASS_BY_RANK)),
)


@given(
    st.lists(VEHICLE, min_size=1, max_size=3),
    st.lists(st.one_of(st.none(), st.sampled_from(CATEGORIES)), min_size=1),
)
def test_the_strictest_of_partial_classes_is_exact(
    vehicles: list[tuple[float | None, float | None]], arcs: list[str | None]
) -> None:
    # The category of the group is the highest rank of every known or
    # unknown characteristic of every vehicle: completing all the unknown
    # ones at one rank covers every case.
    graph, data = parallel(Attribute.categorical("arc_category", arcs, CATEGORIES))
    found = nested_verdicts(vehicles, graph, data)
    completions = [
        nested_verdicts(
            [
                (
                    WIDTH_BY_RANK[r] if w is None else w,
                    MASS_BY_RANK[r] if m is None else m,
                )
                for w, m in vehicles
            ],
            graph,
            data,
        )
        for r in range(len(CATEGORIES))
    ]
    assert found == alike(completions)


def test_a_known_member_at_the_top_decides_through_a_chain() -> None:
    # A is 4.5 m wide, beyond the last threshold; U has no width. The
    # envelope is to be set, at least 4.5 m: its category is the third,
    # decided despite U, as for A alone.
    group = Group("G", ((member("A", width=4.5), 1), (member("U"), 1)))
    envelope = derive(group, {"width": Aggregation.max("width")})
    assert envelope["width"].to_be_set
    derived = classify(envelope, characteristics=[WIDTH])
    category = derived["category"]
    assert category.value == "3"
    assert category.derivation is not None
    assert (category.derivation.fixed_by, category.derivation.unknown) == (
        ("width",),
        ("width",),
    )
    graph, data = parallel(
        Attribute.categorical("arc_category", ["2", "1"], CATEGORIES)
    )
    values = resolve_values([derived.values], CATEGORY_REQS)
    assert verdicts(CATEGORY, graph, data, values) == [FAIL, FAIL]
    assert said(category) == (
        "highest rank of width: '3', fixed by 'width' (at least 4.5 m above 4 m, "
        "art. 3); decided by the bound of width despite unknown values for width"
    )
    # Below the top, the class is to be set, at least as strict as the
    # rank of the bound.
    group = Group("G", ((member("A", width=3.5), 1), (member("U"), 1)))
    envelope = derive(group, {"width": Aggregation.max("width")})
    category = classify(envelope, characteristics=[WIDTH])["category"]
    assert category.to_be_set
    assert category.derivation is not None
    assert (category.derivation.bound, category.derivation.bound_fixed_by) == (
        "2",
        ("width",),
    )
    # A minimum bounds nothing upward: under "above", the class has no
    # bound.
    least = derive(group, {"width": Aggregation.min("width")})
    category = classify(least, characteristics=[WIDTH])["category"]
    assert category.derivation is not None
    assert (category.to_be_set, category.derivation.bound) == (True, None)


def test_a_bound_class_counts_in_the_strictest_of_a_group() -> None:
    # X is at least of the second category by its width, its mass
    # unknown; Y is of the first: the group is at least of the second,
    # bounded by X.
    x = classify(sheet("sheet-X", width=3.5)).values
    y = classify(sheet("sheet-Y", width=2.5, mass=10.0)).values
    assert x.values["category"].to_be_set
    group = Group("G", ((Member("X", (x,)), 1), (Member("Y", (y,)), 1)))
    rules = {"category": Aggregation.strictest("category", CATEGORIES)}
    d = aggregate(group, rules, parameters=VOCABULARY, unknown=PROPAGATE, edition="1")
    trace = d["category"].derivation
    assert trace is not None
    assert (d["category"].value, trace.bound, trace.bound_fixed_by, trace.unknown) == (
        None,
        "2",
        ("X",),
        ("X",),
    )
    assert said(d["category"]) == (
        "strictest of 'category' over G: unknown, at least as strict as '2' (fixed "
        "by X (at least as strict as '2', classify_by_thresholds of classes "
        "(1))); 1 member without a value: X"
    )
    # A bound at the last label decides the group (DD9).
    w = classify(sheet("sheet-W", mass=30.0), characteristics=[MASS]).values
    top = Group(
        "T",
        (
            (Member("W", (w,)), 1),
            (Member("X", (_bounded_at_top(),)), 1),
            (Member("Y", (y,)), 1),
        ),
    )
    d = aggregate(top, rules, parameters=VOCABULARY, unknown=PROPAGATE, edition="1")
    trace = d["category"].derivation
    assert trace is not None
    assert (d["category"].value, trace.fixed_by, trace.unknown) == ("3", ("X",), ("X",))
    # A label the bound allows outside the order of the group is refused.
    narrow = {"category": Aggregation.strictest("category", ("1", "2"))}
    with pytest.raises(ValueError, match="may be '3', not one of the order"):
        aggregate(group, narrow, parameters=VOCABULARY, unknown=PROPAGATE, edition="1")


def _bounded_at_top() -> ValueSet:
    """A category to be set, at least as strict as the last one: by hand,
    since a classification decides it already (DD9)."""
    trace = Derivation(
        "aggregate",
        "strictest",
        {"of": "category", "order": CATEGORIES, "unknown": "propagate"},
        (),
        (),
        unknown=("U",),
        bound="3",
        bound_fixed_by=("A",),
    )
    value = Value(None, Source("By hand"), Origin.DERIVED, derivation=trace)
    return ValueSet("by-hand", "1", {"category": value})


def width_requirement() -> tuple[Requirement, RequirementSet]:
    req = Requirement(
        "ADM-WIDTH",
        "threshold_admissibility",
        {"en": "The width is at most the limit"},
        Source("Regulation C", locator="art. 4"),
        parameters={"quantity": "width"},
        attributes={"limit": "width_limit"},
    )
    return req, RequirementSet((req,), PARAMETERS, (ALIAS_BOOK,))


def test_a_bound_that_fails_every_arc_is_not_applied_already() -> None:
    req, reqs = width_requirement()
    graph, data = parallel(Attribute.numeric("width_limit", [3.0, 2.5], unit="m"))
    group = Group("G", ((B, 1), (member("U"), 1)))
    values = resolve_values(
        [derive(group, {"width": Aggregation.max("width")}).values], reqs
    )
    undecided = "value of 'width' to be set: no value for U; at least 3.5 m (B)"
    report = check_inputs(reqs, graph, data, values)["ADM-WIDTH"]
    assert (report.expected, report.provable) == (S.NOT_APPLIED, False)
    assert report.reason == (
        f"{undecided}; data on 2 of the 2 arcs in scope, 2 fail at the bound"
    )
    check = verify_route((0,), reqs, graph, data, values)["ADM-WIDTH"]
    assert (check.status, check.reason) == (
        S.NOT_APPLIED,
        f"1 arcs violate it; {undecided}",
    )
    # On a flow too.
    flow = verify_flow([1, 0], reqs, FlowProblem(graph), data, values)["ADM-WIDTH"]
    assert (flow.status, flow.failing) == (S.NOT_APPLIED, (0,))
    # No known member: no bound, every arc in scope unknown.
    none = Group("N", ((member("U"), 1), (member("V"), 2)))
    values = resolve_values(
        [derive(none, {"width": Aggregation.max("width")}).values], reqs
    )
    effect = evaluate(req, graph, data, values)
    assert effect.reasons is not None
    assert effect.reasons.tolist() == [Reason.VALUE_TO_BE_SET] * 2
    check = verify_route((1,), reqs, graph, data, values)["ADM-WIDTH"]
    assert (check.status, check.reason) == (
        S.PARTIAL,
        (
            "1 arcs unknown; value of 'width' to be set: no value for U, V; no known "
            "input bounds it"
        ),
    )


def by_hand(
    name: str, rule: str, bound: float | str, *, order: object = CLASSES
) -> ResolvedValues:
    """A value of ``name`` to be set, with a trace built by hand: the
    envelope ``rule`` of A, bounded by ``bound``, U unknown."""
    trace = Derivation(
        "aggregate",
        rule,
        {"of": name, "order": order, "unknown": "propagate"},
        (),
        (),
        unknown=("U",),
        bound=bound,
        bound_fixed_by=("A",),
    )
    unit = "m" if name == "width" else None
    value = Value(None, Source("By hand"), Origin.DERIVED, unit=unit, derivation=trace)
    reqs = width_requirement()[1] if name == "width" else LOAD_CLASSES
    return resolve_values([ValueSet("G", "1", {name: value})], reqs)


def test_a_bound_is_read_with_the_type_and_the_order_of_its_pattern() -> None:
    req, _ = width_requirement()
    graph, data = parallel(Attribute.numeric("width_limit", [3.0], unit="m"))
    # A label bounds no width, a number no class: the types of a known value.
    with pytest.raises(TypeError, match="quantity must be a number"):
        evaluate(req, graph, data, by_hand("width", "strictest", "C50"))
    arcs, classes = parallel(
        Attribute.categorical("arc_class", ["C30", "C50"], ("C30", "C50"))
    )
    with pytest.raises(ValueError, match="class 3.5 is not one of"):
        evaluate(LOAD_CLASS, arcs, classes, by_hand("load_class", "max", 3.5))
    # The bound is a label of the order of its derivation, and every label
    # at least as strict is a class of the arcs.
    with pytest.raises(
        ValueError,
        match="the bound 'C90' of 'load_class' is not a label of the order of its "
        "derivation",
    ):
        evaluate(LOAD_CLASS, arcs, classes, by_hand("load_class", "strictest", "C90"))
    with pytest.raises(ValueError, match="class 'C70' is not one of"):
        evaluate(LOAD_CLASS, arcs, classes, by_hand("load_class", "strictest", "C50"))
    narrow = by_hand("load_class", "strictest", "C50", order=("C30", "C50"))
    # C50, the strictest label of the order: the value is C50 for certain.
    assert verdicts(LOAD_CLASS, arcs, classes, narrow) == [FAIL, PASS]
    # An order of the arcs reversed: no class fails every label the value
    # may take, and C30, the strictest class of the arcs, admits them all.
    reversed_ = ArcData(
        2, (Attribute.categorical("arc_class", ["C50", "C30"], ("C50", "C30")),)
    )
    loose = by_hand("load_class", "strictest", "C30", order=("C30", "C50"))
    assert verdicts(LOAD_CLASS, arcs, reversed_, loose) == [UNKNOWN, PASS]
    # A trace without a bound nor an order: nothing tells what the value
    # may be, every arc is unknown.
    blind = Derivation(
        "aggregate", "strictest", {"of": "load_class"}, (), (), unknown=("U",)
    )
    unset = Value(None, Source("By hand"), Origin.DERIVED, derivation=blind)
    values = resolve_values([ValueSet("G", "1", {"load_class": unset})], LOAD_CLASSES)
    assert verdicts(LOAD_CLASS, arcs, classes, values) == [UNKNOWN, UNKNOWN]


# An equipment in several packagings, in a life-cycle profile ---------------
#
#   a0 L01: 0 -> 1   a1 L02: 1 -> 2   a2 L03: 2 -> 1 (loop)
#   a3 L04: 1 -> 3   a4 L05: 2 -> 3   a5 L06: 3 -> 0 (return, 1..1)
#
# L02 is a transport, L03 a handling repeated in the loop. The worst case
# of the profile is its largest number of occurrences.

LIFE = (
    Parameter("transport_occurrences"),
    Parameter("handling_occurrences"),
    Parameter("one"),
)
SPEC = Rulebook(
    "spec", RulebookKind.CLIENT_SPECIFICATION, {"en": "Specification of use"}, "1"
)
SPEC_SRC = Source("Specification of use", rulebook="spec", edition="1")


def occurrences(
    id: str, maximum: str, link: str, minimum: str | None = None
) -> Requirement:
    bind = {"maximum": maximum} | ({} if minimum is None else {"minimum": minimum})
    return Requirement(
        id,
        "occurrence_bounds",
        {"en": f"The occurrences of {link} are within their bounds."},
        SPEC_SRC,
        parameters=bind,
        scope=frozenset({link}),
    )


PROFILE_REQS = RequirementSet(
    (
        occurrences("OC-TRANSPORT", "transport_occurrences", "L02"),
        occurrences("OC-HANDLING", "handling_occurrences", "L03"),
        occurrences("RETURN", "one", "L06", minimum="one"),
    ),
    LIFE,
    (SPEC,),
)
RETURN_ONCE = ValueSet("spec", "1", {"one": Value(1, SPEC_SRC, Origin.STATEMENT)})
LINK_DATA = ArcData(
    6, (Attribute.categorical("link", list(LINKS), LINKS),), element="link"
)


def packaging(id: str, **values: int | NA) -> Member:
    """A packaging of the equipment, a variant described by its sheet."""
    source = Source(f"Packaging sheet {id}", locator="table 2")
    return Member(
        id,
        (
            ValueSet(
                f"packaging-{id}",
                "1",
                {
                    k: Value(None, source, Origin.STATEMENT, not_applicable=x.reason)
                    if isinstance(x, NA)
                    else Value(x, source, Origin.STATEMENT)
                    for k, x in values.items()
                },
            ),
        ),
    )


VARIANTS = (
    packaging("crate", transport_occurrences=4, handling_occurrences=12),
    packaging(
        "container",
        transport_occurrences=2,
        handling_occurrences=NA("handled with its carrier"),
    ),
    packaging("pallet", transport_occurrences=6, handling_occurrences=8),
)


def worst_case(value_sets: list[ValueSet]) -> tuple[FlowSearch, ResolvedValues]:
    values = resolve_values([*value_sets, RETURN_ONCE], PROFILE_REQS)
    problem = FlowProblem(PROFILE, cost=[1, 1, 1, 1, 1, 0], sense="max")
    search = FlowSearch(
        PROFILE_REQS,
        problem,
        LINK_DATA,
        values,
        method="network_simplex",
        policy=UnknownPolicy.EXCLUDE,
    )
    return search, values


def test_the_envelope_of_the_packagings_bounds_the_profile() -> None:
    equipment = Group("equipment-E", tuple((v, 1) for v in VARIANTS))
    d = aggregate(
        equipment,
        {p.name: Aggregation.max(p.name) for p in LIFE[:2]},
        parameters=LIFE,
        unknown=OnUnknown.propagate(),
        edition="1",
    )
    search, values = worst_case([d.values])
    result = search.solve()
    assert result is not None
    assert (result.objective, result.flow) == (14, (1, 6, 6, 1, 0, 1))
    worst = result.objective
    assert worst is not None
    check = search.verify(result)
    assert set(check.statuses.values()) == {S.APPLIED}
    # A bound: the worst case of the envelope is at least that of every
    # packaging, each taken alone (the container has no handling bound of
    # its own: its requirement is not applicable).
    alone = {}
    for variant in VARIANTS:
        own, _ = worst_case([variant.sheets[0]])
        found = own.solve()
        assert found is not None
        assert found.objective is not None
        assert found.objective <= worst
        alone[variant.id] = found.objective
    assert alone == {"crate": 10, "container": 6, "pallet": 14}
    # The table cites the packaging that fixes each bound.
    rows = {r.id: r.to_dict() for r in requirement_table(check, PROFILE_REQS, values)}
    assert rows["OC-TRANSPORT"]["values"][0]["derivation"]["summary"] == (
        "max of 'transport_occurrences' over equipment-E: 6, fixed by pallet "
        "(Packaging sheet pallet (1), table 2)"
    )
    assert rows["OC-HANDLING"]["values"][0]["derivation"]["summary"] == (
        "max of 'handling_occurrences' over equipment-E: 12, fixed by crate "
        "(Packaging sheet crate (1), table 2); left out: container (not "
        "applicable: handled with its carrier)"
    )
    assert rows["RETURN"]["values"][0]["derivation"] is None
    json.dumps(list(rows.values()))


# What the table says of a derived value --------------------------------------


def said(value: Value) -> str:
    """The summary of a derived value in the table: the row of a
    requirement that reads it, whatever its verification."""
    req = Requirement(
        "R",
        "objective",
        {"en": "Requirement R"},
        Source("Regulation C"),
        parameters={"criterion": "probe"},
    )
    reqs = RequirementSet((req,), (Parameter("probe", unit=value.unit),))
    # A value without a rulebook takes that of its set.
    book, edition = value.source.rulebook or "hand", value.source.edition or "1"
    probe = ValueSet(book, edition, {"probe": value})
    values = resolve_values([probe], reqs)
    check = Verification((RequirementCheck("R", S.NOT_APPLIED, "not checked"),))
    (row,) = requirement_table(check, reqs, values)
    shown = row.to_dict()["values"][0]
    json.dumps(shown)
    summary = shown["derivation"]["summary"]
    assert isinstance(summary, str)
    return summary


FOUR = Group("G", ((A, 2), (B, 1), (C, 1), (D, 3)))
#: A pair spaced by 20 m, A 6 m long and B 12 m.
PAIR_GAP = plan("pair", gap=20.0)
GAP = Gap("gap", GapCount.BETWEEN)
U = member("U", mass=5.0)
MIXED = Group("M", ((A, 1), (B, 1), (U, 2)))
THRESHOLD = Value(
    3.0, Source("Regulation A", locator="art. 5"), Origin.RULEBOOK, unit="m"
)


@pytest.mark.parametrize(
    ("derived", "expected"),
    [
        (
            derive(FOUR, {"members": Aggregation.count()})["members"],
            "count of the members of G: 7, fixed by A, B, C, D",
        ),
        (
            derive(
                FOUR,
                {
                    "heavy": Aggregation.threshold_count(
                        "width", THRESHOLD, Comparison.AT_LEAST
                    )
                },
            )["heavy"],
            (
                "threshold_count of 'width' over G, at least 3 m: 5, fixed by B (Sheet "
                "sheet-B (1), p. 4), C (Sheet sheet-C (1), p. 4), D (Sheet sheet-D (1), "
                "p. 4)"
            ),
        ),
        (
            derive(MIXED, {"load_class": Aggregation.strictest("load_class", CLASSES)})[
                "load_class"
            ],
            (
                "strictest of 'load_class' over M: 'C70', fixed by B (Sheet sheet-B "
                "(1), p. 4); decided by B despite unknown values for U"
            ),
        ),
        (
            derive(MIXED, {"width": Aggregation.max("width")}, KNOWN_ONLY)["width"],
            (
                "max of 'width' over M: 3.5 m, fixed by B (Sheet sheet-B (1), p. 4); "
                "left out: U (unknown: the members without a value are towed)"
            ),
        ),
        (
            derive(MIXED, {"length": Aggregation.sum("length")})["length"],
            "sum of 'length' over M: to be set: no value of 'length' for U",
        ),
        (
            derive(
                Group("N", ((B, 1), (U, 1), (member("V"), 1))),
                {"width": Aggregation.max("width")},
            )["width"],
            (
                "max of 'width' over N: unknown, at least 3.5 m (fixed by B (Sheet "
                "sheet-B (1), p. 4)); 2 members without a value: U, V"
            ),
        ),
        (
            derive(
                Group.from_counts(
                    "Z", [(A, 2), (B, 0), (C, 1)], zero_counts=ZeroCount.DROP
                ).without("Z2", ["C"], reason="sent ahead"),
                {"width": Aggregation.max("width")},
            )["width"],
            (
                "max of 'width' over Z2: 2.5 m, fixed by A (Sheet sheet-A (1), p. 4); "
                "left out: B (count 0 in the table), C (excluded: sent ahead)"
            ),
        ),
        (
            classify(sheet("sheet-S", width=3.5))["category"],
            (
                "highest rank of mass, width: unknown, at least as strict as '2' "
                "(fixed by 'width' (3.5 m above 3 m, art. 3)); 1 input without a "
                "value: mass"
            ),
        ),
        (
            classify(sheet("sheet-S"))["category"],
            "highest rank of mass, width: to be set: no value for mass, width",
        ),
        (
            classify(sheet("sheet-S", width=2.0, mass=10.0))["category"],
            "highest rank of mass, width: '1', fixed by 'mass' (10 t), 'width' (2 m)",
        ),
        (
            classify(sheet("sheet-S", width=4.5))["category"],
            (
                "highest rank of mass, width: '3', fixed by 'width' (4.5 m above 4 m, "
                "art. 3); decided by width despite unknown values for mass"
            ),
        ),
        (
            classify(sheet("sheet-S", width=NA("a liquid bulk"), mass=30.0))[
                "category"
            ],
            (
                "highest rank of mass, width: '2', fixed by 'mass' (30 t above 20 t, "
                "art. 3); left out: width (not applicable: a liquid bulk)"
            ),
        ),
        (
            select(classify(sheet("sheet-S", width=3.5)))["speed_cap"],
            "selected by 'category': to be set: no value for category",
        ),
        (
            select(classify(sheet("sheet-S", width=3.5, mass=30.0)))["speed_cap"],
            (
                "selected by 'category': 60 km/h, for class '2', from 'speed_2' "
                "(Regulation C (1), art. 3)"
            ),
        ),
        (
            select(
                classify(sheet("sheet-S", width=3.5)),
                OnUnknown.assume({"category": chosen("3")}),
            )["speed_cap"],
            (
                "selected by 'category': 40 km/h, for class '3', from 'speed_3' "
                "(Regulation C (1), art. 3); assumed for category: '3' (no sheet: a "
                "planning choice)"
            ),
        ),
        (
            measure(Group("pair", ((A, 1), (B, 2)), values=PAIR_GAP), spacing=[GAP])[
                "column_length"
            ],
            (
                "column_length (geometric) of pair: 70 m, fixed by A (Sheet sheet-A "
                "(1), p. 4), B (Sheet sheet-B (1), p. 4), pair ('gap': Plan of pair "
                "(1), sec. 2)"
            ),
        ),
    ],
)
def test_the_table_says_how_each_value_is_derived(
    derived: Value, expected: str
) -> None:
    assert said(derived) == expected


def test_the_table_says_less_of_a_trace_built_by_hand() -> None:
    # A trace built by hand may lack the settings and the inputs that a
    # derivation of protee records: its summary says what it can.
    source = Source("By hand")
    width = Value(3.0, Source("Sheet S"), Origin.STATEMENT, unit="m")
    ranked = Derivation(
        "classify_by_thresholds",
        "highest_rank",
        {"kinds": frozenset({"b", "a"})},
        ("q", "width"),
        (DerivationInput("characteristic", "width", None, ValueState.KNOWN, width),),
    )
    value = Value("2", source, Origin.DERIVED, derivation=ranked)
    assert said(value) == (
        "highest rank of its characteristics: '2', fixed by 'q', 'width' (3 m)"
    )
    assert _value(value)["derivation"]["settings"] == {"kinds": ["a", "b"]}
    unset_q = Value(None, Source("Sheet S"), Origin.STATEMENT, unit="m")
    unranked = Derivation(
        "classify_by_thresholds",
        "highest_rank",
        {},
        ("q",),
        (DerivationInput("characteristic", "q", None, ValueState.UNKNOWN, unset_q),),
        unknown=("q",),
    )
    assert said(Value("2", source, Origin.DERIVED, derivation=unranked)) == (
        "highest rank of its characteristics: '2', fixed by 'q'"
    )
    chosen_ = Derivation("select_by_class", "table", {"by": "class"}, (), ())
    assert said(Value(5.0, source, Origin.DERIVED, unit="m", derivation=chosen_)) == (
        "selected by 'class': 5 m"
    )
    unset = Derivation("aggregate", "max", {"of": "w"}, (), ())
    assert said(Value(None, source, Origin.DERIVED, derivation=unset)) == (
        "max of 'w' over hand: to be set"
    )


# Certain passes, disagreements and records -----------------------------------


def test_an_arc_that_every_value_passes_passes_for_certain() -> None:
    # The width is to be set, at least 3.5 m (B): an arc without a limit
    # passes whatever it is; an arc of 3 m fails; one of 4 m is unknown.
    req, reqs = width_requirement()
    graph, data = parallel(
        Attribute.numeric("width_limit", [math.inf, 3.0, 4.0], unit="m")
    )
    group = Group("G", ((B, 1), (member("U"), 1)))
    values = resolve_values(
        [derive(group, {"width": Aggregation.max("width")}).values], reqs
    )
    effect = evaluate(req, graph, data, values)
    assert effect.verdict is not None
    assert effect.reasons is not None
    assert effect.verdict.tolist() == [PASS, FAIL, UNKNOWN]
    assert effect.reasons.tolist() == [
        Reason.SATISFIED,
        Reason.VIOLATED,
        Reason.VALUE_TO_BE_SET,
    ]
    report = check_inputs(reqs, graph, data, values)["ADM-WIDTH"]
    assert (report.expected, report.provable) == (S.APPLIED, True)
    assert report.reason == (
        "value of 'width' to be set: no value for U; at least 3.5 m (B); data on "
        "3 of the 3 arcs in scope, 1 fail at the bound, 1 pass whatever the value"
    )
    applied = verify_route((0,), reqs, graph, data, values)["ADM-WIDTH"]
    assert (applied.status, applied.reason) == (
        S.APPLIED,
        (
            "verified on 1 arcs; value of 'width' to be set: no value for U; at "
            "least 3.5 m (B)"
        ),
    )
    # Without a known member, a value may be any: the arc without a limit
    # still passes, the others are unknown.
    none = Group("N", ((member("U"), 1), (member("V"), 1)))
    values = resolve_values(
        [derive(none, {"width": Aggregation.max("width")}).values], reqs
    )
    assert verdicts(req, graph, data, values) == [PASS, UNKNOWN, UNKNOWN]
    # A minimum is at most its bound (a direction the code does not check
    # against the pattern): under a limit, an arc at least the bound passes.
    least = resolve_values(
        [derive(group, {"width": Aggregation.min("width")}).values], reqs
    )
    assert verdicts(req, graph, data, least) == [PASS, UNKNOWN, PASS]


@pytest.mark.parametrize("book", ["aa-plan", "zz-plan"])
def test_values_to_be_set_bounded_apart_disagree_whatever_their_names(
    book: str,
) -> None:
    # The depth of the column is to be set, at most 0.5 m (truck-b); a plan
    # leaves it to be set, without a bound. The bound bars a1: of the same
    # precedence, the two disagree, whatever the name of the plan.
    d = aggregate(COLUMN, ENVELOPE, parameters=FORD, unknown=PROPAGATE, edition="1")
    unset = Value(None, Source("Planning sheet"), Origin.PROVISIONAL, unit="m")
    plan_ = ValueSet(book, "1", {"fording_depth": unset})
    with pytest.raises(
        ValueError,
        match=re.escape(
            "parameter 'fording_depth': values "
            + (
                "[None, 'to be set, at most 0.5 m']"
                if book == "aa-plan"
                else "['to be set, at most 0.5 m', None]"
            )
            + " disagree with the same precedence"
        ),
    ):
        resolve_values([d.values, plan_], FORDS)
    # A precedence settles it.
    first = ValueSet(
        book,
        "1",
        {
            "fording_depth": Value(
                None,
                Source("Planning sheet"),
                Origin.PROVISIONAL,
                unit="m",
                precedence=1,
            )
        },
    )
    kept = resolve_values([d.values, first], FORDS).values["fording_depth"]
    assert kept.derivation is None
    # Two groups bounded apart disagree; bounded alike, or not at all,
    # they agree.
    tank = Group(
        "b-other", ((vehicle("tank", fording_depth=0.2), 1), (vehicle("x"), 1))
    )
    other = aggregate(
        tank,
        {"fording_depth": Aggregation.min("fording_depth")},
        parameters=FORD,
        unknown=PROPAGATE,
        edition="1",
    )
    with pytest.raises(ValueError, match="disagree with the same precedence"):
        resolve_values([d.values, other.values], FORDS)
    alike_ = Group(
        "b-alike", ((vehicle("truck-z", fording_depth=0.5), 1), (vehicle("y"), 1))
    )
    same = aggregate(
        alike_,
        {"fording_depth": Aggregation.min("fording_depth")},
        parameters=FORD,
        unknown=PROPAGATE,
        edition="1",
    )
    kept = resolve_values([d.values, same.values], FORDS).values["fording_depth"]
    assert kept.source.rulebook == "b-alike"


SPEED = Requirement(
    "SPEED",
    "speed_cap",
    {"en": "The speed is capped by the category."},
    Source("Regulation C", locator="art. 14"),
    parameters={"maximum": "speed_cap"},
    attributes={"length": "km", "speed": "free_speed"},
)
SPEED_REQS = RequirementSet((SPEED,), VOCABULARY, (ALIAS_BOOK,))


def speed_cap(category: Derived, edition: str, precedence: int) -> Derived:
    """The speed cap a category selects, in a rulebook of speeds."""
    return select_by_class(
        category,
        by="category",
        table={"1": "speed_2", "2": "speed_2", "3": "speed_3"},
        values=REGULATION_SPEEDS,
        output="speed_cap",
        parameters=VOCABULARY,
        unknown=PROPAGATE,
        rulebook="speeds",
        edition=edition,
        precedence=precedence,
    )


REGULATION_SPEEDS = regulation(speed_2=60.0, speed_3=40.0)


def test_the_provenance_walks_the_chain_of_a_value_set_aside() -> None:
    # Two editions of the same selection, both of class 2: by the width in
    # the one retained, by the mass in the one set aside. Their entries are
    # alike; the derivations they read are not, and both are recorded.
    by_width = classify(sheet("sheet-S", width=3.5, mass=10.0))
    by_mass = classify(sheet("sheet-S", width=2.0, mass=30.0))
    values = resolve_values(
        [speed_cap(by_width, "1", 1).values, speed_cap(by_mass, "2", 0).values],
        SPEED_REQS,
    )
    record = provenance(
        "dijkstra", {}, inputs={}, requirements=SPEED_REQS, values=values, result=()
    )
    assert record.derivations == (
        ("category", "classes", "classify_by_thresholds", "highest_rank", ("mass",)),
        ("category", "classes", "classify_by_thresholds", "highest_rank", ("width",)),
        ("speed_cap", "speeds", "select_by_class", "table", ("category",)),
    )


def test_the_results_of_the_requirement_model_pickle() -> None:
    d, values, search = crossing(PROPAGATE, UnknownPolicy.ADMIT_AND_COUNT)
    check = search.verify(search.solve())
    rows = requirement_table(
        check,
        FORDS,
        values,
        view=search.view(),
        impacts={"FORD-DEPTH": search.impact("FORD-DEPTH")},
    )
    report = check_inputs(FORDS, CROSSING, CROSSING_DATA, values)
    for result in (d, values, check, report, *rows):
        again = pickle.loads(pickle.dumps(result))
        assert again == result
    again_rows = pickle.loads(pickle.dumps(rows))
    assert [r.to_dict() for r in again_rows] == [r.to_dict() for r in rows]
    assert pickle.loads(pickle.dumps(report))["FORD-DEPTH"] == report["FORD-DEPTH"]
    assert dict(pickle.loads(pickle.dumps(check.statuses))) == dict(check.statuses)


def test_numpy_numbers_are_read_as_the_python_numbers_of_their_value() -> None:
    # Values taken from arrays: a NumPy float or integer is the Python
    # number of the same value, for every derivation.
    def described(id: str, **values: object) -> Member:
        source = Source(f"Sheet {id}", locator="p. 4")
        units = {"width": "m", "mass": "t", "length": "m", "speed": "km/h"}
        return Member(
            id,
            (
                ValueSet(
                    f"sheet-{id}",
                    "1",
                    {
                        k: Value(x, source, Origin.STATEMENT, unit=units[k])  # type: ignore[arg-type]
                        for k, x in values.items()
                    },
                ),
            ),
        )

    with_numpy = Group(
        "G",
        (
            (described("A", width=np.float64(2.5), length=np.int64(6)), 2),
            (described("B", width=np.float32(3.5), length=np.int64(12)), 1),
            (described("U"), 1),
        ),
    )
    plain = Group(
        "G",
        (
            (described("A", width=2.5, length=6), 2),
            (described("B", width=3.5, length=12), 1),
            (described("U"), 1),
        ),
    )
    limit = Value(np.float64(3.0), Source("Regulation A"), Origin.RULEBOOK, unit="m")
    rules = {
        "width": Aggregation.max("width"),
        "length": Aggregation.sum("length"),
        "heavy": Aggregation.threshold_count("width", limit, Comparison.AT_LEAST),
    }
    assumed = OnUnknown.assume(
        {
            "width": chosen(np.float64(3.0), "m"),
            "length": chosen(np.int64(8), "m"),  # type: ignore[arg-type]
        }
    )
    envelope = derive(with_numpy, rules, assumed)
    assert envelope == derive(plain, rules, assumed)
    assert (envelope["width"].value, envelope["length"].value) == (3.5, 32)
    assert type(envelope["length"].value) is int
    # A classification and a selection, thresholds and speeds from arrays.
    limits = regulation(
        width_1=np.float64(3.0),
        width_2=np.float64(4.0),
        mass_1=np.float64(20.0),
        mass_2=np.float64(40.0),
        speed_2=np.float64(60.0),
        speed_3=np.float64(40.0),
    )
    subject = sheet("sheet-S", width=np.float64(3.5), mass=np.float32(30.0))  # type: ignore[arg-type]
    category = classify(subject, thresholds=limits)
    assert category == classify(sheet("sheet-S", width=3.5, mass=30.0))
    assert select(category, values=limits) == select(category)
    # A column, its lengths and its gap from arrays.
    gaps = plan("pair", gap=np.float64(20.0))
    pair = Group(
        "pair",
        (
            (described("A", length=np.int64(6)), 1),
            (described("B", length=np.float64(12.0)), 2),
        ),
        values=gaps,
    )
    length = measure(pair, spacing=[GAP])["column_length"]
    assert length.value == 70.0
    plain_pair = Group(
        "pair",
        ((described("A", length=6), 1), (described("B", length=12.0), 2)),
        values=plan("pair", gap=20.0),
    )
    assert length == measure(plain_pair, spacing=[GAP])["column_length"]


def _wide(id: str, x: float | None) -> Member:
    """A member whose width is stated in cm, or unknown."""
    source = Source(f"Sheet {id}")
    sheet_ = (
        {} if x is None else {"width": Value(x, source, Origin.STATEMENT, unit="cm")}
    )
    return Member(id, (ValueSet(f"sheet-{id}", "1", sheet_),))


def _to_be_set(
    parameter: str, rule: str, bound: float | str, **settings: object
) -> Member:
    """A member whose value is to be set by a trace built by hand."""
    trace = Derivation(
        "aggregate",
        rule,
        {"of": parameter, **settings},
        (),
        (),
        unknown=("U",),
        bound=bound,
        bound_fixed_by=("A",),
    )
    unit = "m" if parameter == "width" else None
    value = Value(None, Source("By hand"), Origin.DERIVED, unit=unit, derivation=trace)
    return Member("H", (ValueSet("hand", "1", {parameter: value}),))


def test_an_envelope_reads_the_bound_of_a_partial_envelope() -> None:
    # A sub-group measured in cm: B 350 cm, U unknown, at least 350 cm. The
    # maximum of it and of C, 3 m, is at least 3.5 m, bounded by the
    # sub-group, which stays unknown.
    inner = aggregate(
        Group("S", ((_wide("B", 350), 1), (_wide("U", None), 1))),
        {"width": Aggregation.max("width")},
        parameters=[Parameter("width", unit="cm")],
        unknown=PROPAGATE,
        edition="1",
    )
    trace = inner["width"].derivation
    assert trace is not None
    assert trace.bound == 350
    column = Group("G", ((Member("S", (inner.values,)), 1), (C, 1)))
    widest = derive(column, {"width": Aggregation.max("width")})["width"]
    trace = widest.derivation
    assert trace is not None
    assert (widest.value, trace.bound, trace.bound_fixed_by, trace.unknown) == (
        None,
        3.5,
        ("S",),
        ("S",),
    )
    # The bound of S, read in cm, is converted, and the conversion recorded.
    assert trace.conversions == (
        Conversion("S", "width", 350, "cm", 3.5, "m", "1/100"),
    )
    # A classification reads it too, and records it.
    wide = aggregate(
        Group("S", ((_wide("B", 450), 1), (_wide("U", None), 1))),
        {"width": Aggregation.max("width")},
        parameters=[Parameter("width", unit="cm")],
        unknown=PROPAGATE,
        edition="1",
    )
    category = classify(wide, characteristics=[WIDTH])["category"]
    assert category.value == "3"
    assert category.derivation is not None
    assert category.derivation.conversions == (
        Conversion(None, "width", 450, "cm", 4.5, "m", "1/100"),
    )
    # At most nothing: a minimum is bounded by C alone.
    least = derive(column, {"width": Aggregation.min("width")})["width"]
    assert least.derivation is not None
    assert (least.derivation.bound, least.derivation.bound_fixed_by) == (3.0, ("C",))
    # The same unit needs no conversion.
    same = Group("G", ((_to_be_set("width", "max", 4.0), 1), (C, 1)))
    trace = derive(same, {"width": Aggregation.max("width")})["width"].derivation
    assert trace is not None
    assert (trace.bound, trace.bound_fixed_by) == (4.0, ("H",))
    # The bound of a rule that bounds nothing is not read.
    summed = Group("G", ((_to_be_set("width", "sum", 9.0), 1), (C, 1)))
    trace = derive(summed, {"width": Aggregation.max("width")})["width"].derivation
    assert trace is not None
    assert (trace.bound, trace.bound_fixed_by) == (3.0, ("C",))


def test_a_bound_that_does_not_fit_its_derivation_is_refused() -> None:
    labelled = Group("G", ((_to_be_set("width", "max", "C50"), 1), (C, 1)))
    with pytest.raises(
        TypeError,
        match=re.escape(
            "member 'H': 'width': the bound of a max is a number, got 'C50'"
        ),
    ):
        derive(labelled, {"width": Aggregation.max("width")})
    outside = Group(
        "G", ((_to_be_set("load_class", "strictest", "C90", order=CLASSES), 1), (C, 1))
    )
    with pytest.raises(
        ValueError,
        match=re.escape(
            "member 'H': 'load_class': the bound 'C90' is not a label of the order "
            "of its derivation"
        ),
    ):
        derive(outside, {"load_class": Aggregation.strictest("load_class", CLASSES)})


# Agreement of values to be set, and assumptions against a bound ----------------


def _renamed(values: ValueSet, book: str) -> ValueSet:
    """A value set under another rulebook, its values with it."""
    return ValueSet(
        book,
        values.edition,
        {
            k: replace(v, source=replace(v.source, rulebook=book))
            for k, v in values.values.items()
        },
    )


def _depth_without_bound() -> ValueSet:
    """The depth of a group whose only member is unknown: an envelope to be
    set, without a bound."""
    nobody = Group("g", ((vehicle("z"), 1),))
    rules = {"fording_depth": Aggregation.min("fording_depth")}
    return aggregate(
        nobody, rules, parameters=FORD, unknown=PROPAGATE, edition="1"
    ).values


def _depth_to_be_set() -> ValueSet:
    """A depth left to be set by a plan: no envelope."""
    unset = Value(None, Source("Planning sheet"), Origin.PROVISIONAL, unit="m")
    return ValueSet("plan", "1", {"fording_depth": unset})


def _strictest_load(order: tuple[str, ...]) -> ValueSet:
    """The load class of a group of C50 and an unknown member, strictest in
    ``order``: to be set, at least as strict as C50."""
    group = Group("g", ((member("A", load_class="C50"), 1), (member("U"), 1)))
    return derive(
        group, {"load_class": Aggregation.strictest("load_class", order)}
    ).values


def _classified() -> ValueSet:
    """A category to be set, at least as strict as '2', of the classes 1 to
    3."""
    return classify(sheet("sheet-S", width=3.5)).values


def _strictest_category(order: tuple[str, ...]) -> ValueSet:
    """A category to be set, at least as strict as '2', strictest in
    ``order``."""
    stated = ValueSet(
        "sheet-A", "1", {"category": Value("2", Source("Sheet A"), Origin.STATEMENT)}
    )
    group = Group("g", ((Member("A", (stated,)), 1), (Member("U"), 1)))
    rules = {"category": Aggregation.strictest("category", order)}
    return aggregate(
        group, rules, parameters=VOCABULARY, unknown=PROPAGATE, edition="1"
    ).values


AGREEMENTS = [
    pytest.param(
        _depth_without_bound, _depth_to_be_set, FORDS, False, id="envelope-vs-plain"
    ),
    pytest.param(
        _depth_without_bound, _depth_without_bound, FORDS, True, id="two-envelopes"
    ),
    pytest.param(
        lambda: _strictest_load(CLASSES),
        lambda: _strictest_load((*CLASSES, "C90")),
        LOAD_CLASSES,
        False,
        id="strictest-on-two-scales",
    ),
    pytest.param(
        _classified,
        lambda: _strictest_category((*CATEGORIES, "4")),
        CATEGORY_REQS,
        False,
        id="classification-vs-strictest-on-a-wider-scale",
    ),
    pytest.param(
        _classified,
        lambda: _strictest_category(CATEGORIES),
        CATEGORY_REQS,
        True,
        id="classification-vs-strictest-on-its-scale",
    ),
]


@pytest.mark.parametrize("names", [("a-left", "b-right"), ("b-left", "a-right")])
@pytest.mark.parametrize(("left", "right", "reqs", "agree"), AGREEMENTS)
def test_values_to_be_set_agree_when_they_allow_the_same_values(
    left: Callable[[], ValueSet],
    right: Callable[[], ValueSet],
    reqs: RequirementSet,
    agree: bool,
    names: tuple[str, str],
) -> None:
    # Two values to be set of the same precedence agree when they evaluate
    # alike: the same interval of numbers, the same labels, or no envelope
    # at all. Otherwise the name of a rulebook would decide which applies.
    sets = [_renamed(left(), names[0]), _renamed(right(), names[1])]
    if not agree:
        with pytest.raises(ValueError, match="disagree with the same precedence"):
            resolve_values(sets, reqs)
        return
    (kept,) = resolve_values(sets, reqs).values.values()
    assert kept.source.rulebook is not None
    assert kept.source.rulebook.startswith("a-")


def test_a_disagreement_says_what_each_value_may_be() -> None:
    sets = [
        _renamed(_strictest_load(CLASSES), "a-short"),
        _renamed(_strictest_load((*CLASSES, "C90")), "b-long"),
    ]
    with pytest.raises(
        ValueError,
        match=re.escape(
            "parameter 'load_class': values [\"to be set, at least as strict as "
            "'C50': one of ['C50', 'C70']\", \"to be set, at least as strict as "
            "'C50': one of ['C50', 'C70', 'C90']\"] disagree"
        ),
    ):
        resolve_values(sets, LOAD_CLASSES)
    sets = [_renamed(_depth_without_bound(), "a-env"), _depth_to_be_set()]
    with pytest.raises(
        ValueError,
        match=re.escape("values ['to be set by min, without a bound', None] disagree"),
    ):
        resolve_values(sets, FORDS)


def test_an_assumed_value_respects_the_bound_of_an_input_to_be_set() -> None:
    # G1 is at least 4.5 m wide, fixed by A, its member U unknown. Read as a
    # member of G2, it may not be assumed 2.5 m wide: that would pass the
    # arcs A fails for certain.
    g1 = derive(
        Group("G1", ((member("A", width=4.5), 1), (member("U"), 1))),
        {"width": Aggregation.max("width")},
    ).values
    g2 = Group("G2", ((Member("G1", (g1,)), 1), (member("B", width=3.0), 1)))
    narrow = OnUnknown.assume({"width": chosen(2.5, "m")})
    contradicts = (
        "is to be set, at least 4.5 m (fixed by A): the value assumed for 'width', "
        "2.5 m, contradicts its bound"
    )
    with pytest.raises(
        ValueError, match=re.escape(f"member 'G1': 'width' {contradicts}")
    ):
        derive(g2, {"width": Aggregation.max("width")}, narrow)
    # A value the bound allows is assumed, as for any input.
    broad = OnUnknown.assume({"width": chosen(500, "cm")})
    width = derive(g2, {"width": Aggregation.max("width")}, broad)["width"]
    assert width.derivation is not None
    assert (width.value, width.derivation.fixed_by) == (5.0, ("G1",))
    # The same for a classification of G1, and for a selection by its class.
    envelope = derive(
        Group("G1", ((member("A", width=4.5), 1), (member("U"), 1))),
        {"width": Aggregation.max("width")},
    )
    with pytest.raises(ValueError, match=re.escape(f"subject: 'width' {contradicts}")):
        classify(envelope, narrow, characteristics=[WIDTH])
    assert classify(envelope, broad, characteristics=[WIDTH])["category"].value == "3"
    category = classify(sheet("sheet-S", width=3.5))
    with pytest.raises(
        ValueError,
        match=re.escape(
            "subject: 'category' is to be set, at least as strict as '2' (fixed by "
            "width): the value assumed for 'category', '1', contradicts its bound"
        ),
    ):
        select(category, OnUnknown.assume({"category": chosen("1")}))
    speed = select(category, OnUnknown.assume({"category": chosen("3")}))
    assert speed["speed_cap"].value == 40.0
    # At most a bound: the depth of the column, at most 0.5 m (truck-b).
    column = aggregate(
        COLUMN, ENVELOPE, parameters=FORD, unknown=PROPAGATE, edition="1"
    )
    group = Group("G", ((Member("column", (column.values,)), 1),))
    rules = {"fording_depth": Aggregation.min("fording_depth")}
    deep = OnUnknown.assume(
        {
            "fording_depth": Value(
                0.6,
                Source("Planning note"),
                Origin.CHOICE,
                unit="m",
                justification="a guess",
            )
        }
    )
    with pytest.raises(
        ValueError,
        match=re.escape(
            "member 'column': 'fording_depth' is to be set, at most 0.5 m (fixed by "
            "truck-b): the value assumed for 'fording_depth', 0.6 m, contradicts"
        ),
    ):
        aggregate(group, rules, parameters=FORD, unknown=deep, edition="1")
