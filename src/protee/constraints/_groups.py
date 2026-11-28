# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Members described by their sheets, and groups of members with their
counts."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from protee.constraints._model import LeftOut, LeftOutCause, ValueSet, _name

__all__ = ["Group", "Member", "ZeroCount"]


@dataclass(frozen=True, slots=True)
class Member:
    """A described subject: an identifier and its technical sheets.

    A member describes a subject (a vehicle, a configuration of an
    equipment); it produces no constraint. Its values enter a derivation
    (see :func:`aggregate`), which gives the values of a group.

    Attributes
    ----------
    id : str
        Unique in every group the member belongs to.
    sheets : tuple of ValueSet
        Its sheets, in principle of rulebooks of kind ``description``
        (a default value taken from a text keeps its own rulebook), sorted
        by rulebook and edition. A member without a sheet is allowed: its
        values are all unknown. Two sheets never give the same parameter,
        which a derivation checks when its vocabulary resolves the aliases.

    Raises
    ------
    ValueError
        If the identifier is empty, or two sheets share a rulebook and an
        edition.
    TypeError
        If a sheet is not a :class:`ValueSet`.

    Examples
    --------
    >>> sheet = ValueSet("sheet-b", "2", {"width": Value(
    ...     2.5, Source("Sheet B", locator="p. 4"), Origin.STATEMENT, unit="m")})
    >>> Member("B", (sheet,)).sheets[0].rulebook
    'sheet-b'
    """

    id: str
    sheets: tuple[ValueSet, ...] = ()

    def __post_init__(self) -> None:
        _name("id", self.id)
        sheets = tuple(self.sheets)
        for k, sheet in enumerate(sheets):
            if not isinstance(sheet, ValueSet):
                raise TypeError(
                    f"member {self.id!r}: sheets[{k}] must be a ValueSet, got {sheet!r}"
                )
        sheets = tuple(sorted(sheets, key=lambda s: (s.rulebook, s.edition)))
        for a, b in itertools.pairwise(sheets):
            if (a.rulebook, a.edition) == (b.rulebook, b.edition):
                raise ValueError(
                    f"member {self.id!r}: two sheets for {a.rulebook} ({a.edition})"
                )
        object.__setattr__(self, "sheets", sheets)


class ZeroCount(StrEnum):
    """What a table of counts does with a row of count 0.

    - ``refuse``: the group is refused, as by its constructor;
    - ``drop``: the row is dropped and recorded in :attr:`Group.left_out`
      (cause ``zero_count``).
    """

    REFUSE = "refuse"
    DROP = "drop"


_ZERO_ROW = "count 0 in the table"


@dataclass(frozen=True, slots=True)
class Group:
    """Members, or groups, with their counts.

    A group of vehicles, the variants of an equipment, a group of groups:
    derivations read the members of the flattened group (see
    :meth:`flatten`), and the order of the members never matters (the
    order of sub-groups along a route belongs to the time module).

    Attributes
    ----------
    id : str
        Identifier, and rulebook of the values derived from the group.
    members : tuple of (Member or Group, int)
        Each member or sub-group with its count, a positive integer, sorted
        by identifier.
    values : ValueSet, optional
        Values of the group itself (gaps, density, pace), with their
        sources; :func:`aggregate` does not read them.
    left_out : tuple of LeftOut
        Rows of count 0 dropped (:meth:`from_counts`, :meth:`with_counts`)
        and members excluded (:meth:`without`), with their reason.
    variant_of : str, optional
        The group this one is a variant of.

    Raises
    ------
    ValueError
        If the group is empty, a count is not positive, an identifier
        appears twice among the members, two different members or groups
        share an identifier anywhere in the tree, or ``left_out`` records
        anything but zero rows and exclusions.
    TypeError
        If a row is not a pair of a member or a group and an integer count.

    Examples
    --------
    >>> pair = Group("pair", ((Member("A"), 2), (Member("B"), 1)))
    >>> column = Group("column", ((pair, 3), (Member("C"), 1)))
    >>> [(m.id, c) for m, c in column.flatten()]
    [('A', 6), ('B', 3), ('C', 1)]
    """

    id: str
    members: tuple[tuple[Member | Group, int], ...]
    values: ValueSet | None = None
    left_out: tuple[LeftOut, ...] = ()
    variant_of: str | None = None

    def __post_init__(self) -> None:
        _name("id", self.id)
        rows = tuple(_row(self.id, k, row) for k, row in enumerate(self.members))
        _unique_ids(self.id, (entry for entry, _ in rows))
        for entry, count in rows:
            _positive(self.id, entry.id, count)
        if not rows:
            raise ValueError(
                f"group {self.id!r} has no member: an empty group has no value "
                "to derive"
            )
        object.__setattr__(self, "members", tuple(sorted(rows, key=lambda r: r[0].id)))
        if self.values is not None and not isinstance(self.values, ValueSet):
            raise TypeError(
                f"group {self.id!r}: values must be a ValueSet, got {self.values!r}"
            )
        left_out = tuple(self.left_out)
        for x in left_out:
            if not isinstance(x, LeftOut):
                raise TypeError(f"group {self.id!r}: left_out holds LeftOut records")
            if x.cause not in (LeftOutCause.ZERO_COUNT, LeftOutCause.EXCLUDED):
                raise ValueError(
                    f"group {self.id!r}: left_out records zero counts and "
                    "exclusions only"
                )
        object.__setattr__(
            self,
            "left_out",
            tuple(
                sorted(left_out, key=lambda x: (x.name, x.cause, x.reason, x.instances))
            ),
        )
        if self.variant_of is not None:
            _name("variant_of", self.variant_of)
        _check_identifiers(self)

    @classmethod
    def from_counts(
        cls,
        id: str,
        counts: Iterable[tuple[Member | Group, int]],
        *,
        zero_counts: ZeroCount,
        values: ValueSet | None = None,
    ) -> Group:
        """A group from a table of counts, with a declared treatment of the
        rows of count 0.

        Parameters
        ----------
        id : str
        counts : iterable of (Member or Group, int)
        zero_counts : ZeroCount
            Without default: ``refuse`` refuses a row of count 0, ``drop``
            drops it and records it in :attr:`left_out`.
        values : ValueSet, optional

        Raises
        ------
        ValueError
            As the constructor; with ``drop``, also when every row is 0
            (the group is empty).

        Examples
        --------
        >>> table = [(Member("A"), 2), (Member("B"), 0)]
        >>> g = Group.from_counts("G", table, zero_counts=ZeroCount.DROP)
        >>> [m.id for m, _ in g.members], [x.name for x in g.left_out]
        (['A'], ['B'])
        """
        policy = ZeroCount(zero_counts)
        rows = [_row(id, k, row) for k, row in enumerate(counts)]
        _unique_ids(id, (entry for entry, _ in rows))
        kept = rows
        dropped: list[LeftOut] = []
        if policy is ZeroCount.DROP:
            kept = [r for r in rows if not _is_zero(r[1])]
            dropped = [
                LeftOut(entry.id, LeftOutCause.ZERO_COUNT, _ZERO_ROW, 0)
                for entry, count in rows
                if _is_zero(count)
            ]
        return cls(id, tuple(kept), values=values, left_out=tuple(dropped))

    def with_counts(
        self, id: str, counts: Mapping[str, int], *, zero_counts: ZeroCount
    ) -> Group:
        """A variant with other counts of some direct members, the base of a
        sensitivity analysis.

        The other members keep their counts; a deeper variant is built on
        the sub-group, then into a group of its own.

        Parameters
        ----------
        id : str
            A new identifier: the variant is a group of its own.
        counts : mapping of str to int
            New counts, by identifier of a direct member.
        zero_counts : ZeroCount
            As in :meth:`from_counts`.

        Returns
        -------
        Group
            With ``variant_of`` this group, and the rows it has left out.

        Raises
        ------
        ValueError
            If the identifier is this group's, or a key is not a direct
            member.
        """
        _name("id", id)
        _new_id(self, id)
        changed = dict(counts)
        direct = {entry.id for entry, _ in self.members}
        for key in sorted(changed):
            if key not in direct:
                raise ValueError(f"group {self.id!r} has no direct member {key!r}")
        rows = [(entry, changed.get(entry.id, c)) for entry, c in self.members]
        variant = Group.from_counts(
            id, rows, zero_counts=zero_counts, values=self.values
        )
        return replace(
            variant, left_out=self.left_out + variant.left_out, variant_of=self.id
        )

    def without(self, id: str, members: Iterable[str], *, reason: str) -> Group:
        """A declared sub-group: this group without some members or
        sub-groups, at any depth, with the reason.

        Parameters
        ----------
        id : str
            A new identifier.
        members : iterable of str
            Identifiers of members or sub-groups to exclude.
        reason : str
            Why they are excluded.

        Returns
        -------
        Group
            With ``variant_of`` this group. Each excluded identifier is
            recorded in :attr:`left_out` with the reason and its instances;
            a sub-group emptied by the exclusion disappears, recorded with
            the reason ``"all its members excluded: <reason>"``.

        Raises
        ------
        ValueError
            If the identifier is this group's, the reason is empty, an
            identifier is not in the group, or nothing would be left.

        Examples
        --------
        >>> g = Group("G", ((Member("A"), 2), (Member("B"), 1)))
        >>> sub = g.without("G-B", ["A"], reason="A crosses apart")
        >>> [m.id for m, _ in sub.flatten()], sub.left_out[0].instances
        (['B'], 2)
        """
        _name("id", id)
        _new_id(self, id)
        _name("reason", reason)
        names = sorted(set(members))
        if not names:
            raise ValueError("without needs at least one identifier to exclude")
        present = {node.id for node in _nodes(self)} - {self.id}
        for name in names:
            _name("member", name)
            if name not in present:
                raise ValueError(f"group {self.id!r} has no member {name!r}")
        removed = dict.fromkeys(names, 0)
        emptied: set[str] = set()
        rows = _prune(self, 1, frozenset(names), removed, emptied)
        if not rows:
            raise ValueError(f"group {id!r}: excluding {names} leaves no member")
        excluded = LeftOutCause.EXCLUDED
        records = [LeftOut(n, excluded, reason, k) for n, k in removed.items()]
        records += [
            LeftOut(g, excluded, f"all its members excluded: {reason}", 0)
            for g in sorted(emptied)
        ]
        return Group(
            id,
            tuple(rows),
            values=self.values,
            left_out=self.left_out + tuple(records),
            variant_of=self.id,
        )

    def flatten(self) -> tuple[tuple[Member, int], ...]:
        """The members at the leaves, each with its multiplicity (the product
        of the counts along its path; summed when a member appears in
        several sub-groups), sorted by identifier."""
        found: dict[str, tuple[Member, int]] = {}
        for member, count in _leaves(self, 1):
            known = found.get(member.id)
            found[member.id] = (member, count + (0 if known is None else known[1]))
        return tuple(found[k] for k in sorted(found))


def _row(group: str, k: int, row: object) -> tuple[Member | Group, int]:
    if not isinstance(row, tuple) or len(row) != 2:
        raise TypeError(f"group {group!r}: members[{k}] must be a (member, count) pair")
    entry, count = row
    if not isinstance(entry, (Member, Group)):
        raise TypeError(
            f"group {group!r}: members[{k}] must hold a Member or a Group, "
            f"got {entry!r}"
        )
    return entry, count


def _is_zero(count: object) -> bool:
    return isinstance(count, int) and not isinstance(count, bool) and count == 0


def _positive(group: str, member: str, count: object) -> None:
    text = (
        f"group {group!r}: the count of {member!r} must be a positive integer, "
        f"got {count!r}"
    )
    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError(text)
    if count <= 0:
        if count == 0:
            text += (
                "; Group.from_counts(..., zero_counts=ZeroCount.DROP) drops zero "
                "rows and records them"
            )
        raise ValueError(text)


def _unique_ids(group: str, entries: Iterable[Member | Group]) -> None:
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise ValueError(f"group {group!r}: {entry.id!r} appears twice")
        seen.add(entry.id)


def _new_id(group: Group, id: str) -> None:
    if id == group.id:
        raise ValueError(
            f"a variant of group {group.id!r} needs an identifier of its own"
        )


def _nodes(group: Group) -> Iterator[Member | Group]:
    """The group, then every member and sub-group below it."""
    yield group
    for entry, _ in group.members:
        if isinstance(entry, Group):
            yield from _nodes(entry)
        else:
            yield entry


def _check_identifiers(group: Group) -> None:
    """In the whole tree, an identifier names one object."""
    seen: dict[str, Member | Group] = {}
    for node in _nodes(group):
        other = seen.setdefault(node.id, node)
        if other is node or other == node:
            continue
        if isinstance(node, Member) and isinstance(other, Member):
            what = "two different members share"
        elif isinstance(node, Group) and isinstance(other, Group):
            what = "two different groups share"
        else:
            what = "a member and a group share"
        raise ValueError(f"group {group.id!r}: {what} the identifier {node.id!r}")


def _leaves(group: Group, multiplicity: int) -> Iterator[tuple[Member, int]]:
    for entry, count in group.members:
        if isinstance(entry, Group):
            yield from _leaves(entry, multiplicity * count)
        else:
            yield entry, multiplicity * count


def _size(entry: Member | Group) -> int:
    """The instances of members an entry stands for."""
    if isinstance(entry, Member):
        return 1
    return sum(count * _size(e) for e, count in entry.members)


def _prune(
    group: Group,
    multiplicity: int,
    names: frozenset[str],
    removed: dict[str, int],
    emptied: set[str],
) -> list[tuple[Member | Group, int]]:
    """The rows of ``group`` without the entries named, at any depth; the
    instances removed are added to ``removed``, the sub-groups emptied to
    ``emptied``."""
    rows: list[tuple[Member | Group, int]] = []
    for entry, count in group.members:
        if entry.id in names:
            removed[entry.id] += multiplicity * count * _size(entry)
        elif isinstance(entry, Member):
            rows.append((entry, count))
        else:
            sub = _prune(entry, multiplicity * count, names, removed, emptied)
            if not sub:
                emptied.add(entry.id)
            elif sub == list(entry.members):
                rows.append((entry, count))
            else:
                rows.append((replace(entry, members=tuple(sub)), count))
    return rows


def tree_left_out(group: Group) -> tuple[LeftOut, ...]:
    """The records of :attr:`Group.left_out` of the whole tree, the
    instances multiplied by the counts along the path, and summed when a
    sub-group appears several times; sorted."""
    found: dict[tuple[str, LeftOutCause, str], int] = {}

    def walk(g: Group, multiplicity: int) -> None:
        for x in g.left_out:
            key = (x.name, x.cause, x.reason)
            found[key] = found.get(key, 0) + multiplicity * x.instances
        for entry, count in g.members:
            if isinstance(entry, Group):
                walk(entry, multiplicity * count)

    walk(group, 1)
    return tuple(LeftOut(*key, k) for key, k in sorted(found.items()))
