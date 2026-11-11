# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Graph and flow problem formats.

- node-link JSON, the layout of NetworkX's ``node_link_data`` (``nodes``
  and ``edges``; ``links`` is read too), with attribute columns;
- CSV table of arcs, one row per arc;
- DIMACS minimum cost flow format (``p min``), for flow problems.

Files are read and written in UTF-8.

Provisional API (until version 1.0).
"""

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from protee.flow._problem import FlowProblem
from protee.graph import Digraph

__all__ = [
    "Table",
    "from_node_link",
    "read_arcs_csv",
    "read_dimacs_min",
    "read_node_link",
    "to_node_link",
    "write_arcs_csv",
    "write_dimacs_min",
    "write_node_link",
]


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
    """

    graph: Digraph
    arcs: Mapping[str, tuple[Any, ...]]
    nodes: Mapping[str, tuple[Any, ...]]


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
) -> dict[str, Any]:
    """Node-link dictionary of a graph and its attribute columns.

    Nodes are identified by their labels (or their indices when the graph
    has none); each edge carries a ``key``, its arc index.
    """
    arcs = _check("arc", arcs, graph.m)
    nodes = _check("node", nodes, graph.n)
    ident: list[Any] = (
        list(range(graph.n)) if graph.labels is None else list(graph.labels)
    )
    return {
        "directed": True,
        "multigraph": True,
        "graph": {},
        "nodes": [
            {"id": ident[v], **{k: vals[v] for k, vals in nodes.items()}}
            for v in range(graph.n)
        ],
        "edges": [
            {
                "source": ident[t],
                "target": ident[h],
                "key": a,
                **{k: vals[a] for k, vals in arcs.items()},
            }
            for a, (t, h) in enumerate(graph.arcs())
        ],
    }


def from_node_link(data: Mapping[str, Any]) -> Table:
    """Graph and attribute columns of a node-link dictionary.

    Edges are taken in the order of their ``key`` when every edge has an
    integer one, in file order otherwise. A node attribute or an edge
    attribute missing somewhere is ``None`` there.

    Raises
    ------
    ValueError
        If the data is not directed, or an edge refers to an unknown node.
    """
    if not data.get("directed", False):
        raise ValueError("protee graphs are directed: 'directed' must be true")
    raw_nodes = list(data.get("nodes", []))
    raw_edges = list(data.get("edges", data.get("links", [])))
    ids = [node["id"] for node in raw_nodes]
    numeric = ids == list(range(len(ids)))
    labels = None if numeric else tuple(str(i) for i in ids)
    index = {i: v for v, i in enumerate(ids)}
    if all(isinstance(e.get("key"), int) for e in raw_edges):
        raw_edges.sort(key=lambda e: e["key"])
    arcs = []
    for e in raw_edges:
        try:
            arcs.append((index[e["source"]], index[e["target"]]))
        except KeyError as err:
            raise ValueError(f"edge {e!r} refers to an unknown node") from err
    graph = Digraph.from_arcs(len(ids), arcs, labels)
    node_keys = sorted({k for node in raw_nodes for k in node if k != "id"})
    edge_keys = sorted(
        {k for e in raw_edges for k in e if k not in ("source", "target", "key")}
    )
    return Table(
        graph,
        MappingProxyType({k: tuple(e.get(k) for e in raw_edges) for k in edge_keys}),
        MappingProxyType(
            {k: tuple(node.get(k) for node in raw_nodes) for k in node_keys}
        ),
    )


def write_node_link(
    path: Path,
    graph: Digraph,
    arcs: Mapping[str, Sequence[Any]] | None = None,
    nodes: Mapping[str, Sequence[Any]] | None = None,
) -> None:
    """Write :func:`to_node_link` as a JSON file."""
    text = json.dumps(to_node_link(graph, arcs, nodes), ensure_ascii=False, indent=1)
    Path(path).write_text(text + "\n", encoding="utf-8")


def read_node_link(path: Path) -> Table:
    """Read a node-link JSON file (see :func:`from_node_link`)."""
    return from_node_link(json.loads(Path(path).read_text(encoding="utf-8")))


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
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


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
                supply[int(fields[1]) - 1] = int(fields[2])
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
