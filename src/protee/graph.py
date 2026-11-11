# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Immutable directed multigraph.

A :class:`Digraph` holds the topology only: nodes ``0..n-1``, arcs given by
their tail and head, optional node labels. Parallel arcs and loops are
allowed. Quantities attached to arcs or nodes (bounds, costs, supplies,
geometry) live in the problems that use the graph, so that one structure
can serve many metrics.

Provisional API (until version 1.0).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

__all__ = ["Digraph"]


def _csr(n: int, keys: Sequence[int]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Compressed rows: arcs grouped by ``keys[arc]``, in increasing arc order."""
    start = [0] * (n + 1)
    for k in keys:
        start[k + 1] += 1
    for v in range(n):
        start[v + 1] += start[v]
    fill = start[:-1].copy()
    order = [0] * len(keys)
    for arc, k in enumerate(keys):
        order[fill[k]] = arc
        fill[k] += 1
    return tuple(start), tuple(order)


@dataclass(frozen=True, slots=True)
class Digraph:
    """Directed multigraph with nodes ``0..n-1``.

    Parameters
    ----------
    n : int
        Number of nodes.
    tails, heads : tuple of int
        ``tails[a]`` and ``heads[a]`` are the endpoints of arc ``a``.
    labels : tuple of str, optional
        One distinct label per node.

    Raises
    ------
    ValueError
        If the sizes disagree, a node is out of range or labels repeat.

    Examples
    --------
    >>> g = Digraph.from_arcs(3, [(0, 1), (1, 2), (2, 0)])
    >>> g.m, g.out_arcs(0), g.in_arcs(0)
    (3, (0,), (2,))
    """

    n: int
    tails: tuple[int, ...]
    heads: tuple[int, ...]
    labels: tuple[str, ...] | None = None
    _out_start: tuple[int, ...] = field(init=False, repr=False, compare=False)
    _out: tuple[int, ...] = field(init=False, repr=False, compare=False)
    _in_start: tuple[int, ...] = field(init=False, repr=False, compare=False)
    _in: tuple[int, ...] = field(init=False, repr=False, compare=False)
    _index: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValueError(f"the number of nodes must be non-negative, got {self.n}")
        if len(self.tails) != len(self.heads):
            raise ValueError("tails and heads must have the same length")
        for a, (t, h) in enumerate(zip(self.tails, self.heads, strict=True)):
            if not (0 <= t < self.n and 0 <= h < self.n):
                raise ValueError(
                    f"arc {a} ({t}, {h}) has an endpoint outside 0..{self.n - 1}"
                )
        index: dict[str, int] = {}
        if self.labels is not None:
            if len(self.labels) != self.n:
                raise ValueError("there must be one label per node")
            for v, label in enumerate(self.labels):
                if label in index:
                    raise ValueError(f"label {label!r} is repeated")
                index[label] = v
        out_start, out = _csr(self.n, self.tails)
        in_start, in_ = _csr(self.n, self.heads)
        object.__setattr__(self, "_out_start", out_start)
        object.__setattr__(self, "_out", out)
        object.__setattr__(self, "_in_start", in_start)
        object.__setattr__(self, "_in", in_)
        object.__setattr__(self, "_index", index)

    @classmethod
    def from_arcs(
        cls,
        n: int,
        arcs: Iterable[tuple[int, int]],
        labels: Sequence[str] | None = None,
    ) -> Digraph:
        """Build a graph from ``(tail, head)`` pairs.

        Parameters
        ----------
        n : int
            Number of nodes.
        arcs : iterable of (int, int)
            The arcs, numbered in iteration order.
        labels : sequence of str, optional
            One distinct label per node.

        Returns
        -------
        Digraph
        """
        pairs = list(arcs)
        return cls(
            n,
            tuple(t for t, _ in pairs),
            tuple(h for _, h in pairs),
            None if labels is None else tuple(labels),
        )

    @property
    def m(self) -> int:
        """Number of arcs."""
        return len(self.tails)

    def arc(self, a: int) -> tuple[int, int]:
        """Return ``(tail, head)`` of arc ``a``."""
        return self.tails[a], self.heads[a]

    def arcs(self) -> Iterable[tuple[int, int]]:
        """Iterate over the ``(tail, head)`` pairs, in arc order."""
        return zip(self.tails, self.heads, strict=True)

    def out_arcs(self, v: int) -> tuple[int, ...]:
        """Arcs leaving node ``v``, in increasing order."""
        return self._out[self._out_start[v] : self._out_start[v + 1]]

    def in_arcs(self, v: int) -> tuple[int, ...]:
        """Arcs entering node ``v``, in increasing order."""
        return self._in[self._in_start[v] : self._in_start[v + 1]]

    def out_degree(self, v: int) -> int:
        """Number of arcs leaving ``v`` (a loop counts once)."""
        return self._out_start[v + 1] - self._out_start[v]

    def in_degree(self, v: int) -> int:
        """Number of arcs entering ``v`` (a loop counts once)."""
        return self._in_start[v + 1] - self._in_start[v]

    def degree(self, v: int) -> int:
        """Number of arc ends at ``v`` (a loop counts twice)."""
        return self.out_degree(v) + self.in_degree(v)

    def label(self, v: int) -> str:
        """Label of node ``v``, or ``str(v)`` when the graph has no labels."""
        return str(v) if self.labels is None else self.labels[v]

    def node(self, label: str) -> int:
        """Index of the node carrying ``label``.

        Raises
        ------
        KeyError
            If no node carries this label.
        """
        if self.labels is None:
            try:
                v = int(label)
            except ValueError:
                raise KeyError(label) from None
            if not 0 <= v < self.n:
                raise KeyError(label)
            return v
        return self._index[label]

    def reverse(self) -> Digraph:
        """Same nodes and arc numbering, every arc reversed."""
        return Digraph(self.n, self.heads, self.tails, self.labels)
