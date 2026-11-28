# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""classify_by_thresholds and select_by_class: oracles by hand, the
classification of article 3 of the order of 4 May 2006 and its speeds of
article 14 with the embedded value set, the four states of a value, the
policies for the unknown, refusals and properties."""

from __future__ import annotations

import itertools
import math
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction

import pytest
from derive_cases import (
    CATEGORIES,
    CHARACTERISTICS,
    KNOWN_ONLY,
    MASS,
    NA,
    PROPAGATE,
    REGULATION,
    SPEEDS,
    VOCABULARY,
    WIDTH,
    Given,
    Readable,
    chosen,
    classify,
    derive,
    regulation,
    select,
    sheet,
)
from hypothesis import given
from hypothesis import strategies as st

from protee.constraints import (
    Aggregation,
    ArcData,
    Assumption,
    Attribute,
    Characteristic,
    Comparison,
    Conversion,
    Derived,
    Group,
    LeftOut,
    LeftOutCause,
    Member,
    NotApplicable,
    OnUnknown,
    Origin,
    Parameter,
    Requirement,
    RequirementSet,
    RequirementStatus,
    ResolvedValues,
    RulebookValues,
    Source,
    Tally,
    Value,
    ValueSet,
    ValueState,
    _units,
    classify_by_thresholds,
    evaluate,
    fingerprint,
    resolve_values,
    select_by_class,
    verify_route,
)
from protee.constraints._table import _summary
from protee.graph import Digraph


def subject(**values: Given) -> ValueSet:
    """The sheet of a subject; a parameter not given is unknown."""
    return sheet("sheet-S", **values)


def category(derived: Derived) -> str | None:
    x = derived["category"].value
    assert x is None or isinstance(x, str)
    return x


def after(x: float) -> float:
    """The next float."""
    return math.nextafter(x, math.inf)


def rank(x: float, thresholds: Sequence[float]) -> int:
    """The oracle of an "up to" scale: one plus the thresholds below x."""
    return 1 + sum(x > b for b in thresholds)


# Oracles by hand -----------------------------------------------------------


def test_the_strongest_characteristic_decides() -> None:
    d = classify(subject(width=3.5, mass=50.0))
    value = d["category"]
    assert value.value == "3"
    assert value.unit is None
    assert value.origin is Origin.DERIVED
    assert (value.source.document, value.source.rulebook, value.source.edition) == (
        "classify_by_thresholds of classes",
        "classes",
        "1",
    )
    trace = value.derivation
    assert trace is not None
    assert (trace.name, trace.rule) == ("classify_by_thresholds", "highest_rank")
    assert trace.fixed_by == ("mass",)
    assert trace.settings == {
        "characteristics": {
            "mass": {"thresholds": ("mass_1", "mass_2"), "crossing": "above"},
            "width": {"thresholds": ("width_1", "width_2"), "crossing": "above"},
        },
        "classes": ("1", "2", "3"),
        "unknown": "propagate",
    }
    # Every characteristic and every threshold is an input, with its source.
    assert [(i.role, i.parameter, i.holder, i.state) for i in trace.inputs] == [
        ("characteristic", "mass", None, ValueState.KNOWN),
        ("threshold", "mass_1", None, ValueState.KNOWN),
        ("threshold", "mass_2", None, ValueState.KNOWN),
        ("characteristic", "width", None, ValueState.KNOWN),
        ("threshold", "width_1", None, ValueState.KNOWN),
        ("threshold", "width_2", None, ValueState.KNOWN),
    ]
    mass_2 = trace.inputs[2].value
    assert mass_2 == REGULATION.values["mass_2"]
    assert mass_2 is not None
    assert (mass_2.source.rulebook, mass_2.source.locator) == ("reg-c", "art. 3")
    assert (trace.unknown, trace.assumptions, trace.left_out) == ((), (), ())
    assert trace.bound is None
    assert d.unknown["category"] == Tally()
    assert d.assumed["category"] == Tally()
    assert d.left_out["category"] == Tally()


def test_ties_cite_every_characteristic_and_rank_1_cites_all() -> None:
    assert classify(subject(width=3.5, mass=30.0))["category"].derivation.fixed_by == (  # type: ignore[union-attr]
        "mass",
        "width",
    )
    low = classify(subject(width=2.0, mass=10.0))["category"]
    assert low.value == "1"
    assert low.derivation is not None
    assert low.derivation.fixed_by == ("mass", "width")


WIDTHS = (0.0, 2.5, 3.0, math.nextafter(3.0, math.inf), 3.5, 4.0, 4.5, math.inf)
MASSES = (0.0, 19.9, 20.0, math.nextafter(20.0, math.inf), 40.0, 40.1, math.inf)


@pytest.mark.parametrize(("width", "mass"), list(itertools.product(WIDTHS, MASSES)))
def test_classification_agrees_with_the_enumeration_of_ranks(
    width: float, mass: float
) -> None:
    ranks = {"width": rank(width, (3.0, 4.0)), "mass": rank(mass, (20.0, 40.0))}
    top = max(ranks.values())
    value = classify(subject(width=width, mass=mass))["category"]
    assert value.value == CATEGORIES[top - 1]
    assert value.derivation is not None
    assert value.derivation.fixed_by == tuple(
        sorted(c for c, r in ranks.items() if r == top)
    )


@pytest.mark.parametrize(
    ("crossing", "expected"),
    [
        (Comparison.ABOVE, ["1", "1", "2", "2", "2", "3"]),
        (Comparison.AT_LEAST, ["1", "2", "2", "2", "3", "3"]),
    ],
)
def test_the_crossing_places_a_value_at_a_threshold(
    crossing: Comparison, expected: list[str]
) -> None:
    c = Characteristic("width", ("width_1", "width_2"), crossing)
    widths = (2.0, 3.0, 3.5, math.nextafter(4.0, -math.inf), 4.0, 5.0)
    found = [category(classify(subject(width=w), characteristics=[c])) for w in widths]
    assert found == expected


@pytest.mark.parametrize(
    ("crossing", "expected"),
    [
        (Comparison.BELOW, ["1", "1", "2", "2", "3"]),
        (Comparison.AT_MOST, ["1", "2", "2", "3", "3"]),
    ],
)
def test_decreasing_thresholds_when_a_smaller_value_is_stronger(
    crossing: Comparison, expected: list[str]
) -> None:
    c = Characteristic("speed", ("speed_2", "speed_3"), crossing)
    limits = regulation(speed_2=60.0, speed_3=40.0)
    speeds = (80.0, 60.0, 50.0, 40.0, 30.0)
    found = [
        category(classify(subject(speed=s), characteristics=[c], thresholds=limits))
        for s in speeds
    ]
    assert found == expected


def test_a_count_from_a_threshold_moves_up_at_equality() -> None:
    # "from 10 members": the count derived by aggregate is the subject.
    vocabulary = (*VOCABULARY, Parameter("members_from"))
    limit = ValueSet(
        "reg-d",
        "1",
        {"members_from": Value(10, Source("Regulation D"), Origin.RULEBOOK)},
    )
    from_10 = Characteristic("members", ("members_from",), Comparison.AT_LEAST)

    def classes_of(count: int) -> str | None:
        group = Group("G", ((Member("A"), count),))
        counted = derive(group, {"members": Aggregation.count()})
        d = classify_by_thresholds(
            counted,
            characteristics=[from_10],
            thresholds=limit,
            classes=["below", "from"],
            output="category",
            parameters=vocabulary,
            unknown=PROPAGATE,
            rulebook="classes",
            edition="1",
        )
        return category(d)

    assert [classes_of(n) for n in (9, 10, 11)] == ["below", "from", "from"]


def test_infinity_reaches_the_last_class_and_an_infinite_threshold_is_never_passed() -> (
    None
):
    assert category(classify(subject(width=math.inf, mass=0.0))) == "3"
    open_top = regulation(width_1=3.0, width_2=math.inf)
    above = classify(
        subject(width=math.inf), characteristics=[WIDTH], thresholds=open_top
    )
    assert category(above) == "2"
    from_ = Characteristic("width", ("width_1", "width_2"), Comparison.AT_LEAST)
    at_least = classify(
        subject(width=math.inf), characteristics=[from_], thresholds=open_top
    )
    assert category(at_least) == "3"


def test_values_are_read_from_a_value_set_resolved_values_or_derived_values() -> None:
    as_set = classify(subject(width=3.5, mass=10.0))
    resolved = ResolvedValues(
        values=dict(subject(width=3.5, mass=10.0).values),
        discarded={},
        unused=(),
        missing=(),
    )
    assert classify(resolved) == as_set
    thresholds = ResolvedValues(
        values=dict(REGULATION.values), discarded={}, unused=(), missing=()
    )
    assert classify(subject(width=3.5, mass=10.0), thresholds=thresholds) == as_set
    # The envelope of a group, derived by aggregate, is classified.
    group = Group(
        "G",
        (
            (Member("A", (sheet("sheet-A", width=2.5, mass=12.0),)), 2),
            (Member("B", (sheet("sheet-B", width=3.5, mass=10.0),)), 1),
        ),
    )
    envelope = derive(
        group, {"width": Aggregation.max("width"), "mass": Aggregation.max("mass")}
    )
    from_group = classify(envelope)
    assert from_group["category"].value == "2"
    trace = from_group["category"].derivation
    assert trace is not None
    width = next(i for i in trace.inputs if i.parameter == "width")
    # The input keeps the derivation of the envelope: the chain is traced.
    assert width.value is not None
    assert width.value.derivation is not None
    assert width.value.derivation.fixed_by == ("B",)


# Article 3 of the order of 4 May 2006, with the embedded values -------------

OVERSIZE = "fr-oversize-transport-2006"
RV = RulebookValues.load(OVERSIZE)
LOAD = (
    Parameter("length", unit="m"),
    Parameter("width", unit="m"),
    Parameter("mass", unit="kg"),
    Parameter("category"),
    Parameter("speed_motorway", unit="km/h"),
    Parameter("speed_road", unit="km/h"),
    Parameter("speed_urban", unit="km/h"),
    *RV.parameters,
)
ART_3 = tuple(
    Characteristic(
        name,
        (f"oversize_{name}_category_1_max", f"oversize_{name}_category_2_max"),
        Comparison.ABOVE,
    )
    for name in ("length", "width", "mass")
)


def load(**values: float | NA | None) -> ValueSet:
    """The sheet of an invented load: lengths in m, mass in kg."""
    return load_in("kg", values)


def load_in(mass_unit: str, values: Mapping[str, float | NA | None]) -> ValueSet:
    """The sheet of an invented load, its mass in ``mass_unit``."""
    source = Source("Sheet of the load", locator="p. 1")
    units = {"length": "m", "width": "m", "mass": mass_unit}
    out: dict[str, Value] = {}
    for name, x in values.items():
        if isinstance(x, NA):
            out[name] = Value(
                None,
                source,
                Origin.STATEMENT,
                unit=units[name],
                not_applicable=x.reason,
            )
        else:
            out[name] = Value(x, source, Origin.STATEMENT, unit=units[name])
    return ValueSet("sheet-load", "1", out)


def article_3(
    load_: Readable,
    unknown: OnUnknown = PROPAGATE,
    parameters: Sequence[Parameter] = LOAD,
) -> Derived:
    return classify_by_thresholds(
        load_,
        characteristics=ART_3,
        thresholds=RV.values,
        classes=["1", "2", "3"],
        output="category",
        parameters=parameters,
        unknown=unknown,
        rulebook="oversize-category",
        edition="1",
    )


#: The mass of the load in t, the thresholds of the text in kg.
IN_TONNES = tuple(Parameter("mass", unit="t") if p.name == "mass" else p for p in LOAD)


@pytest.mark.parametrize(
    ("mass", "expected"),
    [(48.0, "1"), (after(48.0), "2"), (72.0, "2"), (after(72.0), "3")],
)
def test_a_threshold_is_converted_into_the_unit_of_its_characteristic(
    mass: float, expected: str
) -> None:
    sheet_ = load_in("t", {"length": 18.0, "width": 3.0, "mass": mass})
    d = article_3(sheet_, parameters=IN_TONNES)
    value = d["category"]
    assert value.value == expected
    trace = value.derivation
    assert trace is not None
    assert trace.conversions == (
        Conversion(
            None, "oversize_mass_category_1_max", 48000.0, "kg", 48.0, "t", "1/1000"
        ),
        Conversion(
            None, "oversize_mass_category_2_max", 72000.0, "kg", 72.0, "t", "1/1000"
        ),
    )
    # The input keeps the threshold as read, in kg, with its source.
    read = next(
        i for i in trace.inputs if i.parameter == "oversize_mass_category_2_max"
    )
    assert read.value == RV.values.values["oversize_mass_category_2_max"]
    # The table says it: values as read, then the conversions.
    if expected == "2" and mass == 72.0:
        assert _summary(value) == (
            "highest rank of length, mass, width: '2', fixed by 'mass' (72 t above "
            "48000 kg, art. 3); converted: 'oversize_mass_category_1_max' 48000 kg "
            "to 48 t (x1/1000), 'oversize_mass_category_2_max' 72000 kg to 72 t "
            "(x1/1000)"
        )


def test_a_characteristic_is_converted_into_the_unit_of_its_parameter() -> None:
    # 72 t is 72 000 kg exactly: the 2nd category, at the threshold.
    d = article_3(load_in("t", {"length": 18.0, "width": 3.0, "mass": 72.0}))
    assert d["category"].value == "2"
    assert d["category"].derivation.conversions == (  # type: ignore[union-attr]
        Conversion(None, "mass", 72.0, "t", 72000.0, "kg", "1000"),
    )
    d = classify(subject_in("width", 350.0, "cm"), characteristics=[WIDTH])
    assert d["category"].value == "2"
    assert d["category"].derivation.conversions == (  # type: ignore[union-attr]
        Conversion(None, "width", 350.0, "cm", 3.5, "m", "1/100"),
    )


def subject_in(name: str, x: float, unit: str) -> ValueSet:
    """A sheet whose value is in another unit than its parameter."""
    value = Value(x, Source("Sheet S"), Origin.STATEMENT, unit=unit)
    return ValueSet("sheet-S", "1", {name: value})


@pytest.fixture
def without_pint(monkeypatch: pytest.MonkeyPatch) -> None:
    """protee as installed without the optional extra ``units``."""
    monkeypatch.setitem(sys.modules, "pint", None)
    monkeypatch.setattr(_units, "_REGISTRY", None)


def test_without_the_extra_another_unit_is_refused(without_pint: None) -> None:
    with pytest.raises(ImportError, match=re.escape("protee[units]")):
        article_3(load(length=18.0), parameters=IN_TONNES)
    with pytest.raises(ImportError, match=re.escape("protee[units]")):
        classify(subject_in("width", 350.0, "cm"))
    # The same units need nothing.
    assert article_3(load(length=27.0))["category"].value == "3"


def oracle(length: float, width: float, mass: float) -> int:
    """Article 3: the strongest characteristic decides the category."""
    v = {k: x.value for k, x in RV.values.values.items()}

    def rank_(x: float, name: str) -> int:
        if x <= v[f"oversize_{name}_category_1_max"]:  # type: ignore[operator]
            return 1
        return 2 if x <= v[f"oversize_{name}_category_2_max"] else 3  # type: ignore[operator]

    return max(rank_(length, "length"), rank_(width, "width"), rank_(mass, "mass"))


@pytest.mark.parametrize(
    ("length", "width", "mass", "expected"),
    [
        (20.0, 3.0, 48000.0, "1"),
        (after(20.0), 3.0, 48000.0, "2"),
        (20.0, after(3.0), 48000.0, "2"),
        (20.0, 3.0, after(48000.0), "2"),
        (25.0, 4.0, 72000.0, "2"),
        (after(25.0), 4.0, 72000.0, "3"),
        (25.0, after(4.0), 72000.0, "3"),
        (25.0, 4.0, after(72000.0), "3"),
        (27.0, 3.5, 60000.0, "3"),
        (18.0, 3.0, 48000.0, "1"),
    ],
)
def test_article_3_exactly_at_its_thresholds(
    length: float, width: float, mass: float, expected: str
) -> None:
    d = article_3(load(length=length, width=width, mass=mass))
    assert d["category"].value == expected
    assert int(expected) == oracle(length, width, mass)


def test_article_3_cites_the_threshold_crossed_and_its_source() -> None:
    value = article_3(load(length=27.0, width=3.5, mass=60000.0))["category"]
    trace = value.derivation
    assert trace is not None
    assert trace.fixed_by == ("length",)
    crossed = next(
        i for i in trace.inputs if i.parameter == "oversize_length_category_2_max"
    )
    assert crossed.role == "threshold"
    assert crossed.value is not None
    assert crossed.value.value == 25.0
    assert (crossed.value.source.rulebook, crossed.value.source.locator) == (
        OVERSIZE,
        "art. 3",
    )


def test_propagate_is_decided_by_a_characteristic_at_the_highest_rank() -> None:
    # DD9: 27 m is the 3rd category whatever the mass.
    d = article_3(load(length=27.0, width=3.5))
    value = d["category"]
    assert value.value == "3"
    assert value.derivation is not None
    assert value.derivation.fixed_by == ("length",)
    assert value.derivation.unknown == ("mass",)
    assert value.derivation.bound is None
    assert d.unknown["category"] == Tally(("mass",), 1)


def test_propagate_leaves_the_class_to_be_set_with_its_bound() -> None:
    # 18 m and 3 m are of the 1st category, but the mass may raise it.
    d = article_3(load(length=18.0, width=3.0))
    value = d["category"]
    assert value.to_be_set
    trace = value.derivation
    assert trace is not None
    assert (trace.fixed_by, trace.unknown) == ((), ("mass",))
    assert (trace.bound, trace.bound_fixed_by) == ("1", ("length", "width"))
    # Without a known characteristic, no bound.
    nothing = article_3(load())["category"].derivation
    assert nothing is not None
    assert nothing.bound is None
    assert nothing.unknown == ("length", "mass", "width")


def test_known_only_classifies_the_known_characteristics() -> None:
    d = article_3(load(length=18.0, width=3.5), KNOWN_ONLY)
    value = d["category"]
    assert value.value == "2"
    trace = value.derivation
    assert trace is not None
    assert trace.fixed_by == ("width",)
    assert trace.unknown == ("mass",)
    assert trace.left_out == (
        LeftOut(
            "mass", LeftOutCause.UNKNOWN, "the members without a value are towed", 1
        ),
    )
    assert trace.settings["justification"] == "the members without a value are towed"
    assert d.left_out["category"] == Tally(("mass",), 1)
    # Nothing known: nothing to classify.
    assert article_3(load(), KNOWN_ONLY)["category"].to_be_set


def test_assume_takes_the_value_assumed_for_a_characteristic() -> None:
    assumed = Value(
        60000.0,
        Source("Planning note"),
        Origin.CHOICE,
        unit="kg",
        justification="the heaviest load planned",
    )
    d = article_3(load(length=18.0, width=3.0), OnUnknown.assume({"mass": assumed}))
    value = d["category"]
    assert value.value == "2"
    trace = value.derivation
    assert trace is not None
    assert trace.fixed_by == ("mass",)
    assert trace.unknown == ("mass",)
    assert trace.assumptions == (Assumption("mass", assumed, ("mass",), 1),)
    mass = next(i for i in trace.inputs if i.parameter == "mass")
    assert (mass.state, mass.value) == (ValueState.ASSUMED, assumed)
    assert d.assumed["category"] == Tally(("mass",), 1)


def test_a_characteristic_not_applicable_is_left_out() -> None:
    d = article_3(load(length=18.0, width=NA("no width: a liquid bulk"), mass=50000.0))
    value = d["category"]
    assert value.value == "2"
    trace = value.derivation
    assert trace is not None
    assert trace.left_out == (
        LeftOut("width", LeftOutCause.NOT_APPLICABLE, "no width: a liquid bulk", 1),
    )
    assert trace.unknown == ()
    # Its thresholds are not read.
    assert "oversize_width_category_1_max" not in {i.parameter for i in trace.inputs}
    assert d.left_out["category"] == Tally(("width",), 1)


def test_a_class_without_any_applicable_characteristic_is_not_applicable() -> None:
    value = classify(subject(width=NA("carried"), mass=NA("weighed apart")))["category"]
    assert value.state is ValueState.NOT_APPLICABLE
    assert value.not_applicable == (
        "no characteristic applies: mass (weighed apart), width (carried)"
    )
    assert value.derivation is not None
    assert value.derivation.fixed_by == ("mass", "width")


@pytest.mark.parametrize("mass_2", [None, "absent"])
def test_a_threshold_to_be_set_makes_its_characteristic_unknown(
    mass_2: str | None,
) -> None:
    given_ = {"width_1": 3.0, "width_2": 4.0, "mass_1": 20.0}
    limits = regulation(**given_) if mass_2 else regulation(**given_, mass_2=None)
    d = classify(subject(width=3.5, mass=50.0), thresholds=limits)
    value = d["category"]
    assert value.to_be_set
    assert value.derivation is not None
    assert value.derivation.unknown == ("mass_2",)
    assert value.derivation.bound == "2"
    # The width at the highest rank decides.
    assert category(classify(subject(width=5.0, mass=50.0), thresholds=limits)) == "3"
    # known_only leaves the mass out; assume takes a threshold.
    only = classify(subject(width=3.5, mass=50.0), KNOWN_ONLY, thresholds=limits)
    assert category(only) == "2"
    assert only["category"].derivation.left_out[0].name == "mass"  # type: ignore[union-attr]
    assumed = OnUnknown.assume({"mass_2": chosen(60.0, "t")})
    assert (
        category(classify(subject(width=3.5, mass=50.0), assumed, thresholds=limits))
        == "2"
    )


# Refusals -------------------------------------------------------------------


def _call(**changes: object) -> Callable[[], Derived]:
    arguments: dict[str, object] = {
        "characteristics": CHARACTERISTICS,
        "thresholds": REGULATION,
        "classes": CATEGORIES,
        "output": "category",
        "parameters": VOCABULARY,
        "unknown": PROPAGATE,
        "rulebook": "classes",
        "edition": "1",
    }
    subject_ = changes.pop("subject", subject(width=3.5, mass=10.0))
    arguments.update(changes)
    return lambda: classify_by_thresholds(subject_, **arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        (
            {
                "thresholds": regulation(
                    width_1=4.0, width_2=3.0, mass_1=20.0, mass_2=40.0
                )
            },
            ValueError,
            (
                "characteristic 'width': thresholds must increase strictly for 'above', "
                "got 4 m then 3 m"
            ),
        ),
        (
            {
                "thresholds": regulation(
                    width_1=3.0, width_2=3.0, mass_1=20.0, mass_2=40.0
                )
            },
            ValueError,
            "thresholds must increase strictly",
        ),
        (
            {
                "characteristics": [
                    Characteristic("width", ("width_1", "width_2"), Comparison.BELOW)
                ]
            },
            ValueError,
            (
                "characteristic 'width': thresholds must decrease strictly for 'below', "
                "got 3 m then 4 m"
            ),
        ),
        (
            {
                "characteristics": [
                    WIDTH,
                    Characteristic("mass", ("mass_1",), Comparison.ABOVE),
                ]
            },
            ValueError,
            "characteristic 'mass' has 1 threshold, the 3 classes need 2",
        ),
        (
            {"classes": ["1", "2"]},
            ValueError,
            "characteristic 'mass' has 2 thresholds, the 2 classes need 1",
        ),
        ({"classes": ["1", "2", "2"]}, ValueError, "classes: '2' given twice"),
        ({"classes": ["1"]}, ValueError, "classes: at least two labels, got ['1']"),
        ({"classes": ["1", "", "3"]}, ValueError, "class must be a non-empty string"),
        ({"classes": "123"}, TypeError, "classes is a sequence of labels"),
        ({"characteristics": [WIDTH, WIDTH]}, ValueError, "'width' given twice"),
        ({"characteristics": []}, ValueError, "no characteristic: give at least one"),
        (
            {"characteristics": ["width"]},
            TypeError,
            "characteristics[0] must be a Characteristic",
        ),
        ({"output": "width"}, ValueError, "'width' must have no unit, got 'm'"),
        ({"output": "nowhere"}, ValueError, "unknown parameter 'nowhere'"),
        (
            {
                "characteristics": [
                    WIDTH,
                    Characteristic("mass", ("width_1", "width_2"), Comparison.ABOVE),
                ]
            },
            ValueError,
            (
                "threshold 'width_1' of 'mass' in 'm', the parameter is in 't': "
                "cannot convert 'm' to 't': different dimensions"
            ),
        ),
        (
            {
                "characteristics": [
                    Characteristic("width", ("mass_1", "mass_2"), Comparison.ABOVE),
                    MASS,
                ],
                "thresholds": regulation(mass_1=20.0, mass_2=40.0),
            },
            ValueError,
            (
                "threshold 'mass_1' serves characteristics in 't' and in 'm': give "
                "each its own threshold"
            ),
        ),
        (
            {
                "subject": ValueSet(
                    "sheet-S",
                    "1",
                    {
                        "width": Value(
                            3.0, Source("Sheet S"), Origin.STATEMENT, unit="s"
                        )
                    },
                )
            },
            ValueError,
            (
                "subject: 'width' in 's', the parameter is in 'm': cannot convert 's' to "
                "'m': different dimensions"
            ),
        ),
        (
            {"thresholds": regulation(width_1=NA("none"), width_2=4.0)},
            ValueError,
            "threshold 'width_1' is not applicable: a threshold is a number",
        ),
        (
            {"subject": subject(width="wide", mass=10.0)},
            TypeError,
            "characteristic 'width' must be a number, got 'wide'",
        ),
        (
            {
                "thresholds": ValueSet(
                    "reg-c",
                    "1",
                    {
                        **REGULATION.values,
                        "width_1": Value("3", Source("Reg"), Origin.RULEBOOK, unit="m"),
                    },
                )
            },
            TypeError,
            "threshold 'width_1' must be a number, got '3'",
        ),
        (
            {
                "subject": subject(mass=10.0),
                "unknown": OnUnknown.assume({"width": chosen("wide", "m")}),
            },
            TypeError,
            "the value assumed for 'width' must be a number, got 'wide'",
        ),
        (
            {
                "subject": subject(width=3.5),
                "unknown": OnUnknown.assume({"width": chosen(3.0, "m")}),
            },
            ValueError,
            "subject: no value for 'mass' and no value assumed for it",
        ),
        (
            {"unknown": OnUnknown.assume({"speed": chosen(50.0, "km/h")})},
            ValueError,
            "a value is assumed for 'speed', which no rule reads",
        ),
        (
            {"subject": sheet("sheet-S", width=3.0, nowhere=1.0)},
            ValueError,
            (
                "subject: value set sheet-S (1): unknown parameter 'nowhere': declare it "
                "in parameters"
            ),
        ),
        ({"subject": {"width": 3.0}}, TypeError, "subject must be a ValueSet"),
        ({"unknown": "propagate"}, TypeError, "unknown must be an OnUnknown policy"),
        ({"rulebook": ""}, ValueError, "rulebook must be a non-empty string"),
        ({"edition": ""}, ValueError, "edition must be a non-empty string"),
    ],
)
def test_classify_refusals(
    changes: dict[str, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        _call(**changes)()


@pytest.mark.parametrize(
    ("arguments", "error", "message"),
    [
        (
            ("width", (), "above"),
            ValueError,
            "characteristic 'width' needs a threshold",
        ),
        (
            ("width", ("w1", "w1"), "above"),
            ValueError,
            "characteristic 'width': threshold 'w1' given twice",
        ),
        (("width", "w1", "above"), TypeError, "got the string 'w1'"),
        (("width", ("w1", ""), "above"), ValueError, "threshold must be a non-empty"),
        (("", ("w1",), "above"), ValueError, "parameter must be a non-empty string"),
        (("width", ("w1",), "over"), ValueError, "'over' is not a valid Comparison"),
    ],
)
def test_characteristic_checks_its_fields(
    arguments: tuple[object, object, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        Characteristic(*arguments)  # type: ignore[arg-type]


# Properties -----------------------------------------------------------------

VALUES = st.one_of(
    st.sampled_from((0.0, 3.0, 4.0, 20.0, 40.0, math.inf)),
    st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
)


@given(VALUES, VALUES, st.floats(min_value=0.0, max_value=50.0, allow_nan=False))
def test_raising_a_characteristic_never_lowers_the_class(
    width: float, mass: float, more: float
) -> None:
    before = category(classify(subject(width=width, mass=mass)))
    after_ = category(classify(subject(width=width, mass=mass + more)))
    assert before is not None
    assert after_ is not None
    assert CATEGORIES.index(after_) >= CATEGORIES.index(before)


LENGTH = Characteristic("length", ("width_1", "width_2"), Comparison.AT_LEAST)


@given(VALUES, VALUES, VALUES, st.permutations((WIDTH, MASS, LENGTH)))
def test_the_order_of_the_characteristics_does_not_matter(
    width: float, mass: float, length: float, order: list[Characteristic]
) -> None:
    given_ = subject(width=width, mass=mass, length=length)
    reference = classify(given_, characteristics=(WIDTH, MASS, LENGTH))
    shuffled = classify(given_, characteristics=order)
    assert shuffled == reference
    assert fingerprint(shuffled) == fingerprint(reference)
    ranks = (
        rank(width, (3.0, 4.0)),
        rank(mass, (20.0, 40.0)),
        1 + (length >= 3.0) + (length >= 4.0),
    )
    assert shuffled["category"].value == CATEGORIES[max(ranks) - 1]


# select_by_class ------------------------------------------------------------


def test_the_class_selects_its_value() -> None:
    classified = classify(subject(width=3.5, mass=50.0))
    d = select(classified)
    value = d["speed_cap"]
    assert (value.value, value.unit, value.origin) == (40.0, "km/h", Origin.DERIVED)
    assert value.source.document == "select_by_class of classes"
    trace = value.derivation
    assert trace is not None
    assert (trace.name, trace.rule, trace.fixed_by) == (
        "select_by_class",
        "table",
        ("category",),
    )
    assert trace.settings == {
        "by": "category",
        "table": {"2": "speed_2", "3": "speed_3"},
        "not_applicable": {"1": "the general limits apply"},
        "unknown": "propagate",
    }
    cls, chosen_ = trace.inputs
    assert (cls.role, cls.parameter, cls.holder) == ("class", "category", None)
    # The class keeps its own derivation: select -> classify.
    assert cls.value == classified["category"]
    assert (chosen_.role, chosen_.parameter, chosen_.value) == (
        "chosen",
        "speed_3",
        REGULATION.values["speed_3"],
    )
    assert d.unknown["speed_cap"] == Tally()


def test_a_table_with_a_value_for_every_class() -> None:
    table = {"1": "speed_2", "2": "speed_2", "3": "speed_3"}
    value = select(classify(subject(width=2.0, mass=10.0)), table=table)["speed_cap"]
    assert value.value == 60.0
    assert value.derivation is not None
    assert "not_applicable" not in value.derivation.settings
    assert value.derivation.settings["table"] == table


def test_the_value_selected_is_converted_into_the_unit_of_the_output() -> None:
    in_ms = (*VOCABULARY, Parameter("speed_ms", unit="m/s"))

    def to_ms(classified: Derived, unknown: OnUnknown) -> Value:
        return select_by_class(
            classified,
            by="category",
            table=SPEEDS,
            values=regulation(speed_2=60.0, speed_3=None),
            output="speed_ms",
            parameters=in_ms,
            unknown=unknown,
            rulebook="classes",
            edition="1",
        )["speed_ms"]

    # 60 km/h is 50/3 m/s, rounded once; the input keeps the km/h.
    value = to_ms(classify(subject(width=3.5, mass=10.0)), PROPAGATE)
    assert (value.value, value.unit) == (float(Fraction(50, 3)), "m/s")
    trace = value.derivation
    assert trace is not None
    assert trace.conversions == (
        Conversion(
            None, "speed_2", 60.0, "km/h", float(Fraction(50, 3)), "m/s", "5/18"
        ),
    )
    assert trace.inputs[1].value is not None
    assert trace.inputs[1].value.unit == "km/h"
    # A value assumed in km/h is converted too: 45 km/h is 12.5 m/s.
    assumed = OnUnknown.assume({"speed_3": chosen(45.0, "km/h")})
    value = to_ms(classify(subject(width=5.0)), assumed)
    assert value.value == 12.5
    assert value.derivation is not None
    assert value.derivation.conversions == (
        Conversion(None, "speed_3", 45.0, "km/h", 12.5, "m/s", "5/18"),
    )


def test_a_class_without_a_value_of_its_own_is_not_applicable() -> None:
    value = select(classify(subject(width=2.0, mass=10.0)))["speed_cap"]
    assert value.state is ValueState.NOT_APPLICABLE
    assert value.not_applicable == (
        "class '1' has no value of its own: the general limits apply"
    )
    assert value.value is None
    assert value.derivation is not None
    assert value.derivation.fixed_by == ("category",)


def test_a_class_not_in_the_table_is_refused() -> None:
    four = ValueSet(
        "sheet-S", "1", {"category": Value("4", Source("Sheet S"), Origin.STATEMENT)}
    )
    with pytest.raises(
        ValueError, match=re.escape("class '4' is not in the table ['1', '2', '3']")
    ):
        select(four)


def test_an_unknown_class_propagates_or_is_assumed() -> None:
    unknown = classify(subject(width=2.0))  # mass unknown: class to be set
    d = select(unknown)
    value = d["speed_cap"]
    assert value.to_be_set
    assert value.derivation is not None
    assert value.derivation.unknown == ("category",)
    assert len(value.derivation.inputs) == 1
    assert d.unknown["speed_cap"] == Tally(("category",), 1)
    assumed = chosen("2")
    d = select(unknown, OnUnknown.assume({"category": assumed}))
    value = d["speed_cap"]
    assert value.value == 60.0
    assert value.derivation is not None
    assert value.derivation.assumptions == (
        Assumption("category", assumed, ("category",), 1),
    )
    assert d.assumed["speed_cap"] == Tally(("category",), 1)


def test_a_value_selected_to_be_set_or_not_applicable_propagates() -> None:
    three = classify(subject(width=5.0))
    open_ = regulation(speed_2=60.0, speed_3=None)
    d = select(three, values=open_)
    assert d["speed_cap"].to_be_set
    assert d["speed_cap"].derivation.unknown == ("speed_3",)  # type: ignore[union-attr]
    assert d["speed_cap"].derivation.fixed_by == ()  # type: ignore[union-attr]
    assumed = OnUnknown.assume({"speed_3": chosen(45.0, "km/h")})
    assert select(three, assumed, values=open_)["speed_cap"].value == 45.0
    closed = regulation(speed_2=60.0, speed_3=NA("closed to such loads"))
    value = select(three, values=closed)["speed_cap"]
    assert value.not_applicable == (
        "the value 'speed_3' of class '3' is not applicable: closed to such loads"
    )
    assert value.derivation is not None
    assert value.derivation.left_out == (
        LeftOut("speed_3", LeftOutCause.NOT_APPLICABLE, "closed to such loads", 1),
    )


def test_a_class_not_applicable_gives_a_value_not_applicable() -> None:
    none = classify(subject(width=NA("carried"), mass=NA("carried")))
    d = select(none)
    value = d["speed_cap"]
    assert value.not_applicable == (
        "the class 'category' is not applicable: no characteristic applies: "
        "mass (carried), width (carried)"
    )
    assert d.left_out["speed_cap"] == Tally(("category",), 1)


def _select(**changes: object) -> Callable[[], Derived]:
    arguments: dict[str, object] = {
        "by": "category",
        "table": SPEEDS,
        "values": REGULATION,
        "output": "speed_cap",
        "parameters": VOCABULARY,
        "unknown": PROPAGATE,
        "rulebook": "classes",
        "edition": "1",
    }
    subject_ = changes.pop("subject", classify(subject(width=3.5)))
    arguments.update(changes)
    return lambda: select_by_class(subject_, **arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        (
            {"unknown": KNOWN_ONLY},
            ValueError,
            "known_only does not apply to a single class: use propagate or assume",
        ),
        ({"table": {}}, ValueError, "the table is empty"),
        (
            {"table": {"1": 50.0}},
            TypeError,
            "table['1'] must be a parameter or NotApplicable",
        ),
        ({"table": {"1": ""}}, ValueError, "table['1'] must be a non-empty string"),
        ({"table": {"": "speed_2"}}, ValueError, "class must be a non-empty string"),
        (
            {"table": {"1": "width"}},
            ValueError,
            (
                "class '1' selects 'width' in 'm', the parameter is in 'km/h': cannot "
                "convert 'm' to 'km/h': different dimensions"
            ),
        ),
        (
            {
                "subject": classify(subject(width=3.5, mass=10.0)),  # class 2
                "values": ValueSet(
                    "reg-c",
                    "1",
                    {"speed_2": Value(60.0, Source("Reg"), Origin.RULEBOOK, unit="m")},
                ),
            },
            ValueError,
            (
                "values: 'speed_2' in 'm', the parameter is in 'km/h': cannot convert 'm' "
                "to 'km/h': different dimensions"
            ),
        ),
        (
            {"table": {"1": "category"}},
            ValueError,
            (
                "class '1' selects 'category' in None, the parameter is in 'km/h': only "
                "a value with a unit converts, into a parameter with a unit"
            ),
        ),
        ({"table": {"1": "nowhere"}}, ValueError, "unknown parameter 'nowhere'"),
        ({"by": "nowhere"}, ValueError, "unknown parameter 'nowhere'"),
        (
            {
                "subject": ValueSet(
                    "s", "1", {"category": Value(3, Source("S"), Origin.STATEMENT)}
                )
            },
            TypeError,
            "the class 'category' must be a label, got 3",
        ),
        (
            {
                "subject": classify(subject(width=3.5)),
                "unknown": OnUnknown.assume({"category": chosen(3)}),
            },
            TypeError,
            "the value assumed for 'category' must be a label, got 3",
        ),
        (
            {"unknown": OnUnknown.assume({"speed_2": chosen(60.0, "km/h")})},
            ValueError,
            "subject: no value for 'category' and no value assumed for it",
        ),
        ({"values": [60.0]}, TypeError, "values must be a ValueSet"),
    ],
)
def test_select_refusals(
    changes: dict[str, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        _select(**changes)()


def test_not_applicable_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="reason must be a non-empty string"):
        NotApplicable(" ")


# Article 14, with the embedded values ---------------------------------------

GENERAL = "the 1st category follows the general limits (art. 14)"
URBAN_ONLY = "the 2nd category has a speed of its own in built-up areas only (art. 14)"
ART_14: Mapping[str, Mapping[str, str | NotApplicable]] = {
    "motorway": {
        "1": NotApplicable(GENERAL),
        "2": NotApplicable(URBAN_ONLY),
        "3": "oversize_category_3_speed_motorway",
    },
    "road": {
        "1": NotApplicable(GENERAL),
        "2": NotApplicable(URBAN_ONLY),
        "3": "oversize_category_3_speed_road",
    },
    "urban": {
        "1": NotApplicable(GENERAL),
        "2": "oversize_category_2_speed_urban",
        "3": "oversize_category_3_speed_urban",
    },
}


def speeds(classified: Derived) -> Derived:
    """Article 14: one call per kind of road, merged."""
    return Derived.merge(
        *(
            select_by_class(
                classified,
                by="category",
                table=table,
                values=RV.values,
                output=f"speed_{kind}",
                parameters=LOAD,
                unknown=PROPAGATE,
                rulebook="oversize-category",
                edition="1",
            )
            for kind, table in ART_14.items()
        )
    )


@pytest.mark.parametrize(
    ("sheet_", "expected"),
    [
        (
            {"length": 27.0, "width": 3.5, "mass": 60000.0},
            {"motorway": 60.0, "road": 50.0, "urban": 30.0},
        ),
        (
            {"length": 22.0, "width": 3.0, "mass": 40000.0},
            {"motorway": URBAN_ONLY, "road": URBAN_ONLY, "urban": 40.0},
        ),
        (
            {"length": 18.0, "width": 2.5, "mass": 30000.0},
            {"motorway": GENERAL, "road": GENERAL, "urban": GENERAL},
        ),
    ],
)
def test_article_14_speeds_by_category(
    sheet_: dict[str, float], expected: dict[str, float | str]
) -> None:
    classified = article_3(load(**sheet_))
    d = speeds(classified)
    for kind, x in expected.items():
        value = d[f"speed_{kind}"]
        if isinstance(x, str):
            label = classified["category"].value
            assert (
                value.not_applicable == f"class '{label}' has no value of its own: {x}"
            )
        else:
            assert (value.value, value.unit) == (x, "km/h")
            chosen_ = value.derivation.inputs[1].value  # type: ignore[union-attr]
            assert chosen_ is not None
            assert (chosen_.source.rulebook, chosen_.source.locator) == (
                OVERSIZE,
                "art. 14",
            )
    # Merged with the class, the values form one value set for resolve_values.
    merged = Derived.merge(classified, d)
    assert set(merged.values.values) == {
        "category",
        "speed_motorway",
        "speed_road",
        "speed_urban",
    }


def test_a_class_without_a_value_makes_the_requirement_not_applicable_in_verify_route() -> (
    None
):
    requirement = Requirement(
        "SPEED-ROAD",
        "speed_cap",
        {"en": "The load keeps under the speed cap on a road."},
        Source(
            "Order of 4 May 2006 on exceptional transport",
            rulebook=OVERSIZE,
            locator="art. 14",
        ),
        parameters={"maximum": "speed_road"},
        attributes={"length": "arc_length", "speed": "speed_limit"},
        scope=frozenset({"road"}),
    )
    reqs = RequirementSet((requirement,), LOAD, (RV.rulebook,))
    graph = Digraph.from_arcs(2, [(0, 1)])
    data = ArcData(
        1,
        (
            Attribute.categorical("kind", ["road"], ("motorway", "road", "urban")),
            Attribute.numeric("speed_limit", [80.0], unit="km/h"),
            Attribute.numeric("arc_length", [1.5], unit="km"),
        ),
        element="kind",
    )
    reason = f"value of 'speed_road' not applicable: class '2' has no value of its own: {URBAN_ONLY}"
    second = speeds(article_3(load(length=22.0, width=3.0, mass=40000.0)))
    values = resolve_values([second.values], reqs)
    check = verify_route((0,), reqs, graph, data, values)["SPEED-ROAD"]
    assert (check.status, check.reason) == (RequirementStatus.NOT_APPLICABLE, reason)
    effect = evaluate(requirement, graph, data, values)
    assert effect.not_applicable == reason
    third = speeds(article_3(load(length=27.0, width=3.5, mass=60000.0)))
    values = resolve_values([third.values], reqs)
    capped = verify_route(
        (0,), reqs, graph, data, values, weights=[1.5 / 50.0], criterion="duration"
    )
    assert capped["SPEED-ROAD"].status is RequirementStatus.APPLIED
