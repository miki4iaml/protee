# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Rendering of node-link documents: contraction, layout attributes,
legend options, themes, footer, orthogonal edges and the matrix view.

NetworkX is the oracle of the contraction and of the matrix; Graphviz,
through pygraphviz, reads the DOT text; the contrast ratios are computed
here, after WCAG 2.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import networkx as nx
import pygraphviz as pgv
import pytest
from hypothesis import given
from hypothesis import strategies as st
from oracles import graphs

from protee import io, viz
from protee.flow import FlowProblem
from protee.graph import Digraph
from protee.transforms import split_nodes

DATA = Path(__file__).parent / "data" / "node_link"
COARE = "nomogram-0.8.0-coare36-surface-layer.json"
KINDS = "nomogram-0.8.0-humidity-kinds.json"
CLOSING: viz.Styles = {
    "edge": {("role", "nomogram:closing"): {"style": "dashed", "constraint": "false"}}
}
ORTHO: viz.Attributes = {"graph": {"splines": "ortho"}}
SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATA / name).read_text(encoding="utf-8"))
    return data


def document(
    nodes: list[dict[str, Any]],
    edges: list[Any],  # (source, target) pairs, or edge objects
    vocabulary: dict[str, Any] | None = None,
    *,
    multigraph: bool = True,
) -> dict[str, Any]:
    graph: dict[str, Any] = {"format": io.NODE_LINK_FORMAT}
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


def ids(doc: dict[str, Any]) -> list[Any]:
    return [n["id"] for n in doc["nodes"]]


def pairs(doc: dict[str, Any]) -> list[tuple[Any, Any]]:
    return [(e["source"], e["target"]) for e in doc["edges"]]


def legend_nodes(dot: str) -> dict[str, dict[str, str]]:
    """The attributes of the node swatches of the legend cluster, by label.

    The graph is kept alive while its nodes are read: pygraphviz frees them
    with it.
    """
    graph = pgv.AGraph(string=dot)
    return {
        n.attr["label"]: dict(n.attr)
        for n in graph.nodes()
        if n.name.startswith("protee:legend") and not n.name.endswith((":a", ":b"))
    }


def texts(svg: str) -> list[str]:
    return [
        "".join(t.itertext()).strip() for t in ET.fromstring(svg).iter(f"{SVG}text")
    ]


def luminance(colour: str) -> float:
    """The relative luminance of WCAG 2."""
    values = []
    for i in (1, 3, 5):
        c = int(colour[i : i + 2], 16) / 255
        values.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# Contraction ---------------------------------------------------------------


def test_contract_joins_each_equation_with_the_variable_it_gives() -> None:
    coare = load(COARE)
    gives = [e for e in coare["edges"] if e["type"] == "nomogram:gives"]
    out = viz.contract(coare, edge_type="nomogram:gives")
    assert io.check_node_link(out) == ()
    assert len(out["nodes"]) == len(coare["nodes"]) - len(gives)
    assert not any(e.get("type") == "nomogram:gives" for e in out["edges"])
    by_id = {n["id"]: n for n in out["nodes"]}
    equations = {n["id"]: n for n in coare["nodes"]}
    for e in gives:
        kept = by_id[e["target"]]
        assert kept["rank"] == equations[e["source"]]["rank"]
        assert kept["type"] == "nomogram:variable"
        assert kept[viz.CONTAINS] == [e["target"], e["source"]]
        assert kept["metrics"][viz.MEMBERS] == 2
    assert coare == load(COARE)  # the input is left as it was


@pytest.mark.parametrize(
    ("edges", "message"),
    [
        ([("a", "a")], "is a loop on node 'a'"),
        ([("a", "b"), ("b", "c")], "touch at node 'b'"),
        ([("a", "b"), ("a", "b")], "touch at node 'a'"),
        ([("a", "b"), ("b", "a")], "touch at node 'b'"),
    ],
)
def test_contract_refuses_edges_that_touch(
    edges: list[tuple[str, str]], message: str
) -> None:
    doc = document(
        [{"id": i} for i in "abc"],
        [{"source": s, "target": t, "type": "c"} for s, t in edges],
    )
    with pytest.raises(ValueError, match=re.escape(message)):
        viz.contract(doc, edge_type="c")


def test_contract_checks_keep_and_copies_without_such_edges() -> None:
    doc = document([{"id": i} for i in "ab"], [("a", "b")])
    with pytest.raises(ValueError, match="keep must be"):
        viz.contract(doc, edge_type="c", keep="both")
    out = viz.contract(doc, edge_type="c")
    assert out == doc
    assert out is not doc


def test_contract_completes_the_kept_node_and_merges_its_marks() -> None:
    doc = document(
        [
            {
                "id": "e",
                "label": "equation",
                "rank": 3,
                "metrics": {viz.HIDDEN: 2, "w": 5},
                viz.SELECTION: viz.OUTSIDE,
                viz.DISPLAY: viz.GROUP,
                viz.CONTAINS: ["e1", "e2"],
            },
            {
                "id": "v",
                "label": "variable",
                "unit": "m",
                "metrics": {viz.HIDDEN: 1, "w": 7},
                viz.SELECTION: viz.OUTSIDE,
            },
            {"id": "w"},
        ],
        [{"source": "e", "target": "v", "type": "c", "label": "gives"}, ("w", "e")],
    )
    out = viz.contract(doc, edge_type="c")
    assert out["nodes"][0] == {
        "id": "v",
        "label": "variable",
        "unit": "m",
        "rank": 3,
        "metrics": {viz.HIDDEN: 3, "w": 7, viz.MEMBERS: 3},
        viz.SELECTION: viz.OUTSIDE,
        viz.CONTAINS: ["v", "e1", "e2"],
    }
    assert out["edges"] == [{"source": "w", "target": "v", "key": 0}]
    # Selected as soon as one end was.
    doc["nodes"][0].pop(viz.SELECTION)
    assert viz.SELECTION not in viz.contract(doc, edge_type="c")["nodes"][0]


def test_contract_keeps_parallel_edges_apart_and_inner_edges_as_loops() -> None:
    doc = document(
        [{"id": i} for i in "abc"],
        [
            {"source": "a", "target": "b", "type": "c"},
            ("c", "a"),
            ("c", "b"),
            {"source": "b", "target": "a", "key": 0},
        ],
        multigraph=False,
    )
    out = viz.contract(doc, edge_type="c")
    assert sorted(pairs(out)) == [("b", "b"), ("c", "b"), ("c", "b")]
    assert out["multigraph"] is True
    assert io.check_node_link(out) == ()


def test_the_trace_follows_repeated_contractions() -> None:
    doc = document(
        [{"id": i} for i in "abc"],
        [
            {"source": "a", "target": "b", "type": "c"},
            {"source": "b", "target": "c", "type": "d"},
        ],
    )
    twice = viz.contract(viz.contract(doc, edge_type="c"), edge_type="d")
    assert twice["nodes"] == [
        {"id": "c", viz.CONTAINS: ["c", "b", "a"], "metrics": {viz.MEMBERS: 3}}
    ]


@given(graph=graphs(), data=st.data())
def test_contract_matches_the_contraction_of_networkx(
    graph: Digraph, data: st.DataObject
) -> None:
    arcs = list(graph.arcs())
    chosen = (
        data.draw(st.lists(st.integers(0, len(arcs) - 1), unique=True)) if arcs else []
    )
    ends: set[int] = set()
    matching = []
    for a in chosen:
        t, h = arcs[a]
        if t != h and t not in ends and h not in ends:
            ends |= {t, h}
            matching.append(a)
    keep = data.draw(st.sampled_from(["target", "source"]))
    types = ["x:c" if a in matching else None for a in range(len(arcs))]
    doc = io.to_node_link(graph, arcs={"type": types})
    out = viz.contract(doc, edge_type="x:c", keep=keep)
    oracle = nx.MultiDiGraph()
    oracle.add_nodes_from(ids(doc))
    oracle.add_edges_from(
        (e["source"], e["target"]) for e in doc["edges"] if e.get("type") != "x:c"
    )
    for e in doc["edges"]:
        if e.get("type") == "x:c":
            s, t = e["source"], e["target"]
            stays, goes = (t, s) if keep == "target" else (s, t)
            # NetworkX counts a loop of the node that goes twice.
            loops = oracle.number_of_edges(goes, goes)
            oracle.remove_edges_from([(goes, goes)] * loops)
            oracle = nx.contracted_nodes(oracle, stays, goes, self_loops=True)
            oracle.add_edges_from([(stays, stays)] * loops)
    assert ids(out) == [i for i in ids(doc) if i in oracle]
    assert sorted(pairs(out)) == sorted(oracle.edges())
    assert io.check_node_link(out) == ()


def test_contract_undoes_a_split_of_nodes() -> None:
    graph = Digraph.from_arcs(4, [(0, 1), (1, 2), (2, 0), (0, 3), (3, 3), (0, 1)])
    split = split_nodes(FlowProblem(graph)).problem.graph
    doc = io.to_node_link(
        split, arcs={"type": [None] * graph.m + ["x:split"] * graph.n}
    )
    out = viz.contract(doc, edge_type="x:split", keep="source")
    original = io.to_node_link(graph)
    back = dict(zip(ids(doc)[: graph.n], ids(original), strict=True))
    assert ids(out) == ids(doc)[: graph.n]
    assert sorted((back[s], back[t]) for s, t in pairs(out)) == sorted(pairs(original))


# Legend --------------------------------------------------------------------


def test_the_legend_shows_only_the_values_present_with_the_same_styles() -> None:
    loop = viz.contract(load(COARE), edge_type="nomogram:gives")
    every = legend_nodes(viz.to_dot(loop))
    present = legend_nodes(viz.to_dot(loop, legend_values="present"))
    assert "equation" in every
    assert "equation" not in present
    assert set(present) < set(every)
    for label, attributes in present.items():
        assert attributes == every[label]
    legend = viz.render_legend_svg(loop, values="present")
    assert "gives" not in texts(legend)
    assert "reads" in texts(legend)


def test_a_legend_without_present_values() -> None:
    doc = document(
        [{"id": "a"}], [], {"type": [{"id": "x:k", "on": "node", "label": "kind"}]}
    )
    with pytest.raises(ValueError, match="no node or edge carries"):
        viz.render_legend_svg(doc, values="present")
    svg = viz.render_svg(doc, legend="below", legend_values="present")
    assert svg.count("<svg") == 1
    with pytest.raises(ValueError, match="legend_values must be"):
        viz.to_dot(doc, legend_values="some")
    with pytest.raises(ValueError, match="values must be"):
        viz.render_legend_svg(doc, values="some")


def test_a_legend_below_at_the_left() -> None:
    kinds = load(KINDS)
    for legend, left in (("below", False), ("below-left", True)):
        root = ET.fromstring(viz.render_svg(kinds, legend=legend))
        _, below = root.findall(f"{SVG}svg")
        width = float(root.get("viewBox", "").split()[2])
        x = float(below.get("x", ""))
        expected = 0.0 if left else (width - float(below.get("width", ""))) / 2
        assert x == pytest.approx(expected, abs=0.01)


def test_the_legend_lists_the_mappings_of_a_value() -> None:
    doc = document(
        [{"id": "a", "type": "x:k"}],
        [],
        {
            "type": [
                {
                    "id": "x:k",
                    "on": "node",
                    "label": "kind",
                    "description": "a kind",
                    "mappings": [{"predicate": "x:exact", "object": "x:Kind"}],
                }
            ]
        },
    )
    swatch = legend_nodes(viz.to_dot(doc))["kind"]
    # pygraphviz gives the text as written in DOT, its line breaks escaped.
    assert swatch["tooltip"] == "a kind\\nx:exact x:Kind"


# Layout attributes -----------------------------------------------------------


def test_attributes_set_the_graph_and_all_its_elements() -> None:
    dot = viz.to_dot(
        load(KINDS),
        attributes={
            "graph": {"splines": "polyline", "ranksep": "1.2"},
            "node": {"fontsize": "11"},
            "edge": {"fontsize": "9"},
        },
    )
    graph = pgv.AGraph(string=dot)
    assert graph.graph_attr["splines"] == "polyline"
    assert graph.graph_attr["ranksep"] == "1.2"
    assert {
        n.attr["fontsize"] for n in graph.nodes() if not n.name.endswith((":a", ":b"))
    } == {"11"}
    assert {e.attr["fontsize"] for e in graph.edges()} == {"9"}
    legend = viz.render_legend_svg(load(KINDS), attributes={"node": {"fontsize": "11"}})
    sizes = {t.get("font-size") for t in ET.fromstring(legend).iter(f"{SVG}text")}
    assert "11.00" in sizes


@pytest.mark.parametrize(
    ("attributes", "message"),
    [
        ({"graph": {"rankdir": "LR"}}, "sets the layout only"),
        ({"cluster": {"style": "dashed"}}, "unknown kinds"),
        ({"node": {"font size": "11"}}, "invalid Graphviz attribute names"),
    ],
)
def test_attributes_are_checked(attributes: viz.Attributes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        viz.to_dot(load(KINDS), attributes=attributes)


def test_styles_name_nodes_and_edges_only() -> None:
    with pytest.raises(ValueError, match="unknown kinds of element"):
        viz.to_dot(load(KINDS), styles={"graph": {}})


def test_without_theme_nor_attributes_the_text_is_unchanged() -> None:
    dot = viz.to_dot(load(COARE), styles=CLOSING, order_by="rank")
    digest = hashlib.sha256(dot.encode()).hexdigest()
    assert digest == "0cfe350b08a5821e6f600d0c38feeaa3254c57469fc0f889e04dbefbe8758599"


# Orthogonal edges ------------------------------------------------------------


def test_the_child_process_draws_as_the_caller_would() -> None:
    dot = viz.to_dot(load(KINDS), attributes={"graph": {"splines": "polyline"}})
    inside: bytes = pgv.AGraph(string=dot).draw(format="svg", prog="dot")
    assert viz._drawn_apart(dot) == inside


def test_orthogonal_edges_are_drawn_apart() -> None:
    svg = viz.render_svg(load(COARE), attributes=ORTHO, order_by="rank", legend=None)
    assert ET.fromstring(svg).tag == f"{SVG}svg"


@pytest.mark.parametrize(
    ("program", "message"),
    [
        ("import os; os._exit(3)", "exit code 3)"),
        ("import sys; sys.stdout.write('no drawing')", "exit code 0)"),
        (
            "import sys; sys.stderr.write('lost edge'); sys.exit(1)",
            "exit code 1): lost edge",
        ),
    ],
)
def test_a_child_that_stops_raises_and_the_caller_goes_on(
    monkeypatch: pytest.MonkeyPatch, program: str, message: str
) -> None:
    monkeypatch.setattr(viz, "_CHILD", program)
    with pytest.raises(RuntimeError, match=re.escape(message)):
        viz.render_svg(load(KINDS), attributes=ORTHO, legend=None)


def test_orthogonal_edges_need_a_python_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(RuntimeError, match="cannot start"):
        viz.render_svg(load(KINDS), attributes=ORTHO, legend=None)
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setattr(sys, "executable", "")
    with pytest.raises(RuntimeError, match="cannot start"):
        viz.render_svg(load(KINDS), attributes=ORTHO, legend=None)


def test_the_tree_that_stops_graphviz_gives_an_error_or_a_drawing() -> None:
    # In-process, this layout stops the Python of Graphviz 14.1.5.
    outcome: str | Exception
    try:
        outcome = viz.render_svg(load(KINDS), attributes=ORTHO, legend=None)
    except RuntimeError as err:
        outcome = err
    if isinstance(outcome, Exception):
        assert "orthogonal" in str(outcome)
    else:
        assert "<svg" in outcome


# Themes ----------------------------------------------------------------------


def test_a_theme_is_written_with_six_hexadecimal_digits() -> None:
    with pytest.raises(ValueError, match="Theme.ink"):
        viz.Theme(background="#FFFFFF", ink="black", muted="#777777")


@pytest.mark.parametrize("theme", [viz.LIGHT, viz.DARK])
def test_the_themes_read_well(theme: viz.Theme) -> None:
    assert contrast(theme.ink, theme.background) >= 4.5
    assert contrast(theme.muted, theme.background) >= 3
    # Seven values of a second node attribute: the seven fills, and the text
    # written on each.
    values = [{"id": f"x:{k}", "on": "node", "label": f"v{k}"} for k in range(7)]
    doc = document(
        [{"id": f"n{k}", "type": "x:t", "status": f"x:{k}"} for k in range(7)],
        [],
        {"type": [{"id": "x:t", "on": "node", "label": "t"}], "status": values},
    )
    graph = pgv.AGraph(string=viz.to_dot(doc, theme=theme, legend=False))
    assert graph.graph_attr["bgcolor"] == theme.background
    for node in graph.nodes():
        fill, text = node.attr["fillcolor"], node.attr["fontcolor"]
        assert contrast(text, fill) >= 4.5, (fill, text)


def test_the_dark_theme_draws_black_lines_in_ink() -> None:
    values = [{"id": f"x:{k}", "on": "edge", "label": f"e{k}"} for k in range(7)]
    doc = document(
        [{"id": "a"}, {"id": "b"}],
        [{"source": "a", "target": "b", "type": f"x:{k}"} for k in range(7)],
        {"type": values},
    )
    plain = pgv.AGraph(string=viz.to_dot(doc))
    assert "#000000" in [e.attr["color"] for e in plain.edges()]
    dark = pgv.AGraph(string=viz.to_dot(doc, theme=viz.DARK))
    colours = [e.attr["color"] for e in dark.edges()]
    assert "#000000" not in colours
    assert viz.DARK.ink in colours


def test_a_themed_figure_has_one_background() -> None:
    svg = viz.render_svg(load(KINDS), theme=viz.DARK, legend="below")
    root = ET.fromstring(svg)
    background = root.find(f"{SVG}rect")
    assert background is not None
    assert background.get("fill") == viz.DARK.background


# Footer ----------------------------------------------------------------------


def png(width: int, height: int) -> bytes:
    """The start of a PNG image: its signature and its header."""
    header = struct.pack(">II", width, height) + bytes(5)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + header + bytes(4)


LOGO = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,120,40">'
    b'<rect id="a" width="120" height="40"/></svg>'
)


@pytest.mark.parametrize(
    ("image", "media"), [(png(300, 100), "png"), (LOGO, "svg+xml")]
)
def test_a_footer_is_embedded_at_the_right_of_the_legend(
    image: bytes, media: str
) -> None:
    kinds = load(KINDS)
    svg = viz.render_svg(kinds, legend="below-left", footer=image)
    assert svg == viz.render_svg(kinds, legend="below-left", footer=image)
    root = ET.fromstring(svg)
    _, legend = root.findall(f"{SVG}svg")
    (footer,) = root.findall(f"{SVG}image")
    width = float(root.get("viewBox", "").split()[2])
    assert float(legend.get("x", "")) == 0
    right = float(footer.get("x", "")) + float(footer.get("width", ""))
    assert right == pytest.approx(width, abs=0.01)
    height = float(footer.get("height", ""))
    assert height == pytest.approx(float(legend.get("height", "")), abs=0.01)
    assert float(footer.get("width", "")) == pytest.approx(3 * height, abs=0.01)
    encoded = base64.b64encode(image).decode()
    assert footer.get(f"{XLINK}href") == f"data:image/{media};base64,{encoded}"
    names = [e.get("id") for e in root.iter() if e.get("id")]
    assert len(names) == len(set(names))


def test_a_footer_without_legend_needs_its_height() -> None:
    kinds = load(KINDS)
    with pytest.raises(ValueError, match="footer_height is needed"):
        viz.render_svg(kinds, legend=None, footer=LOGO)
    root = ET.fromstring(
        viz.render_svg(kinds, legend=None, footer=LOGO, footer_height=36)
    )
    (footer,) = root.findall(f"{SVG}image")
    assert float(footer.get("height", "")) == 36
    for height in (0, float("nan")):
        with pytest.raises(ValueError, match="footer_height must be"):
            viz.render_svg(kinds, footer=LOGO, footer_height=height)


@pytest.mark.parametrize(
    ("image", "error", "message"),
    [
        ("logo.png", TypeError, "never a file name"),
        (png(0, 10), ValueError, "zero width"),
        (b"\x89PNG\r\n\x1a\n", ValueError, "IHDR"),
        (b"\x1f\x8b\x08\x00", ValueError, "compressed"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', ValueError, "viewBox"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 4"/>',
            ValueError,
            "viewBox",
        ),
        (
            (
                b'<!DOCTYPE svg [<!ENTITY a "b">]>'
                b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
            ),
            ValueError,
            "DOCTYPE",
        ),
        (b"<html/>", ValueError, "neither a PNG nor an SVG"),
        (b"GIF89a", ValueError, "neither a PNG nor an SVG"),
    ],
)
def test_a_footer_is_a_png_or_an_svg_image(
    image: Any, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        viz.render_svg(load(KINDS), legend="below", footer=image)


# Matrix ----------------------------------------------------------------------


def cells(svg: str) -> tuple[dict[tuple[int, int], int], dict[int, int]]:
    """The counts of the cells (the diagonal included) and of the inputs."""
    found: dict[tuple[int, int], int] = {}
    inputs: dict[int, int] = {}
    for g in ET.fromstring(svg).iter(f"{SVG}g"):
        kind, count = g.get("class"), int(g.get("data-count", "0"))
        if kind == "protee-cell":
            found[(int(g.get("data-row", "")), int(g.get("data-col", "")))] = count
        elif kind == "protee-diagonal" and count:
            index = int(g.get("data-index", ""))
            found[(index, index)] = count
        elif kind == "protee-input":
            inputs[int(g.get("data-col", ""))] = count
    return found, inputs


@given(graph=graphs(), data=st.data())
def test_the_matrix_counts_the_edges_as_networkx(
    graph: Digraph, data: st.DataObject
) -> None:
    doc = io.to_node_link(graph)
    ranks = data.draw(
        st.lists(st.sampled_from([None, 0, 1, 2]), min_size=graph.n, max_size=graph.n)
    )
    for node, rank in zip(doc["nodes"], ranks, strict=True):
        if rank is not None:
            node["rank"] = rank
    if all(rank is None for rank in ranks):
        with pytest.raises(ValueError, match="no node carries 'rank'"):
            viz.render_matrix_svg(doc, order_by="rank")
        return
    order = [
        node["id"]
        for _, _, node in sorted(
            (node["rank"], k, node)
            for k, node in enumerate(doc["nodes"])
            if "rank" in node
        )
    ]
    oracle = nx.MultiDiGraph()
    oracle.add_nodes_from(ids(doc))
    oracle.add_edges_from(pairs(doc))
    found, inputs = cells(viz.render_matrix_svg(doc, order_by="rank"))
    expected: dict[tuple[int, int], int] = {}
    # NetworkX 3.7 fails on a multigraph without edges among the nodes.
    if oracle.subgraph(order).number_of_edges():
        matrix = nx.to_numpy_array(oracle, nodelist=order, weight=None)
        expected = {
            (r, c): int(matrix[r][c])
            for r in range(len(order))
            for c in range(len(order))
            if matrix[r][c]
        }
    assert found == expected
    outside = set(ids(doc)) - set(order)
    counted = {
        c: sum(1 for s, t in pairs(doc) if s in outside and t == name)
        for c, name in enumerate(order)
    }
    assert inputs == {c: k for c, k in counted.items() if k}


def test_the_feedbacks_of_coare_are_its_closing_reads() -> None:
    loop = viz.contract(load(COARE), edge_type="nomogram:gives")
    order = [n["id"] for n in sorted(loop["nodes"], key=lambda n: n.get("rank", -1))]
    order = [
        i for i in order if any(n["id"] == i and "rank" in n for n in loop["nodes"])
    ]
    closing = {
        (order.index(e["source"]), order.index(e["target"]))
        for e in loop["edges"]
        if e.get("role") == "nomogram:closing"
    }
    found, _ = cells(viz.render_matrix_svg(loop, order_by="rank"))
    assert {cell for cell in found if cell[0] > cell[1]} == closing


def test_the_matrix_frames_ties_and_loops_and_takes_a_theme() -> None:
    doc = document(
        [{"id": "a", "rank": 1}, {"id": "b", "rank": 1}, {"id": "c", "rank": 2}],
        [("a", "c"), ("c", "a")],
        multigraph=False,
    )
    svg = viz.render_matrix_svg(doc, order_by="rank", loops=True, theme=viz.DARK)
    root = ET.fromstring(svg)
    frames = {r.get("class"): r for r in root.iter(f"{SVG}rect") if r.get("class")}
    assert frames["protee-tie"].get("width") == str(2 * 24)
    assert frames["protee-loop"].get("width") == str(3 * 24)
    assert root.find(f"{SVG}rect") is not None
    assert root.find(f"{SVG}rect").get("fill") == viz.DARK.background  # type: ignore[union-attr]


def test_the_matrix_escapes_its_texts_and_needs_no_graphviz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pygraphviz", None)
    label = 'a < b & "c"'
    doc = document([{"id": "a", "label": label, "rank": 0}], [])
    assert any(label in t for t in texts(viz.render_matrix_svg(doc, order_by="rank")))
    for bad in ("x\x01", "x\ud800", "x" + chr(0xFFFF)):
        doc["nodes"][0]["label"] = bad
        with pytest.raises(ValueError, match="XML cannot carry"):
            viz.render_matrix_svg(doc, order_by="rank")
    doc["nodes"][0]["rank"] = "first"
    with pytest.raises(TypeError, match="is not a number"):
        viz.render_matrix_svg(doc, order_by="rank")
