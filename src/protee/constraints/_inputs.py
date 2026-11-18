# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""What the inputs allow to prove, before any solving."""

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

import numpy as np

from protee.constraints._data import ArcData
from protee.constraints._effects import Reason, evaluate
from protee.constraints._model import Requirement, RequirementSet, ResolvedValues
from protee.constraints._patterns import PATTERNS, EffectKind
from protee.constraints._verify import RequirementStatus
from protee.graph import Digraph

__all__ = ["InputCheck", "InputReport", "check_inputs"]


@dataclass(frozen=True, slots=True)
class InputCheck:
    """What the inputs allow to prove for one requirement.

    Attributes
    ----------
    requirement : str
    expected : RequirementStatus
        The best status a result that uses an arc in scope can reach:
        ``applied`` when a known arc can satisfy the requirement,
        ``partial`` when only arcs without data can, ``not_applied`` when
        no arc can (every known value fails), ``no_data`` when an
        attribute is absent, ``not_applicable`` when a value is to be set
        or no arc is in scope.
    reason : str
    missing_values : tuple of str
        Parameters to be set or without a value.
    missing_attributes : tuple of str
        Attributes absent from the data.
    known, total : int
        Arcs in scope whose data is known, and arcs in scope. The data of
        an arc of unknown element are unknown for flow bounds with a
        minimum, which is not imposed there.
    coverage : mapping of str or None to (int, int)
        ``(known, total)`` by element type, ``None`` for an unknown element.
    provable : bool or None
        Whether at least one known arc in scope passes; ``False`` means
        the requirement can be proved on no arc (every known limit is below
        the threshold). ``None`` when it does not apply.
    derived : mapping of str to str or None
        The derived attributes used, with their quality.
    """

    requirement: str
    expected: RequirementStatus
    reason: str
    missing_values: tuple[str, ...] = ()
    missing_attributes: tuple[str, ...] = ()
    known: int = 0
    total: int = 0
    coverage: Mapping[str | None, tuple[int, int]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    provable: bool | None = None
    derived: Mapping[str, str | None] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class InputReport:
    """One :class:`InputCheck` per requirement, in the order of the set."""

    checks: tuple[InputCheck, ...]
    _by_id: Mapping[str, InputCheck] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        checks = tuple(self.checks)
        object.__setattr__(self, "checks", checks)
        object.__setattr__(
            self, "_by_id", MappingProxyType({c.requirement: c for c in checks})
        )

    def __iter__(self) -> Iterator[InputCheck]:
        return iter(self.checks)

    def __len__(self) -> int:
        return len(self.checks)

    def __getitem__(self, requirement: str) -> InputCheck:
        """The check of the requirement of identifier ``requirement``."""
        return self._by_id[requirement]


def check_inputs(
    requirements: RequirementSet,
    graph: Digraph,
    data: ArcData,
    values: ResolvedValues,
) -> InputReport:
    """Say in advance what each requirement can be proved on.

    For each requirement: the values to be set, the attributes absent from
    the data, the coverage of the data by element type, whether any known
    arc can pass, the derived attributes used, and the best status a
    result can reach.

    Parameters
    ----------
    requirements : RequirementSet
    graph : Digraph
    data : ArcData
    values : ResolvedValues

    Returns
    -------
    InputReport

    Raises
    ------
    ValueError
        If ``data`` does not match ``graph``, or a requirement does not fit
        the data (see :func:`evaluate`).
    TypeError
        If a value does not fit its pattern (see :func:`evaluate`).
    """
    if data.m != graph.m:
        raise ValueError(f"data for {data.m} arcs, graph of {graph.m} arcs")
    elements = data.element_labels()
    return InputReport(
        tuple(_check(r, graph, data, values, elements) for r in requirements)
    )


def _check(
    requirement: Requirement,
    graph: Digraph,
    data: ArcData,
    values: ResolvedValues,
    elements: tuple[str | None, ...],
) -> InputCheck:
    rid = requirement.id
    pattern = PATTERNS[requirement.pattern]
    missing_values = tuple(
        name
        for name in requirement.parameters.values()
        if (v := values.get(name)) is None or v.to_be_set
    )
    missing_attributes = tuple(
        n for n in requirement.attributes.values() if n not in data
    )
    derived = MappingProxyType(
        {
            n: data[n].quality
            for n in requirement.attributes.values()
            if n in data and data[n].derived
        }
    )
    base = InputCheck(
        rid,
        RequirementStatus.NOT_APPLICABLE,
        "",
        missing_values=missing_values,
        missing_attributes=missing_attributes,
        derived=derived,
    )
    if missing_values:
        return replace(base, reason=f"value of {missing_values[0]!r} to be set")
    scope = data.in_scope(requirement.scope)
    total = int(scope.sum())
    if missing_attributes:
        return replace(
            base,
            expected=RequirementStatus.NO_DATA,
            reason=f"attribute {missing_attributes[0]!r} absent from the data",
            total=total,
        )
    if total == 0:
        return replace(base, reason="no arc in the scope")
    effect = evaluate(requirement, graph, data, values)
    kind = pattern.effect_kind
    if kind is EffectKind.OBJECTIVE:
        return replace(
            base,
            expected=RequirementStatus.APPLIED,
            reason="checked on the weights or costs of the result",
        )
    if kind is EffectKind.VERDICT:
        assert effect.reasons is not None
        known_mask = scope & (effect.reasons != Reason.MISSING_DATA)
        passing = known_mask & (effect.reasons == Reason.SATISFIED)
    elif kind is EffectKind.COST_TERM:
        # A speed cap is verified on the length of an arc.
        known_mask = scope & data[requirement.attributes["length"]].known
        passing = known_mask
    else:
        # Flow bounds: the minimum is not imposed on an arc of unknown
        # element, whose data are then unknown.
        doubt = data.scope_unknown(requirement.scope)
        if _minimum(requirement, values) == 0:
            doubt = np.zeros_like(doubt)
        known_mask = scope & ~doubt
        passing = known_mask
    known = int(known_mask.sum())
    totals = Counter(e for e, s in zip(elements, scope, strict=True) if s)
    knowns = Counter(e for e, k in zip(elements, known_mask, strict=True) if k)
    coverage = MappingProxyType(
        {
            e: (knowns[e], totals[e])
            for e in sorted(totals, key=lambda e: (e is None, e or ""))
        }
    )
    provable = None if known == 0 else bool(passing.any())
    if provable:
        expected = RequirementStatus.APPLIED
    elif known < total:
        expected = RequirementStatus.PARTIAL
    else:
        expected = RequirementStatus.NOT_APPLIED
    reason = (
        f"no data on the {total} arcs in scope"
        if known == 0
        else f"data on {known} of the {total} arcs in scope"
    )
    if provable is False:
        reason += "; no known arc passes: the requirement cannot be proved on any arc"
    return replace(
        base,
        expected=expected,
        reason=reason,
        known=known,
        total=total,
        coverage=coverage,
        provable=provable,
    )


def _minimum(requirement: Requirement, values: ResolvedValues) -> float:
    name = requirement.parameters.get("minimum")
    value = None if name is None else values.get(name)
    if value is None or not isinstance(value.value, (int, float)):
        return 0.0
    return float(value.value)
