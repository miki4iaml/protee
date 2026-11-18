# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Evaluation of a requirement into an immutable effect on the arcs."""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
from typing import Any

import numpy as np
import numpy.typing as npt

from protee.constraints._data import UNKNOWN_CODE, ArcData
from protee.constraints._model import Datum, Requirement, ResolvedValues
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
    """Why an arc received its verdict."""

    SATISFIED = 0
    VIOLATED = 1
    MISSING_DATA = 2
    OUT_OF_SCOPE = 3


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


type _Evaluator = Callable[
    [Requirement, ArcData, dict[str, Datum], npt.NDArray[np.bool_]], Effect
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
        value is to be set or missing, an effect that does not apply, with
        the reason.

    Raises
    ------
    ValueError
        If ``data`` does not match ``graph``, a scope label is not an
        element of the data, or a value or an attribute does not fit the
        pattern.
    TypeError
        If a value is text where the pattern needs a number, or a number
        where it needs a name.
    """
    if data.m != graph.m:
        raise ValueError(f"data for {data.m} arcs, graph of {graph.m} arcs")
    pattern = PATTERNS[requirement.pattern]
    bound: dict[str, Datum] = {}
    for role in (*pattern.parameters, *pattern.optional):
        name = requirement.parameters.get(role)
        if name is None:
            continue
        value = values.get(name)
        if value is None or value.value is None:
            return Effect(
                requirement.id,
                pattern.effect_kind,
                graph.m,
                not_applicable=f"value of {name!r} to be set",
            )
        bound[role] = value.value
    scope = data.in_scope(requirement.scope)
    return _EVALUATORS[pattern.name](requirement, data, bound, scope)


def _number(requirement: Requirement, role: str, value: Datum) -> float:
    if isinstance(value, str):
        raise TypeError(f"requirement {requirement.id}: {role} must be a number")
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


def _threshold(
    requirement: Requirement,
    data: ArcData,
    bound: dict[str, Datum],
    scope: npt.NDArray[np.bool_],
) -> Effect:
    quantity = _number(requirement, "quantity", bound["quantity"])
    limit = _column(requirement, data, "limit", categorical=False)
    if limit is None:
        return _missing(requirement, data, scope)
    known = ~np.isnan(limit)
    return _verdicts(requirement, data, scope, known, known & (quantity <= limit))


def _class(
    requirement: Requirement,
    data: ArcData,
    bound: dict[str, Datum],
    scope: npt.NDArray[np.bool_],
) -> Effect:
    codes = _column(requirement, data, "class", categorical=True)
    if codes is None:
        return _missing(requirement, data, scope)
    labels = data[requirement.attributes["class"]].labels
    assert labels is not None
    required = bound["required_class"]
    if required not in labels:
        raise ValueError(
            f"requirement {requirement.id}: class {required!r} is not one of {list(labels)}"
        )
    rank = labels.index(str(required))
    known = codes != UNKNOWN_CODE
    return _verdicts(requirement, data, scope, known, known & (codes >= rank))


def _zone(
    requirement: Requirement,
    data: ArcData,
    _bound: dict[str, Datum],
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
    bound: dict[str, Datum],
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
    bound: dict[str, Datum],
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
    bound: dict[str, Datum],
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
        "zone_exclusion": _zone,
        "speed_cap": _speed_cap,
        "occurrence_bounds": _occurrences,
        "objective": _objective,
    }
)
