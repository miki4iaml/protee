# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The common result model: statuses, certificates, guarantees, fingerprints."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import pickle
import struct
import subprocess
import sys
from decimal import Decimal
from fractions import Fraction

import numpy as np
import pytest

import protee
from protee import _fingerprint, flow, paths, results, routes
from protee._frozen import FrozenMap
from protee.graph import Digraph
from protee.results import (
    Guarantee,
    GuaranteeKind,
    InfeasibleCut,
    MethodInfo,
    NegativeCycle,
    ResultCore,
    Status,
)

EXACT = Guarantee(GuaranteeKind.EXACT, "optimal")
BOUNDED = Guarantee("bounded", "bound and gap")  # type: ignore[arg-type]
CUT = InfeasibleCut(frozenset({0}), 2, 1, (0,), ())


def test_statuses() -> None:
    assert [s.value for s in Status] == [
        "optimal",
        "feasible",
        "infeasible",
        "unbounded",
        "limit",
    ]


def test_certificates_and_registry_types_are_shared() -> None:
    assert flow.Status is results.Status
    assert flow.InfeasibleCut is results.InfeasibleCut
    assert flow.NegativeCycle is results.NegativeCycle
    assert paths.NegativeCycle is results.NegativeCycle
    assert flow.MethodInfo is results.MethodInfo
    assert CUT.excess == 1


def test_guarantee() -> None:
    assert BOUNDED.kind is GuaranteeKind.BOUNDED
    with pytest.raises(ValueError, match="states what"):
        Guarantee(GuaranteeKind.PROPERTY, "  ")
    with pytest.raises(ValueError, match="not a valid"):
        Guarantee("approximate", "factor 2")  # type: ignore[arg-type]


def test_method_info_is_keyword_only() -> None:
    info = MethodInfo(
        name="m",
        problem="p",
        summary="s",
        guarantee=EXACT,
        complexity="O(m)",
        reference="r",
    )
    assert (info.warm_start, info.options) == (False, ())
    with pytest.raises(TypeError):
        MethodInfo("m", "p", "s", EXACT, "O(m)", "r")  # type: ignore[call-arg]


def test_core_freezes_its_mappings_and_records_the_version() -> None:
    r = ResultCore(
        status="optimal",  # type: ignore[arg-type]
        method="m",
        guarantee=EXACT,
        parameters={"weights": [1, 2], "options": {"k": [3]}},
        counters={"pivots": 2},
    )
    assert r.status is Status.OPTIMAL
    assert r.version == protee.__version__
    assert r.parameters["weights"] == (1, 2)
    assert isinstance(r.parameters, FrozenMap)
    assert isinstance(r.parameters["options"], FrozenMap)
    assert isinstance(r.counters, FrozenMap)
    with pytest.raises(TypeError):
        r.counters["pivots"] = 3  # type: ignore[index]
    with pytest.raises(AttributeError):
        r.method = "other"  # type: ignore[misc]


def test_a_result_is_a_value() -> None:
    # It leaves a worker process (pickle), copies, enters a set, and
    # converts to a dictionary; a pickled result keeps its fingerprint.
    g = Digraph.from_arcs(2, [(0, 1)])
    r = ResultCore(
        status=Status.OPTIMAL,
        method="m",
        guarantee=EXACT,
        parameters={"weights": [1, 2], "options": {"k": [3]}},
        counters={"pivots": 2},
        _sources=(g, (1.0,)),
    )
    unread = pickle.loads(pickle.dumps(r))
    assert unread == r
    assert unread.inputs == r.inputs
    assert pickle.loads(pickle.dumps(r)).inputs == r.inputs
    assert copy.deepcopy(r) == r == copy.copy(r)
    assert {r, copy.deepcopy(r)} == {r}
    assert dataclasses.asdict(r)["counters"] == {"pivots": 2}
    cut = ResultCore(
        status=Status.INFEASIBLE, method="m", guarantee=EXACT, certificate=CUT
    )
    assert hash(pickle.loads(pickle.dumps(cut))) == hash(cut)


def test_frozen_map() -> None:
    m = FrozenMap({"b": 1, "a": (2, 3)})
    assert m == {"a": (2, 3), "b": 1} == FrozenMap([("a", (2, 3)), ("b", 1)])
    assert m != {"a": (2, 3)}
    assert m != [("a", (2, 3)), ("b", 1)]
    assert (len(m), list(m), m["a"]) == (2, ["b", "a"], (2, 3))
    assert hash(m) == hash(FrozenMap({"a": (2, 3), "b": 1}))
    assert repr(m) == "FrozenMap({'b': 1, 'a': (2, 3)})"
    assert repr(FrozenMap()) == "FrozenMap({})"
    nested = FrozenMap({"inner": FrozenMap({"k": 1})})
    for again in (pickle.loads(pickle.dumps(nested)), copy.deepcopy(nested)):
        assert again == nested
        assert isinstance(again["inner"], FrozenMap)
    with pytest.raises(TypeError):
        m["c"] = 4  # type: ignore[index]
    with pytest.raises(AttributeError, match="immutable"):
        m._items = {}
    with pytest.raises(AttributeError, match="immutable"):
        del m._items
    with pytest.raises(TypeError, match="unhashable"):
        hash(FrozenMap({"a": [1]}))


@pytest.mark.parametrize("status", [Status.INFEASIBLE, Status.UNBOUNDED])
def test_a_negative_answer_needs_its_certificate(status: Status) -> None:
    with pytest.raises(ValueError, match="needs a certificate"):
        ResultCore(status=status, method="m", guarantee=EXACT)
    cycle = NegativeCycle((0,), -1)
    r = ResultCore(status=status, method="m", guarantee=EXACT, certificate=cycle)
    assert r.certificate is cycle


def test_a_bounded_method_returns_its_bound_and_gap() -> None:
    with pytest.raises(ValueError, match="bound and its gap"):
        ResultCore(status=Status.FEASIBLE, method="m", guarantee=BOUNDED, bound=3)
    r = ResultCore(
        status=Status.FEASIBLE, method="m", guarantee=BOUNDED, bound=3, gap=0.5
    )
    assert (r.bound, r.gap) == (3, 0.5)
    with pytest.raises(ValueError, match="not negative"):
        ResultCore(status=Status.LIMIT, method="m", guarantee=EXACT, gap=-1)


def test_inputs_are_fingerprinted_once_and_kept() -> None:
    g = Digraph.from_arcs(2, [(0, 1)])
    r = ResultCore(
        status=Status.OPTIMAL, method="m", guarantee=EXACT, _sources=(g, (1.0,))
    )
    assert g._fingerprint == ""
    first = r.inputs
    assert len(first) == 64
    assert g._fingerprint == _fingerprint.graph_fingerprint(g) != ""
    assert r._inputs == first
    assert r.inputs == first
    other = ResultCore(
        status=Status.OPTIMAL, method="m", guarantee=EXACT, _sources=(g, (2.0,))
    )
    assert other == r  # the inputs are not compared, the fields are
    assert other.inputs != first
    renamed = ResultCore(
        status=Status.OPTIMAL, method="n", guarantee=EXACT, _sources=(g, (1.0,))
    )
    assert renamed.inputs != first
    # The same method name, on another problem, is another computation.
    as_flow = flow.FlowResult(
        status=Status.OPTIMAL, method="m", guarantee=EXACT, _sources=(g, (1.0,))
    )
    assert as_flow.inputs != first


def test_graph_fingerprint_is_the_structure() -> None:
    def fp(g: Digraph) -> str:
        return _fingerprint.graph_fingerprint(g)

    g = Digraph.from_arcs(3, [(0, 1), (1, 2)])
    assert fp(g) == fp(Digraph.from_arcs(3, [(0, 1), (1, 2)]))
    assert fp(g) != fp(Digraph.from_arcs(3, [(1, 2), (0, 1)]))
    assert fp(g) != fp(Digraph.from_arcs(4, [(0, 1), (1, 2)]))
    labelled = Digraph(3, (0, 1), (1, 2), ("a", "b", "c"))
    assert fp(labelled) != fp(g)
    assert fp(labelled) != fp(Digraph(3, (0, 1), (1, 2), ("a", "b", "d")))
    assert _fingerprint.fingerprint(g) == _fingerprint.fingerprint(
        Digraph.from_arcs(3, [(0, 1), (1, 2)])
    )


def test_numbers_are_hashed_by_their_little_endian_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fp = _fingerprint.fingerprint
    floats = hashlib.sha256(struct.pack("<2d", 1.0, 2.5)).hexdigest()
    ints = hashlib.sha256(struct.pack("<2q", 1, 2)).hexdigest()
    assert _fingerprint._canonical([1.0, 2.5]) == {"f8": floats}
    assert _fingerprint._canonical((1, 2)) == {"i8": ints}
    assert fp([1.0, 2.5]) == fp((1.0, 2.5))
    assert fp([1, 2]) != fp([1.0, 2.0])
    # Anything else keeps one tagged item per element.
    for mixed in ([1, 2.0], [True, False], [2**70, 1], ["a", "b"], []):
        assert isinstance(_fingerprint._canonical(mixed), list)
    assert fp([1, 2.0]) not in {fp([1, 2]), fp([1.0, 2.0])}
    assert fp([True, False]) != fp([1, 0])
    if sys.byteorder == "little":
        monkeypatch.setattr(sys, "byteorder", "big")
        swapped = hashlib.sha256(struct.pack(">2d", 1.0, 2.5)).hexdigest()
        assert _fingerprint._canonical([1.0, 2.5]) == {"f8": swapped}


def test_fingerprint_without_numpy(monkeypatch: pytest.MonkeyPatch) -> None:
    with_numpy = _fingerprint.fingerprint([1.0, 2], {"a": (3,)})
    monkeypatch.delitem(sys.modules, "numpy", raising=False)
    assert _fingerprint.fingerprint([1.0, 2], {"a": (3,)}) == with_numpy
    assert _fingerprint.freeze({"a": [1]}) == {"a": (1,)}
    with pytest.raises(TypeError, match="no canonical form"):
        _fingerprint.fingerprint(object())


def test_results_and_paths_import_without_numpy() -> None:
    code = (
        "import sys, protee.results, protee.paths, protee.flow; "
        "assert not {'numpy', 'scipy'} & sys.modules.keys(), "
        "sorted({'numpy', 'scipy'} & sys.modules.keys())"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_numpy_scalars_and_exact_numbers_have_canonical_forms() -> None:
    canonical = _fingerprint._canonical
    fp = _fingerprint.fingerprint
    # A float64 is a float: its digits, whatever NumPy's print options.
    assert canonical(np.float64(1.0)) == {"float": "1.0"} == canonical(1.0)
    before = fp(np.float64(0.1), [np.float64(0.5), np.float64(2.0)])
    with np.printoptions(legacy="1.25"):
        assert fp(np.float64(0.1), [np.float64(0.5), np.float64(2.0)]) == before
    # A sequence of float64, as NumPy weights give, is packed like floats.
    assert canonical([np.float64(1.0), 2.5]) == canonical([1.0, 2.5])
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    as_list = paths.dijkstra(g, [1.0, 2.0, 5.0], 0)
    weights = np.array([1.0, 2.0, 5.0])
    assert paths.dijkstra(g, weights, 0).inputs == as_list.inputs  # type: ignore[arg-type]
    # Other NumPy scalars count as the Python number of the same value.
    assert canonical(np.int64(3)) == 3
    assert canonical(np.float32(1.5)) == {"float": "1.5"}
    # Fractions and decimals: exact, tagged forms.
    assert canonical(Fraction(2, 4)) == {"fraction": "1/2"}
    assert canonical(Decimal("0.10")) == {"decimal": "0.10"}
    assert len({fp(Fraction(1, 2)), fp(Decimal("0.5")), fp(0.5), fp("1/2")}) == 4
    halves = [Fraction(1, 2), Fraction(1, 3), Fraction(2)]
    exact = paths.dijkstra(g, halves, 0)  # type: ignore[arg-type]
    expected: tuple[object, ...] = (0, Fraction(1, 2), Fraction(5, 6))
    assert exact.distance == expected
    assert exact.inputs == paths.dijkstra(g, tuple(halves), 0).inputs  # type: ignore[arg-type]
    assert exact.inputs != paths.dijkstra(g, [0.5, 1 / 3, 2.0], 0).inputs
    decimals = [Decimal("0.1"), Decimal("0.2"), Decimal(1)]
    tenths = paths.dijkstra(g, decimals, 0)  # type: ignore[arg-type]
    assert tenths.distance[2] == Decimal("0.3")
    assert len(tenths.inputs) == 64


def test_inputs_without_canonical_form_name_their_type() -> None:
    # The computation accepts any hashable key; its fingerprint cannot.
    g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    r = routes.replacement_paths(g, [1, 1, 5], 0, 2, [0, 1], key=[b"a", b"b", b"c"])
    assert r.status is Status.OPTIMAL
    with pytest.raises(TypeError, match="no canonical form for bytes: supported"):
        assert r.inputs
    # A NumPy scalar without a Python counterpart: an error, not a recursion.
    with pytest.raises(TypeError, match="no canonical form for numpy.longdouble"):
        _fingerprint.fingerprint(np.longdouble(1))
