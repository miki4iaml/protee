# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The model of protee.constraints: sources, values, requirements, patterns."""

from __future__ import annotations

import math

import pytest
from constraints_cases import (
    DOC,
    DOC_SRC,
    MASS,
    PARAMETERS,
    REG,
    SRC,
    requirement,
    requirement_set,
    value,
    values,
)

from protee.constraints import (
    Correspondence,
    EffectKind,
    Family,
    Origin,
    Parameter,
    Relation,
    RequirementSet,
    ResolvedValues,
    Rulebook,
    RulebookKind,
    Source,
    Subject,
    Value,
    ValueSet,
    patterns,
    resolve_values,
)


def test_registry_is_closed_and_ordered() -> None:
    names = [p.name for p in patterns()]
    assert names == [
        "threshold_admissibility",
        "class_admissibility",
        "zone_exclusion",
        "speed_cap",
        "occurrence_bounds",
        "objective",
    ]
    by_name = {p.name: p for p in patterns()}
    assert by_name["speed_cap"].effect_kind is EffectKind.COST_TERM
    assert by_name["occurrence_bounds"].family is Family.CAPACITY
    assert by_name["occurrence_bounds"].optional == ("minimum",)
    assert all(p.summary and p.composition for p in patterns())


def test_pattern_states_what_its_value_constrains() -> None:
    # A10: the value of a threshold is the vehicle's, a zone is infrastructure.
    by_name = {p.name: p for p in patterns()}
    assert by_name["threshold_admissibility"].subject is Subject.VEHICLE
    assert by_name["zone_exclusion"].subject is Subject.INFRASTRUCTURE
    assert by_name["occurrence_bounds"].subject is Subject.FLOW
    assert by_name["objective"].subject is Subject.RESULT
    assert by_name["objective"].effect_kind is EffectKind.OBJECTIVE


def test_rulebook_needs_english_title_and_coerces_kind() -> None:
    book = Rulebook("x", "standard", {"en": "Standard X", "fr": "Norme X"}, "2024")  # type: ignore[arg-type]
    assert book.kind is RulebookKind.STANDARD
    assert book.title["fr"] == "Norme X"
    with pytest.raises(TypeError):
        book.title["en"] = "other"  # type: ignore[index]
    with pytest.raises(ValueError, match="English"):
        Rulebook("x", RulebookKind.STANDARD, {"fr": "Norme X"}, "2024")
    with pytest.raises(ValueError, match="non-empty"):
        Rulebook("", RulebookKind.STANDARD, {"en": "X"}, "2024")
    with pytest.raises(ValueError, match="non-empty"):
        Rulebook("x", RulebookKind.STANDARD, {"en": " "}, "2024")
    with pytest.raises(ValueError, match="not a valid"):
        Rulebook("x", "law", {"en": "X"}, "2024")  # type: ignore[arg-type]


def test_source_requires_a_document() -> None:
    assert not SRC.citation_checked
    assert Source("Answer of 12/11", citation_checked=True).rulebook is None
    with pytest.raises(ValueError, match="document"):
        Source("")


def test_value_types_and_to_be_set() -> None:
    assert value(None).to_be_set
    assert not value(math.inf).to_be_set
    assert Value(1, SRC, "choice").origin is Origin.CHOICE  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        value(True)
    with pytest.raises(TypeError):
        Value([1], SRC, Origin.CHOICE)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="NaN"):
        value(math.nan)
    with pytest.raises(TypeError, match="precedence"):
        Value(1, SRC, Origin.CHOICE, precedence=1.5)  # type: ignore[arg-type]


def test_value_set_checks_its_entries() -> None:
    vs = values()
    with pytest.raises(TypeError):
        vs.values["x"] = value(1)  # type: ignore[index]
    with pytest.raises(TypeError, match="must be a Value"):
        ValueSet("reg-a", "2006", {"vehicle_height": 4.0})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="non-empty"):
        ValueSet("reg-a", "", {})


def test_requirement_binds_exactly_the_roles_of_its_pattern() -> None:
    assert MASS.scope == frozenset({"bridge"})
    with pytest.raises(ValueError, match="unknown pattern"):
        requirement("R", "no_such_pattern")
    with pytest.raises(ValueError, match="not bound"):
        requirement("R", "threshold_admissibility", attributes={"limit": "mass_limit"})
    with pytest.raises(ValueError, match="no parameter role"):
        requirement(
            "R",
            "speed_cap",
            parameters={"maximum": "speed_max", "minimum": "speed_max"},
        )
    with pytest.raises(ValueError, match="attribute roles"):
        requirement("R", "zone_exclusion")
    with pytest.raises(ValueError, match="English"):
        type(MASS)("R", "zone_exclusion", {"fr": "x"}, SRC, attributes={"inside": "z"})
    with pytest.raises(ValueError, match="scope label"):
        requirement("R", "zone_exclusion", attributes={"inside": "z"}, scope=[""])
    with pytest.raises(ValueError, match="empty scope"):
        requirement("R", "zone_exclusion", attributes={"inside": "z"}, scope=[])


def test_requirement_set_resolves_every_cited_identifier() -> None:
    # A8: unique identifiers, every cited identifier exists.
    reqs = requirement_set()
    assert len(reqs) == 5
    assert reqs["ADM-MASS"] is MASS
    assert next(iter(reqs)).id == "ADM-MASS"
    assert reqs.parameter("vehicle_mass").unit == "t"
    assert reqs.rulebook("reg-a") is REG
    with pytest.raises(ValueError, match="duplicate requirement"):
        RequirementSet((MASS, MASS), PARAMETERS, (REG,))
    with pytest.raises(ValueError, match="unknown parameter"):
        RequirementSet((MASS,), (), (REG,))
    with pytest.raises(ValueError, match="ADM-MASS: unknown rulebook"):
        RequirementSet((MASS,), (Parameter("vehicle_mass", unit="t"),))
    with pytest.raises(ValueError, match="unknown rulebook 'reg-a'"):
        RequirementSet((MASS,), PARAMETERS, (DOC,))
    with pytest.raises(ValueError, match="duplicate parameter"):
        RequirementSet((), (PARAMETERS[1], PARAMETERS[1]))


def test_unknown_parameter_refused_and_unused_reported() -> None:
    # A2: a value set naming an unknown parameter is refused; a value that
    # no requirement reads is reported.
    reqs = requirement_set()
    bad = ValueSet("reg-a", "2006", {"vehicle_speed": value(1, "km/h")})
    with pytest.raises(ValueError, match="unknown parameter 'vehicle_speed'"):
        resolve_values([bad], reqs)
    extra = ValueSet(
        "reg-a", "2006", {**values().values, "unused_width": value(2.5, "m")}
    )
    r = resolve_values([extra], reqs)
    assert r.unused == ("unused_width",)
    assert r.missing == ()
    assert resolve_values([], reqs).missing == (
        "required_load_class",
        "speed_max",
        "vehicle_height",
        "vehicle_mass",
    )


def test_alias_resolves_to_the_canonical_name() -> None:
    # A10: regulation A calls the mass "total_mass".
    r = resolve_values([values(mass=40.0)], requirement_set())
    assert r.values["vehicle_mass"].value == 40.0
    assert r.get("total_mass") is None
    other = ValueSet(
        "doc-b",
        "2019",
        {"total_mass": Value(40.0, DOC_SRC, Origin.RULEBOOK, unit="t")},
    )
    with pytest.raises(ValueError, match="unknown parameter 'total_mass'"):
        resolve_values([other], requirement_set())


def test_unit_must_be_the_parameters_and_given_once() -> None:
    reqs = requirement_set()
    with pytest.raises(ValueError, match="expected 't'"):
        resolve_values(
            [ValueSet("reg-a", "2006", {"vehicle_mass": value(40, "kg")})], reqs
        )
    twice = ValueSet(
        "reg-a",
        "2006",
        {"vehicle_mass": value(40.0, "t"), "total_mass": value(40.0, "t")},
    )
    with pytest.raises(ValueError, match="given twice"):
        resolve_values([twice], reqs)


def test_declared_precedence_settles_a_disagreement() -> None:
    # A5: two rulebooks disagree; the declared precedence decides, and both
    # values stay in the provenance.
    reqs = requirement_set()
    doctrine = ValueSet(
        "doc-b",
        "2019",
        {"vehicle_mass": Value(60.0, DOC_SRC, Origin.RULEBOOK, unit="t", precedence=2)},
    )
    for order in ([values(), doctrine], [doctrine, values()]):
        r = resolve_values(order, reqs)
        assert r.values["vehicle_mass"].value == 60.0
        assert [v.value for v in r.discarded["vehicle_mass"]] == [44.0]
    same = ValueSet(
        "doc-b",
        "2019",
        {"vehicle_mass": Value(60.0, DOC_SRC, Origin.RULEBOOK, unit="t")},
    )
    with pytest.raises(ValueError, match="same precedence"):
        resolve_values([values(), same], reqs)
    agree = ValueSet(
        "doc-b",
        "2019",
        {"vehicle_mass": Value(44, DOC_SRC, Origin.RULEBOOK, unit="t")},
    )
    # Agreeing values of the same precedence: the first rulebook in
    # alphabetical order is retained, whatever the order of the sets.
    for order in ([values(), agree], [agree, values()]):
        r = resolve_values(order, reqs)
        assert r.values["vehicle_mass"].source.rulebook == "doc-b"
        assert r.values["vehicle_mass"].value == 44
        assert [v.source.rulebook for v in r.discarded["vehicle_mass"]] == ["reg-a"]


def test_value_sets_keep_their_rulebook_and_edition() -> None:
    # A value keeps the rulebook and the edition of its set; a source that
    # cites another one is refused, and so is a second set of the same
    # rulebook and edition.
    bare = ValueSet(
        "doc-b",
        "2019",
        {"vehicle_mass": Value(60.0, Source("Doctrine B"), Origin.RULEBOOK, unit="t")},
    )
    source = bare.values["vehicle_mass"].source
    assert (source.document, source.rulebook, source.edition) == (
        "Doctrine B",
        "doc-b",
        "2019",
    )
    with pytest.raises(ValueError, match="cites the rulebook 'reg-a'"):
        ValueSet("doc-b", "2019", {"vehicle_mass": value(60.0, "t")})
    with pytest.raises(ValueError, match="cites the edition '2006'"):
        ValueSet("reg-a", "2023", {"vehicle_mass": value(60.0, "t")})
    with pytest.raises(ValueError, match="two value sets for reg-a"):
        resolve_values([values(), values()], requirement_set())


def test_every_chosen_objective_needs_a_justification() -> None:
    # A chosen value without justification is refused even when a value of
    # higher precedence sets it aside.
    objective = requirement(
        "OBJ", "objective", parameters={"criterion": "route_criterion"}
    )
    reqs = RequirementSet(
        (objective,), (*PARAMETERS, Parameter("route_criterion")), (REG, DOC)
    )
    chosen = ValueSet(
        "reg-a",
        "2006",
        {"route_criterion": Value("length", SRC, Origin.CHOICE)},
    )
    text = ValueSet(
        "doc-b",
        "2019",
        {"route_criterion": Value("duration", DOC_SRC, Origin.STATEMENT, precedence=1)},
    )
    with pytest.raises(ValueError, match="needs a justification"):
        resolve_values([chosen, text], reqs)


def test_resolved_values_copy_what_they_are_given() -> None:
    given = {"vehicle_mass": value(44.0, "t")}
    r = ResolvedValues(given, {"vehicle_mass": [value(40.0, "t")]}, ["x"], [])  # type: ignore[dict-item,arg-type]
    given["vehicle_mass"] = value(1.0, "t")
    assert r.values["vehicle_mass"].value == 44.0
    assert r.discarded["vehicle_mass"] == (value(40.0, "t"),)
    assert r.unused == ("x",)
    with pytest.raises(TypeError):
        r.values["other"] = value(1.0, "t")  # type: ignore[index]


def test_parameter_aliases_name_known_rulebooks() -> None:
    with pytest.raises(ValueError, match="unknown rulebook 'nowhere'"):
        RequirementSet((), (Parameter("p", aliases={"nowhere": "q"}),))
    with pytest.raises(ValueError, match="non-empty"):
        Parameter("p", aliases={"reg-a": ""})


def test_correspondence_is_qualified() -> None:
    c = Correspondence(
        "class_admissibility",
        "doc-b",
        "load class",
        "reg-a",
        "mass limit",
        "close",  # type: ignore[arg-type]
        note="a load class is not a mass limit in tonnes",
    )
    assert c.relation is Relation.CLOSE
    with pytest.raises(ValueError, match="two different rulebooks"):
        Correspondence("speed_cap", "a", "x", "a", "y", Relation.EXACT)
    with pytest.raises(ValueError, match="unknown pattern"):
        Correspondence("nothing", "a", "x", "b", "y", Relation.EXACT)
    with pytest.raises(ValueError, match="non-empty"):
        Correspondence("speed_cap", "a", "", "b", "y", Relation.EXACT)


def test_public_api_is_explicit() -> None:
    import protee.constraints as c

    assert c.__all__ == sorted(c.__all__, key=lambda n: (n[0].islower(), n))
    assert all(hasattr(c, name) for name in c.__all__)
    assert "requirement_table" in c.__all__
    assert "requirements_table" not in c.__all__
