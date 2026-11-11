# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Validation and helpers of FlowProblem."""

import math

import pytest

from protee.flow import FlowProblem, FlowResult, Status
from protee.flow._disjoint import _walks
from protee.flow.diagnostics import optimum_uniqueness
from protee.graph import Digraph

G = Digraph.from_arcs(2, [(0, 1), (1, 0)])


def test_defaults_and_helpers() -> None:
    p = FlowProblem(G, upper=(3, math.inf))  # type: ignore[arg-type]  # accepted at run time
    assert (p.lower, p.upper, p.cost, p.supply, p.sense) == (
        (0, 0),
        (3, None),
        (0, 0),
        (0, 0),
        "min",
    )
    assert p.is_circulation
    assert p.integral_costs
    q = p.with_cost((1.5, 2), "max")
    assert (q.cost, q.sense, q.integral_costs) == ((1.5, 2), "max", False)
    assert q.objective((2, 2)) == 7
    assert p.violations((1,)) == ["expected 2 arc flows, got 1"]
    assert p.violations((4, 1)) == [
        "arc 0: flow 4 outside [0, 3]",
        "node 0: net outflow 3 instead of 0",
        "node 1: net outflow -3 instead of 0",
    ]
    assert not FlowProblem(G, supply=(1, -1)).is_circulation


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"lower": (0,)}, ValueError, "lower: expected 2"),
        ({"upper": (1,)}, ValueError, "upper: expected 2"),
        ({"cost": (1,)}, ValueError, "cost: expected 2"),
        ({"lower": (0.5, 0)}, TypeError, "integer"),
        ({"lower": (True, 0)}, TypeError, "integer"),
        ({"upper": (1.5, None)}, TypeError, "integer, None or math.inf"),
        ({"cost": (math.nan, 0)}, TypeError, "finite number"),
        ({"cost": ("1", 0)}, TypeError, "finite number"),
        ({"lower": (2, 0), "upper": (1, None)}, ValueError, "exceeds"),
        ({"supply": (1, 0)}, ValueError, "sum to zero"),
        ({"sense": "maximize"}, ValueError, "sense"),
    ],
)
def test_invalid_problems_are_refused(
    kwargs: dict[str, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        FlowProblem(G, **kwargs)  # type: ignore[arg-type]


def test_walks_drop_cycles_of_the_flow() -> None:
    # 0 -> 1 -> 2 -> 1 -> 3: the flow goes around 1 -> 2 -> 1 on its way.
    g = Digraph.from_arcs(4, [(0, 1), (1, 2), (2, 1), (1, 3)])
    assert _walks(g, (1, 1, 1, 1), 0, 3, 1) == [(0, 3)]


def test_uniqueness_on_an_interior_optimum() -> None:
    # A flow strictly inside its bounds on a triangle: not a vertex of the
    # polytope (a method returns vertices), but optimal all the same.
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    p = FlowProblem(g, upper=(2, 2, 2), supply=(2, 0, -2))
    result = FlowResult(
        Status.OPTIMAL, "by hand", 0, (1, 1, 1), (0, 0, 0), None, {}, "0"
    )
    found = optimum_uniqueness(p, result)
    assert not found.unique
    assert found.direction is not None
    assert sorted(a for a, _ in found.direction) == [0, 1, 2]
    tree = FlowProblem(Digraph.from_arcs(2, [(0, 1)]), upper=(2,), supply=(1, -1))
    single = FlowResult(Status.OPTIMAL, "by hand", 0, (1,), (0, 0), None, {}, "0")
    assert optimum_uniqueness(tree, single).unique
