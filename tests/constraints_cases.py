# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Shared cases for the tests of :mod:`protee.constraints`.

- a small vocabulary: two rulebooks, parameters with aliases and units;
- requirement builders for each pattern of the registry;
- seeded synthetic graphs with partially unknown arc attributes;
- independent oracles in pure Python: verdicts read from the raw lists,
  and shortest admissible paths by enumeration of simple paths.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from protee.constraints import (
    ArcData,
    Attribute,
    Origin,
    Parameter,
    Requirement,
    RequirementSet,
    ResolvedValues,
    Rulebook,
    RulebookKind,
    Source,
    Value,
    ValueSet,
    resolve_values,
)
from protee.graph import Digraph

REG = Rulebook(
    "reg-a",
    RulebookKind.REGULATION,
    {"en": "Regulation A", "fr": "Règlement A"},
    "2006",
    link="https://example.org/reg-a",
)
DOC = Rulebook("doc-b", RulebookKind.DOCTRINE, {"en": "Doctrine B"}, "2019")
SRC = Source("Regulation A", rulebook="reg-a", edition="2006", locator="art. 3")
DOC_SRC = Source("Doctrine B", rulebook="doc-b", edition="2019", locator="ch. 2")
ELEMENTS = ("road", "bridge", "underpass")
CLASSES = ("C30", "C50", "C70")

PARAMETERS = (
    Parameter("vehicle_mass", unit="t", aliases={"reg-a": "total_mass"}),
    Parameter("vehicle_height", unit="m"),
    Parameter("required_load_class"),
    Parameter("speed_max", unit="km/h"),
    Parameter("occurrence_max"),
    Parameter("occurrence_min"),
    Parameter("unused_width", unit="m"),
    Parameter("fording_depth", unit="m"),
)


def value(x: float | str | None, unit: str | None = None, precedence: int = 0) -> Value:
    """A value of regulation A."""
    return Value(x, SRC, Origin.RULEBOOK, unit=unit, precedence=precedence)


def requirement(
    id: str,
    pattern: str,
    *,
    parameters: Mapping[str, str] | None = None,
    attributes: Mapping[str, str] | None = None,
    scope: Sequence[str] | None = None,
) -> Requirement:
    """A requirement of regulation A with a generated statement."""
    return Requirement(
        id,
        pattern,
        {"en": f"Requirement {id}", "fr": f"Exigence {id}"},
        SRC,
        parameters=parameters or {},
        attributes=attributes or {},
        scope=None if scope is None else frozenset(scope),
    )


MASS = requirement(
    "ADM-MASS",
    "threshold_admissibility",
    parameters={"quantity": "vehicle_mass"},
    attributes={"limit": "mass_limit"},
    scope=["bridge"],
)
HEIGHT = requirement(
    "ADM-HEIGHT",
    "threshold_admissibility",
    parameters={"quantity": "vehicle_height"},
    attributes={"limit": "clearance"},
    scope=["underpass"],
)
CLASS = requirement(
    "ADM-CLASS",
    "class_admissibility",
    parameters={"required_class": "required_load_class"},
    attributes={"class": "load_class"},
    scope=["bridge"],
)
ZONE = requirement("ADM-ZONE", "zone_exclusion", attributes={"inside": "in_zone"})
SPEED = requirement(
    "COST-SPEED",
    "speed_cap",
    parameters={"maximum": "speed_max"},
    attributes={"length": "length", "speed": "speed_limit"},
    scope=["road"],
)
#: A ford on a road: the depth of water the arc demands is at most the
#: depth the vehicle can ford.
CAPACITY = requirement(
    "ADM-DEPTH",
    "capacity_admissibility",
    parameters={"capacity": "fording_depth"},
    attributes={"demand": "water_depth"},
    scope=["road"],
)
ROUTING = (MASS, HEIGHT, CLASS, ZONE, SPEED)
VERDICT_REQUIREMENTS = (MASS, HEIGHT, CLASS, ZONE)


def requirement_set(requirements: Sequence[Requirement] = ROUTING) -> RequirementSet:
    return RequirementSet(tuple(requirements), PARAMETERS, (REG, DOC))


def values(
    mass: float | None = 44.0,
    height: float | None = 4.0,
    load_class: str | None = "C50",
    speed: float | str | None = 50.0,
) -> ValueSet:
    return ValueSet(
        "reg-a",
        "2006",
        {
            "total_mass": value(mass, "t"),
            "vehicle_height": value(height, "m"),
            "required_load_class": value(load_class),
            "speed_max": value(speed, "km/h"),
        },
    )


def resolved(
    requirements: RequirementSet | None = None,
    *,
    mass: float | None = 44.0,
    height: float | None = 4.0,
    load_class: str | None = "C50",
    speed: float | str | None = 50.0,
) -> ResolvedValues:
    reqs = requirement_set() if requirements is None else requirements
    return resolve_values([values(mass, height, load_class, speed)], reqs)


def fording(depth: float | str | None) -> tuple[RequirementSet, ResolvedValues]:
    """:data:`CAPACITY` alone, and the depth the vehicle can ford (``None``
    to be set)."""
    reqs = requirement_set((CAPACITY,))
    vs = ValueSet("reg-a", "2006", {"fording_depth": value(depth, "m")})
    return reqs, resolve_values([vs], reqs)


@dataclass(frozen=True)
class Case:
    """A graph with raw arc attributes (``None`` for unknown)."""

    graph: Digraph
    element: list[str | None]
    mass_limit: list[float | None]
    clearance: list[float | None]
    load_class: list[str | None]
    in_zone: list[float | None]
    length: list[float]
    speed: list[float]

    def data(self) -> ArcData:
        return ArcData(
            self.graph.m,
            (
                Attribute.categorical("element", self.element, ELEMENTS),
                Attribute.numeric("mass_limit", self.mass_limit, unit="t", source=SRC),
                Attribute.numeric("clearance", self.clearance, unit="m"),
                Attribute.categorical("load_class", self.load_class, CLASSES),
                Attribute.numeric("in_zone", self.in_zone),
                Attribute.numeric("length", self.length, unit="km"),
                Attribute.numeric("speed_limit", self.speed, unit="km/h"),
            ),
            element="element",
        )

    def times(self, cap: float = 50.0) -> list[float]:
        """Travel times under the speed cap of the roads, from the raw
        lists: an arc of unknown element is presumed a road."""
        return [
            x / (min(v, cap) if e in (None, "road") else v)
            for x, v, e in zip(self.length, self.speed, self.element, strict=True)
        ]


def random_case(seed: int, n: int = 6, m: int = 14, unknown: float = 0.25) -> Case:
    """A seeded random graph; each attribute is unknown with probability
    ``unknown``."""
    rng = random.Random(seed)
    arcs: list[tuple[int, int]] = []
    while len(arcs) < m:
        t, h = rng.randrange(n), rng.randrange(n)
        if t != h:
            arcs.append((t, h))
    graph = Digraph.from_arcs(n, arcs)

    def maybe[T](x: T) -> T | None:
        return None if rng.random() < unknown else x

    return Case(
        graph=graph,
        element=[maybe(rng.choice(ELEMENTS)) for _ in arcs],
        mass_limit=[maybe(float(rng.choice((30, 40, 60, 80)))) for _ in arcs],
        clearance=[maybe(rng.choice((3.5, 4.2, 5.0))) for _ in arcs],
        load_class=[maybe(rng.choice(CLASSES)) for _ in arcs],
        in_zone=[maybe(float(rng.random() < 0.15)) for _ in arcs],
        length=[float(rng.randint(1, 9)) for _ in arcs],
        speed=[float(rng.choice((30, 50, 80, 130))) for _ in arcs],
    )


def endpoints(seed: int, n: int) -> tuple[int, int]:
    """A source and a target, drawn apart from the graph of the same seed."""
    s, t = random.Random(f"endpoints-{seed}").sample(range(n), 2)
    return s, t


FAIL, UNKNOWN, PASS = 0, 1, 2


def oracle_verdict(
    case: Case,
    arc: int,
    *,
    mass: float = 44.0,
    height: float = 4.0,
    load_class: str = "C50",
) -> int:
    """Kleene conjunction of the routing verdicts of an arc, from the raw
    lists, without NumPy."""
    element = case.element[arc]
    verdicts = []

    def in_scope(scope: tuple[str, ...]) -> bool:
        return element is None or element in scope

    if in_scope(("bridge",)):
        limit = case.mass_limit[arc]
        verdicts.append(UNKNOWN if limit is None else PASS if mass <= limit else FAIL)
        cls = case.load_class[arc]
        verdicts.append(
            UNKNOWN
            if cls is None
            else PASS
            if CLASSES.index(cls) >= CLASSES.index(load_class)
            else FAIL
        )
    if in_scope(("underpass",)):
        c = case.clearance[arc]
        verdicts.append(UNKNOWN if c is None else PASS if height <= c else FAIL)
    z = case.in_zone[arc]
    verdicts.append(UNKNOWN if z is None else FAIL if z == 1.0 else PASS)
    return min(verdicts)


def simple_paths(graph: Digraph, s: int, t: int) -> Iterator[tuple[int, ...]]:
    """Every simple path from ``s`` to ``t``, as arcs."""

    def walk(
        v: int, seen: frozenset[int], arcs: tuple[int, ...]
    ) -> Iterator[tuple[int, ...]]:
        if v == t:
            yield arcs
            return
        for a in graph.out_arcs(v):
            w = graph.heads[a]
            if w not in seen:
                yield from walk(w, seen | {w}, (*arcs, a))

    yield from walk(s, frozenset({s}), ())


def best_admissible(
    case: Case, s: int, t: int, admissible: Sequence[bool], weight: Sequence[float]
) -> float:
    """Least weight of a simple path using admissible arcs only."""
    costs = [
        sum(weight[a] for a in p)
        for p in simple_paths(case.graph, s, t)
        if all(admissible[a] for a in p)
    ]
    return min(costs, default=math.inf)


# Life-cycle profile ------------------------------------------------------
#
#   a0 L01: 0 -> 1   a1 L02: 1 -> 2   a2 L03: 2 -> 1 (loop)
#   a3 L04: 1 -> 3   a4 L05: 2 -> 3   a5 L06: 3 -> 0 (return, 1..1)

PROFILE = Digraph.from_arcs(4, [(0, 1), (1, 2), (2, 1), (1, 3), (2, 3), (3, 0)])
LINKS = ("L01", "L02", "L03", "L04", "L05", "L06")
CLIENT = Rulebook(
    "client", RulebookKind.CLIENT_SPECIFICATION, {"en": "Client specification"}, "1"
)
CLIENT_SRC = Source("Specification of use", rulebook="client", edition="1")
OCC_PARAMETERS = (
    Parameter("occ_all"),
    Parameter("occ_l03"),
    Parameter("occ_l02"),
    Parameter("one"),
    Parameter("three"),
    Parameter("zero"),
)


def occurrence(
    id: str, maximum: str, scope: list[str] | None, minimum: str | None = None
) -> Requirement:
    params = {"maximum": maximum} | ({} if minimum is None else {"minimum": minimum})
    return requirement(id, "occurrence_bounds", parameters=params, scope=scope)


OC_ALL = occurrence("OC-ALL", "occ_all", None)
OC_L03 = occurrence("OC-L03", "occ_l03", ["L03"])
RETURN = occurrence("RETURN", "one", ["L06"], minimum="one")
OC_INF = occurrence("OC-L02", "occ_l02", ["L02"])
MIN_L03 = occurrence("MIN-L03", "three", ["L03"], minimum="three")


def profile(
    *requirements: Requirement,
) -> tuple[RequirementSet, ArcData, ResolvedValues]:
    reqs = RequirementSet(requirements, (*PARAMETERS, *OCC_PARAMETERS), (REG, CLIENT))
    spec = ValueSet(
        "client",
        "1",
        {
            "occ_all": Value(4, CLIENT_SRC, Origin.STATEMENT),
            "occ_l03": Value(2, CLIENT_SRC, Origin.STATEMENT),
            "occ_l02": Value(math.inf, CLIENT_SRC, Origin.STATEMENT),
            "one": Value(1, CLIENT_SRC, Origin.STATEMENT),
            "three": Value(3, CLIENT_SRC, Origin.STATEMENT),
            "zero": Value(0, CLIENT_SRC, Origin.STATEMENT),
        },
    )
    data = ArcData(
        6,
        (
            Attribute.categorical("link", list(LINKS), LINKS),
            Attribute.numeric("in_zone", [0, 0, 0, 1, None, 0]),
        ),
        element="link",
    )
    return reqs, data, resolve_values([spec], reqs)
