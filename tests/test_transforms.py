# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Reversible transformations: solve the transformed problem, restore,
and find the optimum of the original problem."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from oracles import problems, same_value

from protee import transforms
from protee.flow import FlowProblem, Status, solve
from protee.flow.diagnostics import reduced_costs
from protee.graph import Digraph

METHOD = "network_simplex"


def check_restored(
    original: FlowProblem, transformed: FlowProblem, restore: object
) -> None:
    direct = solve(original, method=METHOD)
    via = solve(transformed, method="successive_shortest_paths")
    assert via.status == direct.status
    if direct.optimal:
        assert via.flow is not None
        flow = restore(via.flow)  # type: ignore[operator]
        assert not original.violations(flow)
        assert same_value(original.objective(flow), direct.objective)


@given(problem=problems())
@settings(max_examples=80)
def test_remove_lower_bounds(problem: FlowProblem) -> None:
    shift = transforms.remove_lower_bounds(problem)
    assert not any(shift.problem.lower)
    check_restored(problem, shift.problem, shift.restore_flow)
    r = solve(shift.problem, method=METHOD)
    if r.optimal:
        assert r.objective is not None
        assert same_value(
            r.objective + shift.offset, solve(problem, method=METHOD).objective
        )
        assert r.potentials is not None
        assert shift.restore_potentials(r.potentials) == r.potentials


@given(problem=problems())
@settings(max_examples=80)
def test_subdivision_removes_parallel_arcs_and_loops(problem: FlowProblem) -> None:
    sub = transforms.subdivide_arcs(problem)
    pairs = list(sub.problem.graph.arcs())
    assert len(pairs) == len(set(pairs))
    assert all(t != h for t, h in pairs)
    check_restored(problem, sub.problem, sub.restore_flow)
    r = solve(sub.problem, method=METHOD)
    if r.optimal:
        assert r.flow is not None
        assert r.potentials is not None
        potentials = sub.restore_potentials(r.potentials)
        flow = sub.restore_flow(r.flow)
        for a, rc in enumerate(reduced_costs(problem, potentials)):
            hi = problem.upper[a]
            assert rc >= 0 or (hi is not None and flow[a] == hi)
            assert rc <= 0 or flow[a] == problem.lower[a]


@given(problem=problems(), data=st.data())
@settings(max_examples=80)
def test_split_nodes_without_node_bounds_changes_nothing(
    problem: FlowProblem, data: st.DataObject
) -> None:
    split = transforms.split_nodes(problem)
    check_restored(problem, split.problem, split.restore_flow)
    r = solve(split.problem, method=METHOD)
    if r.flow is not None:
        out = split.node_flow(r.flow)
        g = problem.graph
        flow = split.restore_flow(r.flow)
        for v in range(g.n):
            assert out[v] == sum(flow[a] for a in g.out_arcs(v))


def test_node_bounds_limit_the_flow_through_a_node() -> None:
    # Two routes 0 -> 1 -> 3 and 0 -> 2 -> 3; at most one unit through node 1.
    g = Digraph.from_arcs(4, [(0, 1), (1, 3), (0, 2), (2, 3)])
    p = FlowProblem(g, cost=(1, 1, 2, 2), supply=(2, 0, 0, -2))
    split = transforms.split_nodes(p, upper=(None, 1, None, None))
    r = solve(split.problem, method="cycle_canceling")
    assert r.flow is not None
    assert split.restore_flow(r.flow) == (1, 1, 1, 1)
    assert split.node_flow(r.flow)[1] == 1


def test_super_terminals_close_a_life_cycle_graph() -> None:
    # Two disconnected parts, each with a start (factory) and an end; the
    # closure sends exactly one life from any start to any end.
    g = Digraph.from_arcs(4, [(0, 1), (2, 3)], labels=["f1", "e1", "f2", "e2"])
    p = FlowProblem(g, cost=(5, 7), sense="max")
    closed = transforms.add_super_terminals(
        p,
        sources=[0, 2],
        sinks=[1, 3],
        source_bounds=[(0, 1)] * 2,
        sink_bounds=[(0, 1)] * 2,
        through=(1, 1),
    )
    assert closed.problem.graph.labels is not None
    assert closed.problem.graph.labels[-2:] == ("super-source", "super-sink")
    r = solve(closed.problem, method=METHOD)
    assert r.flow is not None
    assert r.objective == 7
    assert closed.restore_flow(r.flow) == (0, 1)
    assert closed.source_flow(r.flow) == (0, 1)
    assert closed.sink_flow(r.flow) == (0, 1)
    assert closed.through_flow(r.flow) == 1
    assert r.potentials is not None
    assert len(closed.restore_potentials(r.potentials)) == 4
    with pytest.raises(ValueError, match="one pair of bounds"):
        transforms.add_super_terminals(p, [0], [1], source_bounds=[])


@given(problem=problems(), data=st.data())
@settings(max_examples=80)
def test_super_terminals_without_terminals_keep_the_problem(
    problem: FlowProblem, data: st.DataObject
) -> None:
    closed = transforms.add_super_terminals(problem, [], [], through=(0, 0))
    check_restored(problem, closed.problem, closed.restore_flow)


@given(problem=problems(), data=st.data())
@settings(max_examples=100)
def test_contract_paths_is_exact_for_flows(
    problem: FlowProblem, data: st.DataObject
) -> None:
    protected = data.draw(st.sets(st.integers(0, problem.graph.n - 1)))
    try:
        contracted = transforms.contract_paths(problem, protected=protected)
    except ValueError:
        assert solve(problem, method=METHOD).status is Status.INFEASIBLE
        return
    assert contracted.problem.graph.m <= problem.graph.m
    check_restored(problem, contracted.problem, contracted.restore_flow)


def test_contraction_of_a_chain_of_bounds() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (2, 0)])
    p = FlowProblem(g, lower=(1, 0, 2), upper=(5, 3, None), cost=(1, 2, 3), sense="max")
    contracted = transforms.contract_paths(p, protected=[0])
    assert contracted.problem.graph.m == 1
    assert (
        contracted.problem.lower,
        contracted.problem.upper,
        contracted.problem.cost,
    ) == ((2,), (3,), (6,))
    r = solve(contracted.problem, method=METHOD)
    assert r.flow is not None
    assert contracted.restore_flow(r.flow) == (3, 3, 3)
    with pytest.raises(ValueError, match="infeasible"):
        transforms.contract_paths(FlowProblem(g, lower=(4, 0, 0), upper=(5, 3, None)))


def test_labels_of_new_nodes_avoid_existing_ones() -> None:
    g = Digraph.from_arcs(2, [(0, 1), (0, 1)], labels=["super-source", "0~1:0"])
    p = FlowProblem(g)
    assert transforms.add_super_terminals(p, [0], [1]).problem.graph.labels == (
        "super-source",
        "0~1:0",
        "_super-source",
        "super-sink",
    )
    assert transforms.subdivide_arcs(p, [1]).arcs == (1,)
