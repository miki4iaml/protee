# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The immutable directed multigraph, and the lazy package."""

import subprocess
import sys

import pytest
from hypothesis import given
from oracles import graphs

import protee
from protee.graph import Digraph


@given(graph=graphs())
def test_adjacency_lists_every_arc_once(graph: Digraph) -> None:
    for v in range(graph.n):
        assert all(graph.tails[a] == v for a in graph.out_arcs(v))
        assert all(graph.heads[a] == v for a in graph.in_arcs(v))
        assert list(graph.out_arcs(v)) == sorted(graph.out_arcs(v))
        assert graph.degree(v) == graph.out_degree(v) + graph.in_degree(v)
    assert sorted(a for v in range(graph.n) for a in graph.out_arcs(v)) == list(
        range(graph.m)
    )
    assert sorted(a for v in range(graph.n) for a in graph.in_arcs(v)) == list(
        range(graph.m)
    )
    rev = graph.reverse()
    assert all(rev.arc(a) == (h, t) for a, (t, h) in enumerate(graph.arcs()))


def test_parallel_arcs_loops_and_labels() -> None:
    g = Digraph.from_arcs(2, [(0, 1), (0, 1), (1, 1)], labels=["a", "b"])
    assert g.m == 3
    assert g.out_arcs(0) == (0, 1)
    assert g.in_arcs(1) == (0, 1, 2)
    assert g.degree(1) == 4
    assert (g.node("b"), g.label(1)) == (1, "b")
    assert g == Digraph.from_arcs(2, [(0, 1), (0, 1), (1, 1)], labels=["a", "b"])
    assert hash(g) == hash(Digraph(2, (0, 0, 1), (1, 1, 1), ("a", "b")))
    plain = Digraph.from_arcs(3, [])
    assert (plain.label(2), plain.node("2")) == ("2", 2)
    with pytest.raises(KeyError):
        plain.node("7")
    for wrong in ("x", "01", " 1", "+1", "1_0", "١"):
        with pytest.raises(KeyError):
            plain.node(wrong)
    with pytest.raises(KeyError):
        g.node("c")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((-1, (), ()), "non-negative"),
        ((2, (0,), ()), "same length"),
        ((2, (0,), (2,)), "outside"),
        ((2, (), (), ("a",)), "one label per node"),
        ((2, (), (), ("a", "a")), "repeated"),
    ],
)
def test_invalid_graphs_are_refused(args: tuple[object, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Digraph(*args)  # type: ignore[arg-type]


def test_frozen() -> None:
    g = Digraph.from_arcs(1, [(0, 0)])
    with pytest.raises(AttributeError):
        g.n = 2  # type: ignore[misc]


def test_import_is_light_and_submodules_load_on_demand() -> None:
    code = (
        "import sys, protee; assert 'protee.flow' not in sys.modules; "
        "protee.flow; assert 'protee.flow' in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    assert "flow" in dir(protee)
    with pytest.raises(AttributeError, match="no attribute"):
        protee.nothing  # noqa: B018


def test_inputs_are_copied() -> None:
    tails, heads = [0, 1], [1, 0]
    g = Digraph(2, tails, heads)  # type: ignore[arg-type]
    tails[0] = 1
    assert g.tails == (0, 1)
    assert g.out_arcs(0) == (0,)
    assert hash(g) == hash(Digraph(2, (0, 1), (1, 0)))
