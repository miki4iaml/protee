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
            DerivationInfo(
                name="classify_by_thresholds",
                summary=(
                    "The class of a subject from thresholds on its "
                    "characteristics: the rank of each characteristic is one "
                    "plus the number of thresholds its value crosses, by a "
                    "declared comparison, and the strongest characteristic "
                    "decides the class."
                ),
                inputs=(
                    "the values of the characteristics of a subject; for each "
                    "characteristic, its thresholds, from a value set taken from "
                    "a text, and when a value crosses them; the labels of the "
                    "classes, from the weakest"
                ),
                output=(
                    "a value set of a declared rulebook: the class, with the "
                    "characteristics that fix it and the thresholds they cross"
                ),
                rules=("highest_rank",),
                cases=(
                    (
                        "category of an oversize transport from its length, its "
                        "width and its mass"
                    ),
                    "a number of members compared with a threshold stated as from",
                ),
                reference=(
                    "Order of 4 May 2006 on exceptional transport (France), "
                    "article 3, whose thresholds the embedded value set "
                    "fr-oversize-transport-2006 gives."
                ),
            ),
            DerivationInfo(
                name="select_by_class",
                summary=(
                    "The value a class selects in a table: each class names the "
                    "parameter of its value, or has no value of its own, and "
                    "the value selected is then not applicable, with the reason."
                ),
                inputs=(
                    "a class, derived or given; a table from each class to a "
                    "parameter, or to the reason why it has none; the values "
                    "the parameters are resolved in"
                ),
                output=(
                    "a value set of a declared rulebook: the value selected, "
                    "with the class that selects it and its source"
                ),
                rules=("table",),
                cases=(
                    "maximum speeds by category and by kind of road",
                    "a threshold by configuration",
                ),
                reference=(
                    "Order of 4 May 2006 on exceptional transport (France), "
                    "article 14, whose speeds the embedded value set "
                    "fr-oversize-transport-2006 gives."
                ),
            ),
            DerivationInfo(
                name="column_length",
                summary=(
                    "The length a group occupies in a column, level by level: "
                    "the lengths of its members or their number over a density, "
                    "plus the gaps between its units, counted between units or "
                    "one per unit, in distance or in time at a pace."
                ),
                inputs=(
                    "a group of members or of groups, with their counts; the "
                    "length of each member, or a density for each group of "
                    "members; a gap for each level of groups, read on the group "
                    "or on an ancestor; a pace for gaps in time"
                ),
                output=(
                    "a value set named after the group: the length, with the "
                    "members and the values of groups it is computed from"
                ),
                rules=("density", "geometric"),
                cases=(
                    (
                        "road space of a column: its members over a density, plus "
                        "gaps in time at its pace"
                    ),
                    "length of a line of units: their lengths plus the spacings",
                ),
                reference=(
                    "Identities checked by the tests: a density of one over the "
                    "gap plus the mean length gives the geometric length with "
                    "one gap per unit, exactly, and one gap per unit adds one gap "
                    "per group of members to the length with gaps between units."
                ),
            ),
        )
    }
)


#: What the bound of a value to be set says of it, by derivation and rule:
#: the value is at least the bound, at most the bound, or at least as
#: strict in an order of labels (that of ``strictest``, the classes of a
#: classification). A derivation that reads such a value, and the
#: admissibility patterns, read its bound; any other value to be set is
#: unknown, whatever its bound.
ENVELOPES: Mapping[tuple[str, str], str] = MappingProxyType(
    {
        ("aggregate", "max"): "at least",
        ("aggregate", "min"): "at most",
        ("aggregate", "strictest"): "at least as strict as",
        ("classify_by_thresholds", "highest_rank"): "at least as strict as",
    }
)

#: The side of a bound in an order of labels.
STRICTER = "at least as strict as"

#: The setting that holds the order of labels of a derivation, from the
#: least to the most demanding.
ORDERS: Mapping[str, str] = MappingProxyType(
    {"aggregate": "order", "classify_by_thresholds": "classes"}
)


def derivations() -> tuple[DerivationInfo, ...]:
    """The derivations of the registry, in a fixed order.

    Examples
    --------
    >>> [d.name for d in derivations()]
    ['aggregate', 'classify_by_thresholds', 'select_by_class', 'column_length']
    """
    return tuple(DERIVATIONS.values())
