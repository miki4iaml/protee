# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Composition of effects into a computation view."""

from __future__ import annotations

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
    out = np.array(array, copy=True)
    out.flags.writeable = False
    return out


def _per_arc(name: str, values: Sequence[float], m: int) -> npt.NDArray[np.float64]:
    out = np.asarray(values, dtype=np.float64)
    if out.shape != (m,):
        raise ValueError(f"expected {m} {name}, got shape {out.shape}")
    return out


@dataclass(frozen=True, slots=True, eq=False)
class ComputationView:
    """What a solver consumes, with links back to the effects.

    All arrays are read-only copies, one value per arc. Build one with
    :func:`compose`.

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
        Minimum of the speed caps, ``inf`` where none applies; it enters
        the travel times (:meth:`times`), never plain weights.
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

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "policy", UnknownPolicy(self.policy))
        for name in (
            "verdict",
            "admitted",
            "unknown",
            "cap",
            "factor",
            "added",
            "lower",
            "upper",
        ):
            array = _frozen(getattr(self, name))
            if array.shape != (self.m,):
                raise ValueError(f"{name}: expected {self.m} values")
            set_(self, name, array)
        set_(self, "effects", tuple(self.effects))

    @property
    def capped(self) -> tuple[int, ...]:
        """The arcs whose speed is capped, in increasing order."""
        return tuple(int(a) for a in np.flatnonzero(np.isfinite(self.cap)))

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

        Raises
        ------
        ValueError
            If the view caps speeds: a cap changes travel times, which
            :meth:`times` computes; plain weights would ignore it.
        """
        if capped := self.capped:
            raise ValueError(
                f"the view caps the speed on {len(capped)} arcs: use "
                "times(length, speed), plain weights would ignore the caps"
            )
        return self._finish(_per_arc("base weights", base, self.m))

    def times(
        self, length: Sequence[float], speed: Sequence[float]
    ) -> tuple[float, ...]:
        """Travel times for a solver, with the speed caps applied.

        ``length / min(speed, cap)``, then ``* factor + added``, plus the
        penalty on unknown arcs under the ``penalize`` policy; in the unit
        of the length divided by the unit of the speed (hours for
        kilometres and km/h).

        Raises
        ------
        ValueError
            If a length or a speed is unknown (``NaN``), a length negative
            or a speed not positive and finite: the time of the arc cannot
            be computed, and is never presumed; derive the missing values
            explicitly (a derived :class:`Attribute`, with its quality).
        """
        size = _per_arc("lengths", length, self.m)
        pace = _per_arc("speeds", speed, self.m)
        if (unknown := int(np.isnan(size).sum() + np.isnan(pace).sum())) > 0:
            raise ValueError(
                f"{unknown} unknown lengths or speeds: a travel time needs both"
            )
        if not ((size >= 0).all() and np.isfinite(size).all()):
            raise ValueError("lengths must be non-negative and finite")
        if not ((pace > 0).all() and np.isfinite(pace).all()):
            raise ValueError("speeds must be positive and finite")
        return self._finish(size / np.minimum(pace, self.cap))

    def _finish(self, base: npt.NDArray[np.float64]) -> tuple[float, ...]:
        w = base * self.factor + self.added
        if self.policy is UnknownPolicy.PENALIZE:
            assert self.penalty is not None
            w = w + np.where(self.unknown, self.penalty, 0.0)
        return tuple(float(x) for x in w)

    def lexicographic_weights(
        self, weights: Sequence[float]
    ) -> tuple[tuple[int, float], ...]:
        """Weight vectors that count the unknown arcs first, then the weight.

        For :func:`~protee.paths.lexicographic_dijkstra`: among the routes
        with the fewest unknown arcs, the lightest one.

        Parameters
        ----------
        weights : sequence of float
            One weight per arc, from :meth:`weights` or :meth:`times`.
        """
        w = _per_arc("weights", weights, self.m)
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
    policy: UnknownPolicy | str,
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
    policy : UnknownPolicy or str
        The policy for the unknown; no default: the caller states it.
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
    policy = UnknownPolicy(policy)
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
        verdict=verdict,
        admitted=admitted,
        unknown=unknown_mask,
        cap=cap,
        factor=factor,
        added=added,
        lower=lower,
        upper=upper,
        effects=tuple(ordered),
        objective=next(iter(objectives), None),
    )
