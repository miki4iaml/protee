# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Shared cases for the tests of the derivations of
:mod:`protee.constraints`.

- a vocabulary of generic parameters, one of them with an alias;
- invented technical sheets (rulebooks of kind ``description``), no real
  equipment;
- members and nested groups built from them;
- the values a derivation may assume, chosen with a justification.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from protee.constraints import (
    Aggregation,
    Characteristic,
    Comparison,
    Derived,
    Gap,
    GapCount,
    Group,
    Member,
    NotApplicable,
    OnUnknown,
    Origin,
    Parameter,
    ResolvedValues,
    Rulebook,
    RulebookKind,
    Source,
    Value,
    ValueSet,
    aggregate,
    classify_by_thresholds,
    column_length,
    select_by_class,
)

#: What classify_by_thresholds and select_by_class read.
type Readable = ValueSet | ResolvedValues | Derived

#: Labels of a class, from the least to the most demanding.
CLASSES = ("C30", "C50", "C70")

PARAMETERS = (
    Parameter("width", unit="m", aliases={"sheet-alias": "overall_width"}),
    Parameter("mass", unit="t"),
    Parameter("speed", unit="km/h"),
    Parameter("length", unit="m"),
    Parameter("load_class"),
    Parameter("members"),
    Parameter("heavy"),
    Parameter("note"),
)
#: The parameters of the classification, the selection and the column, on
#: top of those of the members.
MORE_PARAMETERS = (
    Parameter("width_1", unit="m"),
    Parameter("width_2", unit="m"),
    Parameter("mass_1", unit="t"),
    Parameter("mass_2", unit="t"),
    Parameter("category"),
    Parameter("speed_2", unit="km/h"),
    Parameter("speed_3", unit="km/h"),
    Parameter("speed_cap", unit="km/h"),
    Parameter("column_length", unit="m"),
    Parameter("gap", unit="m"),
    Parameter("time_gap", unit="min"),
    Parameter("pace", unit="m/min"),
    Parameter("density", unit="1/m"),
)
VOCABULARY = (*PARAMETERS, *MORE_PARAMETERS)
#: The unit of each parameter, by canonical name and by alias.
UNITS = {p.name: p.unit for p in VOCABULARY} | {
    alias: p.unit for p in PARAMETERS for alias in p.aliases.values()
}

ALIAS_BOOK = Rulebook(
    "sheet-alias", RulebookKind.DESCRIPTION, {"en": "Sheet with an alias"}, "1"
)


@dataclass(frozen=True)
class NA:
    """A value declared not applicable, with its reason."""

    reason: str


type Given = float | str | NA | None


def given(x: Given, unit: str | None, source: Source) -> Value:
    """A value of a sheet: ``None`` is to be set, :class:`NA` not
    applicable."""
    if isinstance(x, NA):
        return Value(None, source, Origin.STATEMENT, unit=unit, not_applicable=x.reason)
    return Value(x, source, Origin.STATEMENT, unit=unit)


def sheet(book: str, edition: str = "1", /, **values: Given) -> ValueSet:
    """A technical sheet of rulebook ``book``, each value in the unit of
    its parameter."""
    source = Source(f"Sheet {book}", locator="p. 4")
    return ValueSet(
        book,
        edition,
        {name: given(x, UNITS.get(name), source) for name, x in values.items()},
    )


def member(id: str, **values: Given) -> Member:
    """A member with one sheet, ``sheet-<id>``; a parameter not given is
    absent from the sheet (unknown)."""
    return Member(id, (sheet(f"sheet-{id}", **values),))


def chosen(x: float | str, unit: str | None = None) -> Value:
    """A value assumed by a derivation: a declared choice."""
    return Value(
        x,
        Source("Planning note"),
        Origin.CHOICE,
        unit=unit,
        justification="no sheet: a planning choice",
    )


PROPAGATE = OnUnknown.propagate()
KNOWN_ONLY = OnUnknown.known_only("the members without a value are towed")

A = member("A", width=2.5, mass=12.0, speed=80.0, length=6.0, load_class="C30")
B = member("B", width=3.5, mass=30.0, speed=50.0, length=12.0, load_class="C70")
C = member("C", width=3.0, mass=20.0, speed=60.0, length=8.0, load_class="C50")
D = member("D", width=3.5, mass=8.0, speed=90.0, length=5.0, load_class="C30")

#: A pair of A and B, counted three times in a column with C.
PAIR = Group("pair", ((A, 2), (B, 1)))
COLUMN = Group("column", ((PAIR, 3), (C, 1)))


def derive(
    group: Group,
    rules: Mapping[str, Aggregation],
    unknown: OnUnknown = PROPAGATE,
    **options: object,
) -> Derived:
    """:func:`aggregate` with the shared vocabulary and edition ``"1"``."""
    return aggregate(
        group,
        rules,
        parameters=PARAMETERS,
        unknown=unknown,
        edition="1",
        **options,  # type: ignore[arg-type]
    )


# Classification and selection ---------------------------------------------

REGULATION_SRC = Source("Regulation C", locator="art. 3")


def regulation(**values: float | NA | None) -> ValueSet:
    """Values of a regulation, ``reg-c``, each in the unit of its
    parameter."""
    return ValueSet(
        "reg-c",
        "1",
        {
            name: (
                Value(None, REGULATION_SRC, Origin.RULEBOOK, unit=UNITS[name])
                if x is None
                else Value(
                    None,
                    REGULATION_SRC,
                    Origin.RULEBOOK,
                    unit=UNITS[name],
                    not_applicable=x.reason,
                )
                if isinstance(x, NA)
                else Value(x, REGULATION_SRC, Origin.RULEBOOK, unit=UNITS[name])
            )
            for name, x in values.items()
        },
    )


#: Thresholds of the width (3 m, 4 m) and of the mass (20 t, 40 t), and
#: the speeds of the classes 2 and 3.
REGULATION = regulation(
    width_1=3.0, width_2=4.0, mass_1=20.0, mass_2=40.0, speed_2=60.0, speed_3=40.0
)
CATEGORIES = ("1", "2", "3")
#: "up to" thresholds: a value equal to a threshold stays in the lower class.
WIDTH = Characteristic("width", ("width_1", "width_2"), Comparison.ABOVE)
MASS = Characteristic("mass", ("mass_1", "mass_2"), Comparison.ABOVE)
CHARACTERISTICS = (WIDTH, MASS)
#: The speed cap of each class; the first one has no value of its own.
SPEEDS: Mapping[str, str | NotApplicable] = {
    "1": NotApplicable("the general limits apply"),
    "2": "speed_2",
    "3": "speed_3",
}


def classify(
    subject: Readable,
    unknown: OnUnknown = PROPAGATE,
    *,
    characteristics: Sequence[Characteristic] = CHARACTERISTICS,
    thresholds: Readable = REGULATION,
    classes: Sequence[str] = CATEGORIES,
) -> Derived:
    """:func:`classify_by_thresholds` into ``category``, with the shared
    vocabulary, rulebook ``classes`` and edition ``"1"``."""
    return classify_by_thresholds(
        subject,
        characteristics=characteristics,
        thresholds=thresholds,
        classes=classes,
        output="category",
        parameters=VOCABULARY,
        unknown=unknown,
        rulebook="classes",
        edition="1",
    )


def select(
    subject: Readable,
    unknown: OnUnknown = PROPAGATE,
    *,
    table: Mapping[str, str | NotApplicable] = SPEEDS,
    values: Readable = REGULATION,
) -> Derived:
    """:func:`select_by_class` of ``speed_cap`` by ``category``, with the
    shared vocabulary, rulebook ``classes`` and edition ``"1"``."""
    return select_by_class(
        subject,
        by="category",
        table=table,
        values=values,
        output="speed_cap",
        parameters=VOCABULARY,
        unknown=unknown,
        rulebook="classes",
        edition="1",
    )


# Columns --------------------------------------------------------------------


def plan(id: str, **values: float | None) -> ValueSet:
    """The values of a group (gaps, density, pace), stated by a plan."""
    source = Source(f"Plan of {id}", locator="sec. 2")
    return ValueSet(
        f"plan-{id}",
        "1",
        {
            name: Value(x, source, Origin.STATEMENT, unit=UNITS[name])
            for name, x in values.items()
        },
    )


#: s1 spaces its members by 20 m; s2 by the 30 m of the line, which spaces
#: its groups by 2 min at 500 m/min, and gives a density of 0.05 /m.
S1 = Group("s1", ((A, 2), (B, 1)), values=plan("s1", gap=20.0))
S2 = Group("s2", ((C, 1), (D, 2)))
LINE = Group(
    "line",
    ((S1, 2), (S2, 1)),
    values=plan("line", gap=30.0, time_gap=2.0, pace=500.0, density=0.05),
)
#: Between the groups of the line, a gap in time; between members, in
#: distance.
SPACING = (
    Gap("time_gap", GapCount.BETWEEN, at_pace=True),
    Gap("gap", GapCount.BETWEEN),
)


def measure(
    group: Group,
    unknown: OnUnknown = PROPAGATE,
    *,
    density: bool = False,
    spacing: Sequence[Gap] | None = None,
    context: Readable | None = None,
) -> Derived:
    """:func:`column_length` into ``column_length``, geometric (lengths of
    ``length``) or by ``density``, with the shared vocabulary, pace
    ``pace`` and edition ``"1"``."""
    gaps = SPACING[: 1 if density else 2] if spacing is None else spacing
    timed = any(g.at_pace for g in gaps)
    return column_length(
        group,
        output="column_length",
        member_length=None if density else "length",
        density="density" if density else None,
        spacing=gaps,
        pace="pace" if timed else None,
        context=context,
        parameters=VOCABULARY,
        unknown=unknown,
        edition="1",
    )
