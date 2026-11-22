# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Drawing of node-link documents (``protee-node-link/0``).

The functions take and return node-link documents, the decoded JSON that
:func:`protee.io.check_node_link` checks, never protee objects: a producer
of documents does not need protee's model. Nothing here depends on a
producer: the legend comes from the vocabulary declared in the document,
the styles from a table given by the caller.

- :func:`select`, :func:`collapse`, :func:`condense` and :func:`reduce`
  turn a document into a document that follows the format; the marks they
  add are declared under the ``protee`` prefix (:data:`DISPLAY`);
- :func:`to_dot` writes the Graphviz DOT text of a document, without any
  dependency;
- :func:`render_svg` lays it out and draws it in SVG through Graphviz,
  with the optional extra ``viz`` (pygraphviz, which bundles Graphviz);
  :func:`render_legend_svg` draws its legend alone;
- :func:`render_html` writes a page to explore it, which opens offline,
  with the same layout and styles.

Provisional API (until version 1.0).
"""

from __future__ import annotations

import copy
import html
import itertools
import json
import math
import re
from collections import deque
from collections.abc import Iterable, Mapping
from importlib.resources import files
from typing import Any

from protee.graph import Digraph
from protee.io import check_node_link, from_node_link
from protee.structure import strong_components

__all__ = [
    "CONTAINS",
    "DISPLAY",
    "GROUP",
    "HIDDEN",
    "LOOP",
    "MEMBERS",
    "MERGED",
    "OKABE_ITO",
    "OUTSIDE",
    "Styles",
    "collapse",
    "condense",
    "reduce",
    "render_html",
    "render_legend_svg",
    "render_svg",
    "select",
    "to_dot",
]

#: Attribute of the marks protee adds, and its values.
DISPLAY = "protee:display"
OUTSIDE = "protee:outside"
GROUP = "protee:group"
LOOP = "protee:loop"
#: Metrics protee adds: the neighbours not shown, the members of a group,
#: the edges merged into one.
HIDDEN = "protee:hidden"
MEMBERS = "protee:members"
MERGED = "protee:merged"
#: Key listing the identifiers of the members of a group.
CONTAINS = "protee:contains"

#: A palette told apart with the common colour vision deficiencies (Okabe
#: and Ito): orange, sky blue, bluish green, yellow, blue, vermilion,
#: reddish purple, black.
OKABE_ITO = (
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#000000",
)

#: Graphviz attributes by kind of element, then by (attribute, value).
type Styles = Mapping[str, Mapping[tuple[str, Any], Mapping[str, str]]]

_SHAPES = ("ellipse", "box", "diamond", "hexagon", "octagon", "house", "trapezium")
# Dashes are left to the marks (nodes) and to the absence of a value
# (edges: a value of the second attribute is never drawn plain).
_NODE_LINES = ("solid", "bold", "dotted")
_EDGE_LINES = ("dashed", "dotted", "bold")
_ARROWS = ("normal", "empty", "dot", "odot", "diamond", "odiamond", "box", "obox")
# Yellow is too light for a thin line on white: it only fills nodes.
_LINE_COLOURS = tuple(c for c in OKABE_ITO if c != "#F0E442")
_FONT = "Helvetica,Arial,sans-serif"
_DIRECTIONS = ("TB", "LR", "BT", "RL")
_LEGEND_PLACES = ("right", "below", None)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MARKS: dict[str, dict[str, str]] = {
    OUTSIDE: {
        "id": OUTSIDE,
        "on": "node",
        "label": "outside the selection",
        "description": "a direct neighbour of the selection, not selected",
    },
    GROUP: {
        "id": GROUP,
        "on": "node",
        "label": "group",
        "description": "nodes sharing a value, shown as one",
    },
    LOOP: {
        "id": LOOP,
        "on": "node",
        "label": "loop",
        "description": "nodes on a common cycle, shown as one",
    },
}


def _document(data: Mapping[str, Any]) -> dict[str, Any]:
    """A checked, independent copy of a document, with ``edges``."""
    problems = check_node_link(data)
    if problems:
        shown = "; ".join(problems[:3])
        more = f" (and {len(problems) - 3} more)" if len(problems) > 3 else ""
        raise ValueError(f"not a protee-node-link/0 document: {shown}{more}")
    doc = copy.deepcopy(dict(data))
    if "edges" not in doc:
        doc["edges"] = doc.pop("links")
    return doc


def _declare(doc: dict[str, Any], *marks: str) -> None:
    """Declare protee's marks in the vocabulary of a document."""
    block = doc["graph"]
    prefixes = dict(block.get("prefixes") or {})
    prefixes.setdefault("protee", None)
    block["prefixes"] = prefixes
    vocabulary = dict(block.get("vocabulary") or {})
    values = list(vocabulary.get(DISPLAY, []))
    present = {(v["id"], v["on"]) for v in values}
    values += [dict(_MARKS[m]) for m in marks if (m, "node") not in present]
    vocabulary[DISPLAY] = values
    block["vocabulary"] = vocabulary


def _with_metric(node: dict[str, Any], name: str, value: int) -> None:
    metrics = dict(node.get("metrics") or {})
    metrics[name] = value
    node["metrics"] = metrics


def select(
    data: Mapping[str, Any],
    nodes: Iterable[str | int],
    *,
    depth: int,
    direction: str = "both",
    types: Iterable[str] | None = None,
    families: Iterable[str] | None = None,
    threshold: tuple[str, float] | None = None,
) -> dict[str, Any]:
    """The part of a document reached from some nodes.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.
    nodes : iterable of str or int
        The identifiers of the starting nodes.
    depth : int
        The number of edges followed from them.
    direction : {"both", "out", "in"}
        Follow edges from source to target (``out``), from target to
        source (``in``), or both.
    types, families : iterable of str, optional
        Only nodes of these types, of these families, are selected and
        crossed (starting nodes included).
    threshold : (str, float), optional
        Only nodes whose metric is at least the value are selected.

    Returns
    -------
    dict
        A new document. It keeps the selected nodes and their direct
        neighbours outside the selection, marked :data:`OUTSIDE` under
        :data:`DISPLAY`; a kept node with neighbours not kept counts them in
        ``metrics[HIDDEN]``. It keeps the edges with a selected end.

    Raises
    ------
    ValueError
        If the document does not follow the format, a starting node is
        unknown, the depth is negative or the direction unknown.
    """
    doc = _document(data)
    if depth < 0:
        raise ValueError(f"depth must be at least 0, got {depth}")
    if direction not in ("both", "out", "in"):
        raise ValueError(f"direction must be 'both', 'out' or 'in', got {direction!r}")
    by_id = {n["id"]: n for n in doc["nodes"]}
    starts = list(nodes)
    if unknown := [s for s in starts if s not in by_id]:
        raise ValueError(f"unknown starting nodes {unknown!r}")
    out: dict[Any, list[Any]] = {i: [] for i in by_id}
    into: dict[Any, list[Any]] = {i: [] for i in by_id}
    for e in doc["edges"]:
        out[e["source"]].append(e["target"])
        into[e["target"]].append(e["source"])
    kinds = None if types is None else set(types)
    groups = None if families is None else set(families)

    def eligible(ident: Any) -> bool:
        node = by_id[ident]
        if kinds is not None and node.get("type") not in kinds:
            return False
        if groups is not None and node.get("family") not in groups:
            return False
        if threshold is None:
            return True
        value = (node.get("metrics") or {}).get(threshold[0])
        return isinstance(value, (int, float)) and value >= threshold[1]

    def steps(ident: Any) -> list[Any]:
        return (
            {"out": out, "in": into}[direction][ident]
            if direction != "both"
            else (out[ident] + into[ident])
        )

    selected: set[Any] = set()
    frontier = deque((s, 0) for s in starts if eligible(s))
    while frontier:
        ident, d = frontier.popleft()
        if ident in selected:
            continue
        selected.add(ident)
        if d < depth:
            frontier.extend((n, d + 1) for n in steps(ident) if eligible(n))
    neighbours = {i: set(out[i]) | set(into[i]) for i in by_id}
    outside = {n for s in selected for n in neighbours[s]} - selected
    kept = selected | outside
    doc["nodes"] = [n for n in doc["nodes"] if n["id"] in kept]
    for node in doc["nodes"]:
        if node["id"] in outside:
            node[DISPLAY] = OUTSIDE
        if hidden := len(neighbours[node["id"]] - kept):
            _with_metric(node, HIDDEN, hidden)
    doc["edges"] = [
        e
        for e in doc["edges"]
        if e["source"] in kept
        and e["target"] in kept
        and (e["source"] in selected or e["target"] in selected)
    ]
    _declare(doc, OUTSIDE)
    return doc


def collapse(data: Mapping[str, Any], *, by: str = "family") -> dict[str, Any]:
    """One node for each group of nodes that share a value of ``by``.

    A group of two nodes or more becomes one node, at the place of its
    first member: its identifier is ``"<by>=<value>"`` (made unique), its
    label the value, marked :data:`GROUP` under :data:`DISPLAY`, with the
    identifiers of its members under :data:`CONTAINS` and their number in
    ``metrics[MEMBERS]``. It keeps ``by``, and the ``type`` its members
    share, if any. The edges inside a group disappear; the edges of a
    group to the same node, with the same type, merge into one edge that
    counts them in ``metrics[MERGED]`` and keeps the attributes they share.
    A node alone in its group, or without ``by``, stays as it is.

    Raises
    ------
    ValueError
        If the document does not follow the format.
    """
    doc = _document(data)
    members: dict[Any, list[Any]] = {}
    for node in doc["nodes"]:
        if node.get(by) is not None:
            members.setdefault(node[by], []).append(node["id"])
    groups = [
        (f"{by}={value}", str(value), ids, {by: value})
        for value, ids in members.items()
        if len(ids) > 1
    ]
    return _merge(doc, groups, GROUP)


def condense(data: Mapping[str, Any]) -> dict[str, Any]:
    """One node for each loop: the nodes of a common cycle, shown as one.

    Each strongly connected component of two nodes or more becomes one
    node, at the place of its first member, as in :func:`collapse`: its
    identifier is ``"loop:<first member>"``, its label ``⟳ <size>``, marked
    :data:`LOOP` under :data:`DISPLAY`, with its members under
    :data:`CONTAINS` and their number in ``metrics[MEMBERS]``. The rest of
    the graph no longer has any cycle, but for loops on one node.

    The components are those of :func:`protee.structure.strong_components`.

    Raises
    ------
    ValueError
        If the document does not follow the format.
    """
    doc = _document(data)
    component = strong_components(from_node_link(doc).graph)
    members: dict[int, list[Any]] = {}
    for node, c in zip(doc["nodes"], component, strict=True):
        members.setdefault(c, []).append(node["id"])
    # In the order of their first member, as the nodes are read.
    groups: list[tuple[str, str, list[Any], dict[str, Any]]] = [
        (f"loop:{ids[0]}", f"⟳ {len(ids)}", ids, {})
        for ids in members.values()
        if len(ids) > 1
    ]
    return _merge(doc, groups, LOOP)


def reduce(data: Mapping[str, Any], *, edge_type: str) -> dict[str, Any]:
    """The transitive reduction of one relation: fewer edges, same meaning.

    An edge of type ``edge_type`` from ``u`` to ``v`` is left out when ``v``
    is reached from ``u`` by a longer path of edges of that type: in a
    hierarchy, a link to a grandparent that a parent already gives. A
    second edge of that type between the same two nodes is left out too.
    Edges of other types stay.

    Raises
    ------
    ValueError
        If the document does not follow the format, or the edges of that
        type form a cycle.
    """
    doc = _document(data)
    relation = [e for e in doc["edges"] if e.get("type") == edge_type]
    successors: dict[Any, list[Any]] = {}
    for e in relation:
        successors.setdefault(e["source"], []).append(e["target"])
    if any(
        len(ids) > 1 or ids[0] in successors.get(ids[0], [])
        for ids in _components(doc, successors)
    ):
        raise ValueError(f"the edges of type {edge_type!r} form a cycle")

    def further(u: Any, v: Any) -> bool:
        """Whether v is reached from u by a path of two edges or more."""
        seen: set[Any] = set()
        stack = [w for w in successors.get(u, []) if w != v]
        while stack:
            w = stack.pop()
            if w == v:
                return True
            if w not in seen:
                seen.add(w)
                stack.extend(successors.get(w, []))
        return False

    kept, pairs = [], set()
    for e in doc["edges"]:
        if e.get("type") == edge_type:
            pair = (e["source"], e["target"])
            if pair in pairs or further(*pair):
                continue
            pairs.add(pair)
        kept.append(e)
    doc["edges"] = kept
    return doc


def _components(
    doc: dict[str, Any], successors: Mapping[Any, list[Any]]
) -> list[list[Any]]:
    """The strongly connected components of a relation on the nodes."""
    ids = [n["id"] for n in doc["nodes"]]
    index = {i: k for k, i in enumerate(ids)}
    arcs = [(index[u], index[v]) for u, vs in successors.items() for v in vs]
    component = strong_components(Digraph.from_arcs(len(ids), arcs))
    members: dict[int, list[Any]] = {}
    for i, c in zip(ids, component, strict=True):
        members.setdefault(c, []).append(i)
    return list(members.values())


def _merge(
    doc: dict[str, Any],
    groups: list[tuple[str, str, list[Any], dict[str, Any]]],
    mark: str,
) -> dict[str, Any]:
    """Each group of nodes becomes one node; its edges are merged.

    ``groups`` holds, for each group, a proposed identifier, a label, the
    identifiers of its members and attributes to keep.
    """
    if not groups:
        return doc
    taken = {n["id"] for n in doc["nodes"]}
    target: dict[Any, str] = {}
    by_id = {n["id"]: n for n in doc["nodes"]}
    group_nodes: dict[Any, dict[str, Any]] = {}
    for proposed, label, ids, attributes in groups:
        gid, k = proposed, 1
        while gid in taken:
            k += 1
            gid = f"{proposed}#{k}"
        taken.add(gid)
        group: dict[str, Any] = {"id": gid, "label": label, **attributes}
        shared = {by_id[i].get("type") for i in ids}
        if len(shared) == 1 and None not in shared:
            group["type"] = shared.pop()
        group[DISPLAY] = mark
        group[CONTAINS] = list(ids)
        group["metrics"] = {MEMBERS: len(ids)}
        group_nodes[ids[0]] = group
        target.update(dict.fromkeys(ids, gid))
    doc["nodes"] = [
        group_nodes.get(n["id"], n)
        for n in doc["nodes"]
        if n["id"] not in target or n["id"] in group_nodes
    ]
    kept: list[dict[str, Any]] = []
    merged: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    for e in doc["edges"]:
        s, t = (
            target.get(e["source"], e["source"]),
            target.get(e["target"], e["target"]),
        )
        if e["source"] not in target and e["target"] not in target:
            kept.append(e)
        elif s != t:
            if (s, t, e.get("type")) not in merged:
                kept.append({"source": s, "target": t})
                merged[(s, t, e.get("type"))] = [kept[-1]]
            merged[(s, t, e.get("type"))].append(e)
    used: dict[tuple[Any, Any], set[int]] = {}
    for e in kept:
        if isinstance(e.get("key"), int):
            used.setdefault((e["source"], e["target"]), set()).add(e["key"])
    for (s, t, _), (edge, *originals) in merged.items():
        common = {
            k: v
            for k, v in originals[0].items()
            if k not in ("source", "target", "key", "metrics")
            and all(o.get(k) == v for o in originals)
        }
        edge.update(common)
        if len(originals) > 1:
            edge["metrics"] = {MERGED: len(originals)}
        keys = used.setdefault((s, t), set())
        edge["key"] = next(k for k in range(len(keys) + 1) if k not in keys)
        keys.add(edge["key"])
    doc["edges"] = kept
    pairs = [(e["source"], e["target"]) for e in kept]
    doc["multigraph"] = bool(doc["multigraph"]) or len(set(pairs)) < len(pairs)
    _declare(doc, mark)
    return doc


def _quote(text: object) -> str:
    escaped = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _attributes(values: Mapping[str, object]) -> str:
    return ", ".join(f"{k}={_quote(v)}" for k, v in values.items())


def _dark(colour: str) -> bool:
    r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.45


def _defaults(
    vocabulary: Mapping[str, Any], on: str
) -> dict[tuple[str, Any], dict[str, str]]:
    """Styles drawn from the declared values, in the order of declaration."""
    attributes = [
        a
        for a, values in vocabulary.items()
        if a != DISPLAY and any(v["on"] == on for v in values)
    ]
    styles: dict[tuple[str, Any], dict[str, str]] = {}
    for rank, attribute in enumerate(attributes[:2]):
        values = [v for v in vocabulary[attribute] if v["on"] == on]
        for i, v in enumerate(values):
            style: dict[str, str]
            if on == "node" and rank == 0:
                style = {"shape": _SHAPES[i % len(_SHAPES)]}
            elif on == "node":
                fill = OKABE_ITO[i % 7]  # black is no fill
                line = _NODE_LINES[i % len(_NODE_LINES)]
                style = {"style": f"filled,{line}", "fillcolor": fill}
                if _dark(fill):
                    style["fontcolor"] = "#FFFFFF"
            elif rank == 0:
                colour = _LINE_COLOURS[i % len(_LINE_COLOURS)]
                style = {"color": colour, "fontcolor": colour}
                style["arrowhead"] = _ARROWS[i % len(_ARROWS)]
            else:
                style = {"style": _EDGE_LINES[i % len(_EDGE_LINES)]}
            if v.get("symmetric"):
                # The same head at both ends: symmetric, and still told
                # apart by its shape.
                style["dir"] = "both"
                style["arrowtail"] = style.get("arrowhead", "normal")
            styles[(attribute, v["id"])] = style
    return styles


def _style(
    item: Mapping[str, Any],
    defaults: Mapping[tuple[str, Any], Mapping[str, str]],
    given: Mapping[tuple[str, Any], Mapping[str, str]],
) -> dict[str, str]:
    style: dict[str, str] = {}
    for table in (defaults, given):
        for (attribute, value), attributes in table.items():
            if item.get(attribute) == value:
                for k, v in attributes.items():
                    # A line style replaces the line of a filled node,
                    # which stays filled.
                    if (
                        k == "style"
                        and "filled" in style.get("style", "")
                        and "filled" not in v
                    ):
                        v = f"filled,{v}"
                    style[k] = v
    return style


type _Table = dict[tuple[str, Any], dict[str, str]]


def _style_tables(
    doc: Mapping[str, Any], styles: Styles | None
) -> tuple[_Table, _Table, dict[str, Mapping[tuple[str, Any], Mapping[str, str]]]]:
    """The default styles of nodes and edges, and the caller's, checked."""
    given: dict[str, Mapping[tuple[str, Any], Mapping[str, str]]] = {
        "node": {},
        "edge": {},
        **(styles or {}),
    }
    for kind in given.values():
        for attributes in kind.values():
            if bad := [k for k in attributes if not _NAME.fullmatch(k)]:
                raise ValueError(f"invalid Graphviz attribute names {bad!r}")
    names = [str(n["id"]) for n in doc["nodes"]]
    if len(set(names)) < len(names):
        raise ValueError("two node identifiers write the same in DOT")
    vocabulary = doc["graph"].get("vocabulary") or {}
    node_defaults = _defaults(vocabulary, "node")
    node_defaults[(DISPLAY, OUTSIDE)] = {"style": "dashed", "color": "#7F7F7F"}
    node_defaults[(DISPLAY, GROUP)] = {"peripheries": "2"}
    node_defaults[(DISPLAY, LOOP)] = {"peripheries": "3"}
    return node_defaults, _defaults(vocabulary, "edge"), given


def _texts(node: Mapping[str, Any]) -> tuple[str, str]:
    """The label of a node (with ``+n`` hidden neighbours) and its tooltip."""
    label = str(node.get("label") or node["id"])
    hidden = (node.get("metrics") or {}).get(HIDDEN)
    return (f"{label}\n+{hidden}" if hidden else label), (
        node.get("description") or label
    )


def to_dot(
    data: Mapping[str, Any],
    *,
    styles: Styles | None = None,
    order_by: str | None = None,
    direction: str = "TB",
    legend: bool = True,
) -> str:
    """The Graphviz DOT text of a document.

    A node shows its ``label`` (its ``id`` without one), followed by
    ``+n`` when ``n`` of its neighbours are not shown; its tooltip is its
    ``description``, its link its ``url``. The default styles come from the
    declared vocabulary, in the order of declaration:

    - nodes: the first declared attribute sets the shape, the second the
      fill colour (:data:`OKABE_ITO`) and the border line;
    - edges: the first declared attribute sets the colour (yellow aside)
      and the arrowhead, the second the line (dashed, dotted, bold); a
      symmetric value draws its head at both ends;
    - marks: :data:`OUTSIDE` is grey and dashed, :data:`GROUP` has a double
      border, :data:`LOOP` a triple one.

    Every distinction holds without the colours. The caller's styles
    complete and override the defaults.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.
    styles : mapping, optional
        ``{"node": {(attribute, value): {graphviz_attribute: text}},
        "edge": {...}}``. For instance ``{"edge": {("role", "x:closing"):
        {"style": "dashed", "constraint": "false"}}}`` draws an edge dashed
        and lets it not constrain the layout.
    order_by : str, optional
        A numeric node attribute: the nodes that carry it are drawn in
        increasing order along ``direction``, the others placed by Graphviz.
    direction : {"TB", "LR", "BT", "RL"}
    legend : bool
        A cluster, placed by Graphviz, that shows each declared value with
        its style and label. A node value that sets no shape is shown with
        the shape of the nodes that carry it when they share one, and as a
        rounded box otherwise.

    Returns
    -------
    str

    Raises
    ------
    ValueError
        If the document does not follow the format, the direction is
        unknown, a value of ``order_by`` is not finite, two node
        identifiers write the same, or a style names an invalid Graphviz
        attribute.
    TypeError
        If a value of ``order_by`` is not a number.
    """
    doc = _document(data)
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be one of {_DIRECTIONS}, got {direction!r}")
    node_defaults, edge_defaults, given = _style_tables(doc, styles)
    block = doc["graph"]
    head = {"rankdir": direction, "fontname": _FONT}
    if block.get("label"):
        head.update(label=block["label"], labelloc="t")
    if block.get("description"):
        head["tooltip"] = block["description"]
    lines = [
        f"digraph {_quote(block.get('label') or 'graph')} {{",
        f"  graph [{_attributes(head)}];",
        f"  node [{_attributes({'fontname': _FONT})}];",
        f"  edge [{_attributes({'fontname': _FONT})}];",
    ]
    for node in doc["nodes"]:
        label, tooltip = _texts(node)
        values: dict[str, object] = {"label": label, "tooltip": tooltip}
        if node.get("url"):
            values["URL"] = node["url"]
        values.update(_style(node, node_defaults, given["node"]))
        lines.append(f"  {_quote(node['id'])} [{_attributes(values)}];")
    for edge in doc["edges"]:
        values = {}
        if edge.get("label"):
            values["label"] = edge["label"]
        values.update(_style(edge, edge_defaults, given["edge"]))
        lines.append(
            f"  {_quote(edge['source'])} -> {_quote(edge['target'])}"
            + (f" [{_attributes(values)}]" if values else "")
            + ";"
        )
    if order_by is not None:
        lines += _ordering(doc["nodes"], order_by)
    if legend:
        lines += _legend(_legend_entries(doc, node_defaults, edge_defaults, given))
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_svg(
    data: Mapping[str, Any],
    *,
    styles: Styles | None = None,
    order_by: str | None = None,
    direction: str = "TB",
    legend: str | None = "right",
) -> str:
    """An SVG drawing of a document, laid out by Graphviz (``dot``).

    The text of :func:`to_dot`, with the same parameters, laid out and
    drawn by the Graphviz that pygraphviz bundles: nothing else is
    installed on the workstation, and nothing is fetched. Labels stay text,
    in system fonts. With the same document and the same versions, the SVG
    is the same, byte for byte.

    Parameters
    ----------
    data, styles, order_by, direction
        As :func:`to_dot`.
    legend : {"right", "below"} or None
        ``"right"``: the cluster of :func:`to_dot`, placed by Graphviz
        beside the graph. ``"below"``: the legend of
        :func:`render_legend_svg`, laid out apart and drawn under the
        graph, centred, so that it does not widen the figure. ``None``: no
        legend.

    Returns
    -------
    str
        The SVG document.

    Raises
    ------
    ImportError
        If pygraphviz is not installed (the optional extra ``viz``).
    ValueError, TypeError
        As :func:`to_dot`, or if ``legend`` is not one of its values.
    """
    if legend not in _LEGEND_PLACES:
        raise ValueError(f"legend must be one of {_LEGEND_PLACES}, got {legend!r}")
    graphviz = _pygraphviz("render_svg")
    dot = to_dot(
        data,
        styles=styles,
        order_by=order_by,
        direction=direction,
        legend=legend == "right",
    )
    drawing = _svg(graphviz, dot)
    if legend == "below":
        doc = _document(data)
        entries = _legend_entries(doc, *_style_tables(doc, styles))
        if entries:
            return _stack(drawing, _svg(graphviz, _legend_dot(entries)))
    return drawing


def render_legend_svg(data: Mapping[str, Any], *, styles: Styles | None = None) -> str:
    """The legend of a document alone, in SVG, laid out by Graphviz.

    Each declared value with the style it takes in :func:`render_svg` with
    the same ``styles``, one column per attribute in the order of
    declaration, so that a figure can carry its legend apart. A node value
    that sets no shape is shown with the shape of the nodes that carry it
    when they share one, and as a rounded box otherwise.

    Returns
    -------
    str
        The SVG document.

    Raises
    ------
    ImportError
        If pygraphviz is not installed (the optional extra ``viz``).
    ValueError
        If the document does not follow the format or declares no value,
        or a style names an invalid Graphviz attribute.
    """
    graphviz = _pygraphviz("render_legend_svg")
    doc = _document(data)
    entries = _legend_entries(doc, *_style_tables(doc, styles))
    if not entries:
        raise ValueError("the document declares no value: there is no legend")
    return _svg(graphviz, _legend_dot(entries))


def _svg(graphviz: Any, dot: str) -> str:
    drawing: bytes = graphviz.AGraph(string=dot).draw(format="svg", prog="dot")
    return drawing.decode("utf-8")


_SVG_ROOT = re.compile(r'<svg width="[^"]*" height="[^"]*"\s+viewBox="([^"]*)"([^>]*)>')


def _stack(top: str, bottom: str) -> str:
    """One SVG: the drawing ``top`` above ``bottom``, both centred.

    The identifiers of ``bottom`` are prefixed, so that none is repeated.
    """
    parts = []
    for svg in (top, bottom):
        root = _SVG_ROOT.search(svg)
        assert root is not None, "Graphviz writes the root of its SVG so"
        width, height = (float(x) for x in root.group(1).split()[2:])
        parts.append((root, width, height, svg[root.end() : svg.rindex("</svg>")]))
    gap = 12.0
    width = max(p[1] for p in parts)
    height = parts[0][2] + gap + parts[1][2]
    first = parts[0][0]
    lines = [
        top[: first.start()]
        + f'<svg width="{width:.0f}pt" height="{height:.0f}pt"\n'
        + f' viewBox="0.00 0.00 {width:.2f} {height:.2f}"{first.group(2)}>'
    ]
    y = 0.0
    for k, (root, w, h, inner) in enumerate(parts):
        if k:
            inner = inner.replace(' id="', ' id="protee-legend-')
        lines.append(
            f'<svg x="{(width - w) / 2:.2f}" y="{y:.2f}" width="{w:.2f}"'
            f' height="{h:.2f}" viewBox="{root.group(1)}">{inner}</svg>'
        )
        y += h + gap
    lines.append("</svg>\n")
    return "\n".join(lines)


def _pygraphviz(function: str) -> Any:
    """pygraphviz, imported on use: it comes with the optional extra."""
    try:
        import pygraphviz
    except ImportError as err:
        raise ImportError(
            f"{function} needs pygraphviz: install the optional extra protee[viz]"
        ) from err
    return pygraphviz


_GROUP_BY = ("family", "loop", None)
_CY_SHAPES = {
    "box": "rectangle",
    "diamond": "diamond",
    "hexagon": "hexagon",
    "octagon": "octagon",
    "house": "tag",
    "trapezium": "rhomboid",
}
_CY_ARROWS = {
    "normal": ("triangle", "filled"),
    "empty": ("triangle", "hollow"),
    "dot": ("circle", "filled"),
    "odot": ("circle", "hollow"),
    "diamond": ("diamond", "filled"),
    "odiamond": ("diamond", "hollow"),
    "box": ("square", "filled"),
    "obox": ("square", "hollow"),
}
_PAGE_STYLE = """
body { margin: 0; font-family: Helvetica, Arial, sans-serif; font-size: 14px; }
header { position: absolute; top: 0; left: 0; right: 0; height: 2.6em;
  display: flex; gap: .6em; align-items: center; padding: 0 .8em;
  border-bottom: 1px solid #ccc; }
#cy { position: absolute; top: 2.6em; left: 0; right: 20em; bottom: 0; }
aside { position: absolute; top: 2.6em; right: 0; width: 19em; bottom: 0;
  overflow: auto; padding: .5em; border-left: 1px solid #ccc; }
aside h2 { font-size: 1em; margin: .8em 0 .3em; }
aside ul { list-style: none; margin: 0; padding: 0; }
aside li { margin: .25em 0; }
.swatch { display: inline-block; width: 1.4em; height: .9em;
  margin-right: .4em; vertical-align: middle; border: 2px solid #000; }
.note { color: #555; font-size: .9em; }
#tip { position: absolute; display: none; max-width: 24em; padding: .3em .5em;
  background: #ffffe8; border: 1px solid #999; pointer-events: none; }
"""
_PAGE_SCRIPT = """
(function () {
  var elements = JSON.parse(document.getElementById("protee-elements").textContent);
  var cy = cytoscape({
    container: document.getElementById("cy"),
    elements: elements,
    layout: { name: "preset" },
    wheelSensitivity: 0.2,
    style: [
      { selector: "node", style: {
        "label": "data(label)", "text-wrap": "wrap", "text-valign": "center",
        "text-halign": "center", "font-family": "Helvetica, Arial, sans-serif",
        "font-size": 10, "width": "data(w)", "height": "data(h)",
        "background-color": "#FFFFFF", "border-width": 1, "border-color": "#000000" } },
      { selector: ":parent", style: {
        "text-valign": "top", "background-opacity": 0.04, "border-style": "dashed",
        "border-color": "#7F7F7F" } },
      { selector: "edge", style: {
        "curve-style": "bezier", "width": 1, "line-color": "#000000",
        "target-arrow-shape": "triangle", "target-arrow-color": "#000000",
        "label": "data(label)", "font-size": 9 } },
      { selector: "node.cy-expand-collapse-collapsed-node", style: {
        "shape": "round-rectangle", "border-style": "double", "border-width": 4 } }
    ]
  });
  var api = cy.expandCollapse({ layoutBy: null, fisheye: false, animate: false,
    undoable: false, cueEnabled: true });
  document.getElementById("collapse").onclick = function () { api.collapseAll(); };
  document.getElementById("expand").onclick = function () { api.expandAll(); };
  document.getElementById("fit").onclick = function () { cy.fit(); };
  var tip = document.getElementById("tip");
  cy.on("mouseover", "node", function (event) {
    var text = event.target.data("tooltip");
    if (!text) { return; }
    tip.textContent = text;
    tip.style.left = (event.renderedPosition.x + 14) + "px";
    tip.style.top = (event.renderedPosition.y + 44) + "px";
    tip.style.display = "block";
  });
  cy.on("mouseout", "node", function () { tip.style.display = "none"; });
  cy.on("dbltap", "node", function (event) {
    var url = event.target.data("url");
    if (url) { window.open(url, "_blank", "noopener"); }
  });
})();
"""


def _asset(name: str) -> str:
    return files("protee").joinpath("_assets", name).read_text(encoding="utf-8")


def _groups(doc: dict[str, Any], group_by: str | None) -> list[tuple[str, list[Any]]]:
    """(label, members) of the groups shown as compound nodes."""
    members: dict[Any, list[Any]] = {}
    if group_by == "family":
        for node in doc["nodes"]:
            if node.get("family") is not None:
                members.setdefault(node["family"], []).append(node["id"])
        return [(str(v), ids) for v, ids in members.items() if len(ids) > 1]
    if group_by == "loop":
        component = strong_components(from_node_link(doc).graph)
        for node, c in zip(doc["nodes"], component, strict=True):
            members.setdefault(c, []).append(node["id"])
        return [(f"⟳ {len(ids)}", ids) for ids in members.values() if len(ids) > 1]
    return []


def _cy_node(style: Mapping[str, str]) -> dict[str, object]:
    """A cytoscape.js style from the Graphviz attributes of a node."""
    out: dict[str, object] = {
        "shape": _CY_SHAPES.get(style.get("shape", ""), "ellipse")
    }
    lines = style.get("style", "").split(",")
    if "filled" in lines:
        out["background-color"] = style.get("fillcolor", "#D3D3D3")
    if "color" in style:
        out["border-color"] = style["color"]
    if "dashed" in lines or "dotted" in lines:
        out["border-style"] = "dashed" if "dashed" in lines else "dotted"
    if "bold" in lines:
        out["border-width"] = 3
    if style.get("peripheries") in ("2", "3"):
        out["border-style"] = "double"
        out["border-width"] = 2 * int(style["peripheries"])
    if "fontcolor" in style:
        out["color"] = style["fontcolor"]
    return out


def _cy_edge(style: Mapping[str, str]) -> dict[str, object]:
    """A cytoscape.js style from the Graphviz attributes of an edge."""
    out: dict[str, object] = {}
    if "color" in style:
        out["line-color"] = out["target-arrow-color"] = style["color"]
    if "fontcolor" in style:
        out["color"] = style["fontcolor"]
    lines = style.get("style", "").split(",")
    if "dashed" in lines or "dotted" in lines:
        out["line-style"] = "dashed" if "dashed" in lines else "dotted"
    if "bold" in lines:
        out["width"] = 3
    shape, fill = _CY_ARROWS.get(style.get("arrowhead", "normal"), _CY_ARROWS["normal"])
    out["target-arrow-shape"] = "none" if style.get("dir") == "none" else shape
    out["target-arrow-fill"] = fill
    if style.get("dir") == "both":
        tail, tail_fill = _CY_ARROWS.get(
            style.get("arrowtail", "normal"), _CY_ARROWS["normal"]
        )
        out["source-arrow-shape"] = tail
        out["source-arrow-fill"] = tail_fill
        if "color" in style:
            out["source-arrow-color"] = style["color"]
    return out


def render_html(
    data: Mapping[str, Any],
    *,
    styles: Styles | None = None,
    order_by: str | None = None,
    direction: str = "TB",
    group_by: str | None = "family",
    title: str | None = None,
) -> str:
    """A page to explore a document, which opens offline by a double click.

    The nodes keep the positions of the Graphviz layout of
    :func:`render_svg`, with each group drawn together, and the styles of
    :func:`to_dot`. The page embeds cytoscape.js and its expand-collapse
    extension, with their MIT notices: the reader collapses or expands a
    group with the cue at its corner, or all of them with the buttons; a
    tooltip shows the description of a node, and a double click opens its
    ``url``. A legend lists the declared values. Nothing is fetched.

    Parameters
    ----------
    data, styles, order_by, direction
        As :func:`to_dot`.
    group_by : {"family", "loop", None}
        The groups shown as compound nodes: the nodes sharing a ``family``,
        the loops (strongly connected components), or none.
    title : str, optional
        The title of the page; the label of the graph without one.

    Returns
    -------
    str
        The HTML page.

    Raises
    ------
    ImportError
        If pygraphviz is not installed (the optional extra ``viz``).
    ValueError, TypeError
        As :func:`to_dot`, or if ``group_by`` is unknown.
    """
    if group_by not in _GROUP_BY:
        raise ValueError(f"group_by must be one of {_GROUP_BY}, got {group_by!r}")
    graphviz = _pygraphviz("render_html")
    doc = _document(data)
    dot = to_dot(
        doc, styles=styles, order_by=order_by, direction=direction, legend=False
    )
    groups = _groups(doc, group_by)
    clusters = [
        f"  subgraph {_quote(f'cluster_{k}')} {{ "
        + " ".join(_quote(i) for i in ids)
        + " }"
        for k, (_, ids) in enumerate(groups)
    ]
    end = dot.rstrip().rfind("}")
    layout = graphviz.AGraph(string=dot[:end] + "\n".join(clusters) + "\n}\n")
    layout.layout(prog="dot")
    node_defaults, edge_defaults, given = _style_tables(doc, styles)
    taken = {str(n["id"]) for n in doc["nodes"]}
    parent: dict[Any, str] = {}
    elements: list[dict[str, Any]] = []
    for k, (label, ids) in enumerate(groups):
        gid, n = f"protee:group:{k}", 1
        while gid in taken:
            n += 1
            gid = f"protee:group:{k}#{n}"
        taken.add(gid)
        parent.update(dict.fromkeys(ids, gid))
        elements.append({"data": {"id": gid, "label": label}})
    for node in doc["nodes"]:
        drawn = layout.get_node(str(node["id"]))
        x, y = (float(v) for v in drawn.attr["pos"].split(","))
        label, tooltip = _texts(node)
        values: dict[str, Any] = {
            "id": str(node["id"]),
            "label": label,
            "tooltip": tooltip,
            "w": round(float(drawn.attr["width"]) * 72, 2),
            "h": round(float(drawn.attr["height"]) * 72, 2),
        }
        if node.get("url"):
            values["url"] = node["url"]
        if node["id"] in parent:
            values["parent"] = parent[node["id"]]
        style = _style(node, node_defaults, given["node"])
        elements.append(
            {"data": values, "position": {"x": x, "y": -y}, "style": _cy_node(style)}
        )
    for k, edge in enumerate(doc["edges"]):
        values = {
            "id": f"protee:edge:{k}",
            "source": str(edge["source"]),
            "target": str(edge["target"]),
        }
        if edge.get("label"):
            values["label"] = edge["label"]
        style = _style(edge, edge_defaults, given["edge"])
        elements.append({"data": values, "style": _cy_edge(style)})
    block = doc["graph"]
    heading = title or block.get("label") or "graph"
    payload = json.dumps(elements, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    legend = _legend_html(
        block.get("vocabulary") or {}, node_defaults, edge_defaults, given
    )
    notices = "\n".join(
        _asset(n)
        for n in ("cytoscape.LICENSE.txt", "cytoscape-expand-collapse.LICENSE.md")
    ).replace("--", "- -")
    return "\n".join(
        [
            "<!doctype html>",
            f'<html lang="{html.escape(str(block.get("language") or "en"))}">',
            "<head>",
            '<meta charset="utf-8">',
            f"<title>{html.escape(str(heading))}</title>",
            f"<style>{_PAGE_STYLE}</style>",
            "</head>",
            "<body>",
            "<header>",
            f"<strong>{html.escape(str(heading))}</strong>",
            '<button id="collapse">Collapse all</button>',
            '<button id="expand">Expand all</button>',
            '<button id="fit">Fit</button>',
            "</header>",
            '<div id="cy"></div>',
            f"<aside>{legend}</aside>",
            '<div id="tip"></div>',
            f"<!-- Third-party code embedded below, under the MIT licence:\n{notices}\n-->",
            f"<script>{_asset('cytoscape.min.js')}</script>",
            f"<script>{_asset('cytoscape-expand-collapse.js')}</script>",
            f'<script type="application/json" id="protee-elements">{payload}</script>',
            f"<script>{_PAGE_SCRIPT}</script>",
            "</body>",
            "</html>",
            "",
        ]
    )


def _legend_html(
    vocabulary: Mapping[str, Any],
    node_defaults: Mapping[tuple[str, Any], Mapping[str, str]],
    edge_defaults: Mapping[tuple[str, Any], Mapping[str, str]],
    given: Mapping[str, Mapping[tuple[str, Any], Mapping[str, str]]],
) -> str:
    """The declared values, each with a swatch of its colour and line."""
    parts = []
    for attribute, values in vocabulary.items():
        items = []
        for v in values:
            on = v["on"]
            defaults = node_defaults if on == "node" else edge_defaults
            style = _style({attribute: v["id"]}, defaults, given[on])
            fill = style.get("fillcolor", "#FFFFFF") if on == "node" else "#FFFFFF"
            line = "dashed" if "dashed" in style.get("style", "") else "solid"
            swatch = (
                f'<span class="swatch" style="background:{html.escape(fill)};'
                f"border-color:{html.escape(style.get('color', '#000000'))};"
                f'border-style:{line}"></span>'
            )
            note = (
                f' <span class="note">{html.escape(v["description"])}</span>'
                if v.get("description")
                else ""
            )
            items.append(f"<li>{swatch}{html.escape(v['label'])}{note}</li>")
        parts.append(f"<h2>{html.escape(attribute)}</h2><ul>{''.join(items)}</ul>")
    return "".join(parts)


def _ordering(nodes: list[dict[str, Any]], attribute: str) -> list[str]:
    """Same rank for equal values; invisible heavy edges between ranks."""
    ranks: dict[float, list[Any]] = {}
    for node in nodes:
        value = node.get(attribute)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"order_by {attribute!r}: {value!r} is not a number")
        if not math.isfinite(value):
            raise ValueError(f"order_by {attribute!r}: {value!r} is not finite")
        ranks.setdefault(value, []).append(node["id"])
    order = [ranks[v] for v in sorted(ranks)]
    lines = [
        "  { rank=same; " + " ".join(_quote(i) for i in ids) + " }" for ids in order
    ]
    lines += [
        f'  {_quote(a[0])} -> {_quote(b[0])} [style="invis", weight="100"];'
        for a, b in itertools.pairwise(order)
    ]
    return lines


type _Entry = tuple[str, str, dict[str, str]]


def _legend_entries(
    doc: Mapping[str, Any],
    node_defaults: Mapping[tuple[str, Any], Mapping[str, str]],
    edge_defaults: Mapping[tuple[str, Any], Mapping[str, str]],
    given: Mapping[str, Mapping[tuple[str, Any], Mapping[str, str]]],
) -> list[_Entry]:
    """Each declared value: its attribute, ``on``, and its swatch.

    A node value that sets no shape takes the shape of the nodes that carry
    it when they share one, and a rounded box otherwise: a swatch never
    shows a shape that its nodes do not have.
    """
    vocabulary = doc["graph"].get("vocabulary") or {}
    shapes = [
        (node, _style(node, node_defaults, given["node"]).get("shape", "ellipse"))
        for node in doc["nodes"]
    ]
    entries: list[_Entry] = []
    for attribute, values in vocabulary.items():
        for v in values:
            item = {attribute: v["id"]}
            swatch = {"label": str(v["label"])}
            if v["on"] == "node":
                swatch.update(_style(item, node_defaults, given["node"]))
                if "shape" not in swatch:
                    found = {s for n, s in shapes if n.get(attribute) == v["id"]}
                    if len(found) == 1:
                        swatch["shape"] = found.pop()
                    else:
                        swatch["shape"] = "box"
                        line = swatch.get("style")
                        swatch["style"] = f"rounded,{line}" if line else "rounded"
            else:
                swatch.update(_style(item, edge_defaults, given["edge"]))
            entries.append((attribute, v["on"], swatch))
    return entries


_POINT = 'shape="point", width="0.05", label=""'
_LAYOUT_ONLY = ("constraint", "weight", "minlen")


def _swatch(k: int, on: str, swatch: Mapping[str, str]) -> tuple[list[str], str, str]:
    """The DOT lines of one swatch, and its first and last node."""
    name = f"protee:legend:{k}"
    if on == "node":
        return [f"    {_quote(name)} [{_attributes(swatch)}];"], name, name
    a, b = f"{name}:a", f"{name}:b"
    # Graphviz draws the label of an edge against its line: spaces and an
    # empty line keep them apart.
    spaced = {**swatch, "label": f" {swatch['label']} \n"}
    return (
        [
            f"    {_quote(a)} [{_POINT}]; {_quote(b)} [{_POINT}];",
            f"    {_quote(a)} -> {_quote(b)} [{_attributes(spaced)}];",
        ],
        a,
        b,
    )


def _legend(entries: list[_Entry]) -> list[str]:
    """The legend as a cluster of the drawing, placed by Graphviz."""
    if not entries:
        return []
    lines = ["  subgraph cluster_legend {", '    label=""; style="dashed";']
    for k, (_, on, swatch) in enumerate(entries):
        lines += _swatch(k, on, swatch)[0]
    lines.append("  }")
    return lines


def _legend_dot(entries: list[_Entry]) -> str:
    """The legend alone: one column per attribute, in the order of declaration."""
    head = {"rankdir": "LR", "fontname": _FONT, "nodesep": "0.1", "ranksep": "0.3"}
    lines = [
        "digraph legend {",
        f"  graph [{_attributes(head)}];",
        f"  node [{_attributes({'fontname': _FONT})}];",
        f"  edge [{_attributes({'fontname': _FONT})}];",
        "  subgraph cluster_legend {",
        '    label=""; style="dashed";',
    ]
    columns: dict[tuple[str, str], list[tuple[int, dict[str, str]]]] = {}
    for k, (attribute, on, swatch) in enumerate(entries):
        columns.setdefault((attribute, on), []).append((k, swatch))
    previous: str | None = None
    for (_, on), column in columns.items():
        firsts: list[str] = []
        lasts: list[str] = []
        # Invisible edges within a rank fix the order of its nodes, which
        # rankdir=LR draws from the bottom up: the chains start from the
        # last declared value, so that the first one is drawn at the top.
        for k, swatch in reversed(column):
            if on == "edge":
                # The layout attributes of the caller are left out, and a
                # heavy edge is drawn straight.
                swatch = {
                    **{a: v for a, v in swatch.items() if a not in _LAYOUT_ONLY},
                    "weight": "10",
                }
            drawn, first, last = _swatch(k, on, swatch)
            lines += drawn
            firsts.append(first)
            lasts.append(last)
        for rank in (firsts, lasts) if on == "edge" else (firsts,):
            lines.append(f"    {{ rank=same; {' '.join(map(_quote, rank))} }}")
            if len(rank) > 1:
                lines.append(f'    {" -> ".join(map(_quote, rank))} [style="invis"];')
        if previous is not None:
            lines.append(
                f'    {_quote(previous)} -> {_quote(firsts[-1])} [style="invis"];'
            )
        previous = lasts[-1]
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"
