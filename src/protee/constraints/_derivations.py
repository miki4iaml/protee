# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The closed registry of derivations: from the description of a subject
to its values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

__all__ = ["DERIVATIONS", "DerivationInfo", "derivations"]


@dataclass(frozen=True, slots=True, kw_only=True)
class DerivationInfo:
    """Description of a derivation of the registry.

    A derivation turns the description of a subject (a member, a group of
    members) into values of parameters, each with its trace: the rule, the
    inputs that fix the value and the source of every input.

    Attributes
    ----------
    name : str
        The name of the function, and :attr:`Derivation.name` of every
        value it derives.
    summary : str
    inputs : str
        What the derivation reads.
    output : str
        What it returns.
    rules : tuple of str
        The rules it offers, each named by :attr:`Derivation.rule`.
    cases : tuple of str
        The use cases it serves, in generic sentences.
    reference : str
        A public text, or the property that the tests check.

    Notes
    -----
    The registry is closed until version 1.0: a new derivation comes with
    its use cases, its rules, its reference and its place in the
    conformity suite.
    """

    name: str
    summary: str
    inputs: str
    output: str
    rules: tuple[str, ...]
    cases: tuple[str, ...]
    reference: str


DERIVATIONS: Mapping[str, DerivationInfo] = MappingProxyType(
    {
        d.name: d
        for d in (
            DerivationInfo(
                name="aggregate",
                summary=(
                    "The value of a group from the values of its members, by a "
                    "rule declared for each output parameter: the largest or the "
                    "smallest value, the strictest label of a declared order, a "
                    "sum or a mean weighted by the counts, the number of "
                    "members, or the number of members beyond a threshold."
                ),
                inputs=(
                    "a group of members with their counts, nested groups "
                    "flattened; for each output parameter, a rule and the "
                    "parameter it reads on every member"
                ),
                output=(
                    "a value set named after the group: one derived value per "
                    "output parameter, with the members that fix it, and the "
                    "inputs without a value, assumed or left out, counted"
                ),
                rules=(
                    "max",
                    "min",
                    "strictest",
                    "sum",
                    "count",
                    "mean",
                    "threshold_count",
                ),
                cases=(
                    (
                        "envelope of a group for admissibility: the most limiting "
                        "member fixes each characteristic"
                    ),
                    "pace of a group set by its slowest member",
                    "total number of members of a group",
                    "strictest class of a group in a declared order",
                    (
                        "dimensioning values of an equipment over its variants, a "
                        "bound for a life-cycle profile"
                    ),
                    "number of members beyond a threshold",
                ),
                reference=(
                    "Property checked by the tests: for a threshold, the Kleene "
                    "conjunction of the verdicts of the members equals the "
                    "verdict of their envelope."
                ),
            ),
        )
    }
)


def derivations() -> tuple[DerivationInfo, ...]:
    """The derivations of the registry, in a fixed order.

    Examples
    --------
    >>> [d.name for d in derivations()]
    ['aggregate']
    """
    return tuple(DERIVATIONS.values())
