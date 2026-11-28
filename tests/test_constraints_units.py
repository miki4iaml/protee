# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Tests of the optional extra ``units`` of :mod:`protee.constraints`:
exact conversion of the inputs of a derivation into the unit of their
parameter, with its trace, and values shown as a person reads them.

The factors are checked against their definitions, not against pint: the
international foot is 0.3048 m and the inch 0.0254 m exactly, a tonne is
1000 kg, and 1 km/h is 1000 m in 3600 s.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from typing import Any

import pint
import pytest
from constraints_cases import MASS, requirement_set, values

from protee.constraints import (
    Aggregation,
    ArcData,
    Attribute,
    Comparison,
    Conversion,
    Derived,
    Group,
    Member,
    OnUnknown,
    Origin,
    Parameter,
    RequirementStatus,
    Source,
    Value,
    ValueSet,
    ValueState,
    _units,
    aggregate,
    readable,
    requirement_table,
    resolve_values,
    verify_route,
)
from protee.graph import Digraph

SHEET = Source("Sheet", locator="p. 4")
RULE = Source("Regulation A", locator="art. 3")

VOCABULARY = (
    Parameter("mass", unit="kg"),
    Parameter("width", unit="m"),
    Parameter("speed", unit="m/s"),
    Parameter("duration", unit="d"),
    Parameter("temperature", unit="K"),
    Parameter("ratio", unit="%"),
    Parameter("count"),
)

type Given = tuple[float | str | None, str | None]


def member(id: str, **given: Given) -> Member:
    """A member with one sheet; each value is ``(x, unit)``."""
    sheet = {
        name: Value(x, SHEET, Origin.STATEMENT, unit=unit)
        for name, (x, unit) in given.items()
    }
    return Member(id, (ValueSet(f"sheet-{id}", "1", sheet),))


def derive(
    members: Mapping[str, Mapping[str, Given]],
    rules: Mapping[str, Aggregation],
    unknown: OnUnknown | None = None,
) -> Derived:
    """:func:`aggregate` of a group of members of count 1."""
    group = Group("G", tuple((member(m, **v), 1) for m, v in members.items()))
    return aggregate(
        group,
        rules,
        parameters=VOCABULARY,
        unknown=OnUnknown.propagate() if unknown is None else unknown,
        edition="1",
    )


def threshold(x: float, unit: str) -> Value:
    return Value(x, RULE, Origin.RULEBOOK, unit=unit)


def chosen(x: float, unit: str) -> Value:
    return Value(
        x, Source("Planning note"), Origin.CHOICE, unit=unit, justification="a choice"
    )


def counted(
    given: Given, limit: Value, comparison: Comparison, of: str = "width"
) -> int:
    """How many of one member, of value ``given``, cross ``limit``."""
    rule = Aggregation.threshold_count(of, limit, comparison)
    value = derive({"A": {of: given}}, {"count": rule})["count"].value
    assert isinstance(value, int)
    return value


# Conversions ----------------------------------------------------------------


def test_a_value_is_converted_into_the_unit_of_its_parameter() -> None:
    d = derive(
        {"A": {"mass": (72, "t")}, "B": {"mass": (48000, "kg")}},
        {"mass": Aggregation.max("mass")},
    )
    mass = d["mass"]
    assert (mass.value, mass.unit) == (72000.0, "kg")
    assert isinstance(mass.value, float)
    trace = mass.derivation
    assert trace is not None
    assert trace.fixed_by == ("A",)
    assert trace.conversions == (
        Conversion("A", "mass", 72, "t", 72000.0, "kg", "1000"),
    )
    # The input keeps the value as read, in its own unit, with its source.
    a = next(i for i in trace.inputs if i.holder == "A")
    assert a.state is ValueState.KNOWN
    assert a.value is not None
    assert (a.value.value, a.value.unit, a.value.source.rulebook) == (
        72,
        "t",
        "sheet-A",
    )


@pytest.mark.parametrize(
    ("given", "expected", "factor"),
    [
        ((1, "ft"), Fraction(3048, 10000), "381/1250"),
        ((10, "ft"), Fraction(3048, 1000), "381/1250"),
        ((1, "in"), Fraction(254, 10000), "127/5000"),
        ((100, "in"), Fraction(254, 100), "127/5000"),
        ((0.1, "km"), Fraction(100), "1000"),
        ((1.1, "km"), Fraction(1100), "1000"),
        ((75, "cm"), Fraction(75, 100), "1/100"),
    ],
)
def test_lengths_convert_exactly(given: Given, expected: Fraction, factor: str) -> None:
    d = derive({"A": {"width": given}}, {"width": Aggregation.max("width")})
    width = d["width"]
    assert width.value == float(expected)
    trace = width.derivation
    assert trace is not None
    (conversion,) = trace.conversions
    assert (conversion.factor, conversion.converted) == (factor, float(expected))
    x = given[0]
    assert isinstance(x, (int, float))
    assert Fraction(repr(x)) * Fraction(factor) == expected


def test_a_converted_value_is_exact_at_a_threshold() -> None:
    # 0.1 km is 100 m exactly; 1.005 * 1000 is 1004.9999999999999 in floats.
    for km, m in ((0.1, 100), (1.005, 1005)):
        assert counted((km, "km"), threshold(m, "m"), Comparison.ABOVE) == 0
        assert counted((km, "km"), threshold(m, "m"), Comparison.AT_LEAST) == 1
    assert 1.005 * 1000 < 1005  # what float arithmetic would have missed
    # 72 t is 72000 kg: "up to 72 t" keeps it at the lower rank.
    tonnes = threshold(72000, "kg")
    assert counted((72, "t"), tonnes, Comparison.ABOVE, "mass") == 0
    assert counted((72.001, "t"), tonnes, Comparison.ABOVE, "mass") == 1
    assert counted((10, "ft"), threshold(3.048, "m"), Comparison.AT_MOST) == 1
    assert counted((10, "ft"), threshold(3.048, "m"), Comparison.BELOW) == 0


def test_a_threshold_is_converted_into_the_unit_of_its_parameter() -> None:
    rule = Aggregation.threshold_count("mass", threshold(72, "t"), Comparison.ABOVE)
    d = derive(
        {"A": {"mass": (72000, "kg")}, "B": {"mass": (72001, "kg")}},
        {"count": rule},
    )
    count = d["count"]
    assert count.value == 1
    trace = count.derivation
    assert trace is not None
    assert trace.fixed_by == ("B",)
    assert trace.conversions == (
        Conversion(None, "mass", 72, "t", 72000.0, "kg", "1000"),
    )
    limit = next(i for i in trace.inputs if i.role == "threshold")
    assert limit.value == threshold(72, "t")


def test_a_speed_converts_by_its_exact_factor() -> None:
    d = derive(
        {"A": {"speed": (90, "km/h")}, "B": {"speed": (1, "km/h")}},
        {"speed": Aggregation.sum("speed")},
    )
    speed = d["speed"]
    # 25 m/s + 5/18 m/s, summed exactly and rounded once.
    assert speed.value == float(Fraction(25) + Fraction(5, 18))
    trace = speed.derivation
    assert trace is not None
    assert [(c.holder, c.converted, c.factor) for c in trace.conversions] == [
        ("A", 25.0, "5/18"),
        ("B", float(Fraction(5, 18)), "5/18"),
    ]


def test_a_duration_times_a_pace_is_a_length() -> None:
    # 10 min at 60 km/h: 600 min.km/h, which is 10 km.
    x, factor = _units._convert(Fraction(600), "min*km/h", "km", "the gap")
    assert (x, factor) == (Fraction(10), Fraction(1, 60))
    assert _units._factor("1/km", "1/m", "the density") == Fraction(1, 1000)


def test_a_converted_sum_is_a_float() -> None:
    d = derive(
        {"A": {"mass": (2, "t")}, "B": {"mass": (500, "kg")}},
        {"mass": Aggregation.sum("mass")},
    )
    assert d["mass"].value == 2500.0
    assert isinstance(d["mass"].value, float)
    same = derive(
        {"A": {"mass": (2000, "kg")}, "B": {"mass": (500, "kg")}},
        {"mass": Aggregation.sum("mass")},
    )
    assert same["mass"].value == 2500
    assert isinstance(same["mass"].value, int)


def test_an_infinity_stays_an_infinity() -> None:
    d = derive(
        {"A": {"width": (math.inf, "km")}, "B": {"width": (3.5, "m")}},
        {"width": Aggregation.max("width")},
    )
    width = d["width"]
    assert width.value == math.inf
    trace = width.derivation
    assert trace is not None
    assert trace.conversions == (
        Conversion("A", "width", math.inf, "km", math.inf, "m", "1000"),
    )
    low = derive(
        {"A": {"width": (-math.inf, "km")}}, {"width": Aggregation.min("width")}
    )
    assert low["width"].value == -math.inf


def test_an_assumed_value_is_converted_and_traced() -> None:
    policy = OnUnknown.assume({"width": chosen(800, "cm")})
    d = derive(
        {"A": {"width": (3.5, "m")}, "U": {}},
        {"width": Aggregation.max("width")},
        policy,
    )
    width = d["width"]
    assert width.value == 8.0
    trace = width.derivation
    assert trace is not None
    assert trace.fixed_by == ("U",)
    assert trace.conversions == (
        Conversion(None, "width", 800, "cm", 8.0, "m", "1/100"),
    )
    (assumption,) = trace.assumptions
    assert assumption.value == chosen(800, "cm")
    u = next(i for i in trace.inputs if i.holder == "U")
    assert (u.state, u.value) == (ValueState.ASSUMED, chosen(800, "cm"))
    assert d.assumed["width"].names == ("U",)


def test_an_unused_assumed_value_is_checked_but_not_traced() -> None:
    policy = OnUnknown.assume({"width": chosen(800, "cm")})
    d = derive(
        {"A": {"width": (3.5, "m")}}, {"width": Aggregation.max("width")}, policy
    )
    trace = d["width"].derivation
    assert trace is not None
    assert trace.conversions == ()
    wrong = OnUnknown.assume({"width": chosen(8, "kg")})
    with pytest.raises(ValueError, match="different dimensions"):
        derive({"A": {"width": (3.5, "m")}}, {"width": Aggregation.max("width")}, wrong)


def test_a_value_without_a_number_keeps_its_unit_once_checked() -> None:
    d = derive(
        {"A": {"width": (3.5, "m")}, "P": {"width": (None, "cm")}},
        {"width": Aggregation.max("width")},
    )
    width = d["width"]
    assert width.to_be_set
    trace = width.derivation
    assert trace is not None
    assert (trace.unknown, trace.conversions, trace.bound) == (("P",), (), 3.5)
    with pytest.raises(ValueError, match="different dimensions"):
        derive({"P": {"width": (None, "kg")}}, {"width": Aggregation.max("width")})


def test_a_derived_value_is_a_function_of_the_values_not_of_their_units() -> None:
    in_metres = derive(
        {"A": {"width": (0.75, "m")}, "B": {"width": (3.048, "m")}},
        {"width": Aggregation.max("width")},
    )
    mixed = derive(
        {"A": {"width": (75, "cm")}, "B": {"width": (10, "ft")}},
        {"width": Aggregation.max("width")},
    )
    assert mixed["width"].value == in_metres["width"].value
    assert mixed == derive(
        {"B": {"width": (10, "ft")}, "A": {"width": (75, "cm")}},
        {"width": Aggregation.max("width")},
    )


# Refusals ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("parameter", "given", "message"),
    [
        (
            "mass",
            (3, "m"),
            (
                "member 'A': 'mass' in 'm', the parameter is in 'kg': cannot convert "
                "'m' to 'kg': different dimensions"
            ),
        ),
        (
            "duration",
            (2, "month"),
            (
                "member 'A': 'duration' in 'month', the parameter is in 'd': 'month' "
                "is a calendar convention: state its length in days"
            ),
        ),
        ("duration", (1, "a"), "'year' is a calendar convention"),
        ("duration", (1, "kiloyear"), "'year' is a calendar convention"),
        ("duration", (1, "leap_year"), "'leap_year' is a calendar convention"),
        ("duration", (1, "century"), "'century' is a calendar convention"),
        ("speed", (3, "km/month"), "'month' is a calendar convention"),
        (
            "temperature",
            (20, "degC"),
            (
                "member 'A': 'temperature' in 'degC', the parameter is in 'K': 'degC' "
                "has an offset: only a unit that keeps 0 at 0 converts"
            ),
        ),
        (
            "mass",
            (3, "veh/km"),
            (
                "member 'A': 'mass' in 'veh/km', the parameter is in 'kg': pint does "
                "not know the unit 'veh/km'"
            ),
        ),
        ("mass", (3, "2 kg"), "pint does not know the unit '2 kg'"),
        ("mass", (3, "kg)"), "pint does not know the unit 'kg)'"),
        (
            "ratio",
            (1, "decade"),
            (
                "member 'A': 'ratio' in 'decade', the parameter is in '%': pint cannot "
                "convert 'decade' to '%' exactly"
            ),
        ),
        (
            "mass",
            (3, None),
            (
                "member 'A': 'mass' in None, the parameter is in 'kg': only a value "
                "with a unit converts, into a parameter with a unit"
            ),
        ),
        ("count", (3, "kg"), "in 'kg', the parameter is in None: only a value"),
    ],
)
def test_a_unit_that_does_not_convert_is_refused(
    parameter: str, given: Given, message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        derive({"A": {parameter: given}}, {parameter: Aggregation.max(parameter)})


@pytest.mark.parametrize(
    ("given", "unit", "message"),
    [
        ("d", "year", "'year' is a calendar convention"),
        ("K", "degC", "'degC' has an offset"),
        ("kg", "veh", "pint does not know the unit 'veh'"),
    ],
)
def test_the_unit_of_the_parameter_is_checked_too(
    given: str, unit: str, message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        aggregate(
            Group("G", ((member("A", x=(1, given)), 1),)),
            {"x": Aggregation.max("x")},
            parameters=[Parameter("x", unit=unit)],
            unknown=OnUnknown.propagate(),
            edition="1",
        )


def test_a_text_does_not_convert() -> None:
    with pytest.raises(
        TypeError,
        match=re.escape(
            "member 'A': 'label' in 'kg', the parameter is in 't': a text does not "
            "convert"
        ),
    ):
        aggregate(
            Group("G", ((member("A", label=("C50", "kg")), 1),)),
            {"worst": Aggregation.strictest("label", ("C30", "C50"))},
            parameters=[Parameter("label", unit="t"), Parameter("worst")],
            unknown=OnUnknown.propagate(),
            edition="1",
        )


def test_the_calendar_units_are_units_of_pint() -> None:
    registry = _units._registry("the test")
    day = registry.parse_units("d").dimensionality
    with _units._LOCK:
        for name in _units._CALENDAR:
            assert registry.parse_units(name).dimensionality == day, name


# Without the extra ----------------------------------------------------------


@pytest.fixture
def without_pint(monkeypatch: pytest.MonkeyPatch) -> None:
    """pint not installed: its import fails, and no registry was made."""
    monkeypatch.setitem(sys.modules, "pint", None)
    monkeypatch.setattr(_units, "_REGISTRY", None)


EXTRA = "install the optional extra protee[units]"


def test_without_the_extra_another_unit_is_refused(without_pint: None) -> None:
    with pytest.raises(
        ImportError,
        match=re.escape(
            "member 'A': 'mass' in 't', the parameter is in 'kg': converting needs "
            f"pint, {EXTRA}"
        ),
    ):
        derive({"A": {"mass": (72, "t")}}, {"mass": Aggregation.max("mass")})
    with pytest.raises(ImportError, match=re.escape("the value assumed for 'width'")):
        derive(
            {"A": {"width": (3.5, "m")}},
            {"width": Aggregation.max("width")},
            OnUnknown.assume({"width": chosen(800, "cm")}),
        )
    rule = Aggregation.threshold_count("mass", threshold(72, "t"), Comparison.ABOVE)
    with pytest.raises(ImportError, match=re.escape("the threshold of 'mass' in 't'")):
        derive({"A": {"mass": (72000, "kg")}}, {"count": rule})
    with pytest.raises(ImportError, match=re.escape(f"readable needs pint, {EXTRA}")):
        readable(3.5, "m")


def test_without_the_extra_the_same_unit_needs_nothing(without_pint: None) -> None:
    d = derive(
        {"A": {"mass": (72000, "kg")}, "B": {"mass": (None, "kg")}},
        {"mass": Aggregation.max("mass")},
        OnUnknown.known_only("B is towed"),
    )
    assert d["mass"].value == 72000
    assert _units._REGISTRY is None


def test_the_same_unit_never_imports_pint() -> None:
    code = (
        "import sys\n"
        "from protee.constraints import (Aggregation, Group, Member, OnUnknown,\n"
        "    Origin, Parameter, Source, Value, ValueSet, aggregate)\n"
        "sheet = ValueSet('s', '1', {'w': Value(3.5, Source('S'), "
        "Origin.STATEMENT, unit='m')})\n"
        "d = aggregate(Group('G', ((Member('A', (sheet,)), 2),)),\n"
        "    {'w': Aggregation.max('w')}, parameters=[Parameter('w', unit='m')],\n"
        "    unknown=OnUnknown.propagate(), edition='1')\n"
        "assert d['w'].value == 3.5\n"
        "assert 'pint' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# The registry ---------------------------------------------------------------


def test_the_registry_is_made_once_for_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[Any] = []
    real = pint.UnitRegistry

    def counting(*args: Any, **kwargs: Any) -> Any:
        registry = real(*args, **kwargs)
        made.append(registry)
        return registry

    monkeypatch.setattr(pint, "UnitRegistry", counting)
    monkeypatch.setattr(_units, "_REGISTRY", None)
    start = threading.Barrier(8)

    def convert(k: int) -> tuple[Fraction | float, Fraction]:
        start.wait()
        return _units._convert(Fraction(90 + k % 2), "km/h", "m/s", f"thread {k}")

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(convert, range(8)))
    assert len(made) == 1
    assert _units._REGISTRY is made[0]
    assert results == [
        (Fraction(90 + k % 2) * Fraction(5, 18), Fraction(5, 18)) for k in range(8)
    ]
    assert made[0].non_int_type is Fraction
    assert _units._registry("again") is made[0]


# Display --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("x", "unit", "shown"),
    [
        (135, "s", "2 min 15 s"),
        (5400, "s", "1 h 30 min"),
        (93600, "s", "1 d 2 h"),
        (2, "d", "2 d"),
        (1, "week", "7 d"),
        (90, "min", "1 h 30 min"),
        (2.5, "h", "2 h 30 min"),
        (59.4, "s", "59 s"),
        (59.5, "s", "1 min"),
        (3570, "s", "59 min 30 s"),
        (3599.5, "s", "1 h"),
        (86430, "s", "1 d 1 min"),
        (0, "s", "0 s"),
        (0.4, "s", "0 s"),
        (-0.4, "s", "0 s"),
        (-90, "s", "-1 min 30 s"),
        (12400, "m", "12.4 km"),
        (12.4, "km", "12.4 km"),
        (1000, "m", "1 km"),
        (12345.6789, "m", "12.346 km"),
        (1, "mi", "1.609 km"),
        (350, "m", "350 m"),
        (0.75, "m", "0.75 m"),
        (75, "cm", "0.75 m"),
        (999.994, "m", "999.99 m"),
        (999.996, "m", "1 km"),
        (0.004, "m", "0 m"),
        (-350, "m", "-350 m"),
        (72, "t", "72 t"),
        (60, "km/h", "60 km/h"),
        (0.5, None, "0.5"),
        (3, "year", "3 year"),
        (20, "degC", "20 degC"),
        (10, "veh/km", "10 veh/km"),
        (math.inf, "km", "no limit"),
        (-math.inf, "s", "no limit"),
    ],
)
def test_a_number_is_shown_readably(x: float, unit: str | None, shown: str) -> None:
    assert readable(x, unit) == shown


def test_a_value_is_shown_readably() -> None:
    assert readable(Value(5400, SHEET, Origin.STATEMENT, unit="s")) == "1 h 30 min"
    assert readable(Value(None, SHEET, Origin.STATEMENT, unit="m")) == "to be set"
    na = Value(None, SHEET, Origin.STATEMENT, unit="m", not_applicable="carried by B")
    assert readable(na) == "not applicable"
    assert readable(Value("C50", SHEET, Origin.STATEMENT)) == "C50"
    assert readable(Value("C50", SHEET, Origin.STATEMENT, unit="t")) == "C50 t"


def test_readable_refuses_what_is_not_a_number() -> None:
    with pytest.raises(TypeError, match="a Value gives its own unit"):
        readable(Value(3.5, SHEET, Origin.STATEMENT, unit="m"), "m")
    with pytest.raises(TypeError, match="readable shows a Value or a number"):
        readable(True, "m")
    with pytest.raises(TypeError, match="readable shows a Value or a number"):
        readable([3.5], "m")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="NaN is not a value"):
        readable(math.nan, "m")


def test_the_table_shows_the_values_readably_on_demand() -> None:
    # The sheets give masses in kg; the vocabulary is in t. The derived
    # mass is exactly at the limit of the bridge, which it meets.
    reqs = requirement_set((MASS,))
    group = Group(
        "convoy",
        (
            (member("A", vehicle_mass=(40000, "kg")), 1),
            (member("B", vehicle_mass=(30, "t")), 2),
        ),
    )
    derived = aggregate(
        group,
        {"vehicle_mass": Aggregation.max("vehicle_mass")},
        parameters=reqs.parameters,
        unknown=OnUnknown.propagate(),
        edition="1",
        precedence=1,
    )
    vals = resolve_values([values(), derived.values], reqs)
    graph = Digraph.from_arcs(2, [(0, 1)])
    data = ArcData(
        1,
        (
            Attribute.categorical(
                "element", ["bridge"], ("road", "bridge", "underpass")
            ),
            Attribute.numeric("mass_limit", [40.0], unit="t", source=RULE),
        ),
        element="element",
    )
    check = verify_route((0,), reqs, graph, data, vals)
    assert check["ADM-MASS"].status is RequirementStatus.APPLIED
    (row,) = requirement_table(check, reqs, vals)
    trace = row.values["vehicle_mass"].derivation
    assert trace is not None
    assert trace.conversions == (
        Conversion("A", "vehicle_mass", 40000, "kg", 40.0, "t", "1/1000"),
    )
    plain = row.to_dict()
    assert "shown" not in plain["values"][0]
    # The conversion is said in the summary of the value.
    assert plain["values"][0]["derivation"]["summary"] == (
        "max of 'vehicle_mass' over convoy: 40 t, fixed by A (Sheet (1), p. 4); "
        "converted: A 40000 kg to 40 t (x1/1000)"
    )
    assert plain["values"][0]["derivation"]["conversions"] == [
        {
            "holder": "A",
            "parameter": "vehicle_mass",
            "value": 40000,
            "unit": "kg",
            "converted": 40.0,
            "to_unit": "t",
            "factor": "1/1000",
        }
    ]
    shown = row.to_dict(readable=True)["values"][0]
    assert (shown["value"], shown["shown"]) == (40.0, "40 t")
    assert [d["shown"] for d in shown["discarded"]] == ["44 t"]
    # Each input is shown as read, in its own unit.
    inputs = shown["derivation"]["inputs"]
    assert [i["value"]["shown"] for i in inputs] == ["40000 kg", "30 t"]
    # The display adds a key, and changes nothing else.
    assert without_shown(shown) == plain["values"][0]


def without_shown(entry: Any) -> Any:
    """The data without ``"shown"``, at every depth (a discarded value, the
    inputs of a derivation)."""
    if isinstance(entry, dict):
        return {k: without_shown(v) for k, v in entry.items() if k != "shown"}
    if isinstance(entry, list):
        return [without_shown(v) for v in entry]
    return entry


def test_the_table_needs_the_extra_only_to_show(without_pint: None) -> None:
    reqs = requirement_set((MASS,))
    vals = resolve_values([values()], reqs)
    data = ArcData(
        1,
        (
            Attribute.categorical("element", ["bridge"], ("road", "bridge")),
            Attribute.numeric("mass_limit", [40.0], unit="t", source=RULE),
        ),
        element="element",
    )
    check = verify_route((0,), reqs, Digraph.from_arcs(2, [(0, 1)]), data, vals)
    (row,) = requirement_table(check, reqs, vals)
    assert row.to_dict()["values"][0]["value"] == 44.0
    with pytest.raises(ImportError, match=re.escape(EXTRA)):
        row.to_dict(readable=True)
