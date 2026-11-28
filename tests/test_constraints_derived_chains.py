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
    verify_flow,
    verify_route,
)
from protee.constraints._table import _value
from protee.flow import FlowProblem
from protee.graph import Digraph

S = RequirementStatus
FAIL, UNKNOWN = int(Verdict.FAIL), int(Verdict.UNKNOWN)

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


def kleene(columns: list[list[int]]) -> list[int] | None:
    """The Kleene conjunction of the verdicts of several members, ``None``
    without a member."""
    if not columns:
        return None
    return [min(column) for column in zip(*columns, strict=True)]


def partial(known: list[int] | None, m: int) -> list[int]:
    """The verdicts of an envelope to be set: a failure of a known member
    is certain, any other arc unknown."""
    if known is None:
        return [UNKNOWN] * m
    return [FAIL if v == FAIL else UNKNOWN for v in known]


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
    # Every member known: the verdict of the minimum is the conjunction of
    # the verdicts of the members; some unknown: a known member that fails
    # an arc fails it for certain, the others are unknown.
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
    d = aggregate(
        group,
        {"fording_depth": Aggregation.min("fording_depth")},
        parameters=FORD,
        unknown=PROPAGATE,
        edition="1",
    )
    found = verdicts(req, graph, data, resolve_values([d.values], reqs))
    conjunction = kleene(each)
    if len(known) == len(depths):
        assert found == conjunction
    else:
        assert found == partial(conjunction, len(waters))


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
    known = [x for x in labels if x is not None]
    each = [
        verdicts(LOAD_CLASS, graph, data, label_values("load_class", x)) for x in known
    ]
    d = derive(group, {"load_class": Aggregation.strictest("load_class", CLASSES)})
    found = verdicts(LOAD_CLASS, graph, data, resolve_values([d.values], LOAD_CLASSES))
    conjunction = kleene(each)
    if d["load_class"].value is not None:
        # Every member known, or the strictest label reached (DD9).
        assert found == conjunction
    else:
        assert found == partial(conjunction, len(arcs))


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
    # of each known one alone gives its verdicts.
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
    d = classify(sheet("sheet-S", **given_))
    found = verdicts(CATEGORY, graph, data, resolve_values([d.values], CATEGORY_REQS))
    conjunction = kleene(each)
    if d["category"].value is not None:
        assert found == conjunction
    else:
        assert found == partial(conjunction, len(arcs))


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
    assert verdicts(LOAD_CLASS, arcs, classes, narrow) == [FAIL, UNKNOWN]
    # An order of the arcs reversed: no class fails every label the value
    # may take.
    reversed_ = ArcData(
        2, (Attribute.categorical("arc_class", ["C50", "C30"], ("C50", "C30")),)
    )
    loose = by_hand("load_class", "strictest", "C30", order=("C30", "C50"))
    assert verdicts(LOAD_CLASS, arcs, reversed_, loose) == [UNKNOWN, UNKNOWN]


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
                "(1), p. 4), B (Sheet sheet-B (1), p. 4), pair"
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
    chosen_ = Derivation("select_by_class", "table", {"by": "class"}, (), ())
    assert said(Value(5.0, source, Origin.DERIVED, unit="m", derivation=chosen_)) == (
        "selected by 'class': 5 m"
    )
    unset = Derivation("aggregate", "max", {"of": "w"}, (), ())
    assert said(Value(None, source, Origin.DERIVED, derivation=unset)) == (
        "max of 'w' over hand: to be set"
    )
