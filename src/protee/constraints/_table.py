# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The requirement table, generated from a verification."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from protee.constraints._compose import ComputationView, UnknownPolicy
from protee.constraints._failure import Impact
from protee.constraints._model import RequirementSet, ResolvedValues, Source, Value
from protee.constraints._patterns import PATTERNS, Family
from protee.constraints._verify import RequirementStatus, Verification

__all__ = ["RequirementRow", "requirement_table"]


@dataclass(frozen=True, slots=True)
class RequirementRow:
    """One row of the requirement table.

    Every field is generated from the requirements, the values and the
    verification: no list of active constraints is kept by hand.

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
        Elements without data.
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

    def to_dict(self, *, readable: bool = False) -> dict[str, Any]:
        """The row as plain data, ready for JSON (``inf`` as ``"inf"``, and
        ``-inf`` as ``"-inf"``).

        Parameters
        ----------
        readable : bool
            Whether each value, retained or discarded, also gets
            ``"shown"``, the value as a person reads it (see
            :func:`readable`), which needs the optional extra ``units``. By
            default, the data do not depend on the extras installed.

        Raises
        ------
        ImportError
            If ``readable`` is true and pint is not installed (the
            optional extra ``units``).
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


def _value(v: Value, *, readable: bool = False) -> dict[str, Any]:
    x = v.value
    if isinstance(x, float) and math.isinf(x):
        x = "inf" if x > 0 else "-inf"
    data: dict[str, Any] = {
        "value": x,
        "unit": v.unit,
        "origin": str(v.origin),
        "precedence": v.precedence,
        "justification": v.justification,
        "source": _source(v.source),
    }
    if readable:
        # Imported on use: the display is an option of the table.
        from protee.constraints._units import readable as shown

        data["shown"] = shown(v)
    return data


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
                values=MappingProxyType(applied),
                discarded=MappingProxyType(
                    {n: values.discarded[n] for n in names if n in values.discarded}
                ),
                status=check.status,
                reason=check.reason,
                verification=MappingProxyType(
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
                else MappingProxyType(impacts[r.id].to_dict()),
            )
        )
    return tuple(rows)
