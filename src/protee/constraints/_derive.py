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
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction

from protee._frozen import FrozenMap
from protee.constraints._groups import Member
from protee.constraints._model import (
    Assumption,
    DerivationInput,
    LeftOut,
    LeftOutCause,
    Origin,
    Parameter,
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

__all__ = ["Comparison", "Derived", "OnUnknown", "Tally", "UnknownRule"]


class UnknownRule(StrEnum):
    """What a derivation does with an input without a value.

    - ``propagate``: the derived value is to be set, and cites the inputs
      without a value; only when the known inputs already decide (the
      strictest label of an order reached) is it computed, and the trace
      says so;
    - ``known_only``: computed on the known inputs, the others left out
      and counted, with a justification; refused for additive rules (a sum,
      a mean, a count beyond a threshold), which it would shorten;
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
class _Reading:
    """The value of a parameter read on a holder."""

    holder: str
    instances: int
    state: ValueState
    value: Value | None


def _read(
    holder: str,
    instances: int,
    values: Mapping[str, Value],
    parameter: Parameter,
) -> _Reading:
    """The value of ``parameter`` on a holder, in the unit of the parameter.

    Raises
    ------
    ValueError
        If the value is in another unit.
    """
    value = values.get(parameter.name)
    if value is None:
        return _Reading(holder, instances, ValueState.UNKNOWN, None)
    if value.unit != parameter.unit:
        raise ValueError(
            f"member {holder!r}: {parameter.name!r} in {value.unit!r}, the "
            f"parameter is in {parameter.unit!r}"
        )
    return _Reading(holder, instances, value.state, value)


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
    left_out : tuple of LeftOut
    assumptions : tuple of Assumption
    """

    used: tuple[_Reading, ...]
    unknown: tuple[_Reading, ...]
    pending: bool
    not_applicable: tuple[_Reading, ...]
    inputs: tuple[DerivationInput, ...]
    left_out: tuple[LeftOut, ...]
    assumptions: tuple[Assumption, ...]

    @property
    def unknown_tally(self) -> Tally:
        return Tally(
            tuple(r.holder for r in self.unknown),
            sum(r.instances for r in self.unknown),
        )


def _partition(
    readings: Sequence[_Reading],
    parameter: str,
    policy: OnUnknown,
    *,
    role: str = "member",
) -> _Partition:
    """Sort the inputs of ``parameter`` out by state and policy.

    Raises
    ------
    ValueError
        Under ``assume``, if no value is assumed for the parameter of an
        input without a value.
    """
    used: list[_Reading] = []
    unknown = [r for r in readings if r.state is ValueState.UNKNOWN]
    na = [r for r in readings if r.state is ValueState.NOT_APPLICABLE]
    left_out = [
        LeftOut(r.holder, LeftOutCause.NOT_APPLICABLE, _reason(r), r.instances)
        for r in na
    ]
    assumptions: list[Assumption] = []
    assumed_value = policy.assumed.get(parameter)
    if unknown and policy.rule is UnknownRule.ASSUME:
        if assumed_value is None:
            raise ValueError(
                f"member {unknown[0].holder!r}: no value for {parameter!r} and no "
                "value assumed for it"
            )
        assumptions.append(
            Assumption(
                parameter,
                assumed_value,
                tuple(r.holder for r in unknown),
                sum(r.instances for r in unknown),
            )
        )
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
        if r.state is ValueState.UNKNOWN and assumptions:
            r = _Reading(r.holder, r.instances, ValueState.ASSUMED, assumed_value)
        inputs.append(
            DerivationInput(role, parameter, r.holder, r.state, r.value, r.instances)
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
    rule reads, in its unit.

    Raises
    ------
    ValueError
        If a parameter is unknown, read by no rule, or the assumed value is
        in another unit.
    """
    names = set(read)
    for name, value in sorted(policy.assumed.items()):
        parameter = vocabulary.parameter(name)
        if name not in names:
            raise ValueError(f"a value is assumed for {name!r}, which no rule reads")
        if value.unit != parameter.unit:
            raise ValueError(
                f"the value assumed for {name!r} in {value.unit!r}, the parameter "
                f"is in {parameter.unit!r}"
            )


def _label(reading: _Reading, parameter: str) -> str:
    """Who holds a value, for a message."""
    if reading.state is ValueState.ASSUMED:
        return f"the value assumed for {parameter!r}"
    return f"member {reading.holder!r}: {parameter!r}"
