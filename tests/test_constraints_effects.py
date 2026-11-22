# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Arc data, evaluation of requirements into effects, and composition."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from constraints_cases import (
    CLASS,
    ELEMENTS,
    HEIGHT,
    MASS,
    PARAMETERS,
    REG,
    ROUTING,
    SPEED,
    VERDICT_REQUIREMENTS,
    ZONE,
    oracle_verdict,
    random_case,
    requirement,
    requirement_set,
    resolved,
    value,
)
from hypothesis import given
from hypothesis import strategies as st

from protee.constraints import (
    ArcData,
    Attribute,
    Effect,
    EffectKind,
    Reason,
    RequirementSet,
    ResolvedValues,
    UnknownPolicy,
    ValueSet,
    Verdict,
    compose,
    evaluate,
    resolve_values,
)
from protee.graph import Digraph

LINE = Digraph.from_arcs(4, [(0, 1), (1, 2), (2, 3)])


def effect(rid: str, kind: EffectKind, m: int, **arrays: Any) -> Effect:
    """An effect built from lists (the API takes NumPy arrays)."""
    converted: dict[str, Any] = {
        k: v if isinstance(v, str) else np.asarray(v) for k, v in arrays.items()
    }
    return Effect(rid, kind, m, **converted)


def line_data(**columns: list[float | None]) -> ArcData:
    return ArcData(3, tuple(Attribute.numeric(k, v) for k, v in columns.items()))


# Arc data ---------------------------------------------------------------


def test_numeric_attribute_marks_unknown_and_is_read_only() -> None:
    a = Attribute.numeric(
        "mass_limit", [40, None, 60.5], unit="t", derived=True, quality="lower bound"
    )
    assert np.isnan(a.values[1])
    assert a.known.tolist() == [True, False, True]
    assert a.derived
    assert a.quality == "lower bound"
    with pytest.raises(ValueError, match="read-only"):
        a.values[0] = 1.0
    with pytest.raises(TypeError, match="not a number"):
        Attribute.numeric("x", ["40"])  # type: ignore[list-item]


def test_categorical_attribute_keeps_declared_order() -> None:
    a = Attribute.categorical("element", ["bridge", None, "road"], ELEMENTS)
    assert a.values.tolist() == [1, -1, 0]
    assert a.labels == ELEMENTS
    assert a.known.tolist() == [True, False, True]
    with pytest.raises(ValueError, match="is not one of"):
        Attribute.categorical("element", ["ferry"], ELEMENTS)


def test_attribute_checks_raw_arrays() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Attribute.numeric("", [])
    with pytest.raises(ValueError, match="one value per arc"):
        Attribute("x", np.zeros((2, 2)))
    with pytest.raises(TypeError, match="float64"):
        Attribute("x", np.zeros(2, dtype=np.int32))
    with pytest.raises(TypeError, match="int32"):
        Attribute("x", np.zeros(2), labels=("a",))
    with pytest.raises(ValueError, match="labels repeat"):
        Attribute("x", np.zeros(2, dtype=np.int32), labels=("a", "a"))
    with pytest.raises(ValueError, match="out of range"):
        Attribute("x", np.array([0, 3], dtype=np.int32), labels=("a", "b"))


def test_arc_data_columns_and_scope() -> None:
    element = Attribute.categorical("element", ["bridge", None, "road"], ELEMENTS)
    data = ArcData(3, (element, Attribute.numeric("len", [1, 2, 3])), element="element")
    assert "len" in data
    assert "other" not in data
    assert [a.name for a in data] == ["element", "len"]
    assert data.in_scope(None).tolist() == [True, True, True]
    # An unknown element is never presumed out of scope.
    assert data.in_scope(frozenset({"bridge"})).tolist() == [True, True, False]
    assert data.element_labels() == ("bridge", None, "road")
    assert data.scope_unknown(frozenset({"bridge"})).tolist() == [False, True, False]
    assert data.scope_unknown(None).tolist() == [False, False, False]
    with pytest.raises(ValueError, match=r"scope labels \['ferry'\]"):
        data.in_scope(frozenset({"ferry"}))
    with pytest.raises(ValueError, match="not elements"):
        data.scope_unknown(frozenset({"ferry", "bridge"}))
    # Without an element column, every element is unknown.
    plain = ArcData(3, (Attribute.numeric("len", [1, 2, 3]),))
    assert plain.in_scope(frozenset({"bridge"})).tolist() == [True, True, True]
    assert plain.scope_unknown(frozenset({"bridge"})).tolist() == [True, True, True]
    assert plain.element_labels() == (None, None, None)
    with pytest.raises(ValueError, match="duplicate attribute"):
        ArcData(3, (element, element))
    with pytest.raises(ValueError, match="expected 4 values"):
        ArcData(4, (element,))
    with pytest.raises(ValueError, match="not a category column"):
        ArcData(3, (Attribute.numeric("len", [1, 2, 3]),), element="len")
    with pytest.raises(ValueError, match="non-negative integer"):
        ArcData(True, ())


# Evaluation -------------------------------------------------------------


@pytest.mark.parametrize("seed", range(12))
def test_routing_verdicts_match_the_oracle(seed: int) -> None:
    case = random_case(seed)
    data = case.data()
    vals = resolved()
    effects = [evaluate(r, case.graph, data, vals) for r in VERDICT_REQUIREMENTS]
    view = compose(case.graph, effects, policy=UnknownPolicy.ADMIT_AND_COUNT)
    expected = [oracle_verdict(case, a) for a in range(case.graph.m)]
    assert view.verdict.tolist() == expected
    assert view.unknown_count == expected.count(Verdict.UNKNOWN)


def test_threshold_verdicts_and_reasons() -> None:
    element = Attribute.categorical("element", ["bridge", "bridge", "road"], ELEMENTS)
    limit = Attribute.numeric("mass_limit", [40, None, 10])
    data = ArcData(3, (element, limit), element="element")
    e = evaluate(MASS, LINE, data, resolved(requirement_set((MASS,)), mass=40.0))
    assert e.kind is EffectKind.VERDICT
    assert e.verdict is not None
    assert e.reasons is not None
    assert e.verdict.tolist() == [Verdict.PASS, Verdict.UNKNOWN, Verdict.PASS]
    assert e.reasons.tolist() == [
        Reason.SATISFIED,
        Reason.MISSING_DATA,
        Reason.OUT_OF_SCOPE,
    ]
    heavy = evaluate(MASS, LINE, data, resolved(requirement_set((MASS,)), mass=40.5))
    assert heavy.verdict is not None
    assert heavy.verdict[0] == Verdict.FAIL
    assert heavy.reasons is not None
    assert heavy.reasons[0] == Reason.VIOLATED


def test_missing_attribute_gives_unknown_in_scope() -> None:
    data = ArcData(
        3,
        (Attribute.categorical("element", ["bridge", "road", None], ELEMENTS),),
        element="element",
    )
    e = evaluate(MASS, LINE, data, resolved())
    assert e.verdict is not None
    assert e.verdict.tolist() == [Verdict.UNKNOWN, Verdict.PASS, Verdict.UNKNOWN]


def test_value_to_be_set_makes_the_effect_not_applicable() -> None:
    # A5: a value to be set is never decided silently.
    e = evaluate(MASS, LINE, line_data(mass_limit=[1, 2, 3]), resolved(mass=None))
    assert e.not_applicable == "value of 'vehicle_mass' to be set"
    assert e.verdict is None
    missing = evaluate(
        HEIGHT,
        LINE,
        line_data(clearance=[1, 2, 3]),
        resolve_values([], requirement_set()),
    )
    assert missing.not_applicable == "value of 'vehicle_height' to be set"


def test_class_admissibility_uses_the_declared_order() -> None:
    element = Attribute.categorical("element", ["bridge"] * 3, ELEMENTS)
    cls = Attribute.categorical(
        "load_class", ["C30", "C50", "C70"], ("C30", "C50", "C70")
    )
    data = ArcData(3, (element, cls), element="element")
    e = evaluate(CLASS, LINE, data, resolved(load_class="C50"))
    assert e.verdict is not None
    assert e.verdict.tolist() == [Verdict.FAIL, Verdict.PASS, Verdict.PASS]
    with pytest.raises(ValueError, match="is not one of"):
        evaluate(CLASS, LINE, data, resolved(load_class="C90"))
    numeric = ArcData(
        3, (element, Attribute.numeric("load_class", [1, 2, 3])), element="element"
    )
    with pytest.raises(ValueError, match="must be a category"):
        evaluate(CLASS, LINE, numeric, resolved())


def test_zone_exclusion_reads_a_membership_relation() -> None:
    e = evaluate(ZONE, LINE, line_data(in_zone=[1, 0, None]), resolved())
    assert e.verdict is not None
    assert e.verdict.tolist() == [Verdict.FAIL, Verdict.PASS, Verdict.UNKNOWN]
    with pytest.raises(ValueError, match="0 or 1"):
        evaluate(ZONE, LINE, line_data(in_zone=[2, 0, 0]), resolved())
    with pytest.raises(ValueError, match="must be a number"):
        evaluate(
            ZONE,
            LINE,
            ArcData(3, (Attribute.categorical("in_zone", ["a"] * 3, ("a",)),)),
            resolved(),
        )


def test_speed_cap_is_a_cost_term_in_scope() -> None:
    data = ArcData(
        3,
        (Attribute.categorical("element", ["road", "bridge", None], ELEMENTS),),
        element="element",
    )
    e = evaluate(SPEED, LINE, data, resolved(speed=50.0))
    assert e.kind is EffectKind.COST_TERM
    assert e.cap is not None
    assert e.cap.tolist() == [50.0, math.inf, 50.0]
    with pytest.raises(ValueError, match="positive"):
        evaluate(SPEED, LINE, data, resolved(speed=0.0))
    with pytest.raises(TypeError, match="must be a number"):
        evaluate(SPEED, LINE, data, resolved(speed="fast"))
    kinds = ArcData(
        3,
        (
            Attribute.categorical("element", ["road"] * 3, ELEMENTS),
            Attribute.categorical("length", ["road"] * 3, ELEMENTS),
        ),
        element="element",
    )
    with pytest.raises(ValueError, match="length must be a number"):
        evaluate(SPEED, LINE, kinds, resolved())


def occurrence_set(
    maximum: float | None, minimum: float | None = None
) -> tuple[RequirementSet, ResolvedValues]:
    occ = requirement(
        "OC-1",
        "occurrence_bounds",
        parameters={"maximum": "occurrence_max", "minimum": "occurrence_min"},
        scope=["L1"],
    )
    reqs = RequirementSet((occ,), PARAMETERS, (REG,))
    vs = ValueSet(
        "reg-a",
        "2006",
        {"occurrence_max": value(maximum), "occurrence_min": value(minimum)},
    )
    return reqs, resolve_values([vs], reqs)


def test_occurrence_bounds_in_scope() -> None:
    data = ArcData(
        3,
        (Attribute.categorical("link", ["L0", "L1", "L2"], ("L0", "L1", "L2")),),
        element="link",
    )
    reqs, vals = occurrence_set(2, 1)
    e = evaluate(reqs["OC-1"], LINE, data, vals)
    assert e.kind is EffectKind.BOUND
    assert e.lower is not None
    assert e.upper is not None
    assert e.lower.tolist() == [0, 1, 0]
    assert e.upper.tolist() == [math.inf, 2, math.inf]
    reqs, vals = occurrence_set(math.inf)
    e = evaluate(reqs["OC-1"], LINE, data, vals)
    assert e.not_applicable == "value of 'occurrence_min' to be set"
    for bad in ((1.5, 0), (-1, 0), (1, math.inf), (1, 2)):
        reqs, vals = occurrence_set(*bad)
        with pytest.raises(ValueError, match="count|finite|exceeds"):
            evaluate(reqs["OC-1"], LINE, data, vals)


def test_evaluate_checks_the_data_size() -> None:
    with pytest.raises(ValueError, match="data for 2 arcs"):
        evaluate(ZONE, LINE, ArcData(2, ()), resolved())


# Effects ----------------------------------------------------------------


def test_effect_checks_its_arrays() -> None:
    ok = effect("R", EffectKind.VERDICT, 2, verdict=[2, 0], reasons=[0, 1])
    assert ok.verdict is not None
    with pytest.raises(ValueError, match="read-only"):
        ok.verdict[0] = 1
    with pytest.raises(ValueError, match="expected 2 values"):
        effect("R", EffectKind.VERDICT, 2, verdict=[2], reasons=[0])
    with pytest.raises(ValueError, match="carries"):
        effect("R", EffectKind.VERDICT, 2, cap=[1, 1])
    with pytest.raises(ValueError, match="carries"):
        effect("R", EffectKind.COST_TERM, 2)
    with pytest.raises(ValueError, match="no array"):
        effect("R", EffectKind.BOUND, 2, lower=[0, 0], not_applicable="x")
    with pytest.raises(ValueError, match="Verdict values"):
        effect("R", EffectKind.VERDICT, 1, verdict=[3], reasons=[0])
    with pytest.raises(ValueError, match="Reason values"):
        effect("R", EffectKind.VERDICT, 1, verdict=[2], reasons=[9])
    with pytest.raises(ValueError, match="caps"):
        effect("R", EffectKind.COST_TERM, 1, cap=[-1])
    with pytest.raises(ValueError, match="factors"):
        effect("R", EffectKind.COST_TERM, 1, factor=[math.inf])
    with pytest.raises(ValueError, match="added"):
        effect("R", EffectKind.COST_TERM, 1, added=[math.nan])
    with pytest.raises(ValueError, match="lower"):
        effect("R", EffectKind.BOUND, 1, lower=[0.5], upper=[1])
    with pytest.raises(ValueError, match="upper"):
        effect("R", EffectKind.BOUND, 1, lower=[0], upper=[1.5])


# Composition ------------------------------------------------------------


def verdict_effect(rid: str, verdicts: list[int]) -> Effect:
    reasons = [{0: 1, 1: 2, 2: 0}[v] for v in verdicts]
    return effect(
        rid, EffectKind.VERDICT, len(verdicts), verdict=verdicts, reasons=reasons
    )


def test_policies_for_the_unknown() -> None:
    # A3: the unknown is declared, counted, and handled by a stated policy.
    effects = [verdict_effect("A", [2, 1, 0]), verdict_effect("B", [2, 2, 1])]
    excl = compose(LINE, effects, policy=UnknownPolicy.EXCLUDE)
    assert excl.excluded == (1, 2)
    count = compose(LINE, effects, policy="admit_and_count")
    assert count.excluded == (2,)
    assert count.unknown_count == 1
    pen = compose(LINE, effects, policy=UnknownPolicy.PENALIZE, penalty=10.0)
    assert pen.excluded == (2,)
    assert pen.weights([1, 1, 1]) == (1.0, 11.0, 1.0)
    assert count.weights([1, 1, 1]) == (1.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="penalty"):
        compose(LINE, effects, policy=UnknownPolicy.PENALIZE)
    with pytest.raises(ValueError, match="penalty"):
        compose(LINE, effects, policy=UnknownPolicy.PENALIZE, penalty=math.inf)
    with pytest.raises(ValueError, match="does not apply"):
        compose(LINE, effects, policy=UnknownPolicy.EXCLUDE, penalty=1.0)
    with pytest.raises(ValueError, match="not a valid"):
        compose(LINE, effects, policy="ignore")
    with pytest.raises(ValueError, match="expected 3 base"):
        count.weights([1, 1])


def test_caps_compose_by_their_minimum() -> None:
    # A6: two speed caps on the same arc give the lower one.
    a = effect("A", EffectKind.COST_TERM, 3, cap=[50, math.inf, 70])
    b = effect(
        "B",
        EffectKind.COST_TERM,
        3,
        cap=[60, 30, math.inf],
        factor=[1, 2, 1],
        added=[0, 0, 5],
    )
    view = compose(LINE, [a, b], policy=UnknownPolicy.EXCLUDE)
    assert view.cap.tolist() == [50, 30, 70]
    assert view.capped == (0, 1, 2)
    # 10 km at 100 km/h, capped: 10/50, 10/30 * 2, 10/70 + 5 hours.
    assert view.times([10, 10, 10], [100, 100, 100]) == pytest.approx(
        (0.2, 2 / 3, 10 / 70 + 5)
    )
    assert view.times([10, 10, 10], [20, 20, 20]) == pytest.approx((0.5, 1.0, 5.5))
    with pytest.raises(ValueError, match="use times"):
        view.weights([10, 10, 10])
    assert view.requirements_on(0) == ("A", "B")
    assert view.requirements_on(1) == ("B",)
    with pytest.raises(ValueError, match="out of range"):
        view.requirements_on(3)


def test_bounds_compose_and_conflicts_are_reported() -> None:
    a = effect("A", EffectKind.BOUND, 3, lower=[0, 1, 0], upper=[math.inf, 3, 2])
    b = effect("B", EffectKind.BOUND, 3, lower=[0, 2, 3], upper=[5, math.inf, math.inf])
    view = compose(LINE, [a, b], policy=UnknownPolicy.EXCLUDE)
    assert view.flow_bounds() == ((0, 2, 3), (5, 3, 2))
    assert view.bound_conflicts == (2,)
    neutral = compose(
        LINE,
        [effect("C", EffectKind.BOUND, 3, not_applicable="to be set")],
        policy="exclude",
    )
    assert neutral.flow_bounds() == ((0, 0, 0), (None, None, None))
    assert neutral.requirements_on(0) == ()


def test_compose_refuses_duplicates_and_size_mismatch() -> None:
    with pytest.raises(ValueError, match="two effects"):
        compose(LINE, [verdict_effect("A", [2, 2, 2])] * 2, policy="exclude")
    with pytest.raises(ValueError, match="for 2 arcs"):
        compose(LINE, [verdict_effect("A", [2, 2])], policy="exclude")


def test_view_arrays_are_read_only() -> None:
    view = compose(LINE, [], policy="exclude")
    assert view.excluded == ()
    for array in (view.verdict, view.admitted, view.cap, view.lower):
        with pytest.raises(ValueError, match="read-only"):
            array[0] = 0
    # A view built directly keeps a copy of what it is given.
    cap = np.full(3, math.inf)
    direct = dataclasses.replace(view, cap=cap)
    cap[0] = 1.0
    assert direct.cap[0] == math.inf
    with pytest.raises(ValueError, match="expected 3 values"):
        dataclasses.replace(view, cap=np.ones(2))


M = 4


@st.composite
def effects(draw: st.DrawFn) -> list[Effect]:
    kinds = draw(st.lists(st.sampled_from(list(EffectKind)), max_size=5))
    out = []
    for k, kind in enumerate(kinds):
        rid = f"R{k}"
        if kind is EffectKind.VERDICT:
            v = draw(st.lists(st.sampled_from([0, 1, 2]), min_size=M, max_size=M))
            out.append(verdict_effect(rid, v))
        elif kind is EffectKind.COST_TERM:
            num = st.floats(0.1, 100, allow_nan=False)
            out.append(
                effect(
                    rid,
                    kind,
                    M,
                    cap=draw(st.lists(num | st.just(math.inf), min_size=M, max_size=M)),
                    factor=draw(st.lists(num, min_size=M, max_size=M)),
                    added=draw(st.lists(num, min_size=M, max_size=M)),
                )
            )
        elif kind is EffectKind.OBJECTIVE:
            criterion = draw(st.sampled_from(["length", "duration"]))
            out.append(effect(rid, kind, M, objective=criterion))
        else:
            lo = draw(st.lists(st.integers(0, 3), min_size=M, max_size=M))
            hi = draw(
                st.lists(st.integers(0, 5) | st.just(math.inf), min_size=M, max_size=M)
            )
            out.append(effect(rid, kind, M, lower=lo, upper=hi))
    return out


GRAPH = Digraph.from_arcs(3, [(0, 1), (1, 2), (2, 0), (0, 2)])


def reference(effects: list[Effect]) -> dict[str, list[float]]:
    """The composition, element by element, in pure Python."""
    out: dict[str, list[float]] = {
        "verdict": [2.0] * M,
        "cap": [math.inf] * M,
        "factor": [1.0] * M,
        "added": [0.0] * M,
        "lower": [0.0] * M,
        "upper": [math.inf] * M,
    }
    rules: dict[str, Callable[[float, float], float]] = {
        "verdict": min,
        "cap": min,
        "factor": lambda x, y: x * y,
        "added": lambda x, y: x + y,
        "lower": max,
        "upper": min,
    }
    for e in effects:
        for name, rule in rules.items():
            array = getattr(e, name)
            if array is not None:
                out[name] = [
                    rule(x, float(y)) for x, y in zip(out[name], array, strict=True)
                ]
    return out


@given(effects=effects(), data=st.data())
def test_composition_matches_a_reference_whatever_the_order(
    effects: list[Effect], data: st.DataObject
) -> None:
    # compose sorts the effects by identifier: permuting the identifiers,
    # not only the input order, changes the order of composition.
    ids = data.draw(st.permutations([e.requirement for e in effects]))
    renamed = [
        dataclasses.replace(e, requirement=i) for e, i in zip(effects, ids, strict=True)
    ]
    shuffled = data.draw(st.permutations(renamed))
    policy = data.draw(st.sampled_from(list(UnknownPolicy)))
    penalty = 3.0 if policy is UnknownPolicy.PENALIZE else None
    objectives = {e.objective for e in effects if e.objective is not None}
    if len(objectives) > 1:
        with pytest.raises(ValueError, match="several objectives"):
            compose(GRAPH, shuffled, policy=policy, penalty=penalty)
        return
    view = compose(GRAPH, shuffled, policy=policy, penalty=penalty)
    expected = reference(effects)
    for name in ("verdict", "cap", "lower", "upper"):
        assert getattr(view, name).tolist() == expected[name]
    for name in ("factor", "added"):
        assert np.allclose(getattr(view, name), expected[name], rtol=1e-12)
    unknown = [v == Verdict.UNKNOWN for v in expected["verdict"]]
    assert view.unknown.tolist() == unknown
    admitted = [
        v != Verdict.FAIL and not (u and policy is UnknownPolicy.EXCLUDE)
        for v, u in zip(expected["verdict"], unknown, strict=True)
    ]
    assert view.admitted.tolist() == admitted
    assert view.objective == next(iter(objectives), None)
    assert sorted(e.requirement for e in view.effects) == sorted(ids)


def test_every_routing_requirement_gives_its_declared_kind() -> None:
    case = random_case(3)
    data = case.data()
    for r in ROUTING:
        e = evaluate(r, case.graph, data, resolved())
        assert e.requirement == r.id
        assert e.m == case.graph.m
