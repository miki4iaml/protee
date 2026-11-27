# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The page to explore a document, its tooltips, formulas and matrix, and
the colour of the nodes by vocabulary.

The behaviour of the page in a browser is not run here: the tests read the
data it embeds, and the script it carries.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pygraphviz as pgv
import pytest

from protee import io, viz

DATA = Path(__file__).parent / "data" / "node_link"
COARE = "nomogram-0.8.0-coare36-surface-layer.json"
KINDS = "nomogram-0.8.0-humidity-kinds.json"
LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40"></svg>'
#: A formula, as nomogram writes it: (a + 1) / b.
FORMULA = [
    "math",
    {},
    [
        "mfrac",
        {},
        ["mrow", {}, ["mi", {}, "a"], ["mo", {}, "+"], ["mn", {}, "1"]],
        ["mi", {}, "b"],
    ],
]


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATA / name).read_text(encoding="utf-8"))
    return data


def document(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    vocabulary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph: dict[str, Any] = {"format": io.NODE_LINK_FORMAT}
    if vocabulary is not None:
        graph["prefixes"] = {"x": None}
        graph["vocabulary"] = vocabulary
    return {
        "directed": True,
        "multigraph": True,
        "graph": graph,
        "nodes": nodes,
        "edges": edges,
    }


def data_of(page: str, name: str) -> Any:
    """The JSON data that the page embeds under ``protee-<name>``."""
    found = re.search(
        rf'<script type="application/json" id="protee-{name}">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert found is not None
    return json.loads(found.group(1))


def elements(page: str) -> dict[str, dict[str, Any]]:
    """The data of the nodes and edges of the page, by identifier."""
    return {e["data"]["id"]: e["data"] for e in data_of(page, "elements")}


def cited() -> dict[str, Any]:
    """An equation that cites an article, at its equation 11."""
    return document(
        [
            {"id": "eq", "type": "x:eq", "role": "x:in", "x:formula": FORMULA},
            {"id": "art", "type": "x:ref", "iri": "https://doi.org/10.1/x"},
        ],
        [
            {
                "source": "eq",
                "target": "art",
                "type": "x:cites",
                "label": "cites",
                "locator": "11",
                "description": "where the equation comes from",
            }
        ],
        {
            "type": [
                {"id": "x:eq", "on": "node", "label": "equation"},
                {"id": "x:ref", "on": "node", "label": "reference"},
                {"id": "x:cites", "on": "edge", "label": "cites"},
            ],
            "role": [{"id": "x:in", "on": "node", "label": "input"}],
        },
    )


# Tooltips --------------------------------------------------------------------


def test_the_tooltips_add_the_attributes_asked_for() -> None:
    graph = pgv.AGraph(
        string=viz.to_dot(cited(), tooltip=("role", "type"), legend=False)
    )
    node = graph.get_node("eq")
    assert node.attr["tooltip"] == "eq\\nrole: input\\ntype: equation"
    (edge,) = graph.edges()
    # The description of an edge is a free key of the format: not shown.
    assert edge.attr["tooltip"] == "locator: 11\\ntype: cites"
    # A value that is not a text is written as JSON; an absent one is left.
    doc = cited()
    doc["nodes"][0]["sources"] = ["a", "b"]
    doc["nodes"][0]["rank"] = 3
    texts = elements(viz.render_html(doc, tooltip=("sources", "absent", "rank")))
    assert texts["eq"]["tooltip"] == 'eq\nsources: ["a", "b"]\nrank: 3'


def test_an_edge_without_locator_nor_description_keeps_no_tooltip() -> None:
    graph = pgv.AGraph(string=viz.to_dot(load(COARE)))
    assert all("tooltip" not in e.attr or not e.attr["tooltip"] for e in graph.edges())


def test_the_page_shows_tooltips_on_edges() -> None:
    found = elements(viz.render_html(cited(), tooltip=("role",)))
    assert found["eq"]["tooltip"] == "eq\nrole: input"
    (edge,) = (e for e in found.values() if "source" in e)
    assert edge["tooltip"] == "cites\ntype: cites\nlocator: 11"
    # A declared value asked for again is not repeated.
    found = elements(viz.render_html(cited(), tooltip=("type",)))
    (edge,) = (e for e in found.values() if "source" in e)
    assert edge["tooltip"] == "cites\ntype: cites\nlocator: 11"
    # The tooltip keeps its line breaks.
    assert "white-space: pre-line" in viz.render_html(cited())


# Formulas --------------------------------------------------------------------


def test_a_formula_travels_as_data() -> None:
    page = viz.render_html(cited(), math="x:formula")
    assert elements(page)["eq"]["math"] == FORMULA
    assert "math" not in elements(page)["art"]
    script = page[page.rindex("<script>") :]
    assert "innerHTML" not in script
    assert "setAttribute" not in script
    assert "createElementNS" in script


@pytest.mark.parametrize(
    ("formula", "message"),
    [
        (["mrow", {}, "a"], "a formula is a list \\['math'"),
        ("a + 1", "a formula is a list \\['math'"),
        (["math", {}, ["script", {}, "alert(1)"]], "'script' is not an element"),
        (["math", {}, ["mi", {"href": "javascript:x"}, "a"]], "has no attribute"),
        (["math", {}, ["mi"]], "\\[name, \\{\\}, children"),
        (["math", {}, 3], "\\[name, \\{\\}, children"),
        (["math", {}, *[["mi", {}, "a"]] * 2000], "at most 4000 elements and texts"),
        (["math", {}, ["mi", {}, *["x"] * 4000]], "at most 4000 elements and texts"),
        (["math", {}, ["mi", {}, "x" * 20_001]], "20000 characters of text"),
    ],
)
def test_a_formula_is_checked(formula: Any, message: str) -> None:
    doc = cited()
    doc["nodes"][0]["x:formula"] = formula
    with pytest.raises(ValueError, match=message):
        viz.render_html(doc, math="x:formula")


def test_a_formula_has_a_bounded_depth() -> None:
    tree: list[Any] = ["mi", {}, "a"]
    for _ in range(40):
        tree = ["mrow", {}, tree]
    doc = cited()
    doc["nodes"][0]["x:formula"] = ["math", {}, tree]
    with pytest.raises(ValueError, match="32 levels deep"):
        viz.render_html(doc, math="x:formula")


def test_a_text_cannot_close_the_data_of_the_page() -> None:
    doc = cited()
    doc["nodes"][0]["x:formula"] = ["math", {}, ["mo", {}, "</script><script>"]]
    page = viz.render_html(doc, math="x:formula")
    assert "</script><script>" not in page
    assert elements(page)["eq"]["math"][2][2] == "</script><script>"


# Matrix ----------------------------------------------------------------------


def test_the_page_holds_the_matrix_and_its_order() -> None:
    loop = viz.contract(load(COARE), edge_type="nomogram:gives")
    page = viz.render_html(loop, order_by="rank", matrix=True)
    order = data_of(page, "order")
    ranks = sorted(
        (n["rank"], k, n["id"]) for k, n in enumerate(loop["nodes"]) if "rank" in n
    )
    assert order == [i for _, _, i in ranks]
    assert '<div id="matrix"><svg' in page
    assert 'id="matrix-toggle"' in page
    panel = page[page.index('<div id="matrix">') :]
    panel = panel[: panel.index("</div>")]
    cells = {
        (order.index(str(e["source"])), order.index(str(e["target"])))
        for e in loop["edges"]
        if str(e["source"]) in order
        and str(e["target"]) in order
        and e["source"] != e["target"]
    }
    assert panel.count('<g class="protee-cell"') == len(cells) > 0
    with pytest.raises(ValueError, match="needs order_by"):
        viz.render_html(loop, matrix=True)
    plain = viz.render_html(loop, order_by="rank")
    assert data_of(plain, "order") == []
    assert 'id="matrix"' not in plain


# Look ------------------------------------------------------------------------


def test_the_page_takes_a_theme_a_footer_and_the_font_sizes() -> None:
    page = viz.render_html(
        load(KINDS),
        theme=viz.DARK,
        attributes={"node": {"fontsize": "11"}, "graph": {"splines": "ortho"}},
        footer=LOGO,
        legend_values="present",
    )
    assert data_of(page, "look") == {
        "background": viz.DARK.background,
        "ink": viz.DARK.ink,
        "muted": viz.DARK.muted,
    }
    assert f"--bg: {viz.DARK.background}" in page
    assert "color-scheme: dark" in page
    assert 'src="data:image/svg+xml;base64,' in page
    sizes = {
        e["style"].get("font-size")
        for e in data_of(page, "elements")
        if "position" in e
    }
    assert sizes == {11.0}
    # A size cytoscape.js cannot take is left to it.
    for size in ("big", "0"):
        odd = viz.render_html(load(KINDS), attributes={"node": {"fontsize": size}})
        assert all(
            "font-size" not in e["style"]
            for e in data_of(odd, "elements")
            if "position" in e
        )
    light = viz.render_html(load(KINDS))
    assert "color-scheme: light" in light
    assert data_of(light, "look")["background"] == "#FFFFFF"
    with pytest.raises(ValueError, match="legend_values must be"):
        viz.render_html(load(KINDS), legend_values="some")


# Vocabularies ----------------------------------------------------------------


def test_mark_vocabularies_names_the_vocabulary_of_each_iri() -> None:
    kinds = load(KINDS)
    marked = viz.mark_vocabularies(kinds)
    assert io.check_node_link(marked) == ()
    for before, after in zip(kinds["nodes"], marked["nodes"], strict=True):
        iri = before.get("iri")
        if iri is None:
            assert viz.VOCABULARY not in after
        else:
            # No prefix of the document begins these IRIs: the authority.
            assert after[viz.VOCABULARY] == iri.split("/")[2]
    declared = marked["graph"]["vocabulary"]
    node_attributes = [
        a for a, values in declared.items() if any(v["on"] == "node" for v in values)
    ]
    assert node_attributes[1] == viz.VOCABULARY
    assert viz.mark_vocabularies(marked) == marked


def test_a_declared_prefix_names_the_vocabulary() -> None:
    doc = document(
        [
            {"id": "a", "iri": "http://example.org/v/sub/a"},
            {"id": "b", "iri": "http://example.org/v/b"},
            {"id": "c", "iri": "urn:isbn:1"},
            {"id": "d", "iri": "https://user@host.org:8080/x"},
            {"id": "e"},
            {"id": "f", "iri": "file:///tmp/x"},
            {"id": "g", "iri": "HTTP://Host.ORG/y"},
            {"id": "h", "iri": "http://[::1]:80/x"},
            {"id": "i", "iri": "http://[::1/x"},
        ],
        [],
    )
    doc["graph"]["prefixes"] = {
        "v": "http://example.org/v/",
        "sub": "http://example.org/v/sub/",
        "local": None,
        "protee": "https://protee.example/",
    }
    marked = viz.mark_vocabularies(doc)
    found = {n["id"]: n.get(viz.VOCABULARY) for n in marked["nodes"]}
    # Hosts are read without case; an IPv6 address, which a declared value
    # cannot hold, or a broken one, gives the scheme.
    assert found == {
        "a": "sub",
        "b": "v",
        "c": "urn",
        "d": "host.org",
        "e": None,
        "f": "file",
        "g": "host.org",
        "h": "http",
        "i": "http",
    }
    assert marked["graph"]["prefixes"]["protee"] == "https://protee.example/"
    # Without any IRI, nothing is declared.
    bare = viz.mark_vocabularies(document([{"id": "e"}], []))
    assert viz.VOCABULARY not in (bare["graph"].get("vocabulary") or {})
    labels = {
        v["id"]: v["label"] for v in marked["graph"]["vocabulary"][viz.VOCABULARY]
    }
    assert labels["sub"] == "sub: http://example.org/v/sub/"
    assert labels["host.org"] == "host.org"
    assert io.check_node_link(marked) == ()
    # The only attribute of the nodes: their shape tells their vocabulary.
    graph = pgv.AGraph(string=viz.to_dot(marked, legend=False))
    shapes = {n.name: n.attr["shape"] for n in graph.nodes()}
    assert len({shapes[i] for i in "abcd"}) == 4
    # Second after a type: their fill tells it.
    for node in doc["nodes"]:
        node["type"] = "x:k"
    doc["graph"]["prefixes"]["x"] = None
    doc["graph"]["vocabulary"] = {"type": [{"id": "x:k", "on": "node", "label": "k"}]}
    typed = pgv.AGraph(string=viz.to_dot(viz.mark_vocabularies(doc), legend=False))
    fills = {n.name: n.attr["fillcolor"] for n in typed.nodes()}
    assert len({fills[i] for i in "abcd"}) == 4
