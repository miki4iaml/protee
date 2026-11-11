# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Structure of a :class:`~protee.graph.Digraph`, computed once.

- weak and strong components;
- degree-2 paths and their contraction, with per-attribute aggregation
  and expansion back to the original arcs;
- spanning forest, fundamental cycles, cyclomatic number.

Terms follow Diestel (*Graph Theory*): a *branch vertex* has a degree other
than 2; the interior nodes of a *degree-2 path* have degree 2.

Provisional API (until version 1.0).
"""

from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from protee.graph import Digraph

__all__ = [
    "PathContraction",
    "SignedCycle",
    "SpanningForest",
    "contract_paths",
    "cyclomatic_number",
    "degree2_paths",
    "fundamental_cycles",
    "interior_nodes",
    "spanning_forest",
    "strong_components",
    "weak_components",
]

type Mode = Literal["series", "two_way"]


def weak_components(graph: Digraph) -> tuple[int, ...]:
    """Component of each node, ignoring arc directions.

    Components are numbered ``0, 1, …`` in the order of their smallest node.
    """
    comp = [-1] * graph.n
    count = 0
    for start in range(graph.n):
        if comp[start] != -1:
            continue
        comp[start] = count
        queue = deque((start,))
        while queue:
            u = queue.popleft()
            for a in graph.out_arcs(u):
                v = graph.heads[a]
                if comp[v] == -1:
                    comp[v] = count
                    queue.append(v)
            for a in graph.in_arcs(u):
                v = graph.tails[a]
                if comp[v] == -1:
                    comp[v] = count
                    queue.append(v)
        count += 1
    return tuple(comp)


def strong_components(graph: Digraph) -> tuple[int, ...]:
    """Strongly connected component of each node (Tarjan, iterative).

    Components are numbered in reverse topological order of the
    condensation: an arc between two components goes from a higher number
    to a lower one.
    """
    n = graph.n
    index = [-1] * n
    low = [0] * n
    comp = [-1] * n
    on_stack = [False] * n
    stack: list[int] = []
    counter = 0
    count = 0
    for root in range(n):
        if index[root] != -1:
            continue
        work = [(root, 0)]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        while work:
            u, i = work[-1]
            arcs = graph.out_arcs(u)
            if i < len(arcs):
                work[-1] = (u, i + 1)
                v = graph.heads[arcs[i]]
                if index[v] == -1:
                    index[v] = low[v] = counter
                    counter += 1
                    stack.append(v)
                    on_stack[v] = True
                    work.append((v, 0))
                elif on_stack[v]:
                    low[u] = min(low[u], index[v])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[u])
            if low[u] == index[u]:
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    comp[w] = count
                    if w == u:
                        break
                count += 1
    return tuple(comp)


def _pairing(graph: Digraph, v: int, mode: Mode) -> dict[int, int] | None:
    """Map each arc entering interior node ``v`` to the arc that continues it.

    ``None`` when ``v`` is a branch vertex for this mode.
    """
    ins, outs = graph.in_arcs(v), graph.out_arcs(v)
    if any(graph.heads[a] == v for a in outs):
        return None  # a loop
    if mode == "series":
        if len(ins) == 1 and len(outs) == 1:
            return {ins[0]: outs[0]}
        return None
    sources = [graph.tails[a] for a in ins]
    targets = [graph.heads[a] for a in outs]
    neighbors = set(sources) | set(targets)
    if (
        len(neighbors) != 2
        or len(set(sources)) != len(sources)
        or len(set(targets)) != len(targets)
    ):
        return None
    if len(ins) != len(outs) or not ins:
        return None
    pairs = {}
    for a in ins:
        # Sources and targets are distinct and both lie in the two
        # neighbors, in equal numbers: exactly one arc leaves towards the
        # other neighbor.
        other = next(w for w in neighbors if w != graph.tails[a])
        pairs[a] = next(b for b in outs if graph.heads[b] == other)
    return pairs


def interior_nodes(
    graph: Digraph, *, protected: Iterable[int] = (), mode: Mode = "series"
) -> frozenset[int]:
    """Nodes that a degree-2 path goes through.

    Parameters
    ----------
    graph : Digraph
    protected : iterable of int, optional
        Nodes that must stay branch vertices (terminals, nodes of a turn
        ban, changes of attributes…).
    mode : {"series", "two_way"}, optional
        ``"series"``: one arc in, one arc out; flows are equal on both, so
        contraction is exact for flows. ``"two_way"``: two neighbors, with
        one arc or a pair of opposite arcs towards each; a U-turn at the
        node is lost, so contraction is exact for shortest paths with
        non-negative costs, not for flows.

    Returns
    -------
    frozenset of int
    """
    keep = set(protected)
    return frozenset(
        v
        for v in range(graph.n)
        if v not in keep and _pairing(graph, v, mode) is not None
    )


def degree2_paths(
    graph: Digraph, *, protected: Iterable[int] = (), mode: Mode = "series"
) -> tuple[tuple[int, ...], ...]:
    """Partition of the arcs into maximal paths through interior nodes.

    Every arc belongs to exactly one path; an arc between two branch
    vertices is a path of one arc. A cycle made only of interior nodes is
    cut at its smallest node, which becomes a branch vertex.

    Parameters
    ----------
    graph : Digraph
    protected, mode
        See :func:`interior_nodes`.

    Returns
    -------
    tuple of tuple of int
        The arcs of each path, in order. Paths are ordered by their first
        arc.
    """
    keep = set(protected)
    follow: dict[int, int] = {}
    interior = set()
    for v in range(graph.n):
        if v in keep:
            continue
        pairs = _pairing(graph, v, mode)
        if pairs is not None:
            interior.add(v)
            follow.update(pairs)
    seen = [False] * graph.m
    paths: list[tuple[int, ...]] = []

    def walk(first: int) -> None:
        path = [first]
        seen[first] = True
        a = first
        while graph.heads[a] in interior and (b := follow[a]) != first and not seen[b]:
            path.append(b)
            seen[b] = True
            a = b
        paths.append(tuple(path))

    for a in range(graph.m):
        if not seen[a] and graph.tails[a] not in interior:
            walk(a)
    # Cycles of interior nodes only: start at the arc leaving the smallest node.
    for a in sorted(range(graph.m), key=lambda b: (graph.tails[b], b)):
        if not seen[a]:
            walk(a)
    paths.sort(key=lambda p: p[0])
    return tuple(paths)


@dataclass(frozen=True, slots=True)
class PathContraction:
    """A graph whose degree-2 paths are contracted into single arcs.

    Attributes
    ----------
    graph : Digraph
        The contracted graph; its labels are those of the kept nodes.
    nodes : tuple of int
        Original node of each node of the contracted graph.
    paths : tuple of tuple of int
        Original arcs of each arc of the contracted graph, in order.
    arc_of : tuple of int
        Contracted arc of each original arc.
    columns : mapping of str to tuple
        Aggregated attribute columns, one value per contracted arc.
    """

    graph: Digraph
    nodes: tuple[int, ...]
    paths: tuple[tuple[int, ...], ...]
    arc_of: tuple[int, ...]
    columns: Mapping[str, tuple[object, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def expand[T](self, values: Sequence[T]) -> tuple[T, ...]:
        """Give each original arc the value of its contracted arc.

        Exact for flows in ``"series"`` mode, where the flow is the same on
        every arc of a path.
        """
        if len(values) != self.graph.m:
            raise ValueError(f"expected {self.graph.m} values, got {len(values)}")
        return tuple(values[c] for c in self.arc_of)


def contract_paths(
    graph: Digraph,
    *,
    protected: Iterable[int] = (),
    mode: Mode = "series",
    columns: Mapping[str, tuple[Sequence[Any], Callable[[list[Any]], object]]]
    | None = None,
) -> PathContraction:
    """Contract every degree-2 path into one arc.

    Parameters
    ----------
    graph : Digraph
    protected, mode
        See :func:`interior_nodes`.
    columns : mapping, optional
        ``name -> (values, reducer)``: one value per original arc, and a
        function that turns the list of values along a path, in order, into
        the value of the contracted arc (``sum`` for lengths and times,
        ``min`` for capacities and gauges, a concatenation for geometries
        and identifiers…).

    Returns
    -------
    PathContraction

    Examples
    --------
    >>> g = Digraph.from_arcs(4, [(0, 1), (1, 2), (2, 3)])
    >>> c = contract_paths(g, columns={"length": ((2, 3, 4), sum)})
    >>> c.graph.m, c.paths, dict(c.columns)
    (1, ((0, 1, 2),), {'length': (9,)})
    """
    paths = degree2_paths(graph, protected=protected, mode=mode)
    ends = set()
    for p in paths:
        ends.add(graph.tails[p[0]])
        ends.add(graph.heads[p[-1]])
    interior = {graph.heads[a] for p in paths for a in p[:-1]}
    kept = sorted(v for v in range(graph.n) if v not in interior or v in ends)
    new_index = {v: i for i, v in enumerate(kept)}
    tails = tuple(new_index[graph.tails[p[0]]] for p in paths)
    heads = tuple(new_index[graph.heads[p[-1]]] for p in paths)
    labels = None if graph.labels is None else tuple(graph.labels[v] for v in kept)
    arc_of = [0] * graph.m
    for c, p in enumerate(paths):
        for a in p:
            arc_of[a] = c
    aggregated: dict[str, tuple[object, ...]] = {}
    for name, (values, reducer) in (columns or {}).items():
        if len(values) != graph.m:
            raise ValueError(
                f"column {name!r}: expected {graph.m} values, got {len(values)}"
            )
        aggregated[name] = tuple(reducer([values[a] for a in p]) for p in paths)
    return PathContraction(
        Digraph(len(kept), tails, heads, labels),
        tuple(kept),
        paths,
        tuple(arc_of),
        MappingProxyType(aggregated),
    )


@dataclass(frozen=True, slots=True)
class SpanningForest:
    """Spanning tree of each weak component, arc directions ignored.

    Attributes
    ----------
    roots : tuple of int
        One root per component.
    parent_arc : tuple of int
        Arc joining each node to its parent, ``-1`` for a root.
    parent : tuple of int
        Parent of each node, ``-1`` for a root.
    depth : tuple of int
        Distance to the root, in arcs.
    """

    roots: tuple[int, ...]
    parent_arc: tuple[int, ...]
    parent: tuple[int, ...]
    depth: tuple[int, ...]

    @property
    def tree_arcs(self) -> frozenset[int]:
        """Arcs of the forest."""
        return frozenset(a for a in self.parent_arc if a != -1)


def spanning_forest(graph: Digraph, roots: Iterable[int] = ()) -> SpanningForest:
    """Breadth-first spanning forest of the underlying undirected multigraph.

    Parameters
    ----------
    graph : Digraph
    roots : iterable of int, optional
        Preferred roots, used in order; the smallest unreached node roots
        each remaining component.

    Returns
    -------
    SpanningForest
    """
    n = graph.n
    parent_arc = [-1] * n
    parent = [-1] * n
    depth = [-1] * n
    found = []
    for start in [*roots, *range(n)]:
        if depth[start] != -1:
            continue
        found.append(start)
        depth[start] = 0
        queue = deque((start,))
        while queue:
            u = queue.popleft()
            for a in (*graph.out_arcs(u), *graph.in_arcs(u)):
                v = graph.heads[a] if graph.tails[a] == u else graph.tails[a]
                if depth[v] == -1:
                    depth[v] = depth[u] + 1
                    parent[v] = u
                    parent_arc[v] = a
                    queue.append(v)
    return SpanningForest(tuple(found), tuple(parent_arc), tuple(parent), tuple(depth))


@dataclass(frozen=True, slots=True)
class SignedCycle:
    """A cycle of the underlying undirected graph, with arc orientations.

    Attributes
    ----------
    arcs : tuple of int
        The arcs, in the order of a traversal.
    signs : tuple of int
        ``+1`` when the traversal follows the arc, ``-1`` when it goes
        against it: the incidence vector of the cycle.
    """

    arcs: tuple[int, ...]
    signs: tuple[int, ...]


def fundamental_cycles(
    graph: Digraph, forest: SpanningForest | None = None
) -> tuple[SignedCycle, ...]:
    """Fundamental cycle basis: one cycle per arc outside the forest.

    Each cycle is traversed along its non-forest arc ``a = (u, v)``, then
    back from ``v`` to ``u`` through the forest. A loop is a cycle of one
    arc. The cycles form a basis of the cycle space; there are
    :func:`cyclomatic_number` of them.

    Parameters
    ----------
    graph : Digraph
    forest : SpanningForest, optional
        Defaults to :func:`spanning_forest`.

    Returns
    -------
    tuple of SignedCycle
        In the order of the non-forest arcs.
    """
    forest = forest or spanning_forest(graph)
    tree = forest.tree_arcs
    cycles = []
    for a in range(graph.m):
        if a in tree:
            continue
        u, v = graph.tails[a], graph.heads[a]
        # Paths from v and from u up to their common ancestor.
        up_v: list[int] = []
        up_u: list[int] = []
        x, y = v, u
        while x != y:
            if forest.depth[x] >= forest.depth[y]:
                up_v.append(x)
                x = forest.parent[x]
            else:
                up_u.append(y)
                y = forest.parent[y]
        arcs = [a]
        signs = [1]
        for node in up_v:  # from v up to the apex: node -> parent
            b = forest.parent_arc[node]
            arcs.append(b)
            signs.append(1 if graph.tails[b] == node else -1)
        for node in reversed(up_u):  # from the apex down to u: parent -> node
            b = forest.parent_arc[node]
            arcs.append(b)
            signs.append(1 if graph.heads[b] == node else -1)
        cycles.append(SignedCycle(tuple(arcs), tuple(signs)))
    return tuple(cycles)


def cyclomatic_number(graph: Digraph) -> int:
    """``m - n + c``: dimension of the cycle space (``c`` weak components)."""
    comps = weak_components(graph)
    return graph.m - graph.n + (max(comps) + 1 if comps else 0)
