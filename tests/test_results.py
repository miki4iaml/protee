# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The common result model: statuses, certificates, guarantees, fingerprints."""

from __future__ import annotations

import hashlib
import struct
import subprocess
import sys
from types import MappingProxyType

import pytest

import protee
from protee import _fingerprint, flow, paths, results
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
    assert isinstance(r.parameters, MappingProxyType)
    assert isinstance(r.parameters["options"], MappingProxyType)
    assert isinstance(r.counters, MappingProxyType)
    with pytest.raises(TypeError):
        r.counters["pivots"] = 3  # type: ignore[index]
    with pytest.raises(AttributeError):
        r.method = "other"  # type: ignore[misc]


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
