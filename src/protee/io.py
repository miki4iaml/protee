# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Graph and flow problem formats.

- node-link JSON, the layout of NetworkX's ``node_link_data`` (``nodes``
  and ``edges``; ``links`` is read too), with attribute columns; the
  exchange format ``protee-node-link/0`` (:data:`NODE_LINK_FORMAT`) adds a
  ``graph`` block (producer, prefixes, declared vocabulary), checked by
  :func:`check_node_link`;
- CSV table of arcs, one row per arc;
- DIMACS minimum cost flow format (``p min``), for flow problems.

Files are read and written in UTF-8.

Provisional API (until version 1.0).
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any

from protee.flow._problem import FlowProblem
from protee.graph import Digraph

__all__ = [
    "NODE_LINK_FORMAT",
    "Table",
    "check_node_link",
    "from_node_link",
    "node_link_schema",
    "read_arcs_csv",
    "read_dimacs_min",
    "read_node_link",
    "to_node_link",
    "write_arcs_csv",
    "write_dimacs_min",
    "write_node_link",
]

#: Name and version of the node-link exchange format, in ``graph.format``.
NODE_LINK_FORMAT = "protee-node-link/0"


def _freeze(x: Any) -> Any:
    """A read-only copy: mappings become read-only, lists become tuples."""
    if isinstance(x, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in x.items()})
    if isinstance(x, (list, tuple)):
        return tuple(_freeze(v) for v in x)
    return x


def _thaw(x: Any) -> Any:
    """Plain JSON data from a frozen value."""
    if isinstance(x, Mapping):
        return {k: _thaw(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_thaw(v) for v in x]
    return x


@dataclass(frozen=True, slots=True)
class Table:
    """A graph with attribute columns.

    Attributes
    ----------
    graph : Digraph
    arcs : mapping of str to tuple
        One value per arc for each attribute.
    nodes : mapping of str to tuple
        One value per node for each attribute.
    attributes : mapping of str to object
        The ``graph`` block of a node-link document (format, producer,
        prefixes, vocabulary…), read-only.
    multigraph : bool
        Whether the document allows parallel edges.
    """

    graph: Digraph
    arcs: Mapping[str, tuple[Any, ...]]
    nodes: Mapping[str, tuple[Any, ...]]
    attributes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    multigraph: bool = True


def _check(
    name: str, columns: Mapping[str, Sequence[Any]] | None, size: int
) -> Mapping[str, Sequence[Any]]:
    for key, values in (columns or {}).items():
        if len(values) != size:
            raise ValueError(
                f"{name} column {key!r}: expected {size} values, got {len(values)}"
            )
    return columns or {}


def to_node_link(
    graph: Digraph,
    arcs: Mapping[str, Sequence[Any]] | None = None,
    nodes: Mapping[str, Sequence[Any]] | None = None,
    *,
    attributes: Mapping[str, Any] | None = None,
    multigraph: bool = True,
) -> dict[str, Any]:
    """Node-link dictionary of a graph and its attribute columns.

    Nodes are identified by their labels (or their indices when the graph
    has none). Each edge carries a ``key``: the value of an arc column
    named ``key`` when it is not ``None``, else the smallest integer that
    no other edge between the same two nodes uses. ``null`` is written only
    in the entries of ``prefixes`` and of ``metrics``, where it is a value:
    elsewhere, absent and ``null`` mean the same. An infinite metric is
    written ``"inf"`` or ``"-inf"``, as the format states.

    Parameters
    ----------
    graph : Digraph
    arcs, nodes : mapping of str to sequence, optional
        Attribute columns, one value per arc or per node. A node column
        cannot be named ``id``, nor an arc column ``source`` or ``target``.
    attributes : mapping, optional
        The ``graph`` block (producer, prefixes, vocabulary…); its
        ``format`` is :data:`NODE_LINK_FORMAT`.
    multigraph : bool
        ``False`` declares that no two arcs join the same two nodes.

    Returns
    -------
    dict
        The node-link document, plain JSON data.

    Raises
    ------
    ValueError
        If a column has another size or a reserved name, a key is repeated
        between the same two nodes, ``attributes`` names another format, or
        ``multigraph`` is false while two arcs join the same nodes.
    TypeError
        If a key is not an integer.
    """
    arcs = _check("arc", arcs, graph.m)
    nodes = _check("node", nodes, graph.n)
    if "id" in nodes:
        raise ValueError("a node column cannot be named 'id'")
    if reserved := sorted({"source", "target"} & set(arcs)):
        raise ValueError(f"an arc column cannot be named {reserved[0]!r}")
    block = _without_nulls(_thaw(attributes or {}))
    if block.setdefault("format", NODE_LINK_FORMAT) != NODE_LINK_FORMAT:
        raise ValueError(f"format {block['format']!r} is not {NODE_LINK_FORMAT!r}")
    if not multigraph and len(set(graph.arcs())) < graph.m:
        raise ValueError("parallel arcs in a graph declared not to be a multigraph")
    ident: list[Any] = (
        list(range(graph.n)) if graph.labels is None else list(graph.labels)
    )
    keys = _keys(graph, arcs.get("key"))

    def values(columns: Mapping[str, Sequence[Any]], i: int) -> dict[str, Any]:
        return {
            k: _written(k, _thaw(v[i]))
            for k, v in columns.items()
            if v[i] is not None and k != "key"
        }

    return {
        "directed": True,
        "multigraph": multigraph,
        "graph": {"format": NODE_LINK_FORMAT, **block},
        "nodes": [{"id": ident[v], **values(nodes, v)} for v in range(graph.n)],
        "edges": [
            {"source": ident[t], "target": ident[h], "key": keys[a], **values(arcs, a)}
            for a, (t, h) in enumerate(graph.arcs())
        ],
    }


#: Keys whose entries keep ``null`` as a value.
_NULL_VALUED = frozenset({"prefixes", "metrics"})


def _without_nulls(x: Any, keep: bool = False) -> Any:
    """JSON data without the ``null`` of optional keys (``keep`` keeps them)."""
    if isinstance(x, Mapping):
        return {
            k: _without_nulls(v, k in _NULL_VALUED)
            for k, v in x.items()
            if keep or v is not None
        }
    if isinstance(x, list):
        return [_without_nulls(v) for v in x]
    return x


def _written(key: str, value: Any) -> Any:
    """An attribute as written: no optional null, infinite metrics as text."""
    value = _without_nulls(value, key in _NULL_VALUED)
    if key == "metrics" and isinstance(value, dict):
        return {
            name: ("inf" if v > 0 else "-inf")
            if isinstance(v, float) and math.isinf(v)
            else v
            for name, v in value.items()
        }
    return value


def _keys(graph: Digraph, given: Sequence[Any] | None) -> list[int]:
    """The key of each arc: the one given, else the smallest one free."""
    keys: list[int | None] = list(given) if given is not None else [None] * graph.m
    used: dict[tuple[int, int], set[int]] = {}
    for a, (pair, key) in enumerate(zip(graph.arcs(), keys, strict=True)):
        if key is None:
            continue
        if isinstance(key, bool) or not isinstance(key, int):
            raise TypeError(f"arc {a}: key {key!r} is not an integer")
        if key in used.setdefault(pair, set()):
            raise ValueError(f"arc {a}: key {key} is repeated between the same nodes")
        used[pair].add(key)
    out = []
    for pair, key in zip(graph.arcs(), keys, strict=True):
        if key is None:
            taken = used.setdefault(pair, set())
            key = next(k for k in itertools.count() if k not in taken)
            taken.add(key)
        out.append(key)
    return out


def from_node_link(data: Mapping[str, Any]) -> Table:
    """Graph and attribute columns of a node-link dictionary.

    Arcs are numbered in the order of the edges in the data. Their ``key``
    values, which tell apart the edges between the same two nodes, are kept
    in the arc column ``key``. A node attribute or an edge attribute missing
    somewhere is ``None`` there. The ``graph`` block is kept, read-only, in
    :attr:`Table.attributes`; it is not checked (see :func:`check_node_link`).
    Node identifiers become the labels of the graph, as texts, except
    integer identifiers that are exactly 0 to n - 1 in order, which stay the
    node indices.

    Parameters
    ----------
    data : mapping
        A decoded node-link document.

    Returns
    -------
    Table

    Raises
    ------
    ValueError
        If the data is not directed, an edge refers to an unknown node, or
        two identifiers write the same text (``1`` and ``"1"``).
    KeyError
        If a node has no ``id``.
    """
    if not data.get("directed", False):
        raise ValueError("protee graphs are directed: 'directed' must be true")
    raw_nodes = list(data.get("nodes", []))
    raw_edges = list(data.get("edges", data.get("links", [])))
    ids = [node["id"] for node in raw_nodes]
    numeric = ids == list(range(len(ids)))
    labels = None if numeric else tuple(str(i) for i in ids)
    index = {i: v for v, i in enumerate(ids)}
    arcs = []
    for e in raw_edges:
        try:
            arcs.append((index[e["source"]], index[e["target"]]))
        except KeyError as err:
            raise ValueError(f"edge {e!r} refers to an unknown node") from err
    graph = Digraph.from_arcs(len(ids), arcs, labels)
    node_keys = sorted({k for node in raw_nodes for k in node if k != "id"})
    edge_keys = sorted(
        {k for e in raw_edges for k in e if k not in ("source", "target")}
    )
    return Table(
        graph,
        MappingProxyType(
            {k: tuple(_freeze(e.get(k)) for e in raw_edges) for k in edge_keys}
        ),
        MappingProxyType(
            {k: tuple(_freeze(node.get(k)) for node in raw_nodes) for k in node_keys}
        ),
        _freeze(data.get("graph") or {}),
        bool(data.get("multigraph", True)),
    )


def write_node_link(
    path: Path,
    graph: Digraph,
    arcs: Mapping[str, Sequence[Any]] | None = None,
    nodes: Mapping[str, Sequence[Any]] | None = None,
    *,
    attributes: Mapping[str, Any] | None = None,
    multigraph: bool = True,
) -> None:
    """Write :func:`to_node_link` as a JSON file, in UTF-8 with LF line ends.

    The file is strict JSON: a NaN, or an infinity outside ``metrics``, is
    refused. NumPy scalars are written as the numbers they hold.

    Parameters
    ----------
    path : Path
    graph, arcs, nodes, attributes, multigraph
        As :func:`to_node_link`.

    Raises
    ------
    ValueError
        As :func:`to_node_link`, or for a value that JSON cannot hold.
    TypeError
        For a value that is not JSON data.
    """
    data = to_node_link(
        graph, arcs, nodes, attributes=attributes, multigraph=multigraph
    )
    text = json.dumps(
        data, ensure_ascii=False, indent=1, allow_nan=False, default=_scalar
    )
    Path(path).write_text(text + "\n", encoding="utf-8", newline="\n")


def _scalar(value: object) -> Any:
    """The Python number of a NumPy scalar, for JSON."""
    item = getattr(value, "item", None)
    if callable(item) and getattr(value, "shape", None) == ():
        return item()
    raise TypeError(f"{type(value).__name__} is not JSON data")


def _not_json(token: str) -> Any:
    raise ValueError(f"{token} is not JSON: write 'inf', '-inf' or null")


def read_node_link(path: Path) -> Table:
    """Read a node-link JSON file (see :func:`from_node_link`).

    Parameters
    ----------
    path : Path

    Returns
    -------
    Table

    Raises
    ------
    ValueError
        If the file is not strict JSON (``NaN``, ``Infinity``), or as
        :func:`from_node_link`.
    """
    text = Path(path).read_text(encoding="utf-8")
    return from_node_link(json.loads(text, parse_constant=_not_json))


#: Keys whose values cannot be declared in ``graph.vocabulary``.
_STRUCTURAL = frozenset({"id", "source", "target", "key"})

#: A language tag (BCP 47): a language, then subtags such as a region; or a
#: private use (``x-…``) or grandfathered (``i-…``) tag.
_LANGUAGE = re.compile(
    r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*|[xXiI](?:-[A-Za-z0-9]{1,8})+"
)
#: The start of an absolute IRI: its scheme, then a colon (as the schema).
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


def _absolute(iri: object) -> bool:
    return isinstance(iri, str) and _SCHEME.match(iri) is not None


def _metric(value: object) -> bool:
    if value is None or value in ("inf", "-inf"):
        return True
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and math.isfinite(value))


def _node_id(value: object) -> bool:
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def _text_or_null(value: object) -> bool:
    """An optional text: absent and null mean the same."""
    return value is None or isinstance(value, str)


class _Checker:
    """The rules of :func:`check_node_link`, one method per part."""

    def __init__(self) -> None:
        self.problems: list[str] = []
        self.prefixes: Mapping[str, Any] = {}
        # attribute -> "node" or "edge" -> declared values
        self.declared: dict[str, dict[str, set[str]]] = {}

    def bad(self, where: str, what: str) -> None:
        self.problems.append(f"{where}: {what}")

    def identifier(self, where: str, ident: object) -> bool:
        if not isinstance(ident, str) or not ident:
            self.bad(where, "an identifier is a non-empty text")
            return False
        prefix = ident.split(":", 1)[0]
        if ":" in ident and prefix not in self.prefixes:
            self.bad(where, f"prefix {prefix!r} is not declared in graph.prefixes")
        return True

    def header(self, data: Mapping[str, Any]) -> Mapping[str, Any]:
        if data.get("directed") is not True:
            self.bad("directed", "must be true")
        if not isinstance(data.get("multigraph"), bool):
            self.bad("multigraph", "must be true or false")
        block = data.get("graph")
        if not isinstance(block, Mapping):
            self.bad("graph", "missing, or not an object")
            return {}
        if block.get("format") != NODE_LINK_FORMAT:
            self.bad("graph.format", f"must be {NODE_LINK_FORMAT!r}")
        for key in ("label", "description"):
            if block.get(key) is not None and not isinstance(block[key], str):
                self.bad(f"graph.{key}", "must be a text")
        language = block.get("language")
        if language is not None and not (
            isinstance(language, str) and _LANGUAGE.fullmatch(language)
        ):
            self.bad("graph.language", "must be a language tag, such as 'en'")
        producer = block.get("producer")
        if producer is not None and not (
            isinstance(producer, Mapping)
            and isinstance(producer.get("name"), str)
            and _text_or_null(producer.get("version"))
        ):
            self.bad("graph.producer", "an object with a text 'name' and 'version'")
        return block

    def prefix_table(self, block: Mapping[str, Any]) -> None:
        prefixes = block.get("prefixes")
        if prefixes is None:  # absent or null: the same
            prefixes = {}
        if not isinstance(prefixes, Mapping):
            self.bad("graph.prefixes", "must be an object")
            return
        self.prefixes = prefixes
        for prefix, iri in prefixes.items():
            where = f"graph.prefixes[{prefix!r}]"
            if not prefix or ":" in prefix:
                self.bad(where, "a prefix is a non-empty name without ':'")
            if iri is not None and not _absolute(iri):
                self.bad(where, "must be an absolute IRI, or null")

    def vocabulary(self, block: Mapping[str, Any]) -> None:
        vocabulary = block.get("vocabulary")
        if vocabulary is None:  # absent or null: the same
            vocabulary = {}
        if not isinstance(vocabulary, Mapping):
            self.bad("graph.vocabulary", "must be an object")
            return
        for attribute, entries in vocabulary.items():
            where = f"graph.vocabulary[{attribute!r}]"
            if attribute in _STRUCTURAL:
                self.bad(where, "the values of a structural key are not declared")
                continue
            if entries is None:  # absent or null: the same
                continue
            if not isinstance(entries, list):
                self.bad(where, "must be a list")
                continue
            sets = self.declared.setdefault(attribute, {"node": set(), "edge": set()})
            for i, entry in enumerate(entries):
                self.declaration(f"{where}[{i}]", entry, sets)

    def declaration(self, where: str, entry: object, sets: dict[str, set[str]]) -> None:
        if not isinstance(entry, Mapping):
            self.bad(where, "must be an object")
            return
        on = entry.get("on")
        if on not in ("node", "edge"):
            self.bad(where, "'on' must be 'node' or 'edge'")
            return
        if not isinstance(entry.get("label"), str):
            self.bad(where, "needs a text 'label'")
        if not _text_or_null(entry.get("description")):
            self.bad(where, "'description' must be a text")
        if entry.get("symmetric") is not None and (
            on != "edge" or not isinstance(entry["symmetric"], bool)
        ):
            self.bad(where, "'symmetric' is a boolean, for edges only")
        ident = entry.get("id")
        if self.identifier(f"{where}.id", ident):
            assert isinstance(ident, str)
            if ident in sets[on]:
                self.bad(where, f"{ident!r} is declared twice for {on}s")
            sets[on].add(ident)

    def common(self, where: str, item: Mapping[str, Any], on: str) -> None:
        # The format defines description, family and url for nodes only: on
        # an edge, they are free keys.
        texts = (
            ("label", "description", "family", "url") if on == "node" else ("label",)
        )
        for key in texts:
            if item.get(key) is not None and not isinstance(item[key], str):
                self.bad(f"{where}.{key}", "must be a text")
        metrics = item.get("metrics")
        if metrics is not None and not isinstance(metrics, Mapping):
            self.bad(f"{where}.metrics", "must be an object")
        elif metrics is not None:
            for name, value in metrics.items():
                if not _metric(value):
                    self.bad(
                        f"{where}.metrics[{name!r}]",
                        "must be a finite number, 'inf', '-inf' or null",
                    )
        for attribute, sets in self.declared.items():
            value = item.get(attribute)
            if value is not None and not (isinstance(value, str) and value in sets[on]):
                self.bad(
                    f"{where}.{attribute}",
                    f"{value!r} is not declared for {on}s in "
                    f"graph.vocabulary[{attribute!r}]",
                )

    def nodes(self, raw: object) -> set[Any]:
        ids: set[Any] = set()
        if not isinstance(raw, list):
            self.bad("nodes", "missing, or not a list")
            return ids
        for i, node in enumerate(raw):
            where = f"nodes[{i}]"
            if not isinstance(node, Mapping):
                self.bad(where, "must be an object")
                continue
            ident = node.get("id")
            if not _node_id(ident):
                self.bad(f"{where}.id", "must be a text or an integer")
            elif ident in ids:
                self.bad(f"{where}.id", f"{ident!r} is repeated")
            else:
                ids.add(ident)
            if node.get("iri") is not None and not _absolute(node["iri"]):
                self.bad(f"{where}.iri", "must be an absolute IRI")
            self.common(where, node, "node")
        return ids

    def edges(self, raw: object, ids: set[Any], multigraph: object) -> None:
        if not isinstance(raw, list):
            self.bad("edges", "missing, or not a list")
            return
        keys: dict[tuple[Any, Any], set[int]] = {}
        for i, edge in enumerate(raw):
            where = f"edges[{i}]"
            if not isinstance(edge, Mapping):
                self.bad(where, "must be an object")
                continue
            ends = edge.get("source"), edge.get("target")
            for name, end in zip(("source", "target"), ends, strict=True):
                if not (_node_id(end) and end in ids):
                    self.bad(f"{where}.{name}", f"{end!r} is not a node id")
            key = edge.get("key")
            if key is not None and (isinstance(key, bool) or not isinstance(key, int)):
                self.bad(f"{where}.key", "must be an integer")
                key = None
            if not all(_node_id(end) for end in ends):
                self.common(where, edge, "edge")
                continue
            pair = (ends[0], ends[1])
            if pair in keys and multigraph is False:
                self.bad(
                    where,
                    f"a second edge from {pair[0]!r} to {pair[1]!r}, "
                    "in a graph that is not a multigraph",
                )
            seen = keys.setdefault(pair, set())
            if key is not None and key in seen:
                self.bad(
                    f"{where}.key",
                    f"{key} is repeated from {pair[0]!r} to {pair[1]!r}",
                )
            elif key is not None:
                seen.add(key)
            self.common(where, edge, "edge")


def check_node_link(data: object) -> tuple[str, ...]:
    """The departures of a document from the ``protee-node-link/0`` format.

    The rules are those of the exchange contract: a directed graph; a
    ``graph`` block with its ``format``, an optional language tag, declared
    prefixes; for every attribute declared in ``graph.vocabulary``
    (``type``, ``status``, ``role``…), each value used by a node or an edge
    declared there, for nodes or for edges, a declared value being
    ``prefix:name`` with a declared prefix or a plain name; unique node
    identifiers, opaque texts (an IRI is allowed) or integers, never
    expanded; edges between existing nodes, with integer keys unique
    between the same two nodes; metrics that are finite numbers, ``"inf"``,
    ``"-inf"`` or ``null``. Other keys are allowed. ``links`` is read in
    place of ``edges``.

    Parameters
    ----------
    data : object
        The decoded JSON document.

    Returns
    -------
    tuple of str
        One message per departure, each starting with where it is; empty
        when the document follows the format.
    """
    checker = _Checker()
    if not isinstance(data, Mapping):
        return ("document: must be a JSON object",)
    block = checker.header(data)
    checker.prefix_table(block)
    checker.vocabulary(block)
    ids = checker.nodes(data.get("nodes"))
    checker.edges(data.get("edges", data.get("links")), ids, data.get("multigraph"))
    return tuple(checker.problems)


def node_link_schema() -> dict[str, Any]:
    """The JSON Schema (2020-12) of the structure of ``protee-node-link/0``.

    The schema is shipped in the package
    (``protee/schemas/protee-node-link-0.schema.json``), for the consumers
    that check a document without protee. It checks the required keys, the
    types and the allowed values. The rules that cross parts of a document
    (declared values and prefixes, unique node identifiers, edges between
    existing nodes, unique keys) are checked by :func:`check_node_link`
    only: a document that it accepts passes the schema.

    Returns
    -------
    dict
        The decoded schema, a new object at each call.
    """
    path = files("protee").joinpath("schemas", "protee-node-link-0.schema.json")
    schema: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return schema


def write_arcs_csv(
    path: Path, graph: Digraph, arcs: Mapping[str, Sequence[Any]] | None = None
) -> None:
    """Write one row per arc: ``tail``, ``head``, then the attribute columns.

    Nodes are written by label (by index when the graph has none). Isolated
    nodes do not appear: pass their labels to :func:`read_arcs_csv`.
    """
    arcs = _check("arc", arcs, graph.m)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["tail", "head", *arcs])
        for a, (t, h) in enumerate(graph.arcs()):
            writer.writerow(
                [graph.label(t), graph.label(h), *(vals[a] for vals in arcs.values())]
            )


def read_arcs_csv(path: Path, nodes: Sequence[str] | None = None) -> Table:
    """Read a table of arcs with columns ``tail`` and ``head``.

    Parameters
    ----------
    path : Path
    nodes : sequence of str, optional
        Node labels, in the order of their indices; it may list isolated
        nodes. By default, the labels in order of first appearance.

    Returns
    -------
    Table
        Attribute values are strings, as read; convert them as needed.
    """
    with Path(path).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    labels = list(nodes) if nodes is not None else []
    index = {label: v for v, label in enumerate(labels)}
    if nodes is None:
        for row in rows:
            for label in (row["tail"], row["head"]):
                if label not in index:
                    index[label] = len(labels)
                    labels.append(label)
    try:
        pairs = [(index[row["tail"]], index[row["head"]]) for row in rows]
    except KeyError as err:
        raise ValueError(f"node {err.args[0]!r} is not among the given nodes") from err
    keys = [k for k in (rows[0] if rows else {}) if k not in ("tail", "head")]
    graph = Digraph.from_arcs(len(labels), pairs, labels)
    return Table(
        graph,
        MappingProxyType({k: tuple(row[k] for row in rows) for k in keys}),
        MappingProxyType({}),
    )


def write_dimacs_min(path: Path, problem: FlowProblem, comment: str = "") -> None:
    """Write a flow problem in the DIMACS minimum cost flow format.

    Nodes are numbered from 1. A maximization is written with negated
    costs, since the format minimizes.

    Raises
    ------
    ValueError
        If an arc has no upper bound (the format needs a capacity).
    TypeError
        If a cost is not an integer.
    """
    g = problem.graph
    sign = 1 if problem.sense == "min" else -1
    lines = [f"c {line}" for line in comment.splitlines()]
    lines.append(f"p min {g.n} {g.m}")
    lines += [f"n {v + 1} {b}" for v, b in enumerate(problem.supply) if b]
    for a, (t, h) in enumerate(g.arcs()):
        hi, c = problem.upper[a], problem.cost[a]
        if hi is None:
            raise ValueError(f"arc {a} has no upper bound: DIMACS needs a capacity")
        if not isinstance(c, int):
            raise TypeError(
                f"arc {a} has a non-integer cost {c!r}: DIMACS costs are integers"
            )
        lines.append(f"a {t + 1} {h + 1} {problem.lower[a]} {hi} {sign * c}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def read_dimacs_min(path: Path) -> FlowProblem:
    """Read a DIMACS minimum cost flow file (``p min``).

    Raises
    ------
    ValueError
        If the file is malformed.
    """
    n = -1
    supply: list[int] = []
    arcs: list[tuple[int, int]] = []
    lower: list[int] = []
    upper: list[int | None] = []
    cost: list[int] = []
    for number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        fields = line.split()
        if not fields or fields[0] == "c":
            continue
        try:
            if fields[0] == "p":
                if fields[1] != "min":
                    raise ValueError(f"line {number}: not a minimum cost flow problem")
                n = int(fields[2])
                supply = [0] * n
            elif fields[0] == "n":
                v = int(fields[1])
                if not 1 <= v <= n:
                    raise ValueError(f"node {v} outside 1..{n}")
                supply[v - 1] = int(fields[2])
            elif fields[0] == "a":
                t, h, lo, hi, c = (int(x) for x in fields[1:6])
                arcs.append((t - 1, h - 1))
                lower.append(lo)
                upper.append(hi)
                cost.append(c)
            else:
                raise ValueError(f"line {number}: unknown descriptor {fields[0]!r}")
        except (IndexError, ValueError) as err:
            raise ValueError(f"line {number}: {line!r}: {err}") from err
    if n < 0:
        raise ValueError("no problem line 'p min n m'")
    return FlowProblem(
        Digraph.from_arcs(n, arcs), lower=lower, upper=upper, cost=cost, supply=supply
    )
