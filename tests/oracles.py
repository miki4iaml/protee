# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Independent oracles and instance generators for the flow tests.

- :func:`brute_force`: every integer flow of a tiny problem;
- :func:`networkx_oracle`: NetworkX's network simplex;
- :func:`highs_oracle`: the linear program solved by HiGHS (skipped where
  highspy is not installed, such as Python 3.15 for now);
- :func:`problems`: a Hypothesis strategy of small flow problems, with
  parallel arcs, loops, lower bounds, missing upper bounds and supplies.
"""

import itertools
import math
from collections.abc import Sequence
from typing import Any, cast

import networkx as nx
from hypothesis import strategies as st

from protee.flow import FlowProblem
from protee.flow._problem import Sense
from protee.graph import Digraph

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
