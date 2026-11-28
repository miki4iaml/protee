# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The requirement table, generated from a verification."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Any

from protee._frozen import FrozenMap
from protee.constraints._compose import ComputationView, UnknownPolicy
from protee.constraints._derivations import ENVELOPES
from protee.constraints._failure import Impact
from protee.constraints._model import (
    Conversion,
    Datum,
    Derivation,
    DerivationInput,
    LeftOut,
    LeftOutCause,
    RequirementSet,
    ResolvedValues,
    Source,
    Value,
    ValueState,
    _bound_side,
    _datum_text,
)
from protee.constraints._patterns import PATTERNS, Family
from protee.constraints._verify import RequirementStatus, Verification

__all__ = ["RequirementRow", "requirement_table"]


@dataclass(frozen=True, slots=True)
class RequirementRow:
    """One row of the requirement table.

    Every field is generated from the requirements, the values and the
    verification: no list of active constraints is kept by hand. Its
    tables are frozen mappings: a row pickles and copies.

    Attributes
    ----------
    id : str
    family : Family
    statement : mapping of str to str
    source : Source
    values : mapping of str to Value
        The values applied, by parameter.
    discarded : mapping of str to tuple of Value
        The values set aside by precedence.
    status : RequirementStatus
    reason : str
    verification : mapping of str to int
        Number of elements that ``passed``, ``failed`` or are ``unknown``.
    unknowns : int
        Elements whose verdict is unknown: without data, or undecided by
        the bound of a value to be set.
    policy : UnknownPolicy or None
        The policy for the unknown of the view the result was computed with.
    impact : mapping of str to float, bool or None, optional
        What the requirement changes to the result (see :class:`Impact`).
    """

    id: str
    family: Family
    statement: Mapping[str, str]
    source: Source
    values: Mapping[str, Value]
    discarded: Mapping[str, tuple[Value, ...]]
    status: RequirementStatus
    reason: str
    verification: Mapping[str, int]
    unknowns: int
    policy: UnknownPolicy | None = None
    impact: Mapping[str, float | bool | None] | None = field(default=None)

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "statement", FrozenMap(self.statement))
        set_(self, "values", FrozenMap(self.values))
        set_(
            self,
            "discarded",
            FrozenMap({k: tuple(v) for k, v in self.discarded.items()}),
        )
        set_(self, "verification", FrozenMap(self.verification))
        if self.impact is not None:
            set_(self, "impact", FrozenMap(self.impact))

    def to_dict(self, *, readable: bool = False) -> dict[str, Any]:
        """The row as plain data, ready for JSON (``inf`` as ``"inf"``, and
        ``-inf`` as ``"-inf"``).

        Each value, retained or discarded, gives its number or label, its
        unit, origin, precedence, justification, the reason it is not
        applicable (``"not_applicable"``, or ``None``), its source, and its
        ``"derivation"``: ``None``, or for a derived value its name, rule,
        settings, the inputs that fix it (``"fixed_by"``), a ``"summary"``
        in words (the rule; the value and the members, characteristics or
        class that fix it, with their sources; for a value to be set, the
        bound of its known inputs and the inputs without a value; a
        decision despite unknown inputs; the assumptions; the inputs left
        out with their reasons; the conversions), every input with its
        state and its value (each with its own derivation: a chain such as
        a selection by a class, the classification and the envelope it
        reads, is shown whole), the assumptions, the inputs left out, the
        conversions, the inputs without a value (``"unknown"``), and the
        bound of a value to be set with the inputs that fix it
        (``"bound"``, ``"bound_fixed_by"``).

        Parameters
        ----------
        readable : bool
            Whether each value, retained, discarded or read by a
            derivation, also gets ``"shown"``, the value as a person reads
            it (see :func:`readable`), which needs the optional extra
            ``units`` for a number with a unit. By default, the data do
            not depend on the extras installed.

        Raises
        ------
        ImportError
            If ``readable`` is true, a value is a number with a unit, and
            pint is not installed (the optional extra ``units``).
        """
        return {
            "id": self.id,
            "family": str(self.family),
            "statement": dict(self.statement),
            "source": _source(self.source),
            "values": [
                {
                    "parameter": name,
                    **_value(v, readable=readable),
                    "discarded": [
                        _value(d, readable=readable)
                        for d in self.discarded.get(name, ())
                    ],
                }
                for name, v in self.values.items()
            ],
            "status": str(self.status),
            "reason": self.reason,
            "verification": dict(self.verification),
            "impact": None if self.impact is None else dict(self.impact),
            "unknowns": {
                "count": self.unknowns,
                "policy": None if self.policy is None else str(self.policy),
            },
        }


def _source(s: Source) -> dict[str, Any]:
    return {
        "document": s.document,
        "rulebook": s.rulebook,
        "edition": s.edition,
        "locator": s.locator,
        "link": s.link,
        "citation_checked": s.citation_checked,
    }


def _number(x: object) -> object:
    """``x``, an infinity written ``"inf"`` or ``"-inf"`` for JSON."""
    if isinstance(x, float) and math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return x


def _plain(x: object) -> object:
    """Settings as plain data: mappings, lists, sorted sets, numbers."""
    if isinstance(x, Mapping):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, AbstractSet):
        return sorted((_plain(v) for v in x), key=repr)
    return _number(x)


def _value(v: Value, *, readable: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "value": _number(v.value),
        "unit": v.unit,
        "origin": str(v.origin),
        "precedence": v.precedence,
        "justification": v.justification,
        "not_applicable": v.not_applicable,
        "source": _source(v.source),
        "derivation": _derivation(v, readable=readable),
    }
    if readable:
        # Imported on use: the display is an option of the table.
        from protee.constraints._units import readable as shown

        data["shown"] = shown(v)
    return data


def _derivation(v: Value, *, readable: bool) -> dict[str, Any] | None:
    d = v.derivation
    if d is None:
        return None

    def given(x: Value | None) -> dict[str, Any] | None:
        return None if x is None else _value(x, readable=readable)

    return {
        "name": d.name,
        "rule": d.rule,
        "settings": _plain(d.settings),
        "fixed_by": list(d.fixed_by),
        "summary": _summary(v),
        "inputs": [
            {
                "role": i.role,
                "parameter": i.parameter,
                "holder": i.holder,
                "state": str(i.state),
                "instances": i.instances,
                "value": given(i.value),
            }
            for i in d.inputs
        ],
        "assumptions": [
            {
                "parameter": a.parameter,
                "value": given(a.value),
                "holders": list(a.holders),
                "instances": a.instances,
            }
            for a in d.assumptions
        ],
        "left_out": [
            {
                "name": x.name,
                "cause": str(x.cause),
                "reason": x.reason,
                "instances": x.instances,
            }
            for x in d.left_out
        ],
        "conversions": [
            {
                "holder": c.holder,
                "parameter": c.parameter,
                "value": _number(c.value),
                "unit": c.unit,
                "converted": _number(c.converted),
                "to_unit": c.to_unit,
                "factor": c.factor,
            }
            for c in d.conversions
        ],
        "unknown": list(d.unknown),
        "bound": _number(d.bound),
        "bound_fixed_by": list(d.bound_fixed_by),
    }


# The summary of a derived value ---------------------------------------------


def _summary(value: Value) -> str:
    """The derivation of a value in words, generated from its trace.

    The rule, the value and the inputs that fix it, each with its source;
    for a value to be set, the bound of its known inputs and the inputs
    without a value; then a decision despite unknown inputs, the
    assumptions, the inputs left out with their reasons, and the
    conversions. For instance ``"max of 'width' over G: 3.5 m, fixed by B
    (Sheet B (2), p. 4)"``.
    """
    d = value.derivation
    assert d is not None
    subject = value.source.rulebook or value.source.document
    parts = [f"{_head(d, subject)}: {_outcome(value, d)}"]
    decided = d.settings.get("unknown") == "propagate"
    if value.state is ValueState.KNOWN and d.unknown and decided:
        # A fixer without a value of its own decides by its bound.
        by = (f"the bound of {n}" if n in d.unknown else n for n in d.fixed_by)
        parts.append(
            f"decided by {', '.join(by)} despite unknown values for "
            f"{', '.join(d.unknown)}"
        )
    parts += [
        f"assumed for {', '.join(a.holders)}: {_shown(a.value)} "
        f"({a.value.justification})"
        for a in d.assumptions
    ]
    if d.left_out:
        parts.append("left out: " + ", ".join(_left_out(x) for x in d.left_out))
    if d.conversions:
        parts.append("converted: " + ", ".join(_converted(c) for c in d.conversions))
    return "; ".join(parts)


def _shown(v: Value) -> str:
    """A known value with its unit."""
    assert v.value is not None
    return _datum_text(v.value, v.unit)


def _cited(s: Source) -> str:
    """A source: its document, its edition, its locator."""
    text = s.document if s.edition is None else f"{s.document} ({s.edition})"
    return text if s.locator is None else f"{text}, {s.locator}"


def _head(d: Derivation, subject: str) -> str:
    """The rule and what it reads."""
    of = d.settings.get("of")
    if d.name == "aggregate":
        if d.rule == "count":
            return f"count of the members of {subject}"
        head = f"{d.rule} of {of!r} over {subject}"
        limit = _input(d, "threshold", None)
        if limit is not None and limit.value is not None:
            comparison = str(d.settings.get("comparison")).replace("_", " ")
            head += f", {comparison} {_shown(limit.value)}"
        return head
    if d.name == "classify_by_thresholds":
        found = d.settings.get("characteristics")
        names = sorted(found) if isinstance(found, Mapping) else []
        return f"highest rank of {', '.join(names) or 'its characteristics'}"
    if d.name == "select_by_class":
        return f"selected by {d.settings.get('by')!r}"
    return f"{d.name} ({d.rule}) of {subject}"


def _input(
    d: Derivation, role: str, holder: str | None, parameter: str | None = None
) -> DerivationInput | None:
    """The input of ``role`` read on ``holder`` (and of ``parameter``)."""
    for i in d.inputs:
        if (i.role, i.holder) == (role, holder) and parameter in (None, i.parameter):
            return i
    return None


def _outcome(value: Value, d: Derivation) -> str:
    """The value and what fixes it, or why it has none."""
    if value.not_applicable is not None:
        return f"not applicable ({value.not_applicable})"
    if value.value is None:
        missing = ", ".join(d.unknown)
        if d.bound is not None:
            noun = "member" if d.name == "aggregate" else "input"
            n = len(d.unknown)
            side = ENVELOPES.get((d.name, d.rule), "bounded by")
            return (
                f"unknown, {side} {_datum_text(d.bound, value.unit)} (fixed by "
                f"{_fixers(d, d.bound_fixed_by, d.bound)}); {n} "
                f"{noun if n == 1 else noun + 's'} without a value: {missing}"
            )
        of = d.settings.get("of")
        what = f"no value of {of!r}" if isinstance(of, str) else "no value"
        return f"to be set: {what} for {missing}" if missing else "to be set"
    shown = _datum_text(value.value, value.unit)
    if d.name == "select_by_class":
        selected = _selected(d)
        return f"{shown}, {selected}" if selected else shown
    return f"{shown}, fixed by {_fixers(d, d.fixed_by, value.value)}"


def _fixers(d: Derivation, names: Iterable[str], x: Datum) -> str:
    """The inputs that fix a value (or a bound) ``x``: members with the
    source of their value (and its bound, for a value to be set),
    characteristics with the threshold they cross, the groups of a column
    with the source of each value they give."""
    if d.name == "classify_by_thresholds":
        return ", ".join(_ranked(d, name, x) for name in names)
    out = []
    for name in names:
        i = _input(d, "member", name)
        if i is not None and i.value is not None:
            out.append(f"{name} ({_bounded(i.value)}{_cited(i.value.source)})")
        elif d.name == "column_length":
            out.append(_holding(d, name))
        else:
            out.append(name)
    return ", ".join(out)


def _bounded(v: Value) -> str:
    """The bound of a value to be set, before its source."""
    bounded = _bound_side(v)
    if bounded is None:
        return ""
    side, bound = bounded
    return f"{side} {_datum_text(bound, v.unit)}, "


def _holding(d: Derivation, name: str) -> str:
    """A holder of the values of a column that are not lengths of members:
    a group with the gaps, the density and the pace it gives, or a value of
    the context, named by its parameter, each with its source."""
    cited = []
    for i in d.inputs:
        v = i.value
        if i.role == "member" or v is None:
            continue
        if i.holder == name or (i.holder is None and i.parameter == name):
            cited.append(f"{i.parameter!r}: {_cited(v.source)}")
    return f"{name} ({', '.join(cited)})" if cited else name


def _ranked(d: Derivation, name: str, label: Datum) -> str:
    """A characteristic that fixes a class: its value and, beyond the
    first class, the highest threshold it crosses, with its locator."""
    i = _input(d, "characteristic", None, name)
    if i is None or i.value is None:
        return repr(name)
    if i.value.value is None:  # to be set: its bound ranks it
        bounded = _bound_side(i.value)
        if bounded is None:
            return repr(name)
        side, bound = bounded
        shown = f"{name!r} ({side} {_datum_text(bound, i.value.unit)}"
    else:
        shown = f"{name!r} ({_shown(i.value)}"
    # A trace built by classify_by_thresholds holds these settings; one
    # built by hand may not, and its summary says less.
    settings: Any = d.settings
    try:
        row = settings["characteristics"][name]
        rank = settings["classes"].index(label)
        crossed = row["thresholds"][rank - 1] if rank else None
        crossing = str(row["crossing"]).replace("_", " ")
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        crossed = None
    threshold = None if crossed is None else _input(d, "threshold", None, crossed)
    if threshold is None or threshold.value is None or threshold.value.value is None:
        return shown + ")"
    where = threshold.value.source
    cited = where.document if where.locator is None else where.locator
    return f"{shown} {crossing} {_shown(threshold.value)}, {cited})"


def _selected(d: Derivation) -> str:
    """The class that selects a value, and the value chosen with its
    source."""
    label = _input(d, "class", None)
    chosen = _input(d, "chosen", None)
    parts = []
    if label is not None and label.value is not None:
        parts.append(f"for class {label.value.value!r}")
    if chosen is not None and chosen.value is not None:
        parts.append(f"from {chosen.parameter!r} ({_cited(chosen.value.source)})")
    return ", ".join(parts)


def _left_out(x: LeftOut) -> str:
    """A member left out, with its cause and reason."""
    if x.cause is LeftOutCause.ZERO_COUNT:
        return f"{x.name} ({x.reason})"
    return f"{x.name} ({x.cause.value.replace('_', ' ')}: {x.reason})"


def _converted(c: Conversion) -> str:
    """A conversion: who, from what to what, by which factor."""
    who = c.holder if c.holder is not None else repr(c.parameter)
    return (
        f"{who} {_datum_text(c.value, c.unit)} to "
        f"{_datum_text(c.converted, c.to_unit)} (x{c.factor})"
    )


def requirement_table(
    verification: Verification,
    requirements: RequirementSet,
    values: ResolvedValues,
    *,
    view: ComputationView | None = None,
    impacts: Mapping[str, Impact] | None = None,
) -> tuple[RequirementRow, ...]:
    """The rows of the requirement table, one per verified requirement.

    Parameters
    ----------
    verification : Verification
        From :func:`verify_route` or :func:`verify_flow`.
    requirements : RequirementSet
    values : ResolvedValues
    view : ComputationView, optional
        The view the result was computed with, for its policy.
    impacts : mapping of str to Impact, optional
        By requirement identifier, from :meth:`RouteSearch.impact` or
        :meth:`FlowSearch.impact`.

    Returns
    -------
    tuple of RequirementRow
        In the order of the verification.

    Raises
    ------
    ValueError
        If an impact names a requirement the verification does not check.
    """
    checked = {c.requirement for c in verification}
    if impacts is not None and (stray := sorted(set(impacts) - checked)):
        raise ValueError(f"impacts of unchecked requirements {stray}")
    rows = []
    for check in verification:
        r = requirements[check.requirement]
        names = list(r.parameters.values())
        applied = {n: v for n in names if (v := values.get(n)) is not None}
        rows.append(
            RequirementRow(
                id=r.id,
                family=PATTERNS[r.pattern].family,
                statement=r.statement,
                source=r.source,
                values=FrozenMap(applied),
                discarded=FrozenMap(
                    {n: values.discarded[n] for n in names if n in values.discarded}
                ),
                status=check.status,
                reason=check.reason,
                verification=FrozenMap(
                    {
                        "passed": check.passed,
                        "failed": check.failed,
                        "unknown": check.unknown,
                    }
                ),
                unknowns=check.unknown,
                policy=None if view is None else view.policy,
                impact=None
                if impacts is None or r.id not in impacts
                else FrozenMap(impacts[r.id].to_dict()),
            )
        )
    return tuple(rows)
