# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Drawing of node-link documents (``protee-node-link/0``).

The functions take and return node-link documents, the decoded JSON that
:func:`protee.io.check_node_link` checks, never protee objects: a producer
of documents does not need protee's model. Nothing here depends on a
producer: the legend comes from the vocabulary declared in the document,
the styles from a table given by the caller.

- :func:`select` and :func:`collapse` turn a document into a document that
  follows the format; the marks they add are declared under the
  ``protee`` prefix (:data:`DISPLAY`);
- :func:`to_dot` writes the Graphviz DOT text of a document, without any
  dependency;
- :func:`render_svg` lays it out and draws it in SVG through Graphviz,
  with the optional extra ``viz`` (pygraphviz, which bundles Graphviz).

Provisional API (until version 1.0).
"""

from __future__ import annotations

import copy
import itertools
import math
import re
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any

from protee.io import check_node_link

__all__ = [
    "CONTAINS",
    "DISPLAY",
    "GROUP",
    "HIDDEN",
    "MEMBERS",
    "MERGED",
    "OKABE_ITO",
    "OUTSIDE",
    "Styles",
    "collapse",
    "render_svg",
    "select",
    "to_dot",
]

#: Attribute of the marks protee adds, and its values.
DISPLAY = "protee:display"
OUTSIDE = "protee:outside"
GROUP = "protee:group"
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
_FONT = "Helvetica,Arial,sans-serif"
_DIRECTIONS = ("TB", "LR", "BT", "RL")
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
    groups = {v: ids for v, ids in members.items() if len(ids) > 1}
    if not groups:
        return doc
    taken = {n["id"] for n in doc["nodes"]}
    target: dict[Any, str] = {}
    by_id = {n["id"]: n for n in doc["nodes"]}
    group_nodes: dict[Any, dict[str, Any]] = {}
    for value, ids in groups.items():
        gid, k = f"{by}={value}", 1
        while gid in taken:
            k += 1
            gid = f"{by}={value}#{k}"
        taken.add(gid)
        group: dict[str, Any] = {"id": gid, "label": str(value), by: value}
        shared = {by_id[i].get("type") for i in ids}
        if len(shared) == 1 and None not in shared:
            group["type"] = shared.pop()
        group[DISPLAY] = GROUP
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
    _declare(doc, GROUP)
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
                colour = OKABE_ITO[i % len(OKABE_ITO)]
                style = {"color": colour, "fontcolor": colour}
                style["arrowhead"] = _ARROWS[i % len(_ARROWS)]
            else:
                style = {"style": _EDGE_LINES[i % len(_EDGE_LINES)]}
            if v.get("symmetric"):
                style["dir"] = "none"
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
    - edges: the first declared attribute sets the colour and the
      arrowhead, the second the line (dashed, dotted, bold); a symmetric
      value draws no arrow;
    - marks: :data:`OUTSIDE` is grey and dashed, :data:`GROUP` has a double
      border.

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
        A cluster that shows each declared value with its style and label.

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
    given = {"node": {}, "edge": {}, **(styles or {})}
    for kind in given.values():
        for attributes in kind.values():
            if bad := [k for k in attributes if not _NAME.fullmatch(k)]:
                raise ValueError(f"invalid Graphviz attribute names {bad!r}")
    names = [str(n["id"]) for n in doc["nodes"]]
    if len(set(names)) < len(names):
        raise ValueError("two node identifiers write the same in DOT")
    block = doc["graph"]
    vocabulary = block.get("vocabulary") or {}
    node_defaults = _defaults(vocabulary, "node")
    node_defaults[(DISPLAY, OUTSIDE)] = {"style": "dashed", "color": "#7F7F7F"}
    node_defaults[(DISPLAY, GROUP)] = {"peripheries": "2"}
    edge_defaults = _defaults(vocabulary, "edge")
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
        label = str(node.get("label") or node["id"])
        hidden = (node.get("metrics") or {}).get(HIDDEN)
        values: dict[str, object] = {
            "label": f"{label}\n+{hidden}" if hidden else label
        }
        values["tooltip"] = node.get("description") or label
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
        lines += _legend(vocabulary, node_defaults, edge_defaults, given)
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_svg(
    data: Mapping[str, Any],
    *,
    styles: Styles | None = None,
    order_by: str | None = None,
    direction: str = "TB",
    legend: bool = True,
) -> str:
    """An SVG drawing of a document, laid out by Graphviz (``dot``).

    The text of :func:`to_dot`, with the same parameters, laid out and
    drawn by the Graphviz that pygraphviz bundles: nothing else is
    installed on the workstation, and nothing is fetched. Labels stay text,
    in system fonts. With the same document and the same versions, the SVG
    is the same, byte for byte.

    Returns
    -------
    str
        The SVG document.

    Raises
    ------
    ImportError
        If pygraphviz is not installed (the optional extra ``viz``).
    ValueError, TypeError
        As :func:`to_dot`.
    """
    try:  # an optional extra, imported on use
        import pygraphviz
    except ImportError as err:
        raise ImportError(
            "render_svg needs pygraphviz: install the optional extra protee[viz]"
        ) from err
    dot = to_dot(
        data, styles=styles, order_by=order_by, direction=direction, legend=legend
    )
    drawing: bytes = pygraphviz.AGraph(string=dot).draw(format="svg", prog="dot")
    return drawing.decode("utf-8")


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


def _legend(
    vocabulary: Mapping[str, Any],
    node_defaults: Mapping[tuple[str, Any], Mapping[str, str]],
    edge_defaults: Mapping[tuple[str, Any], Mapping[str, str]],
    given: Mapping[str, Mapping[tuple[str, Any], Mapping[str, str]]],
) -> list[str]:
    entries = [
        (attribute, v) for attribute, values in vocabulary.items() for v in values
    ]
    if not entries:
        return []
    lines = ["  subgraph cluster_legend {", '    label=""; style="dashed";']
    for k, (attribute, v) in enumerate(entries):
        item = {attribute: v["id"]}
        if v["on"] == "node":
            values: dict[str, object] = {"label": v["label"]}
            values.update(_style(item, node_defaults, given["node"]))
            lines.append(f"    {_quote(f'protee:legend:{k}')} [{_attributes(values)}];")
        else:
            a, b = _quote(f"protee:legend:{k}:a"), _quote(f"protee:legend:{k}:b")
            point = _attributes({"shape": "point", "width": "0.05", "label": ""})
            lines.append(f"    {a} [{point}]; {b} [{point}];")
            values = {"label": v["label"]}
            values.update(_style(item, edge_defaults, given["edge"]))
            lines.append(f"    {a} -> {b} [{_attributes(values)}];")
    lines.append("  }")
    return lines
