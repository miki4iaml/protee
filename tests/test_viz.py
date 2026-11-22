# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Drawing of node-link documents: selection, groups and DOT text.

Graphviz (through pygraphviz) reads and lays out the DOT text: it is the
oracle of the syntax and of the order of the nodes.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

import networkx as nx
import pygraphviz as pgv
import pytest
from hypothesis import given
from oracles import graphs

from protee import io, viz
from protee.graph import Digraph

DATA = Path(__file__).parent / "data" / "node_link"
COARE = "nomogram-0.8.0-coare36-surface-layer.json"
KINDS = "nomogram-0.8.0-humidity-kinds.json"
#: The style table a producer gives for the reads that close a loop.
CLOSING: viz.Styles = {
    "edge": {("role", "nomogram:closing"): {"style": "dashed", "constraint": "false"}}
}


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATA / name).read_text(encoding="utf-8"))
    return data


def document(
    nodes: list[dict[str, Any]],
    edges: list[Any],  # (source, target) pairs, or edge objects
    vocabulary: dict[str, Any] | None = None,
    *,
    multigraph: bool = True,
    **block: Any,
) -> dict[str, Any]:
    graph: dict[str, Any] = {"format": io.NODE_LINK_FORMAT, **block}
    if vocabulary is not None:
        graph["prefixes"] = {"x": None}
        graph["vocabulary"] = vocabulary
    return {
        "directed": True,
        "multigraph": multigraph,
        "graph": graph,
        "nodes": nodes,
        "edges": [
            e if isinstance(e, dict) else {"source": e[0], "target": e[1]}
            for e in edges
        ],
    }


def chain() -> dict[str, Any]:
    """a → b → c → d → e, and f → b."""
    return document(
        [{"id": i} for i in "abcdef"],
        [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("f", "b")],
    )


def ids(doc: dict[str, Any]) -> list[Any]:
    return [n["id"] for n in doc["nodes"]]


def marked(doc: dict[str, Any], mark: str) -> set[Any]:
    return {n["id"] for n in doc["nodes"] if n.get(viz.DISPLAY) == mark}


def hidden(doc: dict[str, Any]) -> dict[Any, int]:
    return {
        n["id"]: n["metrics"][viz.HIDDEN]
        for n in doc["nodes"]
        if viz.HIDDEN in (n.get("metrics") or {})
    }


def pairs(doc: dict[str, Any]) -> list[tuple[Any, Any]]:
    return [(e["source"], e["target"]) for e in doc["edges"]]


def drawn(dot: str) -> pgv.AGraph:
    return pgv.AGraph(string=dot)


def own(names: list[str]) -> list[str]:
    """Names that are not those of the legend."""
    return [n for n in names if not n.startswith("protee:legend")]


# Selection ----------------------------------------------------------------


def test_select_both_ways_keeps_and_marks_the_neighbours() -> None:
    doc = chain()
    out = viz.select(doc, ["b"], depth=1)
    assert ids(out) == ["a", "b", "c", "d", "f"]
    assert marked(out, viz.OUTSIDE) == {"d"}
    assert hidden(out) == {"d": 1}  # e is not shown
    assert pairs(out) == [("a", "b"), ("b", "c"), ("c", "d"), ("f", "b")]
    assert io.check_node_link(out) == ()
    assert doc == chain()  # the input is left as it was


def test_select_follows_one_direction_up_to_a_depth() -> None:
    out = viz.select(chain(), ["a"], depth=2, direction="out")
    assert ids(out) == ["a", "b", "c", "d", "f"]
    assert marked(out, viz.OUTSIDE) == {"d", "f"}
    assert hidden(out) == {"d": 1}
    back = viz.select(chain(), ["d"], depth=1, direction="in")
    assert ids(back) == ["b", "c", "d", "e"]
    assert marked(back, viz.OUTSIDE) == {"b", "e"}
    assert hidden(back) == {"b": 2}
    assert viz.select(chain(), ["a"], depth=0)["nodes"][0]["id"] == "a"


def test_select_filters_types_families_and_a_metric() -> None:
    vocabulary = {
        "type": [
            {"id": "x:k", "on": "node", "label": "kind"},
            {"id": "x:o", "on": "node", "label": "other"},
        ]
    }
    nodes = [
        {"id": "a", "type": "x:k", "family": "F", "metrics": {"m": 3}},
        {"id": "b", "type": "x:k", "family": "F", "metrics": {"m": 1}},
        {"id": "c", "type": "x:o", "family": "F", "metrics": {"m": 5}},
        {"id": "d", "type": "x:k", "family": "G", "metrics": {"m": 5}},
    ]
    doc = document(nodes, [("a", "b"), ("b", "c"), ("a", "c"), ("c", "d")], vocabulary)
    by_type = viz.select(doc, ["a"], depth=3, direction="out", types=["x:k"])
    assert marked(by_type, viz.OUTSIDE) == {"c"}
    by_family = viz.select(doc, ["a"], depth=3, direction="out", families=["F"])
    assert marked(by_family, viz.OUTSIDE) == {"d"}
    by_metric = viz.select(doc, ["a"], depth=3, direction="out", threshold=("m", 2))
    assert set(ids(by_metric)) - marked(by_metric, viz.OUTSIDE) == {"a", "c", "d"}
    nothing = viz.select(doc, ["b"], depth=1, types=["x:o"])
    assert nothing["nodes"] == []
    assert nothing["edges"] == []
    assert io.check_node_link(by_metric) == ()


def test_select_reads_links_and_refuses_bad_requests() -> None:
    doc = chain()
    doc["links"] = doc.pop("edges")
    # a and b are selected; c and f, neighbours of b, are kept outside.
    assert pairs(viz.select(doc, ["a"], depth=1)) == [
        ("a", "b"),
        ("b", "c"),
        ("f", "b"),
    ]
    with pytest.raises(ValueError, match="unknown starting nodes"):
        viz.select(chain(), ["z"], depth=1)
    with pytest.raises(ValueError, match="depth must be"):
        viz.select(chain(), ["a"], depth=-1)
    with pytest.raises(ValueError, match="direction must be"):
        viz.select(chain(), ["a"], depth=1, direction="up")
    broken = {"directed": False, "nodes": {}, "edges": 3, "graph": {"format": "?"}}
    with pytest.raises(ValueError, match=r"not a protee-node-link/0 .*and \d+ more"):
        viz.select(broken, ["a"], depth=1)


# Groups -------------------------------------------------------------------

GROUPED = {
    "type": [
        {"id": "x:k", "on": "node", "label": "kind"},
        {"id": "x:o", "on": "node", "label": "other"},
        {"id": "x:r", "on": "edge", "label": "relation"},
        {"id": "x:s", "on": "edge", "label": "another relation"},
    ]
}


def test_collapse_makes_one_node_per_family() -> None:
    nodes = [
        {"id": "a", "type": "x:k", "family": "F"},
        {"id": "b", "type": "x:k", "family": "F"},
        {"id": "c", "family": "G"},
        {"id": "d"},
    ]
    edges = [
        {"source": "a", "target": "b", "type": "x:r"},
        {"source": "a", "target": "c", "type": "x:r", "verified": "2026-11-04"},
        {"source": "b", "target": "c", "type": "x:r", "verified": "2026-11-04"},
        {"source": "d", "target": "a", "key": 4},
    ]
    out = viz.collapse(document(nodes, edges, GROUPED))
    assert ids(out) == ["family=F", "c", "d"]
    group = out["nodes"][0]
    assert (group["label"], group["type"]) == ("F", "x:k")
    assert group[viz.CONTAINS] == ["a", "b"]
    assert group["metrics"] == {viz.MEMBERS: 2}
    assert marked(out, viz.GROUP) == {"family=F"}
    merged, inward = out["edges"]
    assert (merged["source"], merged["target"], merged["type"]) == (
        "family=F",
        "c",
        "x:r",
    )
    assert merged["metrics"] == {viz.MERGED: 2}
    assert merged["verified"] == "2026-11-04"
    assert (inward["source"], inward["target"], inward["key"]) == ("d", "family=F", 0)
    assert io.check_node_link(out) == ()


def test_collapse_avoids_taken_identifiers_and_mixed_types() -> None:
    nodes = [
        {"id": "a", "type": "x:k", "family": "F"},
        {"id": "b", "type": "x:o", "family": "F"},
        {"id": "family=F"},
        {"id": "c"},
    ]
    edges = [
        {"source": "a", "target": "c", "type": "x:r"},
        {"source": "b", "target": "c", "type": "x:s"},
        {"source": "c", "target": "family=F", "key": 0},
    ]
    doc = document(nodes, edges, GROUPED, multigraph=False)
    out = viz.collapse(doc)
    group = out["nodes"][0]
    assert group["id"] == "family=F#2"
    assert "type" not in group
    assert [e["key"] for e in out["edges"]] == [0, 1, 0]
    assert out["multigraph"] is True  # two relations now join the group to c
    assert io.check_node_link(out) == ()


def test_collapse_without_a_group_returns_a_copy() -> None:
    doc = document([{"id": "a", "family": "F"}, {"id": "b"}], [("a", "b")])
    out = viz.collapse(doc)
    assert out == doc
    assert out is not doc


# DOT text -----------------------------------------------------------------


def test_the_loop_of_coare_is_drawn_in_the_order_of_the_source() -> None:
    data = load(COARE)
    dot = viz.to_dot(data, styles=CLOSING, order_by="rank")
    g = drawn(dot)
    g.layout(prog="dot")
    equations = sorted(
        (n for n in data["nodes"] if "rank" in n), key=lambda n: n["rank"]
    )
    assert len({n["rank"] for n in equations}) == len(equations) == 13
    heights = [float(g.get_node(n["id"]).attr["pos"].split(",")[1]) for n in equations]
    assert heights == sorted(heights, reverse=True)  # top to bottom
    assert len(set(heights)) == 13
    loose = [
        e
        for e in g.edges()
        if e.attr["constraint"] == "false" and own([e[0]]) == [e[0]]
    ]
    assert len(loose) == 7
    assert {e.attr["style"] for e in loose} == {"dashed"}


def test_the_humidity_kinds_parse_with_their_legend_and_text() -> None:
    data = load(KINDS)
    g = drawn(viz.to_dot(data))
    assert len(own(g.nodes())) == len(data["nodes"]) == 59
    vocabulary = data["graph"]["vocabulary"]
    on_nodes = sum(v["on"] == "node" for vs in vocabulary.values() for v in vs)
    on_edges = sum(v["on"] == "edge" for vs in vocabulary.values() for v in vs)
    assert len(g.nodes()) - 59 == on_nodes + 2 * on_edges
    symmetric = {v["id"] for v in vocabulary["type"] if v.get("symmetric")}
    expected = sum(e["type"] in symmetric for e in data["edges"])
    both = [e for e in g.edges() if e.attr["dir"] == "both"]
    assert len(own([e[0] for e in both])) == expected == 18
    heads = {e.attr["arrowhead"] for e in both if own([e[0]]) == [e[0]]}
    assert len(heads) == 2  # exact and close matches: told apart without colour
    assert all(e.attr["arrowtail"] == e.attr["arrowhead"] for e in both)
    colours = {e.attr["color"] for e in g.edges() if e.attr["color"]}
    assert "#F0E442" not in colours  # yellow only fills nodes
    svg = g.draw(format="svg", prog="dot").decode()
    assert "<text" in svg
    assert "@font-face" not in svg  # no remote or embedded font
    assert "url(" not in svg


def test_the_drawing_is_stable() -> None:
    first = viz.to_dot(load(COARE), styles=CLOSING, order_by="rank")
    again = viz.to_dot(load(COARE), styles=CLOSING, order_by="rank")
    assert first == again
    assert drawn(first).draw(format="svg", prog="dot") == drawn(again).draw(
        format="svg", prog="dot"
    )


def test_a_renamed_vocabulary_draws_the_same() -> None:
    text = (DATA / COARE).read_text(encoding="utf-8")
    renamed = json.loads(
        text.replace('"nomogram:', '"x:').replace('"nomogram": null', '"x": null')
    )
    assert io.check_node_link(renamed) == ()
    assert renamed != load(COARE)
    assert viz.to_dot(renamed) == viz.to_dot(load(COARE))


def test_labels_tooltips_links_and_marks() -> None:
    doc = chain()
    doc["nodes"][1].update(url="https://example.org/b", description="the second")
    doc["edges"][0]["label"] = "first"
    out = viz.select(doc, ["b"], depth=1)
    dot = viz.to_dot(out, legend=False)
    g = drawn(dot)
    b, d = g.get_node("b"), g.get_node("d")
    assert (b.attr["URL"], b.attr["tooltip"]) == ("https://example.org/b", "the second")
    assert d.attr["label"].endswith("+1")
    assert (d.attr["style"], d.attr["color"]) == ("dashed", "#7F7F7F")
    assert g.get_edge("a", "b").attr["label"] == "first"
    assert "cluster_legend" not in dot
    grouped = document(
        [{"id": "a", "family": "F"}, {"id": "b", "family": "F"}, {"id": "c"}],
        [("a", "c")],
    )
    collapsed = drawn(viz.to_dot(viz.collapse(grouped)))  # kept alive while read
    assert collapsed.get_node("family=F").attr["peripheries"] == "2"
    plain = viz.to_dot(document([{"id": 0}, {"id": 1}], [(0, 1)]))
    assert "cluster_legend" not in plain  # nothing is declared


def test_the_graph_block_titles_the_drawing() -> None:
    doc = document([{"id": "a"}], [], label="Surface layer", description="A loop")
    g = drawn(viz.to_dot(doc))  # kept alive while its attributes are read
    head = g.graph_attr
    assert (head["label"], head["labelloc"], head["tooltip"]) == (
        "Surface layer",
        "t",
        "A loop",
    )
    assert head["rankdir"] == "TB"
    across = drawn(viz.to_dot(doc, direction="LR"))
    assert across.graph_attr["rankdir"] == "LR"


def test_default_styles_follow_the_order_of_declaration() -> None:
    statuses = [{"id": f"s{i}", "on": "node", "label": f"s{i}"} for i in range(5)]
    vocabulary = {
        "type": [
            {"id": "x:k", "on": "node", "label": "kind"},
            {"id": "x:o", "on": "node", "label": "other"},
            {"id": "x:r", "on": "edge", "label": "relation"},
            {"id": "x:s", "on": "edge", "label": "symmetric", "symmetric": True},
        ],
        "status": statuses,
        "role": [{"id": "x:closing", "on": "edge", "label": "closing"}],
    }
    nodes = [
        {"id": "a", "type": "x:k", "status": "s0"},
        {"id": "b", "type": "x:o", "status": "s4"},
        {"id": "c", "status": "s1"},
    ]
    edges = [
        {"source": "a", "target": "b", "type": "x:r"},
        {"source": "b", "target": "a", "type": "x:s", "role": "x:closing"},
    ]
    doc = document(nodes, edges, vocabulary)
    g = drawn(viz.to_dot(doc, styles={"node": {("status", "s1"): {"style": "dashed"}}}))
    a, b, c = (g.get_node(i) for i in "abc")
    assert (a.attr["shape"], b.attr["shape"]) == ("ellipse", "box")
    assert a.attr["fillcolor"] == viz.OKABE_ITO[0]
    assert a.attr["style"] == "filled,solid"
    assert b.attr["fillcolor"] == viz.OKABE_ITO[4]
    assert b.attr["fontcolor"] == "#FFFFFF"  # a dark fill takes a white text
    assert c.attr["style"] == "filled,dashed"  # the caller's line, still filled
    plain, closing = g.get_edge("a", "b"), g.get_edge("b", "a")
    assert (plain.attr["color"], plain.attr["arrowhead"]) == (
        viz.OKABE_ITO[0],
        "normal",
    )
    assert closing.attr["color"] == viz.OKABE_ITO[1]
    assert (closing.attr["dir"], closing.attr["style"]) == ("both", "dashed")
    assert closing.attr["arrowhead"] == closing.attr["arrowtail"] == "empty"


def test_to_dot_refuses_bad_requests() -> None:
    doc = document([{"id": "a", "rank": 1}, {"id": "b", "rank": "2"}], [("a", "b")])
    with pytest.raises(TypeError, match="is not a number"):
        viz.to_dot(doc, order_by="rank")
    doc["nodes"][1]["rank"] = math.inf
    with pytest.raises(ValueError, match="is not finite"):
        viz.to_dot(doc, order_by="rank")
    with pytest.raises(ValueError, match="direction must be"):
        viz.to_dot(chain(), direction="up")
    with pytest.raises(ValueError, match="invalid Graphviz attribute"):
        viz.to_dot(chain(), styles={"node": {("type", "x"): {"bad name": "1"}}})
    with pytest.raises(ValueError, match="write the same"):
        viz.to_dot(document([{"id": 1}, {"id": "1"}], []))
    with pytest.raises(ValueError, match="not a protee-node-link/0"):
        viz.to_dot({"directed": True})


def test_protee_names_no_producer() -> None:
    assert "nomogram" not in inspect.getsource(viz)


# SVG ----------------------------------------------------------------------


def test_render_svg_keeps_text_in_system_fonts_and_fetches_nothing() -> None:
    svg = viz.render_svg(load(COARE), styles=CLOSING, order_by="rank")
    assert svg.startswith("<?xml")
    assert svg.count("<text") >= 37  # one label per node, at least
    assert 'font-family="Helvetica,Arial,sans-serif"' in svg
    assert "@font-face" not in svg
    assert "<image" not in svg
    assert svg == viz.render_svg(load(COARE), styles=CLOSING, order_by="rank")


def test_render_svg_needs_the_viz_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pygraphviz", None)
    with pytest.raises(ImportError, match=r"protee\[viz\]"):
        viz.render_svg(chain())


def test_importing_viz_does_not_import_graphviz() -> None:
    code = "import sys, protee.viz; assert 'pygraphviz' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


# Exploration page -----------------------------------------------------------


def page_parts(page: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The nodes (groups included) and the edges given to cytoscape.js."""
    found = re.search(
        r'<script type="application/json" id="protee-elements">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert found is not None
    elements: list[dict[str, Any]] = json.loads(found.group(1))
    edges = [e for e in elements if "source" in e["data"]]
    return [e for e in elements if "source" not in e["data"]], edges


def test_render_html_is_a_page_that_fetches_nothing() -> None:
    page = viz.render_html(
        load(COARE), styles=CLOSING, order_by="rank", group_by="loop"
    )
    assert page.startswith("<!doctype html>")
    assert re.search(r"<script[^>]*\bsrc=", page) is None
    assert "<link" not in page
    assert "@import" not in page
    assert "The Cytoscape Consortium" in page
    assert "iVis@Bilkent" in page
    assert page == viz.render_html(
        load(COARE), styles=CLOSING, order_by="rank", group_by="loop"
    )


def test_render_html_folds_the_loop_of_coare_in_the_order_of_the_source() -> None:
    data = load(COARE)
    page = viz.render_html(data, styles=CLOSING, order_by="rank", group_by="loop")
    nodes, edges = page_parts(page)
    assert len(edges) == len(data["edges"])
    (group,) = (n for n in nodes if "position" not in n)
    assert group["data"]["label"] == "⟳ 26"
    members = [n for n in nodes if n["data"].get("parent") == group["data"]["id"]]
    assert len(members) == 26
    ranks = {n["id"]: n["rank"] for n in data["nodes"] if "rank" in n}
    equations = sorted(
        (n for n in nodes if n["data"]["id"] in ranks),
        key=lambda n: ranks[n["data"]["id"]],
    )
    heights = [n["position"]["y"] for n in equations]
    assert heights == sorted(heights)  # cytoscape.js counts y downwards
    assert len(set(heights)) == 13
    assert sum(e["style"].get("line-style") == "dashed" for e in edges) == 7


def test_render_html_groups_families_with_a_legend_and_texts() -> None:
    vocabulary = {
        "type": [
            {"id": "x:k", "on": "node", "label": "kind", "description": "a kind"},
            {"id": "x:r", "on": "edge", "label": "specializes"},
            {"id": "x:m", "on": "edge", "label": "matches", "symmetric": True},
        ]
    }
    nodes: list[dict[str, Any]] = [
        {"id": "a", "type": "x:k", "family": "F", "url": "https://example.org/a"},
        {"id": "b", "type": "x:k", "family": "F", "description": "the second"},
        {"id": "c", "label": "</script><b>", "metrics": {viz.HIDDEN: 2}},
    ]
    edges = [
        {"source": "a", "target": "b", "type": "x:r", "label": "is a"},
        {"source": "a", "target": "c", "type": "x:m"},
    ]
    doc = document(nodes, edges, vocabulary, label="Kinds & <names>", language="fr")
    page = viz.render_html(doc)
    assert '<html lang="fr">' in page
    assert "<title>Kinds &amp; &lt;names&gt;</title>" in page
    assert "</script><b>" not in page  # the label cannot end a script
    found, links = page_parts(page)
    (group,) = (n for n in found if "position" not in n)
    assert group["data"]["label"] == "F"
    by_id = {n["data"]["id"]: n["data"] for n in found}
    assert by_id["a"]["parent"] == by_id["b"]["parent"] == group["data"]["id"]
    assert by_id["a"]["url"] == "https://example.org/a"
    assert by_id["b"]["tooltip"] == "the second"
    assert by_id["c"]["label"] == "</script><b>\n+2"
    plain, symmetric = links
    assert plain["data"]["label"] == "is a"
    assert plain["style"]["target-arrow-shape"] == "triangle"
    assert (
        symmetric["style"]["source-arrow-shape"]
        == symmetric["style"]["target-arrow-shape"]
    )
    assert "<h2>type</h2>" in page
    assert '<span class="note">a kind</span>' in page
    assert viz.render_html(doc, title="Mine").count("<title>Mine</title>") == 1


def test_render_html_translates_the_graphviz_styles() -> None:
    styles: viz.Styles = {
        "node": {
            ("k", "box"): {
                "shape": "box",
                "style": "filled,bold",
                "fillcolor": "#0072B2",
            },
            ("k", "dot"): {
                "style": "dotted",
                "color": "#D55E00",
                "fontcolor": "#FFFFFF",
            },
            ("k", "two"): {"peripheries": "2", "shape": "house"},
        },
        "edge": {
            ("k", "dash"): {
                "style": "dashed",
                "color": "#009E73",
                "fontcolor": "#000000",
            },
            ("k", "dot"): {"style": "dotted,bold", "arrowhead": "odot"},
            ("k", "none"): {"dir": "none"},
            ("k", "both"): {"dir": "both", "arrowtail": "diamond"},
        },
    }
    nodes = [{"id": "a", "k": "box"}, {"id": "b", "k": "dot"}, {"id": "c", "k": "two"}]
    edges = [
        {"source": "a", "target": "b", "k": "dash"},
        {"source": "b", "target": "c", "k": "dot"},
        {"source": "c", "target": "a", "k": "none"},
        {"source": "a", "target": "c", "k": "both"},
    ]
    found, links = page_parts(viz.render_html(document(nodes, edges), styles=styles))
    a, b, c = (n["style"] for n in found)
    assert (a["shape"], a["background-color"], a["border-width"]) == (
        "rectangle",
        "#0072B2",
        3,
    )
    assert (b["border-style"], b["border-color"], b["color"]) == (
        "dotted",
        "#D55E00",
        "#FFFFFF",
    )
    assert (c["shape"], c["border-style"], c["border-width"]) == ("tag", "double", 4)
    dash, dotted, none, both = (e["style"] for e in links)
    assert (dash["line-style"], dash["line-color"], dash["color"]) == (
        "dashed",
        "#009E73",
        "#000000",
    )
    assert (dotted["line-style"], dotted["width"], dotted["target-arrow-fill"]) == (
        "dotted",
        3,
        "hollow",
    )
    assert none["target-arrow-shape"] == "none"
    assert both["source-arrow-shape"] == "diamond"


def test_render_html_refuses_unknown_groupings_and_needs_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = viz.render_html(chain(), group_by=None)
    nodes, _ = page_parts(page)
    assert all("position" in n for n in nodes)  # no group
    with pytest.raises(ValueError, match="group_by must be"):
        viz.render_html(chain(), group_by="kind")
    monkeypatch.setitem(sys.modules, "pygraphviz", None)
    with pytest.raises(ImportError, match=r"protee\[viz\]"):
        viz.render_html(chain())


def test_render_html_avoids_a_taken_group_identifier() -> None:
    doc = document(
        [
            {"id": "a", "family": "F"},
            {"id": "b", "family": "F"},
            {"id": "protee:group:0"},
        ],
        [("a", "protee:group:0")],
    )
    found, _ = page_parts(viz.render_html(doc))
    (group,) = (n for n in found if "position" not in n)
    assert group["data"]["id"] == "protee:group:0#2"


def test_the_embedded_scripts_match_their_notice() -> None:
    assets = files("protee").joinpath("_assets")
    notice = assets.joinpath("NOTICE.md").read_text(encoding="utf-8")
    # The last column is the digest of the file as shipped.
    rows = re.findall(
        r"\| `([^`]+)` \| [^|]+ \| [^|]+ \| `[^`]+` \| `[0-9a-f]{64}` \| `([0-9a-f]{64})` \|",
        notice,
    )
    assert len(rows) == 4
    for name, digest in rows:
        assert hashlib.sha256(assets.joinpath(name).read_bytes()).hexdigest() == digest


# Loops and transitive reduction (NetworkX as an independent oracle) -------


def loops_of(doc: dict[str, Any]) -> list[set[Any]]:
    return [
        set(n[viz.CONTAINS]) for n in doc["nodes"] if n.get(viz.DISPLAY) == viz.LOOP
    ]


def test_condense_folds_the_loop_of_coare() -> None:
    data = load(COARE)
    out = viz.condense(data)
    assert io.check_node_link(out) == ()
    oracle = [
        c
        for c in nx.strongly_connected_components(
            nx.node_link_graph(data, edges="edges")
        )
        if len(c) > 1
    ]
    assert loops_of(out) == oracle
    (loop,) = (n for n in out["nodes"] if n.get(viz.DISPLAY) == viz.LOOP)
    assert (loop["label"], loop["metrics"]) == ("⟳ 26", {viz.MEMBERS: 26})
    assert len(out["nodes"]) == 37 - 26 + 1
    rest = nx.DiGraph(nx.node_link_graph(out, edges="edges"))
    rest.remove_edges_from(nx.selfloop_edges(rest))
    assert nx.is_directed_acyclic_graph(rest)
    g = drawn(viz.to_dot(out))
    assert g.get_node(loop["id"]).attr["peripheries"] == "3"


def test_condense_keeps_the_order_and_single_node_loops() -> None:
    doc = document(
        [{"id": i} for i in "abcdef"],
        [
            ("a", "b"),
            ("b", "a"),
            ("b", "c"),
            ("c", "d"),
            ("d", "e"),
            ("e", "c"),
            ("f", "f"),
        ],
    )
    out = viz.condense(doc)
    assert ids(out) == ["loop:a", "loop:c", "f"]
    assert loops_of(out) == [{"a", "b"}, {"c", "d", "e"}]
    assert pairs(out) == [("loop:a", "loop:c"), ("f", "f")]
    assert viz.condense(chain()) == chain()


@given(graph=graphs())
def test_condense_finds_the_components_of_networkx(graph: Digraph) -> None:
    data = io.to_node_link(graph)
    expected = [
        c
        for c in nx.strongly_connected_components(
            nx.node_link_graph(data, edges="edges")
        )
        if len(c) > 1
    ]
    found = loops_of(viz.condense(data))
    assert sorted(map(sorted, found)) == sorted(map(sorted, expected))


@given(graph=graphs())
def test_reduce_matches_the_transitive_reduction_of_networkx(graph: Digraph) -> None:
    arcs = [(t, h) for t, h in graph.arcs() if t < h]  # without cycles
    data = io.to_node_link(
        Digraph.from_arcs(graph.n, arcs), arcs={"type": ["x:r"] * len(arcs)}
    )
    out = viz.reduce(data, edge_type="x:r")
    oracle = nx.transitive_reduction(nx.DiGraph(arcs) if arcs else nx.DiGraph())
    assert set(pairs(out)) == set(oracle.edges)
    assert len(pairs(out)) == len(set(pairs(out)))


def test_reduce_leaves_other_relations_and_refuses_cycles() -> None:
    doc = document(
        [{"id": i} for i in "abcd"],
        [
            {"source": "a", "target": "b", "type": "x:r"},
            {"source": "a", "target": "b", "type": "x:r"},
            {"source": "b", "target": "c", "type": "x:r"},
            {"source": "a", "target": "c", "type": "x:r"},
            {"source": "a", "target": "c", "type": "x:s"},
            {"source": "c", "target": "d"},
        ],
    )
    out = viz.reduce(doc, edge_type="x:r")
    assert [(e["source"], e["target"], e.get("type")) for e in out["edges"]] == [
        ("a", "b", "x:r"),
        ("b", "c", "x:r"),
        ("a", "c", "x:s"),
        ("c", "d", None),
    ]
    kinds = load(KINDS)
    tree = viz.reduce(kinds, edge_type="qudt:specializationOf")
    assert tree == kinds  # a tree has nothing to reduce
    cycle = document([{"id": "a"}, {"id": "b"}], [("a", "b"), ("b", "a")])
    for edge in cycle["edges"]:
        edge["type"] = "x:r"
    with pytest.raises(ValueError, match="form a cycle"):
        viz.reduce(cycle, edge_type="x:r")
    loop = document([{"id": "a"}], [{"source": "a", "target": "a", "type": "x:r"}])
    with pytest.raises(ValueError, match="form a cycle"):
        viz.reduce(loop, edge_type="x:r")
