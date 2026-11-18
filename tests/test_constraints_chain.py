# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""From a public text to a verified route: embedded values, TOML,
declared objective and provenance."""

import enum
import json
import math
import random

import numpy as np
import pytest
from constraints_cases import best_admissible, random_case, requirement_set, resolved

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
    Rulebook,
    RulebookKind,
    RulebookValues,
    Source,
    UnknownPolicy,
    Value,
    ValueSet,
    compose,
    evaluate,
    fingerprint,
    provenance,
    requirement_table,
    resolve_values,
    verify_flow,
    verify_route,
)
from protee.flow import FlowProblem
from protee.graph import Digraph
from protee.paths import dijkstra
from protee.routes import Route

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
    view = compose(
        graph,
        [evaluate(r, graph, data, values) for r in reqs],
        unknown="admit_and_count",
    )
    assert view.objective == "duration"
    hours = [x / min(v, c) for x, v, c in zip(length, limit, view.cap, strict=True)]
    rng = random.Random(seed)
    s, t = rng.sample(range(graph.n), 2)
    capped = {"motorway": 60.0, "road": 50.0, "urban": 30.0}
    oracle = [x / capped[k] for x, k in zip(length, kinds, strict=True)]
    best = best_admissible(
        random_case(seed, n=7, m=18, unknown=0.0), s, t, [True] * graph.m, oracle
    )
    sp = dijkstra(graph, hours, s, t, excluded=view.excluded)
    assert math.isclose(sp.distance[t], best) or sp.distance[t] == best == math.inf
    path = sp.path(t)
    if path is None:
        return
    route = Route(arcs=path, cost=sp.distance[t])
    check = verify_route(route, reqs, graph, data, values, view=view)
    on_route = {kinds[a] for a in path}
    for k in KINDS:
        expected = S.APPLIED if k in on_route else S.NOT_APPLICABLE
        assert check[f"OVERSIZE-SPEED-{k.upper()}"].status is expected
    assert check["OBJ"].status is S.APPLIED
    assert (
        check["OBJ"].reason
        == "objective 'duration', chosen: the fastest route was asked for"
    )
    rows = requirement_table(check, reqs, values, view=view)
    road = next(r for r in rows if r.id == "OVERSIZE-SPEED-ROAD").to_dict()
    assert road["source"]["locator"] == "art. 14"
    assert road["value"][0]["value"] == 50.0
    assert road["value"][0]["source"]["link"] == rv.rulebook.link
    assert road["family"] == "cost"
    json.dumps([r.to_dict() for r in rows])
    first = provenance(
        "dijkstra",
        {"unknown": "admit_and_count"},
        inputs={"graph": graph, "data": data, "hours": hours},
        requirements=reqs,
        values=values,
        result=route,
    )
    again = provenance(
        "dijkstra",
        {"unknown": "admit_and_count"},
        inputs={"graph": graph, "data": data, "hours": list(hours)},
        requirements=reqs,
        values=values,
        result=Route(arcs=path, cost=sp.distance[t]),
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
    view = compose(graph, [evaluate(OBJECTIVE, graph, data, values)], unknown="exclude")
    assert view.requirements_on(0) == ()
    assert verify_route((0,), reqs, graph, data, values, view=view)["OBJ"].reason == (
        "objective 'length', prescribed (statement)"
    )
    assert verify_route((0,), reqs, graph, data, values)["OBJ"].status is S.NOT_APPLIED
    other = compose(graph, [], unknown="exclude")
    assert (
        "optimizes None"
        in verify_route((0,), reqs, graph, data, values, view=other)["OBJ"].reason
    )
    problem = FlowProblem(graph)
    assert (
        verify_flow([0], problem, reqs, data, values, view=view)["OBJ"].status
        is S.APPLIED
    )
    effects = [
        Effect("A", EffectKind.OBJECTIVE, 1, objective="length"),
        Effect("B", EffectKind.OBJECTIVE, 1, objective="duration"),
    ]
    with pytest.raises(ValueError, match="several objectives"):
        compose(graph, effects, unknown="exclude")
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
        RulebookValues.from_toml('format = "protee-rulebook-values/0"\nrulebook = 1')
    with pytest.raises(ValueError, match="undeclared parameter"):
        RulebookValues.from_toml(TOML.replace('name = "limit"', 'name = "other"'))
    with pytest.raises(ValueError, match="expected 't'"):
        RulebookValues.from_toml(
            TOML.replace('unit = "t"\norigin', 'unit = "kg"\norigin')
        )


# Provenance ----------------------------------------------------------------


def test_fingerprint_is_canonical_and_sensitive() -> None:
    # A11: same input, same fingerprint; a modified input changes it.
    a = random_case(1).data()
    assert fingerprint(a) == fingerprint(random_case(1).data())
    assert fingerprint(a) != fingerprint(random_case(2).data())
    assert fingerprint({"b": 1, "a": 2}) == fingerprint({"a": 2, "b": 1})
    assert fingerprint(frozenset({"x", "y"})) == fingerprint(frozenset({"y", "x"}))
    assert fingerprint(1.0) != fingerprint(1)
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
