# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Units, with the optional extra ``units`` (pint): exact conversion into
the unit of a parameter, and values shown as a person reads them.

pint is imported on first use, never by ``import protee.constraints``: a
value already in the unit of its parameter never needs it. Its registry
reads every number as a fraction (``non_int_type=Fraction``), so that a
factor is exact (``5/18`` from km/h to m/s, ``381/1250`` from ft to m),
and keeps no cache on disk.

The registry is the one piece of module data built on demand, an
exception to "no mutable global state": a constant, created once per
process under a lock, never changed by protee. Every call to pint holds the
same lock, since pint fills its caches as it goes; this holds with or
without the GIL.

A conversion is refused, rather than guessed, for:

- a unit pint does not know (a unit of count such as ``veh/km`` is written
  ``1/km``);
- two units of different dimensions;
- a unit with an offset, which does not keep 0 at 0 (``degC``);
- a calendar convention (a year or a month, whatever its kind): pint counts
  a year as 365.25 days and a month as a twelfth of it, where a life-cycle
  profile counts 366 and 30.5 days; such a duration is stated in days.
"""

from __future__ import annotations

import math
import threading
from fractions import Fraction
from tokenize import TokenError
from typing import Any

from protee.constraints._model import Value

__all__ = ["readable"]

#: The units of pint that stand for a year or a month, whatever its kind,
#: and their multiples (a prefixed unit, ``kiloyear``, is read as its base).
_CALENDAR = frozenset(
    {
        "year",
        "month",
        "century",
        "millennium",
        "eon",
        "common_year",
        "leap_year",
        "gregorian_year",
        "sidereal_year",
        "tropical_year",
        "sidereal_month",
        "tropical_month",
        "synodic_month",
    }
)

#: What pint raises for a unit it cannot read or convert: its own errors
#: derive from ``ValueError``, ``TypeError`` or ``AttributeError``; its
#: parser also lets through errors of the tokenizer and of the arithmetic.
_PINT_ERRORS = (ArithmeticError, AttributeError, TokenError, TypeError, ValueError)

_LOCK = threading.Lock()
#: The registry of the process, created by :func:`_registry` on first use.
_REGISTRY: Any = None


def _registry(need: str) -> Any:
    """The unit registry of the process, created on first use, once.

    Raises
    ------
    ImportError
        If pint is not installed; the message starts with ``need``, what
        needs it.
    """
    global _REGISTRY
    with _LOCK:
        if _REGISTRY is None:
            try:
                import pint
            except ImportError as err:
                raise ImportError(
                    f"{need} needs pint, install the optional extra protee[units]"
                ) from err
            _REGISTRY = pint.UnitRegistry(non_int_type=Fraction, cache_folder=None)
        return _REGISTRY


def _parse(registry: Any, unit: str) -> Any:
    """``unit`` read by pint, or ``None`` if pint cannot read it; the
    caller holds the lock."""
    try:
        return registry.parse_units(unit)
    except _PINT_ERRORS:
        return None


def _calendar(registry: Any, parsed: Any) -> str | None:
    """The first calendar unit of ``parsed``, if any; the caller holds the
    lock."""
    for name in sorted(parsed._units):
        for _, base, _ in registry.parse_unit_name(name):
            if base in _CALENDAR:
                return str(base)
    return None


def _factor(unit: str, to_unit: str, what: str) -> Fraction:
    """The exact factor from ``unit`` to ``to_unit``.

    ``what`` names the value converted, for the messages
    (``"member 'A': 'w'"``).

    Raises
    ------
    ImportError
        If pint is not installed (the optional extra ``units``).
    ValueError
        If pint does not know a unit, a unit is a calendar convention or has
        an offset, or the two units differ in dimension.
    """
    head = f"{what} in {unit!r}, the parameter is in {to_unit!r}"
    registry = _registry(f"{head}: converting")
    with _LOCK:
        parsed = []
        for u in (unit, to_unit):
            p = _parse(registry, u)
            if p is None:
                raise ValueError(f"{head}: pint does not know the unit {u!r}")
            if (name := _calendar(registry, p)) is not None:
                raise ValueError(
                    f"{head}: {name!r} is a calendar convention: state its length "
                    "in days"
                )
            parsed.append(p)
        source, target = parsed
        if source.dimensionality != target.dimensionality:
            raise ValueError(
                f"{head}: cannot convert {unit!r} to {to_unit!r}: different dimensions"
            )
        try:
            zeros = [
                registry.Quantity(Fraction(0), p).to_base_units().magnitude
                for p in parsed
            ]
            factor = registry.Quantity(Fraction(1), source).to(target).magnitude
        except _PINT_ERRORS as err:  # a logarithmic unit, for one
            raise ValueError(
                f"{head}: pint cannot convert {unit!r} to {to_unit!r} exactly"
            ) from err
    for u, zero in zip((unit, to_unit), zeros, strict=True):
        if zero != 0:
            raise ValueError(
                f"{head}: {u!r} has an offset: only a unit that keeps 0 at 0 converts"
            )
    return Fraction(factor)


def _convert(
    x: Fraction | float, unit: str, to_unit: str, what: str
) -> tuple[Fraction | float, Fraction]:
    """``x`` in ``unit`` converted to ``to_unit``, and the factor, exactly;
    an infinity stays an infinity.

    Raises
    ------
    ImportError
        If pint is not installed (the optional extra ``units``).
    ValueError
        If the units do not convert (see :func:`_factor`).
    """
    factor = _factor(unit, to_unit, what)
    if isinstance(x, float):  # an infinity: no limit stays no limit
        return x, factor
    return x * factor, factor


# Display --------------------------------------------------------------------

_HOUR = 3600
_DAY_MINUTES = 1440


def readable(value: Value | float, unit: str | None = None) -> str:
    """A value as a person reads it.

    - a duration in days, hours and minutes, and in seconds too under an
      hour: ``"2 min 15 s"``, ``"1 h 30 min"``, ``"1 d 2 h"``;
    - a length in kilometres from 1 km on, with three decimals at most,
      and in metres below, with two: ``"12.4 km"``, ``"350 m"``,
      ``"0.75 m"``;
    - any other number with its unit, ``f"{x:g} {unit}"``, and a label as
      it is;
    - an infinity: ``"no limit"``; a value to be set: ``"to be set"``; a
      value not applicable: ``"not applicable"``.

    The value is rounded once, half up, from its exact value (a float read
    as the decimal it shows). A unit pint does not know, a calendar
    convention or a unit with an offset is shown as written, never
    converted. The display is for a person: the values themselves, in the
    unit of their parameter, are what the package computes with.

    Parameters
    ----------
    value : Value, int or float
    unit : str, optional
        The unit of a number; a :class:`Value` gives its own.

    Returns
    -------
    str

    Raises
    ------
    ImportError
        If pint is not installed (the optional extra ``units``).
    TypeError
        If ``unit`` is given with a :class:`Value`, or ``value`` is neither a
        value nor a number.
    ValueError
        If the number is NaN.

    Examples
    --------
    >>> readable(5400, "s"), readable(12400.0, "m"), readable(0.75, "m")
    ('1 h 30 min', '12.4 km', '0.75 m')
    """
    x: object = value
    if isinstance(value, Value):
        if unit is not None:
            raise TypeError("a Value gives its own unit: give unit with a number only")
        x, unit = value.value, value.unit
    registry = _registry("readable")
    if isinstance(value, Value) and value.not_applicable is not None:
        return "not applicable"
    if x is None:
        return "to be set"
    if isinstance(x, str):
        return x if unit is None else f"{x} {unit}"
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(f"readable shows a Value or a number, got {x!r}")
    if math.isnan(x):
        raise ValueError("readable: NaN is not a value")
    if math.isinf(x):
        return "no limit"
    if unit is None:
        return f"{x:g}"
    exact = Fraction(x) if isinstance(x, int) else Fraction(repr(x))
    with _LOCK:
        measured = _measure(registry, exact, unit)
    if measured is None:
        return f"{x:g} {unit}"
    kind, size = measured
    sign = "-" if size < 0 else ""
    shown = _duration(abs(size)) if kind == "s" else _length(abs(size))
    return shown if shown in ("0 s", "0 m") else sign + shown


def _measure(registry: Any, x: Fraction, unit: str) -> tuple[str, Fraction] | None:
    """``x`` in seconds (``"s"``) for a duration, in metres (``"m"``) for a
    length, exactly; ``None`` for any other unit, and for a unit not to be
    converted. The caller holds the lock."""
    parsed = _parse(registry, unit)
    if parsed is None or _calendar(registry, parsed) is not None:
        return None
    for base in ("s", "m"):
        target = registry.parse_units(base)
        if parsed.dimensionality == target.dimensionality:
            factor = registry.Quantity(Fraction(1), parsed).to(target).magnitude
            return base, x * Fraction(factor)
    return None


def _half_up(x: Fraction) -> int:
    """``x``, at least 0, rounded to an integer, half up."""
    return math.floor(x + Fraction(1, 2))


def _duration(seconds: Fraction) -> str:
    """A duration of at least 0 s: minutes and seconds under an hour, then
    days, hours and minutes."""
    whole = _half_up(seconds)
    if whole < _HOUR:
        minutes, rest = divmod(whole, 60)
        parts = [(minutes, "min"), (rest, "s")]
    else:
        days, rest = divmod(_half_up(seconds / 60), _DAY_MINUTES)
        hours, minutes = divmod(rest, 60)
        parts = [(days, "d"), (hours, "h"), (minutes, "min")]
    return " ".join(f"{n} {u}" for n, u in parts if n) or "0 s"


def _length(metres: Fraction) -> str:
    """A length of at least 0 m: in metres with two decimals at most, in
    kilometres with three from 1 km on."""
    hundredths = _half_up(metres * 100)
    if hundredths < 100_000:
        return f"{_decimal(hundredths, 2)} m"
    return f"{_decimal(_half_up(metres), 3)} km"


def _decimal(n: int, digits: int) -> str:
    """``n / 10**digits`` written without needless zeros."""
    whole, part = divmod(n, 10**digits)
    if not part:
        return str(whole)
    return f"{whole}.{part:0{digits}d}".rstrip("0")
