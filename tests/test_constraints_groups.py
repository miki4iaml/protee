# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Members and groups: construction, tables of counts, variants and
declared sub-groups."""

from __future__ import annotations

import copy
import itertools
import pickle
import re

import pytest
from derive_cases import COLUMN, PAIR, A, B, C, D, member, sheet

from protee.constraints import (
    Group,
    LeftOut,
    LeftOutCause,
    Member,
    ValueSet,
    ZeroCount,
    fingerprint,
)
from protee.constraints._groups import tree_left_out


def flat(group: Group) -> list[tuple[str, int]]:
    return [(m.id, c) for m, c in group.flatten()]


def test_member_sorts_its_sheets_and_refuses_two_for_one_book() -> None:
    one, two = sheet("sheet-x", width=2.0), sheet("sheet-w", mass=3.0)
    m = Member("M", [one, two])  # type: ignore[arg-type]
    assert [s.rulebook for s in m.sheets] == ["sheet-w", "sheet-x"]
    assert m == Member("M", (two, one))
    assert Member("bare").sheets == ()
    assert Member("M", (one, sheet("sheet-x", "2", width=2.0))).sheets[1].edition == "2"
    with pytest.raises(ValueError, match=re.escape("two sheets for sheet-x (1)")):
        Member("M", (one, sheet("sheet-x", mass=1.0)))
    with pytest.raises(TypeError, match=re.escape("member 'M': sheets[0] must be")):
        Member("M", ({"width": 2.0},))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-empty"):
        Member(" ")


def test_members_are_sorted_and_equality_ignores_the_order() -> None:
    rows = [(C, 1), (A, 2), (B, 3)]
    groups = [Group("G", tuple(p)) for p in itertools.permutations(rows)]
    assert all(g == groups[0] for g in groups)
    assert len({hash(g) for g in groups}) == 1
    assert len({fingerprint(g) for g in groups}) == 1
    assert [m.id for m, _ in groups[0].members] == ["A", "B", "C"]


def test_flatten_multiplies_the_counts_along_the_path() -> None:
    # Three levels: a column of 2 convoys of (3 pairs and C), a pair of 2 A
    # and B; A is also a direct member of the convoy.
    convoy = Group("convoy", ((PAIR, 3), (C, 1), (A, 1)))
    top = Group("top", ((convoy, 2), (D, 5)))
    assert flat(top) == [("A", 2 * (3 * 2 + 1)), ("B", 2 * 3), ("C", 2), ("D", 5)]
    assert flat(COLUMN) == [("A", 6), ("B", 3), ("C", 1)]
    # The same sub-group in two places.
    twice = Group("twice", ((PAIR, 1), (Group("other", ((PAIR, 2),)), 1)))
    assert flat(twice) == [("A", 6), ("B", 3)]


GROUP_REFUSALS: list[tuple[tuple[object, ...], type[Exception], str]] = [
    ((), ValueError, "group 'G' has no member: an empty group"),
    (
        ((A, 0),),
        ValueError,
        (
            "group 'G': the count of 'A' must be a positive integer, got 0; "
            "Group.from_counts(..., zero_counts=ZeroCount.DROP) drops zero rows"
        ),
    ),
    (((A, -1),), ValueError, "must be a positive integer, got -1"),
    (((A, True),), TypeError, "must be a positive integer, got True"),
    (((A, 1.0),), TypeError, "must be a positive integer, got 1.0"),
    (((A, 1), (A, 2)), ValueError, "group 'G': 'A' appears twice"),
    (((A,),), TypeError, "members[0] must be a (member, count) pair"),
    ((("A", 1),), TypeError, "members[0] must hold a Member or a Group"),
    (
        ((A, 1), (Group("S", ((member("A", width=9.0), 1),)), 1)),
        ValueError,
        "group 'G': two different members share the identifier 'A'",
    ),
    (
        ((Group("A", ((B, 1),)), 1), (Group("S", ((A, 1),)), 1)),
        ValueError,
        "group 'G': a member and a group share the identifier 'A'",
    ),
    (
        ((Group("G", ((B, 1),)), 1),),
        ValueError,
        "group 'G': two different groups share the identifier 'G'",
    ),
    (
        ((Group("S", ((B, 1),)), 1), (Group("T", ((Group("S", ((C, 1),)), 1),)), 1)),
        ValueError,
        "group 'G': two different groups share the identifier 'S'",
    ),
]


@pytest.mark.parametrize(("rows", "error", "message"), GROUP_REFUSALS)
def test_group_construction_refusals(
    rows: tuple[object, ...], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        Group("G", rows)  # type: ignore[arg-type]


def test_negative_count_has_no_hint_about_zero_rows() -> None:
    with pytest.raises(ValueError, match="got -1$"):
        Group("G", ((A, -1),))


def test_group_fields_are_checked() -> None:
    # The same sub-group in two places is one object: allowed.
    shared = Group("G", ((PAIR, 1), (Group("S", ((PAIR, 1),)), 1)))
    assert [(m.id, c) for m, c in shared.flatten()] == [("A", 4), ("B", 2)]
    with pytest.raises(TypeError, match="values must be a ValueSet"):
        Group("G", ((A, 1),), values={"gap": 1.0})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="left_out holds LeftOut records"):
        Group("G", ((A, 1),), left_out=("B",))  # type: ignore[arg-type]
    unknown = LeftOut("B", LeftOutCause.UNKNOWN, "towed", 1)
    with pytest.raises(ValueError, match="zero counts and exclusions only"):
        Group("G", ((A, 1),), left_out=(unknown,))
    with pytest.raises(ValueError, match="variant_of"):
        Group("G", ((A, 1),), variant_of="")
    gap = ValueSet("G", "1", {})
    assert Group("G", ((A, 1),), values=gap).values == gap
    # left_out is sorted: equality does not depend on its order.
    one = LeftOut("X", LeftOutCause.EXCLUDED, "r", 1)
    two = LeftOut("Y", LeftOutCause.ZERO_COUNT, "count 0 in the table", 0)
    assert Group("G", ((A, 1),), left_out=(two, one)) == Group(
        "G", ((A, 1),), left_out=(one, two)
    )


def test_from_counts_refuses_or_drops_zero_rows() -> None:
    table = [(A, 2), (B, 0), (C, 1)]
    with pytest.raises(ValueError, match="count of 'B' must be a positive integer"):
        Group.from_counts("G", table, zero_counts=ZeroCount.REFUSE)
    assert Group.from_counts("G", [(A, 2)], zero_counts="refuse") == Group(  # type: ignore[arg-type]
        "G", ((A, 2),)
    )
    g = Group.from_counts("G", table, zero_counts=ZeroCount.DROP)
    assert flat(g) == [("A", 2), ("C", 1)]
    assert g.left_out == (
        LeftOut("B", LeftOutCause.ZERO_COUNT, "count 0 in the table", 0),
    )
    with pytest.raises(ValueError, match="has no member"):
        Group.from_counts("G", [(A, 0), (B, 0)], zero_counts=ZeroCount.DROP)
    with pytest.raises(ValueError, match="'A' appears twice"):
        Group.from_counts("G", [(A, 0), (A, 1)], zero_counts=ZeroCount.DROP)
    with pytest.raises(ValueError, match="'invalid' is not a valid ZeroCount"):
        Group.from_counts("G", table, zero_counts="invalid")  # type: ignore[arg-type]
    # A negative count is never a zero row.
    with pytest.raises(ValueError, match="got -2"):
        Group.from_counts("G", [(A, -2)], zero_counts=ZeroCount.DROP)


def test_with_counts_makes_a_variant() -> None:
    base = Group.from_counts("G", [(A, 2), (B, 1), (C, 0)], zero_counts=ZeroCount.DROP)
    v = base.with_counts("G-more-B", {"B": 4}, zero_counts=ZeroCount.REFUSE)
    assert flat(v) == [("A", 2), ("B", 4)]
    assert v.variant_of == "G"
    assert v.left_out == base.left_out
    dropped = base.with_counts("G-no-A", {"A": 0}, zero_counts=ZeroCount.DROP)
    assert flat(dropped) == [("B", 1)]
    assert [x.name for x in dropped.left_out] == ["A", "C"]
    with pytest.raises(ValueError, match="count of 'A' must be a positive"):
        base.with_counts("G2", {"A": 0}, zero_counts=ZeroCount.REFUSE)
    with pytest.raises(ValueError, match="group 'G' has no direct member 'Z'"):
        base.with_counts("G2", {"Z": 1}, zero_counts=ZeroCount.REFUSE)
    with pytest.raises(ValueError, match="needs an identifier of its own"):
        base.with_counts("G", {"A": 3}, zero_counts=ZeroCount.REFUSE)
    # Deeper members are changed through their sub-group.
    with pytest.raises(ValueError, match="no direct member 'A'"):
        COLUMN.with_counts("C2", {"A": 1}, zero_counts=ZeroCount.REFUSE)


def test_without_excludes_at_any_depth_with_its_reason() -> None:
    sub = COLUMN.without("column-no-B", ["B"], reason="B crosses apart")
    assert flat(sub) == [("A", 6), ("C", 1)]
    assert sub.variant_of == "column"
    # Three pairs of one B each: 3 instances excluded.
    assert sub.left_out == (LeftOut("B", LeftOutCause.EXCLUDED, "B crosses apart", 3),)
    # The pair keeps its identifier inside the sub-group.
    assert [e.id for e, _ in sub.members] == ["C", "pair"]
    # An emptied sub-group disappears, recorded with the reason.
    emptied = COLUMN.without("only-C", ["A", "B"], reason="ferried")
    assert flat(emptied) == [("C", 1)]
    assert emptied.left_out == (
        LeftOut("A", LeftOutCause.EXCLUDED, "ferried", 6),
        LeftOut("B", LeftOutCause.EXCLUDED, "ferried", 3),
        LeftOut("pair", LeftOutCause.EXCLUDED, "all its members excluded: ferried", 0),
    )
    # A sub-group excluded by name, with a member named below it.
    named = COLUMN.without("no-pair", ["pair", "A"], reason="ferried")
    assert flat(named) == [("C", 1)]
    assert {x.name: x.instances for x in named.left_out} == {"A": 0, "pair": 9}
    # A sub-group not touched is kept as it is.
    other = Group("other", ((PAIR, 1), (Group("S", ((C, 1), (D, 1))), 1)))
    kept = {e.id: e for e, _ in other.without("o2", ["D"], reason="r").members}
    assert kept["pair"] is PAIR


def test_without_refusals() -> None:
    with pytest.raises(ValueError, match="group 'column' has no member 'Z'"):
        COLUMN.without("X", ["Z"], reason="r")
    with pytest.raises(ValueError, match="no member 'column'"):
        COLUMN.without("X", ["column"], reason="r")
    with pytest.raises(
        ValueError,
        match=re.escape("group 'X': excluding ['A', 'B', 'C'] leaves no member"),
    ):
        COLUMN.without("X", ["C", "B", "A"], reason="r")
    with pytest.raises(ValueError, match="reason must be a non-empty string"):
        COLUMN.without("X", ["A"], reason=" ")
    with pytest.raises(ValueError, match="at least one identifier"):
        COLUMN.without("X", [], reason="r")
    with pytest.raises(ValueError, match="needs an identifier of its own"):
        COLUMN.without("column", ["A"], reason="r")
    # A bare string would be read as its characters, which may be members.
    letters = Group("L", ((Member("A"), 1), (Member("B"), 1), (Member("AB"), 1)))
    with pytest.raises(
        TypeError,
        match=re.escape("members is a sequence of identifiers, got the string 'AB'"),
    ):
        letters.without("L2", "AB", reason="AB crosses apart")


def test_left_out_of_the_tree_counts_the_instances_along_the_path() -> None:
    pair = Group.from_counts("pair", [(A, 2), (B, 0)], zero_counts=ZeroCount.DROP)
    small = Group("small", ((A, 1), (D, 2))).without("small-A", ["D"], reason="towed")
    top = Group("top", ((pair, 3), (small, 2)))
    assert tree_left_out(top) == (
        LeftOut("B", LeftOutCause.ZERO_COUNT, "count 0 in the table", 0),
        LeftOut("D", LeftOutCause.EXCLUDED, "towed", 4),
    )


def test_groups_and_members_pickle_and_copy() -> None:
    sub = Group.from_counts(
        "G", [(COLUMN, 2), (D, 0)], zero_counts=ZeroCount.DROP
    ).without("G2", ["B"], reason="r")
    for x in (A, COLUMN, sub):
        assert pickle.loads(pickle.dumps(x)) == x
        assert copy.deepcopy(x) == x
        assert fingerprint(pickle.loads(pickle.dumps(x))) == fingerprint(x)
