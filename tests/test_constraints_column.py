# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""column_length: oracles by hand on nested groups, both forms and both
gap conventions, the identities between them, the four states of a
value, the policies for the unknown, refusals and properties."""

from __future__ import annotations

import math
import random
import re
import sys
from collections.abc import Callable, Sequence
from fractions import Fraction

import pytest
from derive_cases import (
    COLUMN,
    KNOWN_ONLY,
    LINE,
    NA,
    PROPAGATE,
    S1,
    S2,
    SPACING,
    VOCABULARY,
    A,
    B,
    C,
    D,
    chosen,
    measure,
    member,
    plan,
    sheet,
)
from hypothesis import given
from hypothesis import strategies as st

from protee.constraints import (
    Aggregation,
    Assumption,
    Conversion,
    Derived,
    Gap,
    GapCount,
    Group,
    LeftOut,
    LeftOutCause,
    Member,
    OnUnknown,
    Origin,
    Parameter,
    Source,
    Tally,
    Value,
    ValueSet,
    ValueState,
    _units,
    aggregate,
    column_length,
    fingerprint,
)

BETWEEN = GapCount.BETWEEN
PER_UNIT = GapCount.PER_UNIT


def length(derived: Derived) -> float | None:
    x = derived["column_length"].value
    assert x is None or isinstance(x, float)
    return x


# Oracles by hand -----------------------------------------------------------


def test_geometric_length_of_nested_groups() -> None:
    # s1: 2 x 6 + 12 + 2 gaps of 20 = 64; s2: 8 + 2 x 5 + 2 gaps of 30 (the
    # gap of the line) = 78; the line: 2 x 64 + 78 + 2 gaps of 2 min at
    # 500 m/min = 2206 m.
    d = measure(LINE)
    value = d["column_length"]
    assert (value.value, value.unit, value.origin) == (2206.0, "m", Origin.DERIVED)
    assert (value.source.document, value.source.rulebook, value.source.edition) == (
        "column_length of line",
        "line",
        "1",
    )
    trace = value.derivation
    assert trace is not None
    assert (trace.name, trace.rule) == ("column_length", "geometric")
    assert trace.settings == {
        "member_length": "length",
        "spacing": (("time_gap", "between", True), ("gap", "between", False)),
        "pace": "pace",
        "unknown": "propagate",
    }
    assert trace.fixed_by == ("A", "B", "C", "D", "line", "s1")
    # Each value of a group is held by the group that gives it, and counts
    # the instances of the groups it serves.
    assert [(i.holder, i.parameter, i.role, i.instances) for i in trace.inputs] == [
        ("A", "length", "member", 4),
        ("B", "length", "member", 2),
        ("C", "length", "member", 1),
        ("D", "length", "member", 2),
        ("line", "gap", "gap", 1),
        ("line", "pace", "pace", 1),
        ("line", "time_gap", "gap", 1),
        ("s1", "gap", "gap", 2),
    ]
    gap = trace.inputs[-1].value
    assert gap is not None
    assert (gap.value, gap.source.rulebook, gap.source.locator) == (
        20.0,
        "plan-s1",
        "sec. 2",
    )
    assert (trace.unknown, trace.assumptions, trace.left_out) == ((), (), ())
    assert d.unknown["column_length"] == Tally()


@pytest.mark.parametrize(
    ("spacing", "expected"),
    [
        (SPACING, 2206.0),
        # One gap per member: s1 84, s2 108; 2 x 84 + 108 + 2000.
        ((SPACING[0], Gap("gap", PER_UNIT)), 2276.0),
        # One gap in time per group: three instead of two.
        ((Gap("time_gap", PER_UNIT, at_pace=True), SPACING[1]), 3206.0),
    ],
)
def test_the_gap_convention_counts_n_or_n_minus_1_gaps(
    spacing: Sequence[Gap], expected: float
) -> None:
    assert length(measure(LINE, spacing=spacing)) == expected


def test_one_gap_per_unit_adds_one_gap_per_group_of_members() -> None:
    between = Fraction(repr(length(measure(LINE))))
    per_unit = Fraction(
        repr(length(measure(LINE, spacing=(SPACING[0], Gap("gap", PER_UNIT)))))
    )
    # s1, counted twice, spaces by 20 m; s2 by the 30 m of the line.
    assert per_unit - between == 2 * 20 + 30


def test_density_form_of_nested_groups() -> None:
    # Each group of 3 members at 0.05 /m: 60 m; 2 x 60 + 60 + 2000.
    d = measure(LINE, density=True)
    value = d["column_length"]
    assert value.value == 2180.0
    trace = value.derivation
    assert trace is not None
    assert trace.rule == "density"
    assert trace.settings == {
        "density": "density",
        "spacing": (("time_gap", "between", True),),
        "pace": "pace",
        "unknown": "propagate",
    }
    assert [(i.holder, i.parameter, i.role, i.instances) for i in trace.inputs] == [
        ("A", "column_length", "count", 4),
        ("B", "column_length", "count", 2),
        ("C", "column_length", "count", 1),
        ("D", "column_length", "count", 2),
        ("line", "density", "density", 3),
        ("line", "pace", "pace", 1),
        ("line", "time_gap", "gap", 1),
    ]


KM = (
    Parameter("road_space", unit="km"),
    Parameter("per_km", unit="1/km"),
    Parameter("minutes", unit="min"),
    Parameter("km_per_min", unit="km/min"),
)
KM_PLAN = ValueSet(
    "plan-c",
    "1",
    {
        "per_km": Value(10.0, Source("Plan"), Origin.STATEMENT, unit="1/km"),
        "minutes": Value(10.0, Source("Plan"), Origin.STATEMENT, unit="min"),
        # 60 km/h.
        "km_per_min": Value(1.0, Source("Plan"), Origin.STATEMENT, unit="km/min"),
    },
)


def test_members_over_a_density_plus_gaps_in_time_at_the_pace() -> None:
    # 60 members at 10 /km, plus 10 min at 60 km/h: 6 + 10 = 16 km.
    halves = tuple((Group(f"S{k}", ((Member(f"V{k}"), 30),)), 1) for k in (1, 2))
    d = column_length(
        Group("C", halves, values=KM_PLAN),
        output="road_space",
        density="per_km",
        spacing=[Gap("minutes", BETWEEN, at_pace=True)],
        pace="km_per_min",
        parameters=KM,
        unknown=PROPAGATE,
        edition="1",
    )
    assert (d["road_space"].value, d["road_space"].unit) == (16.0, "km")
    one = column_length(
        Group("C", ((Member("V"), 60),), values=KM_PLAN),
        output="road_space",
        density="per_km",
        spacing=[],
        parameters=KM,
        unknown=PROPAGATE,
        edition="1",
    )
    assert one["road_space"].value == 6.0


P = member("P", length=6.0)
Q = member("Q", length=10.0)


@pytest.mark.parametrize("count", [1, 2, 3, 7, 40])
def test_a_density_of_one_over_gap_plus_mean_length_is_the_geometric_length(
    count: int,
) -> None:
    # Mean length 8 m, gap 92 m: a density of 1 / 100 m.
    group = Group(
        "pq", ((P, count), (Q, count)), values=plan("pq", gap=92.0, density=0.01)
    )
    geometric = measure(group, spacing=[Gap("gap", PER_UNIT)])
    by_density = measure(group, density=True, spacing=[])
    assert length(geometric) == length(by_density) == 200.0 * count


def test_a_single_unit_has_no_gap_between_units() -> None:
    one = Group("one", ((A, 1),), values=plan("one", gap=20.0))
    between = measure(one, spacing=[Gap("gap", BETWEEN)])
    assert length(between) == 6.0
    assert [i.role for i in between["column_length"].derivation.inputs] == ["member"]  # type: ignore[union-attr]
    assert length(measure(one, spacing=[Gap("gap", PER_UNIT)])) == 26.0


def test_three_levels_of_groups() -> None:
    # Two lines and a third one, spaced by 100 m.
    top = Group("set", ((LINE, 2),), values=plan("set", gap=100.0))
    spacing = (Gap("gap", BETWEEN), *SPACING)
    # The set reads its own gap; the line its own; s2 inherits from the line.
    assert length(measure(top, spacing=spacing)) == 2 * 2206.0 + 100.0
    trace = measure(top, spacing=spacing)["column_length"].derivation
    assert trace is not None
    gaps = {
        (i.holder, i.parameter): i.instances for i in trace.inputs if i.role == "gap"
    }
    assert gaps == {
        ("set", "gap"): 1,
        ("line", "gap"): 2,
        ("line", "time_gap"): 2,
        ("s1", "gap"): 4,
    }


# The four states of a value -------------------------------------------------

K = member("K", length=NA("carried by B"))


def test_a_member_not_applicable_is_out_of_the_column() -> None:
    with_k = Group("s1", ((A, 2), (B, 1), (K, 1)), values=plan("s1", gap=20.0))
    carried = Group("s3", ((K, 2),))
    line = Group("line", ((with_k, 2), (S2, 1), (carried, 1)), values=LINE.values)
    d = measure(line)
    assert length(d) == 2206.0
    trace = d["column_length"].derivation
    assert trace is not None
    assert trace.left_out == (
        LeftOut("K", LeftOutCause.NOT_APPLICABLE, "carried by B", 4),
    )
    assert "K" not in trace.fixed_by
    assert d.left_out["column_length"] == Tally(("K",), 4)


def test_a_column_of_members_not_applicable_is_not_applicable() -> None:
    d = measure(Group("k", ((K, 2),), values=plan("k", gap=5.0)), spacing=[SPACING[1]])
    value = d["column_length"]
    assert value.state is ValueState.NOT_APPLICABLE
    assert (
        value.not_applicable == "not applicable to any member of 'k': K (carried by B)"
    )
    assert value.derivation is not None
    assert value.derivation.fixed_by == ("K",)


U = member("U", width=2.0)
WITH_U = Group("u", ((A, 1), (U, 3)), values=plan("u", gap=10.0))


def test_an_unknown_length_propagates_or_is_assumed() -> None:
    d = measure(WITH_U, spacing=[SPACING[1]])
    value = d["column_length"]
    assert value.to_be_set
    assert value.derivation is not None
    assert (value.derivation.unknown, value.derivation.fixed_by) == (("U",), ())
    assert value.derivation.bound is None  # additive: no bound
    assert d.unknown["column_length"] == Tally(("U",), 3)
    eight = chosen(8.0, "m")
    d = measure(WITH_U, OnUnknown.assume({"length": eight}), spacing=[SPACING[1]])
    # 6 + 3 x 8 + 3 gaps of 10 m.
    assert length(d) == 60.0
    trace = d["column_length"].derivation
    assert trace is not None
    assert trace.assumptions == (Assumption("length", eight, ("U",), 3),)
    assert trace.unknown == ("U",)
    assert d.assumed["column_length"] == Tally(("U",), 3)


BARE = Group("bare", ((C, 1), (D, 2)))


def test_a_value_of_a_group_is_read_on_the_group_its_ancestors_or_the_context() -> None:
    gap = [SPACING[1]]
    missing = measure(BARE, spacing=gap)["column_length"]
    assert missing.to_be_set
    assert missing.derivation is not None
    assert missing.derivation.unknown == ("bare",)
    context = plan("ctx", gap=25.0)
    from_context = measure(BARE, spacing=gap, context=context)
    # 8 + 2 x 5 + 2 gaps of 25 m.
    assert length(from_context) == 68.0
    trace = from_context["column_length"].derivation
    assert trace is not None
    read = next(i for i in trace.inputs if i.role == "gap")
    assert (read.holder, read.value) == (None, context.values["gap"])
    assert trace.fixed_by == ("C", "D", "gap")
    unset = measure(BARE, spacing=gap, context=plan("ctx", gap=None))
    assert unset["column_length"].derivation.unknown == ("gap",)  # type: ignore[union-attr]
    assert unset.unknown["column_length"] == Tally(("gap",), 1)
    # A value to be set on the group is not replaced by the context.
    shadow = Group("bare", ((C, 1), (D, 2)), values=plan("bare", gap=None))
    hidden = measure(shadow, spacing=gap, context=context)["column_length"]
    assert hidden.to_be_set
    assert hidden.derivation.unknown == ("bare",)  # type: ignore[union-attr]
    assumed = OnUnknown.assume({"gap": chosen(25.0, "m")})
    d = measure(BARE, assumed, spacing=gap)
    assert length(d) == 68.0
    assert d["column_length"].derivation.assumptions == (  # type: ignore[union-attr]
        Assumption("gap", chosen(25.0, "m"), ("bare",), 1),
    )


def test_the_pace_of_the_slowest_member_from_the_context() -> None:
    e = member("E", length=10.0, pace=500.0)
    f = member("F", length=12.0, pace=400.0)
    group = Group(
        "tg",
        ((Group("e", ((e, 2),)), 1), (Group("f", ((f, 1),)), 1)),
        values=plan("tg", time_gap=1.0, gap=5.0),
    )
    slowest = aggregate(
        group,
        {"pace": Aggregation.min("pace")},
        parameters=VOCABULARY,
        unknown=PROPAGATE,
        edition="1",
    )
    d = measure(group, context=slowest)
    # e: 2 x 10 + 5; f: 12; one gap of 1 min at 400 m/min.
    assert length(d) == 437.0
    trace = d["column_length"].derivation
    assert trace is not None
    pace = next(i for i in trace.inputs if i.role == "pace")
    assert pace.holder is None
    assert pace.value is not None
    assert pace.value.derivation is not None
    assert pace.value.derivation.fixed_by == ("F",)


def test_members_left_out_of_the_group_are_recorded() -> None:
    sub = LINE.without("line-x", ["D"], reason="D crosses apart")
    d = measure(sub)
    # s2 keeps C alone: 8, no gap; 2 x 64 + 8 + 2000.
    assert length(d) == 2136.0
    assert d.left_out["column_length"] == Tally(("D",), 2)


# Units ----------------------------------------------------------------------

#: The pace in km/h, the gaps in time in min, the column in m.
IN_KMH = tuple(
    Parameter("pace", unit="km/h") if p.name == "pace" else p for p in VOCABULARY
)


def line_values(**units: tuple[float, str]) -> ValueSet:
    """The values of the line, each with its unit."""
    source = Source("Plan of line", locator="sec. 2")
    return ValueSet(
        "plan-line",
        "1",
        {
            name: Value(x, source, Origin.STATEMENT, unit=unit)
            for name, (x, unit) in units.items()
        },
    )


def test_a_pace_in_km_h_covers_gaps_in_minutes() -> None:
    # 30 km/h is 500 m/min exactly: the line is 2206 m, as at 500 m/min.
    values = line_values(gap=(30.0, "m"), time_gap=(2.0, "min"), pace=(30.0, "km/h"))
    d = column_length(
        Group("line", LINE.members, values=values),
        output="column_length",
        member_length="length",
        spacing=SPACING,
        pace="pace",
        parameters=IN_KMH,
        unknown=PROPAGATE,
        edition="1",
    )
    assert length(d) == 2206.0
    trace = d["column_length"].derivation
    assert trace is not None
    assert trace.conversions == (
        Conversion("line", "pace", 30.0, "km/h", 500.0, "m/min", "50/3"),
    )
    pace = next(i for i in trace.inputs if i.role == "pace")
    assert pace.value == values.values["pace"]  # as read, in km/h


def test_lengths_and_gaps_are_read_in_the_unit_of_the_column() -> None:
    in_km = (*VOCABULARY, Parameter("column_km", unit="km"))
    d = column_length(
        LINE,
        output="column_km",
        member_length="length",
        spacing=SPACING,
        pace="pace",
        parameters=in_km,
        unknown=PROPAGATE,
        edition="1",
    )
    assert (d["column_km"].value, d["column_km"].unit) == (2.206, "km")
    trace = d["column_km"].derivation
    assert trace is not None
    assert [
        (c.holder, c.parameter, c.to_unit, c.factor) for c in trace.conversions
    ] == [
        ("A", "length", "km", "1/1000"),
        ("B", "length", "km", "1/1000"),
        ("C", "length", "km", "1/1000"),
        ("D", "length", "km", "1/1000"),
        ("line", "gap", "km", "1/1000"),
        ("line", "pace", "km/min", "1/1000"),
        ("s1", "gap", "km", "1/1000"),
    ]


def test_a_density_a_gap_and_an_assumed_length_convert() -> None:
    values = line_values(
        time_gap=(2.0, "min"), pace=(500.0, "m/min"), density=(50.0, "1/km")
    )
    d = measure(Group("line", LINE.members, values=values), density=True)
    # 50 /km is 0.05 /m: as in the unit of the column.
    assert length(d) == 2180.0
    assert d["column_length"].derivation.conversions == (  # type: ignore[union-attr]
        Conversion("line", "density", 50.0, "1/km", 0.05, "1/m", "1/1000"),
    )
    in_km = measure(_values("g", 0.02, unit="km"), spacing=[Gap("gap", BETWEEN)])
    assert length(in_km) == 32.0  # 2 x 6 m + 20 m
    assert in_km["column_length"].derivation.conversions == (  # type: ignore[union-attr]
        Conversion("g", "gap", 0.02, "km", 20.0, "m", "1000"),
    )
    eight = chosen(0.008, "km")
    assumed = measure(WITH_U, OnUnknown.assume({"length": eight}), spacing=[SPACING[1]])
    assert length(assumed) == 60.0
    assert assumed["column_length"].derivation.conversions == (  # type: ignore[union-attr]
        Conversion(None, "length", 0.008, "km", 8.0, "m", "1000"),
    )


@pytest.fixture
def without_pint(monkeypatch: pytest.MonkeyPatch) -> None:
    """protee as installed without the optional extra ``units``."""
    monkeypatch.setitem(sys.modules, "pint", None)
    monkeypatch.setattr(_units, "_REGISTRY", None)


def test_without_the_extra_another_unit_is_refused(without_pint: None) -> None:
    with pytest.raises(ImportError, match=re.escape("protee[units]")):
        measure(_values("g", 0.02, unit="km"), spacing=[Gap("gap", BETWEEN)])
    assert length(measure(LINE)) == 2206.0


# Refusals -------------------------------------------------------------------


def _call(**changes: object) -> Callable[[], Derived]:
    arguments: dict[str, object] = {
        "output": "column_length",
        "member_length": "length",
        "spacing": SPACING,
        "pace": "pace",
        "parameters": VOCABULARY,
        "unknown": PROPAGATE,
        "edition": "1",
    }
    group = changes.pop("group", LINE)
    arguments.update(changes)
    return lambda: column_length(group, **arguments)  # type: ignore[arg-type]


def _one(group: Group, gap: GapCount = BETWEEN) -> dict[str, object]:
    return {"group": group, "spacing": [Gap("gap", gap)], "pace": None}


def _values(id: str, x: object, unit: str = "m", **options: str) -> Group:
    value = Value(x, Source("Plan"), Origin.STATEMENT, unit=unit, **options)  # type: ignore[arg-type]
    return Group(id, ((A, 2),), values=ValueSet(f"plan-{id}", "1", {"gap": value}))


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        (
            {"density": "density"},
            ValueError,
            "give member_length (geometric form) or density (density form), not both",
        ),
        ({"member_length": None}, ValueError, "give member_length"),
        (
            {"spacing": SPACING[:1]},
            ValueError,
            "spacing: 1 level given, group 'line' has 2 levels of groups",
        ),
        (
            {"member_length": None, "density": "density"},
            ValueError,
            (
                "spacing: 2 levels given, group 'line' has 2 levels of groups, the last "
                "one spaced by its density"
            ),
        ),
        (
            {"group": COLUMN},
            ValueError,
            (
                "group 'column' mixes members and groups: a column is measured level by "
                "level"
            ),
        ),
        (
            {"group": Group("deep", ((LINE, 1), (Group("flat", ((A, 1),)), 1)))},
            ValueError,
            (
                "group 'deep': its groups of members are at depths [1, 2]: a column is "
                "measured level by level"
            ),
        ),
        ({"pace": None}, ValueError, "the gaps of level 0 are in time: give pace"),
        (
            {"spacing": [Gap("gap", BETWEEN), Gap("gap", BETWEEN)]},
            ValueError,
            "pace given, but no gap is in time",
        ),
        (
            {"output": "note"},
            ValueError,
            "column_length gives a length: 'note' must have a unit",
        ),
        (
            {"member_length": "mass"},
            ValueError,
            (
                "member_length 'mass' in 't', the parameter is in 'm': cannot convert "
                "'t' to 'm': different dimensions"
            ),
        ),
        (
            {"member_length": None, "density": "gap", "spacing": SPACING[:1]},
            ValueError,
            (
                "density 'gap' in 'm', the parameter is in '1/m': cannot convert 'm' to "
                "'1/m': different dimensions"
            ),
        ),
        (
            {"spacing": [SPACING[0], Gap("mass", BETWEEN)]},
            ValueError,
            (
                "gap 'mass' in 't', the parameter is in 'm': cannot convert 't' to 'm': "
                "different dimensions"
            ),
        ),
        (
            {"pace": "mass"},
            ValueError,
            (
                "pace 'mass' in 't', the parameter is in 'm/min': cannot convert 't' to "
                "'m/min': different dimensions"
            ),
        ),
        (
            {"spacing": [Gap("note", BETWEEN, at_pace=True), SPACING[1]]},
            ValueError,
            "gap 'note' is in time: its parameter needs a unit of time",
        ),
        (
            {"unknown": KNOWN_ONLY},
            ValueError,
            (
                "known_only would shorten an additive value (geometric length of 'line'): "
                "use propagate or assume"
            ),
        ),
        (
            _one(Group("n", ((member("N", length=-1.0), 1),))),
            ValueError,
            "member 'N': 'length' must be at least 0 and finite, got -1.0",
        ),
        (
            _one(Group("n", ((member("N", length=math.inf), 1),))),
            ValueError,
            "member 'N': 'length' must be at least 0 and finite, got inf",
        ),
        (
            _one(Group("n", ((member("N", length="long"), 1),))),
            TypeError,
            "member 'N': 'length' must be a number, got 'long'",
        ),
        (
            {
                **_one(Group("u", ((U, 1),))),
                "unknown": OnUnknown.assume({"length": chosen(-2.0, "m")}),
            },
            ValueError,
            "the value assumed for 'length' must be at least 0 and finite, got -2.0",
        ),
        (
            _one(_values("g", math.inf)),
            ValueError,
            "group 'g': the gap 'gap' must be at least 0 and finite, got inf",
        ),
        (
            _one(_values("g", "wide")),
            TypeError,
            "group 'g': the gap 'gap' must be a number, got 'wide'",
        ),
        (
            _one(_values("g", None, not_applicable="no gap")),
            ValueError,
            (
                "group 'g': the gap 'gap' is not applicable (no gap): a column needs a "
                "number"
            ),
        ),
        (
            _one(_values("g", 3.0, unit="s")),
            ValueError,
            (
                "group 'g': 'gap' in 's', the parameter is in 'm': cannot convert 's' to "
                "'m': different dimensions"
            ),
        ),
        (
            {
                "group": Group("g", ((A, 2),), values=plan("g", density=0.0)),
                "member_length": None,
                "density": "density",
                "spacing": [],
                "pace": None,
            },
            ValueError,
            "group 'g': the density 'density' must be positive and finite, got 0.0",
        ),
        (
            {
                "group": Group(
                    "line",
                    LINE.members,
                    values=plan("line", gap=30.0, time_gap=2.0, pace=0.0),
                )
            },
            ValueError,
            "group 'line': the pace 'pace' must be positive and finite, got 0.0",
        ),
        (
            {**_one(BARE), "unknown": OnUnknown.assume({"length": chosen(8.0, "m")})},
            ValueError,
            "group 'bare': no value for 'gap' and no value assumed for it",
        ),
        (
            {
                **_one(Group("u", ((U, 1),), values=plan("u", gap=1.0))),
                "unknown": OnUnknown.assume({"gap": chosen(8.0, "m")}),
            },
            ValueError,
            "member 'U': no value for 'length' and no value assumed for it",
        ),
        (
            {"unknown": OnUnknown.assume({"speed": chosen(50.0, "km/h")})},
            ValueError,
            "a value is assumed for 'speed', which no rule reads",
        ),
        ({"context": {"gap": 1.0}}, TypeError, "context must be a ValueSet"),
        (
            {
                "group": Group(
                    "g",
                    ((A, 2),),
                    values=ValueSet(
                        "plan-g",
                        "1",
                        {"nowhere": Value(1.0, Source("Plan"), Origin.STATEMENT)},
                    ),
                ),
                "spacing": [Gap("gap", BETWEEN)],
                "pace": None,
            },
            ValueError,
            (
                "group 'g': value set plan-g (1): unknown parameter 'nowhere': declare it "
                "in parameters"
            ),
        ),
        ({"spacing": ["gap"]}, TypeError, "spacing[0] must be a Gap, got 'gap'"),
        ({"group": A}, TypeError, "group must be a Group"),
        ({"unknown": "assume"}, TypeError, "unknown must be an OnUnknown policy"),
        ({"edition": " "}, ValueError, "edition must be a non-empty string"),
        ({"output": "nowhere"}, ValueError, "unknown parameter 'nowhere'"),
    ],
)
def test_column_refusals(
    changes: dict[str, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        _call(**changes)()


@pytest.mark.parametrize(
    ("arguments", "error", "message"),
    [
        (
            ("gap", "between", 1),
            TypeError,
            "gap 'gap': at_pace must be a boolean, got 1",
        ),
        (("", "between"), ValueError, "parameter must be a non-empty string"),
        (("gap", "sometimes"), ValueError, "'sometimes' is not a valid GapCount"),
    ],
)
def test_gap_checks_its_fields(
    arguments: tuple[object, ...], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        Gap(*arguments)  # type: ignore[arg-type]


# Properties -----------------------------------------------------------------

LEVELS = (*VOCABULARY, Parameter("gap_0", unit="m"), Parameter("gap_1", unit="m"))
LENGTHS = st.floats(min_value=0.0, max_value=30.0, allow_nan=False)
COUNTS = st.integers(min_value=1, max_value=4)
CONVENTIONS = st.sampled_from((BETWEEN, PER_UNIT))
type Tree = list[list[tuple[float, int]]]

#: Leaf groups of members, each a list of (length, count).
TREES = st.lists(
    st.lists(st.tuples(LENGTHS, COUNTS), min_size=1, max_size=3),
    min_size=1,
    max_size=3,
)


def build(tree: Tree, gaps: tuple[float, float], counts: Sequence[int]) -> Group:
    """A column of the leaf groups of ``tree``, each counted ``counts[k]``
    times; the gaps are values of the column."""
    leaves = []
    for k, rows in enumerate(tree):
        members = tuple(
            (Member(f"M{k}-{j}", (sheet(f"sheet-{k}-{j}", length=x),)), c)
            for j, (x, c) in enumerate(rows)
        )
        leaves.append((Group(f"L{k}", members), counts[k % len(counts)]))
    values = ValueSet(
        "plan",
        "1",
        {
            f"gap_{level}": Value(g, Source("Plan"), Origin.STATEMENT, unit="m")
            for level, g in enumerate(gaps)
        },
    )
    return Group("top", tuple(leaves), values=values)


def run(group: Group, conventions: tuple[GapCount, GapCount]) -> Derived:
    return column_length(
        group,
        output="column_length",
        member_length="length",
        spacing=[Gap(f"gap_{level}", c) for level, c in enumerate(conventions)],
        parameters=LEVELS,
        unknown=PROPAGATE,
        edition="1",
    )


def oracle(
    tree: Tree,
    gaps: tuple[float, float],
    counts: Sequence[int],
    conventions: tuple[GapCount, GapCount],
) -> float:
    """The length by the formula, in fractions, independently of the
    implementation."""

    def spaced(units: list[tuple[Fraction, int]], level: int) -> Fraction:
        n = sum(c for _, c in units)
        k = n - 1 if conventions[level] is BETWEEN else n
        return sum((c * x for x, c in units), Fraction(0)) + k * Fraction(
            repr(gaps[level])
        )

    leaves = [
        (spaced([(Fraction(repr(x)), c) for x, c in rows], 1), counts[k % len(counts)])
        for k, rows in enumerate(tree)
    ]
    return float(spaced(leaves, 0))


GAPS = st.tuples(
    st.floats(min_value=0.0, max_value=500.0, allow_nan=False),
    st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
)


@given(
    TREES,
    GAPS,
    st.lists(COUNTS, min_size=3, max_size=3),
    st.tuples(CONVENTIONS, CONVENTIONS),
)
def test_the_length_agrees_with_the_formula(
    tree: Tree,
    gaps: tuple[float, float],
    counts: list[int],
    conventions: tuple[GapCount, GapCount],
) -> None:
    d = run(build(tree, gaps, counts), conventions)
    assert length(d) == oracle(tree, gaps, counts, conventions)


@given(
    TREES,
    GAPS,
    st.lists(COUNTS, min_size=3, max_size=3),
    st.tuples(CONVENTIONS, CONVENTIONS),
    LENGTHS,
    COUNTS,
)
def test_adding_a_member_never_shortens_the_column(
    tree: Tree,
    gaps: tuple[float, float],
    counts: list[int],
    conventions: tuple[GapCount, GapCount],
    extra: float,
    count: int,
) -> None:
    before = length(run(build(tree, gaps, counts), conventions))
    grown = [[*tree[0], (extra, count)], *tree[1:]]
    after = length(run(build(grown, gaps, counts), conventions))
    assert before is not None
    assert after is not None
    assert after >= before


@given(
    TREES,
    GAPS,
    st.lists(COUNTS, min_size=3, max_size=3),
    st.randoms(use_true_random=False),
)
def test_the_order_of_the_members_does_not_matter(
    tree: Tree, gaps: tuple[float, float], counts: list[int], rng: random.Random
) -> None:
    group = build(tree, gaps, counts)
    reference = run(group, (BETWEEN, PER_UNIT))
    rows = list(group.members)
    rng.shuffle(rows)
    leaves = []
    for sub, c in rows:
        assert isinstance(sub, Group)
        members = list(sub.members)
        rng.shuffle(members)
        leaves.append((Group(sub.id, tuple(members)), c))
    shuffled = run(
        Group("top", tuple(leaves), values=group.values), (BETWEEN, PER_UNIT)
    )
    assert shuffled == reference
    assert fingerprint(shuffled) == fingerprint(reference)


def test_identical_calls_give_equal_results() -> None:
    assert measure(LINE) == measure(LINE)
    assert measure(LINE, density=True) == measure(LINE, density=True)
    assert measure(S1, spacing=[SPACING[1]]) != measure(
        Group("s1", ((A, 2), (B, 2)), values=S1.values), spacing=[SPACING[1]]
    )
    assert {m.id for m, _ in LINE.flatten()} == {A.id, B.id, C.id, D.id}
