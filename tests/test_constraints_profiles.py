# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Life-cycle profiles whose maximum occurrences are sourced requirements.

The topologies are those of nine hand-built reference profiles (links
numbered from 1, situation 1 is the factory, of zero duration; the other
situations last 1). Each profile is closed by a sink and a single return
link bounded to 1..1. The occurrence values are built for these tests, edge
cases included: non-zero minimum, zero or infinite maxima, unattainable or
non-binding maxima, an overconstrained system and multiple optima.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping

import pytest
from oracles import check_certificate, networkx_oracle

from protee.constraints import (
    ArcData,
    Attribute,
    Family,
    FlowSearch,
    Origin,
    Parameter,
    Provenance,
    Requirement,
    RequirementSet,
    RequirementStatus,
    Rulebook,
    RulebookKind,
    Source,
    UnknownPolicy,
    Value,
    ValueSet,
    minimal_conflict,
    provenance,
    requirement_table,
    resolve_values,
    verify_flow,
)
from protee.flow import FlowProblem, Status, methods
from protee.flow.diagnostics import flow_ranges, optimum_uniqueness, unattainable_bounds
from protee.graph import Digraph

REFERENCE: dict[str, tuple[int, list[int], list[int]]] = {
    "case-01": (6, [1, 2, 3, 4, 5, 5], [2, 3, 4, 5, 6, 2]),
    "case-02": (8, [1, 2, 3, 3, 4, 5, 6, 7, 7], [2, 3, 4, 5, 6, 6, 7, 8, 2]),
    "case-03": (8, [1, 2, 3, 5, 4, 6, 6, 7, 7], [2, 3, 4, 3, 6, 5, 7, 8, 2]),
    "case-04": (
        9,
        [1, 2, 3, 8, 9, 2, 4, 5, 7, 4, 6],
        [2, 3, 8, 9, 1, 4, 5, 7, 8, 6, 7],
    ),
    "case-05": (8, [1, 2, 3, 4, 1, 5, 7, 6, 3, 8], [2, 3, 4, 1, 5, 7, 6, 1, 8, 7]),
    "case-06": (6, [1, 2, 3, 4, 5, 4, 5], [2, 3, 4, 5, 3, 2, 6]),
    "case-07": (11, [1, 3, 4, 2, 6, 7, 5, 6, 6, 10], [2, 4, 2, 6, 7, 5, 2, 8, 9, 11]),
    "case-08": (9, [1, 2, 3, 3, 8, 8, 5], [2, 3, 4, 8, 2, 9, 6]),
    "case-09": (
        22,
        [
            1,
            2,
            3,
            4,
            5,
            3,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            7,
            13,
            14,
            15,
            16,
            17,
            18,
            14,
            19,
            20,
            17,
            10,
            17,
        ],
        [
            2,
            3,
            4,
            5,
            1,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            7,
            13,
            14,
            15,
            16,
            17,
            18,
            7,
            19,
            20,
            16,
            21,
            22,
            9,
        ],
    ),
}
#: The maxima given with case-09, by link number.
GIVEN_09 = {5: 2, 13: 3, 20: 4, 23: 5, 26: 6}

CLIENT = Rulebook(
    "client", RulebookKind.CLIENT_SPECIFICATION, {"en": "Specification of use"}, "1"
)
SPEC = Source("Specification of use", rulebook="client", edition="1")
S = RequirementStatus
METHODS = [info.name for info in methods()]


def closed(name: str) -> tuple[Digraph, list[str], list[int]]:
    """The profile, closed by a single return link to the factory.

    The links into the factory and the final situations (without a
    successor) lead to a return node, whose only link goes back to the
    factory.
    """
    n, tails, heads = REFERENCE[name]
    links = [(t - 1, h - 1) for t, h in zip(tails, heads, strict=True)]
    arcs = [(t, n if h == 0 else h) for t, h in links]
    labels = [f"L{k + 1:02d}" for k in range(len(links))]
    outs = {t for t, _ in links}
    ins = {h for _, h in links}
    finals = [v for v in range(1, n) if v in ins and v not in outs]
    arcs += [(v, n) for v in finals]
    labels += ["final"] * len(finals)
    arcs.append((n, 0))
    labels.append("return")
    cost = [0 if h == n else 1 for _, h in arcs]
    cost[-1] = 0
    return Digraph.from_arcs(n + 1, arcs), labels, cost


def occurrences(
    name: str,
    maxima: Mapping[str, float],
    minima: Mapping[str, int] | None = None,
    method: str = "network_simplex",
) -> FlowSearch:
    """A flow search whose bounds are sourced requirements, one per link;
    the label ``*`` bounds every link."""
    graph, labels, cost = closed(name)
    minima = {"return": 1} | dict(minima or {})
    maxima = {"return": 1} | dict(maxima)
    reqs: list[Requirement] = []
    params: list[Parameter] = []
    entries: dict[str, Value] = {}
    for label in sorted(set(maxima) | set(minima)):
        key = label.replace("*", "all")
        bind = {"maximum": f"max_{key}"}
        params.append(Parameter(f"max_{key}"))
        entries[f"max_{key}"] = Value(
            maxima.get(label, math.inf), SPEC, Origin.STATEMENT
        )
        if label in minima:
            bind["minimum"] = f"min_{key}"
            params.append(Parameter(f"min_{key}"))
            entries[f"min_{key}"] = Value(minima[label], SPEC, Origin.STATEMENT)
        scope = None if label == "*" else [label]
        reqs.append(
            Requirement(
                f"OC-{key}",
                "occurrence_bounds",
                {"en": f"Occurrences of {label} within their bounds."},
                SPEC,
                parameters=bind,
                scope=None if scope is None else frozenset(scope),
            )
        )
    rs = RequirementSet(tuple(reqs), tuple(params), (CLIENT,))
    values = resolve_values([ValueSet("client", "1", entries)], rs)
    data = ArcData(
        graph.m,
        (Attribute.categorical("link", labels, tuple(dict.fromkeys(labels))),),
        element="link",
    )
    return FlowSearch(
        rs,
        FlowProblem(graph, cost=cost, sense="max"),
        data,
        values,
        method=method,
        policy=UnknownPolicy.EXCLUDE,
    )


def oracle_problem(
    name: str, maximum: int | None, given: Mapping[int, int] | None = None
) -> FlowProblem:
    """The problem built directly from the reference topology, bounds by
    link number, without any requirement: the same maximum on every arc,
    the given maxima on their links, and the return bounded to 1..1."""
    graph, _, cost = closed(name)
    upper: list[int | None] = [maximum] * graph.m
    for link, v in (given or {}).items():
        upper[link - 1] = v
    upper[-1] = 1
    lower = [0] * (graph.m - 1) + [1]
    return FlowProblem(graph, lower=lower, upper=upper, cost=cost, sense="max")


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_bounded_profiles_against_the_oracle(name: str, method: str) -> None:
    search = occurrences(name, {"*": 3}, method=method)
    result = search.solve()
    assert result is not None
    expected = networkx_oracle(oracle_problem(name, 3))
    assert (str(result.status), result.objective) == expected
    assert result.flow is not None
    assert max(result.flow) <= 3
    assert result.flow[-1] == 1
    check = search.verify(result)
    assert check.violations == ()
    assert set(check.statuses.values()) == {S.APPLIED}


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_infinite_maxima_give_the_oracle_status(name: str) -> None:
    links = GIVEN_09 if name == "case-09" else {}
    search = occurrences(name, {f"L{k:02d}": v for k, v in links.items()})
    problem = search.problem_for()
    assert problem is not None
    result = search.solve()
    assert result is not None
    status, value = networkx_oracle(oracle_problem(name, None, links))
    assert str(result.status) == status
    assert result.objective == value
    if result.status is Status.UNBOUNDED:
        check_certificate(problem, result)
    else:
        # case-09, bounded by its given maxima.
        assert result.flow is not None
        for link, maximum in links.items():
            assert result.flow[link - 1] <= maximum
        assert set(search.verify(result).statuses.values()) == {S.APPLIED}


def test_nonzero_minimum_and_zero_maximum() -> None:
    # case-01: 1 -> 2 -> 3 -> 4 -> 5 -> 6, with the loop L06: 5 -> 2.
    search = occurrences("case-01", {"L06": 4}, minima={"L06": 2})
    result = search.solve()
    assert result is not None
    assert result.flow is not None
    assert result.flow[5] == 4
    problem = search.problem_for()
    assert problem is not None
    assert (
        verify_flow(result, search.requirements, problem, search.data, search.values)[
            "OC-L06"
        ].status
        is S.APPLIED
    )
    closed_loop = occurrences("case-01", {"L06": 0})
    assert closed_loop.solve().objective == 5  # type: ignore[union-attr]


def test_unattainable_and_non_binding_maxima() -> None:
    search = occurrences("case-01", {"L06": 1, "L02": 10, "L01": 5})
    problem = search.problem_for()
    assert problem is not None
    unattainable = unattainable_bounds(problem, method="network_simplex")
    assert 1 in unattainable.upper
    assert 0 in unattainable.upper
    ranges = flow_ranges(problem, method="network_simplex", at_optimum=True)
    assert ranges.maximum is not None
    assert ranges.maximum[0] == 1
    impact = search.impact("OC-L01")
    assert impact.delta == 0


def test_overconstrained_profile_and_its_minimal_conflict() -> None:
    # L01 leaves the factory: its occurrences equal the single return.
    search = occurrences("case-01", {"L06": 2}, minima={"L01": 2})
    assert not search.feasible(search.ids)
    for method in ("enumeration", "deletion_filter"):
        conflict = minimal_conflict(search.ids, search.feasible, method=method)
        assert conflict.requirements == ("OC-L01", "OC-return")


def test_multiple_optima_are_detected() -> None:
    # case-02 has two parallel branches of the same duration (3 -> 4 -> 6
    # and 3 -> 5 -> 6).
    search = occurrences("case-02", {"*": 2})
    problem = search.problem_for()
    result = search.solve()
    assert problem is not None
    assert result is not None
    assert not optimum_uniqueness(problem, result).unique


def test_profile_chain_to_the_table_and_the_provenance() -> None:
    # From the specification of use to the requirement table and the
    # provenance, as for routes.
    search = occurrences("case-01", {"*": 4, "L06": 2})
    problem = search.problem_for()
    result = search.solve()
    assert problem is not None
    assert result is not None
    check = verify_flow(
        result, search.requirements, problem, search.data, search.values
    )
    impacts = {rid: search.impact(rid) for rid in search.ids}
    rows = requirement_table(check, search.requirements, search.values, impacts=impacts)
    assert [r.id for r in rows] == list(search.ids)
    row = next(r for r in rows if r.id == "OC-L06")
    assert row.status is S.APPLIED
    assert row.family is Family.CAPACITY
    assert row.source.rulebook == "client"
    assert row.values["max_L06"].value == 2
    assert row.values["max_L06"].origin is Origin.STATEMENT
    assert row.verification == {"passed": 1, "failed": 0, "unknown": 0}
    # The maximum of L06 is binding: without it, four more occurrences.
    assert row.impact is not None
    assert (row.impact["cost_with"], row.impact["delta"]) == (13.0, -4.0)
    data = json.dumps([r.to_dict() for r in rows])
    assert '"origin": "statement"' in data

    def record(s: FlowSearch) -> Provenance:
        p = s.problem_for()
        r = s.solve()
        assert r is not None
        return provenance(
            s.method,
            {"sense": "max"},
            inputs={"problem": p, "data": s.data},
            requirements=s.requirements,
            values=s.values,
            result=r,
            counters=r.counters,
        )

    first, again = record(search), record(occurrences("case-01", {"*": 4, "L06": 2}))
    assert first == again
    assert first.replays(again)
    assert ("max_L06", "client", "1", True) in first.values
    changed = record(occurrences("case-01", {"*": 4, "L06": 1}))
    assert set(first.differences(changed)) == {"inputs", "result"}
