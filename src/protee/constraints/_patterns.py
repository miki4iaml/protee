# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The closed registry of constraint patterns."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

__all__ = ["PATTERNS", "EffectKind", "Family", "Pattern", "Subject", "patterns"]


class Family(StrEnum):
    """Family of a requirement, by what it acts upon."""

    ADMISSIBILITY = "admissibility"
    COST = "cost"
    MODE = "mode"
    TRANSITION = "transition"
    ROUTE = "route"
    TIME = "time"
    CAPACITY = "capacity"
    NETWORK = "network"
    TIERS = "tiers"
    RESOLUTION = "resolution"


class EffectKind(StrEnum):
    """What the evaluation of a requirement returns, declared by its pattern.

    - ``verdict``: pass, fail or unknown for each arc (a ban is never turned
      into a penalty silently);
    - ``cost_term``: a cap, a factor or an added amount for each arc;
    - ``bound``: lower and upper bounds on the flow of each arc;
    - ``objective``: the criterion a result optimizes.
    """

    VERDICT = "verdict"
    COST_TERM = "cost_term"
    BOUND = "bound"
    OBJECTIVE = "objective"


class Subject(StrEnum):
    """What the value of a pattern constrains.

    The clearance offered by a deck (infrastructure) is not the clearance a
    vehicle requires (vehicle): a pattern states which one its value is.
    """

    VEHICLE = "vehicle"
    INFRASTRUCTURE = "infrastructure"
    FLOW = "flow"
    RESULT = "result"


@dataclass(frozen=True, slots=True)
class Pattern:
    """A generic form of constraint on a graph, without any value.

    Attributes
    ----------
    name : str
        Explicit, generic name, used by :attr:`Requirement.pattern`.
    summary : str
    family : Family
    effect_kind : EffectKind
    subject : Subject
        What the value constrains.
    parameters : tuple of str
        Roles of the values a requirement must bind to named parameters.
    attributes : tuple of str
        Roles of the arc attributes a requirement must bind to columns of
        :class:`ArcData`.
    optional : tuple of str
        Roles of values a requirement may bind.
    composition : str
        How the effects of several requirements of this pattern combine.

    Notes
    -----
    The registry is closed until version 1.0: a new pattern comes with its
    definition, its composition rule and its tests.
    """

    name: str
    summary: str
    family: Family
    effect_kind: EffectKind
    subject: Subject
    parameters: tuple[str, ...]
    attributes: tuple[str, ...]
    optional: tuple[str, ...] = ()
    composition: str = ""


_KLEENE = "Kleene conjunction: a failure prevails, then the unknown"

PATTERNS: Mapping[str, Pattern] = MappingProxyType(
    {
        p.name: p
        for p in (
            Pattern(
                name="threshold_admissibility",
                summary=(
                    "An arc is admissible when the quantity of the vehicle (mass, "
                    "height, width) is at most the limit of the arc."
                ),
                family=Family.ADMISSIBILITY,
                effect_kind=EffectKind.VERDICT,
                subject=Subject.VEHICLE,
                parameters=("quantity",),
                attributes=("limit",),
                composition=_KLEENE,
            ),
            Pattern(
                name="class_admissibility",
                summary=(
                    "An arc is admissible when its class, in a declared order, is "
                    "at least the class required by the vehicle (load class, "
                    "tunnel category)."
                ),
                family=Family.ADMISSIBILITY,
                effect_kind=EffectKind.VERDICT,
                subject=Subject.VEHICLE,
                parameters=("required_class",),
                attributes=("class",),
                composition=_KLEENE,
            ),
            Pattern(
                name="zone_exclusion",
                summary=(
                    "An arc inside a zone is not admissible; membership is a "
                    "relation computed elsewhere (1 inside, 0 outside)."
                ),
                family=Family.ADMISSIBILITY,
                effect_kind=EffectKind.VERDICT,
                subject=Subject.INFRASTRUCTURE,
                parameters=(),
                attributes=("inside",),
                composition=_KLEENE,
            ),
            Pattern(
                name="speed_cap",
                summary=(
                    "The speed of the vehicle on an arc is at most a cap: the "
                    "travel time of the arc is its length divided by the least of "
                    "its speed and the cap."
                ),
                family=Family.COST,
                effect_kind=EffectKind.COST_TERM,
                subject=Subject.VEHICLE,
                parameters=("maximum",),
                attributes=("length", "speed"),
                composition="minimum of the caps",
            ),
            Pattern(
                name="occurrence_bounds",
                summary=(
                    "The flow of an arc (the occurrences of a link of a life-cycle "
                    "profile) lies between a minimum and a maximum."
                ),
                family=Family.CAPACITY,
                effect_kind=EffectKind.BOUND,
                subject=Subject.FLOW,
                parameters=("maximum",),
                attributes=(),
                optional=("minimum",),
                composition="maximum of the lower bounds, minimum of the upper bounds",
            ),
            Pattern(
                name="objective",
                summary=(
                    "The criterion a result optimizes, prescribed by a text, or "
                    "chosen with a justification."
                ),
                family=Family.RESOLUTION,
                effect_kind=EffectKind.OBJECTIVE,
                subject=Subject.RESULT,
                parameters=("criterion",),
                attributes=(),
                composition="one objective per computation",
            ),
        )
    }
)


def patterns() -> tuple[Pattern, ...]:
    """The patterns of the registry, in a fixed order."""
    return tuple(PATTERNS.values())
