# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Primal network simplex with strongly feasible spanning trees.

Follows Ahuja, Magnanti and Orlin, *Network Flows* (1993), chapter 11:

- an artificial root joined to every node by an artificial arc of large
  cost gives the initial strongly feasible tree (big-M start);
- the leaving arc is the last blocking arc met when the pivot cycle is
  traversed from its apex along its orientation (Cunningham's rule), which
  keeps the tree strongly feasible and rules out cycling whatever the
  entering rule;
- entering arc by Dantzig's rule (most violating arc) or by block search
  (the most violating arc of the first block that has one).

The state survives a change of costs: the tree stays primal feasible, the
potentials are recomputed and pivoting resumes (warm start).
"""

import math
from collections.abc import Sequence
from typing import Literal

from protee.flow._normal import Normal, tolerance_for

type Number = int | float
type PivotRule = Literal["block_search", "dantzig"]

TREE, LOWER, UPPER = 0, 1, -1


class NetworkSimplex:
    """Network simplex state on a problem in standard form."""

    def __init__(self, normal: Normal, pivot_rule: PivotRule = "block_search") -> None:
        if pivot_rule not in ("block_search", "dantzig"):
            raise ValueError(
                f"unknown pivot rule {pivot_rule!r}; choose 'block_search' or 'dantzig'"
            )
        self.pivot_rule = pivot_rule
        n, m = normal.n, normal.m
        self.n, self.m = n, m
        root = n
        self.root = root
        supply = normal.supply
        art_cap = sum(abs(b) for b in supply) + sum(normal.cap) + 1
        self.tail = list(normal.tails) + [0] * n
        self.head = list(normal.heads) + [0] * n
        self.cap = list(normal.cap) + [art_cap] * n
        self.flow = [0] * (m + n)
        self.state = [LOWER] * m + [TREE] * n
        self.cost: list[Number] = [0] * (m + n)
        self.parent = [root] * n + [-1]
        self.pred = [m + v for v in range(n)] + [-1]
        self.up = [True] * n + [False]
        self.depth = [1] * n + [0]
        self.children: list[list[int]] = [[] for _ in range(n)] + [list(range(n))]
        for v, b in enumerate(supply):
            a = m + v
            if b >= 0:
                self.tail[a], self.head[a], self.flow[a] = v, root, b
            else:
                self.tail[a], self.head[a], self.flow[a] = root, v, -b
                self.up[v] = False
        self.potential: list[Number] = [0] * (n + 1)
        self.tolerance = 0.0
        self.block = max(10, math.isqrt(m + n) + 1)
        self.next_arc = 0
        self.counters = {"pivots": 0, "degenerate_pivots": 0, "bound_flips": 0}
        self.set_costs(normal.cost)

    # -- costs and potentials -------------------------------------------

    def set_costs(self, cost: Sequence[Number]) -> None:
        """Install new real arc costs; recompute artificial costs and potentials."""
        m, n = self.m, self.n
        self.cost[:m] = cost
        biggest = max((abs(c) for c in cost), default=0)
        art: Number = (biggest + 1) * (n + 1)
        for a in range(m, m + n):
            self.cost[a] = art
        self.tolerance = tolerance_for(self.cost)
        self._potentials()

    def _potentials(self) -> None:
        """Potentials making every tree arc's reduced cost zero (root at 0)."""
        self.potential[self.root] = 0
        stack = [self.root]
        while stack:
            u = stack.pop()
            for v in self.children[u]:
                c = self.cost[self.pred[v]]
                self.potential[v] = (
                    self.potential[u] + c if self.up[v] else self.potential[u] - c
                )
                stack.append(v)

    def reduced_cost(self, a: int) -> Number:
        return (
            self.cost[a] - self.potential[self.tail[a]] + self.potential[self.head[a]]
        )

    # -- pricing ----------------------------------------------------------

    def _entering(self) -> int:
        """An eligible arc, or -1 at optimality."""
        total = self.m + self.n
        tol = -self.tolerance
        if self.pivot_rule == "dantzig":
            best, best_v = -1, tol
            for a in range(total):
                if self.state[a] != TREE:
                    v = self.state[a] * self.reduced_cost(a)
                    if v < best_v:
                        best, best_v = a, v
            return best
        best, best_v = -1, tol
        count = 0
        a = self.next_arc
        for _ in range(total):
            if self.state[a] != TREE:
                v = self.state[a] * self.reduced_cost(a)
                if v < best_v:
                    best, best_v = a, v
            a = a + 1 if a + 1 < total else 0
            count += 1
            if count == self.block:
                if best != -1:
                    break
                count = 0
        self.next_arc = a
        return best

    # -- pivoting -------------------------------------------------------

    def _residual_down(self, u: int) -> int:
        """Residual of tree arc ``pred[u]`` traversed from ``parent[u]`` to ``u``."""
        a = self.pred[u]
        return self.flow[a] if self.up[u] else self.cap[a] - self.flow[a]

    def _residual_up(self, u: int) -> int:
        """Residual of tree arc ``pred[u]`` traversed from ``u`` to ``parent[u]``."""
        a = self.pred[u]
        return self.cap[a] - self.flow[a] if self.up[u] else self.flow[a]

    def _pivot(self, e: int) -> None:
        k, l = self.tail[e], self.head[e]
        first, second = (k, l) if self.state[e] == LOWER else (l, k)
        # Paths from both ends up to the apex.
        a, b = first, second
        path_a: list[int] = []
        path_b: list[int] = []
        while a != b:
            if self.depth[a] >= self.depth[b]:
                path_a.append(a)
                a = self.parent[a]
            else:
                path_b.append(b)
                b = self.parent[b]
        # Traversal order from the apex: down to `first`, the entering arc,
        # then up from `second`. Keep the last blocking arc (Cunningham).
        # A candidate is (residual, node whose pred arc it is, first side);
        # node -1 stands for the entering arc.
        order = [(self._residual_down(u), u, True) for u in reversed(path_a)]
        order.append((self.cap[e], -1, False))
        order.extend((self._residual_up(u), u, False) for u in path_b)
        delta = min(r for r, _, _ in order)
        leaving, leaving_first = next(
            (u, side) for r, u, side in reversed(order) if r == delta
        )
        # Push delta around the cycle.
        if delta:
            for u in path_a:
                self.flow[self.pred[u]] += -delta if self.up[u] else delta
            for u in path_b:
                self.flow[self.pred[u]] += delta if self.up[u] else -delta
            self.flow[e] += delta if self.state[e] == LOWER else -delta
        else:
            self.counters["degenerate_pivots"] += 1
        if leaving == -1:
            self.state[e] = -self.state[e]
            self.counters["bound_flips"] += 1
            return
        self.counters["pivots"] += 1
        rc = self.reduced_cost(e)
        u_in = first if leaving_first else second
        u_out = second if leaving_first else first
        shift = -rc if u_in == l else rc
        out_arc = self.pred[leaving]
        self.state[out_arc] = LOWER if self.flow[out_arc] == 0 else UPPER
        self.state[e] = TREE
        # Re-hang the subtree of `leaving` from `u_in`.
        chain = [u_in]
        while chain[-1] != leaving:
            chain.append(self.parent[chain[-1]])
        old_pred = [self.pred[x] for x in chain]
        old_up = [self.up[x] for x in chain]
        self.children[self.parent[leaving]].remove(leaving)
        for i in range(len(chain) - 1, 0, -1):
            x, below = chain[i], chain[i - 1]
            self.children[x].remove(below)
            self.children[below].append(x)
            self.parent[x] = below
            self.pred[x] = old_pred[i - 1]
            self.up[x] = not old_up[i - 1]
        self.parent[u_in] = u_out
        self.pred[u_in] = e
        self.up[u_in] = self.tail[e] == u_in
        self.children[u_out].append(u_in)
        stack = [u_in]
        while stack:
            x = stack.pop()
            self.depth[x] = self.depth[self.parent[x]] + 1
            self.potential[x] += shift
            stack.extend(self.children[x])

    def run(self) -> bool:
        """Pivot to optimality; return True when the problem is feasible."""
        while (e := self._entering()) != -1:
            self._pivot(e)
        return not any(self.flow[self.m :])

    def solution(self) -> tuple[list[int], list[Number]]:
        """Flows of the real arcs and potentials of the real nodes."""
        return self.flow[: self.m], self.potential[: self.n]
