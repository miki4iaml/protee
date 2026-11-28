# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Conformity of the flow methods to the common result model."""

from __future__ import annotations

import pytest
from conformity import check_core, check_registry
from hypothesis import given, settings
from oracles import check_certificate, problems, same_value

from protee.flow import FlowProblem, FlowResult, Status, methods, prepare, solve
from protee.graph import Digraph
from protee.results import GuaranteeKind

INFOS = {info.name: info for info in methods()}
VARIANTS = [
    ("network_simplex", {"pivot_rule": "block_search"}),
    ("network_simplex", {"pivot_rule": "dantzig"}),
    ("cycle_canceling", {}),
    ("successive_shortest_paths", {}),
]


def test_registry() -> None:
    check_registry(methods())
    for info in methods():
        assert info.problem == "min_cost_flow"
        assert info.guarantee.kind is GuaranteeKind.EXACT


@pytest.mark.parametrize(("method", "options"), VARIANTS)
@given(problem=problems())
@settings(max_examples=60)
def test_every_method_conforms(
    method: str, options: dict[str, str], problem: FlowProblem
) -> None:
    def run() -> FlowResult:
        return solve(problem, method=method, **options)

    result = solve(problem, method=method, **options)
    check_core(result, INFOS[method], run)
    if result.status is Status.OPTIMAL:
        assert result.certificate is None
    else:
        check_certificate(problem, result)


@given(problem=problems())
@settings(max_examples=60)
def test_exact_methods_agree(problem: FlowProblem) -> None:
    results = [solve(problem, method=m, **o) for m, o in VARIANTS]
    first = results[0]
    for other in results[1:]:
        assert other.status is first.status
        if first.status is Status.OPTIMAL:
            assert same_value(other.objective, first.objective)


def test_parameters_are_the_effective_options() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    p = FlowProblem(g, upper=(2, 2, 1), cost=(1, 1, 3), supply=(3, 0, -3))
    default = solve(p, method="network_simplex")
    dantzig = solve(p, method="network_simplex", pivot_rule="dantzig")
    assert dict(default.parameters) == {"pivot_rule": "block_search"}
    assert dict(dantzig.parameters) == {"pivot_rule": "dantzig"}
    assert default.inputs != dantzig.inputs
    assert dict(solve(p, method="cycle_canceling").parameters) == {}


def test_fingerprint_follows_the_inputs() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    p = FlowProblem(g, upper=(2, 2, 1), cost=(1, 1, 3), supply=(3, 0, -3))
    same = FlowProblem(
        Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)]),
        upper=[2, 2, 1],
        cost=[1, 1, 3],
        supply=[3, 0, -3],
    )
    base = solve(p, method="cycle_canceling")
    assert solve(same, method="cycle_canceling").inputs == base.inputs
    assert solve(p, method="successive_shortest_paths").inputs != base.inputs
    assert solve(p.with_cost((1, 1, 2)), method="cycle_canceling").inputs != (
        base.inputs
    )
    assert solve(p.with_cost(p.cost, "max"), method="cycle_canceling").inputs != (
        base.inputs
    )


def test_prepared_results_carry_the_costs_they_solved() -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    p = FlowProblem(g, upper=(2, 2, 1), cost=(1, 1, 3), supply=(3, 0, -3))
    prepared = prepare(p, method="network_simplex")
    first = prepared.solve()
    second = prepared.solve((1, 1, 0))
    assert first.inputs == solve(p, method="network_simplex").inputs
    assert second.inputs == (
        solve(p.with_cost((1, 1, 0)), method="network_simplex").inputs
    )
    assert first.inputs != second.inputs
