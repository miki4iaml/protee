# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Composition of effects into a computation view."""

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from protee.constraints._effects import Effect, Verdict
from protee.graph import Digraph

__all__ = ["ComputationView", "UnknownPolicy", "compose"]


class UnknownPolicy(StrEnum):
    """What to do with an arc whose verdict is unknown.

    - ``exclude``: as if it failed;
    - ``penalize``: admitted, with a penalty added to its weight;
    - ``admit_and_count``: admitted, and counted in every result.
    """

    EXCLUDE = "exclude"
    PENALIZE = "penalize"
    ADMIT_AND_COUNT = "admit_and_count"


def _frozen[T: np.generic](array: npt.NDArray[T]) -> npt.NDArray[T]:
    array.flags.writeable = False
    return array


@dataclass(frozen=True, slots=True, eq=False)
class ComputationView:
    """What a solver consumes, with links back to the effects.

    All arrays are read-only, one value per arc.

    Attributes
    ----------
    m : int
        Number of arcs.
    policy : UnknownPolicy
        Applied once, after the composition.
    penalty : float or None
        Weight added to an unknown arc (``penalize`` policy).
    verdict : numpy.ndarray of int8
        Kleene conjunction of the verdicts (``PASS`` where none applies).
    admitted : numpy.ndarray of bool
        Arcs a solver may use.
    unknown : numpy.ndarray of bool
        Arcs whose verdict is unknown.
    cap : numpy.ndarray of float64
        Minimum of the caps, ``inf`` where none applies.
    factor : numpy.ndarray of float64
        Product of the factors.
    added : numpy.ndarray of float64
        Sum of the added amounts.
    lower, upper : numpy.ndarray of float64
        Greatest lower bound and least upper bound of the flow.
    effects : tuple of Effect
        The composed effects, by requirement identifier.
    objective : str or None
        The criterion declared by an ``objective`` requirement.
    """

    m: int
    policy: UnknownPolicy
    penalty: float | None
    verdict: npt.NDArray[np.int8]
    admitted: npt.NDArray[np.bool_]
    unknown: npt.NDArray[np.bool_]
    cap: npt.NDArray[np.float64]
    factor: npt.NDArray[np.float64]
    added: npt.NDArray[np.float64]
    lower: npt.NDArray[np.float64]
    upper: npt.NDArray[np.float64]
    effects: tuple[Effect, ...]
    objective: str | None = None

    @property
    def excluded(self) -> tuple[int, ...]:
        """The arcs a solver must not use, in increasing order."""
        return tuple(int(a) for a in np.flatnonzero(~self.admitted))

    @property
    def unknown_count(self) -> int:
        """Number of arcs whose verdict is unknown."""
        return int(self.unknown.sum())

    @property
    def bound_conflicts(self) -> tuple[int, ...]:
        """The arcs whose lower bound exceeds their upper bound."""
        return tuple(int(a) for a in np.flatnonzero(self.lower > self.upper))

    def weights(self, base: Sequence[float]) -> tuple[float, ...]:
        """Arc weights for a solver, from a base weight per arc.

        ``base * factor + added``, plus the penalty on unknown arcs under
        the ``penalize`` policy. Excluded arcs keep a weight: pass
        :attr:`excluded` to the solver.
        """
        b = np.asarray(base, dtype=np.float64)
        if b.shape != (self.m,):
            raise ValueError(f"expected {self.m} base weights, got shape {b.shape}")
        w = b * self.factor + self.added
        if self.policy is UnknownPolicy.PENALIZE:
            assert self.penalty is not None
            w = w + np.where(self.unknown, self.penalty, 0.0)
        return tuple(float(x) for x in w)

    def lexicographic_weights(
        self, base: Sequence[float]
    ) -> tuple[tuple[int, float], ...]:
        """Weight vectors that count the unknown arcs first, then the weight.

        For :func:`~protee.paths.lexicographic_dijkstra`: among the routes
        with the fewest unknown arcs, the lightest one (``base * factor +
        added``).
        """
        b = np.asarray(base, dtype=np.float64)
        if b.shape != (self.m,):
            raise ValueError(f"expected {self.m} base weights, got shape {b.shape}")
        w = b * self.factor + self.added
        return tuple((int(u), float(x)) for u, x in zip(self.unknown, w, strict=True))

    def flow_bounds(self) -> tuple[tuple[int, ...], tuple[int | None, ...]]:
        """Lower and upper flow bounds for a :class:`~protee.flow.FlowProblem`.

        ``None`` stands for no upper bound.
        """
        lower = tuple(int(x) for x in self.lower)
        upper = tuple(None if math.isinf(x) else int(x) for x in self.upper)
        return lower, upper

    def requirements_on(self, arc: int) -> tuple[str, ...]:
        """The requirements whose effect is not neutral on ``arc``.

        A verdict that is not a pass, a finite cap, a factor other than 1,
        an amount other than 0, or a flow bound.
        """
        if not 0 <= arc < self.m:
            raise ValueError(f"arc {arc} out of range")
        return tuple(e.requirement for e in self.effects if _touches(e, arc))


def _touches(e: Effect, a: int) -> bool:
    return bool(
        (e.verdict is not None and e.verdict[a] != Verdict.PASS)
        or (e.cap is not None and math.isfinite(e.cap[a]))
        or (e.factor is not None and e.factor[a] != 1.0)
        or (e.added is not None and e.added[a] != 0.0)
        or (e.lower is not None and e.lower[a] > 0)
        or (e.upper is not None and math.isfinite(e.upper[a]))
    )


def compose(
    graph: Digraph,
    effects: Iterable[Effect],
    *,
    unknown: UnknownPolicy | str,
    penalty: float | None = None,
) -> ComputationView:
    """Compose effects into a computation view, independently of their order.

    Verdicts combine by the Kleene conjunction (a failure prevails, then the
    unknown), caps by their minimum, factors by their product, added
    amounts by their sum, lower bounds by their maximum and upper bounds
    by their minimum. The policy for the unknown is applied once, after the
    composition.

    Parameters
    ----------
    graph : Digraph
    effects : iterable of Effect
        One per requirement; effects that do not apply are neutral.
    unknown : UnknownPolicy or str
        No default: the caller states the policy.
    penalty : float, optional
        Positive and finite, required by the ``penalize`` policy only.

    Returns
    -------
    ComputationView

    Raises
    ------
    ValueError
        If two effects share a requirement, an effect does not match the
        graph, ``penalty`` does not fit the policy, or two objectives
        differ.
    """
    policy = UnknownPolicy(unknown)
    if policy is UnknownPolicy.PENALIZE:
        if penalty is None or not (math.isfinite(penalty) and penalty > 0):
            raise ValueError("the penalize policy needs a positive, finite penalty")
    elif penalty is not None:
        raise ValueError(f"a penalty does not apply to the {policy} policy")
    m = graph.m
    ordered = sorted(effects, key=lambda e: e.requirement)
    for e, f in itertools.pairwise(ordered):
        if e.requirement == f.requirement:
            raise ValueError(f"two effects for requirement {e.requirement!r}")
    verdict = np.full(m, Verdict.PASS, dtype=np.int8)
    cap = np.full(m, math.inf)
    factor = np.ones(m)
    added = np.zeros(m)
    lower = np.zeros(m)
    upper = np.full(m, math.inf)
    for e in ordered:
        if e.m != m:
            raise ValueError(f"effect of {e.requirement} for {e.m} arcs, graph of {m}")
        if e.verdict is not None:
            verdict = np.minimum(verdict, e.verdict)
        if e.cap is not None:
            cap = np.minimum(cap, e.cap)
        if e.factor is not None:
            factor = factor * e.factor
        if e.added is not None:
            added = added + e.added
        if e.lower is not None:
            lower = np.maximum(lower, e.lower)
        if e.upper is not None:
            upper = np.minimum(upper, e.upper)
    objectives = {e.objective for e in ordered if e.objective is not None}
    if len(objectives) > 1:
        raise ValueError(f"several objectives declared: {sorted(objectives)}")
    unknown_mask = verdict == Verdict.UNKNOWN
    admitted = verdict != Verdict.FAIL
    if policy is UnknownPolicy.EXCLUDE:
        admitted = admitted & ~unknown_mask
    return ComputationView(
        m=m,
        policy=policy,
        penalty=penalty,
        verdict=_frozen(verdict),
        admitted=_frozen(admitted),
        unknown=_frozen(unknown_mask),
        cap=_frozen(cap),
        factor=_frozen(factor),
        added=_frozen(added),
        lower=_frozen(lower),
        upper=_frozen(upper),
        effects=tuple(ordered),
        objective=next(iter(objectives), None),
    )
