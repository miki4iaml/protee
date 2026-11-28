# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""What the derivations share: the policy for the unknown, the derived
values and their tallies, the reading of the values of members, and exact
arithmetic.

A float is read as the decimal it shows (``Fraction(repr(x))``), an
integer exactly; ``inf`` and ``-inf`` stay apart, as known values (no
limit). Every computation is exact, and its result is rounded once: the
result depends on the multiset of the members only, never on their order,
and a value at a threshold is compared exactly.

A value in another unit than its parameter's is converted into it,
exactly, with the optional extra ``units`` (pint), and the conversion is
recorded; without the extra, it is refused.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from fractions import Fraction

from protee._frozen import FrozenMap
from protee.constraints._groups import Member
from protee.constraints._model import (
    Assumption,
    Conversion,
    DerivationInput,
    LeftOut,
    LeftOutCause,
    Origin,
    Parameter,
    ResolvedValues,
    Value,
    ValueSet,
    ValueState,
    _aliases,
    _by_name,
    _check_assumed,
    _count,
    _name,
    _sorted_names,
)
from protee.constraints._units import _convert, _factor

__all__ = ["Comparison", "Derived", "OnUnknown", "Tally", "UnknownRule"]


class UnknownRule(StrEnum):
    """What a derivation does with an input without a value.

    - ``propagate``: the derived value is to be set, and cites the inputs
      without a value; only when the known inputs already decide (the
      strictest label of an order, or the highest rank of a
      classification, reached) is it computed, and the trace says so;
    - ``known_only``: computed on the known inputs, the others left out
      and counted, with a justification; refused for additive rules (a sum,
      a mean, a count beyond a threshold, the length of a column), which it
      would shorten, and for the selection by a single class;
    - ``assume``: each input without a value takes the value assumed for
      its parameter, a declared choice, and the trace says for which
      members.
    """

    PROPAGATE = "propagate"
    KNOWN_ONLY = "known_only"
    ASSUME = "assume"


@dataclass(frozen=True, slots=True)
class OnUnknown:
    """The policy of a derivation for the inputs without a value, stated by
    the caller, without default.

    An input not applicable is left out under every policy: it is never
    unknown. Build it with :meth:`propagate`, :meth:`known_only` or
    :meth:`assume`.

    Attributes
    ----------
    rule : UnknownRule
    justification : str, optional
        Why the inputs without a value can be left out: required by
        ``known_only``, and by it only.
    assumed : mapping of str to Value
        For ``assume``: the value assumed for each canonical parameter,
        known, of origin ``choice``, with its justification.

    Raises
    ------
    ValueError
        If ``propagate`` takes a justification or a value, ``known_only``
        has no justification or takes a value, or ``assume`` has no value,
        takes a justification of its own, or assumes a value to be set or
        not chosen.

    Examples
    --------
    >>> OnUnknown.known_only("the members without a speed are towed").rule
    <UnknownRule.KNOWN_ONLY: 'known_only'>
    """

    rule: UnknownRule
    justification: str | None = None
    assumed: Mapping[str, Value] = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        rule = UnknownRule(self.rule)
        object.__setattr__(self, "rule", rule)
        assumed = dict(self.assumed)
        has_text = self.justification is not None
        if rule is UnknownRule.PROPAGATE and (has_text or assumed):
            raise ValueError("propagate takes no justification nor assumed value")
        if rule is UnknownRule.KNOWN_ONLY:
            if not (self.justification or "").strip():
                raise ValueError(
                    "known_only needs a justification: why the inputs without a "
                    "value can be left out"
                )
            if assumed:
                raise ValueError("known_only takes no assumed value")
        if rule is UnknownRule.ASSUME:
            if not assumed:
                raise ValueError("assume needs at least one assumed value")
            if has_text:
                raise ValueError(
                    "assume takes no justification of its own: each assumed value "
                    "carries its justification"
                )
            for parameter, value in assumed.items():
                _name("assumed parameter", parameter)
                _check_assumed(parameter, value)
        object.__setattr__(self, "assumed", FrozenMap(assumed))

    @classmethod
    def propagate(cls) -> OnUnknown:
        """An input without a value leaves the derived value to be set."""
        return cls(UnknownRule.PROPAGATE)

    @classmethod
    def known_only(cls, justification: str) -> OnUnknown:
        """The known inputs only, with the reason why the others can be left
        out."""
        return cls(UnknownRule.KNOWN_ONLY, justification=justification)

    @classmethod
    def assume(cls, values: Mapping[str, Value]) -> OnUnknown:
        """A value assumed for the inputs without a value, by canonical
        parameter."""
        return cls(UnknownRule.ASSUME, assumed=values)


class Comparison(StrEnum):
    """When a value *x* crosses a threshold *b*: the closure and the
    direction, declared, without default.

    - ``above``: *x* > *b* (a text that says "up to *b*" keeps *b* below);
    - ``at_least``: *x* >= *b* ("from *b*");
    - ``below``: *x* < *b*;
    - ``at_most``: *x* <= *b*.
    """

    ABOVE = "above"
    AT_LEAST = "at_least"
    BELOW = "below"
    AT_MOST = "at_most"


@dataclass(frozen=True, slots=True)
class Tally:
    """Inputs counted by holder: their names and their instances.

    Attributes
    ----------
    names : tuple of str
        Sorted, without duplicate.
    instances : int
        Their instances in the group (a member of count 3 counts 3).
    """

    names: tuple[str, ...] = ()
    instances: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "names", _sorted_names("name", self.names))
        _count("instances", self.instances, least=0)
        if not self.names and self.instances:
            raise ValueError("a tally without names counts no instance")


_TABLES = ("unknown", "assumed", "left_out")


@dataclass(frozen=True, slots=True)
class Derived:
    """Values derived from the description of a subject, with their
    tallies.

    The value set enters :func:`resolve_values` like any other, with its
    precedence: each value carries its :class:`Derivation`.

    Attributes
    ----------
    values : ValueSet
        Its rulebook is the subject (the identifier of the group), its
        edition the one declared; every value is of origin ``derived``.
    unknown : mapping of str to Tally
        By derived parameter: the inputs without a value, whatever the
        policy (objective 6: every result counts its unknowns).
    assumed : mapping of str to Tally
        Among them, those replaced by an assumed value.
    left_out : mapping of str to Tally
        The inputs left out: not applicable, excluded from the group, of
        count 0, unknown and left out by ``known_only``.

    Raises
    ------
    ValueError
        If a value is not derived, a table has no tally for a derived value
        or names a parameter that is not derived, or an assumed input is
        not among the unknown ones.
    TypeError
        If ``values`` is not a value set, or a tally not a :class:`Tally`.
    """

    values: ValueSet
    unknown: Mapping[str, Tally]
    assumed: Mapping[str, Tally]
    left_out: Mapping[str, Tally]

    def __post_init__(self) -> None:
        if not isinstance(self.values, ValueSet):
            raise TypeError(f"values must be a ValueSet, got {self.values!r}")
        derived = set(self.values.values)
        for name, value in self.values.values.items():
            if value.origin is not Origin.DERIVED:
                raise ValueError(
                    f"derived values: {name!r} is not derived "
                    f"(origin {value.origin.value!r})"
                )
        for what in _TABLES:
            table = dict(getattr(self, what))
            for name, tally in table.items():
                if name not in derived:
                    raise ValueError(
                        f"tallies name {name!r}, which is not a derived value"
                    )
                if not isinstance(tally, Tally):
                    raise TypeError(f"{what}[{name!r}] must be a Tally, got {tally!r}")
            missing = sorted(derived - set(table))
            if missing:
                raise ValueError(f"{what} has no tally for {missing[0]!r}")
            object.__setattr__(self, what, FrozenMap(table))
        for name in sorted(derived):
            if not set(self.assumed[name].names) <= set(self.unknown[name].names):
                raise ValueError(
                    f"the assumed inputs of {name!r} must be among its unknown inputs"
                )

    def __getitem__(self, parameter: str) -> Value:
        """The value derived for ``parameter``."""
        return self.values.values[parameter]

    @classmethod
    def merge(cls, *parts: Derived) -> Derived:
        """The values of several derivations on the same subject, in one
        value set (one per rulebook and edition in :func:`resolve_values`).

        Raises
        ------
        ValueError
            If there is no part, the parts differ in rulebook or edition,
            or a parameter is derived twice.
        """
        if not parts:
            raise ValueError("nothing to merge")
        first = parts[0].values
        values: dict[str, Value] = {}
        tables: dict[str, dict[str, Tally]] = {what: {} for what in _TABLES}
        for part in parts:
            vs = part.values
            if (vs.rulebook, vs.edition) != (first.rulebook, first.edition):
                raise ValueError(
                    f"cannot merge the values of {first.rulebook} ({first.edition}) "
                    f"and {vs.rulebook} ({vs.edition}): same rulebook and edition "
                    "required"
                )
            for name, value in vs.values.items():
                if name in values:
                    raise ValueError(f"{name!r} derived twice")
                values[name] = value
                for what in _TABLES:
                    tables[what][name] = getattr(part, what)[name]
        return cls(
            ValueSet(first.rulebook, first.edition, values),
            unknown=tables["unknown"],
            assumed=tables["assumed"],
            left_out=tables["left_out"],
        )


# Exact arithmetic -----------------------------------------------------------

#: An exact number: a fraction, or an infinite float.
type Exact = Fraction | float


def _exact(x: float) -> Exact:
    """``x`` exactly: an integer as is, a float as the decimal it shows;
    an infinity stays a float."""
    if isinstance(x, int):
        return Fraction(x)
    if math.isinf(x):
        return x
    return Fraction(repr(x))


def _weighted_sum(terms: Iterable[tuple[int, Exact]], what: str) -> Exact:
    """The exact sum of ``count * x``; ``inf`` absorbs the finite terms.

    Raises
    ------
    ValueError
        If ``+inf`` and ``-inf`` are both terms.
    """
    total = Fraction(0)
    signs: set[bool] = set()
    for count, x in terms:
        if isinstance(x, float):
            signs.add(x > 0)
        else:
            total += count * x
    if len(signs) == 2:
        raise ValueError(f"{what}: sum of +inf and -inf has no value")
    if signs:
        return math.inf if signs.pop() else -math.inf
    return total


def _crosses(comparison: Comparison, x: Exact, threshold: Exact) -> bool:
    """Whether ``x`` crosses ``threshold``, exactly."""
    if comparison is Comparison.ABOVE:
        return x > threshold
    if comparison is Comparison.AT_LEAST:
        return x >= threshold
    if comparison is Comparison.BELOW:
        return x < threshold
    return x <= threshold


# Reading the values of members ---------------------------------------------

_DECLARE = ": declare it in parameters"


@dataclass(frozen=True, slots=True)
class _Vocabulary:
    """The parameters of a derivation, with their aliases."""

    by_name: Mapping[str, Parameter]
    aliases: Mapping[tuple[str, str], str]

    def parameter(self, name: str) -> Parameter:
        found = self.by_name.get(name)
        if found is None:
            raise ValueError(f"unknown parameter {name!r}{_DECLARE}")
        return found


def _vocabulary(parameters: Iterable[Parameter]) -> _Vocabulary:
    """The vocabulary of a derivation; a parameter may be given twice
    (from requirements and from a rulebook), if identically.

    Raises
    ------
    ValueError
        If a parameter is declared twice differently.
    TypeError
        If an element is not a :class:`Parameter`.
    """
    by_name: dict[str, Parameter] = {}
    for p in parameters:
        if not isinstance(p, Parameter):
            raise TypeError(f"parameters must be Parameter objects, got {p!r}")
        if by_name.setdefault(p.name, p) != p:
            raise ValueError(f"parameter {p.name!r} declared twice, differently")
    return _Vocabulary(FrozenMap(by_name), FrozenMap(_aliases(by_name.values())))


# Values given directly ------------------------------------------------------

#: The values a derivation reads directly, not on the members of a group:
#: a value set, read through the vocabulary, or resolved or derived values,
#: by canonical name already.
type ValuesLike = ValueSet | ResolvedValues | Derived


def _check_unknown(unknown: object) -> OnUnknown:
    """The policy for the unknown, checked.

    Raises
    ------
    TypeError
        If ``unknown`` is not an :class:`OnUnknown` policy.
    """
    if not isinstance(unknown, OnUnknown):
        raise TypeError(f"unknown must be an OnUnknown policy, got {unknown!r}")
    return unknown


def _named(
    values: ValuesLike, vocabulary: _Vocabulary, what: str
) -> Mapping[str, Value]:
    """The values given directly to a derivation, by canonical name.

    A value set is read through the vocabulary: a key is a canonical name,
    or the alias its rulebook uses. Resolved values and derived values are
    by canonical name already.

    Raises
    ------
    ValueError
        If a key of a value set is not in the vocabulary, or two keys name
        the same parameter.
    TypeError
        If ``values`` is none of the three.
    """
    if isinstance(values, Derived):
        return values.values.values
    if isinstance(values, ResolvedValues):
        return values.values
    if isinstance(values, ValueSet):
        where = f"{what}: value set {values.rulebook} ({values.edition})"
        names = _by_name(
            values, vocabulary.by_name, vocabulary.aliases, where, _DECLARE
        )
        return {name: value for name, (_, value) in names.items()}
    raise TypeError(
        f"{what} must be a ValueSet, ResolvedValues or Derived, got {values!r}"
    )


def _assumptions(
    found: Iterable[tuple[str, Value, str, int]],
) -> tuple[Assumption, ...]:
    """One assumption per parameter, from ``(parameter, value, holder,
    instances)``: the holders gathered, their instances summed."""
    gathered: dict[str, tuple[Value, set[str], int]] = {}
    for parameter, value, holder, instances in found:
        _, holders, total = gathered.get(parameter, (value, set(), 0))
        gathered[parameter] = (value, holders | {holder}, total + instances)
    return tuple(
        Assumption(parameter, value, tuple(holders), total)
        for parameter, (value, holders, total) in sorted(gathered.items())
    )


def _member_values(member: Member, vocabulary: _Vocabulary) -> dict[str, Value]:
    """The values of a member by canonical parameter, from all its sheets.

    Raises
    ------
    ValueError
        If a key of a sheet is not in the vocabulary, a sheet gives a
        parameter twice, or two sheets give the same parameter.
    """
    found: dict[str, tuple[ValueSet, Value]] = {}
    for sheet in member.sheets:
        where = f"member {member.id!r}: value set {sheet.rulebook} ({sheet.edition})"
        names = _by_name(sheet, vocabulary.by_name, vocabulary.aliases, where, _DECLARE)
        for name, (_, value) in names.items():
            if name in found:
                other = found[name][0]
                raise ValueError(
                    f"member {member.id!r}: {name!r} given by two sheets "
                    f"({other.rulebook} ({other.edition}), "
                    f"{sheet.rulebook} ({sheet.edition}))"
                )
            found[name] = (sheet, value)
    return {name: value for name, (_, value) in found.items()}


@dataclass(frozen=True, slots=True)
class _Converted:
    """A number read in another unit than its parameter's, and its
    conversion.

    Attributes
    ----------
    read : Value
        The value as read, in its own unit: the input of the trace.
    exact : Fraction or float
        The number in the unit of the parameter, exactly (an infinity as
        is).
    record : Conversion
    """

    read: Value
    exact: Exact
    record: Conversion


@dataclass(frozen=True, slots=True)
class _Reading:
    """The value of a parameter read on a holder, in the unit of the
    parameter.

    Attributes
    ----------
    holder : str
    instances : int
    state : ValueState
    value : Value or None
        In the unit of the parameter: a number read in another unit is
        converted, rounded once.
    converted : _Converted, optional
        The value as read and its conversion, for a converted number.
    """

    holder: str
    instances: int
    state: ValueState
    value: Value | None
    converted: _Converted | None = None

    @property
    def read(self) -> Value | None:
        """The value as read, in its own unit: the input of the trace."""
        return self.value if self.converted is None else self.converted.read

    @property
    def exact(self) -> Exact:
        """The number, exactly, in the unit of the parameter."""
        if self.converted is not None:
            return self.converted.exact
        assert self.value is not None
        x = self.value.value
        assert isinstance(x, (int, float))
        return _exact(x)


def _in_unit(
    value: Value, parameter: Parameter, holder: str | None, what: str
) -> tuple[Value, _Converted | None]:
    """``value`` in the unit of ``parameter``, and its conversion if one
    was needed.

    A number is converted exactly and rounded once; a value without a
    number (to be set, not applicable) keeps its unit, once checked that it
    converts. ``what`` names the value for the messages.

    Raises
    ------
    ImportError
        If the units differ and pint is not installed (the optional extra
        ``units``).
    ValueError
        If one of the units is missing, or the units do not convert.
    TypeError
        If the value to convert is a text.
    """
    unit, to_unit = value.unit, parameter.unit
    if unit == to_unit:
        return value, None
    if unit is None or to_unit is None:
        raise ValueError(
            f"{what} in {unit!r}, the parameter is in {to_unit!r}: only a value "
            "with a unit converts, into a parameter with a unit"
        )
    x = value.value
    if x is None:
        _factor(unit, to_unit, what)
        return value, None
    if isinstance(x, str):
        raise TypeError(
            f"{what} in {unit!r}, the parameter is in {to_unit!r}: a text does "
            "not convert"
        )
    exact, factor = _convert(_exact(x), unit, to_unit, what)
    converted = exact if isinstance(exact, float) else float(exact)
    record = Conversion(
        holder, parameter.name, x, unit, converted, to_unit, str(factor)
    )
    in_unit = replace(value, value=converted, unit=to_unit)
    return in_unit, _Converted(value, exact, record)


def _given(
    value: Value, parameter: Parameter, what: str
) -> tuple[Exact, tuple[Conversion, ...]]:
    """A number given directly (a threshold), exactly in the unit of
    ``parameter``, and its conversion if one was needed.

    Raises
    ------
    ImportError, ValueError, TypeError
        As :func:`_in_unit`.
    """
    in_unit, converted = _in_unit(value, parameter, None, what)
    if converted is not None:
        return converted.exact, (converted.record,)
    x = in_unit.value
    assert isinstance(x, (int, float))
    return _exact(x), ()


def _read(
    holder: str,
    instances: int,
    values: Mapping[str, Value],
    parameter: Parameter,
) -> _Reading:
    """The value of ``parameter`` on a holder, in the unit of the
    parameter: converted, with the optional extra ``units``, if it is in
    another unit.

    Raises
    ------
    ImportError
        If the value is in another unit and pint is not installed.
    ValueError
        If the value is in another unit and does not convert into the unit
        of the parameter.
    """
    value = values.get(parameter.name)
    if value is None:
        return _Reading(holder, instances, ValueState.UNKNOWN, None)
    what = f"member {holder!r}: {parameter.name!r}"
    in_unit, converted = _in_unit(value, parameter, holder, what)
    return _Reading(holder, instances, value.state, in_unit, converted)


def _converts(unit: str | None, to_unit: str | None, what: str) -> None:
    """Check that a value in ``unit`` converts into ``to_unit``, before any
    value is read; equal units need nothing.

    Raises
    ------
    ImportError
        If the units differ and pint is not installed.
    ValueError
        If one of the units is missing, or the units do not convert.
    """
    if unit == to_unit:
        return
    if unit is None or to_unit is None:
        raise ValueError(
            f"{what} in {unit!r}, the parameter is in {to_unit!r}: only a value "
            "with a unit converts, into a parameter with a unit"
        )
    _factor(unit, to_unit, what)


def _read_given(
    where: str,
    name: str,
    values: Mapping[str, Value],
    target: Parameter,
    *,
    holder: str | None = None,
    instances: int = 1,
) -> _Reading:
    """The value of ``target`` given directly, or on a group, converted
    into the unit of ``target``, which is the unit the derivation needs
    (that of a characteristic for a threshold, of the output for a value
    selected, of the column for a gap).

    ``where`` names the place in a message, ``name`` the input in the
    trace; ``holder`` is the group the value was read on, ``None`` for a
    value given directly.

    Raises
    ------
    ImportError, ValueError, TypeError
        As :func:`_in_unit`.
    """
    value = values.get(target.name)
    if value is None:
        return _Reading(name, instances, ValueState.UNKNOWN, None)
    what = f"{where}: {target.name!r}"
    in_unit, converted = _in_unit(value, target, holder, what)
    return _Reading(name, instances, value.state, in_unit, converted)


def _assume(
    reading: _Reading, target: Parameter, policy: OnUnknown, where: str
) -> _Reading:
    """Under ``assume``, an input without a value takes the value assumed
    for its parameter, converted into the unit of ``target``; any other
    input is returned as is.

    Raises
    ------
    ValueError
        If no value is assumed for the parameter, or it does not convert.
    ImportError
        If the value assumed is in another unit and pint is not installed.
    """
    if reading.state is not ValueState.UNKNOWN or policy.rule is not UnknownRule.ASSUME:
        return reading
    name = target.name
    value = policy.assumed.get(name)
    if value is None:
        raise ValueError(f"{where}: no value for {name!r} and no value assumed for it")
    in_unit, converted = _in_unit(
        value, target, None, f"the value assumed for {name!r}"
    )
    return _Reading(
        reading.holder, reading.instances, ValueState.ASSUMED, in_unit, converted
    )


@dataclass(frozen=True, slots=True)
class _Partition:
    """The inputs of a parameter, sorted out by the policy for the unknown.

    Attributes
    ----------
    used : tuple of _Reading
        Known inputs, and unknown inputs replaced by the assumed value
        (state ``assumed``): the inputs the rule computes on.
    unknown : tuple of _Reading
        The inputs without a value, whatever the policy.
    pending : bool
        Whether the value is to be set unless the known inputs decide:
        ``propagate`` with unknown inputs.
    not_applicable : tuple of _Reading
    inputs : tuple of DerivationInput
        Each with the value as read, in its own unit.
    left_out : tuple of LeftOut
    assumptions : tuple of Assumption
    conversions : tuple of Conversion
        The inputs converted into the unit of the parameter, the value
        assumed included.
    """

    used: tuple[_Reading, ...]
    unknown: tuple[_Reading, ...]
    pending: bool
    not_applicable: tuple[_Reading, ...]
    inputs: tuple[DerivationInput, ...]
    left_out: tuple[LeftOut, ...]
    assumptions: tuple[Assumption, ...]
    conversions: tuple[Conversion, ...] = ()

    @property
    def unknown_tally(self) -> Tally:
        return Tally(
            tuple(r.holder for r in self.unknown),
            sum(r.instances for r in self.unknown),
        )


def _partition(
    readings: Sequence[_Reading],
    parameter: Parameter,
    policy: OnUnknown,
    *,
    role: str = "member",
) -> _Partition:
    """Sort the inputs of ``parameter`` out by state and policy.

    A value assumed in another unit than the parameter's is converted into
    it, like a value read (see :func:`_read`).

    Raises
    ------
    ValueError
        Under ``assume``, if no value is assumed for the parameter of an
        input without a value, or the value assumed does not convert.
    ImportError
        If the value assumed is in another unit and pint is not installed.
    """
    name = parameter.name
    used: list[_Reading] = []
    unknown = [r for r in readings if r.state is ValueState.UNKNOWN]
    na = [r for r in readings if r.state is ValueState.NOT_APPLICABLE]
    left_out = [
        LeftOut(r.holder, LeftOutCause.NOT_APPLICABLE, _reason(r), r.instances)
        for r in na
    ]
    assumptions: list[Assumption] = []
    conversions = [r.converted.record for r in readings if r.converted is not None]
    assumed: tuple[Value, _Converted | None] | None = None
    if unknown and policy.rule is UnknownRule.ASSUME:
        assumed_value = policy.assumed.get(name)
        if assumed_value is None:
            raise ValueError(
                f"member {unknown[0].holder!r}: no value for {name!r} and no "
                "value assumed for it"
            )
        assumptions.append(
            Assumption(
                name,
                assumed_value,
                tuple(r.holder for r in unknown),
                sum(r.instances for r in unknown),
            )
        )
        assumed = _in_unit(
            assumed_value, parameter, None, f"the value assumed for {name!r}"
        )
        if assumed[1] is not None:
            conversions.append(assumed[1].record)
    if policy.rule is UnknownRule.KNOWN_ONLY:
        justification = policy.justification
        assert justification is not None
        left_out += [
            LeftOut(r.holder, LeftOutCause.UNKNOWN, justification, r.instances)
            for r in unknown
        ]
    inputs: list[DerivationInput] = []
    for reading in readings:
        r = reading
        if r.state is ValueState.UNKNOWN and assumed is not None:
            r = _Reading(r.holder, r.instances, ValueState.ASSUMED, *assumed)
        inputs.append(
            DerivationInput(role, name, r.holder, r.state, r.read, r.instances)
        )
        if r.state in (ValueState.KNOWN, ValueState.ASSUMED):
            used.append(r)
    return _Partition(
        used=tuple(used),
        unknown=tuple(unknown),
        pending=bool(unknown) and policy.rule is UnknownRule.PROPAGATE,
        not_applicable=tuple(na),
        inputs=tuple(inputs),
        left_out=tuple(left_out),
        assumptions=tuple(assumptions),
        conversions=tuple(conversions),
    )


def _reason(reading: _Reading) -> str:
    assert reading.value is not None
    reason = reading.value.not_applicable
    assert reason is not None
    return reason


def _check_policy(
    policy: OnUnknown, read: Iterable[str], vocabulary: _Vocabulary
) -> None:
    """Every assumed value is for a parameter of the vocabulary that a
    rule reads, in its unit or in a unit that converts into it.

    Raises
    ------
    ValueError
        If a parameter is unknown, read by no rule, or the assumed value is
        in another unit that does not convert into the parameter's.
    ImportError
        If the assumed value is in another unit and pint is not installed.
    """
    names = set(read)
    for name, value in sorted(policy.assumed.items()):
        parameter = vocabulary.parameter(name)
        if name not in names:
            raise ValueError(f"a value is assumed for {name!r}, which no rule reads")
        _in_unit(value, parameter, None, f"the value assumed for {name!r}")


def _label(reading: _Reading, parameter: str) -> str:
    """Who holds a value, for a message."""
    if reading.state is ValueState.ASSUMED:
        return f"the value assumed for {parameter!r}"
    return f"member {reading.holder!r}: {parameter!r}"
