# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Registry of the methods that explain a failure: conflicts, relaxations
and tiers."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from protee.results import Guarantee, GuaranteeKind, MethodInfo

__all__ = ["FEASIBILITY_TESTS", "PROBLEMS", "info", "methods"]

#: Name of the counter of every method of the registry: the number of
#: distinct sets of requirements passed to the feasibility test.
FEASIBILITY_TESTS = "feasibility_tests"

#: The problems of the registry, in a fixed order.
PROBLEMS = ("minimal_conflict", "minimal_relaxation", "relaxation_by_tiers")

_BOOK = "Chinneck, Feasibility and Infeasibility in Optimization (2008)"
_MINIMUM = "minimum cardinality"
_RESTORED = "no relaxed requirement can be restored"

_REGISTRY: Mapping[tuple[str, str], MethodInfo] = MappingProxyType(
    {
        (described.problem, described.name): described
        for described in (
            MethodInfo(
                name="enumeration",
                problem="minimal_conflict",
                summary="Subsets of increasing size: the first infeasible one.",
                guarantee=Guarantee(GuaranteeKind.EXACT, f"conflict of {_MINIMUM}"),
                complexity="at most 2^k feasibility tests, k requirements",
                reference=f"Exhaustive search; {_BOOK}",
            ),
            MethodInfo(
                name="deletion_filter",
                problem="minimal_conflict",
                summary=(
                    "Remove each requirement in turn when the rest stays infeasible."
                ),
                guarantee=Guarantee(
                    GuaranteeKind.PROPERTY,
                    "irreducible: feasible as soon as one requirement is removed",
                ),
                complexity="at most k + 1 feasibility tests, k requirements",
                reference=(
                    "Chinneck, Dravnieks, ORSA Journal on Computing 3(2) (1991)"
                ),
            ),
            MethodInfo(
                name="enumeration",
                problem="minimal_relaxation",
                summary=(
                    "Subsets of increasing size: the first whose relaxation "
                    "makes the others hold."
                ),
                guarantee=Guarantee(GuaranteeKind.EXACT, f"relaxation of {_MINIMUM}"),
                complexity="at most 2^k feasibility tests, k requirements",
                reference=f"Exhaustive search; {_BOOK}",
            ),
            MethodInfo(
                name="greedy",
                problem="minimal_relaxation",
                summary=(
                    "Relax every requirement, then restore each one in turn "
                    "when the problem stays feasible."
                ),
                guarantee=Guarantee(GuaranteeKind.PROPERTY, _RESTORED),
                complexity="at most k + 2 feasibility tests, k requirements",
                reference=f"Greedy maximal feasible subset; {_BOOK}",
            ),
            MethodInfo(
                name="enumeration",
                problem="relaxation_by_tiers",
                summary=(
                    "Tiers by increasing level; in the first feasible one, the "
                    "fewest requirements to relax."
                ),
                guarantee=Guarantee(
                    GuaranteeKind.EXACT,
                    f"lowest feasible tier, relaxation of {_MINIMUM} within it",
                ),
                complexity=(
                    "at most t + 2^c feasibility tests, t tiers and c "
                    "requirements relaxable up to the first feasible tier"
                ),
                reference=f"Declared tiers tried in order; {_BOOK}",
            ),
            MethodInfo(
                name="greedy",
                problem="relaxation_by_tiers",
                summary=(
                    "Tiers by increasing level; in the first feasible one, "
                    "restore each relaxable requirement in turn when feasible."
                ),
                guarantee=Guarantee(
                    GuaranteeKind.PROPERTY, f"lowest feasible tier; {_RESTORED}"
                ),
                complexity=(
                    "at most t + c + 1 feasibility tests, t tiers and c "
                    "requirements relaxable up to the first feasible tier"
                ),
                reference=f"Declared tiers tried in order; {_BOOK}",
            ),
        )
    }
)


def methods(problem: str | None = None) -> tuple[MethodInfo, ...]:
    """The methods that explain a failure, in a fixed order.

    Parameters
    ----------
    problem : str, optional
        Only the methods of this problem: ``"minimal_conflict"``,
        ``"minimal_relaxation"`` or ``"relaxation_by_tiers"``, solved by
        :func:`minimal_conflict`, :func:`minimal_relaxation` and
        :func:`relax_by_tiers`; each takes the name of a method of its
        problem, without default. All of them by default.

    Returns
    -------
    tuple of MethodInfo
        With its guarantee and its complexity, counted in calls to the
        feasibility test (the counter ``feasibility_tests`` of every
        result).

    Raises
    ------
    ValueError
        If the problem is unknown.

    Examples
    --------
    >>> [info.name for info in methods("minimal_conflict")]
    ['enumeration', 'deletion_filter']
    """
    if problem is None:
        return tuple(_REGISTRY.values())
    if problem not in PROBLEMS:
        raise ValueError(f"unknown problem {problem!r}; one of {PROBLEMS}")
    return tuple(i for (p, _), i in _REGISTRY.items() if p == problem)


def info(problem: str, method: str) -> MethodInfo:
    """The description of ``method`` for ``problem``.

    Raises
    ------
    ValueError
        If the method is unknown for this problem.
    """
    found = _REGISTRY.get((problem, method))
    if found is None:
        names = [i.name for i in methods(problem)]
        raise ValueError(f"unknown method {method!r} for {problem}; one of {names}")
    return found
