# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The length a group occupies in a column, level by level: the lengths
of its members or their number over a density, plus the gaps between its
units."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction

from protee.constraints._derive import (
    Derived,
    OnUnknown,
    Tally,
    UnknownRule,
    ValuesLike,
    _assume,
    _assumptions,
    _check_policy,
    _check_unknown,
    _converts,
    _label,
    _member_values,
    _named,
    _partition,
    _read,
    _read_given,
    _Reading,
    _reason,
    _Vocabulary,
    _vocabulary,
)
from protee.constraints._groups import Group, Member, tree_left_out
from protee.constraints._model import (
    Conversion,
    Derivation,
    DerivationInput,
    LeftOut,
    Origin,
    Parameter,
    Source,
    Value,
    ValueSet,
    ValueState,
    _name,
)

__all__ = ["Gap", "GapCount", "column_length"]


class GapCount(StrEnum):
    """How many gaps a group of *n* units counts, declared without
    default.

    - ``between``: *n* - 1, between consecutive units (geometry: units end
      to end, a line of units);
    - ``per_unit``: *n*, one per unit (the convention of a density: each
      unit with its gap).
    """

    BETWEEN = "between"
    PER_UNIT = "per_unit"


@dataclass(frozen=True, slots=True)
class Gap:
    """The gap between the units of a level of groups.

    Attributes
    ----------
    parameter : str
        The canonical parameter of the gap, read on the group, else on its
        nearest ancestor that gives it, else in the ``context`` of
        :func:`column_length`.
    count : GapCount
        How many gaps a group counts, without default.
    at_pace : bool
        Whether the gap is a duration, turned into a distance at the pace.

    Raises
    ------
    ValueError
        If the parameter is empty.
    TypeError
        If ``at_pace`` is not a boolean.

    Examples
    --------
    >>> Gap("serial_gap", GapCount.BETWEEN, at_pace=True).count
    <GapCount.BETWEEN: 'between'>
    """

    parameter: str
    count: GapCount
    at_pace: bool = False

    def __post_init__(self) -> None:
        _name("parameter", self.parameter)
        object.__setattr__(self, "count", GapCount(self.count))
        if not isinstance(self.at_pace, bool):
            raise TypeError(
                f"gap {self.parameter!r}: at_pace must be a boolean, got "
                f"{self.at_pace!r}"
            )


def column_length(
    group: Group,
    *,
    output: str,
    member_length: str | None = None,
    density: str | None = None,
    spacing: Sequence[Gap],
    pace: str | None = None,
    context: ValuesLike | None = None,
    parameters: Iterable[Parameter],
    unknown: OnUnknown,
    edition: str,
    precedence: int = 0,
) -> Derived:
    """The length a group occupies in a column.

    The group at the head is at level 0, its sub-groups at level 1, and so
    on; a group of level *d* spaces its units by ``spacing[d]``. A group
    holds members only or groups only, and its groups of members are all
    at the same depth: a column is measured level by level. With *c* the
    count of a unit and *n* the sum of the counts of a group:

    - geometric form (``member_length``): a member is its length; a group
      is the sum of *c* times the length of its units, plus *g(n)* gaps,
      with *g(n)* = *n* - 1 (``between``) or *n* (``per_unit``);
    - density form (``density``): a group of members is *n* over its
      density, which includes the gaps between its members; a group of
      groups as in the geometric form;
    - a gap in time (``at_pace``) is its duration times the pace.

    A density, a gap and a pace are values of a group (its
    :attr:`Group.values`), read on the group, else on its nearest
    ancestor that gives them, else in ``context`` (the pace of the slowest
    member derived by :func:`aggregate`, typically). The formula *N* /
    *D* + *TG* *r* of a doctrine (members over a density, plus the gaps in
    time at the pace) is the density form with gaps in time; the length
    of a line of units, the sum of their lengths plus (*N* - 1) spacings,
    the geometric form with ``between``. The arithmetic is exact, the
    result a float rounded once, never rounded further (the time to pass
    a point belongs to the time module).

    Parameters
    ----------
    group : Group
    output : str
        The parameter that receives the length, with a unit.
    member_length : str, optional
        The geometric form: the length of each member, at least 0 and
        finite, read in the unit of the output.
    density : str, optional
        The density form: the number of members per unit of length,
        positive and finite, read in ``1/<unit of the output>``. Exactly one
        of ``member_length`` and ``density`` is given.
    spacing : sequence of Gap
        One gap per level of groups; in the density form, none for the
        groups of members, whose density holds their gaps. A gap is at
        least 0 and finite: in distance, read in the unit of the output; in
        time, in the unit of the first gap in time.
    pace : str, optional
        The pace a gap in time is covered at, positive and finite, read in
        ``<unit of the output>/<unit of the gaps in time>``; given if and
        only if a gap is in time.
    context : ValueSet, ResolvedValues or Derived, optional
        Where a value of a group is read last.
    parameters : iterable of Parameter
        The vocabulary: units, and the aliases of the sheets of the
        members and of the values of the groups.
    unknown : OnUnknown
        The policy for the inputs without a value, without default:
        ``propagate`` or ``assume``.
    edition : str
        The edition of the value set returned.
    precedence : int
        The precedence of the value returned.

    Returns
    -------
    Derived
        Its rulebook is the identifier of the group. The length has the
        origin ``derived`` and its :class:`Derivation` (rule ``geometric``
        or ``density``): the members (role ``member`` with their length,
        or ``count``) and every value of a group read (roles ``gap``,
        ``density``, ``pace``), held by the group that gives it, or by
        ``None`` when ``context`` does (named by its parameter in the
        tallies); its ``instances`` count the groups it serves. Each input
        is traced as read; one in another unit than the one it is read in
        is converted, exactly, with the optional extra ``units`` (a pace
        in km/h for gaps in min and a length in m), and the conversion
        recorded.

        A member whose length is not applicable (it is carried) is out of
        the column, without length or gap, and recorded as left out; if
        every member is, the length is not applicable. Under
        ``propagate``, an input without a value leaves the length to be
        set; under ``assume``, it takes the value assumed for its
        parameter. A group of one unit has no gap under ``between``.

    Raises
    ------
    ValueError
        If both or neither form is given, ``known_only`` is given (it
        would shorten the column), the levels of ``spacing`` do not match
        the levels of the group, a group mixes members and groups or its
        groups of members are at different depths, the pace is missing or
        not needed, a unit does not convert into the one it is read in
        (different dimensions), a value is out of its range or not
        applicable, a parameter is not in the vocabulary, or the policy
        assumes a value no input reads or misses one.
    ImportError
        If a unit differs and pint is not installed (the optional extra
        ``units``).
    TypeError
        If a value is not a number, or an argument is not of its type.

    Examples
    --------
    >>> source = Source("Sheet A", locator="p. 2")
    >>> a = Member("A", (ValueSet("sheet-a", "1", {
    ...     "length": Value(12.0, source, Origin.STATEMENT, unit="m")}),))
    >>> gaps = ValueSet("plan", "1", {
    ...     "gap": Value(50.0, Source("Plan"), Origin.CHOICE, unit="m",
    ...                  justification="the planned distance")})
    >>> derived = column_length(
    ...     Group("line", ((a, 3),), values=gaps),
    ...     output="line_length",
    ...     member_length="length",
    ...     spacing=[Gap("gap", GapCount.BETWEEN)],
    ...     parameters=[Parameter(p, unit="m") for p in ("length", "gap", "line_length")],
    ...     unknown=OnUnknown.propagate(),
    ...     edition="1",
    ... )
    >>> derived["line_length"].value
    136.0
    """
    if not isinstance(group, Group):
        raise TypeError(f"group must be a Group, got {group!r}")
    policy = _check_unknown(unknown)
    _name("edition", edition)
    if (member_length is None) == (density is None):
        raise ValueError(
            "give member_length (geometric form) or density (density form), not both"
        )
    rule = "geometric" if member_length is not None else "density"
    if policy.rule is UnknownRule.KNOWN_ONLY:
        raise ValueError(
            f"known_only would shorten an additive value ({rule} length of "
            f"{group.id!r}): use propagate or assume"
        )
    gaps = _spacing(spacing)
    levels = _levels(group)
    spaced = levels if rule == "geometric" else levels - 1
    if len(gaps) != spaced:
        tail = "" if rule == "geometric" else ", the last one spaced by its density"
        raise ValueError(
            f"spacing: {_plural(len(gaps), 'level')} given, group {group.id!r} has "
            f"{_plural(levels, 'level')} of groups{tail}"
        )
    timed = [level for level, gap in enumerate(gaps) if gap.at_pace]
    if timed and pace is None:
        raise ValueError(f"the gaps of level {timed[0]} are in time: give pace")
    if pace is not None and not timed:
        raise ValueError("pace given, but no gap is in time")
    vocabulary = _vocabulary(parameters)
    unit = vocabulary.parameter(output).unit
    if unit is None:
        raise ValueError(f"column_length gives a length: {output!r} must have a unit")
    targets = _targets(unit, vocabulary, member_length, density, gaps, pace)
    measured = member_length if member_length is not None else density
    assert measured is not None
    read = [measured, *(gap.parameter for gap in gaps), *([pace] if pace else [])]
    _check_policy(policy, read, vocabulary)
    own = {
        g.id: {}
        if g.values is None
        else _named(g.values, vocabulary, f"group {g.id!r}")
        for g in _groups(group)
    }
    context_values = {} if context is None else _named(context, vocabulary, "context")
    leaves = group.flatten()
    inputs: list[DerivationInput] = []
    left_out: list[LeftOut] = list(tree_left_out(group))
    unknown_found: list[tuple[str, int]] = []
    assumed: list[tuple[str, Value, str, int]] = []
    conversions: list[Conversion] = []
    contributors: list[str] = []
    not_applicable: list[_Reading] = []
    lengths: dict[str, Fraction | None] = {}
    if member_length is not None:
        # The lengths are read in the unit of the column.
        target = targets[("member", member_length)]
        sheets = {m.id: _member_values(m, vocabulary) for m, _ in leaves}
        readings = [_read(m.id, c, sheets[m.id], target) for m, c in leaves]
        part = _partition(readings, target, policy)
        inputs += part.inputs
        left_out += part.left_out
        conversions += part.conversions
        not_applicable += part.not_applicable
        unknown_found += [(r.holder, r.instances) for r in part.unknown]
        if part.assumptions:
            chosen = policy.assumed[member_length]
            assumed += [
                (member_length, chosen, r.holder, r.instances) for r in part.unknown
            ]
        lengths = dict.fromkeys((r.holder for r in part.unknown), None)
        for r in part.used:
            lengths[r.holder] = _measure(r, _label(r, member_length), positive=False)
            contributors.append(r.holder)
    else:
        inputs += [
            DerivationInput("count", output, m.id, ValueState.KNOWN, None, c)
            for m, c in leaves
        ]
        contributors += [m.id for m, _ in leaves]
    column = _Column(gaps, density, pace, own, context_values, targets, policy, lengths)
    total, on_road = column.length(group, (), 1, 0)
    for (role, name, holder), (reading, state, uses) in column.found.items():
        inputs.append(
            DerivationInput(role, name, holder, reading.state, reading.read, uses)
        )
        label = name if holder is None else holder
        if state is ValueState.UNKNOWN:
            unknown_found.append((label, uses))
        if reading.state is ValueState.ASSUMED:
            assert reading.read is not None
            assumed.append((name, reading.read, label, uses))
        if reading.state in (ValueState.KNOWN, ValueState.ASSUMED):
            contributors.append(label)
        # The value assumed for several groups is converted once.
        if (
            reading.converted is not None
            and reading.converted.record not in conversions
        ):
            conversions.append(reading.converted.record)
    settings: dict[str, object] = {
        "member_length" if member_length is not None else "density": measured,
        "spacing": tuple((gap.parameter, gap.count.value, gap.at_pace) for gap in gaps),
        "unknown": policy.rule.value,
    }
    if pace is not None:
        settings["pace"] = pace
    x: float | None = None
    na: str | None = None
    fixed_by: Iterable[str] = ()
    if not on_road:  # every member not applicable
        reasons = ", ".join(f"{r.holder} ({_reason(r)})" for r in not_applicable)
        na = f"not applicable to any member of {group.id!r}: {reasons}"
        fixed_by = (r.holder for r in not_applicable)
    elif total is not None:
        x = float(total)
        fixed_by = contributors
    unknown_names = tuple(name for name, _ in unknown_found)
    trace = Derivation(
        "column_length",
        rule,
        settings,
        tuple(fixed_by),
        tuple(inputs),
        assumptions=_assumptions(assumed),
        left_out=tuple(left_out),
        conversions=tuple(conversions),
        unknown=unknown_names,
    )
    value = Value(
        x,
        Source(f"column_length of {group.id}", rulebook=group.id, edition=edition),
        Origin.DERIVED,
        unit=unit,
        precedence=precedence,
        not_applicable=na,
        derivation=trace,
    )
    return Derived(
        ValueSet(group.id, edition, {output: value}),
        unknown={output: Tally(unknown_names, sum(k for _, k in unknown_found))},
        assumed={
            output: Tally(
                tuple(h for _, _, h, _ in assumed), sum(k for *_, k in assumed)
            )
        },
        left_out={
            output: Tally(
                tuple(x.name for x in left_out), sum(x.instances for x in left_out)
            )
        },
    )


# Validation -----------------------------------------------------------------


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _spacing(spacing: Sequence[Gap]) -> tuple[Gap, ...]:
    gaps = tuple(spacing)
    for k, gap in enumerate(gaps):
        if not isinstance(gap, Gap):
            raise TypeError(f"spacing[{k}] must be a Gap, got {gap!r}")
    return gaps


def _levels(group: Group) -> int:
    """The number of levels of groups of a column.

    Raises
    ------
    ValueError
        If a group mixes members and groups, or the groups of members are
        not all at the same depth.
    """
    depths: set[int] = set()

    def walk(g: Group, depth: int) -> None:
        kinds = {isinstance(entry, Group) for entry, _ in g.members}
        if len(kinds) == 2:
            raise ValueError(
                f"group {g.id!r} mixes members and groups: a column is measured "
                "level by level"
            )
        if kinds == {False}:
            depths.add(depth)
            return
        for entry, _ in g.members:
            assert isinstance(entry, Group)
            walk(entry, depth + 1)

    walk(group, 0)
    if len(depths) > 1:
        raise ValueError(
            f"group {group.id!r}: its groups of members are at depths "
            f"{sorted(depths)}: a column is measured level by level"
        )
    return depths.pop() + 1


def _groups(group: Group) -> Iterator[Group]:
    """The group and every group below it."""
    yield group
    for entry, _ in group.members:
        if isinstance(entry, Group):
            yield from _groups(entry)


def _targets(
    unit: str,
    vocabulary: _Vocabulary,
    member_length: str | None,
    density: str | None,
    gaps: Sequence[Gap],
    pace: str | None,
) -> dict[tuple[str, str], Parameter]:
    """The unit each input is read in, by role and parameter: a length and
    a gap in distance in the unit of the column, a density in its inverse,
    a gap in time in the unit of the first gap in time, a pace in the unit
    of the column per that unit; checked against the vocabulary before any
    value is read.

    Raises
    ------
    ValueError
        If a gap in time has no unit, or a unit of the vocabulary does not
        convert into the unit its values are read in.
    ImportError
        If a unit differs and pint is not installed.
    """
    targets: dict[tuple[str, str], Parameter] = {}

    def read_in(role: str, name: str, to_unit: str, what: str) -> None:
        _converts(vocabulary.parameter(name).unit, to_unit, f"{what} {name!r}")
        targets[(role, name)] = Parameter(name, unit=to_unit)

    if member_length is not None:
        read_in("member", member_length, unit, "member_length")
    if density is not None:
        read_in("density", density, f"1/{unit}", "density")
    timed = [gap.parameter for gap in gaps if gap.at_pace]
    time_unit = vocabulary.parameter(timed[0]).unit if timed else None
    if timed and time_unit is None:
        raise ValueError(
            f"gap {timed[0]!r} is in time: its parameter needs a unit of time"
        )
    for gap in gaps:
        to_unit = time_unit if gap.at_pace else unit
        assert to_unit is not None
        read_in("gap", gap.parameter, to_unit, "gap")
    if pace is not None:
        read_in("pace", pace, f"{unit}/{time_unit}", "pace")
    return targets


def _measure(reading: _Reading, label: str, *, positive: bool) -> Fraction:
    """A length, a gap, a density or a pace read, exactly, in the unit it
    is read in.

    Raises
    ------
    ValueError
        If it is infinite, or negative (zero too, for ``positive``).
    TypeError
        If it is not a number.
    """
    read = reading.read
    assert read is not None
    x = read.value
    if isinstance(x, str):
        raise TypeError(f"{label} must be a number, got {x!r}")
    assert x is not None
    if math.isinf(x) or (x <= 0 if positive else x < 0):
        least = "positive" if positive else "at least 0"
        raise ValueError(f"{label} must be {least} and finite, got {x!r}")
    exact = reading.exact
    assert isinstance(exact, Fraction)
    return exact


# The values of groups -------------------------------------------------------

#: The values of groups read during one call, in reading order: by role,
#: parameter and holder (``None`` for the context), the reading under the
#: policy, the state read, and the instances of the groups it serves.
type _Found = dict[tuple[str, str, str | None], tuple[_Reading, ValueState, int]]


@dataclass(frozen=True, slots=True)
class _Column:
    """What the levels of one call share; ``found`` gathers the values of
    groups as the levels read them."""

    gaps: tuple[Gap, ...]
    density: str | None
    pace: str | None
    own: Mapping[str, Mapping[str, Value]]
    context: Mapping[str, Value]
    targets: Mapping[tuple[str, str], Parameter]
    policy: OnUnknown
    lengths: Mapping[str, Fraction | None]
    found: _Found = field(default_factory=dict)

    def lookup(
        self,
        role: str,
        name: str,
        group: Group,
        ancestors: tuple[Group, ...],
        uses: int,
        *,
        positive: bool,
    ) -> Fraction | None:
        """The value ``name`` for ``group``: on the group, else on its
        nearest ancestor that gives it, else in the context; ``None``
        without a value."""
        holder: str | None = group.id
        values: Mapping[str, Value] = {}
        for g in (group, *reversed(ancestors)):
            if name in self.own[g.id]:
                holder, values = g.id, self.own[g.id]
                break
        else:
            if name in self.context:
                holder, values = None, self.context
        where = "context" if holder is None else f"group {holder!r}"
        key = (role, name, holder)
        found = self.found
        if key in found:
            reading, state, served = found[key]
        else:
            target = self.targets[(role, name)]
            raw = _read_given(where, holder or name, values, target, holder=holder)
            if raw.state is ValueState.NOT_APPLICABLE:
                raise ValueError(
                    f"{where}: the {role} {name!r} is not applicable "
                    f"({_reason(raw)}): a column needs a number"
                )
            reading = _assume(raw, target, self.policy, where)
            state, served = raw.state, 0
        found[key] = (reading, state, served + uses)
        if reading.state is ValueState.UNKNOWN:
            return None
        label = (
            f"the value assumed for {name!r}"
            if reading.state is ValueState.ASSUMED
            else f"{where}: the {role} {name!r}"
        )
        return _measure(reading, label, positive=positive)

    def length(
        self, group: Group, ancestors: tuple[Group, ...], uses: int, level: int
    ) -> tuple[Fraction | None, bool]:
        """The length of ``group`` (``None`` when an input has no value),
        and whether it is on the road (at least one member is)."""
        members = isinstance(group.members[0][0], Member)
        if members and self.density is not None:
            n = sum(c for _, c in group.members)
            d = self.lookup(
                "density", self.density, group, ancestors, uses, positive=True
            )
            return (None if d is None else Fraction(n) / d), True
        units: list[tuple[Fraction | None, int]] = []
        for entry, c in group.members:
            if isinstance(entry, Member):
                if entry.id in self.lengths:
                    units.append((self.lengths[entry.id], c))
            else:
                sub, on_road = self.length(
                    entry, (*ancestors, group), uses * c, level + 1
                )
                if on_road:
                    units.append((sub, c))
        n = sum(c for _, c in units)
        if not n:
            return None, False
        total: Fraction | None = None
        if all(x is not None for x, _ in units):
            total = sum((c * x for x, c in units if x is not None), Fraction(0))
        gap = self.gaps[level]
        k = n - 1 if gap.count is GapCount.BETWEEN else n
        if k:
            step = self.lookup(
                "gap", gap.parameter, group, ancestors, uses, positive=False
            )
            if gap.at_pace:
                assert self.pace is not None
                rate = self.lookup(
                    "pace", self.pace, group, ancestors, uses, positive=True
                )
                step = None if step is None or rate is None else step * rate
            total = None if total is None or step is None else total + k * step
        return total, True
