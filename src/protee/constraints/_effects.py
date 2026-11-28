# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Evaluation of a requirement into an immutable effect on the arcs."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
from typing import Any

import numpy as np
import numpy.typing as npt

from protee.constraints._data import UNKNOWN_CODE, ArcData
from protee.constraints._derivations import ENVELOPES, ORDERS, STRICTER
from protee.constraints._model import (
    Datum,
    Derivation,
    Requirement,
    ResolvedValues,
    Value,
    _datum_text,
    _may_take,
)
from protee.constraints._patterns import PATTERNS, EffectKind
from protee.graph import Digraph

__all__ = ["Effect", "Reason", "Verdict", "evaluate"]


class Verdict(IntEnum):
    """Three-valued verdict of an arc, ordered so that the Kleene
    conjunction of verdicts is their minimum."""

    FAIL = 0
    UNKNOWN = 1
    PASS = 2


class Reason(IntEnum):
    """Why an arc received its verdict.

    - ``SATISFIED``: the arc passes;
    - ``VIOLATED``: the arc fails;
    - ``MISSING_DATA``: the attribute of the arc is unknown, or absent from
      the data;
    - ``OUT_OF_SCOPE``: the requirement does not apply to the arc, which
      passes;
    - ``VALUE_TO_BE_SET``: the value of the subject is to be set, and the
      values its bound allows (see :attr:`Derivation.bound`) do not decide
      the arc: some pass it, some fail it.
    """

    SATISFIED = 0
    VIOLATED = 1
    MISSING_DATA = 2
    OUT_OF_SCOPE = 3
    VALUE_TO_BE_SET = 4


def _array(
    name: str, values: npt.ArrayLike | None, m: int, dtype: type[Any]
) -> npt.NDArray[Any] | None:
    if values is None:
        return None
    out = np.array(values, dtype=dtype, copy=True)
    if out.shape != (m,):
        raise ValueError(f"{name}: expected {m} values, got shape {out.shape}")
    out.flags.writeable = False
    return out


@dataclass(frozen=True, slots=True, eq=False)
class Effect:
    """What a requirement does to the arcs of a graph.

    An effect never modifies the graph: it carries, for each arc, a
    verdict, a cost term or flow bounds, and the identifier of its
    requirement. Effects compose independently of their order (see
    :func:`compose`). All arrays are read-only.

    Attributes
    ----------
    requirement : str
        Identifier of the requirement.
    kind : EffectKind
    m : int
        Number of arcs.
    verdict : numpy.ndarray of int8, optional
        :class:`Verdict` codes (``verdict`` kind).
    reasons : numpy.ndarray of uint8, optional
        :class:`Reason` codes (``verdict`` kind).
    cap : numpy.ndarray of float64, optional
        Speed cap, ``inf`` for none (``cost_term`` kind).
    factor : numpy.ndarray of float64, optional
        Multiplier of the base cost (``cost_term`` kind).
    added : numpy.ndarray of float64, optional
        Amount added to the cost (``cost_term`` kind).
    lower, upper : numpy.ndarray of float64, optional
        Integer flow bounds, ``inf`` for no upper bound (``bound`` kind).
    objective : str, optional
        The criterion to optimize (``objective`` kind).
    not_applicable : str, optional
        Why the requirement has no effect (a value to be set); the arrays
        are then absent.
    """

    requirement: str
    kind: EffectKind
    m: int
    verdict: npt.NDArray[np.int8] | None = None
    reasons: npt.NDArray[np.uint8] | None = None
    cap: npt.NDArray[np.float64] | None = None
    factor: npt.NDArray[np.float64] | None = None
    added: npt.NDArray[np.float64] | None = None
    lower: npt.NDArray[np.float64] | None = None
    upper: npt.NDArray[np.float64] | None = None
    objective: str | None = None
    not_applicable: str | None = None

    def __post_init__(self) -> None:
        m = self.m
        set_ = object.__setattr__
        set_(self, "kind", EffectKind(self.kind))
        set_(self, "verdict", _array("verdict", self.verdict, m, np.int8))
        set_(self, "reasons", _array("reasons", self.reasons, m, np.uint8))
        for name in ("cap", "factor", "added", "lower", "upper"):
            set_(self, name, _array(name, getattr(self, name), m, np.float64))
        arrays = {
            name: getattr(self, name)
            for name in (
                "verdict",
                "reasons",
                "cap",
                "factor",
                "added",
                "lower",
                "upper",
            )
            if getattr(self, name) is not None
        }
        if self.not_applicable is not None:
            if arrays or self.objective is not None:
                raise ValueError("an effect that does not apply carries no array")
            return
        if self.kind is EffectKind.OBJECTIVE:
            if arrays or not self.objective:
                raise ValueError("an objective effect carries its criterion only")
            return
        if self.objective is not None:
            raise ValueError("only an objective effect carries a criterion")
        expected = {
            EffectKind.VERDICT: ({"verdict", "reasons"}, {"verdict", "reasons"}),
            EffectKind.COST_TERM: (set(), {"cap", "factor", "added"}),
            EffectKind.BOUND: ({"lower", "upper"}, {"lower", "upper"}),
        }[self.kind]
        required, allowed = expected
        if not required <= set(arrays) <= allowed or not arrays:
            raise ValueError(
                f"a {self.kind} effect carries {sorted(allowed)}, got {sorted(arrays)}"
            )
        self._check_values()

    def _check_values(self) -> None:
        if self.verdict is not None and not np.isin(self.verdict, list(Verdict)).all():
            raise ValueError("verdict codes must be Verdict values")
        if self.reasons is not None and not np.isin(self.reasons, list(Reason)).all():
            raise ValueError("reason codes must be Reason values")
        if self.cap is not None and not (self.cap >= 0).all():
            raise ValueError("caps must be non-negative (inf for none)")
        if self.factor is not None and not (
            np.isfinite(self.factor).all() and (self.factor >= 0).all()
        ):
            raise ValueError("factors must be finite and non-negative")
        if self.added is not None and not np.isfinite(self.added).all():
            raise ValueError("added amounts must be finite")
        if self.lower is not None and self.upper is not None:
            lo, hi = self.lower, self.upper
            if not (
                np.isfinite(lo).all() and (lo >= 0).all() and (lo == np.floor(lo)).all()
            ):
                raise ValueError("lower bounds must be non-negative integers")
            finite = np.isfinite(hi)
            if not ((hi >= 0).all() and (hi[finite] == np.floor(hi[finite])).all()):
                raise ValueError("upper bounds must be non-negative integers or inf")


@dataclass(frozen=True, slots=True)
class _Undecided:
    """A value to be set by an envelope, and the values it may take.

    Attributes
    ----------
    role : str
        The role the value is bound to.
    candidates : tuple of int, float or str
        For a number, the two ends of the interval the value lies in: the
        bound, and ``inf`` (at least the bound) or ``-inf`` (at most), or
        ``-inf`` and ``inf`` without a bound; for a label, every label of
        its order at least as strict as the bound, every label of the order
        without a bound; empty when the order is not known.
    """

    role: str
    candidates: tuple[Datum, ...]


#: The admissibility patterns whose evaluators read the bound of a value
#: to be set by an envelope.
_BOUNDED = frozenset(
    {"threshold_admissibility", "class_admissibility", "capacity_admissibility"}
)


def envelope_to_be_set(value: Value | None) -> Derivation | None:
    """The derivation of a value to be set by an envelope (``max``,
    ``min``, ``strictest``, a classification by thresholds), ``None`` for
    any other value."""
    if value is None or not value.to_be_set or value.derivation is None:
        return None
    d = value.derivation
    return d if (d.name, d.rule) in ENVELOPES else None


type _Bound = Datum | _Undecided

type _Evaluator = Callable[
    [Requirement, ArcData, dict[str, _Bound], npt.NDArray[np.bool_]], Effect
]


def evaluate(
    requirement: Requirement,
    graph: Digraph,
    data: ArcData,
    values: ResolvedValues,
) -> Effect:
    """Effect of a requirement on the arcs of a graph.

    A pure function: it reads the arc attributes and the values, and never
    modifies the graph. An arc whose attribute is unknown gets the
    ``UNKNOWN`` verdict, never a presumed pass.

    Parameters
    ----------
    requirement : Requirement
    graph : Digraph
    data : ArcData
        Arc attributes of ``graph``.
    values : ResolvedValues
        See :func:`resolve_values`.

    Returns
    -------
    Effect
        Of the kind declared by the pattern of the requirement; when a
        value is to be set, missing or not applicable, an effect that does
        not apply, with the reason (that of a value not applicable, the
        members without a value of a derived value to be set).

        An admissibility requirement (``threshold_admissibility``,
        ``class_admissibility``, ``capacity_admissibility``) whose value
        is to be set by an envelope (``max``, ``min`` or ``strictest`` of
        :func:`aggregate`, :func:`classify_by_thresholds`) reads instead the
        bound of its known inputs (see :attr:`Derivation.bound`), and
        decides an arc only when every value the bound allows decides it
        alike: ``FAIL`` (``VIOLATED``) when every one fails it, ``PASS``
        (``SATISFIED``) when every one passes it (an arc without a limit
        for a quantity at least its bound, an arc that admits the strictest
        label of the order for a class at least as strict as its bound),
        ``UNKNOWN`` (``VALUE_TO_BE_SET``, or ``MISSING_DATA`` without data)
        elsewhere in scope, counted and handled by the policy for the
        unknown. Without a bound (no known input), the value may be any:
        a number any from ``-inf`` to ``inf``, a label any of its order.
        This is the Kleene conjunction of the verdicts of the members: the
        unknown is never presumed compatible.

    Raises
    ------
    ValueError
        If ``data`` does not match ``graph``, a scope label is not an
        element of the data, a value or an attribute does not fit the
        pattern, or the bound of a value to be set is not a label of the
        order of its derivation.
    TypeError
        If a value is text where the pattern needs a number, or a number
        where it needs a name.
    """
    if data.m != graph.m:
        raise ValueError(f"data for {data.m} arcs, graph of {graph.m} arcs")
    pattern = PATTERNS[requirement.pattern]
    reason = unset_reason(requirement, values)
    bound: dict[str, _Bound] = {}
    if reason is not None:
        undecided = _undecided(requirement, values)
        if undecided is None:
            return Effect(
                requirement.id, pattern.effect_kind, graph.m, not_applicable=reason
            )
        bound[undecided.role] = undecided
    else:
        for role, name in _bound_roles(requirement):
            x = values.values[name].value
            assert x is not None
            bound[role] = x
    scope = data.in_scope(requirement.scope)
    return _EVALUATORS[pattern.name](requirement, data, bound, scope)


def _undecided(requirement: Requirement, values: ResolvedValues) -> _Undecided | None:
    """The values a value to be set by an envelope may take, for an
    admissibility requirement; ``None`` for any other requirement or
    value.

    Raises
    ------
    ValueError
        If the bound of a label is not in the order of its derivation.
    """
    if requirement.pattern not in _BOUNDED:
        return None
    ((role, name),) = tuple(_bound_roles(requirement))
    value = values.get(name)
    d = envelope_to_be_set(value)
    if d is None:
        return None
    assert value is not None
    order = d.settings.get(ORDERS.get(d.name, ""))
    labelled = ENVELOPES[d.name, d.rule] == STRICTER and d.bound is not None
    if labelled and not (isinstance(order, tuple) and d.bound in order):
        raise ValueError(
            f"requirement {requirement.id}: the bound {d.bound!r} of {name!r} "
            f"is not a label of the order of its derivation, {order!r}"
        )
    candidates = _may_take(value)
    assert candidates is not None
    return _Undecided(role, candidates)


def undecided_reason(requirement: Requirement, values: ResolvedValues) -> str | None:
    """Why an admissibility requirement is undecided on some arcs: its
    value is to be set by an envelope, with the bound of its known inputs;
    ``None`` for any other requirement or value.

    For instance ``"value of 'width' to be set: no value for U; at least
    3.5 m (B)"``.
    """
    if requirement.pattern not in _BOUNDED:
        return None
    ((_, name),) = tuple(_bound_roles(requirement))
    value = values.get(name)
    d = envelope_to_be_set(value)
    reason = unset_reason(requirement, values)
    if d is None or reason is None:
        return None
    assert value is not None
    if d.bound is None:
        return f"{reason}; no known input bounds it"
    side = ENVELOPES[d.name, d.rule]
    return (
        f"{reason}; {side} {_datum_text(d.bound, value.unit)} "
        f"({', '.join(d.bound_fixed_by)})"
    )


def _bound_roles(requirement: Requirement) -> Iterator[tuple[str, str]]:
    """The value roles bound by a requirement, with their parameter, in the
    order of its pattern."""
    pattern = PATTERNS[requirement.pattern]
    for role in (*pattern.parameters, *pattern.optional):
        name = requirement.parameters.get(role)
        if name is not None:
            yield role, name


def unset_reason(requirement: Requirement, values: ResolvedValues) -> str | None:
    """Why a value the requirement needs has no value, or ``None``.

    The first value without one, in the order of the roles of the pattern:
    missing or to be set (with the members without a value, for a derived
    value), or not applicable (with its reason).
    """
    for _, name in _bound_roles(requirement):
        value = values.get(name)
        if value is None:
            return f"value of {name!r} to be set"
        if value.not_applicable is not None:
            return f"value of {name!r} not applicable: {value.not_applicable}"
        if value.value is None:
            d = value.derivation
            if d is not None and d.unknown:
                return (
                    f"value of {name!r} to be set: no value for {', '.join(d.unknown)}"
                )
            return f"value of {name!r} to be set"
    return None


def _number(requirement: Requirement, role: str, value: _Bound) -> float:
    if isinstance(value, str):
        raise TypeError(f"requirement {requirement.id}: {role} must be a number")
    assert not isinstance(value, _Undecided)
    return float(value)


def _column(
    requirement: Requirement, data: ArcData, role: str, *, categorical: bool
) -> npt.NDArray[Any] | None:
    name = requirement.attributes[role]
    if name not in data:
        return None
    column = data[name]
    if (column.labels is not None) != categorical:
        kind = "a category" if categorical else "a number"
        raise ValueError(f"requirement {requirement.id}: {name} must be {kind}")
    return column.values


def _verdicts(
    requirement: Requirement,
    data: ArcData,
    scope: npt.NDArray[np.bool_],
    known: npt.NDArray[np.bool_],
    passed: npt.NDArray[np.bool_],
) -> Effect:
    verdict = np.where(
        known, np.where(passed, Verdict.PASS, Verdict.FAIL), Verdict.UNKNOWN
    )
    reasons = np.where(
        known, np.where(passed, Reason.SATISFIED, Reason.VIOLATED), Reason.MISSING_DATA
    )
    verdict = np.where(scope, verdict, Verdict.PASS)
    reasons = np.where(scope, reasons, Reason.OUT_OF_SCOPE)
    return Effect(
        requirement.id, EffectKind.VERDICT, data.m, verdict=verdict, reasons=reasons
    )


def _missing(
    requirement: Requirement, data: ArcData, scope: npt.NDArray[np.bool_]
) -> Effect:
    unknown = np.zeros(data.m, dtype=np.bool_)
    return _verdicts(requirement, data, scope, unknown, unknown)


type _Passes = Callable[[Datum], npt.NDArray[np.bool_]]


def _decide(
    requirement: Requirement,
    data: ArcData,
    scope: npt.NDArray[np.bool_],
    known: npt.NDArray[np.bool_],
    value: _Bound,
    passes: _Passes,
) -> Effect:
    """The verdicts of a value, by ``passes`` on the arcs whose data is
    known; for a value to be set by an envelope, ``FAIL`` where every value
    it may take fails, ``PASS`` where every one passes, ``UNKNOWN``
    elsewhere.

    Every admissibility test is monotonic in a number: on an interval,
    failing (or passing) at both ends is failing (or passing) everywhere;
    the labels a value may take are all tried.
    """
    if not isinstance(value, _Undecided):
        return _verdicts(requirement, data, scope, known, known & passes(value))
    failed = known.copy()
    passed = known.copy()
    for x in value.candidates:
        ok = passes(x)
        failed &= ~ok
        passed &= ok
    if not value.candidates:
        failed[:] = False
        passed[:] = False
    verdict = np.where(
        failed, Verdict.FAIL, np.where(passed, Verdict.PASS, Verdict.UNKNOWN)
    )
    reasons = np.where(
        failed,
        Reason.VIOLATED,
        np.where(
            passed,
            Reason.SATISFIED,
            np.where(known, Reason.VALUE_TO_BE_SET, Reason.MISSING_DATA),
        ),
    )
    return Effect(
        requirement.id,
        EffectKind.VERDICT,
        data.m,
        verdict=np.where(scope, verdict, Verdict.PASS),
        reasons=np.where(scope, reasons, Reason.OUT_OF_SCOPE),
    )


def _threshold(
    requirement: Requirement,
    data: ArcData,
    bound: dict[str, _Bound],
    scope: npt.NDArray[np.bool_],
) -> Effect:
    limit = _column(requirement, data, "limit", categorical=False)
    if limit is None:
        return _missing(requirement, data, scope)

    def passes(quantity: Datum) -> npt.NDArray[np.bool_]:
        return _number(requirement, "quantity", quantity) <= limit

    known = ~np.isnan(limit)
    return _decide(requirement, data, scope, known, bound["quantity"], passes)


def _capacity(
    requirement: Requirement,
    data: ArcData,
    bound: dict[str, _Bound],
    scope: npt.NDArray[np.bool_],
) -> Effect:
    demand = _column(requirement, data, "demand", categorical=False)
    if demand is None:
        return _missing(requirement, data, scope)

    def passes(capacity: Datum) -> npt.NDArray[np.bool_]:
        return demand <= _number(requirement, "capacity", capacity)

    known = ~np.isnan(demand)
    return _decide(requirement, data, scope, known, bound["capacity"], passes)


def _class(
    requirement: Requirement,
    data: ArcData,
    bound: dict[str, _Bound],
    scope: npt.NDArray[np.bool_],
) -> Effect:
    codes = _column(requirement, data, "class", categorical=True)
    if codes is None:
        return _missing(requirement, data, scope)
    labels = data[requirement.attributes["class"]].labels
    assert labels is not None

    def passes(required: Datum) -> npt.NDArray[np.bool_]:
        if required not in labels:
            raise ValueError(
                f"requirement {requirement.id}: class {required!r} is not one of "
                f"{list(labels)}"
            )
        return codes >= labels.index(str(required))

    known = codes != UNKNOWN_CODE
    return _decide(requirement, data, scope, known, bound["required_class"], passes)


def _zone(
    requirement: Requirement,
    data: ArcData,
    _bound: dict[str, _Bound],
    scope: npt.NDArray[np.bool_],
) -> Effect:
    inside = _column(requirement, data, "inside", categorical=False)
    if inside is None:
        return _missing(requirement, data, scope)
    known = ~np.isnan(inside)
    if not np.isin(inside[known], (0.0, 1.0)).all():
        raise ValueError(f"requirement {requirement.id}: membership must be 0 or 1")
    return _verdicts(requirement, data, scope, known, known & (inside == 0.0))


def _speed_cap(
    requirement: Requirement,
    data: ArcData,
    bound: dict[str, _Bound],
    scope: npt.NDArray[np.bool_],
) -> Effect:
    maximum = _number(requirement, "maximum", bound["maximum"])
    if not maximum > 0:
        raise ValueError(f"requirement {requirement.id}: a speed cap must be positive")
    for role in ("length", "speed"):
        _column(requirement, data, role, categorical=False)
    cap = np.where(scope, maximum, math.inf)
    return Effect(requirement.id, EffectKind.COST_TERM, data.m, cap=cap)


def _occurrences(
    requirement: Requirement,
    data: ArcData,
    bound: dict[str, _Bound],
    scope: npt.NDArray[np.bool_],
) -> Effect:
    maximum = _number(requirement, "maximum", bound["maximum"])
    minimum = _number(requirement, "minimum", bound.get("minimum", 0))
    for role, v in (("maximum", maximum), ("minimum", minimum)):
        if v < 0 or (math.isfinite(v) and v != math.floor(v)):
            raise ValueError(f"requirement {requirement.id}: {role} must be a count")
    if not math.isfinite(minimum):
        raise ValueError(f"requirement {requirement.id}: minimum must be finite")
    if minimum > maximum:
        raise ValueError(f"requirement {requirement.id}: minimum exceeds maximum")
    # The maximum restricts an arc of unknown element too; the minimum would
    # force flow on a presumption, and is not imposed there.
    imposed = scope & ~data.scope_unknown(requirement.scope)
    lower = np.where(imposed, minimum, 0.0)
    upper = np.where(scope, maximum, math.inf)
    return Effect(requirement.id, EffectKind.BOUND, data.m, lower=lower, upper=upper)


def _objective(
    requirement: Requirement,
    data: ArcData,
    bound: dict[str, _Bound],
    _scope: npt.NDArray[np.bool_],
) -> Effect:
    criterion = bound["criterion"]
    if not isinstance(criterion, str):
        raise TypeError(f"requirement {requirement.id}: the criterion must be a name")
    return Effect(requirement.id, EffectKind.OBJECTIVE, data.m, objective=criterion)


_EVALUATORS: Mapping[str, _Evaluator] = MappingProxyType(
    {
        "threshold_admissibility": _threshold,
        "class_admissibility": _class,
        "capacity_admissibility": _capacity,
        "zone_exclusion": _zone,
        "speed_cap": _speed_cap,
        "occurrence_bounds": _occurrences,
        "objective": _objective,
    }
)
