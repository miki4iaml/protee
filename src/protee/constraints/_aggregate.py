# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The values of a group from the values of its members."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from protee.constraints._derive import (
    Comparison,
    Derived,
    Exact,
    OnUnknown,
    Tally,
    UnknownRule,
    _check_policy,
    _crosses,
    _given,
    _label,
    _member_values,
    _partition,
    _read,
    _Reading,
    _reason,
    _Vocabulary,
    _vocabulary,
    _weighted_sum,
)
from protee.constraints._groups import Group, Member, tree_left_out
from protee.constraints._model import (
    Datum,
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

__all__ = ["AggregateKind", "Aggregation", "aggregate"]


class AggregateKind(StrEnum):
    """The rule that gives the value of a group from those of its members.

    With *v* the value of a member and *c* its count in the flattened group:

    - ``max``, ``min``: the largest or the smallest *v*; the counts play
      no part; the members that reach it fix it;
    - ``strictest``: the label of highest rank in a declared order, from
      the least to the most demanding;
    - ``sum``: the sum of *c v*;
    - ``count``: the sum of *c*, the number of members; it reads no value;
    - ``mean``: the sum of *c v* divided by the sum of *c*; for additive
      quantities only (lengths, masses), which the code cannot check;
    - ``threshold_count``: the sum of *c* over the members whose *v*
      crosses a threshold, by a declared :class:`Comparison`.
    """

    MAX = "max"
    MIN = "min"
    STRICTEST = "strictest"
    SUM = "sum"
    COUNT = "count"
    MEAN = "mean"
    THRESHOLD_COUNT = "threshold_count"


#: Rules that ``known_only`` would shorten.
_ADDITIVE = frozenset(
    {AggregateKind.SUM, AggregateKind.MEAN, AggregateKind.THRESHOLD_COUNT}
)
#: Rules that give a number of members, without unit.
_COUNTS = frozenset({AggregateKind.COUNT, AggregateKind.THRESHOLD_COUNT})
#: Envelopes: under ``propagate``, the extreme of the known inputs bounds
#: the unknown value.
_ENVELOPES = frozenset({AggregateKind.MAX, AggregateKind.MIN, AggregateKind.STRICTEST})


@dataclass(frozen=True, slots=True)
class Aggregation:
    """The rule of a parameter of a group, and what it reads.

    Build it with its constructor of the same name: :meth:`max`,
    :meth:`min`, :meth:`strictest`, :meth:`sum`, :meth:`count`,
    :meth:`mean`, :meth:`threshold_count`.

    Attributes
    ----------
    kind : AggregateKind
    of : str, optional
        The canonical parameter read on every member; ``None`` for
        ``count``.
    order : tuple of str
        For ``strictest``: the labels, from the least to the most
        demanding.
    threshold : Value, optional
        For ``threshold_count``: the threshold, a known number with its
        source, in the unit of ``of`` or in a unit that converts into it
        (with the optional extra ``units``).
    comparison : Comparison, optional
        For ``threshold_count``: when a value crosses the threshold,
        without default (at equality, ``at_least`` counts and ``above``
        does not).

    Raises
    ------
    ValueError
        If the options do not fit the rule.
    """

    kind: AggregateKind
    of: str | None = None
    order: tuple[str, ...] = ()
    threshold: Value | None = None
    comparison: Comparison | None = None

    def __post_init__(self) -> None:
        kind = AggregateKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind is AggregateKind.COUNT:
            if self.of is not None:
                raise ValueError("count reads no parameter")
        elif self.of is None:
            raise ValueError(f"{kind} reads a parameter: give of")
        else:
            _name("of", self.of)
        order: tuple[object, ...] = tuple(self.order)
        if kind is AggregateKind.STRICTEST:
            labels = {x for x in order if isinstance(x, str) and x.strip()}
            if len(order) < 2 or len(labels) != len(order):
                raise ValueError(
                    "strictest needs an order of at least two distinct labels"
                )
        elif order:
            raise ValueError("only strictest takes an order")
        object.__setattr__(self, "order", order)
        given = self.threshold is not None or self.comparison is not None
        if kind is AggregateKind.THRESHOLD_COUNT:
            t = self.threshold
            if (
                not isinstance(t, Value)
                or isinstance(t.value, str)
                or t.value is None
                or self.comparison is None
            ):
                raise ValueError(
                    "threshold_count needs a known threshold and its comparison"
                )
            object.__setattr__(self, "comparison", Comparison(self.comparison))
        elif given:
            raise ValueError("only threshold_count takes a threshold and a comparison")

    @classmethod
    def max(cls, of: str) -> Aggregation:
        """The largest value of ``of`` (the most limiting, for a quantity
        at most a limit)."""
        return cls(AggregateKind.MAX, of)

    @classmethod
    def min(cls, of: str) -> Aggregation:
        """The smallest value of ``of`` (the slowest, the shallowest)."""
        return cls(AggregateKind.MIN, of)

    @classmethod
    def strictest(cls, of: str, order: Sequence[str]) -> Aggregation:
        """The label of ``of`` of highest rank in ``order``, given from the
        least to the most demanding."""
        return cls(AggregateKind.STRICTEST, of, order=tuple(order))

    @classmethod
    def sum(cls, of: str) -> Aggregation:
        """The sum of ``of`` weighted by the counts."""
        return cls(AggregateKind.SUM, of)

    @classmethod
    def count(cls) -> Aggregation:
        """The number of members, the counts summed."""
        return cls(AggregateKind.COUNT)

    @classmethod
    def mean(cls, of: str) -> Aggregation:
        """The mean of ``of`` weighted by the counts; for additive
        quantities only."""
        return cls(AggregateKind.MEAN, of)

    @classmethod
    def threshold_count(
        cls, of: str, threshold: Value, comparison: Comparison
    ) -> Aggregation:
        """The number of members whose ``of`` crosses ``threshold`` by
        ``comparison``."""
        return cls(
            AggregateKind.THRESHOLD_COUNT,
            of,
            threshold=threshold,
            comparison=comparison,
        )


def aggregate(
    group: Group,
    rules: Mapping[str, Aggregation],
    *,
    parameters: Iterable[Parameter],
    unknown: OnUnknown,
    edition: str,
    precedence: int = 0,
) -> Derived:
    """The values of a group, each from the values of its members by a
    declared rule.

    The rules read the members of the flattened group (see
    :meth:`Group.flatten`), never the values of the group itself. The
    result is a function of the multiset of the members: their order does
    not matter, and the arithmetic is exact (a float is read as the decimal
    it shows, and the result rounded once).

    Parameters
    ----------
    group : Group
    rules : mapping of str to Aggregation
        By output parameter, a canonical name of ``parameters``.
    parameters : iterable of Parameter
        The vocabulary: it gives the units and resolves the aliases the
        sheets of the members use (``requirements.parameters`` and those of
        the rulebooks of the sheets).
    unknown : OnUnknown
        The policy for the inputs without a value, without default.
    edition : str
        The edition of the value set returned.
    precedence : int
        The precedence of the values returned.

    Returns
    -------
    Derived
        Its rulebook is the identifier of the group. Each value has the
        origin ``derived``, the source ``"aggregate of <group>"``, the
        unit of its output parameter, and its :class:`Derivation`: the
        rule, the members that fix the value (ties all cited), every input
        with its source and state, the assumptions, and the members left
        out (not applicable, excluded, of count 0, unknown under
        ``known_only``).

        A member whose value is not applicable is left out under every
        policy; if every member is, the value is not applicable too. Under
        ``propagate``, an unknown input leaves the value to be set; its
        derivation keeps, for ``max``, ``min`` and ``strictest``, the
        extreme of the known inputs as ``bound``, which an admissibility
        requirement reads: an arc a known member fails fails for certain
        (see :func:`evaluate`). Only ``strictest`` is decided despite
        unknown inputs, when a known value reaches the last label of the
        order.

        The envelope follows the direction of the requirement it feeds: a
        quantity at most a limit (``threshold_admissibility``) by its
        maximum, a capacity at least a demand (``capacity_admissibility``)
        by its minimum, a required class (``class_admissibility``) by
        ``strictest``; the code does not check it.

        An input in another unit than the parameter it reads (a value of a
        member, the value assumed, the threshold) is converted into it,
        exactly, with the optional extra ``units``; each conversion is
        recorded in the derivation (:class:`Conversion`), and a converted
        value is a float.

    Raises
    ------
    ValueError
        If there is no rule, a parameter is not in the vocabulary, a unit
        differs where it cannot (a derived value keeps the unit of its
        inputs; ``count``, ``threshold_count`` and ``strictest`` give a
        value without unit), an input does not convert into the unit of its
        parameter, a label is not in the order, ``known_only`` is given for
        an additive rule (``sum``, ``mean``, ``threshold_count``), a value
        is assumed for a parameter no rule reads, an unknown input has no
        assumed value under ``assume``, the sheets of a member are
        inconsistent (see :class:`Member`), or a sum meets ``+inf`` and
        ``-inf``.
    TypeError
        If a rule reads text where it needs a number, or an argument is not
        of its type.
    ImportError
        If an input is in another unit than its parameter and pint is not
        installed (the optional extra ``units``).

    Examples
    --------
    >>> def member(id, width):
    ...     source = Source(f"Sheet {id}", locator="p. 4")
    ...     sheet = ValueSet(f"sheet-{id}", "1", {"width": Value(
    ...         width, source, Origin.STATEMENT, unit="m")})
    ...     return Member(id, (sheet,))
    >>> group = Group("G", ((member("A", 2.5), 2), (member("B", 3.5), 1)))
    >>> derived = aggregate(
    ...     group,
    ...     {"width": Aggregation.max("width")},
    ...     parameters=[Parameter("width", unit="m")],
    ...     unknown=OnUnknown.propagate(),
    ...     edition="1",
    ... )
    >>> derived["width"].value, derived["width"].derivation.fixed_by
    (3.5, ('B',))
    """
    if not isinstance(group, Group):
        raise TypeError(f"group must be a Group, got {group!r}")
    if not isinstance(unknown, OnUnknown):
        raise TypeError(f"unknown must be an OnUnknown policy, got {unknown!r}")
    _name("edition", edition)
    table = dict(rules)
    if not table:
        raise ValueError("no rule: give at least one output parameter")
    vocabulary = _vocabulary(parameters)
    ordered = sorted(table.items())
    for output, rule in ordered:
        if not isinstance(rule, Aggregation):
            raise TypeError(f"rules[{output!r}] must be an Aggregation, got {rule!r}")
        _check_rule(output, rule, vocabulary)
    if unknown.rule is UnknownRule.KNOWN_ONLY:
        for _, rule in ordered:
            if rule.kind in _ADDITIVE:
                raise ValueError(
                    f"known_only would shorten an additive value ({rule.kind} of "
                    f"{rule.of!r}): use propagate or assume"
                )
    _check_policy(unknown, (r.of for r in table.values() if r.of), vocabulary)
    leaves = group.flatten()
    sheets = {m.id: _member_values(m, vocabulary) for m, _ in leaves}
    context = _Context(group, leaves, sheets, vocabulary, unknown, edition, precedence)
    values: dict[str, Value] = {}
    tallies: dict[str, dict[str, Tally]] = {"unknown": {}, "assumed": {}, "left": {}}
    for output, rule in ordered:
        values[output], (counted, assumed, left) = context.derive(output, rule)
        tallies["unknown"][output] = counted
        tallies["assumed"][output] = assumed
        tallies["left"][output] = left
    return Derived(
        ValueSet(group.id, edition, values),
        unknown=tallies["unknown"],
        assumed=tallies["assumed"],
        left_out=tallies["left"],
    )


def _check_rule(output: str, rule: Aggregation, vocabulary: _Vocabulary) -> None:
    out = vocabulary.parameter(output)
    if rule.kind in _COUNTS and out.unit is not None:
        raise ValueError(
            f"{rule.kind} gives a number of members: {output!r} must have no unit, "
            f"got {out.unit!r}"
        )
    if rule.of is None:
        return
    of = vocabulary.parameter(rule.of)
    if rule.kind is AggregateKind.STRICTEST:
        if out.unit is not None:
            raise ValueError(
                f"strictest gives a label of its order: {output!r} must have no "
                f"unit, got {out.unit!r}"
            )
    elif rule.kind is AggregateKind.THRESHOLD_COUNT:
        assert rule.threshold is not None
        _given(rule.threshold, of, _threshold_of(rule))
    elif out.unit != of.unit:
        raise ValueError(
            f"{rule.kind} of {rule.of!r} ({of.unit}) into {output!r} "
            f"({out.unit}): a derived value keeps the unit of its inputs"
        )


def _threshold_of(rule: Aggregation) -> str:
    """The threshold of a rule, for a message."""
    return f"the threshold of {rule.of!r}"


def _settings(rule: Aggregation, policy: OnUnknown) -> dict[str, object]:
    settings: dict[str, object] = {"unknown": policy.rule.value}
    if rule.of is not None:
        settings["of"] = rule.of
    if rule.order:
        settings["order"] = rule.order
    if rule.comparison is not None:
        settings["comparison"] = rule.comparison.value
    if policy.justification is not None:
        settings["justification"] = policy.justification
    return settings


def _tally(records: Iterable[LeftOut]) -> Tally:
    found = tuple(records)
    return Tally(tuple(x.name for x in found), sum(x.instances for x in found))


type _Tallies = tuple[Tally, Tally, Tally]


@dataclass(frozen=True, slots=True)
class _Context:
    """What every rule of a call shares."""

    group: Group
    leaves: tuple[tuple[Member, int], ...]
    sheets: Mapping[str, Mapping[str, Value]]
    vocabulary: _Vocabulary
    policy: OnUnknown
    edition: str
    precedence: int

    def value(
        self, output: str, x: Datum | None, trace: Derivation, na: str | None = None
    ) -> Value:
        """The derived value of ``output``."""
        group = self.group.id
        return Value(
            x,
            Source(f"aggregate of {group}", rulebook=group, edition=self.edition),
            Origin.DERIVED,
            unit=self.vocabulary.parameter(output).unit,
            precedence=self.precedence,
            not_applicable=na,
            derivation=trace,
        )

    def derive(self, output: str, rule: Aggregation) -> tuple[Value, _Tallies]:
        """The value of ``output``, with its tallies: unknown, assumed and
        left out."""
        settings = _settings(rule, self.policy)
        tree = tree_left_out(self.group)
        if rule.of is None:  # count: the members, by their counts
            inputs = tuple(
                DerivationInput("count", output, m.id, ValueState.KNOWN, None, c)
                for m, c in self.leaves
            )
            trace = Derivation(
                "aggregate",
                rule.kind.value,
                settings,
                tuple(m.id for m, _ in self.leaves),
                inputs,
                left_out=tree,
            )
            total = sum(c for _, c in self.leaves)
            return self.value(output, total, trace), (Tally(), Tally(), _tally(tree))
        of = self.vocabulary.parameter(rule.of)
        readings = [_read(m.id, c, self.sheets[m.id], of) for m, c in self.leaves]
        part = _partition(readings, of, self.policy)
        _check_types(rule, part.used, of.name)
        limit: Exact | None = None
        if rule.threshold is not None:
            threshold = DerivationInput(
                "threshold", of.name, None, ValueState.KNOWN, rule.threshold
            )
            limit, records = _given(rule.threshold, of, _threshold_of(rule))
            part = replace(
                part,
                inputs=(*part.inputs, threshold),
                conversions=part.conversions + records,
            )
        left_out = part.left_out + tree
        counted = part.unknown_tally
        tallies = (counted, counted if part.assumptions else Tally(), _tally(left_out))

        def traced(
            fixed_by: Iterable[str] = (),
            bound: tuple[Datum, tuple[str, ...]] | None = None,
        ) -> Derivation:
            return Derivation(
                "aggregate",
                rule.kind.value,
                settings,
                tuple(fixed_by),
                part.inputs,
                assumptions=part.assumptions,
                left_out=left_out,
                conversions=part.conversions,
                unknown=counted.names,
                bound=None if bound is None else bound[0],
                bound_fixed_by=() if bound is None else bound[1],
            )

        if not part.used and not part.unknown:
            holders = [r.holder for r in part.not_applicable]
            reasons = ", ".join(
                f"{r.holder} ({_reason(r)})" for r in part.not_applicable
            )
            na = f"not applicable to any member of {self.group.id!r}: {reasons}"
            return self.value(output, None, traced(holders), na), tallies
        result = _compute(rule, part.used, of.name, limit)
        if part.pending:
            # DD9: only the last label of an order decides despite unknowns.
            decided = (
                rule.kind is AggregateKind.STRICTEST
                and result is not None
                and result[0] == rule.order[-1]
            )
            if not decided:
                bound = result if rule.kind in _ENVELOPES else None
                return self.value(output, None, traced(bound=bound)), tallies
        if result is None:  # known_only, and no known input
            return self.value(output, None, traced()), tallies
        x, fixers = result
        return self.value(output, x, traced(fixers)), tallies


def _check_types(rule: Aggregation, used: Sequence[_Reading], parameter: str) -> None:
    """Numbers for a numeric rule, labels of the order for ``strictest``.

    Raises
    ------
    ValueError
        If a label is not in the order.
    TypeError
        If a numeric rule reads text.
    """
    for r in used:
        assert r.value is not None
        x = r.value.value
        if rule.kind is AggregateKind.STRICTEST:
            if x not in rule.order:
                raise ValueError(
                    f"{_label(r, parameter)} is {x!r}, not one of the order "
                    f"{list(rule.order)}"
                )
        elif isinstance(x, str):
            raise TypeError(
                f"{_label(r, parameter)} must be a number for {rule.kind}, got {x!r}"
            )


def _datum(r: _Reading) -> Datum:
    assert r.value is not None
    assert r.value.value is not None
    return r.value.value


def _number(r: _Reading) -> int | float:
    x = _datum(r)
    assert not isinstance(x, str)
    return x


def _compute(
    rule: Aggregation,
    used: Sequence[_Reading],
    parameter: str,
    threshold: Exact | None = None,
) -> tuple[Datum, tuple[str, ...]] | None:
    """The value of the rule on the inputs used, and the holders that fix
    it; ``None`` without input. Every input and the threshold are in the
    unit of the parameter, exactly."""
    if not used:
        return None
    kind = rule.kind
    everyone = tuple(r.holder for r in used)
    if kind is AggregateKind.STRICTEST:
        ranks = [rule.order.index(str(_datum(r))) for r in used]
        top = max(ranks)
        return rule.order[top], tuple(
            r.holder for r, rank in zip(used, ranks, strict=True) if rank == top
        )
    exact = [r.exact for r in used]
    if kind in (AggregateKind.MAX, AggregateKind.MIN):
        extreme = max(exact) if kind is AggregateKind.MAX else min(exact)
        fixers = [r for r, x in zip(used, exact, strict=True) if x == extreme]
        return _number(fixers[0]), tuple(r.holder for r in fixers)
    if kind is AggregateKind.THRESHOLD_COUNT:
        assert threshold is not None
        assert rule.comparison is not None
        counted = [
            r
            for r, x in zip(used, exact, strict=True)
            if _crosses(rule.comparison, x, threshold)
        ]
        return sum(r.instances for r in counted), tuple(r.holder for r in counted)
    weighted = zip((r.instances for r in used), exact, strict=True)
    total = _weighted_sum(weighted, f"{kind} of {parameter!r}")
    if isinstance(total, float):  # an infinity
        return total, everyone
    if kind is AggregateKind.SUM:
        if all(isinstance(_number(r), int) for r in used):
            return int(total), everyone
        return float(total), everyone
    return float(total / sum(r.instances for r in used)), everyone
