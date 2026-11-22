# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The node-link exchange format ``protee-node-link/0``.

The examples are written the way a producer that does not depend on protee
would write them: a branch of a tree of quantity kinds, and a system of
equations with a loop.
"""

import copy
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import networkx as nx
import pytest
from constraints_cases import LINKS, PROFILE
from hypothesis import given
from oracles import graphs

from protee import io
from protee.graph import Digraph

SKOS = "http://www.w3.org/2004/02/skos/core#"

#: A branch of a tree of quantity kinds, with a correspondence to CF.
KINDS: dict[str, Any] = {
    "directed": True,
    "multigraph": True,
    "graph": {
        "format": "protee-node-link/0",
        "producer": {"name": "example", "version": "1"},
        "prefixes": {
            "skos": SKOS,
            "qudt": "http://qudt.org/schema/qudt/",
            "example": None,
        },
        "vocabulary": {
            "type": [
                {"id": "example:kind", "on": "node", "label": "quantity kind"},
                {"id": "example:external", "on": "node", "label": "external name"},
                {"id": "qudt:specializationOf", "on": "edge", "label": "specializes"},
                {
                    "id": "skos:exactMatch",
                    "on": "edge",
                    "label": "same notion",
                    "symmetric": True,
                },
            ],
            "status": [
                {"id": "verified", "on": "node", "label": "verified"},
                {
                    "id": "to-confirm",
                    "on": "node",
                    "label": "to confirm",
                    "description": "source not read yet",
                },
            ],
        },
    },
    "nodes": [
        {
            "id": "k.humidity",
            "label": "Humidity",
            "type": "example:kind",
            "family": "humidity",
            "status": "verified",
        },
        {
            "id": "k.relative",
            "label": "Relative humidity",
            "type": "example:kind",
            "family": "humidity",
            "status": "verified",
            "iri": "http://qudt.org/vocab/quantitykind/RelativeHumidity",
            "url": "https://example.org/k#relative",
            "description": "partial pressure of water vapour over saturation",
        },
        {
            "id": "k.specific",
            "label": "Specific humidity",
            "type": "example:kind",
            "family": "humidity",
            "status": "to-confirm",
            "metrics": {"formulations": 4, "spread": "inf", "gap": None},
        },
        {
            "id": "ext.rh",
            "label": "relative_humidity",
            "type": "example:external",
        },
    ],
    "edges": [
        {
            "source": "k.relative",
            "target": "k.humidity",
            "key": 0,
            "type": "qudt:specializationOf",
        },
        {
            "source": "k.specific",
            "target": "k.humidity",
            "key": 0,
            "type": "qudt:specializationOf",
        },
        {
            "source": "k.relative",
            "target": "ext.rh",
            "key": 0,
            "type": "skos:exactMatch",
            "metrics": {"checked": 1},
        },
    ],
}

#: A system of equations: eq.1 reads u before eq.2 gives it, hence a loop.
SYSTEM: dict[str, Any] = {
    "directed": True,
    "multigraph": False,
    "graph": {
        "format": "protee-node-link/0",
        "producer": {"name": "example"},
        "prefixes": {"example": None},
        "vocabulary": {
            "type": [
                {"id": "example:equation", "on": "node", "label": "equation"},
                {"id": "example:variable", "on": "node", "label": "variable"},
                {"id": "example:gives", "on": "edge", "label": "gives"},
                {"id": "example:reads", "on": "edge", "label": "reads"},
            ],
            "role": [
                {"id": "example:input", "on": "node", "label": "input"},
                {
                    "id": "example:unknown",
                    "on": "node",
                    "label": "unknown",
                    "description": "read before the equation that gives it",
                },
                {"id": "example:intermediate", "on": "node", "label": "intermediate"},
            ],
        },
    },
    "nodes": [
        {"id": "eq.1", "type": "example:equation", "rank": 1},
        {"id": "eq.2", "type": "example:equation", "rank": 2},
        {"id": "x", "type": "example:variable", "role": "example:input"},
        {"id": "u", "type": "example:variable", "role": "example:unknown"},
        {"id": "v", "type": "example:variable", "role": "example:intermediate"},
    ],
    "edges": [
        {"source": "x", "target": "eq.1", "type": "example:reads"},
        {"source": "u", "target": "eq.1", "type": "example:reads"},
        {"source": "eq.1", "target": "v", "type": "example:gives"},
        {"source": "v", "target": "eq.2", "type": "example:reads"},
        {"source": "eq.2", "target": "u", "type": "example:gives"},
    ],
}

EXAMPLES = {"kinds": KINDS, "system": SYSTEM}


def rewritten(table: io.Table) -> dict[str, Any]:
    return io.to_node_link(
        table.graph,
        table.arcs,
        table.nodes,
        attributes=table.attributes,
        multigraph=table.multigraph,
    )


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_follow_the_format(name: str) -> None:
    assert io.check_node_link(EXAMPLES[name]) == ()


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_round_trip_without_loss(name: str, tmp_path: Path) -> None:
    data = EXAMPLES[name]
    expected = copy.deepcopy(data)
    for a, edge in enumerate(expected["edges"]):
        edge.setdefault("key", a)  # protee numbers the edges without a key
    assert rewritten(io.from_node_link(data)) == expected
    path = tmp_path / f"{name}.json"
    table = io.from_node_link(data)
    io.write_node_link(
        path,
        table.graph,
        table.arcs,
        table.nodes,
        attributes=table.attributes,
        multigraph=table.multigraph,
    )
    again = io.read_node_link(path)
    assert rewritten(again) == expected
    assert io.check_node_link(expected) == ()


#: Written by nomogram 0.8.0 from its catalogue, kept verbatim: the branch
#: of relative humidity, with node identifiers that are IRIs.
NOMOGRAM = Path(__file__).parent / "data" / "node_link"


def test_nomogram_extract_follows_the_format_and_round_trips() -> None:
    data = json.loads(
        (NOMOGRAM / "nomogram-0.8.0-relative-humidity.json").read_text(encoding="utf-8")
    )
    assert io.check_node_link(data) == ()
    assert rewritten(io.from_node_link(data)) == data
    g = nx.node_link_graph(data, edges="edges")
    assert nx.node_link_data(g, edges="edges") == data


def test_networkx_reads_the_examples_and_finds_the_loop() -> None:
    kinds = nx.node_link_graph(KINDS, edges="edges")
    assert (kinds.number_of_nodes(), kinds.number_of_edges()) == (4, 3)
    assert kinds.graph["format"] == io.NODE_LINK_FORMAT
    system = nx.node_link_graph(SYSTEM, edges="edges")
    loops = [c for c in nx.strongly_connected_components(system) if len(c) > 1]
    assert loops == [{"u", "eq.1", "v", "eq.2"}]


def test_a_profile_written_by_protee_follows_the_format() -> None:
    attributes = {
        "producer": {"name": "protee"},
        "prefixes": {"protee": None},
        "vocabulary": {"type": [{"id": "protee:link", "on": "edge", "label": "link"}]},
    }
    data = io.to_node_link(
        PROFILE,
        arcs={"link": LINKS, "type": ["protee:link"] * PROFILE.m},
        attributes=attributes,
    )
    assert data["graph"]["format"] == io.NODE_LINK_FORMAT
    assert io.check_node_link(data) == ()
    assert nx.node_link_graph(data, edges="edges").number_of_edges() == PROFILE.m


@given(graph=graphs())
def test_every_written_graph_follows_the_format(graph: Digraph) -> None:
    data = io.to_node_link(graph, arcs={"cost": list(range(graph.m))})
    assert io.check_node_link(data) == ()


def test_links_is_read_in_place_of_edges() -> None:
    data = copy.deepcopy(KINDS)
    data["links"] = data.pop("edges")
    assert io.check_node_link(data) == ()


def test_writing_refuses_another_format_and_false_multigraphs() -> None:
    g = Digraph.from_arcs(2, [(0, 1), (0, 1)])
    with pytest.raises(ValueError, match="is not 'protee-node-link/0'"):
        io.to_node_link(g, attributes={"format": "other/1"})
    with pytest.raises(ValueError, match="parallel arcs"):
        io.to_node_link(g, multigraph=False)


def test_tables_read_from_a_document_are_read_only() -> None:
    table = io.from_node_link(KINDS)
    with pytest.raises(TypeError):
        table.attributes["format"] = "other/1"  # type: ignore[index]
    metrics = table.nodes["metrics"][2]
    assert metrics["formulations"] == 4
    with pytest.raises(TypeError):
        metrics["formulations"] = 5
    assert table.multigraph is True
    assert io.from_node_link(SYSTEM).multigraph is False


Change = Callable[[dict[str, Any]], object]


def setting(path: str, value: object) -> Change:
    """Set ``value`` at a dotted path (integers index lists)."""

    def change(doc: dict[str, Any]) -> None:
        *head, last = path.split(".")
        node: Any = doc
        for part in head:
            node = node[int(part)] if part.isdigit() else node[part]
        node[int(last) if last.isdigit() else last] = value

    return change


def removing(path: str) -> Change:
    def change(doc: dict[str, Any]) -> None:
        *head, last = path.split(".")
        node: Any = doc
        for part in head:
            node = node[int(part)] if part.isdigit() else node[part]
        del node[last]

    return change


def appending(path: str, value: object) -> Change:
    def change(doc: dict[str, Any]) -> None:
        node: Any = doc
        for part in path.split("."):
            node = node[int(part)] if part.isdigit() else node[part]
        node.append(value)

    return change


DEPARTURES: list[tuple[str, Change, str]] = [
    ("not directed", setting("directed", False), "directed: must be true"),
    ("no multigraph", removing("multigraph"), "multigraph: must be"),
    ("no graph", removing("graph"), "graph: missing"),
    ("format", setting("graph.format", "node-link/1"), "graph.format: must be"),
    ("language", setting("graph.language", "english!"), "graph.language"),
    ("a region is allowed", setting("graph.language", "fr-FR"), ""),
    ("graph label", setting("graph.label", 3), "graph.label: must be a text"),
    ("a graph title", setting("graph.description", "Surface layer"), ""),
    (
        "one value on nodes and on edges",
        appending(
            "graph.vocabulary.status",
            {"id": "verified", "on": "edge", "label": "checked correspondence"},
        ),
        "",
    ),
    (
        "an IRI is a node id",
        setting("nodes.3.id", "https://example.org/ext/rh/"),
        "edges[2].target",  # the edge still names the old id
    ),
    ("producer", setting("graph.producer", {"name": 3}), "graph.producer"),
    ("prefixes", setting("graph.prefixes", []), "graph.prefixes: must be an object"),
    ("prefix name", setting("graph.prefixes.a:b", None), "a prefix is a non-empty"),
    (
        "prefix iri",
        setting("graph.prefixes.skos", "skos-core"),
        "absolute IRI, or null",
    ),
    ("vocabulary", setting("graph.vocabulary", []), "graph.vocabulary: must be an"),
    ("structural", setting("graph.vocabulary.key", []), "structural key"),
    ("entries", setting("graph.vocabulary.status", {}), "must be a list"),
    ("entry", appending("graph.vocabulary.status", "draft"), "must be an object"),
    ("on", setting("graph.vocabulary.status.0.on", "graph"), "'on' must be"),
    ("label", removing("graph.vocabulary.status.0.label"), "needs a text 'label'"),
    (
        "description",
        setting("graph.vocabulary.status.1.description", 2),
        "'description' must be a text",
    ),
    (
        "symmetric on a node",
        setting("graph.vocabulary.status.0.symmetric", True),
        "'symmetric' is a boolean, for edges only",
    ),
    ("empty id", setting("graph.vocabulary.status.0.id", ""), "a non-empty text"),
    (
        "undeclared prefix",
        setting("graph.vocabulary.type.0.id", "dc:kind"),
        "prefix 'dc' is not declared",
    ),
    (
        "declared twice",
        appending(
            "graph.vocabulary.status", {"id": "verified", "on": "node", "label": "x"}
        ),
        "declared twice",
    ),
    ("nodes", setting("nodes", {}), "nodes: missing"),
    ("node", setting("nodes.0", "k.humidity"), "nodes[0]: must be an object"),
    ("node id", setting("nodes.0.id", True), "nodes[0].id: must be a text"),
    ("repeated id", setting("nodes.1.id", "k.humidity"), "is repeated"),
    ("node iri", setting("nodes.1.iri", "quantitykind/RH"), "nodes[1].iri"),
    ("node label", setting("nodes.0.label", 7), "nodes[0].label: must be a text"),
    ("metrics", setting("nodes.2.metrics", [4]), "nodes[2].metrics: must be an obj"),
    ("metric", setting("nodes.2.metrics.formulations", math.nan), "finite number"),
    ("metric text", setting("nodes.2.metrics.formulations", "4"), "finite number"),
    (
        "undeclared type",
        setting("nodes.0.type", "example:formulation"),
        "is not declared for nodes",
    ),
    (
        "node type on an edge",
        setting("edges.0.type", "example:kind"),
        "is not declared for edges",
    ),
    ("edges", setting("edges", None), "edges: missing"),
    ("edge", setting("edges.0", 1), "edges[0]: must be an object"),
    ("source", setting("edges.0.source", "k.pressure"), "edges[0].source"),
    ("list end", setting("edges.0.target", ["k.humidity"]), "edges[0].target"),
    ("key", setting("edges.0.key", "0"), "edges[0].key: must be an integer"),
    (
        "a loop is allowed",
        appending(
            "edges",
            {"source": "k.humidity", "target": "k.humidity", "key": 3},
        ),
        "",
    ),
]


@pytest.mark.parametrize(
    ("change", "message"),
    [pytest.param(c, m, id=name) for name, c, m in DEPARTURES],
)
def test_each_departure_is_reported(change: Change, message: str) -> None:
    doc = copy.deepcopy(KINDS)
    change(doc)
    problems = io.check_node_link(doc)
    if message:
        assert any(message in p for p in problems), problems
    else:
        assert problems == ()


def test_repeated_keys_and_parallel_edges() -> None:
    doc = copy.deepcopy(KINDS)
    doc["edges"].append(dict(doc["edges"][0]))
    assert any("0 is repeated from" in p for p in io.check_node_link(doc))
    single = copy.deepcopy(SYSTEM)
    single["edges"].append({"source": "x", "target": "eq.1"})
    assert any("not a multigraph" in p for p in io.check_node_link(single))


def test_a_document_must_be_an_object() -> None:
    assert io.check_node_link([]) == ("document: must be a JSON object",)
