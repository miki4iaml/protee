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
        The best status a result can reach: ``applied``, ``partial``,
        ``no_data`` or ``not_applicable``.
    reason : str
    missing_values : tuple of str
        Parameters to be set or without a value.
    missing_attributes : tuple of str
        Attributes absent from the data.
    known, total : int
        Arcs in scope whose data is known, and arcs in scope.
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
        object.__setattr__(
            self, "_by_id", MappingProxyType({c.requirement: c for c in self.checks})
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
    """
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
    if pattern.effect_kind is not EffectKind.VERDICT:
        return replace(
            base,
            expected=RequirementStatus.APPLIED,
            reason=f"{total} arcs in the scope, no data needed",
            known=total,
            total=total,
        )
    effect = evaluate(requirement, graph, data, values)
    assert effect.reasons is not None
    known_mask = scope & (effect.reasons != Reason.MISSING_DATA)
    known = int(known_mask.sum())
    totals = Counter(e for e, s in zip(elements, scope, strict=True) if s)
    knowns = Counter(e for e, k in zip(elements, known_mask, strict=True) if k)
    coverage = MappingProxyType(
        {
            e: (knowns[e], totals[e])
            for e in sorted(totals, key=lambda e: (e is None, e or ""))
        }
    )
    provable = None
    if known:
        provable = bool(np.any(known_mask & (effect.reasons == Reason.SATISFIED)))
    if known == 0:
        expected, reason = (
            RequirementStatus.NO_DATA,
            f"no data on the {total} arcs in scope",
        )
    elif known < total:
        expected = RequirementStatus.PARTIAL
        reason = f"data on {known} of the {total} arcs in scope"
    else:
        expected, reason = (
            RequirementStatus.APPLIED,
            f"data on the {total} arcs in scope",
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
