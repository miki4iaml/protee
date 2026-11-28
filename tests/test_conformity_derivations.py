# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Conformity of the derivations of the registry (objective 3 of
AGENTS.md): every derivation has a factory of cases here, and every value
it derives carries a complete trace, whatever the policy for the unknown.
"""

from __future__ import annotations

import copy
import pickle
import re
from collections.abc import Callable, Iterable

import pytest
from derive_cases import (
    CLASSES,
    COLUMN,
    KNOWN_ONLY,
    LINE,
    NA,
    PROPAGATE,
    S1,
    SPACING,
    A,
    B,
    C,
    chosen,
    classify,
    derive,
    measure,
    member,
    plan,
    regulation,
    select,
    sheet,
)

from protee.constraints import (
    Aggregation,
    Comparison,
    DerivationInfo,
    Derived,
    Gap,
    GapCount,
    Group,
    OnUnknown,
    Origin,
    Source,
    Value,
    ValueState,
    derivations,
    fingerprint,
)
from protee.constraints._derivations import DERIVATIONS

#: Members known, unknown and not applicable, nested; a member whose
#: values are not applicable.
CASES = (
    COLUMN,
    Group(
        "mixed",
        (
            (A, 2),
            (member("U", mass=5.0), 1),
            (member("K", width=NA("carried by B"), load_class=NA("carried")), 1),
            (Group("sub", ((B, 3),)), 1),
        ),
    ),
    Group(
        "carried",
        ((member("K", width=NA("carried by B"), load_class=NA("carried")), 2),),
    ),
)
THRESHOLD = Value(
    20.0, Source("Regulation A", locator="art. 3"), Origin.RULEBOOK, unit="t"
)


#: The values assumed under the policy ``assume``, by parameter.
ASSUMED = {
    "width": chosen(3.0, "m"),
    "speed": chosen(50.0, "km/h"),
    "load_class": chosen("C50"),
    "length": chosen(8.0, "m"),
    "mass": chosen(10.0, "t"),
    "category": chosen("2"),
    "speed_3": chosen(45.0, "km/h"),
    "gap": chosen(25.0, "m"),
    "time_gap": chosen(1.0, "min"),
    "pace": chosen(400.0, "m/min"),
    "density": chosen(0.05, "1/m"),
}


def policy_for(name: str, reads: Iterable[str]) -> OnUnknown:
    """The policy ``name``; under ``assume``, a value for each parameter
    read (a value for a parameter that no rule reads is refused)."""
    if name == "propagate":
        return PROPAGATE
    if name == "known_only":
        return KNOWN_ONLY
    return OnUnknown.assume({p: ASSUMED[p] for p in reads if p in ASSUMED})


def _aggregate(policy: str) -> list[Derived]:
    envelopes = {
        "width": Aggregation.max("width"),
        "speed": Aggregation.min("speed"),
        "load_class": Aggregation.strictest("load_class", CLASSES),
        "members": Aggregation.count(),
    }
    additive = {
        "mass": Aggregation.sum("mass"),
        "length": Aggregation.mean("length"),
        "heavy": Aggregation.threshold_count("mass", THRESHOLD, Comparison.AT_LEAST),
    }
    sets = [envelopes] if policy == "known_only" else [envelopes, additive]
    return [
        derive(group, rules, policy_for(policy, (r.of for r in rules.values() if r.of)))
        for rules in sets
        for group in CASES
    ]


#: Subjects with every characteristic known, one unknown and one not
#: applicable, none applicable, and the envelope of a group.
SUBJECTS = (
    sheet("sheet-S", width=3.5, mass=50.0),
    sheet("sheet-S", width=NA("carried"), length=4.0),
    sheet("sheet-S", width=NA("carried"), mass=NA("weighed apart")),
    derive(
        COLUMN, {"width": Aggregation.max("width"), "mass": Aggregation.max("mass")}
    ),
)


def _classify(policy: str) -> list[Derived]:
    unknown = policy_for(policy, ("width", "mass"))
    # The width at the highest rank decides despite the unknown mass.
    decided = sheet("sheet-S", width=5.0)
    return [classify(s, unknown) for s in (*SUBJECTS, decided)]


def _select(policy: str) -> list[Derived]:
    classes = [classify(s, PROPAGATE) for s in SUBJECTS]
    classes.append(classify(sheet("sheet-S", width=2.0, mass=10.0)))  # class 1
    unknown = policy_for(policy, ("category", "speed_2", "speed_3"))
    if policy == "known_only":
        with pytest.raises(ValueError, match="known_only does not apply"):
            select(classes[0], unknown)
        return []
    open_ = regulation(speed_2=60.0, speed_3=None)
    return [
        *(select(c, unknown) for c in classes),
        select(classes[0], unknown, values=open_),
    ]


GEOMETRIC = ("length", "time_gap", "gap", "pace")
BY_DENSITY = ("density", "time_gap", "pace")


def _column(policy: str) -> list[Derived]:
    if policy == "known_only":
        with pytest.raises(ValueError, match="known_only would shorten"):
            measure(LINE, KNOWN_ONLY)
        return []
    carried = member("K", length=NA("carried by B"))
    with_unknowns = Group(
        "u",
        (
            (Group("s1", ((A, 2), (member("U", width=2.0), 1)), values=S1.values), 2),
            (Group("bare", ((C, 2), (carried, 2))), 1),
        ),
        values=plan("u", time_gap=2.0, pace=500.0),
    )
    gap = [Gap("gap", GapCount.PER_UNIT)]
    one = Group("one", ((C, 3),), values=plan("one", density=0.1))
    return [
        measure(LINE, policy_for(policy, GEOMETRIC)),
        measure(LINE, policy_for(policy, BY_DENSITY), density=True),
        measure(with_unknowns, policy_for(policy, GEOMETRIC)),
        measure(
            Group("k", ((carried, 2),)),
            policy_for(policy, ("length", "gap")),
            spacing=gap,
        ),
        measure(one, policy_for(policy, ("density",)), density=True, spacing=[]),
        measure(S1, policy_for(policy, ("length", "gap")), spacing=[SPACING[1]]),
    ]


#: One factory of cases per derivation of the registry, by policy.
FACTORIES: dict[str, Callable[[str], list[Derived]]] = {
    "aggregate": _aggregate,
    "classify_by_thresholds": _classify,
    "select_by_class": _select,
    "column_length": _column,
}

POLICIES = ("propagate", "known_only", "assume")

#: The rules that refuse ``known_only``: it would shorten an additive
#: value, or a single class has no known inputs to keep.
REFUSE_KNOWN_ONLY = {
    "aggregate": {"sum", "mean", "threshold_count"},
    "classify_by_thresholds": set(),
    "select_by_class": {"table"},
    "column_length": {"density", "geometric"},
}


def test_registry_is_closed_and_ordered() -> None:
    infos = derivations()
    assert [d.name for d in infos] == [
        "aggregate",
        "classify_by_thresholds",
        "select_by_class",
        "column_length",
    ]
    assert infos == tuple(DERIVATIONS.values())
    for info in infos:
        assert isinstance(info, DerivationInfo)
        for text in (info.name, info.summary, info.inputs, info.output, info.reference):
            assert text.strip()
        assert info.rules
        assert len(set(info.rules)) == len(info.rules)
        assert info.cases
        assert all(case.strip() for case in info.cases)
        # Generic names only: no domain word in the registry.
        words = " ".join((info.summary, info.inputs, info.output, *info.cases))
        assert not re.search(r"vehicle|convoy|military", words, re.IGNORECASE)
    by_name = {d.name: d for d in infos}
    assert by_name["aggregate"].rules == (
        "max",
        "min",
        "strictest",
        "sum",
        "count",
        "mean",
        "threshold_count",
    )
    assert by_name["classify_by_thresholds"].rules == ("highest_rank",)
    assert by_name["select_by_class"].rules == ("table",)
    assert by_name["column_length"].rules == ("density", "geometric")
    assert set(REFUSE_KNOWN_ONLY) == set(by_name)


def test_every_derivation_has_a_factory_of_cases() -> None:
    assert set(FACTORIES) == {d.name for d in derivations()}


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("name", [d.name for d in derivations()])
def test_every_derived_value_carries_its_trace(name: str, policy: str) -> None:
    info = DERIVATIONS[name]
    refused = REFUSE_KNOWN_ONLY[name] if policy == "known_only" else set()
    expected = set(info.rules) - refused
    results = FACTORIES[name](policy)
    # A policy every rule refuses leaves no case: the factory checked the
    # refusal.
    assert bool(results) == bool(expected)
    seen_rules: set[str] = set()
    states: set[ValueState] = set()
    for derived in results:
        assert set(derived.unknown) == set(derived.values.values)
        assert set(derived.assumed) == set(derived.values.values)
        assert set(derived.left_out) == set(derived.values.values)
        for parameter, value in derived.values.values.items():
            assert value.origin is Origin.DERIVED
            states.add(value.state)
            trace = value.derivation
            assert trace is not None
            assert trace.name == name
            assert trace.rule in info.rules
            seen_rules.add(trace.rule)
            assert trace.settings["unknown"] == policy
            assert value.source.rulebook == derived.values.rulebook
            # The tallies agree with the trace.
            assert derived.unknown[parameter].names == trace.unknown
            assumed = {h for a in trace.assumptions for h in a.holders}
            assert set(derived.assumed[parameter].names) == assumed
            assert assumed <= set(trace.unknown)
            assert set(derived.left_out[parameter].names) == {
                x.name for x in trace.left_out
            }
            # Under assume, no input stays unknown: each one is assumed.
            if policy == "assume":
                assert ValueState.UNKNOWN not in {i.state for i in trace.inputs}
            # A value to be set is fixed by no input.
            if value.to_be_set:
                assert trace.fixed_by == ()
    if results:
        assert ValueState.KNOWN in states
        assert ValueState.NOT_APPLICABLE in states
        if policy == "propagate":
            assert ValueState.UNKNOWN in states
    # An identical call gives the same result.
    again = FACTORIES[name](policy)
    assert again == results
    assert [fingerprint(r) for r in again] == [fingerprint(r) for r in results]
    for derived in results:
        assert pickle.loads(pickle.dumps(derived)) == derived
        assert copy.deepcopy(derived) == derived
    assert seen_rules == expected
