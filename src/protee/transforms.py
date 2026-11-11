# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Reversible transformations of flow problems.

Each function returns an object whose ``problem`` is the transformed
:class:`~protee.flow.FlowProblem` and whose ``restore_flow`` maps a flow of
that problem back to the original arcs. Solving the transformed problem
and restoring gives an optimal flow of the original one: the
transformations are support functions of the methods, applied and undone
explicitly. When the node potentials carry over as well,
``restore_potentials`` is provided.

- :func:`remove_lower_bounds`: ``x = lower + y``;
- :func:`split_nodes`: bounds and costs on nodes, as internal arcs;
- :func:`subdivide_arcs`: a middle node on chosen arcs (no parallel arcs
  or loops left, for methods that do not accept them);
- :func:`add_super_terminals`: a super-source, a super-sink and a return
  arc, which close a graph into a circulation;
- :func:`contract_paths`: degree-2 paths contracted into single arcs.

Provisional API (until version 1.0).
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from protee import structure
from protee.flow._normal import shifted_supply
from protee.flow._problem import FlowProblem
from protee.graph import Digraph

__all__ = [
    "LowerBoundShift",
    "NodeSplit",
    "PathContraction",
    "Subdivision",
    "SuperTerminals",
    "add_super_terminals",
    "contract_paths",
    "remove_lower_bounds",
    "split_nodes",
    "subdivide_arcs",
]

type Number = int | float
type Bounds = tuple[int, int | None]


def _labels(graph: Digraph, extra: Sequence[str]) -> tuple[str, ...] | None:
    if graph.labels is None:
        return None
    taken = set(graph.labels)
    out = []
    for label in extra:
        while label in taken:
            label = f"_{label}"
        taken.add(label)
        out.append(label)
    return graph.labels + tuple(out)


@dataclass(frozen=True, slots=True)
class LowerBoundShift:
    """Result of :func:`remove_lower_bounds`.

    Attributes
    ----------
    original : FlowProblem
    problem : FlowProblem
        Lower bounds 0, upper bounds ``upper - lower``, supplies adjusted.
    offset : int or float
        ``sum(cost * lower)``: original objective minus transformed one.
    """

    original: FlowProblem
    problem: FlowProblem
    offset: Number

    def restore_flow(self, flow: Sequence[int]) -> tuple[int, ...]:
        """``lower + y``."""
        return tuple(lo + y for lo, y in zip(self.original.lower, flow, strict=True))

    def restore_potentials(self, potentials: Sequence[Number]) -> tuple[Number, ...]:
        """Unchanged: the shift keeps every reduced cost."""
        return tuple(potentials)


def remove_lower_bounds(problem: FlowProblem) -> LowerBoundShift:
    """Substitute ``x = lower + y``, so that every lower bound becomes 0."""
    g = problem.graph
    supply = shifted_supply(problem)
    upper = tuple(
        None if hi is None else hi - lo
        for lo, hi in zip(problem.lower, problem.upper, strict=True)
    )
    shifted = FlowProblem(
        g, upper=upper, cost=problem.cost, supply=supply, sense=problem.sense
    )
    return LowerBoundShift(problem, shifted, problem.objective(problem.lower))


@dataclass(frozen=True, slots=True)
class NodeSplit:
    """Result of :func:`split_nodes`.

    Node ``v`` becomes an entry ``v``, which receives the arcs entering
    ``v`` and its supply, and an exit ``n + v``, which emits the arcs leaving
    ``v``. The internal arc ``m + v`` (entry to exit) carries the outflow of
    ``v`` and holds its node bounds and cost.

    Attributes
    ----------
    original : FlowProblem
    problem : FlowProblem
    """

    original: FlowProblem
    problem: FlowProblem

    def restore_flow(self, flow: Sequence[int]) -> tuple[int, ...]:
        """Flows of the original arcs (the first ``m`` arcs)."""
        return tuple(flow[: self.original.graph.m])

    def node_flow(self, flow: Sequence[int]) -> tuple[int, ...]:
        """Flow through each original node: its internal arc."""
        m = self.original.graph.m
        return tuple(flow[m : m + self.original.graph.n])


def split_nodes(
    problem: FlowProblem,
    *,
    lower: Sequence[int] | None = None,
    upper: Sequence[int | None] | None = None,
    cost: Sequence[Number] | None = None,
) -> NodeSplit:
    """Put bounds and costs on the flow through nodes (node splitting).

    Parameters
    ----------
    problem : FlowProblem
    lower, upper : sequence, optional
        Bounds on the outflow of each node; 0 and no bound by default.
    cost : sequence of int or float, optional
        Cost per unit of outflow; 0 by default.

    Returns
    -------
    NodeSplit
    """
    g = problem.graph
    n = g.n
    tails = tuple(n + t for t in g.tails) + tuple(range(n))
    heads = g.heads + tuple(n + v for v in range(n))
    labels = _labels(g, [f"{g.label(v)}:out" for v in range(n)])
    split = Digraph(2 * n, tails, heads, labels)
    new = FlowProblem(
        split,
        lower=tuple(problem.lower) + tuple((0,) * n if lower is None else lower),
        upper=tuple(problem.upper) + tuple((None,) * n if upper is None else upper),
        cost=tuple(problem.cost) + tuple((0,) * n if cost is None else cost),
        supply=tuple(problem.supply) + (0,) * n,
        sense=problem.sense,
    )
    return NodeSplit(problem, new)


@dataclass(frozen=True, slots=True)
class Subdivision:
    """Result of :func:`subdivide_arcs`.

    Arc ``a = (u, v)`` of ``arcs`` becomes ``(u, w)``, same index, bounds and
    cost, then ``(w, v)``, appended with the same bounds and cost 0, where
    ``w`` is a new node.

    Attributes
    ----------
    original : FlowProblem
    problem : FlowProblem
    arcs : tuple of int
        The subdivided arcs, in the order of their new nodes.
    """

    original: FlowProblem
    problem: FlowProblem
    arcs: tuple[int, ...]

    def restore_flow(self, flow: Sequence[int]) -> tuple[int, ...]:
        """Flows of the original arcs (the first ``m`` arcs)."""
        return tuple(flow[: self.original.graph.m])

    def restore_potentials(self, potentials: Sequence[Number]) -> tuple[Number, ...]:
        """Potentials of the original nodes: the two halves of an arc add up
        to its reduced cost, with the same sign conditions."""
        return tuple(potentials[: self.original.graph.n])


def subdivide_arcs(
    problem: FlowProblem, arcs: Iterable[int] | None = None
) -> Subdivision:
    """Insert a middle node on arcs, removing parallel arcs and loops.

    Parameters
    ----------
    problem : FlowProblem
    arcs : iterable of int, optional
        Arcs to subdivide. By default, the loops and every arc that has a
        parallel arc (same tail and head).

    Returns
    -------
    Subdivision
    """
    g = problem.graph
    if arcs is None:
        count = Counter(g.arcs())
        chosen = tuple(
            a for a, (t, h) in enumerate(g.arcs()) if t == h or count[t, h] > 1
        )
    else:
        chosen = tuple(dict.fromkeys(arcs))
        for a in chosen:
            if not 0 <= a < g.m:
                raise ValueError(f"arc {a} is outside 0..{g.m - 1}")
    n = g.n
    tails = list(g.tails)
    heads = list(g.heads)
    for i, a in enumerate(chosen):
        w = n + i
        tails.append(w)
        heads.append(g.heads[a])
        heads[a] = w
    labels = _labels(
        g, [f"{g.label(g.tails[a])}~{g.label(g.heads[a])}:{a}" for a in chosen]
    )
    graph = Digraph(n + len(chosen), tuple(tails), tuple(heads), labels)
    new = FlowProblem(
        graph,
        lower=tuple(problem.lower) + tuple(problem.lower[a] for a in chosen),
        upper=tuple(problem.upper) + tuple(problem.upper[a] for a in chosen),
        cost=tuple(problem.cost) + (0,) * len(chosen),
        supply=tuple(problem.supply) + (0,) * len(chosen),
        sense=problem.sense,
    )
    return Subdivision(problem, new, chosen)


@dataclass(frozen=True, slots=True)
class SuperTerminals:
    """Result of :func:`add_super_terminals`.

    Node ``n`` is the super-source and ``n + 1`` the super-sink. Arcs
    ``m .. m + len(sources) - 1`` go from the super-source to each source,
    the next ones from each sink to the super-sink, and the last arc
    returns from the super-sink to the super-source.

    Attributes
    ----------
    original : FlowProblem
    problem : FlowProblem
    sources, sinks : tuple of int
    """

    original: FlowProblem
    problem: FlowProblem
    sources: tuple[int, ...]
    sinks: tuple[int, ...]

    def restore_flow(self, flow: Sequence[int]) -> tuple[int, ...]:
        """Flows of the original arcs (the first ``m`` arcs)."""
        return tuple(flow[: self.original.graph.m])

    def restore_potentials(self, potentials: Sequence[Number]) -> tuple[Number, ...]:
        """Potentials of the original nodes: added arcs and nodes leave the
        reduced costs of the original arcs unchanged."""
        return tuple(potentials[: self.original.graph.n])

    def source_flow(self, flow: Sequence[int]) -> tuple[int, ...]:
        """Flow from the super-source into each source."""
        m = self.original.graph.m
        return tuple(flow[m : m + len(self.sources)])

    def sink_flow(self, flow: Sequence[int]) -> tuple[int, ...]:
        """Flow from each sink into the super-sink."""
        start = self.original.graph.m + len(self.sources)
        return tuple(flow[start : start + len(self.sinks)])

    def through_flow(self, flow: Sequence[int]) -> int:
        """Flow on the return arc."""
        return flow[-1]


def add_super_terminals(
    problem: FlowProblem,
    sources: Iterable[int],
    sinks: Iterable[int],
    *,
    source_bounds: Sequence[Bounds] | None = None,
    sink_bounds: Sequence[Bounds] | None = None,
    through: Bounds = (0, None),
) -> SuperTerminals:
    """Join a super-source to sources, sinks to a super-sink, and close.

    The return arc from the super-sink to the super-source, bounded by
    ``through``, turns the graph into a circulation: each unit of flow
    starts at one source and ends at one sink. With ``through = (1, 1)``
    and source and sink bounds ``(0, 1)``, exactly one unit goes from one
    of the sources to one of the sinks; disconnected parts of the graph
    are closed into a single circulation.

    Parameters
    ----------
    problem : FlowProblem
    sources, sinks : iterable of int
    source_bounds, sink_bounds : sequence of (int, int or None), optional
        Bounds of each added arc; ``(0, None)`` by default.
    through : (int, int or None), optional
        Bounds of the return arc; ``(0, None)`` by default.

    Returns
    -------
    SuperTerminals
    """
    g = problem.graph
    src = tuple(sources)
    snk = tuple(sinks)
    n = g.n
    s, t = n, n + 1
    sb = tuple(source_bounds) if source_bounds is not None else ((0, None),) * len(src)
    tb = tuple(sink_bounds) if sink_bounds is not None else ((0, None),) * len(snk)
    if len(sb) != len(src) or len(tb) != len(snk):
        raise ValueError("one pair of bounds per source and per sink")
    tails = g.tails + (s,) * len(src) + snk + (t,)
    heads = g.heads + src + (t,) * len(snk) + (s,)
    graph = Digraph(n + 2, tails, heads, _labels(g, ["super-source", "super-sink"]))
    bounds = [*sb, *tb, through]
    new = FlowProblem(
        graph,
        lower=tuple(problem.lower) + tuple(lo for lo, _ in bounds),
        upper=tuple(problem.upper) + tuple(hi for _, hi in bounds),
        cost=tuple(problem.cost) + (0,) * len(bounds),
        supply=tuple(problem.supply) + (0, 0),
        sense=problem.sense,
    )
    return SuperTerminals(problem, new, src, snk)


@dataclass(frozen=True, slots=True)
class PathContraction:
    """Result of :func:`contract_paths`.

    Attributes
    ----------
    original : FlowProblem
    problem : FlowProblem
        One arc per degree-2 path: lower bound the largest lower bound of
        the path, upper bound the smallest upper bound, cost the sum.
    contraction : protee.structure.PathContraction
        The contracted structure (paths, node correspondence).
    """

    original: FlowProblem
    problem: FlowProblem
    contraction: structure.PathContraction

    def restore_flow(self, flow: Sequence[int]) -> tuple[int, ...]:
        """The flow of each contracted arc on every arc of its path."""
        return self.contraction.expand(flow)


def _min_upper(values: list[int | None]) -> int | None:
    finite = [v for v in values if v is not None]
    return min(finite) if finite else None


def contract_paths(
    problem: FlowProblem, *, protected: Iterable[int] = ()
) -> PathContraction:
    """Contract the series degree-2 paths of a flow problem.

    Nodes with a non-zero supply stay branch vertices. In series mode, the
    flow is the same on every arc of a path, so the contraction is exact.
    The potentials of interior nodes are not restored: the rule to expand
    them is still open (any value between the bounds of the path's reduced
    costs is valid).

    Parameters
    ----------
    problem : FlowProblem
    protected : iterable of int, optional
        Further nodes to keep.

    Returns
    -------
    PathContraction

    Raises
    ------
    ValueError
        If the bounds along a path leave no feasible value: the original
        problem is then infeasible.
    """
    keep = set(protected) | {v for v, b in enumerate(problem.supply) if b}
    c = structure.contract_paths(
        problem.graph,
        protected=keep,
        mode="series",
        columns={
            "lower": (problem.lower, max),
            "upper": (problem.upper, _min_upper),
            "cost": (problem.cost, sum),
        },
    )
    lower = cast(tuple[int, ...], c.columns["lower"])
    upper = cast(tuple[int | None, ...], c.columns["upper"])
    cost = cast(tuple[Number, ...], c.columns["cost"])
    for i, (lo, hi) in enumerate(zip(lower, upper, strict=True)):
        if hi is not None and lo > hi:
            raise ValueError(
                f"path {c.paths[i]} has lower bound {lo} above upper bound {hi}: infeasible"
            )
    supply = tuple(problem.supply[v] for v in c.nodes)
    new = FlowProblem(
        c.graph,
        lower=lower,
        upper=upper,
        cost=cost,
        supply=supply,
        sense=problem.sense,
    )
    return PathContraction(problem, new, c)
