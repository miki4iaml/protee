# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Independent oracles and instance generators for the flow tests.

- :func:`brute_force`: every integer flow of a tiny problem;
- :func:`networkx_oracle`: NetworkX's network simplex;
- :func:`highs_oracle`: the linear program solved by HiGHS;
- :func:`problems`: a Hypothesis strategy of small flow problems, with
  parallel arcs, loops, lower bounds, missing upper bounds and supplies;
  :func:`networks` and :func:`disjoint_cases`, instances of maximum flow
  and of disjoint paths;
- :func:`check_certificate`: a certificate of infeasibility or
  unboundedness, recomputed from the problem (:func:`check_cut`,
  :func:`check_cycle`), independently of the method that found it.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from typing import Any, cast

import networkx as nx
from hypothesis import strategies as st

from protee.flow import (
    FlowProblem,
    InfeasibleCut,
    NegativeCycle,
    Status,
)
from protee.flow._problem import Sense
from protee.graph import Digraph
from protee.results import ResultCore

type Number = int | float
type Outcome = tuple[str, Number | None]


def all_flows(problem: FlowProblem, cap: int = 4) -> list[tuple[int, ...]]:
    """Every feasible integer flow; arcs without upper bound are cut at
    ``lower + cap``."""
    ranges = [
        range(lo, (lo + cap if hi is None else hi) + 1)
        for lo, hi in zip(problem.lower, problem.upper, strict=True)
    ]
    return [x for x in itertools.product(*ranges) if not problem.violations(x)]


def brute_force(problem: FlowProblem) -> Outcome:
    """Status and optimal value by enumeration (finite upper bounds)."""
    assert all(hi is not None for hi in problem.upper)
    flows = all_flows(problem)
    if not flows:
        return "infeasible", None
    values = [problem.objective(x) for x in flows]
    return "optimal", min(values) if problem.sense == "min" else max(values)


def _shifted(problem: FlowProblem) -> tuple[list[int], Number]:
    g = problem.graph
    supply = list(problem.supply)
    for a, (t, h) in enumerate(g.arcs()):
        supply[t] -= problem.lower[a]
        supply[h] += problem.lower[a]
    return supply, problem.objective(problem.lower)


def networkx_oracle(problem: FlowProblem) -> Outcome:
    """Status and optimal value by ``networkx.network_simplex``."""
    g = problem.graph
    supply, offset = _shifted(problem)
    sign = 1 if problem.sense == "min" else -1
    graph: Any = nx.MultiDiGraph()
    for v in range(g.n):
        graph.add_node(v, demand=-supply[v])
    for a, (t, h) in enumerate(g.arcs()):
        attrs: dict[str, Number] = {"weight": sign * problem.cost[a]}
        hi = problem.upper[a]
        if hi is not None:
            attrs["capacity"] = hi - problem.lower[a]
        graph.add_edge(t, h, key=a, **attrs)
    try:
        value, _ = nx.network_simplex(graph)
    except nx.NetworkXUnfeasible:
        return "infeasible", None
    except nx.NetworkXUnbounded:
        return "unbounded", None
    return "optimal", sign * value + offset


def highs_oracle(problem: FlowProblem) -> Outcome:
    """Status and optimal value of the linear program, solved by HiGHS."""
    import highspy
    import numpy as np

    g = problem.graph
    if g.m == 0:  # HiGHS reports an empty model without solving it
        return ("optimal", 0) if not any(problem.supply) else ("infeasible", None)
    h = highspy.Highs()  # type: ignore[no-untyped-call]
    h.setOptionValue("output_flag", False)
    inf = highspy.kHighsInf
    lower = np.array(problem.lower, dtype=float)
    upper = np.array([inf if hi is None else hi for hi in problem.upper], dtype=float)
    h.addVars(g.m, lower, upper)
    h.changeColsCost(
        g.m, np.arange(g.m, dtype=np.int32), np.array(problem.cost, dtype=float)
    )
    for v in range(g.n):
        idx = list(g.out_arcs(v)) + list(g.in_arcs(v))
        val = [1.0] * g.out_degree(v) + [-1.0] * g.in_degree(v)
        merged: dict[int, float] = {}
        for i, x in zip(idx, val, strict=True):
            merged[i] = merged.get(i, 0.0) + x
        keys = [i for i, x in merged.items() if x != 0]
        b = float(problem.supply[v])
        h.addRow(
            b,
            b,
            len(keys),
            np.array(keys, dtype=np.int32),
            np.array([merged[i] for i in keys]),
        )
    if problem.sense == "max":
        h.changeObjectiveSense(highspy.ObjSense.kMaximize)
    h.run()
    status = h.getModelStatus()
    if status == highspy.HighsModelStatus.kOptimal:
        return "optimal", h.getInfo().objective_function_value
    if status == highspy.HighsModelStatus.kInfeasible:
        return "infeasible", None
    if status in (
        highspy.HighsModelStatus.kUnbounded,
        highspy.HighsModelStatus.kUnboundedOrInfeasible,
    ):
        return "unbounded", None
    raise AssertionError(f"unexpected HiGHS status {status}")


def same_value(a: Number | None, b: Number | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-6)


def balanced(draw: st.DrawFn, n: int, size: int) -> list[int]:
    """Supplies summing to zero."""
    supply = [0] * n
    for _ in range(draw(st.integers(0, 3))):
        s, t = draw(st.integers(0, n - 1)), draw(st.integers(0, n - 1))
        q = draw(st.integers(1, size))
        supply[s] += q
        supply[t] -= q
    return supply


@st.composite
def graphs(draw: st.DrawFn, max_nodes: int = 6, max_arcs: int = 9) -> Digraph:
    n = draw(st.integers(1, max_nodes))
    arcs = draw(
        st.lists(
            st.tuples(st.integers(0, n - 1), st.integers(0, n - 1)), max_size=max_arcs
        )
    )
    return Digraph.from_arcs(n, arcs)


@st.composite
def problems(
    draw: st.DrawFn,
    max_nodes: int = 6,
    max_arcs: int = 9,
    finite: bool = False,
    span: int = 3,
    float_costs: bool = False,
) -> FlowProblem:
    """Small flow problems; ``finite`` keeps every upper bound finite."""
    g = draw(graphs(max_nodes, max_arcs))
    lower = [draw(st.integers(0, 2)) for _ in range(g.m)]
    upper: list[int | None] = []
    for lo in lower:
        unbounded = not finite and draw(st.booleans()) and draw(st.booleans())
        upper.append(None if unbounded else lo + draw(st.integers(0, span)))
    cost: Sequence[Number]
    if float_costs:
        cost = [draw(st.floats(-4, 6, allow_nan=False, width=32)) for _ in range(g.m)]
    else:
        cost = [draw(st.integers(-4, 6)) for _ in range(g.m)]
    supply = balanced(draw, g.n, 3)
    sense = cast(Sense, draw(st.sampled_from(["min", "max"])))
    return FlowProblem(
        g, lower=lower, upper=upper, cost=cost, supply=supply, sense=sense
    )


@st.composite
def networks(draw: st.DrawFn) -> tuple[Digraph, list[int | None], int, int]:
    """A maximum flow instance: graph, capacities, source, target (equal
    when the graph has a single node)."""
    g = draw(graphs(max_nodes=7, max_arcs=14))
    cap: list[int | None] = [draw(st.integers(0, 6)) for _ in range(g.m)]
    s = draw(st.integers(0, g.n - 1))
    t = draw(st.integers(0, g.n - 1).filter(lambda v: v != s)) if g.n > 1 else s
    return g, cap, s, t


@st.composite
def disjoint_cases(draw: st.DrawFn) -> tuple[Digraph, list[int], int, int, int]:
    """A disjoint paths instance: graph, costs, source, target (equal when
    the graph has a single node), k."""
    g = draw(graphs(max_nodes=5, max_arcs=8))
    cost = [draw(st.integers(0, 5)) for _ in range(g.m)]
    s = draw(st.integers(0, g.n - 1))
    t = draw(st.integers(0, g.n - 1).filter(lambda v: v != s)) if g.n > 1 else s
    return g, cost, s, t, draw(st.integers(1, 3))


def check_cut(problem: FlowProblem, cut: InfeasibleCut) -> None:
    """``cut`` is the Gale-Hoffman inequality of its node set, recomputed
    from ``problem``, and it is violated."""
    g = problem.graph
    nodes = cut.nodes
    assert all(0 <= v < g.n for v in nodes)
    leaving = tuple(
        a for a, (t, h) in enumerate(g.arcs()) if t in nodes and h not in nodes
    )
    entering = tuple(
        a for a, (t, h) in enumerate(g.arcs()) if h in nodes and t not in nodes
    )
    assert (cut.out_arcs, cut.in_arcs) == (leaving, entering)
    upper = [problem.upper[a] for a in leaving]
    assert all(hi is not None for hi in upper)
    capacity = sum(hi or 0 for hi in upper) - sum(problem.lower[a] for a in entering)
    supply = sum(problem.supply[v] for v in nodes)
    assert (cut.supply, cut.capacity) == (supply, capacity)
    assert supply > capacity
    assert cut.excess == supply - capacity


def check_cycle(problem: FlowProblem, cycle: NegativeCycle) -> None:
    """``cycle`` is a cycle of arcs without upper bound whose cost improves
    the objective, walked again on ``problem``."""
    g = problem.graph
    assert cycle.arcs
    for a, b in zip(cycle.arcs, (*cycle.arcs[1:], cycle.arcs[0]), strict=True):
        assert problem.upper[a] is None
        assert g.heads[a] == g.tails[b]
    sign = 1 if problem.sense == "min" else -1
    weight = math.fsum(sign * problem.cost[a] for a in cycle.arcs)
    assert same_value(weight, cycle.weight)
    assert cycle.weight < 0


def check_certificate(problem: FlowProblem, result: ResultCore) -> None:
    """The certificate of an infeasible or unbounded result of ``problem``,
    verified without the method that produced it."""
    if result.status is Status.INFEASIBLE:
        cut = result.certificate
        assert isinstance(cut, InfeasibleCut)
        check_cut(problem, cut)
    else:
        assert result.status is Status.UNBOUNDED
        cycle = result.certificate
        assert isinstance(cycle, NegativeCycle)
        check_cycle(problem, cycle)
        # The problem is feasible: NetworkX finds a flow for zero costs.
        zero = problem.with_cost((0,) * problem.graph.m, "min")
        assert networkx_oracle(zero)[0] == "optimal"
