# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Conformity of the derivations of the registry (objective 3 of
AGENTS.md): every derivation has a factory of cases here, and every value
it derives carries a complete trace, whatever the policy for the unknown.
"""

from __future__ import annotations

import copy
import pickle
from collections.abc import Callable, Iterable

import pytest
from derive_cases import (
    CLASSES,
    COLUMN,
    KNOWN_ONLY,
    NA,
    PROPAGATE,
    A,
    B,
    chosen,
    derive,
    member,
)

from protee.constraints import (
    Aggregation,
    Comparison,
    DerivationInfo,
    Derived,
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

#: Members known, unknown and not applicable, nested.
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


#: One factory of cases per derivation of the registry, by policy.
FACTORIES: dict[str, Callable[[str], list[Derived]]] = {
    "aggregate": _aggregate,
}

POLICIES = ("propagate", "known_only", "assume")


def test_registry_is_closed_and_ordered() -> None:
    infos = derivations()
    assert [d.name for d in infos] == ["aggregate"]
    assert infos == tuple(DERIVATIONS.values())
    for info in infos:
        assert isinstance(info, DerivationInfo)
        for text in (info.name, info.summary, info.inputs, info.output, info.reference):
            assert text.strip()
        assert info.rules
        assert len(set(info.rules)) == len(info.rules)
        assert info.cases
        assert all(case.strip() for case in info.cases)
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


def test_every_derivation_has_a_factory_of_cases() -> None:
    assert set(FACTORIES) == {d.name for d in derivations()}


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("name", [d.name for d in derivations()])
def test_every_derived_value_carries_its_trace(name: str, policy: str) -> None:
    info = DERIVATIONS[name]
    results = FACTORIES[name](policy)
    assert results
    seen_rules: set[str] = set()
    for derived in results:
        assert set(derived.unknown) == set(derived.values.values)
        assert set(derived.assumed) == set(derived.values.values)
        assert set(derived.left_out) == set(derived.values.values)
        for parameter, value in derived.values.values.items():
            assert value.origin is Origin.DERIVED
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
    # An identical call gives the same result.
    again = FACTORIES[name](policy)
    assert again == results
    assert [fingerprint(r) for r in again] == [fingerprint(r) for r in results]
    for derived in results:
        assert pickle.loads(pickle.dumps(derived)) == derived
        assert copy.deepcopy(derived) == derived
    expected = (
        set(info.rules)
        if policy != "known_only"
        else set(info.rules)
        - {
            "sum",
            "mean",
            "threshold_count",
        }
    )
    assert seen_rules == expected
