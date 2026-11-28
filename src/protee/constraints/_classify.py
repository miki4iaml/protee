# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""A class from thresholds on the characteristics of a subject, and the
value a class selects in a table.

Both read values given directly (a value set, resolved values, derived
values), not the members of a group: an input is named by its parameter
in the trace, and its holder is ``None``.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from protee.constraints._derive import (
    Comparison,
    Derived,
    Exact,
    OnUnknown,
    Tally,
    UnknownRule,
    ValuesLike,
    _assume,
    _assumptions,
    _check_policy,
    _check_unknown,
    _converts,
    _crosses,
    _named,
    _partial,
    _read_given,
    _Reading,
    _reason,
    _vocabulary,
)
from protee.constraints._model import (
    Assumption,
    Conversion,
    Datum,
    Derivation,
    DerivationInput,
    LeftOut,
    LeftOutCause,
    Origin,
    Parameter,
    Source,
    Value,
    ValueSet,
    ValueState,
    _datum_text,
    _name,
)

__all__ = [
    "Characteristic",
    "NotApplicable",
    "classify_by_thresholds",
    "select_by_class",
]

#: The comparisons under which thresholds increase.
_INCREASING = frozenset({Comparison.ABOVE, Comparison.AT_LEAST})


@dataclass(frozen=True, slots=True)
class Characteristic:
    """A characteristic of a subject, its thresholds, and when a value
    crosses them.

    The rank of a value *x* is one plus the number of thresholds it
    crosses: below every threshold, *x* is of the first class; beyond the
    last one, of the last class.

    Attributes
    ----------
    parameter : str
        The canonical parameter read on the subject, a number.
    thresholds : tuple of str
        The parameters of its thresholds, in the order in which a stronger
        value crosses them (ranks 2, 3, ...); their values come from a
        value set taken from a text.
    crossing : Comparison
        When *x* crosses a threshold *b*, declared without default, since
        texts and sheets round their values: ``above`` keeps *x* = *b* in
        the lower class (a text that says "up to *b*"), ``at_least`` moves
        it up ("from *b*"). Under ``below`` or ``at_most``, a smaller value
        is stronger, and the thresholds decrease.

    Raises
    ------
    ValueError
        If a name is empty, there is no threshold, or a threshold is given
        twice.
    TypeError
        If ``thresholds`` is a string instead of a sequence of names.

    Examples
    --------
    >>> c = Characteristic("length", ["length_1", "length_2"], Comparison.ABOVE)
    >>> c.thresholds
    ('length_1', 'length_2')
    """

    parameter: str
    thresholds: tuple[str, ...]
    crossing: Comparison

    def __post_init__(self) -> None:
        _name("parameter", self.parameter)
        given: object = self.thresholds
        if isinstance(given, str):
            raise TypeError(
                f"characteristic {self.parameter!r}: thresholds is a sequence of "
                f"parameters, got the string {given!r}"
            )
        thresholds = tuple(self.thresholds)
        if not thresholds:
            raise ValueError(f"characteristic {self.parameter!r} needs a threshold")
        for k, threshold in enumerate(thresholds):
            _name("threshold", threshold)
            if threshold in thresholds[:k]:
                raise ValueError(
                    f"characteristic {self.parameter!r}: threshold {threshold!r} "
                    "given twice"
                )
        object.__setattr__(self, "thresholds", thresholds)
        object.__setattr__(self, "crossing", Comparison(self.crossing))


@dataclass(frozen=True, slots=True)
class NotApplicable:
    """The entry of a class without a value of its own in the table of
    :func:`select_by_class`, with the reason.

    The value selected for such a class is not applicable, with this
    reason: never an infinite limit, which would read the arcs and count
    unknowns for a limit without effect.

    Attributes
    ----------
    reason : str
        Why the class has no value of its own (the general limits apply,
        the text gives a value elsewhere only).

    Raises
    ------
    ValueError
        If the reason is empty.
    """

    reason: str

    def __post_init__(self) -> None:
        _name("reason", self.reason)


def classify_by_thresholds(
    subject: ValuesLike,
    *,
    characteristics: Sequence[Characteristic],
    thresholds: ValuesLike,
    classes: Sequence[str],
    output: str,
    parameters: Iterable[Parameter],
    unknown: OnUnknown,
    rulebook: str,
    edition: str,
    precedence: int = 0,
) -> Derived:
    """The class of a subject: the strongest of its characteristics
    decides.

    Each characteristic has a rank, one plus the number of its thresholds
    its value crosses (see :class:`Characteristic`); the class is
    ``classes[r - 1]`` for the highest rank *r*. Every comparison is exact
    (a float is read as the decimal it shows, a converted value as the
    decimal of its float): a value equal to a threshold is placed by the
    declared crossing, and the next float is beyond it.

    Parameters
    ----------
    subject : ValueSet, ResolvedValues or Derived
        The values of the characteristics, often derived by
        :func:`aggregate`.
    characteristics : sequence of Characteristic
        Distinct, each with ``len(classes) - 1`` thresholds (one scale for
        all); their order does not matter.
    thresholds : ValueSet, ResolvedValues or Derived
        The values of the thresholds, with their sources (the value set of
        a text). A threshold in another unit than its characteristic is
        converted into it, exactly, with the optional extra ``units`` (a
        threshold of 72 000 kg is 72 t), and the conversion recorded.
    classes : sequence of str
        The labels of the ranks 1, 2, ..., from the weakest; distinct, at
        least two.
    output : str
        The parameter that receives the class, without unit.
    parameters : iterable of Parameter
        The vocabulary: units, and the aliases of the value sets read.
    unknown : OnUnknown
        The policy for the inputs without a value, without default.
    rulebook, edition : str
        The rulebook and the edition of the value set returned.
    precedence : int
        The precedence of the value returned.

    Returns
    -------
    Derived
        One value, the class, of origin ``derived``, with its
        :class:`Derivation` (rule ``highest_rank``): the characteristics
        that reach the highest rank in ``fixed_by`` (all of them at rank
        1), every characteristic and threshold read as an input (roles
        ``characteristic`` and ``threshold``), as read, with its source,
        and the conversions into the unit of the characteristic.

        A characteristic not applicable is left out under every policy; if
        every one is, the class is not applicable. A characteristic is
        unknown when its value or one of its thresholds has no value.
        Under ``propagate``, an unknown characteristic leaves the class to
        be set, its derivation keeping the class of the known
        characteristics as ``bound`` (the class is at least as strong),
        which ``class_admissibility`` reads (see :func:`evaluate`); a
        characteristic to be set with a bound on the side its comparison
        goes (the maximum of a group, at least its bound, under ``above``
        and ``at_least``; a minimum, at most its bound, under ``below`` and
        ``at_most``) reaches at least the rank of its bound, and counts so
        in ``bound``; a characteristic, known or bounded, at the highest
        rank of the scale decides the class anyway, and the trace says so
        (``unknown`` filled).
        ``known_only`` classifies on the known characteristics, which may
        underestimate the class: its justification says why it may.
        ``assume`` takes the value assumed for each input without a value.

    Raises
    ------
    ValueError
        If the classes or the characteristics are inconsistent (see
        above), a parameter is not in the vocabulary, the output has a
        unit, a threshold does not convert into the unit of its
        characteristic (different dimensions) or serves characteristics in
        different units, is not applicable, or the thresholds of a
        characteristic are not strictly monotonic (increasing under
        ``above`` and ``at_least``, decreasing under ``below`` and
        ``at_most``), or the policy assumes a value no input reads,
        misses one, or assumes one that the bound of an input to be set
        does not allow (see :class:`UnknownRule`).
    ImportError
        If a unit differs and pint is not installed (the optional extra
        ``units``).
    TypeError
        If a characteristic or a threshold is not a number, or an argument
        is not of its type.

    Examples
    --------
    >>> def given(**values):
    ...     source = Source("Sheet A", locator="p. 2")
    ...     return ValueSet("sheet-a", "1", {
    ...         k: Value(x, source, Origin.STATEMENT, unit="m")
    ...         for k, x in values.items()})
    >>> derived = classify_by_thresholds(
    ...     given(length=27.0),
    ...     characteristics=[Characteristic("length", ["l1", "l2"], Comparison.ABOVE)],
    ...     thresholds=given(l1=20.0, l2=25.0),
    ...     classes=["1", "2", "3"],
    ...     output="category",
    ...     parameters=[Parameter(p, unit="m") for p in ("length", "l1", "l2")]
    ...     + [Parameter("category")],
    ...     unknown=OnUnknown.propagate(),
    ...     rulebook="classes",
    ...     edition="1",
    ... )
    >>> derived["category"].value, derived["category"].derivation.fixed_by
    ('3', ('length',))
    """
    policy = _check_unknown(unknown)
    _name("rulebook", rulebook)
    _name("edition", edition)
    labels = _labels(classes)
    rows = _characteristics(characteristics, len(labels))
    vocabulary = _vocabulary(parameters)
    out = vocabulary.parameter(output)
    if out.unit is not None:
        raise ValueError(
            f"classify_by_thresholds gives a class: {output!r} must have no unit, "
            f"got {out.unit!r}"
        )
    # Each threshold is read in the unit of its characteristic.
    targets: dict[str, Parameter] = {}
    for row in rows:
        unit = vocabulary.parameter(row.parameter).unit
        for name in row.thresholds:
            target = targets.setdefault(name, Parameter(name, unit=unit))
            if target.unit != unit:
                raise ValueError(
                    f"threshold {name!r} serves characteristics in {target.unit!r} "
                    f"and in {unit!r}: give each its own threshold"
                )
            _converts(
                vocabulary.parameter(name).unit,
                unit,
                f"threshold {name!r} of {row.parameter!r}",
            )
    read = [row.parameter for row in rows] + [t for row in rows for t in row.thresholds]
    _check_policy(policy, read, vocabulary)
    given = _named(subject, vocabulary, "subject")
    limits = _named(thresholds, vocabulary, "thresholds")
    found: _Found = {}
    ranks: dict[str, int] = {}
    # The ranks that characteristics to be set reach at least, by a bound,
    # and the conversions of those bounds.
    lows: dict[str, int] = {}
    read_bounds: tuple[Conversion, ...] = ()
    pending: list[str] = []
    not_applicable: list[tuple[str, str]] = []
    left_out: list[LeftOut] = []
    for row in rows:
        parameter = vocabulary.parameter(row.parameter)
        reading = _take(found, "characteristic", given, parameter, policy)
        if reading.state is ValueState.NOT_APPLICABLE:
            reason = _reason(reading)
            not_applicable.append((row.parameter, reason))
            left_out.append(
                LeftOut(row.parameter, LeftOutCause.NOT_APPLICABLE, reason, 1)
            )
            continue
        x = _numeric(reading, row.parameter, "characteristic")
        bounds = [_threshold(found, limits, targets[t], policy) for t in row.thresholds]
        _check_order(row, bounds)
        if x is None or None in bounds:
            pending.append(row.parameter)
            if policy.rule is UnknownRule.KNOWN_ONLY:
                assert policy.justification is not None
                left_out.append(
                    LeftOut(
                        row.parameter, LeftOutCause.UNKNOWN, policy.justification, 1
                    )
                )
            elif x is None and None not in bounds:
                low = _low(row, reading, parameter, bounds)
                if low is not None:
                    lows[row.parameter], record = low
                    read_bounds += () if record is None else (record,)
            continue
        crossed = (_crosses(row.crossing, x[1], b[1]) for b in bounds if b is not None)
        ranks[row.parameter] = 1 + sum(crossed)
    settings: dict[str, object] = {
        "characteristics": {
            row.parameter: {
                "thresholds": row.thresholds,
                "crossing": row.crossing.value,
            }
            for row in rows
        },
        "classes": labels,
        "unknown": policy.rule.value,
    }
    if policy.justification is not None:
        settings["justification"] = policy.justification
    inputs, unknown_names, assumptions, conversions = _trace(found)
    conversions += read_bounds
    label: str | None = None
    na: str | None = None
    fixed_by: tuple[str, ...] = ()
    bound: str | None = None
    bound_by: tuple[str, ...] = ()
    if not ranks and not pending:
        shown = ", ".join(f"{name} ({reason})" for name, reason in not_applicable)
        na = f"no characteristic applies: {shown}"
        fixed_by = tuple(name for name, _ in not_applicable)
    elif ranks or lows:
        reached = lows | ranks
        top = max(reached.values())
        fixers = tuple(name for name, rank in reached.items() if rank == top)
        # DD9: the highest rank of the scale decides despite unknowns.
        decided = (
            not pending
            or policy.rule is not UnknownRule.PROPAGATE
            or top == len(labels)
        )
        if decided:
            label, fixed_by = labels[top - 1], fixers
        else:
            bound, bound_by = labels[top - 1], fixers
    trace = Derivation(
        "classify_by_thresholds",
        "highest_rank",
        settings,
        fixed_by,
        inputs,
        assumptions=assumptions,
        left_out=tuple(left_out),
        conversions=conversions,
        unknown=unknown_names,
        bound=bound,
        bound_fixed_by=bound_by,
    )
    return _result(
        "classify_by_thresholds",
        output,
        None,
        label,
        trace,
        na,
        _tallies(found, left_out),
        rulebook=rulebook,
        edition=edition,
        precedence=precedence,
    )


def select_by_class(
    subject: ValuesLike,
    *,
    by: str,
    table: Mapping[str, str | NotApplicable],
    values: ValuesLike,
    output: str,
    parameters: Iterable[Parameter],
    unknown: OnUnknown,
    rulebook: str,
    edition: str,
    precedence: int = 0,
) -> Derived:
    """The value a class selects in a table.

    The class is read in ``subject[by]``, derived (by
    :func:`classify_by_thresholds`) or given; ``table[class]`` names the
    parameter whose value, resolved in ``values``, is taken as the output,
    in the unit of the output. A table with two keys (a class and a kind
    of element) takes one call per output, each bound to a requirement of
    its own scope.

    Parameters
    ----------
    subject : ValueSet, ResolvedValues or Derived
        Holds the class.
    by : str
        The parameter of the class, a label.
    table : mapping of str to str or NotApplicable
        By class label: the parameter selected, or :class:`NotApplicable`
        for a class without a value of its own.
    values : ValueSet, ResolvedValues or Derived
        Where the parameters of the table are resolved (the value set of a
        text).
    output : str
        The parameter that receives the value; a value selected in another
        unit is converted into its unit, exactly, with the optional extra
        ``units``, and the conversion recorded.
    parameters : iterable of Parameter
        The vocabulary.
    unknown : OnUnknown
        The policy for the inputs without a value, without default:
        ``propagate`` or ``assume``.
    rulebook, edition : str
        The rulebook and the edition of the value set returned.
    precedence : int
        The precedence of the value returned.

    Returns
    -------
    Derived
        One value, of origin ``derived``, with its :class:`Derivation`
        (rule ``table``): the class (role ``class``, with its own
        derivation) and the value selected (role ``chosen``, with its
        source) as inputs, ``by`` in ``fixed_by``.

        The value is not applicable when the class is, when its entry is
        :class:`NotApplicable` (``"class '1' has no value of its own:
        <reason>"``), or when the value selected is. Under ``propagate``,
        a class or a value selected without a value leaves the output to
        be set, naming it, without a bound: a class to be set and bounded
        (at least as strict as a label) still leaves the value selected
        to be set, whatever the values of the classes it may be; under
        ``assume``, each takes the value assumed for its parameter.

    Raises
    ------
    ValueError
        If ``known_only`` is given (a single class has no known inputs to
        keep), the table is empty, a class is not in the table, a
        parameter is not in the vocabulary, a parameter of the table does
        not convert into the unit of the output, or the policy assumes a
        value no input reads, misses one, or assumes a class or a value
        that the bound of an input to be set does not allow (see
        :class:`UnknownRule`).
    ImportError
        If a unit differs and pint is not installed (the optional extra
        ``units``).
    TypeError
        If the class is not a label, an entry of the table is neither a
        parameter nor :class:`NotApplicable`, or an argument is not of its
        type.

    Examples
    --------
    >>> source = Source("Regulation A", locator="art. 14")
    >>> speeds = ValueSet("reg-a", "1", {
    ...     "speed_3": Value(50.0, source, Origin.RULEBOOK, unit="km/h")})
    >>> category = ValueSet("sheet-a", "1", {
    ...     "category": Value("3", Source("Sheet A"), Origin.STATEMENT)})
    >>> derived = select_by_class(
    ...     category,
    ...     by="category",
    ...     table={"1": NotApplicable("the general limits apply"),
    ...            "3": "speed_3"},
    ...     values=speeds,
    ...     output="speed",
    ...     parameters=[Parameter("category"), Parameter("speed_3", unit="km/h"),
    ...                 Parameter("speed", unit="km/h")],
    ...     unknown=OnUnknown.propagate(),
    ...     rulebook="speeds",
    ...     edition="1",
    ... )
    >>> derived["speed"].value, derived["speed"].unit
    (50.0, 'km/h')
    """
    policy = _check_unknown(unknown)
    if policy.rule is UnknownRule.KNOWN_ONLY:
        raise ValueError(
            "known_only does not apply to a single class: use propagate or assume"
        )
    _name("by", by)
    _name("rulebook", rulebook)
    _name("edition", edition)
    entries = _entries(table)
    vocabulary = _vocabulary(parameters)
    by_parameter = vocabulary.parameter(by)
    out = vocabulary.parameter(output)
    for label, entry in entries.items():
        if isinstance(entry, str):
            _converts(
                vocabulary.parameter(entry).unit,
                out.unit,
                f"class {label!r} selects {entry!r}",
            )
    selected = [entry for entry in entries.values() if isinstance(entry, str)]
    _check_policy(policy, (by, *selected), vocabulary)
    given = _named(subject, vocabulary, "subject")
    resolved = _named(values, vocabulary, "values")
    found: _Found = {}
    left_out: list[LeftOut] = []
    x: Datum | None = None
    na: str | None = None
    fixed_by: tuple[str, ...] = ()
    reading = _take(found, "class", given, by_parameter, policy)
    if reading.state is ValueState.NOT_APPLICABLE:
        reason = _reason(reading)
        left_out.append(LeftOut(by, LeftOutCause.NOT_APPLICABLE, reason, 1))
        na = f"the class {by!r} is not applicable: {reason}"
        fixed_by = (by,)
    elif reading.state is not ValueState.UNKNOWN:
        label = _class_label(reading, by)
        if label not in entries:
            raise ValueError(f"class {label!r} is not in the table {sorted(entries)}")
        fixed_by = (by,)
        entry = entries[label]
        if isinstance(entry, NotApplicable):
            na = f"class {label!r} has no value of its own: {entry.reason}"
        else:
            # The value selected is read in the unit of the output.
            target = Parameter(entry, unit=out.unit)
            chosen = _take(found, "chosen", resolved, target, policy)
            if chosen.state is ValueState.NOT_APPLICABLE:
                reason = _reason(chosen)
                left_out.append(LeftOut(entry, LeftOutCause.NOT_APPLICABLE, reason, 1))
                na = (
                    f"the value {entry!r} of class {label!r} is not applicable: "
                    f"{reason}"
                )
            elif chosen.state is ValueState.UNKNOWN:
                fixed_by = ()
            else:
                assert chosen.value is not None
                x = chosen.value.value
    settings: dict[str, object] = {
        "by": by,
        "table": {k: e for k, e in sorted(entries.items()) if isinstance(e, str)},
        "unknown": policy.rule.value,
    }
    reasons = {
        k: e.reason for k, e in sorted(entries.items()) if isinstance(e, NotApplicable)
    }
    if reasons:
        settings["not_applicable"] = reasons
    inputs, unknown_names, assumptions, conversions = _trace(found)
    trace = Derivation(
        "select_by_class",
        "table",
        settings,
        fixed_by,
        inputs,
        assumptions=assumptions,
        left_out=tuple(left_out),
        conversions=conversions,
        unknown=unknown_names,
    )
    return _result(
        "select_by_class",
        output,
        out.unit,
        x,
        trace,
        na,
        _tallies(found, left_out),
        rulebook=rulebook,
        edition=edition,
        precedence=precedence,
    )


# Validation -----------------------------------------------------------------


def _labels(classes: Sequence[str]) -> tuple[str, ...]:
    if isinstance(classes, str):
        raise TypeError(f"classes is a sequence of labels, got the string {classes!r}")
    labels = tuple(classes)
    for k, label in enumerate(labels):
        _name("class", label)
        if label in labels[:k]:
            raise ValueError(f"classes: {label!r} given twice")
    if len(labels) < 2:
        raise ValueError(f"classes: at least two labels, got {list(labels)}")
    return labels


def _characteristics(
    characteristics: Sequence[Characteristic], classes: int
) -> tuple[Characteristic, ...]:
    """The characteristics, sorted by parameter: one scale for all.

    Raises
    ------
    ValueError
        If there is none, one is given twice, or one has not ``classes - 1``
        thresholds.
    TypeError
        If an element is not a :class:`Characteristic`.
    """
    rows = tuple(characteristics)
    if not rows:
        raise ValueError("no characteristic: give at least one")
    for k, row in enumerate(rows):
        if not isinstance(row, Characteristic):
            raise TypeError(
                f"characteristics[{k}] must be a Characteristic, got {row!r}"
            )
    rows = tuple(sorted(rows, key=lambda row: row.parameter))
    for one, other in itertools.pairwise(rows):
        if one.parameter == other.parameter:
            raise ValueError(f"characteristic {one.parameter!r} given twice")
    for row in rows:
        k = len(row.thresholds)
        if k != classes - 1:
            plural = "threshold" if k == 1 else "thresholds"
            raise ValueError(
                f"characteristic {row.parameter!r} has {k} {plural}, the {classes} "
                f"classes need {classes - 1}"
            )
    return rows


def _entries(
    table: Mapping[str, str | NotApplicable],
) -> dict[str, str | NotApplicable]:
    entries = dict(table)
    if not entries:
        raise ValueError(
            "the table is empty: give each class its parameter, or NotApplicable"
        )
    for label, entry in entries.items():
        _name("class", label)
        if isinstance(entry, NotApplicable):
            continue
        if not isinstance(entry, str):
            raise TypeError(
                f"table[{label!r}] must be a parameter or NotApplicable, got {entry!r}"
            )
        _name(f"table[{label!r}]", entry)
    return entries


def _check_order(
    row: Characteristic, bounds: Sequence[tuple[str, Exact] | None]
) -> None:
    """The known thresholds of a characteristic are strictly monotonic, in
    the direction of its crossing.

    Raises
    ------
    ValueError
        If they are not; the message shows each threshold as read, and as
        converted into the unit of the characteristic.
    """
    increasing = row.crossing in _INCREASING
    known = [b for b in bounds if b is not None]
    for (a, xa), (b, xb) in itertools.pairwise(known):
        if (xa < xb) if increasing else (xa > xb):
            continue
        direction = "increase" if increasing else "decrease"
        raise ValueError(
            f"characteristic {row.parameter!r}: thresholds must {direction} "
            f"strictly for {row.crossing.value!r}, got {a} then {b}"
        )


def _low(
    row: Characteristic,
    reading: _Reading,
    parameter: Parameter,
    bounds: Sequence[tuple[str, Exact] | None],
) -> tuple[int, Conversion | None] | None:
    """The rank a characteristic to be set reaches at least, when its
    derivation bounds it on the side its comparison goes (at least a value
    under ``above`` and ``at_least``, at most under ``below`` and
    ``at_most``), and the conversion of its bound into the unit of the
    characteristic, if any; ``None`` otherwise. Every threshold is
    known."""
    p = _partial(reading, parameter, f"subject: {row.parameter!r}")
    side = "at least" if row.crossing in _INCREASING else "at most"
    if p is None or p.side != side:
        return None
    assert p.exact is not None
    crossed = (_crosses(row.crossing, p.exact, b[1]) for b in bounds if b is not None)
    return 1 + sum(crossed), p.conversion


# Inputs given directly ------------------------------------------------------

#: Where an input given directly is read, by role.
_WHERE = {
    "characteristic": "subject",
    "threshold": "thresholds",
    "class": "subject",
    "chosen": "values",
}

#: The inputs read, by role and parameter: the reading under the policy,
#: and the state read.
type _Found = dict[tuple[str, str], tuple[_Reading, ValueState]]


def _take(
    found: _Found,
    role: str,
    values: Mapping[str, Value],
    target: Parameter,
    policy: OnUnknown,
) -> _Reading:
    """The input ``target.name`` given directly, read once, in the unit of
    ``target``, under the policy."""
    key = (role, target.name)
    if key not in found:
        where = _WHERE[role]
        raw = _read_given(where, target.name, values, target)
        found[key] = (_assume(raw, target, policy, where), raw.state)
    return found[key][0]


def _threshold(
    found: _Found,
    values: Mapping[str, Value],
    target: Parameter,
    policy: OnUnknown,
) -> tuple[str, Exact] | None:
    """A threshold as a message shows it (as read, and as converted into
    the unit of its characteristic), and exactly, in that unit; ``None``
    without a value.

    Raises
    ------
    ValueError
        If it is not applicable.
    TypeError
        If it is not a number.
    """
    reading = _take(found, "threshold", values, target, policy)
    if reading.state is ValueState.NOT_APPLICABLE:
        raise ValueError(
            f"threshold {target.name!r} is not applicable: a threshold is a number"
        )
    number = _numeric(reading, target.name, "threshold")
    if number is None:
        return None
    read, value = reading.read, reading.value
    assert read is not None
    assert value is not None
    shown = _datum_text(number[0], read.unit)
    if reading.converted is not None:
        assert value.value is not None
        shown += f" ({_datum_text(value.value, value.unit)})"
    return shown, number[1]


def _numeric(reading: _Reading, name: str, what: str) -> tuple[Datum, Exact] | None:
    """A number as read, and its exact value in the unit it is read in;
    ``None`` without a value.

    Raises
    ------
    TypeError
        If it is not a number.
    """
    if reading.state is ValueState.UNKNOWN:
        return None
    read = reading.read
    assert read is not None
    x = read.value
    assert x is not None
    if isinstance(x, str):
        label = (
            f"the value assumed for {name!r}"
            if reading.state is ValueState.ASSUMED
            else f"{what} {name!r}"
        )
        raise TypeError(f"{label} must be a number, got {x!r}")
    return x, reading.exact


def _class_label(reading: _Reading, by: str) -> str:
    """The label of a class read.

    Raises
    ------
    TypeError
        If it is not a string.
    """
    assert reading.value is not None
    x = reading.value.value
    if not isinstance(x, str):
        label = (
            f"the value assumed for {by!r}"
            if reading.state is ValueState.ASSUMED
            else f"the class {by!r}"
        )
        raise TypeError(f"{label} must be a label, got {x!r}")
    return x


def _trace(
    found: _Found,
) -> tuple[
    tuple[DerivationInput, ...],
    tuple[str, ...],
    tuple[Assumption, ...],
    tuple[Conversion, ...],
]:
    """The inputs as read, the names of those without a value, the
    assumptions and the conversions."""
    inputs = tuple(
        DerivationInput(role, name, None, r.state, r.read)
        for (role, name), (r, _) in found.items()
    )
    unknown = tuple(
        name for (_, name), (_, state) in found.items() if state is ValueState.UNKNOWN
    )
    assumed = []
    for (_, name), (r, _) in found.items():
        if r.state is ValueState.ASSUMED:
            assert r.read is not None
            assumed.append((name, r.read, name, 1))
    conversions = tuple(
        r.converted.record for r, _ in found.values() if r.converted is not None
    )
    return inputs, unknown, _assumptions(assumed), conversions


def _tallies(found: _Found, left_out: Sequence[LeftOut]) -> tuple[Tally, Tally, Tally]:
    """The inputs unknown, assumed and left out."""
    unknown = [n for (_, n), (_, state) in found.items() if state is ValueState.UNKNOWN]
    assumed = [n for (_, n), (r, _) in found.items() if r.state is ValueState.ASSUMED]
    return (
        Tally(tuple(unknown), len(unknown)),
        Tally(tuple(assumed), len(assumed)),
        Tally(tuple(x.name for x in left_out), sum(x.instances for x in left_out)),
    )


def _result(
    name: str,
    output: str,
    unit: str | None,
    x: Datum | None,
    trace: Derivation,
    na: str | None,
    tallies: tuple[Tally, Tally, Tally],
    *,
    rulebook: str,
    edition: str,
    precedence: int,
) -> Derived:
    """The derived value of ``output``, in a value set of its own."""
    value = Value(
        x,
        Source(f"{name} of {rulebook}", rulebook=rulebook, edition=edition),
        Origin.DERIVED,
        unit=unit,
        precedence=precedence,
        not_applicable=na,
        derivation=trace,
    )
    unknown, assumed, left = tallies
    return Derived(
        ValueSet(rulebook, edition, {output: value}),
        unknown={output: unknown},
        assumed={output: assumed},
        left_out={output: left},
    )
