# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""aggregate: oracles computed by hand, the policies for the unknown,
values not applicable, and properties (order, monotonicity, exactness of
the envelope)."""

from __future__ import annotations

import copy
import math
import pickle
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from fractions import Fraction

import numpy as np
import pytest
from constraints_cases import PROFILE, REG, SRC, profile, requirement
from derive_cases import (
    ALIAS_BOOK,
    CLASSES,
    COLUMN,
    KNOWN_ONLY,
    NA,
    PAIR,
    PARAMETERS,
    PROPAGATE,
    A,
    B,
    C,
    D,
    Given,
    chosen,
    derive,
    member,
    sheet,
)
from hypothesis import given
from hypothesis import strategies as st

from protee.constraints import (
    AggregateKind,
    Aggregation,
    ArcData,
    Assumption,
    Attribute,
    Comparison,
    Derived,
    Group,
    LeftOut,
    LeftOutCause,
    Member,
    OnUnknown,
    Origin,
    Parameter,
    Requirement,
    RequirementSet,
    Source,
    Tally,
    UnknownRule,
    Value,
    ValueSet,
    ValueState,
    ZeroCount,
    aggregate,
    check_inputs,
    evaluate,
    fingerprint,
    resolve_values,
)
from protee.graph import Digraph

MAX = Aggregation.max
MIN = Aggregation.min

#: The four members of the oracles, with counts 2, 1, 1, 3.
FOUR = Group("G", ((A, 2), (B, 1), (C, 1), (D, 3)))

#: A, B, C known; U without width and class, counted 3 times.
UNKNOWN_WIDTH = member("U", mass=5.0, speed=40.0, length=4.0)
MIXED = Group("M", ((A, 2), (B, 1), (C, 1), (UNKNOWN_WIDTH, 3)))

WIDTH_REQ = Requirement(
    "ADM-WIDTH",
    "threshold_admissibility",
    {"en": "The width is at most the limit"},
    SRC,
    parameters={"quantity": "width"},
    attributes={"limit": "width_limit"},
)
WIDTH_REQS = RequirementSet((WIDTH_REQ,), PARAMETERS, (REG, ALIAS_BOOK))


def mass(x: float, unit: str = "t") -> Value:
    """A threshold of a regulation."""
    return Value(
        x, Source("Regulation A", locator="art. 3"), Origin.RULEBOOK, unit=unit
    )


def arcs(limits: Sequence[float | None]) -> tuple[Digraph, ArcData]:
    """Parallel arcs with these width limits (``None`` unknown)."""
    graph = Digraph.from_arcs(2, [(0, 1)] * len(limits))
    data = ArcData(len(limits), (Attribute.numeric("width_limit", limits, unit="m"),))
    return graph, data


# Oracles by hand -----------------------------------------------------------


def test_max_and_min_cite_every_member_that_reaches_the_extreme() -> None:
    d = derive(FOUR, {"width": MAX("width"), "speed": MIN("speed")})
    width = d["width"]
    assert width.value == 3.5
    assert width.origin is Origin.DERIVED
    assert width.unit == "m"
    assert (width.source.document, width.source.rulebook, width.source.edition) == (
        "aggregate of G",
        "G",
        "1",
    )
    trace = width.derivation
    assert trace is not None
    assert (trace.name, trace.rule) == ("aggregate", "max")
    assert trace.fixed_by == ("B", "D")  # ties all cited, sorted
    assert trace.settings == {"of": "width", "unknown": "propagate"}
    assert [(i.holder, i.instances, i.state) for i in trace.inputs] == [
        ("A", 2, ValueState.KNOWN),
        ("B", 1, ValueState.KNOWN),
        ("C", 1, ValueState.KNOWN),
        ("D", 3, ValueState.KNOWN),
    ]
    # Every input keeps its source: the sheet of its member.
    b = trace.inputs[1].value
    assert b == B.sheets[0].values["width"]
    assert b is not None
    assert b.source.rulebook == "sheet-B"
    speed = d["speed"].derivation
    assert speed is not None
    assert (d["speed"].value, speed.fixed_by) == (50.0, ("B",))
    assert d.unknown == {"width": Tally(), "speed": Tally()}
    assert d.values.rulebook == "G"
    # A single member: the rule applies as usual.
    one = derive(Group("one", ((C, 4),)), {"width": MAX("width")})
    assert one["width"].value == 3.0
    assert one["width"].derivation is not None
    assert one["width"].derivation.fixed_by == ("C",)


def test_strictest_takes_the_label_of_highest_rank() -> None:
    rule = Aggregation.strictest("load_class", CLASSES)
    d = derive(FOUR, {"load_class": rule})
    trace = d["load_class"].derivation
    assert trace is not None
    assert d["load_class"].value == "C70"
    assert d["load_class"].unit is None
    assert trace.fixed_by == ("B",)
    assert trace.settings["order"] == CLASSES
    low = derive(Group("low", ((A, 1), (C, 1), (D, 1))), {"load_class": rule})
    assert low["load_class"].value == "C50"
    odd = Group("odd", ((member("Z", load_class="C99"), 1), (A, 1)))
    with pytest.raises(
        ValueError,
        match=re.escape("member 'Z': 'load_class' is 'C99', not one of the order"),
    ):
        derive(odd, {"load_class": rule})
    number = Group("number", ((member("N", load_class=3.0), 1),))
    with pytest.raises(ValueError, match="'load_class' is 3.0, not one of"):
        derive(number, {"load_class": rule})


def test_sum_count_and_mean_weight_by_the_counts() -> None:
    d = derive(
        COLUMN,
        {
            "mass": Aggregation.sum("mass"),
            "members": Aggregation.count(),
            "length": Aggregation.mean("length"),
        },
    )
    # A 6 times, B 3 times, C once.
    assert d["mass"].value == 6 * 12.0 + 3 * 30.0 + 20.0
    assert isinstance(d["mass"].value, float)
    assert d["members"].value == 10
    assert d["members"].unit is None
    assert d["length"].value == (6 * 6.0 + 3 * 12.0 + 8.0) / 10
    count = d["members"].derivation
    assert count is not None
    assert count.fixed_by == ("A", "B", "C")
    assert [(i.role, i.holder, i.instances, i.value) for i in count.inputs] == [
        ("count", "A", 6, None),
        ("count", "B", 3, None),
        ("count", "C", 1, None),
    ]
    # Integers only: an integer sum.
    ints = Group("ints", ((member("I", mass=3), 2), (member("J", mass=4), 1)))
    total = derive(ints, {"mass": Aggregation.sum("mass")})["mass"].value
    assert total == 10
    assert isinstance(total, int)


def test_sum_and_mean_are_exact() -> None:
    pair = Group("P", ((member("X", length=0.1), 1), (member("Y", length=0.2), 1)))
    assert 0.1 + 0.2 != 0.3
    assert derive(pair, {"length": Aggregation.sum("length")})["length"].value == 0.3
    g = Group("G", ((member("X", length=0.1), 1), (member("Y", length=0.2), 2)))
    assert derive(g, {"length": Aggregation.sum("length")})["length"].value == 0.5
    mean = derive(g, {"length": Aggregation.mean("length")})["length"].value
    assert mean == float((Fraction("0.1") + 2 * Fraction("0.2")) / 3)
    # The same exact sum whatever the order of the terms.
    values = [1e16, 1.0, -1e16, 0.1]
    group = Group(
        "S", tuple((member(f"m{k}", length=x), 1) for k, x in enumerate(values))
    )
    assert derive(group, {"length": Aggregation.sum("length")})["length"].value == 1.1


@pytest.mark.parametrize(
    ("comparison", "counted", "count"),
    [
        (Comparison.ABOVE, ("B",), 1),
        (Comparison.AT_LEAST, ("B", "C"), 2),
        (Comparison.BELOW, ("A", "D"), 5),
        (Comparison.AT_MOST, ("A", "C", "D"), 6),
    ],
)
def test_threshold_count_decides_equality_by_its_comparison(
    comparison: Comparison, counted: tuple[str, ...], count: int
) -> None:
    # C weighs exactly the threshold, 20 t.
    threshold = mass(20)
    rule = Aggregation.threshold_count("mass", threshold, comparison)
    d = derive(FOUR, {"heavy": rule})
    assert d["heavy"].value == count
    trace = d["heavy"].derivation
    assert trace is not None
    assert trace.fixed_by == counted
    assert trace.settings["comparison"] == comparison.value
    (limit,) = [i for i in trace.inputs if i.role == "threshold"]
    assert (limit.holder, limit.parameter, limit.value) == (None, "mass", threshold)


def test_threshold_count_of_none_counts_zero() -> None:
    rule = Aggregation.threshold_count("mass", mass(100.0), Comparison.AT_LEAST)
    d = derive(FOUR, {"heavy": rule})
    assert d["heavy"].value == 0
    assert d["heavy"].derivation is not None
    assert d["heavy"].derivation.fixed_by == ()


def test_infinity_is_a_known_value() -> None:
    free = member("F", width=math.inf, length=math.inf)
    g = Group("G", ((A, 1), (free, 2)))
    d = derive(
        g,
        {
            "width": MAX("width"),
            "length": Aggregation.sum("length"),
            "mass": Aggregation.sum("mass"),
        },
        unknown=OnUnknown.assume({"mass": chosen(0.0, "t")}),
    )
    assert d["width"].value == math.inf
    assert d["width"].derivation is not None
    assert d["width"].derivation.fixed_by == ("F",)
    assert d["length"].value == math.inf
    assert d["mass"].value == 12.0
    mean = derive(g, {"length": Aggregation.mean("length")})
    assert mean["length"].value == math.inf
    low = Group("L", ((member("N", length=-math.inf), 1), (A, 1)))
    total = derive(low, {"length": Aggregation.sum("length")})["length"].value
    assert total == -math.inf
    both = Group("B", ((free, 1), (member("N", length=-math.inf), 1)))
    with pytest.raises(
        ValueError,
        match=re.escape("sum of 'length': sum of +inf and -inf has no value"),
    ):
        derive(both, {"length": Aggregation.sum("length")})


def test_nested_groups_equal_their_flattened_group() -> None:
    rules = {
        "width": MAX("width"),
        "speed": MIN("speed"),
        "load_class": Aggregation.strictest("load_class", CLASSES),
        "mass": Aggregation.sum("mass"),
        "members": Aggregation.count(),
        "length": Aggregation.mean("length"),
    }
    flat = Group("column", COLUMN.flatten())
    assert derive(COLUMN, rules) == derive(flat, rules)
    # A member in two sub-groups: one identifier, multiplicities summed.
    twice = Group("T", ((PAIR, 1), (Group("S", ((A, 1),)), 2)))
    d = derive(twice, {"members": Aggregation.count(), "mass": Aggregation.sum("mass")})
    assert d["members"].value == 2 + 1 + 2
    assert d["mass"].value == 4 * 12.0 + 30.0


def test_members_left_out_of_the_group_are_recorded_in_each_value() -> None:
    table = [(A, 2), (B, 0), (C, 1)]
    g = Group.from_counts("G", table, zero_counts=ZeroCount.DROP).without(
        "G2", ["C"], reason="crosses apart"
    )
    d = derive(g, {"width": MAX("width"), "members": Aggregation.count()})
    expected = (
        LeftOut("B", LeftOutCause.ZERO_COUNT, "count 0 in the table", 0),
        LeftOut("C", LeftOutCause.EXCLUDED, "crosses apart", 1),
    )
    for name in ("width", "members"):
        trace = d[name].derivation
        assert trace is not None
        assert trace.left_out == expected
        assert d.left_out[name] == Tally(("B", "C"), 1)
    assert d["members"].value == 2


# Values not applicable -----------------------------------------------------


@pytest.mark.parametrize(
    "policy",
    [PROPAGATE, KNOWN_ONLY, OnUnknown.assume({"width": chosen(9.0, "m")})],
    ids=["propagate", "known_only", "assume"],
)
def test_a_member_not_applicable_is_left_out_under_every_policy(
    policy: OnUnknown,
) -> None:
    carried = member("K", width=NA("carried by B"))
    g = Group("G", ((A, 1), (B, 1), (carried, 2)))
    d = derive(g, {"width": MAX("width")}, policy)
    assert d["width"].value == 3.5
    assert d.unknown["width"] == Tally()
    assert d.left_out["width"] == Tally(("K",), 2)
    trace = d["width"].derivation
    assert trace is not None
    assert trace.left_out == (
        LeftOut("K", LeftOutCause.NOT_APPLICABLE, "carried by B", 2),
    )
    (k,) = [i for i in trace.inputs if i.holder == "K"]
    assert k.state is ValueState.NOT_APPLICABLE
    assert trace.unknown == ()


def test_a_value_not_applicable_to_any_member_is_not_applicable() -> None:
    g = Group(
        "G",
        (
            (member("K", width=NA("carried by B")), 1),
            (member("L", width=NA("folded")), 1),
        ),
    )
    d = derive(g, {"width": MAX("width"), "mass": Aggregation.sum("mass")})
    width = d["width"]
    assert width.state is ValueState.NOT_APPLICABLE
    assert width.not_applicable == (
        "not applicable to any member of 'G': K (carried by B), L (folded)"
    )
    assert width.derivation is not None
    assert width.derivation.fixed_by == ("K", "L")
    # The mass is unknown for both: to be set.
    assert d["mass"].to_be_set
    assert d.unknown["mass"] == Tally(("K", "L"), 2)


# The policies for the unknown ----------------------------------------------


def test_propagate_leaves_an_envelope_to_be_set_with_its_bound() -> None:
    rules = {
        "width": MAX("width"),
        "load_class": Aggregation.strictest("load_class", ("C30", "C50", "C70", "C90")),
        "length": Aggregation.sum("length"),
        "members": Aggregation.count(),
    }
    d = derive(MIXED, rules)
    width = d["width"]
    assert width.to_be_set
    trace = width.derivation
    assert trace is not None
    assert trace.unknown == ("U",)
    assert (trace.bound, trace.bound_fixed_by) == (3.5, ("B",))
    assert trace.fixed_by == ()
    assert d.unknown["width"] == Tally(("U",), 3)
    assert d.assumed["width"] == Tally()
    (u,) = [i for i in trace.inputs if i.holder == "U"]
    assert (u.state, u.value) == (ValueState.UNKNOWN, None)
    # The last label is not reached: to be set, bounded by C70.
    label = d["load_class"].derivation
    assert label is not None
    assert d["load_class"].to_be_set
    assert (label.bound, label.bound_fixed_by) == ("C70", ("B",))
    # The other rules: U has a length, and the count reads no value.
    assert d["length"].value == 2 * 6.0 + 12.0 + 8.0 + 3 * 4.0
    assert d["members"].value == 7
    # An additive rule has no bound.
    total = derive(MIXED, {"width": Aggregation.sum("width")})["width"]
    assert total.to_be_set
    assert total.derivation is not None
    assert total.derivation.bound is None
    # The minimum is bounded too, by the least known value.
    low = derive(MIXED, {"width": MIN("width")})["width"].derivation
    assert low is not None
    assert (low.bound, low.bound_fixed_by) == (2.5, ("A",))
    # No known value: no bound.
    none = derive(Group("alone", ((UNKNOWN_WIDTH, 1),)), {"width": MAX("width")})
    assert none["width"].derivation is not None
    assert none["width"].derivation.bound is None


def test_propagate_is_decided_by_the_last_label_of_the_order() -> None:
    # DD9: B is already at C70, the most demanding label.
    rule = Aggregation.strictest("load_class", CLASSES)
    d = derive(MIXED, {"load_class": rule})
    value = d["load_class"]
    assert value.value == "C70"
    trace = value.derivation
    assert trace is not None
    assert (trace.fixed_by, trace.unknown, trace.bound) == (("B",), ("U",), None)
    assert d.unknown["load_class"] == Tally(("U",), 3)
    # Never for a numeric maximum, even at inf.
    free = member("F", width=math.inf)
    g = Group("G", ((free, 1), (UNKNOWN_WIDTH, 1)))
    assert derive(g, {"width": MAX("width")})["width"].to_be_set


def test_known_only_computes_on_the_known_inputs_and_counts_the_others() -> None:
    rules = {
        "width": MAX("width"),
        "speed": MIN("speed"),
        "load_class": Aggregation.strictest("load_class", CLASSES),
    }
    d = derive(MIXED, rules, KNOWN_ONLY)
    # U has no width and no class: the oracle is the group without U.
    oracle = derive(Group("M", ((A, 2), (B, 1), (C, 1))), rules)
    for name in ("width", "load_class"):
        assert d[name].value == oracle[name].value
    assert d["speed"].value == 40.0  # U has a speed
    assert d.unknown["speed"] == Tally()
    trace = d["width"].derivation
    assert trace is not None
    assert trace.unknown == ("U",)
    justification = KNOWN_ONLY.justification
    assert justification is not None
    assert trace.left_out == (LeftOut("U", LeftOutCause.UNKNOWN, justification, 3),)
    assert trace.settings["justification"] == justification
    assert d.unknown["width"] == Tally(("U",), 3)
    assert d.left_out["width"] == Tally(("U",), 3)
    assert d.assumed["width"] == Tally()
    # Without a known input: to be set.
    alone = derive(
        Group("alone", ((UNKNOWN_WIDTH, 1),)), {"width": MAX("width")}, KNOWN_ONLY
    )
    assert alone["width"].to_be_set
    # The count reads no value: allowed.
    count = derive(MIXED, {"members": Aggregation.count()}, KNOWN_ONLY)
    assert count["members"].value == 7


@pytest.mark.parametrize(
    ("output", "rule", "shown"),
    [
        ("length", Aggregation.sum("length"), "sum of 'length'"),
        ("length", Aggregation.mean("length"), "mean of 'length'"),
        (
            "heavy",
            Aggregation.threshold_count("mass", mass(20.0), Comparison.ABOVE),
            "threshold_count of 'mass'",
        ),
    ],
)
def test_known_only_is_refused_for_additive_rules(
    output: str, rule: Aggregation, shown: str
) -> None:
    with pytest.raises(
        ValueError,
        match=re.escape(
            f"known_only would shorten an additive value ({shown}): use propagate "
            "or assume"
        ),
    ):
        derive(FOUR, {output: rule}, KNOWN_ONLY)


def test_assume_replaces_the_unknown_inputs_and_says_so() -> None:
    assumed = chosen(8.0, "m")
    policy = OnUnknown.assume({"width": assumed})
    d = derive(MIXED, {"width": MAX("width")}, policy)
    rebuilt = Group(
        "M", ((A, 2), (B, 1), (C, 1), (member("U", width=8.0, mass=5.0), 3))
    )
    assert d["width"].value == derive(rebuilt, {"width": MAX("width")})["width"].value
    assert d["width"].value == 8.0
    trace = d["width"].derivation
    assert trace is not None
    assert trace.fixed_by == ("U",)
    assert trace.assumptions == (Assumption("width", assumed, ("U",), 3),)
    (u,) = [i for i in trace.inputs if i.holder == "U"]
    assert (u.state, u.value) == (ValueState.ASSUMED, assumed)
    assert d.assumed["width"] == d.unknown["width"] == Tally(("U",), 3)
    # The sum of the widths, additive: assumed for the 3 instances of U.
    total = derive(MIXED, {"width": Aggregation.sum("width")}, policy)["width"]
    assert total.value == 2 * 2.5 + 3.5 + 3.0 + 3 * 8.0
    # An assumed value no unknown needs is allowed, and not traced.
    full = derive(FOUR, {"width": MAX("width")}, policy)
    assert full["width"].derivation is not None
    assert full["width"].derivation.assumptions == ()
    assert full.assumed["width"] == Tally()


def test_assume_refusals() -> None:
    policy = OnUnknown.assume({"width": chosen(8.0, "m")})
    strictest = Aggregation.strictest("load_class", CLASSES)
    with pytest.raises(
        ValueError,
        match="member 'U': no value for 'load_class' and no value assumed for it",
    ):
        derive(MIXED, {"width": MAX("width"), "load_class": strictest}, policy)
    with pytest.raises(
        ValueError, match="a value is assumed for 'width', which no rule reads"
    ):
        derive(FOUR, {"members": Aggregation.count()}, policy)
    with pytest.raises(ValueError, match="unknown parameter 'depth'"):
        derive(FOUR, {"width": MAX("width")}, OnUnknown.assume({"depth": chosen(1.0)}))
    cm = OnUnknown.assume({"width": chosen(8.0, "cm")})
    with pytest.raises(
        ValueError,
        match=re.escape(
            "the value assumed for 'width' in 'cm', the parameter is in 'm'"
        ),
    ):
        derive(MIXED, {"width": MAX("width")}, cm)
    text = OnUnknown.assume({"width": chosen("wide", "m")})
    with pytest.raises(
        TypeError,
        match="the value assumed for 'width' must be a number for max, got 'wide'",
    ):
        derive(MIXED, {"width": MAX("width")}, text)


def test_a_value_to_be_set_on_a_sheet_is_unknown() -> None:
    pending = member("P", width=None)
    g = Group("G", ((A, 1), (pending, 1)))
    d = derive(g, {"width": MAX("width")})
    trace = d["width"].derivation
    assert trace is not None
    (p,) = [i for i in trace.inputs if i.holder == "P"]
    assert p.state is ValueState.UNKNOWN
    assert p.value == pending.sheets[0].values["width"]
    assert d.unknown["width"] == Tally(("P",), 1)


# Refusals ------------------------------------------------------------------


def test_values_are_read_in_the_unit_of_their_parameter() -> None:
    cm = Member(
        "A",
        (
            ValueSet(
                "sheet-A",
                "1",
                {"width": Value(250, Source("Sheet A"), Origin.STATEMENT, unit="cm")},
            ),
        ),
    )
    with pytest.raises(
        ValueError,
        match=re.escape("member 'A': 'width' in 'cm', the parameter is in 'm'"),
    ):
        derive(Group("G", ((cm, 1),)), {"width": MAX("width")})


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        (
            {"mass": MAX("width")},
            (
                "max of 'width' (m) into 'mass' (t): a derived value keeps the unit of "
                "its inputs"
            ),
        ),
        (
            {"width": Aggregation.count()},
            "count gives a number of members: 'width' must have no unit, got 'm'",
        ),
        (
            {"width": Aggregation.threshold_count("mass", mass(1.0), Comparison.ABOVE)},
            "threshold_count gives a number of members: 'width' must have no unit",
        ),
        (
            {"width": Aggregation.strictest("load_class", CLASSES)},
            "strictest gives a label of its order: 'width' must have no unit",
        ),
        (
            {
                "heavy": Aggregation.threshold_count(
                    "mass", mass(1, "kg"), Comparison.ABOVE
                )
            },
            "the threshold of 'mass' in 'kg', the parameter is in 't'",
        ),
        ({"nothing": MAX("width")}, "unknown parameter 'nothing': declare it in"),
        ({"width": MAX("depth")}, "unknown parameter 'depth': declare it in"),
        ({}, "no rule: give at least one output parameter"),
    ],
)
def test_rules_are_checked_against_the_vocabulary(
    rules: dict[str, Aggregation], message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        derive(FOUR, rules)


def test_sheets_are_read_through_the_vocabulary() -> None:
    assert ALIAS_BOOK.id == "sheet-alias"
    aliased = Member("X", (sheet("sheet-alias", overall_width=4.0),))
    d = derive(Group("G", ((aliased, 1), (A, 1))), {"width": MAX("width")})
    assert d["width"].value == 4.0
    both = Member(
        "X", (sheet("sheet-alias", overall_width=4.0), sheet("sheet-x", width=3.0))
    )
    with pytest.raises(
        ValueError,
        match=re.escape(
            "member 'X': 'width' given by two sheets (sheet-alias (1), sheet-x (1))"
        ),
    ):
        derive(Group("G", ((both, 1),)), {"width": MAX("width")})
    twice = Member("X", (sheet("sheet-alias", overall_width=4.0, width=4.0),))
    with pytest.raises(ValueError, match="parameter 'width' given twice"):
        derive(Group("G", ((twice, 1),)), {"width": MAX("width")})
    stray = Member("X", (sheet("sheet-x", colour="red"),))
    with pytest.raises(
        ValueError,
        match=re.escape(
            "member 'X': value set sheet-x (1): unknown parameter 'colour': declare "
            "it in parameters"
        ),
    ):
        derive(Group("G", ((stray, 1),)), {"width": MAX("width")})


def test_vocabulary_and_arguments_are_checked() -> None:
    rules = {"width": MAX("width")}
    # The same parameter twice, identically: from the requirements and
    # from a rulebook.
    same = aggregate(
        FOUR,
        rules,
        parameters=[*PARAMETERS, PARAMETERS[0]],
        unknown=PROPAGATE,
        edition="1",
    )
    assert same["width"].value == 3.5
    with pytest.raises(ValueError, match="'width' declared twice, differently"):
        aggregate(
            FOUR,
            rules,
            parameters=[*PARAMETERS, Parameter("width", unit="cm")],
            unknown=PROPAGATE,
            edition="1",
        )
    with pytest.raises(TypeError, match="parameters must be Parameter objects"):
        aggregate(
            FOUR,
            rules,
            parameters=["width"],  # type: ignore[list-item]
            unknown=PROPAGATE,
            edition="1",
        )
    with pytest.raises(TypeError, match="group must be a Group"):
        derive(A, rules)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="unknown must be an OnUnknown policy"):
        derive(FOUR, rules, UnknownRule.PROPAGATE)  # type: ignore[arg-type]
    with pytest.raises(
        TypeError, match=re.escape("rules['width'] must be an Aggregation")
    ):
        derive(FOUR, {"width": "max"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="edition must be a non-empty string"):
        aggregate(FOUR, rules, parameters=PARAMETERS, unknown=PROPAGATE, edition="")
    with pytest.raises(
        TypeError, match="member 'A': 'note' must be a number for max, got 'x'"
    ):
        derive(Group("G", ((member("A", note="x"), 1),)), {"note": MAX("note")})
    assert derive(FOUR, rules, precedence=2)["width"].precedence == 2


AGGREGATION_REFUSALS: list[tuple[Callable[[], object], str]] = [
    (lambda: Aggregation(AggregateKind.COUNT, "width"), "count reads no parameter"),
    (lambda: Aggregation(AggregateKind.MAX), "max reads a parameter: give of"),
    (lambda: Aggregation(AggregateKind.MAX, ""), "of must be a non-empty string"),
    (
        lambda: Aggregation.strictest("c", ("A",)),
        "strictest needs an order of at least two distinct labels",
    ),
    (
        lambda: Aggregation.strictest("c", ("A", "A")),
        "strictest needs an order of at least two distinct labels",
    ),
    (
        lambda: Aggregation.strictest("c", ("A", " ")),
        "strictest needs an order of at least two distinct labels",
    ),
    (
        lambda: Aggregation(AggregateKind.MAX, "c", order=("A", "B")),
        "only strictest takes an order",
    ),
    (
        lambda: Aggregation(AggregateKind.THRESHOLD_COUNT, "mass"),
        "threshold_count needs a known threshold and its comparison",
    ),
    (
        lambda: Aggregation(AggregateKind.THRESHOLD_COUNT, "mass", threshold=mass(1.0)),
        "threshold_count needs a known threshold and its comparison",
    ),
    (
        lambda: Aggregation.threshold_count(
            "mass", Value(None, Source("x"), Origin.STATEMENT), Comparison.ABOVE
        ),
        "threshold_count needs a known threshold and its comparison",
    ),
    (
        lambda: Aggregation.threshold_count(
            "mass", Value("x", Source("x"), Origin.STATEMENT), Comparison.ABOVE
        ),
        "threshold_count needs a known threshold and its comparison",
    ),
    (
        lambda: Aggregation.threshold_count(
            "mass",
            1.0,  # type: ignore[arg-type]
            Comparison.ABOVE,
        ),
        "threshold_count needs a known threshold and its comparison",
    ),
    (
        lambda: Aggregation(AggregateKind.MAX, "mass", comparison=Comparison.ABOVE),
        "only threshold_count takes a threshold and a comparison",
    ),
]


@pytest.mark.parametrize(
    ("build", "message"),
    AGGREGATION_REFUSALS,
    ids=[str(k) for k in range(len(AGGREGATION_REFUSALS))],
)
def test_aggregation_checks_its_options(
    build: Callable[[], object], message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        build()


def test_aggregation_constructors() -> None:
    assert Aggregation.max("w") == Aggregation(AggregateKind.MAX, "w")
    assert Aggregation.min("w").kind is AggregateKind.MIN
    assert Aggregation.sum("w").kind is AggregateKind.SUM
    assert Aggregation.mean("w").kind is AggregateKind.MEAN
    assert Aggregation.count() == Aggregation("count")  # type: ignore[arg-type]
    assert Aggregation.strictest("c", ["A", "B"]).order == ("A", "B")
    t = Aggregation.threshold_count("m", mass(1.0), "at_least")  # type: ignore[arg-type]
    assert t.comparison is Comparison.AT_LEAST


POLICY_REFUSALS: list[tuple[Callable[[], object], str]] = [
    (
        lambda: OnUnknown(UnknownRule.PROPAGATE, justification="x"),
        "propagate takes no justification nor assumed value",
    ),
    (
        lambda: OnUnknown(UnknownRule.PROPAGATE, assumed={"w": chosen(1.0)}),
        "propagate takes no justification nor assumed value",
    ),
    (
        lambda: OnUnknown.known_only(" "),
        (
            "known_only needs a justification: why the inputs without a value can be "
            "left out"
        ),
    ),
    (lambda: OnUnknown(UnknownRule.KNOWN_ONLY), "known_only needs a justification"),
    (
        lambda: OnUnknown(
            UnknownRule.KNOWN_ONLY, justification="x", assumed={"w": chosen(1.0)}
        ),
        "known_only takes no assumed value",
    ),
    (lambda: OnUnknown.assume({}), "assume needs at least one assumed value"),
    (
        lambda: OnUnknown(
            UnknownRule.ASSUME, justification="x", assumed={"w": chosen(1.0)}
        ),
        "assume takes no justification of its own",
    ),
    (
        lambda: OnUnknown.assume({"w": Value(None, SRC, Origin.CHOICE)}),
        "the value assumed for 'w' must be known, got to be set",
    ),
    (
        lambda: OnUnknown.assume(
            {"w": Value(None, SRC, Origin.CHOICE, not_applicable="none")}
        ),
        "the value assumed for 'w' must be known, got not applicable",
    ),
    (
        lambda: OnUnknown.assume({"w": Value(1.0, SRC, Origin.RULEBOOK)}),
        "the value assumed for 'w' is a choice: origin 'choice' with its justification",
    ),
    (
        lambda: OnUnknown.assume({"w": Value(1.0, SRC, Origin.CHOICE)}),
        "the value assumed for 'w' is a choice",
    ),
    (lambda: OnUnknown.assume({"": chosen(1.0)}), "assumed parameter must be"),
]


@pytest.mark.parametrize(
    ("build", "message"),
    POLICY_REFUSALS,
    ids=[str(k) for k in range(len(POLICY_REFUSALS))],
)
def test_on_unknown_checks_its_policy(
    build: Callable[[], object], message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        build()


def test_on_unknown_types() -> None:
    with pytest.raises(TypeError, match="the value assumed for 'w' must be a Value"):
        OnUnknown.assume({"w": 1.0})  # type: ignore[dict-item]
    policy = OnUnknown("assume", assumed={"w": chosen(1.0)})  # type: ignore[arg-type]
    assert policy.rule is UnknownRule.ASSUME
    assert OnUnknown.propagate() == PROPAGATE
    assert OnUnknown.propagate().assumed == {}
    assert pickle.loads(pickle.dumps(policy)) == policy


# Derived and Tally ---------------------------------------------------------


def test_tally_is_canonical() -> None:
    assert Tally(("B", "A", "B"), 3).names == ("A", "B")
    assert Tally() == Tally((), 0)
    with pytest.raises(ValueError, match="at least 0"):
        Tally(("A",), -1)
    with pytest.raises(ValueError, match="a tally without names counts no instance"):
        Tally((), 2)
    with pytest.raises(TypeError, match="must be an integer"):
        Tally(("A",), 1.0)  # type: ignore[arg-type]


def test_derived_checks_its_tables_and_merges() -> None:
    widths = derive(FOUR, {"width": MAX("width")})
    speeds = derive(FOUR, {"speed": MIN("speed")})
    merged = Derived.merge(widths, speeds)
    assert merged["width"] == widths["width"]
    assert set(merged.values.values) == {"width", "speed"}
    assert merged.unknown == {"width": Tally(), "speed": Tally()}
    assert Derived.merge(widths) == widths
    with pytest.raises(ValueError, match="'width' derived twice"):
        Derived.merge(widths, widths)
    other = derive(Group("H", ((A, 1),)), {"speed": MIN("speed")})
    with pytest.raises(
        ValueError,
        match=re.escape(
            "cannot merge the values of G (1) and H (1): same rulebook and edition "
            "required"
        ),
    ):
        Derived.merge(widths, other)
    with pytest.raises(ValueError, match="nothing to merge"):
        Derived.merge()
    plain = ValueSet(
        "G", "1", {"width": Value(1.0, Source("x"), Origin.STATEMENT, unit="m")}
    )
    empty = {"width": Tally()}
    with pytest.raises(
        ValueError,
        match=re.escape("derived values: 'width' is not derived (origin 'statement')"),
    ):
        Derived(plain, empty, empty, empty)
    vs = widths.values
    with pytest.raises(
        ValueError, match="tallies name 'q', which is not a derived value"
    ):
        Derived(vs, {**empty, "q": Tally()}, empty, empty)
    with pytest.raises(ValueError, match="assumed has no tally for 'width'"):
        Derived(vs, empty, {}, empty)
    with pytest.raises(TypeError, match=re.escape("left_out['width'] must be a Tally")):
        Derived(vs, empty, empty, {"width": 0})  # type: ignore[dict-item]
    with pytest.raises(
        ValueError, match="the assumed inputs of 'width' must be among its unknown"
    ):
        Derived(vs, empty, {"width": Tally(("A",), 1)}, empty)
    with pytest.raises(TypeError, match="values must be a ValueSet"):
        Derived({}, {}, {}, {})  # type: ignore[arg-type]


def test_derived_values_enter_resolve_values_with_their_precedence() -> None:
    derived = derive(FOUR, {"width": MAX("width")}, precedence=1)
    stated = ValueSet(
        "client",
        "1",
        {"width": Value(3.0, Source("Statement"), Origin.STATEMENT, unit="m")},
    )
    resolved = resolve_values([derived.values, stated], WIDTH_REQS)
    assert resolved.values["width"] == derived["width"]
    assert resolved.discarded["width"][0].value == 3.0


# Traceability --------------------------------------------------------------


def test_a_derived_value_to_be_set_names_the_members_without_a_value() -> None:
    graph, data = arcs([3.0, 4.0, None])
    d = derive(MIXED, {"width": MAX("width")})
    resolved = resolve_values([d.values], WIDTH_REQS)
    reason = "value of 'width' to be set: no value for U"
    assert evaluate(WIDTH_REQ, graph, data, resolved).not_applicable == reason
    check = check_inputs(WIDTH_REQS, graph, data, resolved)["ADM-WIDTH"]
    assert (check.reason, check.missing_values) == (reason, ("width",))
    na = Group("N", ((member("K", width=NA("carried")), 1),))
    resolved = resolve_values([derive(na, {"width": MAX("width")}).values], WIDTH_REQS)
    reason = (
        "value of 'width' not applicable: not applicable to any member of 'N': "
        "K (carried)"
    )
    assert evaluate(WIDTH_REQ, graph, data, resolved).not_applicable == reason
    check = check_inputs(WIDTH_REQS, graph, data, resolved)["ADM-WIDTH"]
    assert (check.reason, check.missing_values) == (reason, ())


def test_the_fingerprint_covers_every_member_not_only_the_one_that_fixes() -> None:
    rules = {"width": MAX("width")}
    base = derive(FOUR, rules)
    # A is not the widest; widen it a little.
    wider = Group("G", ((member("A", width=2.6), 2), (B, 1), (C, 1), (D, 3)))
    changed = derive(wider, rules)
    assert changed["width"].value == base["width"].value
    assert fingerprint(changed) != fingerprint(base)
    resolved = resolve_values([base.values], WIDTH_REQS)
    other = resolve_values([changed.values], WIDTH_REQS)
    assert fingerprint(resolved) != fingerprint(other)
    # Identical calls: equal results and fingerprints.
    assert derive(FOUR, rules) == base
    assert fingerprint(derive(FOUR, rules)) == fingerprint(base)


def test_derived_values_pickle_and_copy() -> None:
    d = derive(
        MIXED,
        {
            "width": MAX("width"),
            "speed": MIN("speed"),
            "members": Aggregation.count(),
        },
        OnUnknown.assume({"width": chosen(8.0, "m"), "speed": chosen(30.0, "km/h")}),
    )
    resolved = resolve_values([d.values], WIDTH_REQS)
    width = d["width"]
    for x in (d, width, width.derivation, resolved, WIDTH_REQS):
        assert pickle.loads(pickle.dumps(x)) == x
        assert copy.deepcopy(x) == x
        assert fingerprint(pickle.loads(pickle.dumps(x))) == fingerprint(x)
    assert hash(width) == hash(pickle.loads(pickle.dumps(width)))


def test_import_constraints_imports_no_unit_library() -> None:
    code = (
        "import sys, protee.constraints; "
        "heavy = {'pint', 'scipy', 'pandas'} & sys.modules.keys(); "
        "assert not heavy, sorted(heavy)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# Life-cycle profile: one equipment in several packagings -------------------

LIFE = (
    Parameter("storage_duration", unit="d"),
    Parameter("transport_occurrences"),
    Parameter("handling_occurrences"),
)
LIFE_UNITS = {p.name: p.unit for p in LIFE}


def packaging(id: str, **values: Given) -> Member:
    """A packaging of the equipment, a variant described by its sheet."""
    source = Source(f"Packaging sheet {id}", locator="table 2")
    sheet_ = ValueSet(
        f"packaging-{id}",
        "1",
        {
            name: Value(
                None,
                source,
                Origin.STATEMENT,
                unit=LIFE_UNITS[name],
                not_applicable=x.reason,
            )
            if isinstance(x, NA)
            else Value(x, source, Origin.STATEMENT, unit=LIFE_UNITS[name])
            for name, x in values.items()
        },
    )
    return Member(id, (sheet_,))


def test_life_cycle_envelope_of_an_equipment_over_its_packagings() -> None:
    # One equipment in three packagings, each a variant counted once: the
    # envelope gives the dimensioning durations and occurrences, a bound for
    # the profile (its worst case is at least that of every variant).
    crate = packaging(
        "crate", storage_duration=180, transport_occurrences=4, handling_occurrences=12
    )
    container = packaging(
        "container",
        storage_duration=365,
        transport_occurrences=2,
        handling_occurrences=NA("handled with its carrier"),
    )
    pallet = packaging(
        "pallet", storage_duration=90, transport_occurrences=6, handling_occurrences=8
    )
    variants = (crate, container, pallet)
    equipment = Group("equipment-E", tuple((v, 1) for v in variants))
    names = [p.name for p in LIFE]
    d = aggregate(
        equipment,
        {name: Aggregation.max(name) for name in names},
        parameters=LIFE,
        unknown=OnUnknown.propagate(),
        edition="1",
    )
    duration = d["storage_duration"]
    assert (duration.value, duration.unit) == (365, "d")
    assert duration.derivation is not None
    assert duration.derivation.fixed_by == ("container",)
    assert d["transport_occurrences"].value == 6
    assert d["handling_occurrences"].value == 12
    assert d.left_out["handling_occurrences"] == Tally(("container",), 1)
    for v in variants:
        for name, own in v.sheets[0].values.items():
            if own.value is not None:
                assert d[name].value >= own.value  # type: ignore[operator]
    # The envelope bounds the occurrences of every link of a profile.
    reqs, data, _ = profile()
    bound = requirement(
        "OC-TRANSPORT",
        "occurrence_bounds",
        parameters={"maximum": "transport_occurrences"},
    )
    life = RequirementSet((bound,), (*reqs.parameters, *LIFE), reqs.rulebooks)
    effect = evaluate(bound, PROFILE, data, resolve_values([d.values], life))
    assert effect.upper is not None
    assert np.array_equal(effect.upper, np.full(PROFILE.m, 6.0))


# Properties ----------------------------------------------------------------

NUMBERS = st.sampled_from([0, 1, 3, 0.0, 0.1, 0.2, 0.25, 1.5, 2.5, 3.5, 1e16, math.inf])
COUNTS = st.integers(1, 3)


@st.composite
def rows(
    draw: st.DrawFn, *, unknown: bool = False, size: int = 5
) -> list[tuple[Member, int]]:
    """Members m0, m1... with a length and a class (neither when
    ``unknown`` draws the member unknown), and a count."""
    n = draw(st.integers(1, size))
    out = []
    for k in range(n):
        x = draw(st.one_of(st.none(), NUMBERS) if unknown else NUMBERS)
        if x is None:
            out.append((member(f"m{k}"), draw(COUNTS)))
        else:
            label = draw(st.sampled_from(CLASSES))
            out.append((member(f"m{k}", length=x, load_class=label), draw(COUNTS)))
    return out


#: Envelopes of the lengths and of the classes.
ENVELOPES = {
    "length": MAX("length"),
    "width": MIN("length"),
    "load_class": Aggregation.strictest("load_class", CLASSES),
}
#: The other rules, on the lengths.
ADDITIVE = {
    "length": Aggregation.sum("length"),
    "width": Aggregation.mean("length"),
    "members": Aggregation.count(),
    "heavy": Aggregation.threshold_count(
        "length", Value(1.5, SRC, Origin.RULEBOOK, unit="m"), Comparison.AT_LEAST
    ),
}


def _rename(member_: Member, id: str) -> Member:
    """The same values under another identifier."""
    (sheet_,) = member_.sheets
    source = Source(f"Sheet sheet-{id}")
    values = {
        k: Value(v.value, source, v.origin, unit=v.unit)
        for k, v in sheet_.values.items()
    }
    return Member(id, (ValueSet(f"sheet-{id}", sheet_.edition, values),))


def _rank(label: object) -> int:
    return CLASSES.index(str(label))


@given(st.data(), rows())
def test_the_order_of_the_members_does_not_matter(
    data: st.DataObject, table: list[tuple[Member, int]]
) -> None:
    shuffled = data.draw(st.permutations(table))
    renamed = [m.id for m, _ in data.draw(st.permutations(table))]
    relabelled = [
        (_rename(m, new), c) for (m, c), new in zip(table, renamed, strict=True)
    ]
    for rules in (ENVELOPES, ADDITIVE):
        first = derive(Group("G", tuple(table)), rules)
        second = derive(Group("G", tuple(shuffled)), rules)
        assert first == second
        assert fingerprint(first) == fingerprint(second)
        # Renamed members: the values depend on the multiset of values only.
        third = derive(Group("G", tuple(relabelled)), rules)
        for name in rules:
            assert third[name].value == first[name].value


@given(rows(size=4), NUMBERS, st.sampled_from(CLASSES), COUNTS)
def test_adding_a_member_never_relaxes_an_envelope(
    table: list[tuple[Member, int]], x: float, label: str, count: int
) -> None:
    new = member("new", length=x, load_class=label)
    rules = {**ENVELOPES, "members": Aggregation.count()}
    before = derive(Group("G", tuple(table)), rules)
    after = derive(Group("G", (*table, (new, count))), rules)
    assert after["length"].value >= before["length"].value  # type: ignore[operator]
    assert after["width"].value <= before["width"].value  # type: ignore[operator]
    assert _rank(after["load_class"].value) >= _rank(before["load_class"].value)
    assert after["members"].value > before["members"].value  # type: ignore[operator]
    # A sum of non-negative values never decreases.
    total = {"length": Aggregation.sum("length")}
    more = derive(Group("G", (*table, (new, count))), total)["length"].value
    less = derive(Group("G", tuple(table)), total)["length"].value
    assert more >= less  # type: ignore[operator]


@given(rows(), st.lists(COUNTS, min_size=5, max_size=5))
def test_envelopes_do_not_depend_on_the_counts(
    table: list[tuple[Member, int]], counts: list[int]
) -> None:
    base = Group("G", tuple(table))
    variant = base.with_counts(
        "G2",
        {m.id: c for (m, _), c in zip(table, counts, strict=False)},
        zero_counts=ZeroCount.REFUSE,
    )
    first = derive(base, ENVELOPES)
    second = derive(variant, ENVELOPES)
    for name in ENVELOPES:
        one, two = first[name].derivation, second[name].derivation
        assert one is not None
        assert two is not None
        assert first[name].value == second[name].value
        assert one.fixed_by == two.fixed_by


@given(rows(unknown=True))
def test_policies_agree_with_their_oracles(table: list[tuple[Member, int]]) -> None:
    group = Group("G", tuple(table))
    unknown = tuple(m.id for m, _ in table if "length" not in m.sheets[0].values)
    rules = {"length": MAX("length"), "width": MIN("length")}
    propagated = derive(group, rules)
    for name in rules:
        assert propagated[name].to_be_set == bool(unknown)
        assert propagated.unknown[name].names == unknown
    # known_only: the declared sub-group without the unknown members.
    known_only = derive(group, rules, KNOWN_ONLY)
    if len(unknown) == len(table):
        assert all(known_only[name].to_be_set for name in rules)
    else:
        known = group.without("known", unknown, reason="r") if unknown else group
        oracle = derive(known, rules)
        for name in rules:
            assert known_only[name].value == oracle[name].value
    # assume: the members rebuilt with the assumed value.
    policy = OnUnknown.assume({"length": chosen(2.5, "m")})
    rebuilt = Group(
        "G",
        tuple(
            ((member(m.id, length=2.5) if m.id in unknown else m), c) for m, c in table
        ),
    )
    for chosen_rules in (rules, {"length": Aggregation.sum("length")}):
        assumed = derive(group, chosen_rules, policy)
        oracle = derive(rebuilt, chosen_rules)
        for name in chosen_rules:
            assert assumed[name].value == oracle[name].value
            assert set(assumed.assumed[name].names) <= set(assumed.unknown[name].names)
            assert assumed.assumed[name].names == unknown


@given(rows(unknown=True))
def test_strictest_under_propagate_is_decided_only_by_the_last_label(
    table: list[tuple[Member, int]],
) -> None:
    d = derive(Group("G", tuple(table)), {"load_class": ENVELOPES["load_class"]})
    labels = [
        m.sheets[0].values["load_class"].value
        for m, _ in table
        if "load_class" in m.sheets[0].values
    ]
    value = d["load_class"]
    assert value.derivation is not None
    if len(labels) == len(table):
        assert value.value == max(labels, key=_rank)
        assert value.derivation.unknown == ()
    elif "C70" in labels:
        assert value.value == "C70"
        assert value.derivation.unknown
    else:
        assert value.to_be_set


LIMITS = st.lists(
    st.one_of(st.none(), st.sampled_from([0.0, 0.1, 2.5, 3.0, 3.5, 4.0, math.inf])),
    min_size=1,
    max_size=6,
)
WIDTHS = st.lists(
    st.one_of(st.none(), st.sampled_from([0.1, 2.5, 3.0, 3.5, 3.7])),
    min_size=1,
    max_size=4,
)


def _verdicts(width: float, graph: Digraph, data: ArcData) -> list[int]:
    """The verdicts of one member, its width stated alone."""
    stated = ValueSet(
        "stated", "1", {"width": Value(width, Source("x"), Origin.STATEMENT, unit="m")}
    )
    effect = evaluate(WIDTH_REQ, graph, data, resolve_values([stated], WIDTH_REQS))
    assert effect.verdict is not None
    return [int(v) for v in effect.verdict]


@given(WIDTHS, LIMITS)
def test_the_envelope_is_exact_for_a_threshold(
    widths: list[float | None], limits: list[float | None]
) -> None:
    # The Kleene conjunction (the minimum) of the verdicts of the members
    # equals the verdict of their maximum.
    graph, data = arcs(limits)
    table = tuple(
        (member(f"m{k}") if w is None else member(f"m{k}", width=w), 1)
        for k, w in enumerate(widths)
    )
    group = Group("G", table)
    known = [w for w in widths if w is not None]

    def conjunction(values: list[float]) -> list[int]:
        each = [_verdicts(w, graph, data) for w in values]
        return [min(column) for column in zip(*each, strict=True)]

    def verdicts(policy: OnUnknown) -> list[int] | str | None:
        d = derive(group, {"width": MAX("width")}, policy)
        effect = evaluate(
            WIDTH_REQ, graph, data, resolve_values([d.values], WIDTH_REQS)
        )
        if effect.verdict is None:
            return effect.not_applicable
        return [int(v) for v in effect.verdict]

    if len(known) == len(widths):
        assert verdicts(PROPAGATE) == conjunction(known)
        return
    # R1: under propagate, the requirement is not applicable.
    missing = ", ".join(f"m{k}" for k, w in enumerate(widths) if w is None)
    assert verdicts(PROPAGATE) == f"value of 'width' to be set: no value for {missing}"
    policy = OnUnknown.assume({"width": chosen(3.6, "m")})
    assert verdicts(policy) == conjunction([3.6 if w is None else w for w in widths])
    if known:
        assert verdicts(KNOWN_ONLY) == conjunction(known)
