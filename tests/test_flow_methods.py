# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Minimum and maximum cost flow methods, against independent oracles."""

import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from oracles import brute_force, highs_oracle, networkx_oracle, problems, same_value

from protee.flow import (
    FlowProblem,
    FlowResult,
    InfeasibleCut,
    NegativeCycle,
    Status,
    check_feasibility,
    methods,
    prepare,
    solve,
)
from protee.flow.diagnostics import reduced_costs
from protee.graph import Digraph

METHODS = [info.name for info in methods()]
SIMPLEX_RULES = [
    ("network_simplex", {"pivot_rule": rule}) for rule in ("block_search", "dantzig")
]
VARIANTS = [*SIMPLEX_RULES, ("cycle_canceling", {}), ("successive_shortest_paths", {})]
needs_highs = pytest.mark.skipif(
    sys.version_info >= (3, 15), reason="no highspy wheel for Python 3.15 yet"
)


def check_optimal(problem: FlowProblem, result: FlowResult) -> None:
    """Feasible integer flow, value, and complementary slackness."""
    assert result.flow is not None
    assert result.potentials is not None
    assert not problem.violations(result.flow)
    assert all(isinstance(x, int) for x in result.flow)
    assert same_value(result.objective, problem.objective(result.flow))
    tol = (
        1e-6
        * (1 + max((abs(c) for c in problem.cost), default=0))
        * (problem.graph.n + 2)
    )
    for a, rc in enumerate(reduced_costs(problem, result.potentials)):
        hi = problem.upper[a]
        if hi is None or result.flow[a] < hi:
            assert rc >= -tol, f"arc {a} below its upper bound with reduced cost {rc}"
        if result.flow[a] > problem.lower[a]:
            assert rc <= tol, f"arc {a} above its lower bound with reduced cost {rc}"


def check_certificate(problem: FlowProblem, result: FlowResult) -> None:
    if result.status is Status.INFEASIBLE:
        cut = result.certificate
        assert isinstance(cut, InfeasibleCut)
        assert cut.excess > 0
        assert not check_feasibility(problem).feasible
    else:
        assert result.status is Status.UNBOUNDED
        cycle = result.certificate
        assert isinstance(cycle, NegativeCycle)
        assert cycle.weight < 0
        g = problem.graph
        for a, b in zip(cycle.arcs, (*cycle.arcs[1:], cycle.arcs[0]), strict=True):
            assert problem.upper[a] is None
            assert g.heads[a] == g.tails[b]
        assert check_feasibility(problem).feasible


@pytest.mark.parametrize(("method", "options"), VARIANTS)
@given(problem=problems())
@settings(max_examples=150)
def test_methods_agree_with_networkx(
    method: str, options: dict[str, str], problem: FlowProblem
) -> None:
    result = solve(problem, method=method, **options)
    status, value = networkx_oracle(problem)
    assert result.status == status
    if result.optimal:
        assert same_value(result.objective, value)
        check_optimal(problem, result)
    else:
        check_certificate(problem, result)


@needs_highs
@pytest.mark.parametrize("method", METHODS)
@given(problem=problems(float_costs=True))
@settings(max_examples=80)
def test_methods_agree_with_highs_on_float_costs(
    method: str, problem: FlowProblem
) -> None:
    result = solve(problem, method=method)
    status, value = highs_oracle(problem)
    if status == "unbounded":
        assert result.status in (Status.UNBOUNDED, Status.INFEASIBLE)
    else:
        assert result.status == status
    if result.optimal:
        assert same_value(result.objective, value)
        check_optimal(problem, result)


@pytest.mark.parametrize("method", METHODS)
@given(problem=problems(max_nodes=4, max_arcs=6, finite=True, span=2))
@settings(max_examples=60)
def test_methods_agree_with_enumeration(method: str, problem: FlowProblem) -> None:
    result = solve(problem, method=method)
    status, value = brute_force(problem)
    assert result.status == status
    assert same_value(result.objective, value)


@given(
    problem=problems(),
    costs=st.lists(
        st.lists(st.integers(-5, 5), min_size=9, max_size=9), min_size=1, max_size=4
    ),
)
@settings(max_examples=60)
def test_prepared_problem_solves_new_costs_like_fresh_solves(
    problem: FlowProblem, costs: list[list[int]]
) -> None:
    m = problem.graph.m
    for method in METHODS:
        prepared = prepare(problem, method=method)
        for cost in costs:
            again = prepared.solve(cost[:m], "max")
            fresh = solve(problem.with_cost(cost[:m], "max"), method=method)
            assert again.status == fresh.status
            assert same_value(again.objective, fresh.objective)


@pytest.mark.parametrize("method", METHODS)
@given(problem=problems())
@settings(max_examples=30)
def test_counters_are_deterministic(method: str, problem: FlowProblem) -> None:
    first = solve(problem, method=method)
    second = solve(problem, method=method)
    assert dict(first.counters) == dict(second.counters)
    assert first.flow == second.flow


def test_warm_start_saves_pivots() -> None:
    g = Digraph.from_arcs(4, [(0, 1), (1, 3), (0, 2), (2, 3), (1, 2), (3, 0)])
    p = FlowProblem(
        g, upper=(5, 5, 5, 5, 5, 8), cost=(1, 2, 2, 1, 1, 0), lower=(0, 0, 0, 0, 0, 6)
    )
    prepared = prepare(p, method="network_simplex")
    assert prepared.feasibility() is prepared.feasibility()
    assert prepared.feasibility().feasible
    first = prepared.solve()
    same = prepared.solve()
    assert same.counters["pivots"] == 0
    assert same.flow == first.flow


def test_float_tolerance_does_not_grow_with_the_graph() -> None:
    # Two parallel arcs whose costs differ by 1e-6, in a graph of 2000
    # nodes: the artificial big-M cost must not widen the tolerance.
    n = 2000
    g = Digraph.from_arcs(n, [(0, 1), (0, 1)])
    p = FlowProblem(
        g, upper=(1, 1), cost=(1.0, 0.999999), supply=(1, -1) + (0,) * (n - 2)
    )
    for method in METHODS:
        r = solve(p, method=method)
        assert r.flow == (0, 1), method


def test_documented_example() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    p = FlowProblem(g, upper=(2, 2, 1), cost=(1, 1, 3), supply=(3, 0, -3))
    for method in METHODS:
        r = solve(p, method=method)
        assert (r.status, r.objective, r.flow, r.method) == (
            Status.OPTIMAL,
            7,
            (2, 2, 1),
            method,
        )


def test_infeasible_cut_names_the_bottleneck() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2)])
    p = FlowProblem(g, upper=(5, 2), supply=(4, 0, -4))
    r = solve(p, method="successive_shortest_paths")
    assert r.status is Status.INFEASIBLE
    assert isinstance(r.certificate, InfeasibleCut)
    assert r.certificate.excess == 2
    assert r.certificate.out_arcs == (1,)


def test_unbounded_cycle_without_upper_bounds() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (2, 0)])
    p = FlowProblem(g, cost=(1, 1, 1), sense="max")
    r = solve(p, method="network_simplex")
    assert r.status is Status.UNBOUNDED
    assert isinstance(r.certificate, NegativeCycle)
    assert sorted(r.certificate.arcs) == [0, 1, 2]


def test_infeasibility_wins_over_unboundedness() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 0), (1, 2)])
    p = FlowProblem(g, upper=(None, None, 0), cost=(-1, 0, 0), supply=(1, 0, -1))
    assert solve(p, method="cycle_canceling").status is Status.INFEASIBLE


def test_method_choice_is_explicit() -> None:
    g = Digraph.from_arcs(1, [])
    p = FlowProblem(g)
    with pytest.raises(ValueError, match="unknown flow method"):
        solve(p, method="simplex")
    with pytest.raises(TypeError, match="no option"):
        solve(p, method="cycle_canceling", pivot_rule="dantzig")
    with pytest.raises(ValueError, match="pivot rule"):
        solve(p, method="network_simplex", pivot_rule="bland")
    assert solve(p, method="network_simplex").objective == 0
    assert [m.name for m in methods()] == [
        "network_simplex",
        "cycle_canceling",
        "successive_shortest_paths",
    ]
    assert methods()[0].warm_start
