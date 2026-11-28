# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Shortest paths on a :class:`~protee.graph.Digraph`.

Named methods, chosen explicitly by the caller (see :func:`methods`):

- :func:`dijkstra`, for non-negative arc weights;
- :func:`bellman_ford`, for any weights: the status is ``unbounded``, with
  a :class:`NegativeCycle`, when a cycle of negative weight is reachable
  from the sources;
- :func:`lexicographic_dijkstra`, for non-negative weight vectors compared
  in lexicographic order (first the number of unknown arcs, then the
  length, for instance).

Each returns a result built on :class:`~protee.results.ResultCore`:
status, guarantee, parameters, counters, version and fingerprint of the
inputs. A shortest path tree is exact whether or not every node is
reachable: its status is ``optimal``, and ``path(v)`` returns ``None`` for
an unreachable node.

Provisional API (until version 1.0).
"""

from __future__ import annotations

import heapq
import math
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import NamedTuple

from protee.graph import Digraph
from protee.results import (
    Guarantee,
    GuaranteeKind,
    MethodInfo,
    NegativeCycle,
    ResultCore,
    SeparatingCut,
    Status,
)

__all__ = [
    "LexicographicPaths",
    "NegativeCycle",
    "SeparatingCut",
    "ShortestPaths",
    "bellman_ford",
    "dijkstra",
    "lexicographic_dijkstra",
    "methods",
]

type Number = int | float
type Vector = tuple[Number, ...]

_METHODS: Mapping[str, MethodInfo] = MappingProxyType(
    {
        "dijkstra": MethodInfo(
            name="dijkstra",
            problem="shortest_paths",
            summary="Label setting with a binary heap, for non-negative weights.",
            guarantee=Guarantee(
                GuaranteeKind.EXACT,
                "exact distances and shortest path tree from the sources "
                "(with a target: up to the distance of the target)",
            ),
            complexity="O((n + m) log n)",
            reference="Dijkstra (1959)",
        ),
        "bellman_ford": MethodInfo(
            name="bellman_ford",
            problem="shortest_paths",
            summary="Label correcting by passes over every arc, for any weights.",
            guarantee=Guarantee(
                GuaranteeKind.EXACT,
                "exact distances and shortest path tree, or a negative cycle "
                "reachable from the sources",
            ),
            complexity="O(n m)",
            reference="Ford (1956); Bellman (1958); Moore (1959)",
            options=("tolerance",),
        ),
        "lexicographic_dijkstra": MethodInfo(
            name="lexicographic_dijkstra",
            problem="lexicographic_shortest_paths",
            summary="Dijkstra on non-negative weight vectors, added componentwise "
            "and compared lexicographically.",
            guarantee=Guarantee(
                GuaranteeKind.EXACT,
                "exact lexicographic distances and shortest path tree, without scaling",
            ),
            complexity="O(k (n + m) log n), k the length of the vectors",
            reference="Dijkstra (1959); Gondran, Minoux, Graphs, Dioids and "
            "Semirings (2008)",
        ),
    }
)


def _registry(
    infos: Iterable[MethodInfo], problem: str | None
) -> tuple[MethodInfo, ...]:
    found = tuple(infos)
    if problem is None:
        return found
    chosen = tuple(info for info in found if info.problem == problem)
    if not chosen:
        known = sorted({info.problem for info in found})
        raise ValueError(f"unknown problem {problem!r}; choose among {known}")
    return chosen


def methods(problem: str | None = None) -> tuple[MethodInfo, ...]:
    """The shortest path methods, in a fixed order.

    Parameters
    ----------
    problem : str, optional
        ``"shortest_paths"`` (``dijkstra``, ``bellman_ford``) or
        ``"lexicographic_shortest_paths"`` (``lexicographic_dijkstra``);
        every method of the module by default.

    Returns
    -------
    tuple of MethodInfo
        The name of a method is the name of its function.

    Raises
    ------
    ValueError
        If ``problem`` is not one of this module.
    """
    return _registry(_METHODS.values(), problem)


def _walk(
    predecessor: Sequence[int], tails: Sequence[int], target: int
) -> tuple[int, ...]:
    """The arcs from a source to ``target``, by the predecessors."""
    arcs: list[int] = []
    v = target
    while (a := predecessor[v]) != -1:
        arcs.append(a)
        v = tails[a]
    arcs.reverse()
    return tuple(arcs)


@dataclass(frozen=True, slots=True, kw_only=True)
class ShortestPaths(ResultCore):
    """Shortest path tree from one or several sources.

    On top of the fields of :class:`~protee.results.ResultCore` (status,
    method, guarantee, parameters, counters, version, certificate and the
    fingerprint of the inputs):

    Attributes
    ----------
    sources : tuple of int
        The sources, which start at distance 0. With negative weights
        (:func:`bellman_ford`, every node being a source when none is
        given), a path from another source can give a source a negative
        distance and a predecessor.
    distance : tuple of int or float
        Distance of each node: ``math.inf`` when it is unreachable, and
        ``-math.inf`` when the status is ``unbounded`` and a negative cycle
        reachable from the sources reaches the node.
    predecessor : tuple of int
        Last arc of a shortest path to each node; ``-1`` for a source that
        keeps its distance 0, an unreachable node or a node at
        ``-math.inf``.

    Notes
    -----
    ``optimal``: the distances are exact; with a target, those of the
    target and of the nodes settled before it, the others being
    provisional (at least the true distance). ``unbounded``
    (:func:`bellman_ford` only): the certificate is a
    :class:`NegativeCycle`; a node that no negative cycle reaches keeps
    its exact distance and shortest path.

    ``counters``: ``settled_nodes`` and ``scanned_arcs`` for
    :func:`dijkstra`, ``passes`` for :func:`bellman_ford`. ``inputs``
    covers the graph, the weights and the sources, with the target and
    the excluded arcs for :func:`dijkstra`.
    """

    sources: tuple[int, ...]
    distance: tuple[Number, ...]
    predecessor: tuple[int, ...]
    _tails: tuple[int, ...] = field(repr=False, compare=False)

    def path(self, target: int) -> tuple[int, ...] | None:
        """Arcs of a shortest path from a source to ``target``.

        Returns
        -------
        tuple of int or None
            The arcs in order (empty when ``target`` is a source that keeps
            its distance 0), or ``None`` when ``target`` is unreachable.

        Raises
        ------
        ValueError
            If a negative cycle reaches ``target``: no path is shortest.
        """
        d = self.distance[target]
        if d == math.inf:
            return None
        if d == -math.inf:
            raise ValueError(
                f"no shortest path to node {target}: a negative cycle reaches it"
            )
        return _walk(self.predecessor, self._tails, target)


@dataclass(frozen=True, slots=True, kw_only=True)
class LexicographicPaths(ResultCore):
    """Shortest path tree for weight vectors in lexicographic order.

    On top of the fields of :class:`~protee.results.ResultCore`:

    Attributes
    ----------
    sources : tuple of int
        The sources, at the zero vector.
    distance : tuple of (tuple of int or float) or None
        Distance vector of each node, ``None`` when it is unreachable.
    predecessor : tuple of int
        Last arc of a shortest path to each node, ``-1`` for a source or an
        unreachable node.

    Notes
    -----
    The status is always ``optimal``; with a target, the distances of the
    target and of the nodes settled before it are exact, the others
    provisional.

    ``counters``: ``settled_nodes`` and ``scanned_arcs``. ``inputs`` covers
    the graph, the weight vectors, the sources, the target and the
    excluded arcs.
    """

    sources: tuple[int, ...]
    distance: tuple[Vector | None, ...]
    predecessor: tuple[int, ...]
    _tails: tuple[int, ...] = field(repr=False, compare=False)

    def path(self, target: int) -> tuple[int, ...] | None:
        """Arcs of a shortest path from a source to ``target``, or ``None``
        when ``target`` is unreachable."""
        if self.distance[target] is None:
            return None
        return _walk(self.predecessor, self._tails, target)


# --- checks of the public functions ----------------------------------------


def _node(graph: Digraph, v: int, what: str) -> int:
    if not 0 <= v < graph.n:
        raise ValueError(f"{what} {v} is not a node")
    return v


def _source_nodes(graph: Digraph, source: int | Iterable[int]) -> tuple[int, ...]:
    found = (source,) if isinstance(source, int) else tuple(dict.fromkeys(source))
    for s in found:
        _node(graph, s, "source")
    return found


def _finite(x: Number, arc: int, what: str = "the weight of arc") -> bool:
    """Whether ``x``, of ``arc``, is finite. An int always is, whatever its
    size; another number beyond the float range (a fraction, for instance)
    is refused, as no float holds it."""
    if isinstance(x, int):
        return True
    try:
        return math.isfinite(x)
    except OverflowError:
        raise ValueError(f"{what} {arc} is beyond the float range") from None


def _overflows() -> ValueError:
    return ValueError(
        "the absolute weights sum beyond the float range: "
        "the sum along a path could overflow"
    )


def _float_bound(values: Sequence[Number]) -> float | None:
    """A bound on the float sums of ``values`` (finite numbers) along a
    path: the sum of their absolute values, as a float.

    ``None`` when every value is an int: ints sum exactly, whatever their
    size, and no sum overflows.

    Raises
    ------
    ValueError
        If the bound is beyond the float range (an int beyond it among
        other numbers included): a float sum along a path could overflow.
    """
    if all(isinstance(x, int) for x in values):
        return None
    try:
        total = sum(map(abs, map(float, values)))
    except OverflowError:  # an int beyond the float range
        raise _overflows() from None
    if not math.isfinite(total):
        raise _overflows()
    return total


def _used[T](values: Sequence[T], skip: Sequence[bool] | None) -> Sequence[T]:
    """The values of the arcs a computation can use: those ``skip`` does
    not flag, every one without ``skip``."""
    if skip is None or not any(skip):
        return values
    return [x for x, barred in zip(values, skip, strict=True) if not barred]


def _check_weights(
    graph: Digraph, weight: Sequence[Number], skip: Sequence[bool] | None = None
) -> float | None:
    """Check one finite weight per arc, and return :func:`_float_bound` of
    the weights the computation can use (an excluded arc never enters a
    sum): finite, so that no float sum along a path overflows, or ``None``
    when these weights are all ints, which sum exactly."""
    if len(weight) != graph.m:
        raise ValueError(f"expected {graph.m} weights, got {len(weight)}")
    for a, w in enumerate(weight):
        if not _finite(w, a):
            raise ValueError(f"the weight of arc {a} is not finite: {w}")
    return _float_bound(_used(weight, skip))


def _check_nonnegative(
    graph: Digraph, weight: Sequence[Number], skip: Sequence[bool] | None = None
) -> float | None:
    """As :func:`_check_weights`, for non-negative weights."""
    bound = _check_weights(graph, weight, skip)
    for a, w in enumerate(weight):
        if w < 0:
            raise ValueError(
                f"the weight of arc {a} is negative ({w}): use bellman_ford"
            )
    return bound


def _skip(graph: Digraph, excluded: Collection[int]) -> list[bool]:
    """One flag per arc: ``True`` for an excluded arc."""
    skip = [False] * graph.m
    for a in excluded:
        if not 0 <= a < graph.m:
            raise ValueError(f"excluded arc {a} does not exist")
        skip[a] = True
    return skip


def _vectors(
    graph: Digraph, weight: Sequence[Sequence[Number]], skip: Sequence[bool]
) -> tuple[Vector, ...]:
    """Check one vector of non-negative finite components per arc, and the
    :func:`_float_bound` of each rank over the arcs the computation can
    use."""
    if len(weight) != graph.m:
        raise ValueError(f"expected {graph.m} weight vectors, got {len(weight)}")
    vectors = tuple(tuple(w) for w in weight)
    size = len(vectors[0]) if vectors else 1
    for a, w in enumerate(vectors):
        if len(w) != size or size == 0:
            raise ValueError(
                f"the weight of arc {a} has {len(w)} components, not {size}"
            )
        what = "a component of the weight of arc"
        if not all(_finite(x, a, what) and x >= 0 for x in w):
            raise ValueError(f"the weight of arc {a} is negative or not finite: {w}")
    used = _used(vectors, skip)
    for rank in range(size):
        _float_bound([w[rank] for w in used])
    return vectors


def _sum_along(values: Iterable[Number]) -> Number:
    """The sum of ``values`` from left to right, as Dijkstra adds the
    weights along a path, so that a route costs the distance of its end:
    ``sum()`` compensates the rounding of floats (since Python 3.12) and
    can give another float."""
    total: Number = 0
    for x in values:
        total += x
    return total


# --- kernels: no checks, no result, for the internal callers ---------------


class _Run(NamedTuple):
    """What a Dijkstra kernel found, and its work."""

    distance: list[Number]
    predecessor: list[int]
    settled: int
    scanned: int


class _LexicographicRun(NamedTuple):
    distance: list[Vector | None]
    predecessor: list[int]
    settled: int
    scanned: int


class _BellmanFordRun(NamedTuple):
    distance: list[Number]
    predecessor: list[int]
    passes: int
    cycle: NegativeCycle | None


def _dijkstra(
    graph: Digraph,
    weight: Sequence[Number],
    sources: Sequence[int],
    target: int | None,
    skip: Sequence[bool],
    start: Number = 0,
) -> _Run:
    """Dijkstra with a binary heap, without checks: non-negative finite
    weights, existing sources, one ``skip`` flag per arc.

    The sources start at distance ``start``: a search that extends a root
    path starts from its cost, so that a distance adds the weights of the
    whole path from left to right. Stops when ``target`` is settled.
    ``settled`` counts the nodes taken from the heap for good, ``scanned``
    the arcs leaving them (barred arcs included); the target settles but
    is not scanned.
    """
    heads = graph.heads
    out_arcs = graph.out_arcs
    dist: list[Number] = [math.inf] * graph.n
    pred = [-1] * graph.n
    done = [False] * graph.n
    heap: list[tuple[Number, int]] = []
    for s in sources:
        dist[s] = start
        heap.append((start, s))
    heapq.heapify(heap)
    settled = scanned = 0
    while heap:
        d, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        settled += 1
        if u == target:
            break
        out = out_arcs(u)
        scanned += len(out)
        for a in out:
            if skip[a]:
                continue
            v = heads[a]
            new_dist = d + weight[a]
            if new_dist < dist[v]:
                dist[v] = new_dist
                pred[v] = a
                heapq.heappush(heap, (new_dist, v))
    return _Run(dist, pred, settled, scanned)


def _lexicographic_dijkstra(
    graph: Digraph,
    vectors: Sequence[Vector],
    sources: Sequence[int],
    target: int | None,
    skip: Sequence[bool],
) -> _LexicographicRun:
    """Dijkstra on weight vectors, without checks (as :func:`_dijkstra`)."""
    size = len(vectors[0]) if vectors else 1
    zero: Vector = (0,) * size
    dist: list[Vector | None] = [None] * graph.n
    pred = [-1] * graph.n
    done = [False] * graph.n
    heap: list[tuple[Vector, int]] = []
    for s in sources:
        dist[s] = zero
        heap.append((zero, s))
    heapq.heapify(heap)
    settled = scanned = 0
    while heap:
        d, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        settled += 1
        if u == target:
            break
        out = graph.out_arcs(u)
        scanned += len(out)
        for a in out:
            if skip[a]:
                continue
            v = graph.heads[a]
            new_dist = tuple(x + y for x, y in zip(d, vectors[a], strict=True))
            old = dist[v]
            if old is None or new_dist < old:
                dist[v] = new_dist
                pred[v] = a
                heapq.heappush(heap, (new_dist, v))
    return _LexicographicRun(dist, pred, settled, scanned)


def _negative_cycle_from(
    graph: Digraph, weight: Sequence[Number], pred: list[int], start: int
) -> NegativeCycle:
    """Walk back the predecessors from a node relaxed in round n."""
    v = start
    for _ in range(graph.n):
        v = graph.tails[pred[v]]
    arcs = [pred[v]]
    u = graph.tails[pred[v]]
    while u != v:
        arcs.append(pred[u])
        u = graph.tails[pred[u]]
    arcs.reverse()
    return NegativeCycle(tuple(arcs), sum(weight[a] for a in arcs))


def _slack(tolerance: float) -> Number:
    """The tolerance subtracted from a distance: a zero tolerance stays the
    int 0, so that an int distance minus it stays an int, exact, where
    ``- 0.0`` would round it to a float (beyond ``2**53``), or overflow
    (beyond the float range)."""
    return tolerance if tolerance else 0


def _bellman_ford(
    graph: Digraph,
    weight: Sequence[Number],
    sources: Sequence[int] | None,
    tolerance: float,
) -> _BellmanFordRun:
    """Bellman-Ford without checks: finite weights, existing sources.

    Without sources, every node starts at distance 0. ``passes`` counts
    the passes over the arcs. When a negative cycle is found, the
    distances and predecessors are those of the last pass.
    """
    slack = _slack(tolerance)
    if sources is None:
        dist: list[Number] = [0] * graph.n
    else:
        dist = [math.inf] * graph.n
        for s in sources:
            dist[s] = 0
    pred = [-1] * graph.n
    changed = -1
    passes = 0
    for _ in range(graph.n):
        passes += 1
        changed = -1
        for a, (u, v) in enumerate(graph.arcs()):
            if dist[u] != math.inf and dist[u] + weight[a] < dist[v] - slack:
                dist[v] = dist[u] + weight[a]
                pred[v] = a
                changed = v
        if changed == -1:
            break
    cycle = (
        None if changed == -1 else _negative_cycle_from(graph, weight, pred, changed)
    )
    return _BellmanFordRun(dist, pred, passes, cycle)


def _reached(distance: Sequence[Number]) -> frozenset[int]:
    """The nodes at a finite distance."""
    return frozenset(v for v, d in enumerate(distance) if d != math.inf)


def _separating_cut(
    graph: Digraph, nodes: frozenset[int], sources: tuple[int, ...], target: int
) -> SeparatingCut:
    """The cut around ``nodes``, the nodes a complete search reached from
    ``sources``: the arcs that leave it are those the search barred."""
    arcs = tuple(
        a for a, (u, v) in enumerate(graph.arcs()) if u in nodes and v not in nodes
    )
    return SeparatingCut(nodes, sources, target, arcs)


def _unbounded_below(
    graph: Digraph,
    weight: Sequence[Number],
    dist: Sequence[Number],
    cycle: NegativeCycle,
    tolerance: float,
) -> set[int]:
    """The nodes a negative cycle reachable from the sources reaches.

    After the passes of :func:`_bellman_ford`, a node that no negative
    cycle reaches has its exact distance, so an arc that still improves
    leads into the set; each negative cycle keeps such an arc, since the
    improvements around it sum to its weight.
    """
    slack = _slack(tolerance)
    start = {graph.tails[a] for a in cycle.arcs}
    for a, (u, v) in enumerate(graph.arcs()):
        if dist[u] != math.inf and dist[u] + weight[a] < dist[v] - slack:
            start.add(v)
    seen = set(start)
    stack = list(start)
    while stack:
        for a in graph.out_arcs(stack.pop()):
            v = graph.heads[a]
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return seen


# --- public methods ----------------------------------------------------------


def dijkstra(
    graph: Digraph,
    weight: Sequence[Number],
    source: int | Iterable[int],
    target: int | None = None,
    *,
    excluded: Collection[int] = (),
) -> ShortestPaths:
    """Shortest paths with non-negative weights (Dijkstra, binary heap).

    Parameters
    ----------
    graph : Digraph
    weight : sequence of int or float
        One non-negative weight per arc.
    source : int or iterable of int
        One source, or several sources all at distance 0.
    target : int, optional
        Stop as soon as the distance of ``target`` is final. Nodes not yet
        settled then keep a provisional distance, at least the true one.
    excluded : collection of int, optional
        Arcs to ignore, as if they were removed from the graph.

    Returns
    -------
    ShortestPaths
        Status ``optimal``. Counters: ``settled_nodes`` (nodes whose
        distance became final) and ``scanned_arcs`` (arcs leaving them,
        excluded arcs included). No parameters: the graph, the weights,
        the sources, the target and the excluded arcs are the inputs.

    Raises
    ------
    ValueError
        If a weight is negative or not finite, the absolute weights of the
        arcs not excluded sum beyond the float range when one of them is
        not an int (a float sum along a path could overflow; ints sum
        exactly, whatever their size), or a source, the target or an
        excluded arc does not exist.

    Notes
    -----
    Complexity :math:`O((n + m) \\log n)`. A distance adds the weights
    along its path from left to right.
    """
    skip = _skip(graph, excluded)
    _check_nonnegative(graph, weight, skip)
    sources = _source_nodes(graph, source)
    if target is not None:
        _node(graph, target, "target")
    run = _dijkstra(graph, weight, sources, target, skip)
    return ShortestPaths(
        status=Status.OPTIMAL,
        method="dijkstra",
        guarantee=_METHODS["dijkstra"].guarantee,
        counters={"settled_nodes": run.settled, "scanned_arcs": run.scanned},
        sources=sources,
        distance=tuple(run.distance),
        predecessor=tuple(run.predecessor),
        _tails=graph.tails,
        _sources=(graph, tuple(weight), sources, target, frozenset(excluded)),
    )


def lexicographic_dijkstra(
    graph: Digraph,
    weight: Sequence[Sequence[Number]],
    source: int | Iterable[int],
    target: int | None = None,
    *,
    excluded: Collection[int] = (),
) -> LexicographicPaths:
    """Shortest paths for weight vectors compared in lexicographic order.

    Vectors add componentwise and compare lexicographically: the first
    component decides, the next ones break ties. Exact, with no scaling by
    a large constant, which is fragile in floating point.

    Parameters
    ----------
    graph : Digraph
    weight : sequence of sequences of int or float
        One vector per arc, all of the same length, with non-negative,
        finite components.
    source : int or iterable of int
    target : int, optional
        Stop as soon as the distance of ``target`` is final.
    excluded : collection of int, optional
        Arcs to ignore.

    Returns
    -------
    LexicographicPaths
        Status ``optimal``. Counters: ``settled_nodes`` and
        ``scanned_arcs``, as for :func:`dijkstra`.

    Raises
    ------
    ValueError
        If a vector has another length, a component is negative or not
        finite, the components of one rank sum beyond the float range on
        the arcs not excluded when one of them is not an int (a float sum
        along a path could overflow; ints sum exactly), or a source, the
        target or an excluded arc does not exist.

    Notes
    -----
    Dijkstra's algorithm applies because non-negative vectors form an
    ordered monoid under componentwise addition and lexicographic order.
    Complexity :math:`O(k (n + m) \\log n)` for vectors of length ``k``.
    """
    skip = _skip(graph, excluded)
    vectors = _vectors(graph, weight, skip)
    sources = _source_nodes(graph, source)
    if target is not None:
        _node(graph, target, "target")
    run = _lexicographic_dijkstra(graph, vectors, sources, target, skip)
    return LexicographicPaths(
        status=Status.OPTIMAL,
        method="lexicographic_dijkstra",
        guarantee=_METHODS["lexicographic_dijkstra"].guarantee,
        counters={"settled_nodes": run.settled, "scanned_arcs": run.scanned},
        sources=sources,
        distance=tuple(run.distance),
        predecessor=tuple(run.predecessor),
        _tails=graph.tails,
        _sources=(graph, vectors, sources, target, frozenset(excluded)),
    )


def bellman_ford(
    graph: Digraph,
    weight: Sequence[Number],
    source: int | Iterable[int] | None = None,
    *,
    tolerance: float = 0.0,
) -> ShortestPaths:
    """Shortest paths with any weights, or a negative cycle (Bellman-Ford).

    Parameters
    ----------
    graph : Digraph
    weight : sequence of int or float
        One finite weight per arc.
    source : int or iterable of int, optional
        The sources. Without a source, every node starts at distance 0, as
        if a virtual source reached each of them: any negative cycle of the
        graph is then found.
    tolerance : float, optional
        Finite and non-negative. A distance improves only by more than
        ``tolerance``; for float weights, it keeps rounding errors from
        showing a false cycle.

    Returns
    -------
    ShortestPaths
        Status ``optimal`` with exact distances, or ``unbounded`` when a
        cycle of negative weight is reachable from the sources: the
        certificate is that cycle, the nodes it reaches (and those reached
        by any other negative cycle) are at ``-math.inf`` with no
        predecessor, and the other nodes keep their exact distance and
        shortest path. Parameters: ``tolerance``. Counters: ``passes``
        (passes over every arc).

    Raises
    ------
    ValueError
        If a weight is not finite, the tolerance is negative or not finite,
        or a source does not exist. With a weight that is not an int, or a
        positive tolerance, which compares the distances as floats: if the
        absolute weights sum beyond the float range, or ``n`` times ``m``
        times the largest absolute weight is beyond it (on the way to a
        negative cycle, a distance is the sum of a walk of up to ``n m``
        arcs, which could overflow). Int weights with a zero tolerance sum
        and compare exactly, whatever their size.

    Notes
    -----
    Complexity :math:`O(nm)`.
    """
    bound = _check_weights(graph, weight)
    tolerance = float(tolerance)
    if not (math.isfinite(tolerance) and tolerance >= 0):
        raise ValueError(
            f"the tolerance must be finite and non-negative, got {tolerance}"
        )
    if bound is not None or tolerance > 0:
        # Floats are summed, or compared with the tolerance: on the way to
        # a negative cycle, a distance sums a walk of up to n m arcs.
        largest = max((abs(w) for w in weight), default=0)
        if graph.n * graph.m * largest > sys.float_info.max:
            raise ValueError(
                f"the weights are too large for bellman_ford: {graph.n} nodes "
                f"times {graph.m} arcs times the largest absolute weight is "
                "beyond the float range"
            )
    if source is None:
        sources = tuple(range(graph.n))
        run = _bellman_ford(graph, weight, None, tolerance)
    else:
        sources = _source_nodes(graph, source)
        run = _bellman_ford(graph, weight, sources, tolerance)
    dist, pred = run.distance, run.predecessor
    status = Status.OPTIMAL
    if run.cycle is not None:
        status = Status.UNBOUNDED
        for v in _unbounded_below(graph, weight, dist, run.cycle, tolerance):
            dist[v] = -math.inf
            pred[v] = -1
    return ShortestPaths(
        status=status,
        method="bellman_ford",
        guarantee=_METHODS["bellman_ford"].guarantee,
        parameters={"tolerance": tolerance},
        counters={"passes": run.passes},
        certificate=run.cycle,
        sources=sources,
        distance=tuple(dist),
        predecessor=tuple(pred),
        _tails=graph.tails,
        _sources=(graph, tuple(weight), sources),
    )
