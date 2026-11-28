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

from collections.abc import Mapping
from dataclasses import dataclass

from protee.constraints import (
    Aggregation,
    Derived,
    Group,
    Member,
    OnUnknown,
    Origin,
    Parameter,
    Rulebook,
    RulebookKind,
    Source,
    Value,
    ValueSet,
    aggregate,
)

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
#: The unit of each parameter, by canonical name and by alias.
UNITS = {p.name: p.unit for p in PARAMETERS} | {
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
