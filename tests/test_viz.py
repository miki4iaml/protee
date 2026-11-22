# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Drawing of node-link documents: selection, groups and DOT text.

Graphviz (through pygraphviz) reads and lays out the DOT text: it is the
oracle of the syntax and of the order of the nodes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any

import networkx as nx
import pygraphviz as pgv
import pytest
from hypothesis import given
from hypothesis import strategies as st
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
    assert (b.attr["URL"], b.attr["tooltip"]) == (
        "https://example.org/b",
        "the second\\nhttps://example.org/b",  # then the url, a line below
    )
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
    with pytest.raises(ImportError, match=r"protee\[viz\]"):
        viz.render_legend_svg(chain())


# Legend -------------------------------------------------------------------

SVG = "{http://www.w3.org/2000/svg}"


def svg_tree(svg: str) -> ET.Element:
    return ET.fromstring(svg.encode("utf-8"))


def texts(element: ET.Element) -> dict[str, tuple[float, float]]:
    """Each text of a drawing, with its position (labels of links are spaced)."""
    return {
        str(t.text).strip(): (float(t.attrib["x"]), float(t.attrib["y"]))
        for t in element.iter(f"{SVG}text")
    }


def swatch_tags(element: ET.Element, label: str) -> set[str]:
    """The shapes drawn by the node or edge group of a drawing that shows
    ``label``."""
    for group in element.iter(f"{SVG}g"):
        if group.get("class") not in ("node", "edge"):
            continue
        if any(str(t.text).strip() == label for t in group.iter(f"{SVG}text")):
            return {
                e.tag.removeprefix(SVG)
                for e in group.iter()
                if e.tag not in (f"{SVG}g", f"{SVG}title", f"{SVG}text", f"{SVG}a")
            }
    raise AssertionError(f"no swatch shows {label!r}")


def swatches(g: pgv.AGraph) -> dict[str, Any]:
    return {
        g.get_node(n).attr["label"]: g.get_node(n)
        for n in g.nodes()
        if n.startswith("protee:legend")
    }


def test_a_legend_swatch_takes_the_shape_of_its_nodes() -> None:
    vocabulary = {
        "type": [
            {"id": "x:e", "on": "node", "label": "equation"},
            {"id": "x:v", "on": "node", "label": "variable"},
        ],
        "role": [
            {"id": "x:in", "on": "node", "label": "input"},
            {"id": "x:mixed", "on": "node", "label": "mixed"},
            {"id": "x:unused", "on": "node", "label": "unused"},
            {"id": "x:fixed", "on": "node", "label": "fixed"},
        ],
    }
    nodes = [
        {"id": "a", "type": "x:v", "role": "x:in"},
        {"id": "b", "type": "x:v", "role": "x:mixed"},
        {"id": "c", "type": "x:e", "role": "x:mixed"},
        {"id": "d", "type": "x:e", "role": "x:fixed"},
    ]
    styles: viz.Styles = {"node": {("role", "x:fixed"): {"shape": "hexagon"}}}
    g = drawn(viz.to_dot(document(nodes, [], vocabulary), styles=styles))
    swatch = swatches(g)
    assert (swatch["equation"].attr["shape"], swatch["variable"].attr["shape"]) == (
        "ellipse",
        "box",
    )
    assert swatch["input"].attr["shape"] == "box"  # the shape of its nodes
    assert "rounded" not in swatch["input"].attr["style"]
    for neutral in ("mixed", "unused"):  # several shapes, or no node
        assert swatch[neutral].attr["shape"] == "box"
        assert swatch[neutral].attr["style"].startswith("rounded,filled")
    assert swatch["fixed"].attr["shape"] == "hexagon"  # the caller's
    coare = drawn(viz.to_dot(load(COARE)))
    roles = load(COARE)["graph"]["vocabulary"]["role"]
    on_nodes = [v["label"] for v in roles if v["on"] == "node"]
    assert {swatches(coare)[r].attr["shape"] for r in on_nodes} == {"box"}


def test_render_svg_places_the_legend_below_or_leaves_it_out() -> None:
    data = load(COARE)
    below = viz.render_svg(data, styles=CLOSING, legend="below")
    assert below == viz.render_svg(data, styles=CLOSING, legend="below")
    root = svg_tree(below)
    graph, legend = root.findall(f"{SVG}svg")
    assert "protee:legend" not in ET.tostring(graph, encoding="unicode")
    labels = [v["label"] for vs in data["graph"]["vocabulary"].values() for v in vs]
    assert set(labels) <= set(texts(legend))
    height = float(graph.attrib["height"])
    assert float(legend.attrib["y"]) > height
    width = float(root.attrib["viewBox"].split()[2])
    assert width == max(float(graph.attrib["width"]), float(legend.attrib["width"]))
    alone = svg_tree(viz.render_svg(data, styles=CLOSING, legend=None))
    assert graph.attrib["viewBox"] == alone.attrib["viewBox"]  # the same drawing
    found = [e.attrib["id"] for e in root.iter() if "id" in e.attrib]
    assert len(found) == len(set(found))  # the legend's are prefixed
    right = viz.render_svg(data, styles=CLOSING)
    assert "protee:legend" in right
    assert not svg_tree(right).findall(f"{SVG}svg")
    assert "protee:legend" not in viz.render_svg(data, legend=None)
    plain = document([{"id": 0}, {"id": 1}], [(0, 1)])  # nothing is declared
    assert viz.render_svg(plain, legend="below") == viz.render_svg(plain, legend=None)
    for wrong in (True, "left"):
        with pytest.raises(ValueError, match="legend must be one of"):
            viz.render_svg(data, legend=wrong)  # type: ignore[arg-type]


def test_render_legend_svg_draws_one_column_per_attribute_in_order() -> None:
    data = load(KINDS)
    svg = viz.render_legend_svg(data)
    assert svg == viz.render_legend_svg(data)
    at = texts(svg_tree(svg))
    vocabulary = data["graph"]["vocabulary"]
    columns = [
        [v["label"] for v in vocabulary[attribute] if v["on"] == on]
        for attribute, on in (("type", "node"), ("type", "edge"), ("origin", "node"))
    ]
    for column in columns:  # the first declared value at the top
        ys = [at[label][1] for label in column]
        assert ys == sorted(ys)
    xs = [at[column[0]][0] for column in columns]
    assert xs == sorted(xs)  # the attributes from left to right
    with pytest.raises(ValueError, match="declares no value"):
        viz.render_legend_svg(chain())


def test_the_gallery_is_the_one_its_script_writes(tmp_path: Path) -> None:
    folder = Path(__file__).parents[1] / "docs" / "gallery"
    spec = importlib.util.spec_from_file_location(
        "make_gallery", folder / "make_gallery.py"
    )
    assert spec is not None
    assert spec.loader is not None
    gallery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gallery)
    gallery.write(tmp_path)
    written = sorted(p.name for p in tmp_path.iterdir())
    kept = sorted(p.name for p in folder.iterdir() if p.suffix in {".md", ".svg"})
    assert written == kept
    page = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert page == (folder / "README.md").read_text(encoding="utf-8")
    for name in written:
        if name.endswith(".svg"):
            assert f"]({name})" in page
            again = (tmp_path / name).read_text(encoding="utf-8")
            kept_svg = (folder / name).read_text(encoding="utf-8")
            assert projection(again) == projection(kept_svg), name


def projection(svg: str) -> list[tuple[str, ...]]:
    """What a drawing shows, its positions and sizes aside: those depend on
    the fonts of the workstation, which Graphviz measures."""
    return sorted(
        (
            e.tag.removeprefix(SVG),
            e.get("fill", ""),
            e.get("stroke", ""),
            e.get("stroke-dasharray", ""),
            str(e.text or "").strip(),
        )
        for e in svg_tree(svg).iter()
    )


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
    aside = page[page.index("<aside>") : page.index("</aside>")]
    legend = svg_tree(aside[len("<aside>") : aside.index("</svg>") + len("</svg>")])
    shown = texts(legend)
    assert {"kind", "specializes", "matches"} <= set(shown)
    assert swatch_tags(legend, "kind") >= {"ellipse"}  # its shape, as drawn
    assert '<span class="note">a kind</span>' in aside
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


# What any producer may write ------------------------------------------------


def test_select_reads_infinite_metrics_and_adds_hidden_counts() -> None:
    doc = document(
        [
            {"id": "a", "metrics": {"m": 3}},
            {"id": "b", "metrics": {"m": "inf"}},
            {"id": "c", "metrics": {"m": "-inf"}},
        ],
        [("a", "b"), ("b", "c")],
    )
    kept = viz.select(doc, ["a", "b", "c"], depth=0, threshold=("m", 1))
    assert marked(kept, viz.OUTSIDE) == {"c"}  # "inf" is at least 1
    star = document(
        [{"id": i} for i in ("z", "y1", "y2", "x", "q")],
        [("z", "y1"), ("z", "y2"), ("y1", "x"), ("y2", "x"), ("x", "q")],
    )
    once = viz.select(star, ["y1"], depth=0)
    twice = viz.select(viz.select(star, ["z"], depth=1), ["y1"], depth=0)
    assert hidden(once)["x"] == hidden(twice)["x"] == 2  # y2 and q


@given(graph=graphs(), data=st.data())
def test_select_reaches_what_networkx_reaches(
    graph: Digraph, data: st.DataObject
) -> None:
    doc = io.to_node_link(graph)
    names = [n["id"] for n in doc["nodes"]]
    starts = data.draw(
        st.lists(st.sampled_from(names), min_size=1, max_size=3, unique=True)
    )
    depth = data.draw(st.integers(0, 3))
    direction = data.draw(st.sampled_from(["both", "out", "in"]))
    out = viz.select(doc, starts, depth=depth, direction=direction)
    g = nx.node_link_graph(doc, edges="edges")
    view = {
        "out": g,
        "in": g.reverse(copy=False),
        "both": g.to_undirected(as_view=True),
    }[direction]
    reached: set[Any] = set()
    for s in starts:
        reached |= set(nx.single_source_shortest_path_length(view, s, cutoff=depth))
    selected = set(ids(out)) - marked(out, viz.OUTSIDE)
    assert selected == reached
    assert pairs(out) == [
        (e["source"], e["target"])
        for e in doc["edges"]
        if e["source"] in selected or e["target"] in selected
    ]
    assert io.check_node_link(out) == ()


def test_collapse_keeps_the_metrics_of_an_edge_redirected_alone() -> None:
    doc = document(
        [{"id": "a", "family": "f"}, {"id": "b", "family": "f"}, {"id": "c"}],
        [
            {"source": "a", "target": "c", "label": "x", "metrics": {"w": 3}},
            {"source": "c", "target": "a", "metrics": {"w": 1, "v": 2}},
            {"source": "c", "target": "b", "metrics": {"w": 1}},
        ],
    )
    out = viz.collapse(doc)
    assert out["edges"] == [
        {
            "source": "family=f",
            "target": "c",
            "label": "x",
            "metrics": {"w": 3},
            "key": 0,
        },
        {
            "source": "c",
            "target": "family=f",
            "metrics": {"w": 1, viz.MERGED: 2},
            "key": 0,
        },
    ]
    assert io.check_node_link(out) == ()
    by_type = viz.collapse(
        document(
            [{"id": "a", "type": "t"}, {"id": "b", "type": "t"}, {"id": "c"}],
            [("a", "c")],
        ),
        by="type",
    )
    assert ids(by_type) == ["type=t", "c"]
    with pytest.raises(TypeError, match="not a text or a number"):
        viz.collapse(document([{"id": "a", "tags": ["x"]}], []), by="tags")


def test_loops_tell_apart_ids_that_write_the_same() -> None:
    doc = document([{"id": 1}, {"id": "1"}, {"id": 2}], [(1, 2), (2, 1), ("1", 2)])
    out = viz.condense(doc)
    (loop,) = (n for n in out["nodes"] if n.get(viz.DISPLAY) == viz.LOOP)
    assert loop[viz.CONTAINS] == [1, 2]
    assert io.check_node_link(out) == ()


def test_read_only_documents_are_drawn() -> None:
    block = MappingProxyType(load(KINDS)["graph"])  # a read-only graph block
    assert io.check_node_link(dict(load(KINDS), graph=block)) == ()
    assert viz.to_dot(dict(load(KINDS), graph=block)) == viz.to_dot(load(KINDS))


def test_links_that_open_a_script_are_dropped() -> None:
    urls = {
        "a": "javascript:alert(1)",
        "b": " JaVaScRiPt:alert(1)",
        "c": "java\tscript:alert(1)",
        "d": "data:text/html,<b>x</b>",
        "e": "https://example.org/e",
        "f": "doc.html#f",
        "g": "mailto:?subject=protee",
    }
    nodes: list[dict[str, Any]] = [{"id": i, "url": u} for i, u in urls.items()]
    nodes[4]["iri"] = "https://example.org/iri/e"
    doc = document(nodes, [])
    g = drawn(viz.to_dot(doc, legend=False))
    links = {i: g.get_node(i).attr["URL"] or None for i in urls}
    safe = {"e": urls["e"], "f": urls["f"], "g": urls["g"]}
    assert links == {i: safe.get(i) for i in urls}
    assert g.get_node("e").attr["tooltip"] == "\\n".join(
        ["e", "https://example.org/iri/e", urls["e"]]
    )
    found, _ = page_parts(viz.render_html(doc))
    assert {n["data"]["id"]: n["data"].get("url") for n in found} == links


def test_the_page_resists_texts_that_look_like_markup() -> None:
    label = "<!--<script>"
    doc = document([{"id": "a", "label": label, "description": "<!-- <script>"}], [])
    page = viz.render_html(doc)
    start = page.index('id="protee-elements">') + len('id="protee-elements">')
    assert "<" not in page[start : page.index("</script>", start)]
    found, _ = page_parts(page)
    assert found[0]["data"]["label"] == label


def test_the_page_places_ids_that_dot_writes_otherwise() -> None:
    names = ["C:\\dir", "two\nlines", "ends\\"]
    doc = document(
        [{"id": i} for i in names], [(names[0], names[1]), (names[1], names[2])]
    )
    found, _ = page_parts(viz.render_html(doc))
    assert [n["data"]["id"] for n in found] == names
    heights = [n["position"]["y"] for n in found]
    assert heights == sorted(heights)  # a chain, from top to bottom
    assert len(set(heights)) == 3


def test_order_by_keeps_the_groups_of_the_page_whole() -> None:
    doc = document(
        [
            {"id": "a", "family": "f", "r": 1},
            {"id": "b", "family": "g", "r": 1},
            {"id": "c", "family": "f", "r": 2},
            {"id": "d", "family": "g", "r": 2},
        ],
        [("a", "d"), ("b", "c")],
    )
    found, _ = page_parts(viz.render_html(doc, order_by="r"))
    at = {n["data"]["id"]: n["position"] for n in found if "position" in n}
    f = sorted([at["a"]["x"], at["c"]["x"]])
    g = sorted([at["b"]["x"], at["d"]["x"]])
    assert f[1] < g[0] or g[1] < f[0]  # the groups do not interleave
    assert at["a"]["y"] == at["b"]["y"]  # equal values, same rank
    assert at["c"]["y"] == at["d"]["y"]


def test_internal_names_leave_the_ids_of_a_document_alone() -> None:
    vocabulary = {
        "type": [
            {"id": "x:k", "on": "node", "label": "kind"},
            {"id": "x:r", "on": "edge", "label": "rel"},
        ]
    }
    nodes = [
        {"id": "protee:legend:0", "label": "mine", "type": "x:k"},
        {"id": "protee:edge:0", "type": "x:k"},
    ]
    edges = [{"source": "protee:legend:0", "target": "protee:edge:0", "type": "x:r"}]
    doc = document(nodes, edges, vocabulary)
    g = drawn(viz.to_dot(doc))
    assert g.get_node("protee:legend:0").attr["label"] == "mine"
    assert len(g.nodes()) == 2 + 3  # two nodes; a node swatch, an edge swatch
    found, links = page_parts(viz.render_html(doc))
    names = [e["data"]["id"] for e in found + links]
    assert len(names) == len(set(names))
    assert len(links) == 1


def test_gradient_fills_stay_referenced_and_stable() -> None:
    vocabulary = {"type": [{"id": "x:k", "on": "node", "label": "kind"}]}
    doc = document(
        [{"id": "a", "type": "x:k"}, {"id": "b", "type": "x:k"}],
        [("a", "b")],
        vocabulary,
    )
    styles: viz.Styles = {
        "node": {("type", "x:k"): {"style": "filled", "fillcolor": "red:blue"}}
    }
    first = viz.render_svg(doc, styles=styles, legend="below")
    assert first == viz.render_svg(doc, styles=styles, legend="below")
    referenced = set(re.findall(r"url\(#([^)]+)\)", first))
    defined = set(re.findall(r' id="([^"]+)"', first))
    assert referenced
    assert referenced <= defined


def test_a_nul_character_is_refused_with_a_clear_message() -> None:
    with pytest.raises(ValueError, match="NUL"):
        viz.to_dot(document([{"id": "a", "label": "x\x00y"}], []))


def test_the_legends_take_the_styles_of_the_caller() -> None:
    vocabulary = {"type": [{"id": "x:k", "on": "node", "label": "kind"}]}
    doc = document([{"id": "a", "type": "x:k"}], [], vocabulary)
    styles: viz.Styles = {"node": {("type", "x:k"): {"shape": "box"}}}
    assert swatch_tags(svg_tree(viz.render_legend_svg(doc)), "kind") == {"ellipse"}
    alone = svg_tree(viz.render_legend_svg(doc, styles=styles))
    assert swatch_tags(alone, "kind") == {"polygon"}
    below = svg_tree(viz.render_svg(doc, styles=styles, legend="below"))
    graph, legend = below.findall(f"{SVG}svg")
    assert swatch_tags(legend, "kind") == {"polygon"}
    width = float(below.attrib["viewBox"].split()[2])
    for part in (graph, legend):
        centre = (width - float(part.attrib["width"])) / 2
        assert float(part.attrib["x"]) == pytest.approx(centre, abs=0.01)


def test_render_html_follows_its_direction_and_leaves_lone_members_alone() -> None:
    doc = document(
        [
            {"id": "a", "family": "f"},
            {"id": "b", "family": "g"},
            {"id": "c", "family": "g"},
        ],
        [("a", "b"), ("b", "c")],
    )
    found, _ = page_parts(viz.render_html(doc, direction="LR"))
    by_id = {n["data"]["id"]: n for n in found}
    xs = [by_id[i]["position"]["x"] for i in "abc"]
    assert xs == sorted(xs)
    assert len(set(xs)) == 3
    assert "parent" not in by_id["a"]["data"]  # alone in its family
    assert by_id["b"]["data"]["parent"] == by_id["c"]["data"]["parent"]
