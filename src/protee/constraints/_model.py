# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Sources, rulebooks, values and requirements."""

import itertools
import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType

from protee.constraints._patterns import PATTERNS, Pattern

__all__ = [
    "Correspondence",
    "Origin",
    "Parameter",
    "Relation",
    "Requirement",
    "RequirementSet",
    "ResolvedValues",
    "Rulebook",
    "RulebookKind",
    "Source",
    "Value",
    "ValueSet",
    "resolve_values",
]

type Datum = int | float | str


def _name(what: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string, got {value!r}")
    return value


def _texts(what: str, texts: Mapping[str, str]) -> Mapping[str, str]:
    out = dict(texts)
    for lang, text in out.items():
        _name(f"{what}[{lang!r}]", text)
    if "en" not in out:
        raise ValueError(f"{what}: an English text ('en') is required")
    return MappingProxyType(out)


def _names(what: str, mapping: Mapping[str, str]) -> Mapping[str, str]:
    out = dict(mapping)
    for key, value in out.items():
        _name(f"{what} key", key)
        _name(f"{what}[{key!r}]", value)
    return MappingProxyType(out)


@dataclass(frozen=True, slots=True)
class Source:
    """Where an input (a requirement, a value) comes from.

    Attributes
    ----------
    document : str
        The text, or the statement, the answer or the declared choice.
    rulebook : str, optional
        Identifier of the :class:`Rulebook` the document belongs to.
    edition : str, optional
    locator : str, optional
        Paragraph, page or table within the document.
    link : str, optional
        Official link, when there is one.
    citation_checked : bool
        Whether the citation was checked again against the document.
    """

    document: str
    rulebook: str | None = None
    edition: str | None = None
    locator: str | None = None
    link: str | None = None
    citation_checked: bool = False

    def __post_init__(self) -> None:
        _name("document", self.document)


class RulebookKind(StrEnum):
    """Nature of a rulebook."""

    DOCTRINE = "doctrine"
    REGULATION = "regulation"
    STANDARD = "standard"
    CLIENT_SPECIFICATION = "client_specification"


@dataclass(frozen=True, slots=True)
class Rulebook:
    """A set of rules requirements and values come from.

    A doctrine, a regulation, a standard, or the specification of a client.

    Attributes
    ----------
    id : str
    kind : RulebookKind
    title : mapping of str to str
        Title by language; English (``"en"``) is required.
    edition : str
    link : str, optional
        Official link, when there is one.
    """

    id: str
    kind: RulebookKind
    title: Mapping[str, str]
    edition: str
    link: str | None = None

    def __post_init__(self) -> None:
        _name("id", self.id)
        _name("edition", self.edition)
        object.__setattr__(self, "kind", RulebookKind(self.kind))
        object.__setattr__(self, "title", _texts("title", self.title))


class Origin(StrEnum):
    """Where a value comes from: a rulebook, a statement, a choice, or a
    provisional value waiting for its source."""

    RULEBOOK = "rulebook"
    STATEMENT = "statement"
    CHOICE = "choice"
    PROVISIONAL = "provisional"


@dataclass(frozen=True, slots=True)
class Value:
    """The value of a parameter, with its source.

    Attributes
    ----------
    value : int, float, str or None
        ``None`` means *to be set*: a requirement that needs it is then not
        applicable, with this reason, and never decided silently.
        ``math.inf`` stands for no limit.
    source : Source
    origin : Origin
    unit : str, optional
        Must be the unit of the :class:`Parameter`.
    precedence : int
        Between values of the same parameter from several value sets, the
        highest precedence wins; equal precedences must agree.
    justification : str, optional
        Why the value was chosen; required for a chosen objective.
    """

    value: int | float | str | None
    source: Source
    origin: Origin
    unit: str | None = None
    precedence: int = 0
    justification: str | None = None

    def __post_init__(self) -> None:
        v = self.value
        if isinstance(v, bool) or not (v is None or isinstance(v, (int, float, str))):
            raise TypeError(f"a value must be a number, a string or None, got {v!r}")
        if isinstance(v, float) and math.isnan(v):
            raise ValueError("a value cannot be NaN; use None for a value to be set")
        if isinstance(self.precedence, bool) or not isinstance(self.precedence, int):
            raise TypeError(f"precedence must be an integer, got {self.precedence!r}")
        object.__setattr__(self, "origin", Origin(self.origin))

    @property
    def to_be_set(self) -> bool:
        """True when the value is still to be set."""
        return self.value is None


@dataclass(frozen=True, slots=True)
class ValueSet:
    """The values of a rulebook and an edition, by parameter.

    Attributes
    ----------
    rulebook : str
        Identifier of the rulebook.
    edition : str
    values : mapping of str to Value
        By canonical parameter name, or by the alias the rulebook uses. A
        source that names no rulebook or no edition is given those of the
        set, so that every value keeps them.

    Raises
    ------
    ValueError
        If the source of a value cites another rulebook or edition.
    """

    rulebook: str
    edition: str
    values: Mapping[str, Value]

    def __post_init__(self) -> None:
        _name("rulebook", self.rulebook)
        _name("edition", self.edition)
        values = {}
        for key, value in dict(self.values).items():
            _name("parameter", key)
            if not isinstance(value, Value):
                raise TypeError(f"values[{key!r}] must be a Value, got {value!r}")
            src = value.source
            for what, cited, own in (
                ("rulebook", src.rulebook, self.rulebook),
                ("edition", src.edition, self.edition),
            ):
                if cited is not None and cited != own:
                    raise ValueError(
                        f"values[{key!r}]: its source cites the {what} {cited!r}, "
                        f"the value set is {own!r}"
                    )
            values[key] = replace(
                value,
                source=replace(src, rulebook=self.rulebook, edition=self.edition),
            )
        object.__setattr__(self, "values", MappingProxyType(values))


@dataclass(frozen=True, slots=True)
class Parameter:
    """A named parameter, with its unit and its aliases.

    Attributes
    ----------
    name : str
        Canonical name.
    unit : str, optional
    aliases : mapping of str to str
        The name each rulebook (by identifier) uses for this parameter.
    """

    name: str
    unit: str | None = None
    aliases: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _name("name", self.name)
        object.__setattr__(self, "aliases", _names("aliases", self.aliases))


@dataclass(frozen=True, slots=True)
class Requirement:
    """A normalized statement taken from a source: an *exigence*.

    A requirement is not a constraint: its pattern turns it into an
    effect on the graph (see :func:`evaluate`).

    Attributes
    ----------
    id : str
        Explicit and unique identifier.
    pattern : str
        Name of a pattern of the registry (see :func:`patterns`).
    statement : mapping of str to str
        Normalized statement by language; English (``"en"``) is required.
    source : Source
    parameters : mapping of str to str
        Canonical parameter name bound to each value role of the pattern.
    attributes : mapping of str to str
        Arc attribute bound to each attribute role of the pattern.
    scope : frozenset of str, optional
        Element types the requirement applies to (see
        :attr:`ArcData.element`), not empty; all arcs when ``None``.
    """

    id: str
    pattern: str
    statement: Mapping[str, str]
    source: Source
    parameters: Mapping[str, str] = field(default_factory=dict)
    attributes: Mapping[str, str] = field(default_factory=dict)
    scope: frozenset[str] | None = None

    def __post_init__(self) -> None:
        _name("id", self.id)
        object.__setattr__(self, "statement", _texts("statement", self.statement))
        object.__setattr__(self, "parameters", _names("parameters", self.parameters))
        object.__setattr__(self, "attributes", _names("attributes", self.attributes))
        if self.scope is not None:
            scope = frozenset(self.scope)
            if not scope:
                raise ValueError(f"requirement {self.id}: an empty scope covers no arc")
            for label in scope:
                _name("scope label", label)
            object.__setattr__(self, "scope", scope)
        pattern = PATTERNS.get(self.pattern)
        if pattern is None:
            raise ValueError(f"requirement {self.id}: unknown pattern {self.pattern!r}")
        _check_roles(self, pattern)


def _check_roles(requirement: Requirement, pattern: Pattern) -> None:
    allowed = set(pattern.parameters) | set(pattern.optional)
    bound = set(requirement.parameters)
    if missing := set(pattern.parameters) - bound:
        raise ValueError(
            f"requirement {requirement.id}: parameter roles {sorted(missing)} "
            f"of {pattern.name} are not bound"
        )
    if extra := bound - allowed:
        raise ValueError(
            f"requirement {requirement.id}: {pattern.name} has no parameter "
            f"role {sorted(extra)}"
        )
    if set(requirement.attributes) != set(pattern.attributes):
        raise ValueError(
            f"requirement {requirement.id}: {pattern.name} needs exactly the "
            f"attribute roles {list(pattern.attributes)}, got "
            f"{sorted(requirement.attributes)}"
        )


@dataclass(frozen=True, slots=True)
class RequirementSet:
    """Requirements checked together, with the names they cite.

    Every identifier cited must exist, and identifiers are unique: a
    requirement, a parameter and a rulebook are found by name, never by
    position or range.

    Attributes
    ----------
    requirements : tuple of Requirement
    parameters : tuple of Parameter
        The vocabulary of parameters the requirements bind.
    rulebooks : tuple of Rulebook
        The rulebooks the sources cite.

    Raises
    ------
    ValueError
        If an identifier repeats, or a parameter or a rulebook cited is not
        declared.
    """

    requirements: tuple[Requirement, ...]
    parameters: tuple[Parameter, ...] = ()
    rulebooks: tuple[Rulebook, ...] = ()
    _by_id: Mapping[str, Requirement] = field(init=False, repr=False, compare=False)
    _params: Mapping[str, Parameter] = field(init=False, repr=False, compare=False)
    _books: Mapping[str, Rulebook] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        reqs = tuple(self.requirements)
        by_id = _unique("requirement", ((r.id, r) for r in reqs))
        params = _unique("parameter", ((p.name, p) for p in self.parameters))
        books = _unique("rulebook", ((b.id, b) for b in self.rulebooks))
        for p in params.values():
            for book in p.aliases:
                if book not in books:
                    raise ValueError(f"parameter {p.name}: unknown rulebook {book!r}")
        for r in reqs:
            for name in r.parameters.values():
                if name not in params:
                    raise ValueError(f"requirement {r.id}: unknown parameter {name!r}")
            if r.source.rulebook is not None and r.source.rulebook not in books:
                raise ValueError(
                    f"requirement {r.id}: unknown rulebook {r.source.rulebook!r}"
                )
        object.__setattr__(self, "requirements", reqs)
        object.__setattr__(self, "parameters", tuple(params.values()))
        object.__setattr__(self, "rulebooks", tuple(books.values()))
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))
        object.__setattr__(self, "_params", MappingProxyType(params))
        object.__setattr__(self, "_books", MappingProxyType(books))

    def __iter__(self) -> Iterator[Requirement]:
        return iter(self.requirements)

    def __len__(self) -> int:
        return len(self.requirements)

    def __getitem__(self, id: str) -> Requirement:
        """The requirement of identifier ``id``."""
        return self._by_id[id]

    def parameter(self, name: str) -> Parameter:
        """The parameter of canonical name ``name``."""
        return self._params[name]

    def rulebook(self, id: str) -> Rulebook:
        """The rulebook of identifier ``id``."""
        return self._books[id]


def _unique[T](what: str, items: Iterable[tuple[str, T]]) -> dict[str, T]:
    out: dict[str, T] = {}
    for key, item in items:
        if key in out:
            raise ValueError(f"duplicate {what} identifier {key!r}")
        out[key] = item
    return out


@dataclass(frozen=True, slots=True)
class ResolvedValues:
    """The value retained for each parameter, after precedence.

    Attributes
    ----------
    values : mapping of str to Value
        By canonical parameter name.
    discarded : mapping of str to tuple of Value
        The values of lower precedence, kept for the provenance.
    unused : tuple of str
        Parameters given a value but bound by no requirement.
    missing : tuple of str
        Parameters bound by a requirement but given no value: the
        requirements that need them are not applicable.
    """

    values: Mapping[str, Value]
    discarded: Mapping[str, tuple[Value, ...]]
    unused: tuple[str, ...]
    missing: tuple[str, ...]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "values", MappingProxyType(dict(self.values)))
        set_(
            self,
            "discarded",
            MappingProxyType({k: tuple(v) for k, v in self.discarded.items()}),
        )
        set_(self, "unused", tuple(self.unused))
        set_(self, "missing", tuple(self.missing))

    def get(self, name: str) -> Value | None:
        """The value retained for ``name``, or ``None``."""
        return self.values.get(name)


def resolve_values(
    value_sets: Iterable[ValueSet], requirements: RequirementSet
) -> ResolvedValues:
    """Retain one value per parameter, by declared precedence.

    Parameters
    ----------
    value_sets : iterable of ValueSet
        At most one per rulebook and edition; their order does not matter.
    requirements : RequirementSet
        Gives the parameters, their units and their aliases.

    Returns
    -------
    ResolvedValues
        Between agreeing values of the same precedence, the one of the
        first rulebook and edition (in alphabetical order) is retained,
        and the others are kept with the discarded values.

    Raises
    ------
    ValueError
        If two value sets share a rulebook and an edition, a value set
        names an unknown parameter, gives a unit other than the
        parameter's, gives a parameter twice, if two values of the same
        parameter disagree with the same precedence (the disagreement must
        be declared by a precedence), or if a value of an objective is
        chosen without a justification.
    """
    aliases = {
        (book, alias): p.name
        for p in requirements.parameters
        for book, alias in p.aliases.items()
    }
    known = {p.name for p in requirements.parameters}
    candidates: dict[str, list[Value]] = {}
    ordered = sorted(value_sets, key=lambda s: (s.rulebook, s.edition))
    for vs, other in itertools.pairwise(ordered):
        if (vs.rulebook, vs.edition) == (other.rulebook, other.edition):
            raise ValueError(
                f"two value sets for {vs.rulebook} ({vs.edition}): merge them"
            )
    for vs in ordered:
        seen: set[str] = set()
        for key, value in vs.values.items():
            name = key if key in known else aliases.get((vs.rulebook, key))
            if name is None:
                raise ValueError(
                    f"value set {vs.rulebook} ({vs.edition}): unknown parameter {key!r}"
                )
            if name in seen:
                raise ValueError(
                    f"value set {vs.rulebook} ({vs.edition}): parameter {name!r} "
                    "given twice"
                )
            seen.add(name)
            unit = requirements.parameter(name).unit
            if value.unit != unit:
                raise ValueError(
                    f"value set {vs.rulebook} ({vs.edition}): {key!r} in "
                    f"{value.unit!r}, expected {unit!r}"
                )
            candidates.setdefault(name, []).append(value)
    retained: dict[str, Value] = {}
    discarded: dict[str, tuple[Value, ...]] = {}
    for name, values in sorted(candidates.items()):
        ranked = sorted(values, key=lambda v: -v.precedence)
        top = [v for v in ranked if v.precedence == ranked[0].precedence]
        if len({v.value for v in top}) > 1:
            raise ValueError(
                f"parameter {name!r}: values {[v.value for v in top]} disagree "
                "with the same precedence"
            )
        retained[name] = ranked[0]
        if len(ranked) > 1:
            discarded[name] = tuple(ranked[1:])
    for r in requirements:
        if r.pattern == "objective":
            for v in candidates.get(r.parameters["criterion"], ()):
                if v.origin is Origin.CHOICE and not v.justification:
                    raise ValueError(
                        f"requirement {r.id}: a chosen objective needs a justification"
                    )
    used = {name for r in requirements for name in r.parameters.values()}
    return ResolvedValues(
        values=MappingProxyType(retained),
        discarded=MappingProxyType(discarded),
        unused=tuple(sorted(set(candidates) - used)),
        missing=tuple(sorted(used - set(candidates))),
    )


class Relation(StrEnum):
    """Qualified relation between two notions (SKOS mapping relations)."""

    EXACT = "exact"
    CLOSE = "close"
    BROAD = "broad"
    NARROW = "narrow"
    RELATED = "related"


@dataclass(frozen=True, slots=True)
class Correspondence:
    """How a notion of one rulebook relates to a notion of another.

    The relation is qualified, never a bare equivalence: a load class is
    not a mass limit in tonnes.

    Attributes
    ----------
    pattern : str
        The pattern both notions are expressed with.
    rulebook : str
    notion : str
        The notion in ``rulebook``.
    other_rulebook : str
    other_notion : str
    relation : Relation
        From ``notion`` to ``other_notion``, as in SKOS: ``broad`` means
        that ``other_notion`` is broader.
    note : str, optional
        Differences of definition.
    """

    pattern: str
    rulebook: str
    notion: str
    other_rulebook: str
    other_notion: str
    relation: Relation
    note: str | None = None

    def __post_init__(self) -> None:
        if self.pattern not in PATTERNS:
            raise ValueError(f"unknown pattern {self.pattern!r}")
        for what in ("rulebook", "notion", "other_rulebook", "other_notion"):
            _name(what, getattr(self, what))
        if self.rulebook == self.other_rulebook:
            raise ValueError("a correspondence relates two different rulebooks")
        object.__setattr__(self, "relation", Relation(self.relation))
