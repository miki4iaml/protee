# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Node-link JSON, CSV and DIMACS formats."""

from pathlib import Path

import networkx as nx
import pytest
from hypothesis import given
from oracles import graphs, problems

from protee import io
from protee.flow import FlowProblem
from protee.graph import Digraph


@given(graph=graphs())
def test_node_link_round_trip_and_networkx(graph: Digraph) -> None:
    cost = list(range(graph.m))
    data = io.to_node_link(
        graph, arcs={"cost": cost}, nodes={"rank": list(range(graph.n))}
    )
    table = io.from_node_link(data)
    assert table.graph == graph
    assert table.arcs.get("cost", ()) == tuple(cost)  # no column without arcs
    assert table.nodes["rank"] == tuple(range(graph.n))
    g = nx.node_link_graph(data, edges="edges")
    assert g.number_of_edges() == graph.m
    assert sorted(g.nodes) == list(range(graph.n))
    back = io.from_node_link(nx.node_link_data(g, edges="edges"))
    assert sorted(back.graph.arcs()) == sorted(graph.arcs())


def test_node_link_files_labels_and_errors(tmp_path: Path) -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 2)], labels=["Vannes", "Ploërmel", "Rennes"])
    path = tmp_path / "g.json"
    io.write_node_link(path, g, arcs={"length": [3, 4]})
    assert "Ploërmel" in path.read_text(encoding="utf-8")
    table = io.read_node_link(path)
    assert table.graph == g
    assert table.arcs["length"] == (3, 4)
    legacy = {
        "directed": True,
        "nodes": [{"id": "a"}, {"id": "b"}],
        "links": [{"source": "a", "target": "b"}],
    }
    assert io.from_node_link(legacy).graph == Digraph.from_arcs(2, [(0, 1)], ["a", "b"])
    with pytest.raises(ValueError, match="directed"):
        io.from_node_link({"directed": False})
    with pytest.raises(ValueError, match="unknown node"):
        io.from_node_link(
            {"directed": True, "nodes": [], "edges": [{"source": 0, "target": 1}]}
        )
    with pytest.raises(ValueError, match="arc column"):
        io.to_node_link(g, arcs={"length": [1]})


def test_csv_round_trip(tmp_path: Path) -> None:
    g = Digraph.from_arcs(3, [(0, 1), (1, 0)], labels=["a", "b", "isolated"])
    path = tmp_path / "arcs.csv"
    io.write_arcs_csv(path, g, {"speed": [50, 90]})
    table = io.read_arcs_csv(path, nodes=["a", "b", "isolated"])
    assert table.graph == g
    assert table.arcs["speed"] == ("50", "90")
    assert io.read_arcs_csv(path).graph.n == 2
    with pytest.raises(ValueError, match="not among the given nodes"):
        io.read_arcs_csv(path, nodes=["a"])


@given(problem=problems(finite=True))
def test_dimacs_round_trip(problem: FlowProblem) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "p.min"
        io.write_dimacs_min(path, problem, comment="generated\nby a test")
        back = io.read_dimacs_min(path)
    sign = 1 if problem.sense == "min" else -1
    assert back.graph.arcs().__class__ is problem.graph.arcs().__class__
    assert list(back.graph.arcs()) == list(problem.graph.arcs())
    assert (back.lower, back.upper, back.supply) == (
        problem.lower,
        problem.upper,
        problem.supply,
    )
    assert back.cost == tuple(sign * c for c in problem.cost)


def test_dimacs_errors(tmp_path: Path) -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    path = tmp_path / "p.min"
    with pytest.raises(ValueError, match="capacity"):
        io.write_dimacs_min(path, FlowProblem(g))
    with pytest.raises(TypeError, match="non-integer"):
        io.write_dimacs_min(path, FlowProblem(g, upper=(1,), cost=(0.5,)))
    for text, message in [
        ("c nothing\n", "no problem line"),
        ("p max 2 1\n", "not a minimum cost flow"),
        ("p min 2 1\nx 1\n", "unknown descriptor"),
        ("p min 2 1\na 1 2 0\n", "line 2"),
    ]:
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            io.read_dimacs_min(path)
