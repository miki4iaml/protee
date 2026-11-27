# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Drawing of node-link documents (``protee-node-link/0``).

The functions take and return node-link documents, the decoded JSON that
:func:`protee.io.check_node_link` checks, never protee objects: a producer
of documents does not need protee's model. Nothing here depends on a
producer: the legend comes from the vocabulary declared in the document,
the styles from a table given by the caller.

- :func:`select`, :func:`collapse`, :func:`condense`, :func:`reduce` and
  :func:`contract` turn a document into a document that follows the
  format; the marks they add are declared under the ``protee`` prefix
  (:data:`DISPLAY`, :data:`SELECTION`);
- :func:`to_dot` writes the Graphviz DOT text of a document, without any
  dependency;
- :func:`render_svg` lays it out and draws it in SVG through Graphviz,
  with the optional extra ``viz`` (pygraphviz, which bundles Graphviz),
  its legend beside or below and an image as a footer;
  :func:`render_legend_svg` draws its legend alone;
- :func:`render_matrix_svg` draws its matrix (N² chart), without any
  dependency;
- :func:`render_html` writes a page to explore it, which opens offline,
  with the same layout and styles.

A :class:`Theme` (:data:`LIGHT`, :data:`DARK`) sets the background and the
ink of the drawings.

Provisional API (until version 1.0).
"""

from __future__ import annotations

import base64
import copy
import html
import itertools
import json
import math
import re
import struct
import subprocess
import sys
import xml.parsers.expat
from collections import Counter, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from protee.graph import Digraph
from protee.io import check_node_link
from protee.structure import strong_components

__all__ = [
    "CONTAINS",
    "DARK",
    "DISPLAY",
    "GROUP",
    "HIDDEN",
    "LIGHT",
    "LOOP",
    "MEMBERS",
    "MERGED",
    "OKABE_ITO",
    "OUTSIDE",
    "SELECTION",
    "VOCABULARY",
    "Attributes",
    "Styles",
    "Theme",
    "collapse",
    "condense",
    "contract",
    "mark_vocabularies",
    "reduce",
    "render_html",
    "render_legend_svg",
    "render_matrix_svg",
    "render_svg",
    "select",
    "to_dot",
]

#: Attributes of the marks protee adds, and their values: a node shown for
#: a group or a loop (DISPLAY), and a neighbour outside a selection
#: (SELECTION); a group outside a selection carries both.
DISPLAY = "protee:display"
GROUP = "protee:group"
LOOP = "protee:loop"
SELECTION = "protee:selection"
OUTSIDE = "protee:outside"
#: Metrics protee adds: the neighbours not shown, the nodes of the original
#: document that a node stands for (the members of a group, the ends of
#: contracted edges), the edges merged into one.
HIDDEN = "protee:hidden"
MEMBERS = "protee:members"
MERGED = "protee:merged"
#: Key listing the identifiers of the nodes of the original document that a
#: node stands for: the members of a group, the ends of contracted edges.
CONTAINS = "protee:contains"
#: Attribute naming the vocabulary of the IRI of a node
#: (:func:`mark_vocabularies`).
VOCABULARY = "protee:vocabulary"

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
#: Graphviz attributes of the graph, and of all its nodes and all its edges:
#: ``{"graph": {...}, "node": {...}, "edge": {...}}``.
type Attributes = Mapping[str, Mapping[str, str]]

_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


@dataclass(frozen=True, slots=True)
class Theme:
    """The colours of a drawing: its background, its ink and a muted grey.

    The ink draws the lines and texts that no style colours; the muted grey
    draws the nodes outside a selection and the frame of the legend. Each
    colour is written ``#RRGGBB``.
    """

    background: str
    ink: str
    muted: str

    def __post_init__(self) -> None:
        for name in ("background", "ink", "muted"):
            value = getattr(self, name)
            if not (isinstance(value, str) and _HEX.fullmatch(value)):
                raise ValueError(f"Theme.{name} must be written #RRGGBB, got {value!r}")


#: Black ink on white.
LIGHT = Theme(background="#FFFFFF", ink="#000000", muted="#767676")
#: Light ink on a dark background.
DARK = Theme(background="#0D1117", ink="#E6EDF3", muted="#8B949E")

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
_LEGEND_PLACES = ("right", "below", "below-left", None)
_LEGEND_VALUES = ("declared", "present")
#: The graph attributes that ``attributes`` may set: layout only.
_GRAPH_ATTRIBUTES = ("splines", "ranksep", "nodesep", "pad")
_KINDS = ("graph", "node", "edge")
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
_MARK_ATTRIBUTE = {OUTSIDE: SELECTION, GROUP: DISPLAY, LOOP: DISPLAY}
#: The class of the nodes outside a selection, whose labels are in italics.
_OUTSIDE_CLASS = "protee_outside"
_OUTSIDE_STYLE = f"<style>.{_OUTSIDE_CLASS} text {{ font-style: italic; }}</style>"


def _document(data: Mapping[str, Any]) -> dict[str, Any]:
    """A checked, independent copy of a document, with ``edges``."""
    problems = check_node_link(data)
    if problems:
        shown = "; ".join(problems[:3])
        more = f" (and {len(problems) - 3} more)" if len(problems) > 3 else ""
        raise ValueError(f"not a protee-node-link/0 document: {shown}{more}")
    doc: dict[str, Any] = _plain(data)
    if "edges" not in doc:
        doc["edges"] = doc.pop("links")
    return doc


def _plain(x: Any) -> Any:
    """An independent copy as plain JSON data, read-only mappings included."""
    if isinstance(x, Mapping):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return copy.deepcopy(x)


def _declare(doc: dict[str, Any], *marks: str) -> None:
    """Declare protee's marks in the vocabulary of a document."""
    block = doc["graph"]
    prefixes = dict(block.get("prefixes") or {})
    prefixes.setdefault("protee", None)
    block["prefixes"] = prefixes
    vocabulary = dict(block.get("vocabulary") or {})
    for mark in marks:
        attribute = _MARK_ATTRIBUTE[mark]
        values = list(vocabulary.get(attribute) or [])
        if (mark, "node") not in {(v["id"], v["on"]) for v in values}:
            values.append(dict(_MARKS[mark]))
        vocabulary[attribute] = values
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
        Only nodes whose metric is at least the value are selected; the
        metric ``"inf"`` is at least any value, ``"-inf"`` at most.

    Returns
    -------
    dict
        A new document. It keeps the selected nodes and their direct
        neighbours outside the selection, marked :data:`OUTSIDE` under
        :data:`SELECTION` (a group keeps its own mark under
        :data:`DISPLAY`); a kept node with neighbours not kept counts them in
        ``metrics[HIDDEN]``, added to the count it already had. It keeps the
        edges with a selected end.

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
        if value in ("inf", "-inf"):
            value = math.inf if value == "inf" else -math.inf
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= threshold[1]
        )

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
            node[SELECTION] = OUTSIDE
        else:  # selected now, if outside an earlier selection
            node.pop(SELECTION, None)
        if hidden := len(neighbours[node["id"]] - kept):
            # Added to the neighbours an earlier selection already hid.
            before = (node.get("metrics") or {}).get(HIDDEN)
            _with_metric(node, HIDDEN, hidden + (before or 0))
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
    counts them in ``metrics[MERGED]`` and keeps the attributes and metrics
    they share; an edge redirected alone keeps its attributes and metrics.
    A merged or redirected edge takes the smallest key free between its two
    nodes. A node alone in its group, or without ``by``, stays as it is.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.
    by : str
        The node attribute that makes the groups; its values are texts or
        numbers.

    Returns
    -------
    dict
        A new document.

    Raises
    ------
    ValueError
        If the document does not follow the format.
    TypeError
        If a value of ``by`` is neither a text nor a number.
    """
    doc = _document(data)
    members: dict[Any, list[Any]] = {}
    for node in doc["nodes"]:
        value = node.get(by)
        if isinstance(value, (dict, list)):
            raise TypeError(f"collapse by {by!r}: {value!r} is not a text or a number")
        if value is not None:
            members.setdefault(value, []).append(node["id"])
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

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.

    Returns
    -------
    dict
        A new document.

    Raises
    ------
    ValueError
        If the document does not follow the format.
    """
    doc = _document(data)
    # In the order of their first member, as the nodes are read.
    groups: list[tuple[str, str, list[Any], dict[str, Any]]] = [
        (f"loop:{ids[0]}", f"⟳ {len(ids)}", ids, {})
        for ids in _components(doc, _successors(doc["edges"]))
        if len(ids) > 1
    ]
    return _merge(doc, groups, LOOP)


def mark_vocabularies(data: Mapping[str, Any]) -> dict[str, Any]:
    """Each node with an ``iri``, marked with the vocabulary of that IRI.

    The vocabulary of an IRI is the declared prefix whose IRI begins it (the
    longest, when several do); without one, the authority of the IRI
    (``qudt.org`` for ``http://qudt.org/vocab/quantitykind/Pressure``), or
    its scheme when it has none (``urn``). It is written under
    :data:`VOCABULARY` and declared in ``graph.vocabulary``, labelled with
    the prefix and its IRI, or with the authority, second among the
    attributes of the nodes (first when they have none): the default styles
    then fill the nodes by vocabulary (or shape them), and the legend lists
    the vocabularies, as VOWL and Graffoo colour the terms of each
    vocabulary. A node without ``iri`` has no vocabulary.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.

    Returns
    -------
    dict
        A new document.

    Raises
    ------
    ValueError
        If the document does not follow the format.
    """
    doc = _document(data)
    block = doc["graph"]
    prefixes = [
        (prefix, base)
        for prefix, base in (block.get("prefixes") or {}).items()
        if isinstance(base, str) and base
    ]
    found: dict[str, str] = {}  # value -> label, in the order of first use
    for node in doc["nodes"]:
        node.pop(VOCABULARY, None)
        iri = node.get("iri")
        if not isinstance(iri, str):
            continue
        matches = [
            (len(base), prefix, base)
            for prefix, base in prefixes
            if iri.startswith(base)
        ]
        if matches:
            _, value, base = max(matches)
            label = f"{value}: {base}"
        else:
            value = label = _authority(iri)
        node[VOCABULARY] = value
        found.setdefault(value, label)
    vocabulary = {
        k: v for k, v in (block.get("vocabulary") or {}).items() if k != VOCABULARY
    }
    if found:
        items = list(vocabulary.items())
        first = next(
            (
                k
                for k, (attribute, values) in enumerate(items)
                if attribute not in (DISPLAY, SELECTION)
                and any(v["on"] == "node" for v in values or ())
            ),
            -1,
        )
        declared = [
            {"id": value, "on": "node", "label": label}
            for value, label in found.items()
        ]
        items.insert(first + 1, (VOCABULARY, declared))
        vocabulary = dict(items)
        block["prefixes"] = {**(block.get("prefixes") or {}), "protee": None}
    block["vocabulary"] = vocabulary
    return doc


def _authority(iri: str) -> str:
    """The authority of an IRI without its port, or its scheme."""
    scheme, _, rest = iri.partition(":")
    if rest.startswith("//"):
        host = re.split(r"[/?#]", rest[2:], maxsplit=1)[0].rpartition("@")[2]
        host = host.split(":", 1)[0]
        if host:
            return host
    return scheme


def _successors(edges: Iterable[Mapping[str, Any]]) -> dict[Any, list[Any]]:
    successors: dict[Any, list[Any]] = {}
    for e in edges:
        successors.setdefault(e["source"], []).append(e["target"])
    return successors


def reduce(data: Mapping[str, Any], *, edge_type: str) -> dict[str, Any]:
    """The transitive reduction of one relation: fewer edges, same meaning.

    An edge of type ``edge_type`` from ``u`` to ``v`` is left out when ``v``
    is reached from ``u`` by a longer path of edges of that type: in a
    hierarchy, a link to a grandparent that a parent already gives. A
    second edge of that type between the same two nodes is left out too.
    Edges of other types stay.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.
    edge_type : str
        The ``type`` of the edges of the relation.

    Returns
    -------
    dict
        A new document.

    Raises
    ------
    ValueError
        If the document does not follow the format, or the edges of that
        type form a cycle.
    """
    doc = _document(data)
    successors = _successors(e for e in doc["edges"] if e.get("type") == edge_type)
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
    for edge, *originals in merged.values():
        common = {
            k: v
            for k, v in originals[0].items()
            if k not in ("source", "target", "key", "metrics")
            and all(o.get(k) == v for o in originals)
        }
        edge.update(common)
        measured = [o.get("metrics") or {} for o in originals]
        metrics = {
            k: v
            for k, v in measured[0].items()
            if all(k in m and m[k] == v for m in measured)
        }
        if len(originals) > 1:
            metrics[MERGED] = len(originals)
        if metrics:
            edge["metrics"] = metrics
    _free_keys(kept, [edge for edge, *_ in merged.values()])
    doc["edges"] = kept
    _multigraph(doc)
    _declare(doc, mark)
    return doc


def _free_keys(edges: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> None:
    """Give each edge of ``fresh``, in turn, the smallest key free between
    its two nodes among the integer keys of the other ``edges``."""
    new = {id(e) for e in fresh}
    used: dict[tuple[Any, Any], set[int]] = {}
    for e in edges:
        if id(e) not in new and isinstance(e.get("key"), int):
            used.setdefault((e["source"], e["target"]), set()).add(e["key"])
    for e in fresh:
        keys = used.setdefault((e["source"], e["target"]), set())
        e["key"] = next(k for k in range(len(keys) + 1) if k not in keys)
        keys.add(e["key"])


def _multigraph(doc: dict[str, Any]) -> None:
    """A multigraph as soon as two edges join the same two nodes."""
    pairs = [(e["source"], e["target"]) for e in doc["edges"]]
    doc["multigraph"] = bool(doc["multigraph"]) or len(set(pairs)) < len(pairs)


def contract(
    data: Mapping[str, Any], *, edge_type: str, keep: str = "target"
) -> dict[str, Any]:
    """The two ends of each edge of a type, shown as one node.

    Each edge of type ``edge_type`` disappears, and its two ends become one
    node: the end named by ``keep``, at its place, with its identifier and
    its attributes, completed by those of the other end (for an attribute
    both carry, the kept end wins; ``metrics`` are merged name by name, and
    the counts of hidden neighbours are added). The kept node lists the
    nodes of the original document that it stands for under
    :data:`CONTAINS`, with their number in ``metrics[MEMBERS]``; it is
    outside a selection only if both ends were, and keeps its own mark under
    :data:`DISPLAY`. The edges of the other end are joined to the kept node,
    in both directions; the other edges stay distinct, even when parallel,
    and an edge between the two ends becomes a loop. An edge joined to the
    kept node takes the smallest key free between its two nodes. The label
    and the metrics of a contracted edge are lost.

    It undoes a split of nodes (:func:`protee.transforms.split_nodes`):
    contracting the edges between the two halves of each node, keeping the
    half that the other edges enter, gives the graph back.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.
    edge_type : str
        The ``type`` of the edges to contract. They must not touch: no node
        is the end of two of them, and none is a loop.
    keep : {"target", "source"}
        The end of each edge that stays.

    Returns
    -------
    dict
        A new document; a copy when no edge has that type.

    Raises
    ------
    ValueError
        If the document does not follow the format, ``keep`` is unknown, or
        two edges of that type touch.
    """
    if keep not in ("target", "source"):
        raise ValueError(f"keep must be 'target' or 'source', got {keep!r}")
    doc = _document(data)
    into: dict[Any, Any] = {}  # the end that goes -> the end that stays
    ends: set[Any] = set()
    for e in doc["edges"]:
        if e.get("type") != edge_type:
            continue
        s, t = e["source"], e["target"]
        if s == t:
            raise ValueError(
                f"an edge of type {edge_type!r} is a loop on node {s!r}: "
                "it cannot be contracted"
            )
        for end in (s, t):
            if end in ends:
                raise ValueError(
                    f"the edges of type {edge_type!r} touch at node {end!r}: "
                    "they cannot be contracted"
                )
            ends.add(end)
        stays, goes = (t, s) if keep == "target" else (s, t)
        into[goes] = stays
    if not into:
        return doc
    by_id = {n["id"]: n for n in doc["nodes"]}
    for goes, stays in into.items():
        _absorb(by_id[stays], by_id[goes])
    doc["nodes"] = [n for n in doc["nodes"] if n["id"] not in into]
    edges: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    for e in doc["edges"]:
        if e.get("type") == edge_type:
            continue
        s, t = into.get(e["source"], e["source"]), into.get(e["target"], e["target"])
        if (s, t) != (e["source"], e["target"]):
            e = {k: v for k, v in e.items() if k != "key"} | {"source": s, "target": t}
            moved.append(e)
        edges.append(e)
    _free_keys(edges, moved)
    doc["edges"] = edges
    _multigraph(doc)
    return doc


def _absorb(stays: dict[str, Any], goes: Mapping[str, Any]) -> None:
    """The node ``stays`` takes in the node ``goes``, which disappears."""
    for k, v in goes.items():
        if k in ("id", "metrics") or k.startswith("protee:"):
            continue
        if stays.get(k) is None:
            stays[k] = v
    metrics = {**(goes.get("metrics") or {}), **(stays.get("metrics") or {})}
    hidden = [
        m[HIDDEN]
        for m in (goes.get("metrics") or {}, stays.get("metrics") or {})
        if isinstance(m.get(HIDDEN), int)
    ]
    if hidden:
        metrics[HIDDEN] = sum(hidden)
    members = list(stays.get(CONTAINS) or [stays["id"]])
    members += list(goes.get(CONTAINS) or [goes["id"]])
    stays[CONTAINS] = members
    metrics[MEMBERS] = len(members)
    stays["metrics"] = metrics
    if stays.get(SELECTION) == OUTSIDE and goes.get(SELECTION) != OUTSIDE:
        del stays[SELECTION]


def _quote(text: object) -> str:
    raw = str(text)
    if "\x00" in raw:
        raise ValueError(f"{raw!r} holds a NUL character, which Graphviz cannot read")
    escaped = raw.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


#: Characters a browser ignores around or inside a URL.
_URL_IGNORED = re.compile(r"^[\x00-\x20]+|[\t\n\r]")
_URL_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*):")
_URL_SCHEMES = frozenset({"http", "https", "mailto"})


def _safe_url(url: object) -> str | None:
    """A link that opens no script: http, https, mailto, or relative."""
    if not isinstance(url, str) or not url:
        return None
    cleaned = _URL_IGNORED.sub("", url)
    scheme = _URL_SCHEME.match(cleaned)
    if scheme is not None and scheme.group(1).lower() not in _URL_SCHEMES:
        return None
    return cleaned or None


def _attributes(values: Mapping[str, object]) -> str:
    return ", ".join(f"{k}={_quote(v)}" for k, v in values.items())


def _luminance(colour: str) -> float:
    """The relative luminance of a colour ``#RRGGBB`` (WCAG 2)."""
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    )
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    """The contrast ratio of two colours (WCAG 2), from 1 to 21."""
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _text_on(fill: str) -> str:
    """Black or white, whichever contrasts more with a fill."""
    black, white = _contrast(fill, "#000000"), _contrast(fill, "#FFFFFF")
    return "#000000" if black >= white else "#FFFFFF"


def _defaults(
    vocabulary: Mapping[str, Any], on: str, theme: Theme | None = None
) -> dict[tuple[str, Any], dict[str, str]]:
    """Styles drawn from the declared values, in the order of declaration."""
    attributes = [
        a
        for a, values in vocabulary.items()
        if a not in (DISPLAY, SELECTION) and any(v["on"] == on for v in values or ())
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
                # Without a theme, the text is black unless told otherwise;
                # with one, the ink would be lost on a light fill.
                text = _text_on(fill)
                if theme is not None or text != "#000000":
                    style["fontcolor"] = text
            elif rank == 0:
                colour = _LINE_COLOURS[i % len(_LINE_COLOURS)]
                if theme is not None and colour == "#000000":
                    colour = theme.ink
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
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The attributes of an element: those of all elements (``base``), then
    the default styles of its values, then the caller's."""
    style: dict[str, str] = {}

    def put(attributes: Mapping[str, str]) -> None:
        for k, v in attributes.items():
            # A line style replaces the line of a filled node, which stays
            # filled.
            if (
                k == "style"
                and "filled" in style.get("style", "")
                and "filled" not in v
            ):
                v = f"filled,{v}"
            style[k] = v

    put(base or {})
    for table in (defaults, given):
        for (attribute, value), attributes in table.items():
            if item.get(attribute) == value:
                put(attributes)
    return style


type _Table = dict[tuple[str, Any], dict[str, str]]


def _style_tables(
    doc: Mapping[str, Any], styles: Styles | None, theme: Theme | None = None
) -> tuple[_Table, _Table, dict[str, Mapping[tuple[str, Any], Mapping[str, str]]]]:
    """The default styles of nodes and edges, and the caller's, checked."""
    given: dict[str, Mapping[tuple[str, Any], Mapping[str, str]]] = {
        "node": {},
        "edge": {},
        **(styles or {}),
    }
    if unknown := sorted(set(given) - {"node", "edge"}):
        raise ValueError(
            f"styles: unknown kinds of element {unknown!r}, expected 'node' or 'edge'"
        )
    for kind in given.values():
        for attributes in kind.values():
            if bad := [k for k in attributes if not _NAME.fullmatch(k)]:
                raise ValueError(f"invalid Graphviz attribute names {bad!r}")
    names = [str(n["id"]) for n in doc["nodes"]]
    if len(set(names)) < len(names):
        raise ValueError("two node identifiers write the same in DOT")
    vocabulary = doc["graph"].get("vocabulary") or {}
    node_defaults = _defaults(vocabulary, "node", theme)
    # Grey, and the label in italics: the line of the node stays its own.
    grey = "#7F7F7F" if theme is None else theme.muted
    node_defaults[(SELECTION, OUTSIDE)] = {"color": grey, "class": _OUTSIDE_CLASS}
    node_defaults[(DISPLAY, GROUP)] = {"peripheries": "2"}
    node_defaults[(DISPLAY, LOOP)] = {"peripheries": "3"}
    return node_defaults, _defaults(vocabulary, "edge", theme), given


def _layout(
    attributes: Attributes | None,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """The attributes of the graph, of all nodes and of all edges, checked."""
    given = dict(attributes or {})
    if unknown := sorted(set(given) - set(_KINDS)):
        raise ValueError(
            f"attributes: unknown kinds {unknown!r}, expected 'graph', 'node' or 'edge'"
        )
    checked: list[dict[str, str]] = []
    for kind in _KINDS:
        values = dict(given.get(kind) or {})
        if bad := [k for k in values if not _NAME.fullmatch(k)]:
            raise ValueError(f"invalid Graphviz attribute names {bad!r}")
        if kind == "graph" and (bad := sorted(set(values) - set(_GRAPH_ATTRIBUTES))):
            raise ValueError(
                f"attributes['graph'] sets the layout only {_GRAPH_ATTRIBUTES}, "
                f"not {bad!r}"
            )
        checked.append({k: str(v) for k, v in values.items()})
    return checked[0], checked[1], checked[2]


type _Labels = dict[tuple[str, str, str], str]


def _labels(vocabulary: Mapping[str, Any]) -> _Labels:
    """The label of each declared value: (attribute, on, value) -> label."""
    return {
        (attribute, v["on"], v["id"]): str(v["label"])
        for attribute, values in vocabulary.items()
        for v in values or ()
    }


def _field_lines(
    item: Mapping[str, Any], fields: Iterable[str], labels: _Labels, on: str
) -> list[str]:
    """One line per attribute of ``fields`` that the element carries: the
    label of a declared value, or the value itself."""
    lines = []
    for name in fields:
        value = item.get(name)
        if value is None:
            continue
        if isinstance(value, str):
            value = labels.get((name, on, value), value)
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"{name}: {value}")
    return lines


def _texts(
    node: Mapping[str, Any], fields: Iterable[str] = (), labels: _Labels | None = None
) -> tuple[str, str]:
    """The label of a node (with ``+n`` hidden neighbours) and its tooltip:
    its description (its label without one), then its ``iri`` and ``url``,
    then the attributes of ``fields``."""
    label = str(node.get("label") or node["id"])
    hidden = (node.get("metrics") or {}).get(HIDDEN)
    tooltip = [str(node.get("description") or label)]
    tooltip += [str(node[k]) for k in ("iri", "url") if node.get(k)]
    tooltip += _field_lines(node, fields, labels or {}, "node")
    return (f"{label}\n+{hidden}" if hidden else label), "\n".join(tooltip)


def _edge_lines(
    edge: Mapping[str, Any], fields: Iterable[str], labels: _Labels
) -> list[str]:
    """The tooltip of an edge: its description, its ``locator``, then the
    attributes of ``fields``."""
    lines = (
        [str(edge["description"])] if isinstance(edge.get("description"), str) else []
    )
    if edge.get("locator"):
        lines.append(f"locator: {edge['locator']}")
    return lines + _field_lines(edge, fields, labels, "edge")


def _heads(theme: Theme | None) -> tuple[dict[str, str], dict[str, str]]:
    """The attributes of the graph and of every element that a theme sets."""
    graph = {"fontname": _FONT}
    element = {"fontname": _FONT}
    if theme is not None:
        graph.update(bgcolor=theme.background, fontcolor=theme.ink, color=theme.ink)
        element.update(color=theme.ink, fontcolor=theme.ink)
    return graph, element


def to_dot(
    data: Mapping[str, Any],
    *,
    styles: Styles | None = None,
    attributes: Attributes | None = None,
    theme: Theme | None = None,
    order_by: str | None = None,
    direction: str = "TB",
    legend: bool = True,
    legend_values: str = "declared",
    tooltip: Iterable[str] = (),
) -> str:
    """The Graphviz DOT text of a document.

    A node shows its ``label`` (its ``id`` without one), followed by
    ``+n`` when ``n`` of its neighbours are not shown; its tooltip is its
    ``description``, then its ``iri`` and ``url``; its link is its ``url``
    when it opens no script (http, https, mailto, or a relative link). The
    default styles come from the declared vocabulary, in the order of
    declaration:

    - nodes: the first declared attribute sets the shape, the second the
      fill colour (:data:`OKABE_ITO`), with a black or white text, whichever
      contrasts more, and the border line;
    - edges: the first declared attribute sets the colour (yellow aside)
      and the arrowhead, the second the line (dashed, dotted, bold); a
      symmetric value draws its head at both ends;
    - marks: :data:`OUTSIDE` has a grey border and its label in italics
      (class ``protee_outside``, which :func:`render_svg` and
      :func:`render_html` draw in italics), its line kept; :data:`GROUP`
      has a double border, :data:`LOOP` a triple one.

    The distinctions hold without the colours up to 7 values of the first
    node attribute, 3 of the second, 8 heads for the first edge attribute
    and 3 lines for the second; beyond, the cues repeat and only the colours
    tell the values apart. The caller's ``attributes`` come first, then the
    defaults, then the caller's ``styles``.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.
    styles : mapping, optional
        ``{"node": {(attribute, value): {graphviz_attribute: text}},
        "edge": {...}}``. For instance ``{"edge": {("role", "x:closing"):
        {"style": "dashed", "constraint": "false"}}}`` draws an edge dashed
        and lets it not constrain the layout.
    attributes : mapping, optional
        ``{"graph": {...}, "node": {...}, "edge": {...}}``: Graphviz
        attributes of the graph, and of all nodes and all edges, the legend
        included (``{"node": {"fontsize": "11"}}``). The graph takes layout
        attributes only: ``splines``, ``ranksep``, ``nodesep`` and ``pad``.
    theme : Theme, optional
        The background, ink and muted grey (:data:`LIGHT`, :data:`DARK`, or
        a :class:`Theme` of one's own); the defaults of Graphviz without
        one.
    order_by : str, optional
        A numeric node attribute: the nodes that carry it are drawn in
        increasing order along ``direction``, the others placed by Graphviz.
    direction : {"TB", "LR", "BT", "RL"}
        The direction of the edges: top to bottom, left to right, bottom to
        top, right to left.
    legend : bool
        A cluster, placed by Graphviz, that shows each declared value with
        its style and label. A node value that sets no shape is shown with
        the shape of the nodes that carry it when they share one, and as a
        rounded box otherwise. A value with ``mappings`` lists them in its
        tooltip.
    legend_values : {"declared", "present"}
        The values the legend shows: all the declared values, or only those
        that a node or an edge of the document carries.
    tooltip : iterable of str
        Attributes whose values the tooltips of the nodes and of the edges
        add, one line each: the label of a declared value, or the value
        itself. An edge has a tooltip when it has a description, a
        ``locator`` or one of these attributes.

    Returns
    -------
    str

    Raises
    ------
    ValueError
        If the document does not follow the format, the direction or
        ``legend_values`` is unknown, a value of ``order_by`` is not finite,
        two node identifiers write the same, a style or an attribute names
        an invalid Graphviz attribute, a kind of element is unknown, or the
        graph attributes set more than the layout.
    TypeError
        If a value of ``order_by`` is not a number.
    """
    doc = _document(data)
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be one of {_DIRECTIONS}, got {direction!r}")
    if legend_values not in _LEGEND_VALUES:
        raise ValueError(
            f"legend_values must be one of {_LEGEND_VALUES}, got {legend_values!r}"
        )
    graph_attributes, node_base, edge_base = _layout(attributes)
    node_defaults, edge_defaults, given = _style_tables(doc, styles, theme)
    block = doc["graph"]
    themed, element = _heads(theme)
    head = {"rankdir": direction, **themed, **graph_attributes}
    if block.get("label"):
        head.update(label=block["label"], labelloc="t")
    if block.get("description"):
        head["tooltip"] = block["description"]
    lines = [
        f"digraph {_quote(block.get('label') or 'graph')} {{",
        f"  graph [{_attributes(head)}];",
        f"  node [{_attributes(element)}];",
        f"  edge [{_attributes(element)}];",
    ]
    fields = tuple(tooltip)
    labels = _labels(block.get("vocabulary") or {})
    for node in doc["nodes"]:
        label, text = _texts(node, fields, labels)
        values: dict[str, object] = {"label": label, "tooltip": text}
        if url := _safe_url(node.get("url")):
            values["URL"] = url
        values.update(_style(node, node_defaults, given["node"], node_base))
        lines.append(f"  {_quote(node['id'])} [{_attributes(values)}];")
    for edge in doc["edges"]:
        values = {}
        if edge.get("label"):
            values["label"] = edge["label"]
        if notes := _edge_lines(edge, fields, labels):
            values["tooltip"] = "\n".join(notes)
        values.update(_style(edge, edge_defaults, given["edge"], edge_base))
        lines.append(
            f"  {_quote(edge['source'])} -> {_quote(edge['target'])}"
            + (f" [{_attributes(values)}]" if values else "")
            + ";"
        )
    if order_by is not None:
        lines += _ordering(doc["nodes"], order_by)
    if legend:
        entries = _legend_entries(
            doc,
            node_defaults,
            edge_defaults,
            given,
            node_base=node_base,
            edge_base=edge_base,
            present=legend_values == "present",
        )
        lines += _legend(entries, {str(n["id"]) for n in doc["nodes"]}, theme)
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_svg(
    data: Mapping[str, Any],
    *,
    styles: Styles | None = None,
    attributes: Attributes | None = None,
    theme: Theme | None = None,
    order_by: str | None = None,
    direction: str = "TB",
    legend: str | None = "right",
    legend_values: str = "declared",
    tooltip: Iterable[str] = (),
    footer: bytes | None = None,
    footer_height: float | None = None,
) -> str:
    """An SVG drawing of a document, laid out by Graphviz (``dot``).

    The text of :func:`to_dot`, with the same parameters, laid out and
    drawn by the Graphviz that pygraphviz bundles in its wheels (Windows,
    Linux and macOS, on x86-64 and ARM 64; elsewhere, pygraphviz builds
    against a Graphviz installed on the workstation). Nothing is fetched.
    Labels stay text, in system fonts. With the same document, the same
    versions and the same fonts, the SVG is the same, byte for byte.

    Orthogonal edges (``attributes={"graph": {"splines": "ortho"}}``) are
    laid out in a child process of the same Python: their routing in
    Graphviz can stop the process that runs it, which then raises a
    ``RuntimeError`` instead of stopping the caller's.

    Parameters
    ----------
    data, styles, attributes, theme, order_by, direction, legend_values, tooltip
        As :func:`to_dot`.
    legend : {"right", "below", "below-left"} or None
        ``"right"``: the cluster of :func:`to_dot`, placed by Graphviz
        beside the graph. ``"below"``, ``"below-left"``: the legend of
        :func:`render_legend_svg`, laid out apart and drawn under the
        graph, centred or at the left; it widens the figure only when it is
        wider than the graph. ``None``: no legend.
    footer : bytes, optional
        The bytes of a PNG or SVG image (an SVG needs a ``viewBox``), drawn
        under the graph at the right, the legend below at the left. It is
        embedded in the drawing (a ``data:`` URI), never linked.
    footer_height : float, optional
        The height of the footer in points; that of the legend below by
        default.

    Returns
    -------
    str
        The SVG document.

    Raises
    ------
    ImportError
        If pygraphviz is not installed (the optional extra ``viz``).
    ValueError, TypeError
        As :func:`to_dot`, or if ``legend`` is not one of its values, the
        footer is not a PNG or SVG image, or it has no height (no legend
        below and no ``footer_height``).
    RuntimeError
        If Graphviz stops while laying out orthogonal edges, or the child
        process cannot be started.
    """
    if legend not in _LEGEND_PLACES:
        raise ValueError(f"legend must be one of {_LEGEND_PLACES}, got {legend!r}")
    image = None if footer is None else _image(footer)
    if footer_height is not None and not (
        math.isfinite(footer_height) and footer_height > 0
    ):
        raise ValueError(
            f"footer_height must be a positive number, got {footer_height!r}"
        )
    graphviz = _pygraphviz("render_svg")
    dot = to_dot(
        data,
        styles=styles,
        attributes=attributes,
        theme=theme,
        order_by=order_by,
        direction=direction,
        legend=legend == "right",
        legend_values=legend_values,
        tooltip=tooltip,
    )
    graph_attributes, node_base, edge_base = _layout(attributes)
    drawing = _svg(graphviz, dot, apart=graph_attributes.get("splines") == "ortho")
    below = None
    if legend in ("below", "below-left"):
        doc = _document(data)
        entries = _legend_entries(
            doc,
            *_style_tables(doc, styles, theme),
            node_base=node_base,
            edge_base=edge_base,
            present=legend_values == "present",
        )
        if entries:
            below = _svg(graphviz, _legend_dot(entries, theme))
    if image is not None and footer_height is None and below is None:
        raise ValueError("footer_height is needed when no legend is drawn below")
    if below is None and image is None:
        return drawing
    return _stack(
        drawing,
        below,
        left=legend == "below-left",
        footer=None if image is None else (image, footer_height),
        background=None if theme is None else theme.background,
    )


def render_legend_svg(
    data: Mapping[str, Any],
    *,
    styles: Styles | None = None,
    attributes: Attributes | None = None,
    theme: Theme | None = None,
    values: str = "declared",
) -> str:
    """The legend of a document alone, in SVG, laid out by Graphviz.

    Each declared value with the style it takes in :func:`render_svg` with
    the same ``styles`` and ``attributes``, so that a figure can carry its
    legend apart: one column per attribute and per kind of element (nodes,
    edges), in the order of declaration. A node value that sets no shape is
    shown with the shape of the nodes that carry it when they share one,
    and as a rounded box when they have several or none carries it. A value
    with ``mappings`` lists them in its tooltip.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.
    styles, attributes, theme : optional
        As :func:`to_dot`; the graph attributes do not apply to the legend.
    values : {"declared", "present"}
        All the declared values, or only those that a node or an edge of
        the document carries.

    Returns
    -------
    str
        The SVG document.

    Raises
    ------
    ImportError
        If pygraphviz is not installed (the optional extra ``viz``).
    ValueError
        If the document does not follow the format or the legend shows no
        value, two node identifiers write the same, a style or an attribute
        names an invalid Graphviz attribute, or ``values`` is unknown.
    """
    graphviz = _pygraphviz("render_legend_svg")
    doc = _document(data)
    if values not in _LEGEND_VALUES:
        raise ValueError(f"values must be one of {_LEGEND_VALUES}, got {values!r}")
    _, node_base, edge_base = _layout(attributes)
    entries = _legend_entries(
        doc,
        *_style_tables(doc, styles, theme),
        node_base=node_base,
        edge_base=edge_base,
        present=values == "present",
    )
    if not entries:
        raise ValueError(
            "the document declares no value: there is no legend"
            if values == "declared"
            else "no node or edge carries a declared value: there is no legend"
        )
    return _svg(graphviz, _legend_dot(entries, theme))


#: The program of the child process that lays out a DOT text: the import
#: path of the parent as arguments, the text on its input, the SVG on its
#: output, in bytes.
_CHILD = (
    "import sys\n"
    "sys.path[:0] = sys.argv[1:]\n"
    "import pygraphviz\n"
    "dot = sys.stdin.buffer.read().decode('utf-8')\n"
    "svg = pygraphviz.AGraph(string=dot).draw(format='svg', prog='dot')\n"
    "sys.stdout.buffer.write(svg)\n"
)


def _drawn_apart(dot: str) -> bytes:
    """The SVG of a DOT text, laid out by Graphviz in a child process."""
    if getattr(sys, "frozen", False) or not sys.executable:
        raise RuntimeError(
            "orthogonal edges are laid out in a child Python process, which "
            "this program cannot start; splines='polyline' draws without it"
        )
    done = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD, *(p for p in sys.path if p)],
        input=dot.encode("utf-8"),
        capture_output=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode != 0 or b"<svg" not in done.stdout:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(
            "Graphviz stopped while routing orthogonal edges "
            f"(exit code {done.returncode})"
            + (f": {detail}" if detail else "")
            + "; splines='polyline' draws without it"
        )
    return done.stdout


def _svg(graphviz: Any, dot: str, *, apart: bool = False) -> str:
    drawing: bytes = (
        _drawn_apart(dot)
        if apart
        else graphviz.AGraph(string=dot).draw(format="svg", prog="dot")
    )
    svg = _renumbered(drawing.decode("utf-8"))
    if _OUTSIDE_CLASS in svg:
        root = _SVG_ROOT.search(svg)
        assert root is not None, "Graphviz writes the root of its SVG so"
        svg = f"{svg[: root.end()]}\n{_OUTSIDE_STYLE}{svg[root.end() :]}"
    return svg


#: The gradients of a fill or a colour list: Graphviz numbers them with a
#: counter of its process, ``<element>_l_<n>`` or ``<element>_r_<n>``.
_GRADIENT = re.compile(
    r'(?<=id=")((?:\w+_)?[lr]_)(\d+)(?=")|(?<=url\(#)((?:\w+_)?[lr]_)(\d+)(?=\))'
)


def _renumbered(svg: str) -> str:
    """The SVG with its gradients numbered in their order, from 0: the same
    document gives the same SVG, whatever Graphviz drew before."""
    numbers: dict[str, int] = {}

    def number(match: re.Match[str]) -> str:
        stem = match.group(1) or match.group(3)
        old = stem + (match.group(2) or match.group(4))
        return stem + str(numbers.setdefault(old, len(numbers)))

    return _GRADIENT.sub(number, svg)


_SVG_ROOT = re.compile(r'<svg width="[^"]*" height="[^"]*"\s+viewBox="([^"]*)"([^>]*)>')
_GAP = 12.0


@dataclass(frozen=True, slots=True)
class _Image:
    """An image to embed: its media type, its bytes, its width over its
    height."""

    media: str
    data: bytes
    ratio: float


_PNG = b"\x89PNG\r\n\x1a\n"
_SVG_NS = "http://www.w3.org/2000/svg"


def _image(footer: object) -> _Image:
    """The image of a footer, read from its bytes: a PNG or an SVG."""
    if not isinstance(footer, (bytes, bytearray, memoryview)):
        raise TypeError(
            "footer must be the bytes of a PNG or SVG image, never a file name "
            f"or a URL; got {type(footer).__name__}"
        )
    data = bytes(footer)
    if data.startswith(_PNG):
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ValueError("footer: a PNG image without its IHDR header")
        width, height = struct.unpack(">II", data[16:24])
        if not (width and height):
            raise ValueError("footer: a PNG image of zero width or height")
        return _Image("image/png", data, width / height)
    if data.startswith(b"\x1f\x8b"):
        raise ValueError("footer: a compressed SVG image is not read; give it plain")
    width, height = _svg_size(data)
    return _Image("image/svg+xml", data, width / height)


class _Found(Exception):
    """The root element of an SVG image is read: the rest is not."""


def _svg_size(data: bytes) -> tuple[float, float]:
    """The width and height of the ``viewBox`` of an SVG image."""
    parser = xml.parsers.expat.ParserCreate(namespace_separator=" ")
    root: dict[str, Any] = {}

    def start(name: str, attributes: dict[str, str]) -> None:
        root.update(name=name, attributes=attributes)
        raise _Found

    def refuse(*_: object) -> None:
        raise ValueError("footer: an SVG image with a DOCTYPE is not read")

    parser.StartElementHandler = start
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    try:
        parser.Parse(data, True)
    except _Found:
        pass
    except xml.parsers.expat.ExpatError as err:
        raise ValueError(f"footer: neither a PNG nor an SVG image ({err})") from err
    if root.get("name") != f"{_SVG_NS} svg":
        raise ValueError("footer: neither a PNG nor an SVG image")
    box = str(root["attributes"].get("viewBox", ""))
    try:
        numbers = [float(v) for v in re.split(r"[\s,]+", box.strip())]
    except ValueError:
        numbers = []
    if not (
        len(numbers) == 4
        and all(math.isfinite(v) for v in numbers)
        and numbers[2] > 0
        and numbers[3] > 0
    ):
        raise ValueError("footer: an SVG image needs a viewBox of positive size")
    return numbers[2], numbers[3]


def _root(svg: str) -> tuple[re.Match[str], float, float, str]:
    """The root of an SVG of Graphviz, its width, its height, its content."""
    root = _SVG_ROOT.search(svg)
    assert root is not None, "Graphviz writes the root of its SVG so"
    width, height = (float(x) for x in root.group(1).split()[2:])
    return root, width, height, svg[root.end() : svg.rindex("</svg>")]


def _stack(
    top: str,
    bottom: str | None = None,
    *,
    left: bool = False,
    footer: tuple[_Image, float | None] | None = None,
    background: str | None = None,
) -> str:
    """One SVG: the drawing ``top``, centred, above a row that holds the
    drawing ``bottom`` (a legend), centred or at the left, and the image of
    ``footer`` at the right, at its height or at that of ``bottom``.

    The identifiers of ``bottom``, and the references to them, are
    prefixed, so that none is repeated; the image is embedded whole, so its
    own identifiers stay in it.
    """
    first, top_width, top_height, top_inner = _root(top)
    legend = None
    if bottom is not None:
        root, w, h, inner = _root(bottom)
        for mark in (' id="', "url(#", 'href="#'):
            inner = inner.replace(mark, mark + "protee-legend-")
        legend = (root, w, h, inner)
    image = None
    if footer is not None:
        picture, wanted = footer
        height = wanted if wanted is not None else legend[2] if legend else None
        assert height is not None, "render_svg checks that the footer has a height"
        image = (picture, height * picture.ratio, height)
    widths = [p[1] for p in (legend, image) if p is not None]
    row_width = sum(widths) + _GAP * (len(widths) - 1)
    row_height = max((p[2] for p in (legend, image) if p is not None), default=0.0)
    width = max(top_width, row_width)
    height = top_height + (_GAP + row_height if widths else 0.0)
    lines = [
        top[: first.start()]
        + f'<svg width="{width:.0f}pt" height="{height:.0f}pt"\n'
        + f' viewBox="0.00 0.00 {width:.2f} {height:.2f}"{first.group(2)}>'
    ]
    if background is not None:
        lines.append(
            f'<rect width="{width:.2f}" height="{height:.2f}" fill="{background}"/>'
        )
    lines.append(
        f'<svg x="{(width - top_width) / 2:.2f}" y="0.00" width="{top_width:.2f}"'
        f' height="{top_height:.2f}" viewBox="{first.group(1)}">{top_inner}</svg>'
    )
    y = top_height + _GAP
    if legend is not None:
        root, w, h, inner = legend
        x = 0.0 if left or image is not None else (width - w) / 2
        lines.append(
            f'<svg x="{x:.2f}" y="{y + (row_height - h) / 2:.2f}" width="{w:.2f}"'
            f' height="{h:.2f}" viewBox="{root.group(1)}">{inner}</svg>'
        )
    if image is not None:
        picture, w, h = image
        encoded = base64.b64encode(picture.data).decode("ascii")
        lines.append(
            f'<image x="{width - w:.2f}" y="{y + (row_height - h) / 2:.2f}"'
            f' width="{w:.2f}" height="{h:.2f}" preserveAspectRatio="xMidYMid meet"'
            f' xlink:href="data:{picture.media};base64,{encoded}"/>'
        )
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
#: The colours of the page without a theme: background, ink, muted grey,
#: rules, notes and tooltips.
_PAGE_COLOURS = ("#FFFFFF", "#000000", "#7F7F7F", "#CCCCCC", "#555555", "#FFFFE8")
_PAGE_STYLE = """
body { margin: 0; font-family: Helvetica, Arial, sans-serif; font-size: 14px;
  background: var(--bg); color: var(--ink); }
header { position: absolute; top: 0; left: 0; right: 0; height: 2.6em;
  display: flex; gap: .6em; align-items: center; padding: 0 .8em;
  border-bottom: 1px solid var(--rule); }
#cy { position: absolute; top: 2.6em; left: 0; right: 20em; bottom: 0; }
#matrix { display: none; position: absolute; top: 50%; left: 0; right: 20em;
  bottom: 0; overflow: auto; border-top: 1px solid var(--rule); }
body.matrix #cy { bottom: 50%; }
body.matrix #matrix { display: block; }
#matrix g.protee-cell, #matrix g.protee-diagonal { cursor: pointer; }
#matrix g.hl rect, #matrix g.hl circle { stroke: #F0E442; stroke-width: 4px; }
aside { position: absolute; top: 2.6em; right: 0; width: 19em; bottom: 0;
  overflow: auto; padding: .5em; border-left: 1px solid var(--rule); }
aside h2 { font-size: 1em; margin: .8em 0 .3em; }
aside ul { list-style: none; margin: 0; padding: 0; }
aside li { margin: .25em 0; }
aside svg, aside img { max-width: 100%; height: auto; }
.note { color: var(--note); font-size: .9em; }
#tip { position: absolute; display: none; max-width: 24em; padding: .3em .5em;
  white-space: pre-line; background: var(--tip); border: 1px solid var(--muted);
  pointer-events: none; }
#tip math { display: block; margin-top: .3em; }
"""
_PAGE_SCRIPT = """
(function () {
  var elements = JSON.parse(document.getElementById("protee-elements").textContent);
  var look = JSON.parse(document.getElementById("protee-look").textContent);
  var order = JSON.parse(document.getElementById("protee-order").textContent);
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
        "background-color": look.background, "border-width": 1,
        "border-color": look.ink, "color": look.ink } },
      { selector: ":parent", style: {
        "text-valign": "top", "background-opacity": 0.04, "border-style": "dashed",
        "border-color": look.muted } },
      { selector: "edge", style: {
        "curve-style": "bezier", "width": 1, "line-color": look.ink,
        "target-arrow-shape": "triangle", "target-arrow-color": look.ink,
        "label": "data(label)", "font-size": 9, "color": look.ink } },
      { selector: "node.cy-expand-collapse-collapsed-node", style: {
        "shape": "round-rectangle", "border-style": "double", "border-width": 4 } },
      { selector: ".match", style: {
        "overlay-color": "#D55E00", "overlay-opacity": 0.3, "overlay-padding": 6 } },
      { selector: ".faded", style: { "opacity": 0.2 } }
    ]
  });
  var api = cy.expandCollapse({ layoutBy: null, fisheye: false, animate: false,
    undoable: false, cueEnabled: true });
  document.getElementById("collapse").onclick = function () { api.collapseAll(); };
  document.getElementById("expand").onclick = function () { api.expandAll(); };
  document.getElementById("fit").onclick = function () { cy.fit(); };
  // A formula is data: elements of a closed list, and texts; no markup is
  // ever read, and no attribute is ever set.
  var MATHML = "http://www.w3.org/1998/Math/MathML";
  var FORMULA = { "math": 1, "mrow": 1, "mi": 1, "mn": 1, "mo": 1, "mfrac": 1,
    "msup": 1, "msub": 1, "msubsup": 1, "msqrt": 1, "mroot": 1 };
  function formula(tree) {
    if (typeof tree === "string") { return document.createTextNode(tree); }
    if (!Object.prototype.hasOwnProperty.call(FORMULA, tree[0])) {
      return document.createTextNode("");
    }
    var element = document.createElementNS(MATHML, tree[0]);
    for (var k = 2; k < tree.length; k++) { element.appendChild(formula(tree[k])); }
    return element;
  }
  var tip = document.getElementById("tip");
  cy.on("mouseover", "node, edge", function (event) {
    var text = event.target.data("tooltip");
    var math = event.target.data("math");
    if (!text && !math) { return; }
    tip.textContent = text || "";
    if (math) { tip.appendChild(formula(math)); }
    tip.style.left = (event.renderedPosition.x + 14) + "px";
    tip.style.top = (event.renderedPosition.y + 44) + "px";
    tip.style.display = "block";
  });
  cy.on("mouseout", "node, edge", function () { tip.style.display = "none"; });
  cy.on("dbltap", "node", function (event) {
    var url = event.target.data("url");
    if (url) { window.open(url, "_blank", "noopener"); }
  });
  // The matrix: a node chosen in the graph lights its row and its column; a
  // cell chosen in the matrix marks its edges in the graph.
  var matrix = document.getElementById("matrix");
  if (matrix) {
    var cells = Array.prototype.slice.call(
      matrix.querySelectorAll("g.protee-cell, g.protee-diagonal"));
    var light = function (test) {
      cells.forEach(function (g) { g.classList.toggle("hl", test(g.dataset)); });
    };
    document.getElementById("matrix-toggle").onclick = function () {
      document.body.classList.toggle("matrix");
      cy.resize();
    };
    cy.on("tap", "node", function (event) {
      var i = order.indexOf(event.target.id());
      light(function (d) {
        return i >= 0 && (+d.row === i || +d.col === i || +d.index === i);
      });
    });
    matrix.addEventListener("click", function (event) {
      var g = event.target.closest("g.protee-cell, g.protee-diagonal");
      if (!g) { return; }
      var d = g.dataset;
      cy.elements().removeClass("match");
      if (d.index !== undefined) {
        cy.getElementById(order[+d.index]).addClass("match");
      } else {
        var source = order[+d.row], target = order[+d.col];
        cy.edges().filter(function (edge) {
          return edge.data("source") === source && edge.data("target") === target;
        }).addClass("match");
      }
      light(function (other) { return other === d; });
    });
  }
  // Filters: an unchecked value hides the nodes or the edges that carry it
  // (and the edges of a hidden node); the search marks the matching labels.
  var boxes = Array.prototype.slice.call(
    document.querySelectorAll("#filters input[type=checkbox]"));
  var search = document.getElementById("search");
  function hidden(element, on) {
    var values = element.data("values") || {};
    return boxes.some(function (box) {
      return !box.checked && box.dataset.on === on &&
        values[box.dataset.attribute] === box.dataset.value;
    });
  }
  function apply() {
    var text = search.value.trim().toLowerCase();
    cy.batch(function () {
      cy.nodes().forEach(function (node) {
        if (node.isParent()) { return; }
        node.style("display", hidden(node, "node") ? "none" : "element");
        var label = String(node.data("label") || "").toLowerCase();
        var match = text !== "" && label.indexOf(text) >= 0;
        node.toggleClass("match", match);
        node.toggleClass("faded", text !== "" && !match);
      });
      cy.edges().forEach(function (edge) {
        edge.style("display", hidden(edge, "edge") ? "none" : "element");
        edge.toggleClass("faded", text !== "");
      });
    });
  }
  boxes.forEach(function (box) { box.onchange = apply; });
  search.oninput = apply;
  document.getElementById("all").onclick = function () {
    boxes.forEach(function (box) { box.checked = true; });
    search.value = "";
    apply();
  };
})();
"""
#: The elements of a formula (MathML), without attributes, and its bounds.
_FORMULA = frozenset(
    {
        "math",
        "mrow",
        "mi",
        "mn",
        "mo",
        "mfrac",
        "msup",
        "msub",
        "msubsup",
        "msqrt",
        "mroot",
    }
)
_FORMULA_SIZE = 2000
_FORMULA_DEPTH = 32


def _asset(name: str) -> str:
    return files("protee").joinpath("_assets", name).read_text(encoding="utf-8")


def _formula(tree: object, where: str) -> Any:
    """A formula, checked: ``["math", {}, children…]``, each child a text or
    a node ``[name, {}, children…]`` of a MathML element of the closed list
    :data:`_FORMULA`, without attributes, at most 2000 elements and 32
    levels deep."""
    if not (isinstance(tree, list) and tree and tree[0] == "math"):
        raise ValueError(f"{where}: a formula is a list ['math', {{}}, ...]")
    count = 0
    stack: list[tuple[object, int, str]] = [(tree, 1, "")]
    while stack:
        node, depth, path = stack.pop()
        if isinstance(node, str):
            continue
        if not (isinstance(node, list) and len(node) >= 2 and isinstance(node[0], str)):
            raise ValueError(
                f"{where}{path}: an element of a formula is [name, {{}}, children...]"
            )
        if node[0] not in _FORMULA:
            raise ValueError(
                f"{where}{path}: {node[0]!r} is not an element of a formula "
                f"({', '.join(sorted(_FORMULA))})"
            )
        if node[1] != {}:
            raise ValueError(f"{where}{path}: an element of a formula has no attribute")
        count += 1
        if count > _FORMULA_SIZE or depth > _FORMULA_DEPTH:
            raise ValueError(
                f"{where}: a formula has at most {_FORMULA_SIZE} elements, "
                f"{_FORMULA_DEPTH} levels deep"
            )
        stack.extend(
            (child, depth + 1, f"{path}[{k}]") for k, child in enumerate(node) if k > 1
        )
    return tree


def _groups(doc: dict[str, Any], group_by: str | None) -> list[tuple[str, list[Any]]]:
    """(label, members) of the groups shown as compound nodes: the loops, or
    the nodes that share a value of an attribute."""
    if group_by is None:
        return []
    if group_by == "loop":
        loops = _components(doc, _successors(doc["edges"]))
        return [(f"⟳ {len(ids)}", ids) for ids in loops if len(ids) > 1]
    members: dict[Any, list[Any]] = {}
    for node in doc["nodes"]:
        value = node.get(group_by)
        if isinstance(value, (dict, list)):
            raise TypeError(
                f"group_by {group_by!r}: {value!r} is not a text or a number"
            )
        if value is not None:
            members.setdefault(value, []).append(node["id"])
    return [(str(v), ids) for v, ids in members.items() if len(ids) > 1]


def _font_size(style: Mapping[str, str], out: dict[str, object]) -> None:
    """The font size of Graphviz, in the points of cytoscape.js."""
    try:
        size = float(style.get("fontsize", ""))
    except ValueError:
        return
    if math.isfinite(size) and size > 0:
        out["font-size"] = size


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
    if _OUTSIDE_CLASS in style.get("class", "").split():
        out["font-style"] = "italic"
    _font_size(style, out)
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
    _font_size(style, out)
    return out


def _page_colours(theme: Theme | None) -> tuple[str, dict[str, str]]:
    """The CSS variables of the page, and the colours of cytoscape.js."""
    if theme is None:
        background, ink, muted, rule, note, tip = _PAGE_COLOURS
    else:
        background, ink, muted = theme.background, theme.ink, theme.muted
        rule = note = muted
        tip = background
    scheme = "dark" if _luminance(background) < 0.5 else "light"
    css = (
        f":root {{ --bg: {background}; --ink: {ink}; --muted: {muted}; "
        f"--rule: {rule}; --note: {note}; --tip: {tip}; color-scheme: {scheme}; }}"
    )
    return css, {"background": background, "ink": ink, "muted": muted}


def render_html(
    data: Mapping[str, Any],
    *,
    styles: Styles | None = None,
    attributes: Attributes | None = None,
    theme: Theme | None = None,
    order_by: str | None = None,
    direction: str = "TB",
    group_by: str | None = "family",
    title: str | None = None,
    tooltip: Iterable[str] = (),
    math: str | None = None,
    matrix: bool = False,
    legend_values: str = "declared",
    footer: bytes | None = None,
) -> str:
    """A page to explore a document, which opens offline by a double click.

    The nodes keep the positions of the Graphviz layout of
    :func:`render_svg`, with each group drawn together. They keep the
    shapes, fills, colours, lines, heads and font sizes of :func:`to_dot`
    that cytoscape.js can draw: an unknown shape is an ellipse, an unknown
    head a triangle. The page embeds cytoscape.js and its expand-collapse
    extension, with their MIT notices: the reader collapses or expands a
    group with the cue at its corner, or all of them with the buttons. A
    tooltip shows the description of a node, its ``iri`` and its ``url``;
    that of an edge, its label, its declared values, its description and
    its ``locator``; both add the attributes named by ``tooltip``. A double
    click opens the ``url`` of a node when it opens no script. The legend of
    :func:`render_legend_svg` shows the declared values; below it, a box for
    each declared value and each family, with its description, hides the
    nodes or the edges that carry it when unchecked (and the edges of a
    hidden node). A search marks the nodes whose label holds a text; "Show
    all" undoes the filters and the search. Nothing is fetched.

    Parameters
    ----------
    data, styles, theme, order_by, direction, legend_values
        As :func:`to_dot`.
    attributes : mapping, optional
        As :func:`to_dot`. The page keeps the positions of the layout, not
        the routes of the edges: ``splines`` is left out.
    group_by : str or None
        The groups shown as compound nodes: ``"loop"`` for the loops
        (strongly connected components), or a node attribute (``"family"``,
        by default) for the nodes that share a value; ``None`` for none.
    title : str, optional
        The title of the page; the label of the graph without one.
    tooltip : iterable of str
        Attributes whose values the tooltips add, one line each: the label
        of a declared value, or the value itself.
    math : str, optional
        A node attribute that holds a formula, drawn in the tooltip: a
        MathML tree written as data, ``["math", {}, child, …]``, each child
        a text or ``[name, {}, child, …]`` with a name among ``math``,
        ``mrow``, ``mi``, ``mn``, ``mo``, ``mfrac``, ``msup``, ``msub``,
        ``msubsup``, ``msqrt`` and ``mroot``, without attributes, at most
        2000 elements and 32 levels deep. The page builds its elements one
        by one, and never reads markup.
    matrix : bool
        Add the matrix of :func:`render_matrix_svg` (``order_by`` needed),
        shown under the graph with a button: a node chosen in the graph
        lights its row and its column; a cell chosen in the matrix marks its
        edges in the graph.
    footer : bytes, optional
        A PNG or SVG image, as for :func:`render_svg`, shown under the
        legend (a logo, an attribution).

    Returns
    -------
    str
        The HTML page.

    Raises
    ------
    ImportError
        If pygraphviz is not installed (the optional extra ``viz``).
    ValueError, TypeError
        As :func:`to_dot`, or if a formula does not follow its form, a value
        of ``group_by`` is neither a text nor a number, ``matrix`` is asked
        without ``order_by``, or the footer is not a PNG or SVG image.
    """
    graphviz = _pygraphviz("render_html")
    doc = _document(data)
    if matrix and order_by is None:
        raise ValueError("the matrix needs order_by")
    if legend_values not in _LEGEND_VALUES:
        raise ValueError(
            f"legend_values must be one of {_LEGEND_VALUES}, got {legend_values!r}"
        )
    image = None if footer is None else _image(footer)
    fields = tuple(tooltip)
    graph_attributes, node_base, edge_base = _layout(attributes)
    # The page keeps the positions only: the routes of the edges, whose
    # orthogonal kind can stop the process, are left to Graphviz's default.
    graph_attributes.pop("splines", None)
    dot = to_dot(
        doc,
        styles=styles,
        attributes={"graph": graph_attributes, "node": node_base, "edge": edge_base},
        theme=theme,
        order_by=order_by,
        direction=direction,
        legend=False,
    )
    groups = _groups(doc, group_by)
    clusters = [
        f"  subgraph {_quote(f'cluster_{k}')} {{ "
        + " ".join(_quote(i) for i in ids)
        + " }"
        for k, (_, ids) in enumerate(groups)
    ]
    if clusters and order_by is not None:
        # The ranks of order_by span the clusters, which stay whole.
        clusters.insert(0, '  graph [newrank="true"];')
    end = dot.rstrip().rfind("}")
    layout = graphviz.AGraph(string=dot[:end] + "\n".join(clusters) + "\n}\n")
    layout.layout(prog="dot")
    node_defaults, edge_defaults, given = _style_tables(doc, styles, theme)
    vocabulary = doc["graph"].get("vocabulary") or {}
    labels = _labels(vocabulary)
    filters = _filters(doc)
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
    # The nodes of the layout come in the order of the document: they are
    # matched by place, as a name may be written otherwise in DOT.
    for node, drawn in zip(doc["nodes"], layout.nodes(), strict=False):
        x, y = (float(v) for v in drawn.attr["pos"].split(","))
        label, text = _texts(node, fields, labels)
        values: dict[str, Any] = {
            "id": str(node["id"]),
            "label": label,
            "tooltip": text,
            "w": round(float(drawn.attr["width"]) * 72, 2),
            "h": round(float(drawn.attr["height"]) * 72, 2),
        }
        if math is not None and node.get(math) is not None:
            values["math"] = _formula(node[math], f"node {node['id']!r}, {math}")
        if url := _safe_url(node.get("url")):
            values["url"] = url
        if node["id"] in parent:
            values["parent"] = parent[node["id"]]
        if filtered := _filtered(node, filters):
            values["values"] = filtered
        style = _style(node, node_defaults, given["node"], node_base)
        elements.append(
            {"data": values, "position": {"x": x, "y": -y}, "style": _cy_node(style)}
        )
    edge_prefix = _free("protee:edge:", taken)
    for k, edge in enumerate(doc["edges"]):
        values = {
            "id": f"{edge_prefix}{k}",
            "source": str(edge["source"]),
            "target": str(edge["target"]),
        }
        if edge.get("label"):
            values["label"] = edge["label"]
        lines = [str(edge["label"])] if edge.get("label") else []
        lines += [
            f"{attribute}: {labels[(attribute, 'edge', edge[attribute])]}"
            for attribute in vocabulary
            if (attribute, "edge", edge.get(attribute)) in labels
        ]
        if lines := lines + _edge_lines(edge, fields, labels):
            values["tooltip"] = "\n".join(lines)
        if filtered := _filtered(edge, filters):
            values["values"] = filtered
        style = _style(edge, edge_defaults, given["edge"], edge_base)
        elements.append({"data": values, "style": _cy_edge(style)})
    block = doc["graph"]
    heading = title or block.get("label") or "graph"
    entries = _legend_entries(
        doc,
        node_defaults,
        edge_defaults,
        given,
        node_base=node_base,
        edge_base=edge_base,
        present=legend_values == "present",
    )
    legend = _legend_html(
        filters, _svg(graphviz, _legend_dot(entries, theme)) if entries else ""
    )
    if image is not None:
        encoded = base64.b64encode(image.data).decode("ascii")
        legend += f'<p><img alt="" src="data:{image.media};base64,{encoded}"></p>'
    order: list[str] = []
    panel = ""
    if matrix:
        assert order_by is not None, "checked above"
        order = [str(node["id"]) for _, _, node in _ordered(doc, order_by)]
        drawing = render_matrix_svg(doc, order_by=order_by, theme=theme)
        panel = f'<div id="matrix">{drawing[drawing.index("<svg") :]}</div>'
    css, look = _page_colours(theme)
    notices = "\n".join(
        _asset(n)
        for n in ("cytoscape.LICENSE.txt", "cytoscape-expand-collapse.LICENSE.md")
    ).replace("--", "- -")

    def data_script(name: str, value: object) -> str:
        # No "<" at all, so that no text can close or comment out the element.
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        text = text.replace("<", "\\u003c")
        return f'<script type="application/json" id="protee-{name}">{text}</script>'

    return "\n".join(
        [
            "<!doctype html>",
            f'<html lang="{html.escape(str(block.get("language") or "en"))}">',
            "<head>",
            '<meta charset="utf-8">',
            f"<title>{html.escape(str(heading))}</title>",
            f"<style>{css}{_PAGE_STYLE}</style>",
            "</head>",
            "<body>",
            "<header>",
            f"<strong>{html.escape(str(heading))}</strong>",
            '<button id="collapse">Collapse all</button>',
            '<button id="expand">Expand all</button>',
            '<button id="fit">Fit</button>',
            *(['<button id="matrix-toggle">Matrix</button>'] if matrix else []),
            '<input type="search" id="search" placeholder="Find a label">',
            '<button id="all">Show all</button>',
            "</header>",
            '<div id="cy"></div>',
            *([panel] if panel else []),
            f"<aside>{legend}</aside>",
            '<div id="tip"></div>',
            f"<!-- Third-party code embedded below, under the MIT licence:\n{notices}\n-->",
            f"<script>{_asset('cytoscape.min.js')}</script>",
            f"<script>{_asset('cytoscape-expand-collapse.js')}</script>",
            data_script("elements", elements),
            data_script("look", look),
            data_script("order", order),
            f"<script>{_PAGE_SCRIPT}</script>",
            "</body>",
            "</html>",
            "",
        ]
    )


#: A filter of the page: attribute, the kind of element it applies to, and
#: its values, each with its label and description.
type _Filter = tuple[str, str, list[tuple[str, str, str]]]


def _filters(doc: Mapping[str, Any]) -> list[_Filter]:
    """The filters of the page: each declared attribute, for nodes and for
    edges, then the families."""
    out: list[_Filter] = []
    for attribute, declared in (doc["graph"].get("vocabulary") or {}).items():
        for on in ("node", "edge"):
            values = [
                (str(v["id"]), str(v["label"]), str(v.get("description") or ""))
                for v in declared or ()
                if v["on"] == on
            ]
            if values:
                out.append((attribute, on, values))
    families = dict.fromkeys(
        str(n["family"]) for n in doc["nodes"] if n.get("family") is not None
    )
    if families:
        out.append(("family", "node", [(f, f, "") for f in families]))
    return out


def _filtered(item: Mapping[str, Any], filters: list[_Filter]) -> dict[str, str]:
    """The values an element carries for the filters of the page."""
    names = {attribute for attribute, _, _ in filters}
    return {k: str(item[k]) for k in sorted(names) if item.get(k) is not None}


def _legend_html(filters: list[_Filter], drawing: str) -> str:
    """The panel of the page: the drawing of :func:`render_legend_svg`, then
    a box for each value of each filter, with its description."""
    parts = []
    if drawing:
        parts.append(drawing[drawing.index("<svg") :])
    sections = []
    for attribute, on, values in filters:
        boxes = []
        for value, label, description in values:
            note = (
                f' <span class="note">{html.escape(description)}</span>'
                if description
                else ""
            )
            boxes.append(
                f'<li><label><input type="checkbox" checked'
                f' data-attribute="{html.escape(attribute)}" data-on="{on}"'
                f' data-value="{html.escape(value)}"> {html.escape(label)}</label>'
                f"{note}</li>"
            )
        heading = f"{attribute} ({on}s)"
        sections.append(f"<h2>{html.escape(heading)}</h2><ul>{''.join(boxes)}</ul>")
    if sections:
        parts.append(f'<div id="filters">{"".join(sections)}</div>')
    return "".join(parts)


def _order_value(node: Mapping[str, Any], attribute: str) -> int | float | None:
    """The value of a node for ``order_by``: a finite number, or None."""
    value = node.get(attribute)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"order_by {attribute!r}: {value!r} is not a number")
    if not math.isfinite(value):
        raise ValueError(f"order_by {attribute!r}: {value!r} is not finite")
    return value


def _ordering(nodes: list[dict[str, Any]], attribute: str) -> list[str]:
    """Same rank for equal values; invisible heavy edges between ranks."""
    ranks: dict[float, list[Any]] = {}
    for node in nodes:
        value = _order_value(node, attribute)
        if value is not None:
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
    *,
    node_base: Mapping[str, str] | None = None,
    edge_base: Mapping[str, str] | None = None,
    present: bool = False,
) -> list[_Entry]:
    """Each declared value: its attribute, ``on``, and its swatch.

    A node value that sets no shape takes the shape of the nodes that carry
    it when they share one, and a rounded box otherwise: a swatch never
    shows a shape that its nodes do not have. With ``present``, only the
    values that a node or an edge carries: the styles stay those of the
    whole vocabulary, as in the drawing.
    """
    vocabulary = doc["graph"].get("vocabulary") or {}
    shapes = [
        (
            node,
            _style(node, node_defaults, given["node"], node_base).get(
                "shape", "ellipse"
            ),
        )
        for node in doc["nodes"]
    ]
    carried = {
        (attribute, on, item[attribute])
        for on, items in (("node", doc["nodes"]), ("edge", doc["edges"]))
        for item in items
        for attribute in vocabulary
        if item.get(attribute) is not None
    }
    entries: list[_Entry] = []
    for attribute, values in vocabulary.items():
        for v in values or ():  # a null entry declares nothing
            if present and (attribute, v["on"], v["id"]) not in carried:
                continue
            item = {attribute: v["id"]}
            swatch = {"label": str(v["label"])}
            if v.get("mappings"):
                swatch["tooltip"] = "\n".join(
                    [str(v.get("description") or v["label"])]
                    + [f"{m['predicate']} {m['object']}" for m in v["mappings"]]
                )
            if v["on"] == "node":
                swatch.update(_style(item, node_defaults, given["node"], node_base))
                if "shape" not in swatch:
                    found = {s for n, s in shapes if n.get(attribute) == v["id"]}
                    if len(found) == 1:
                        swatch["shape"] = found.pop()
                    else:
                        swatch["shape"] = "box"
                        line = swatch.get("style")
                        swatch["style"] = f"rounded,{line}" if line else "rounded"
            else:
                swatch.update(_style(item, edge_defaults, given["edge"], edge_base))
            entries.append((attribute, v["on"], swatch))
    return entries


_POINT = 'shape="point", width="0.05", label=""'
_LAYOUT_ONLY = ("constraint", "weight", "minlen")


def _free(prefix: str, taken: set[str]) -> str:
    """A prefix of names that no taken name starts with."""
    free, k = prefix, 1
    while any(name.startswith(free) for name in taken):
        k += 1
        free = f"{prefix.rstrip(':')}#{k}:"
    return free


def _point(theme: Theme | None) -> str:
    """The attributes of the ends of an edge swatch."""
    return _POINT if theme is None else f'{_POINT}, color="{theme.ink}"'


def _frame(theme: Theme | None) -> str:
    """The attributes of the frame of the legend."""
    frame = '    label=""; style="dashed";'
    return frame if theme is None else f'{frame} color="{theme.muted}";'


def _swatch(
    k: int,
    on: str,
    swatch: Mapping[str, str],
    prefix: str = "protee:legend:",
    point: str = _POINT,
) -> tuple[list[str], str, str]:
    """The DOT lines of one swatch, and its first and last node."""
    name = f"{prefix}{k}"
    if on == "node":
        return [f"    {_quote(name)} [{_attributes(swatch)}];"], name, name
    a, b = f"{name}:a", f"{name}:b"
    # Graphviz draws the label of an edge against its line: spaces and an
    # empty line keep them apart.
    spaced = {**swatch, "label": f" {swatch['label']} \n"}
    return (
        [
            f"    {_quote(a)} [{point}]; {_quote(b)} [{point}];",
            f"    {_quote(a)} -> {_quote(b)} [{_attributes(spaced)}];",
        ],
        a,
        b,
    )


def _legend(
    entries: list[_Entry], taken: set[str], theme: Theme | None = None
) -> list[str]:
    """The legend as a cluster of the drawing, placed by Graphviz; its names
    are free among the ``taken`` names of the nodes."""
    if not entries:
        return []
    prefix = _free("protee:legend:", taken)
    lines = ["  subgraph cluster_legend {", _frame(theme)]
    for k, (_, on, swatch) in enumerate(entries):
        lines += _swatch(k, on, swatch, prefix, _point(theme))[0]
    lines.append("  }")
    return lines


def _legend_dot(entries: list[_Entry], theme: Theme | None = None) -> str:
    """The legend alone: one column per attribute, in the order of declaration."""
    themed, element = _heads(theme)
    head = {"rankdir": "LR", **themed, "nodesep": "0.1", "ranksep": "0.3"}
    lines = [
        "digraph legend {",
        f"  graph [{_attributes(head)}];",
        f"  node [{_attributes(element)}];",
        f"  edge [{_attributes(element)}];",
        "  subgraph cluster_legend {",
        _frame(theme),
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
            drawn, first, last = _swatch(k, on, swatch, point=_point(theme))
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


#: Characters that XML 1.0 cannot carry, even as references, and lone
#: halves of surrogate pairs (which JSON can carry).
_NOT_XML = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff" + chr(0xFFFE) + chr(0xFFFF) + "]"
)
_CELL = 24  # the side of a cell of the matrix, in points
_MARGIN = 8
_CHAR = 7  # the width of a character of the matrix, roughly, in points
_ROW_LABEL = 40  # characters of a row label, beyond which it is cut
_FORWARD = "#0072B2"  # blue: read later in the order
_FEEDBACK = "#D55E00"  # vermilion: read earlier, a feedback


def _ordered(
    doc: Mapping[str, Any], order_by: str
) -> list[tuple[int | float, int, dict[str, Any]]]:
    """The nodes that carry ``order_by``, with their value and place, in
    increasing order (in the order of the document for equal values)."""
    ordered = []
    for k, node in enumerate(doc["nodes"]):
        value = _order_value(node, order_by)
        if value is not None:
            ordered.append((value, k, node))
    if not ordered:
        raise ValueError(f"no node carries {order_by!r}: the matrix is empty")
    ordered.sort(key=lambda t: (t[0], t[1]))
    return ordered


def _xml(text: object) -> str:
    """A text escaped for XML, refused if XML cannot carry it."""
    raw = str(text)
    if _NOT_XML.search(raw):
        raise ValueError(f"{raw!r} holds a character that XML cannot carry")
    return html.escape(raw, quote=True)


def render_matrix_svg(
    data: Mapping[str, Any],
    *,
    order_by: str,
    theme: Theme | None = None,
    loops: bool = False,
) -> str:
    """The matrix of a document (an N² chart, or design structure matrix).

    The nodes that carry ``order_by`` stand on the diagonal, in increasing
    order (in the order of the document for equal values, each block of
    equal values framed). An edge from the node of a row to the node of a
    column marks their cell: the row gives, the column reads, as in XDSM and
    in the N² charts of OpenMDAO. Above the diagonal, the column comes later
    in the order (a disc); below, it comes earlier, and the edge is a
    feedback (a square). A cell counts its parallel edges; a loop on a node
    is counted on the diagonal. A row above the matrix counts, for each
    column, the edges that come from nodes without ``order_by`` (the
    inputs); the edges between two such nodes, or from a node of the matrix
    to one of them, are not shown.

    Each cell is an element ``g`` of class ``protee-cell``, with its row,
    column and count as ``data-row``, ``data-col`` and ``data-count``, and
    its edges in its ``title``. The matrix is written by protee, without
    Graphviz: it reads well up to about a hundred nodes; beyond, a
    :func:`collapse` shows fewer.

    Parameters
    ----------
    data : mapping
        A ``protee-node-link/0`` document.
    order_by : str
        The numeric node attribute that orders the diagonal.
    theme : Theme, optional
        The background, ink and muted grey; black on white without one, as
        Graphviz draws.
    loops : bool
        Frame the loops: the nodes of the matrix on a common cycle (strongly
        connected components of its edges), from the first to the last.

    Returns
    -------
    str
        The SVG document.

    Raises
    ------
    ValueError
        If the document does not follow the format, no node carries
        ``order_by``, a value of it is not finite, or a label holds a
        character that XML cannot carry.
    TypeError
        If a value of ``order_by`` is not a number.
    """
    doc = _document(data)
    ordered = _ordered(doc, order_by)
    nodes = [node for _, _, node in ordered]
    index = {node["id"]: i for i, node in enumerate(nodes)}
    cells: Counter[tuple[int, int]] = Counter()
    inputs: Counter[int] = Counter()
    for e in doc["edges"]:
        s, t = index.get(e["source"]), index.get(e["target"])
        if s is not None and t is not None:
            cells[(s, t)] += 1
        elif t is not None:
            inputs[t] += 1
    names = [str(node.get("label") or node["id"]) for node in nodes]
    shown = [
        name if len(name) <= _ROW_LABEL else name[: _ROW_LABEL - 1] + "…"
        for name in names
    ]
    ink = "#000000" if theme is None else theme.ink
    muted = "#7F7F7F" if theme is None else theme.muted
    n, c, m = len(nodes), _CELL, _MARGIN
    title = doc["graph"].get("label")
    # The labels, then the numbers of the rows, then the matrix.
    numbers = _CHAR * len(str(n)) + m
    left = m + _CHAR * max(len(s) for s in [*shown, "inputs"]) + m + numbers
    top = m + (2 * c if title else c) + c  # title, column numbers, inputs
    notes = [
        (_FORWARD, "disc: the column reads what the row gives, later in the order"),
        (_FEEDBACK, "square: the column reads it earlier, a feedback"),
        (muted, f"inputs: edges from nodes without {order_by}"),
    ]
    width = max(
        left + n * c + m,
        m + _CHAR * len(str(title or "")) + m,
        m + 16 + _CHAR * max(len(text) for _, text in notes) + m,
    )
    legend_top = top + n * c + m
    height = legend_top + 3 * 16 + m
    root = (
        f'<svg width="{width}pt" height="{height}pt" viewBox="0 0 {width} {height}"'
        ' xmlns="http://www.w3.org/2000/svg"'
        f' font-family="{_FONT}" font-size="11" fill="{ink}">'
    )
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>', root]
    if title:
        out.append(f"<title>{_xml(title)}</title>")
    background = "#FFFFFF" if theme is None else theme.background
    out.append(f'<rect width="{width}" height="{height}" fill="{background}"/>')
    if title:
        out.append(
            f'<text x="{width // 2}" y="{m + c // 2 + 4}" text-anchor="middle"'
            f' font-size="13">{_xml(title)}</text>'
        )
    numbers_y, inputs_y = top - 2 * c, top - c
    for i in range(n):
        x = left + i * c + c // 2
        out.append(
            f'<text x="{x}" y="{numbers_y + c // 2 + 4}" text-anchor="middle">'
            f"{i + 1}</text>"
        )
    out.append(
        f'<text x="{left - numbers}" y="{inputs_y + c // 2 + 4}" text-anchor="end"'
        f' fill="{muted}">inputs</text>'
    )
    for col, count in sorted(inputs.items()):
        x = left + col * c + c // 2
        out.append(
            f'<g class="protee-input" data-col="{col}" data-count="{count}">'
            f"<title>{count} input{'s' if count > 1 else ''} of {_xml(names[col])}"
            f'</title><text x="{x}" y="{inputs_y + c // 2 + 4}" text-anchor="middle"'
            f' fill="{muted}">{count}</text></g>'
        )
    grid = [f"M{left} {top + i * c}H{left + n * c}" for i in range(n + 1)]
    grid += [f"M{left + i * c} {top}V{top + n * c}" for i in range(n + 1)]
    out.append(
        f'<path d="{"".join(grid)}" fill="none" stroke="{muted}" stroke-width="0.5"/>'
    )
    for i, label in enumerate(shown):
        y = top + i * c
        out.append(
            f'<text x="{left - numbers}" y="{y + c // 2 + 4}" text-anchor="end">'
            f"<title>{_xml(names[i])}</title>{_xml(label)}</text>"
        )
        out.append(
            f'<text x="{left - m // 2}" y="{y + c // 2 + 4}" text-anchor="end">'
            f"{i + 1}</text>"
        )
        loop = cells.get((i, i), 0)
        out.append(
            f'<g class="protee-diagonal" data-index="{i}" data-count="{loop}">'
            f"<title>({i + 1}) {_xml(names[i])}</title>"
            f'<rect x="{left + i * c + 2}" y="{y + 2}" width="{c - 4}"'
            f' height="{c - 4}" fill="{ink}"/>'
            + (
                f'<text x="{left + i * c + c // 2}" y="{y + c // 2 + 4}"'
                f' text-anchor="middle" fill="{_text_on(ink)}">{loop}</text>'
                if loop
                else ""
            )
            + "</g>"
        )
    for (row, col), count in sorted(cells.items()):
        if row == col:
            continue
        x, y = left + col * c, top + row * c
        colour = _FORWARD if row < col else _FEEDBACK
        mark = (
            f'<circle cx="{x + c // 2}" cy="{y + c // 2}" r="7" fill="{colour}"/>'
            if row < col
            else f'<rect x="{x + 5}" y="{y + 5}" width="{c - 10}"'
            f' height="{c - 10}" fill="{colour}"/>'
        )
        if count > 1:
            mark += (
                f'<text x="{x + c // 2}" y="{y + c // 2 + 3}" text-anchor="middle"'
                f' font-size="9" fill="{_text_on(colour)}">{count}</text>'
            )
        edges = "edges" if count > 1 else "edge"
        out.append(
            f'<g class="protee-cell" data-row="{row}" data-col="{col}"'
            f' data-count="{count}"><title>{_xml(names[row])} → {_xml(names[col])}'
            f" ({count} {edges})</title>{mark}</g>"
        )
    out += _matrix_frames(ordered, cells, n, left, top, ink, muted, loops)
    for k, (colour, text) in enumerate(notes):
        y = legend_top + 16 * k + 12
        out.append(
            f'<rect x="{m}" y="{y - 9}" width="10" height="10" fill="{colour}"/>'
        )
        out.append(f'<text x="{m + 16}" y="{y}">{_xml(text)}</text>')
    out.append("</svg>\n")
    return "\n".join(out)


def _matrix_frames(
    ordered: list[tuple[int | float, int, dict[str, Any]]],
    cells: Counter[tuple[int, int]],
    n: int,
    left: int,
    top: int,
    ink: str,
    muted: str,
    loops: bool,
) -> list[str]:
    """The frames of the matrix: blocks of equal order, and loops."""
    c = _CELL
    frames: list[tuple[int, int, str, str, str]] = []
    position = 0
    for _, group in itertools.groupby(ordered, key=lambda t: t[0]):
        size = len(list(group))
        if size > 1:
            frames.append((position, position + size - 1, "protee-tie", muted, "3 2"))
        position += size
    if loops:
        arcs = sorted(cells)
        component = strong_components(Digraph.from_arcs(n, arcs))
        members: dict[int, list[int]] = {}
        for i, k in enumerate(component):
            members.setdefault(k, []).append(i)
        frames += [
            (min(ids), max(ids), "protee-loop", ink, "")
            for ids in members.values()
            if len(ids) > 1
        ]
    out = []
    for first, last, kind, colour, dashes in frames:
        side = (last - first + 1) * c
        dash = f' stroke-dasharray="{dashes}"' if dashes else ""
        out.append(
            f'<rect class="{kind}" x="{left + first * c}" y="{top + first * c}"'
            f' width="{side}" height="{side}" fill="none" stroke="{colour}"'
            f' stroke-width="1.5"{dash}/>'
        )
    return out
