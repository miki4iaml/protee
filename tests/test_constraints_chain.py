# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""From a public text to a verified route: embedded values, TOML,
declared objective and provenance."""

from __future__ import annotations

import copy
import enum
import json
import math
import pickle
import random
import re
from collections.abc import Mapping

import numpy as np
import pytest
from constraints_cases import (
    best_admissible,
    endpoints,
    random_case,
    requirement_set,
    resolved,
)

from protee.constraints import (
    ArcData,
    Attribute,
    Effect,
    EffectKind,
    Origin,
    Parameter,
    Provenance,
    Requirement,
    RequirementSet,
    RequirementStatus,
    ResolvedValues,
    RouteSearch,
    Rulebook,
    RulebookKind,
    RulebookValues,
    Source,
    UnknownPolicy,
    Value,
    ValueSet,
    check_inputs,
    compose,
    evaluate,
    fingerprint,
    minimal_conflict,
    minimal_relaxation,
    provenance,
    requirement_table,
    resolve_values,
    verify_flow,
    verify_route,
)
from protee.flow import FlowProblem
from protee.graph import Digraph
from protee.paths import dijkstra
from protee.results import Status

S = RequirementStatus


class Shade(enum.Enum):
    DARK = 2


OVERSIZE = "fr-oversize-transport-2006"
PLANNER = Rulebook(
    "planner", RulebookKind.CLIENT_SPECIFICATION, {"en": "Planning choices"}, "1"
)
PLANNER_SRC = Source("Planning choices", rulebook="planner", edition="1")
KINDS = ("motorway", "road", "urban")


def test_embedded_values_come_from_the_text() -> None:
    assert RulebookValues.names() == (OVERSIZE,)
    rv = RulebookValues.load(OVERSIZE)
    assert rv.rulebook.kind is RulebookKind.REGULATION
    assert rv.rulebook.title["fr"].startswith("Arrêté du 4 mai 2006")
    assert "Licence Ouverte 2.0" in rv.notice
    road = rv.values.values["oversize_category_3_speed_road"]
    assert (road.value, road.unit, road.origin) == (50.0, "km/h", Origin.RULEBOOK)
    assert road.source.locator == "art. 14"
    assert road.source.citation_checked
    assert road.source.link == rv.rulebook.link
    mass = rv.values.values["oversize_mass_category_2_max"]
    assert (mass.value, mass.unit, mass.source.locator) == (72000.0, "kg", "art. 3")
    assert len(rv.parameters) == len(rv.values.values) == 10
    with pytest.raises(ValueError, match="no embedded rulebook"):
        RulebookValues.load("nowhere")


def category(rv: RulebookValues, length: float, width: float, mass: float) -> int:
    """Article 3: the strongest characteristic decides the category."""
    v = {k: x.value for k, x in rv.values.values.items()}

    def rank(x: float, name: str) -> int:
        if x <= v[f"oversize_{name}_category_1_max"]:  # type: ignore[operator]
            return 1
        return 2 if x <= v[f"oversize_{name}_category_2_max"] else 3  # type: ignore[operator]

    return max(rank(length, "length"), rank(width, "width"), rank(mass, "mass"))


def speed_requirement(kind: str) -> Requirement:
    return Requirement(
        f"OVERSIZE-SPEED-{kind.upper()}",
        "speed_cap",
        {
            "en": f"A 3rd category convoy keeps under the speed cap on a {kind}.",
            "fr": f"Un convoi de 3e catégorie respecte la vitesse maximale ({kind}).",
        },
        Source(
            "Arrêté du 4 mai 2006 relatif aux transports exceptionnels",
            rulebook=OVERSIZE,
            locator="art. 14",
            citation_checked=True,
        ),
        parameters={"maximum": f"oversize_category_3_speed_{kind}"},
        attributes={"length": "length", "speed": "speed_limit"},
        scope=frozenset({kind}),
    )


OBJECTIVE = Requirement(
    "OBJ",
    "objective",
    {"en": "The route minimizes the duration."},
    PLANNER_SRC,
    parameters={"criterion": "route_criterion"},
)


def chain_inputs(
    justification: str | None = "the fastest route was asked for",
) -> tuple[RulebookValues, RequirementSet, ResolvedValues]:
    rv = RulebookValues.load(OVERSIZE)
    reqs = RequirementSet(
        (*(speed_requirement(k) for k in KINDS), OBJECTIVE),
        (*rv.parameters, Parameter("route_criterion")),
        (rv.rulebook, PLANNER),
    )
    choice = ValueSet(
        "planner",
        "1",
        {
            "route_criterion": Value(
                "duration", PLANNER_SRC, Origin.CHOICE, justification=justification
            )
        },
    )
    return rv, reqs, resolve_values([rv.values, choice], reqs)


def network(seed: int) -> tuple[Digraph, ArcData, list[float], list[float], list[str]]:
    case = random_case(seed, n=7, m=18, unknown=0.0)
    rng = random.Random(seed)
    kinds = [rng.choice(KINDS) for _ in range(case.graph.m)]
    limit = [{"motorway": 130.0, "road": 80.0, "urban": 50.0}[k] for k in kinds]
    data = ArcData(
        case.graph.m,
        (
            Attribute.categorical("kind", kinds, KINDS),
            Attribute.numeric("speed_limit", limit, unit="km/h"),
            Attribute.numeric("length", case.length, unit="km"),
        ),
        element="kind",
    )
    return case.graph, data, case.length, limit, kinds


@pytest.mark.parametrize("seed", range(10))
def test_full_chain_from_the_text_to_a_verified_route(seed: int) -> None:
    rv, reqs, values = chain_inputs()
    assert category(rv, length=27.0, width=3.5, mass=60000.0) == 3
    assert category(rv, length=18.0, width=3.0, mass=48000.0) == 1
    assert "oversize_mass_category_1_max" in values.unused
    graph, data, length, limit, kinds = network(seed)
    s, t = endpoints(seed, graph.n)
    search = RouteSearch(
        reqs,
        graph,
        data,
        values,
        s,
        t,
        method="dijkstra",
        policy=UnknownPolicy.ADMIT_AND_COUNT,
        criterion="duration",
    )
    view = search.view()
    assert view.objective == "duration"
    # The oracle applies the caps of article 14 to the raw lists.
    capped = {"motorway": 60.0, "road": 50.0, "urban": 30.0}
    oracle = [
        x / min(v, capped[k]) for x, v, k in zip(length, limit, kinds, strict=True)
    ]
    best = best_admissible(
        random_case(seed, n=7, m=18, unknown=0.0), s, t, [True] * graph.m, oracle
    )
    route = search.solve()
    if route.status is Status.INFEASIBLE:
        assert best == math.inf
        assert route.route is None
        return
    assert route.cost is not None
    assert route.arcs is not None
    assert math.isclose(route.cost, best)
    check = search.verify(route)
    on_route = {kinds[a] for a in route.arcs}
    for k in KINDS:
        expected = S.APPLIED if k in on_route else S.NOT_APPLICABLE
        assert check[f"OVERSIZE-SPEED-{k.upper()}"].status is expected
    assert check["OBJ"].status is S.APPLIED
    assert check["OBJ"].reason == (
        "objective 'duration', chosen: the fastest route was asked for; "
        "optimal (duration), checked by Bellman-Ford"
    )
    # A1: a solver that times the arcs at their own speed is caught: every
    # speed limit of the network is above the cap of its kind.
    free = [x / v for x, v in zip(length, limit, strict=True)]
    forgot = dijkstra(graph, free, s, t).path(t)
    assert forgot is not None
    blind = verify_route(
        forgot, reqs, graph, data, values, view=view, weights=free, criterion="duration"
    )
    for k in {kinds[a] for a in forgot}:
        assert blind[f"OVERSIZE-SPEED-{k.upper()}"].status is S.NOT_APPLIED
    impacts = {rid: search.impact(rid) for rid in search.ids}
    for k in on_route:
        delta = impacts[f"OVERSIZE-SPEED-{k.upper()}"].delta
        assert delta is not None
        assert delta >= 0
    rows = requirement_table(check, reqs, values, view=view, impacts=impacts)
    road = next(r for r in rows if r.id == "OVERSIZE-SPEED-ROAD").to_dict()
    assert road["source"]["locator"] == "art. 14"
    assert road["values"][0]["value"] == 50.0
    assert road["values"][0]["source"]["link"] == rv.rulebook.link
    assert road["family"] == "cost"
    json.dumps([r.to_dict() for r in rows])
    first = provenance(
        "dijkstra",
        {"unknown": "admit_and_count"},
        inputs={"graph": graph, "data": data, "weights": search.weights()},
        requirements=reqs,
        values=values,
        result=route,
    )
    again = provenance(
        "dijkstra",
        {"unknown": "admit_and_count"},
        inputs={"graph": graph, "data": data, "weights": list(search.weights())},
        requirements=reqs,
        values=values,
        result=search.solve(),
    )
    assert first == again
    assert first.replays(again)
    assert first.differences(again) == ()
    assert first.requirements[-1] == "OBJ"


def test_chosen_objective_needs_a_justification() -> None:
    # A12: a chosen objective without its justification is refused.
    with pytest.raises(ValueError, match="needs a justification"):
        chain_inputs(justification=None)


def test_prescribed_objective_and_objective_checks() -> None:
    rv = RulebookValues.load(OVERSIZE)
    reqs = RequirementSet((OBJECTIVE,), (Parameter("route_criterion"),), (PLANNER,))
    prescribed = ValueSet(
        "planner",
        "1",
        {"route_criterion": Value("length", PLANNER_SRC, Origin.STATEMENT)},
    )
    values = resolve_values([prescribed], reqs)
    graph = Digraph.from_arcs(2, [(0, 1)])
    data = ArcData(1, ())
    view = compose(graph, [evaluate(OBJECTIVE, graph, data, values)], policy="exclude")
    assert view.requirements_on(0) == ()
    check = verify_route(
        (0,), reqs, graph, data, values, view=view, weights=[1.0], criterion="length"
    )
    assert check["OBJ"].reason == (
        "objective 'length', prescribed (statement); optimal (length), "
        "checked by Bellman-Ford"
    )
    assert verify_route((0,), reqs, graph, data, values)["OBJ"].status is S.NOT_APPLIED
    report = check_inputs(reqs, graph, data, values)["OBJ"]
    assert report.expected is S.APPLIED
    assert report.reason == "checked on the weights or costs of the result"
    problem = FlowProblem(graph)
    assert (
        verify_flow([0], reqs, problem, data, values, criterion="length")["OBJ"].status
        is S.APPLIED
    )
    effects = [
        Effect("A", EffectKind.OBJECTIVE, 1, objective="length"),
        Effect("B", EffectKind.OBJECTIVE, 1, objective="duration"),
    ]
    with pytest.raises(ValueError, match="several objectives"):
        compose(graph, effects, policy="exclude")
    with pytest.raises(ValueError, match="criterion only"):
        Effect("A", EffectKind.OBJECTIVE, 1)
    with pytest.raises(ValueError, match="only an objective"):
        Effect("A", EffectKind.COST_TERM, 1, cap=np.ones(1), objective="x")
    with pytest.raises(ValueError, match="no array"):
        Effect("A", EffectKind.OBJECTIVE, 1, objective="x", not_applicable="to be set")
    numeric = ValueSet(
        "planner", "1", {"route_criterion": Value(3, PLANNER_SRC, Origin.STATEMENT)}
    )
    with pytest.raises(TypeError, match="must be a name"):
        evaluate(OBJECTIVE, graph, data, resolve_values([numeric], reqs))
    assert rv.rulebook.id == OVERSIZE


def test_flow_objective_is_checked_exactly_on_int_costs() -> None:
    # Int costs beyond the float range: the improving cycle is found, and
    # weighed, exactly.
    reqs = RequirementSet((OBJECTIVE,), (Parameter("route_criterion"),), (PLANNER,))
    length = Value("length", PLANNER_SRC, Origin.STATEMENT)
    values = resolve_values(
        [ValueSet("planner", "1", {"route_criterion": length})], reqs
    )
    data = ArcData(3, ())

    def check(problem: FlowProblem, flow: tuple[int, ...]) -> tuple[object, str]:
        found = verify_flow(flow, reqs, problem, data, values, criterion="length")
        return found["OBJ"].status, found["OBJ"].reason

    graph = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    huge = 10**400
    problem = FlowProblem(
        graph, upper=(1, 1, 1), cost=(huge, huge, 1), supply=(1, 0, -1)
    )
    assert check(problem, (0, 0, 1))[0] is S.APPLIED
    cycle = f"an improving cycle of 3 arcs exists (cost {1 - 2 * huge})"
    assert check(problem, (1, 1, 0)) == (S.NOT_APPLIED, cycle)
    # Beyond 2**53 already: as floats, the cycle would cost 0 and the empty
    # flow would be declared optimal.
    ring = Digraph.from_arcs(3, [(0, 1), (1, 2), (2, 0)])
    k = 2**53
    rounded = FlowProblem(ring, upper=(1, 1, 1), cost=(k, k, -1 - 2 * k))
    cycle = "an improving cycle of 3 arcs exists (cost -1)"
    assert check(rounded, (0, 0, 0)) == (S.NOT_APPLIED, cycle)


TOML = """
format = "protee-rulebook-values/0"
notice = "test"

[rulebook]
id = "book"
kind = "standard"
edition = "1"
title = { en = "Book" }

[[parameters]]
name = "limit"
unit = "t"
aliases = { book = "max_mass" }

[values.limit]
value = inf
unit = "t"
origin = "provisional"
locator = "p. 2"
"""


def test_toml_reading_and_errors() -> None:
    rv = RulebookValues.from_toml(TOML)
    limit = rv.values.values["limit"]
    assert limit.value == math.inf
    assert limit.origin is Origin.PROVISIONAL
    assert limit.source.document == "Book"
    assert rv.parameters[0].aliases == {"book": "max_mass"}
    with pytest.raises(ValueError, match="expected format"):
        RulebookValues.from_toml('format = "other"')
    with pytest.raises(TypeError, match="rulebook must be a table"):
        RulebookValues.from_toml(
            'format = "protee-rulebook-values/0"\nnotice = "n"\nrulebook = 1'
        )
    with pytest.raises(ValueError, match="undeclared parameter"):
        RulebookValues.from_toml(TOML.replace('name = "limit"', 'name = "other"'))
    with pytest.raises(ValueError, match="expected 't'"):
        RulebookValues.from_toml(
            TOML.replace('unit = "t"\norigin', 'unit = "kg"\norigin')
        )


@pytest.mark.parametrize(
    ("old", "new", "error"),
    [
        # A misspelt or unknown key is refused, never ignored.
        ("[values.limit]", "[value.limit]", "the document: unknown keys ['value']"),
        ('origin = "provisional"', "precedance = 5", "unknown keys ['precedance']"),
        ("value = inf", "amount = inf", "unknown keys ['amount']"),
        ('id = "book"', "", "rulebook: missing key 'id'"),
        ('name = "limit"', 'nom = "limit"', "unknown keys ['nom']"),
        ('notice = "test"', "", "missing key 'notice'"),
        ('notice = "test"', 'notice = " "', "where the values come from"),
        ('kind = "standard"', 'kind = "standard"\nedition2 = "x"', "edition2"),
    ],
)
def test_toml_reading_is_strict(old: str, new: str, error: str) -> None:
    assert old in TOML
    with pytest.raises(ValueError, match=re.escape(error)):
        RulebookValues.from_toml(TOML.replace(old, new))


def test_toml_without_a_parameter_name() -> None:
    with pytest.raises(
        ValueError, match=re.escape("parameters[0]: missing key 'name'")
    ):
        RulebookValues.from_toml(TOML.replace('name = "limit"\n', ""))
    with pytest.raises(ValueError, match="source: unknown keys"):
        RulebookValues.from_toml(TOML + '\n[source]\nedition = "2"\n')


# Provenance ----------------------------------------------------------------


def test_fingerprint_is_canonical_and_sensitive() -> None:
    # A11: same input, same fingerprint; a modified input changes it.
    a = random_case(1).data()
    assert fingerprint(a) == fingerprint(random_case(1).data())
    assert fingerprint(a) != fingerprint(random_case(2).data())
    assert fingerprint({"b": 1, "a": 2}) == fingerprint({"a": 2, "b": 1})
    assert fingerprint(frozenset({"x", "y"})) == fingerprint(frozenset({"y", "x"}))
    assert fingerprint(1.0) != fingerprint(1)
    # Types that JSON would confuse are told apart.
    assert fingerprint(1.5) != fingerprint("1.5")
    assert fingerprint(math.inf) != fingerprint("inf")
    assert fingerprint(math.nan) != fingerprint("nan")
    assert fingerprint(frozenset({1, 2})) != fingerprint([1, 2])
    assert fingerprint({1: "a"}) != fingerprint({"1": "a"})
    assert fingerprint({1: "a", "1": "b"}) != fingerprint({"1": "b"})
    # A tuple and a list with the same items are the same sequence.
    assert fingerprint((1, 2)) == fingerprint([1, 2])
    assert fingerprint(
        math.inf,
        np.float64(2.0),
        np.int64(3),
        np.arange(3),
        UnknownPolicy.EXCLUDE,
        None,
    )
    assert fingerprint(Shade.DARK) == fingerprint(2)
    assert fingerprint(np.arange(3, dtype=np.int8)) != fingerprint(
        np.arange(3, dtype=np.int16)
    )
    with pytest.raises(TypeError, match="no canonical form"):
        fingerprint(object())


def test_provenance_keeps_both_values_and_reports_a_different_replay() -> None:
    # A5 and A11: the discarded value stays in the provenance; a replay
    # from the same inputs with another result is reported.
    reqs = requirement_set()
    doctrine = ValueSet(
        "doc-b",
        "2019",
        {
            "vehicle_mass": Value(
                60.0,
                Source("Doctrine B", rulebook="doc-b", edition="2019"),
                Origin.RULEBOOK,
                unit="t",
                precedence=1,
            )
        },
    )
    from constraints_cases import values as reg_values

    values = resolve_values([reg_values(), doctrine], reqs)
    p = provenance(
        "dijkstra",
        {},
        inputs={},
        requirements=reqs,
        values=values,
        result=(1, 2),
        counters={"pops": 3},
    )
    assert ("vehicle_mass", "doc-b", "2019", True) in p.values
    assert ("vehicle_mass", "reg-a", "2006", False) in p.values
    assert p.counters == {"pops": 3}
    q = provenance(
        "dijkstra", {}, inputs={}, requirements=reqs, values=values, result=(1, 3)
    )
    assert p.replays(q)
    assert p.differences(q) == ("result",)
    r = provenance(
        "bellman_ford",
        {},
        inputs={},
        requirements=reqs,
        values=resolved(),
        result=(1, 2),
    )
    assert not p.replays(r)
    assert set(p.differences(r)) == {"method", "inputs"}
    assert isinstance(p, Provenance)


def test_provenance_of_a_result_on_the_common_model() -> None:
    # A result built on ResultCore gives its method, parameters, counters
    # and version; the fingerprint of its own inputs tells apart two
    # problems whose methods share a name.
    _, reqs, values = chain_inputs()
    ids = tuple(r.id for r in reqs)
    blocked = frozenset({"OVERSIZE-SPEED-ROAD", "OBJ"})

    def feasible(active: frozenset[str]) -> bool:
        return not blocked <= active

    def record(
        result: object,
        method: str | None = None,
        parameters: Mapping[str, object] | None = None,
        counters: Mapping[str, int] | None = None,
    ) -> Provenance:
        return provenance(
            method,
            parameters,
            inputs={"ids": ids},
            requirements=reqs,
            values=values,
            result=result,
            counters=counters,
        )

    conflict = minimal_conflict(ids, feasible, method="deletion_filter")
    p = record(conflict)
    assert (p.method, dict(p.parameters), p.version) == (
        "deletion_filter",
        {},
        conflict.version,
    )
    assert dict(p.counters) == dict(conflict.counters)
    again = record(minimal_conflict(ids, feasible, method="deletion_filter"))
    assert p == again
    assert p.replays(again)
    # A provenance is a value, as a result is: it pickles, copies, hashes.
    assert pickle.loads(pickle.dumps(p)) == p == copy.deepcopy(p)
    assert hash(p) == hash(again)
    assert {p, again} == {p}
    exact = record(minimal_conflict(ids, feasible, method="enumeration"))
    assert not p.replays(exact)
    assert set(p.differences(exact)) == {"method", "inputs", "result"}
    relaxation = record(minimal_relaxation(ids, feasible, method="enumeration"))
    assert relaxation.method == exact.method
    assert not relaxation.replays(exact)
    # Given explicitly, the parameters and counters are recorded as given;
    # another method than the result's is refused.
    explicit = record(conflict, method="deletion_filter", parameters={"note": 1})
    assert dict(explicit.parameters) == {"note": 1}
    assert not explicit.replays(p)
    assert dict(record(conflict, counters={}).counters) == {}
    with pytest.raises(ValueError, match="produced by 'deletion_filter'"):
        record(conflict, method="enumeration")
    with pytest.raises(TypeError, match="needs its method and parameters"):
        record((1, 2))
    with pytest.raises(TypeError, match="needs its method and parameters"):
        record((1, 2), method="dijkstra")


def test_provenance_keeps_the_edition_and_freezes_its_parameters() -> None:
    # The values of two editions, given without rulebook in their source,
    # keep the edition of their set: the provenances differ.
    reqs = requirement_set()

    def record(edition: str) -> Provenance:
        vs = ValueSet(
            "doc-b",
            edition,
            {
                "vehicle_mass": Value(
                    60.0, Source("Doctrine B"), Origin.RULEBOOK, unit="t"
                )
            },
        )
        return provenance(
            "dijkstra",
            {
                "weights": [1, 2],
                "options": {"tolerance": 0.0},
                "kinds": {"road"},
                "base": np.arange(2),
            },
            inputs={},
            requirements=reqs,
            values=resolve_values([vs], reqs),
            result=(),
        )

    old, new = record("2019"), record("2023")
    assert old.values == (("vehicle_mass", "doc-b", "2019", True),)
    assert new.values == (("vehicle_mass", "doc-b", "2023", True),)
    assert not old.replays(new)
    assert old.parameters["weights"] == (1, 2)
    assert old.parameters["kinds"] == frozenset({"road"})
    with pytest.raises(TypeError):
        old.parameters["options"]["tolerance"] = 1.0  # type: ignore[index]
    with pytest.raises(ValueError, match="read-only"):
        old.parameters["base"][0] = 1  # type: ignore[index]
