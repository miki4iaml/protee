# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Sources, rulebooks, values and requirements; the trace of a derived
value.

Tables are :class:`~protee._frozen.FrozenMap`: read-only, they pickle and
copy, so that a value set, a group of members or derived values can leave
a worker process.
"""

from __future__ import annotations

import itertools
import math
import numbers
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from protee._fingerprint import freeze
from protee._frozen import FrozenMap
from protee.constraints._derivations import DERIVATIONS, ENVELOPES, ORDERS, STRICTER
from protee.constraints._patterns import PATTERNS, Pattern

__all__ = [
    "Assumption",
    "Conversion",
    "Correspondence",
    "Derivation",
    "DerivationInput",
    "LeftOut",
    "LeftOutCause",
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
    "ValueState",
    "resolve_values",
]

type Datum = int | float | str


def _name(what: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string, got {value!r}")
    return value


def _sequence(what: str, given: object, of: str = "names") -> None:
    """Refuse a bare string where a sequence of names is expected: it would
    be read as its characters.

    Raises
    ------
    TypeError
        If ``given`` is a string.
    """
    if isinstance(given, str):
        raise TypeError(f"{what} is a sequence of {of}, got the string {given!r}")


def _sorted_names(what: str, names: Iterable[str]) -> tuple[str, ...]:
    """Sorted, without duplicate: an order that does not depend on the
    caller's."""
    _sequence(what, names)
    out = tuple(sorted(set(names)))
    for n in out:
        _name(what, n)
    return out


def _plain_number(x: object) -> int | float | None:
    """``x`` as the Python number of the same value: an integer of any type
    (a NumPy integer, say) as an ``int``, a floating number of any type (a
    NumPy float) as a ``float`` when it is one exactly; ``None`` for
    anything else, a boolean, a fraction and a decimal included."""
    if isinstance(x, bool) or not isinstance(x, numbers.Real):
        return None
    if isinstance(x, numbers.Integral):
        return int(x)
    if isinstance(x, numbers.Rational):  # a fraction: not a float
        return None
    y = float(x)
    # A float of more precision than a float (a long double) may not be one.
    return y if y == x or math.isnan(y) else None


def _datum_text(x: Datum, unit: str | None = None) -> str:
    """A value as messages and summaries write it: a label quoted; a
    number exactly, an integral float without its decimals, any other as
    its shortest form (``repr``); then its unit."""
    if isinstance(x, str):
        return repr(x)
    if isinstance(x, float) and x.is_integer() and abs(x) < 2**53:
        shown = str(int(x))
    else:
        shown = repr(x)
    return shown if unit is None else f"{shown} {unit}"


def _count(what: str, x: object, *, least: int) -> int:
    if isinstance(x, bool) or not isinstance(x, int):
        raise TypeError(f"{what} must be an integer, got {x!r}")
    if x < least:
        raise ValueError(f"{what} must be at least {least}, got {x}")
    return x


def _texts(what: str, texts: Mapping[str, str]) -> Mapping[str, str]:
    out = dict(texts)
    for lang, text in out.items():
        _name(f"{what}[{lang!r}]", text)
    if "en" not in out:
        raise ValueError(f"{what}: an English text ('en') is required")
    return FrozenMap(out)


def _names(what: str, mapping: Mapping[str, str]) -> Mapping[str, str]:
    out = dict(mapping)
    for key, value in out.items():
        _name(f"{what} key", key)
        _name(f"{what}[{key!r}]", value)
    return FrozenMap(out)


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
    """Nature of a rulebook.

    ``description`` is the technical sheet of a member (see
    :class:`Member`): it describes a subject, never a requirement.
    """

    DOCTRINE = "doctrine"
    REGULATION = "regulation"
    STANDARD = "standard"
    CLIENT_SPECIFICATION = "client_specification"
    DESCRIPTION = "description"


@dataclass(frozen=True, slots=True)
class Rulebook:
    """A set of rules requirements and values come from.

    A doctrine, a regulation, a standard, the specification of a client,
    or the description of a member (its technical sheet).

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
    """Where a value comes from: a rulebook, a statement, a choice, a
    provisional value waiting for its source, or a derivation of the
    registry (see :func:`derivations`): the envelope of a group, the class
    of a subject, the value a class selects, the length of a column."""

    RULEBOOK = "rulebook"
    STATEMENT = "statement"
    CHOICE = "choice"
    PROVISIONAL = "provisional"
    DERIVED = "derived"


class ValueState(StrEnum):
    """The four states of the value of a member for a parameter.

    - ``known``: a value is given;
    - ``unknown``: no value is given, or the value is to be set;
    - ``assumed``: unknown, and replaced by the value a derivation assumes
      (see :class:`OnUnknown`); never stored on a member;
    - ``not_applicable``: the parameter has no meaning for the member (it
      is carried, it has no such part), declared with its reason.
    """

    KNOWN = "known"
    UNKNOWN = "unknown"
    ASSUMED = "assumed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class Value:
    """The value of a parameter, with its source.

    Attributes
    ----------
    value : int, float, str or None
        ``None`` means *to be set* (or *not applicable*, when
        ``not_applicable`` gives the reason): a requirement that needs it is
        then not applicable, with this reason, and never decided silently;
        an admissibility requirement whose value is to be set by an envelope
        reads instead the bound of its derivation (see :func:`evaluate`).
        ``math.inf`` stands for no limit. A number of another type (a NumPy
        integer or float) is kept as the ``int`` or the ``float`` of the
        same value.
    source : Source
    origin : Origin
    unit : str, optional
        Must be the unit of the :class:`Parameter`.
    precedence : int
        Between values of the same parameter from several value sets, the
        highest precedence wins; equal precedences must agree.
    justification : str, optional
        Why the value was chosen; required for a chosen objective.
    not_applicable : str, optional
        Why the parameter has no value: a declared mark, never ``NaN``.
        The value is then ``None``.
    derivation : Derivation, optional
        How a derived value was obtained: required for the origin
        ``derived``, and for it only.

    Raises
    ------
    ValueError
        If the value is NaN, a value not applicable has a value, a derived
        value has no derivation, another value has one, or a bound is given
        for a value that is not to be set.
    TypeError
        If the value is neither a number, a string nor ``None`` (a boolean,
        a fraction, a decimal are refused), or the precedence is not an
        integer.

    Examples
    --------
    >>> sheet = Source("Sheet of member B", locator="p. 4")
    >>> Value(None, sheet, Origin.STATEMENT, not_applicable="carried by A").state
    <ValueState.NOT_APPLICABLE: 'not_applicable'>
    >>> Value(None, sheet, Origin.STATEMENT).to_be_set
    True
    """

    value: int | float | str | None
    source: Source
    origin: Origin
    unit: str | None = None
    precedence: int = 0
    justification: str | None = None
    not_applicable: str | None = None
    derivation: Derivation | None = None

    def __post_init__(self) -> None:
        v = self.value
        if not (v is None or isinstance(v, str)):
            number = _plain_number(v)
            if number is None:
                raise TypeError(
                    f"a value must be a number, a string or None, got {v!r}"
                )
            object.__setattr__(self, "value", number)
            v = number
        if isinstance(v, float) and math.isnan(v):
            raise ValueError("a value cannot be NaN; use None for a value to be set")
        if isinstance(self.precedence, bool) or not isinstance(self.precedence, int):
            raise TypeError(f"precedence must be an integer, got {self.precedence!r}")
        object.__setattr__(self, "origin", Origin(self.origin))
        if self.not_applicable is not None:
            _name("not_applicable", self.not_applicable)
            if v is not None:
                raise ValueError(f"a value not applicable has no value, got {v!r}")
        d = self.derivation
        if d is not None and not isinstance(d, Derivation):
            raise TypeError(f"derivation must be a Derivation, got {d!r}")
        if self.origin is Origin.DERIVED and d is None:
            raise ValueError("a derived value carries its derivation")
        if d is not None and self.origin is not Origin.DERIVED:
            raise ValueError(
                "only a derived value carries a derivation "
                f"(origin {self.origin.value!r})"
            )
        if d is not None and d.bound is not None and not self.to_be_set:
            raise ValueError(
                "only a value to be set carries a bound on its unknown value"
            )

    @property
    def to_be_set(self) -> bool:
        """True when the value is still to be set: no value, and not
        declared not applicable."""
        return self.value is None and self.not_applicable is None

    @property
    def state(self) -> ValueState:
        """``known``, ``unknown`` (to be set) or ``not_applicable``; never
        ``assumed``, which only a derivation records."""
        if self.not_applicable is not None:
            return ValueState.NOT_APPLICABLE
        if self.value is None:
            return ValueState.UNKNOWN
        return ValueState.KNOWN


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
        object.__setattr__(self, "values", FrozenMap(values))


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
        object.__setattr__(self, "_by_id", FrozenMap(by_id))
        object.__setattr__(self, "_params", FrozenMap(params))
        object.__setattr__(self, "_books", FrozenMap(books))

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
        set_(self, "values", FrozenMap(self.values))
        set_(
            self,
            "discarded",
            FrozenMap({k: tuple(v) for k, v in self.discarded.items()}),
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
        be declared by a precedence; a value not applicable and a value to
        be set disagree, and so do two values to be set unless they may
        take the same values: two values to be set that are not
        envelopes, or two envelopes to be set that allow the same
        interval of numbers or the same labels; see :func:`evaluate`), or
        if a value of an objective is chosen without a justification.
    """
    aliases = _aliases(requirements.parameters)
    known = {p.name for p in requirements.parameters}
    candidates: dict[str, list[Value]] = {}
    ordered = sorted(value_sets, key=lambda s: (s.rulebook, s.edition))
    for vs, other in itertools.pairwise(ordered):
        if (vs.rulebook, vs.edition) == (other.rulebook, other.edition):
            raise ValueError(
                f"two value sets for {vs.rulebook} ({vs.edition}): merge them"
            )
    for vs in ordered:
        where = f"value set {vs.rulebook} ({vs.edition})"
        for name, (key, value) in _by_name(vs, known, aliases, where).items():
            unit = requirements.parameter(name).unit
            if value.unit != unit:
                raise ValueError(
                    f"{where}: {key!r} in {value.unit!r}, expected {unit!r}"
                )
            candidates.setdefault(name, []).append(value)
    retained: dict[str, Value] = {}
    discarded: dict[str, tuple[Value, ...]] = {}
    for name, values in sorted(candidates.items()):
        ranked = sorted(values, key=lambda v: -v.precedence)
        top = [v for v in ranked if v.precedence == ranked[0].precedence]
        if len({_agreement(v) for v in top}) > 1:
            shown = [_disagreeing(v) for v in top]
            raise ValueError(
                f"parameter {name!r}: values {shown} disagree with the same precedence"
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
        values=retained,
        discarded=discarded,
        unused=tuple(sorted(set(candidates) - used)),
        missing=tuple(sorted(used - set(candidates))),
    )


def _bound_side(value: Value) -> tuple[str, Datum] | None:
    """The side and the bound of a value to be set whose derivation bounds
    it, ``None`` for any other value."""
    d = value.derivation
    if not value.to_be_set or d is None or d.bound is None:
        return None
    return ENVELOPES.get((d.name, d.rule), "bounded by"), d.bound


def _may_take(value: Value) -> tuple[Datum, ...] | None:
    """The values a value to be set by an envelope (``max``, ``min``,
    ``strictest``, a classification) may take, as the admissibility
    patterns read them: the ends of an interval of numbers (its bound and
    an infinity on the side of the bound; ``-inf`` and ``inf`` without a
    bound), or the labels of its order at least as strict as its bound
    (every label without a bound, none when the order is not known);
    ``None`` for any other value, which leaves its requirement not
    applicable. A label bound outside its order is returned alone, for
    :func:`evaluate` to refuse."""
    d = value.derivation
    if not value.to_be_set or d is None:
        return None
    side = ENVELOPES.get((d.name, d.rule))
    if side is None:
        return None
    if side != STRICTER:
        if d.bound is None:
            return (-math.inf, math.inf)
        return (d.bound, math.inf if side == "at least" else -math.inf)
    order = d.settings.get(ORDERS[d.name])
    if d.bound is None:
        return order if isinstance(order, tuple) else ()
    if not isinstance(order, tuple) or d.bound not in order:
        return (d.bound,)
    return order[order.index(d.bound) :]


def _agreement(value: Value) -> tuple[object, ...]:
    """What two values of the same precedence share when they agree: the
    value, whether it is not applicable, and for a value to be set by an
    envelope, the values it may take, which decide arcs (a value to be set
    otherwise decides none)."""
    return (value.value, value.not_applicable is not None, _may_take(value))


def _disagreeing(value: Value) -> object:
    """A value, as a disagreement shows it."""
    if value.not_applicable is not None:
        return "not applicable"
    taken = _may_take(value)
    d = value.derivation
    if taken is None or d is None:
        return value.value
    side = ENVELOPES[d.name, d.rule]
    bound = "" if d.bound is None else f", {side} {_datum_text(d.bound, value.unit)}"
    if side == STRICTER:
        return f"to be set{bound}: one of {list(taken)}"
    return f"to be set{bound}" if bound else f"to be set by {d.rule}, without a bound"


def _aliases(parameters: Iterable[Parameter]) -> dict[tuple[str, str], str]:
    """The canonical name of each alias, by rulebook and alias."""
    return {
        (book, alias): p.name for p in parameters for book, alias in p.aliases.items()
    }


def _by_name(
    value_set: ValueSet,
    known: Collection[str],
    aliases: Mapping[tuple[str, str], str],
    where: str,
    hint: str = "",
) -> dict[str, tuple[str, Value]]:
    """The values of a set by canonical name, each with its key: a key is
    a canonical name, or the alias the rulebook of the set uses.

    Raises
    ------
    ValueError
        If a key is not a parameter of the vocabulary (the message ends
        with ``hint``), or two keys name the same parameter.
    """
    out: dict[str, tuple[str, Value]] = {}
    for key, value in value_set.values.items():
        name = key if key in known else aliases.get((value_set.rulebook, key))
        if name is None:
            raise ValueError(f"{where}: unknown parameter {key!r}{hint}")
        if name in out:
            raise ValueError(f"{where}: parameter {name!r} given twice")
        out[name] = (key, value)
    return out


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


# The trace of a derived value ----------------------------------------------


class LeftOutCause(StrEnum):
    """Why a member, a group or an input takes no part in a derived value.

    - ``zero_count``: a row of count 0 dropped from a table of counts (see
      :meth:`Group.from_counts`);
    - ``excluded``: excluded from a declared sub-group (see
      :meth:`Group.without`);
    - ``not_applicable``: the value of the member is declared not
      applicable;
    - ``unknown``: the value is unknown, and left out by the policy
      ``known_only`` (see :class:`OnUnknown`).
    """

    ZERO_COUNT = "zero_count"
    EXCLUDED = "excluded"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LeftOut:
    """A member, a group or an input left out of a derived value, with its
    reason.

    Attributes
    ----------
    name : str
        The member, the group or the input.
    cause : LeftOutCause
    reason : str
        The declared justification: the reason of a sub-group, of a value
        not applicable, of the policy ``known_only``; ``"count 0 in the
        table"`` for a zero row.
    instances : int
        Instances left out: the count of the member in the group, ``0`` for
        a zero row, or for a sub-group emptied by an exclusion (its members
        are recorded with their instances).
    """

    name: str
    cause: LeftOutCause
    reason: str
    instances: int

    def __post_init__(self) -> None:
        _name("name", self.name)
        object.__setattr__(self, "cause", LeftOutCause(self.cause))
        _name("reason", self.reason)
        _count("instances", self.instances, least=0)


def _check_assumed(parameter: str, value: object) -> Value:
    """A value a derivation assumes: known, chosen, and justified."""
    if not isinstance(value, Value):
        raise TypeError(f"the value assumed for {parameter!r} must be a Value")
    if value.state is not ValueState.KNOWN:
        shown = "to be set" if value.to_be_set else "not applicable"
        raise ValueError(
            f"the value assumed for {parameter!r} must be known, got {shown}"
        )
    if value.origin is not Origin.CHOICE or not (value.justification or "").strip():
        raise ValueError(
            f"the value assumed for {parameter!r} is a choice: origin 'choice' "
            "with its justification"
        )
    return value


@dataclass(frozen=True, slots=True)
class Assumption:
    """A value assumed for the unknown inputs of a parameter.

    Attributes
    ----------
    parameter : str
        Canonical name.
    value : Value
        Of origin ``choice``, with its justification.
    holders : tuple of str
        The members (or groups) whose unknown value was replaced, sorted.
    instances : int
        Their instances in the group.
    """

    parameter: str
    value: Value
    holders: tuple[str, ...]
    instances: int

    def __post_init__(self) -> None:
        _name("parameter", self.parameter)
        _check_assumed(self.parameter, self.value)
        _sequence("holders", self.holders)
        holders = _sorted_names("holder", self.holders)
        if not holders:
            raise ValueError(f"an assumption for {self.parameter!r} names its holders")
        object.__setattr__(self, "holders", holders)
        _count("instances", self.instances, least=1)


@dataclass(frozen=True, slots=True)
class Conversion:
    """The conversion of an input into the unit of its parameter.

    Attributes
    ----------
    holder : str or None
        The member or the group the value was read on; ``None`` for a value
        given directly.
    parameter : str
    value : int or float
        The value read, in ``unit``.
    unit : str
    converted : int or float
        The value in ``to_unit``, rounded once.
    to_unit : str
    factor : str
        The exact factor, as a fraction (``"1000"``, ``"5/18"``).
    """

    holder: str | None
    parameter: str
    value: int | float
    unit: str
    converted: int | float
    to_unit: str
    factor: str

    def __post_init__(self) -> None:
        if self.holder is not None:
            _name("holder", self.holder)
        for what in ("parameter", "unit", "to_unit", "factor"):
            _name(what, getattr(self, what))
        for what in ("value", "converted"):
            x = _plain_number(getattr(self, what))
            if x is None:
                raise TypeError(f"{what} must be a number, got {getattr(self, what)!r}")
            object.__setattr__(self, what, x)


@dataclass(frozen=True, slots=True)
class DerivationInput:
    """An input of a derived value, with its state and its source.

    Attributes
    ----------
    role : str
        What the input is to the rule: ``"member"`` (a value read on a
        member), ``"count"`` (the count of a member, for a rule that reads
        no value), ``"threshold"``, ``"characteristic"``, ``"class"``,
        ``"chosen"`` (the value a class selects), ``"gap"``, ``"density"``,
        ``"pace"``.
    parameter : str
        Canonical name.
    holder : str or None
        The member or the group the value was read on; ``None`` for a value
        given directly.
    state : ValueState
    value : Value or None
        The value read, with its source, or the value assumed; ``None``
        when nothing is read: the key is absent (``unknown``), or the input
        is a count (``known``).
    instances : int
        The multiplicity of the holder in the flattened group; for a value
        of a group, the instances of the groups it serves.
    """

    role: str
    parameter: str
    holder: str | None
    state: ValueState
    value: Value | None
    instances: int = 1

    def __post_init__(self) -> None:
        _name("role", self.role)
        _name("parameter", self.parameter)
        if self.holder is not None:
            _name("holder", self.holder)
        state = ValueState(self.state)
        object.__setattr__(self, "state", state)
        _count("instances", self.instances, least=1)
        v = self.value
        if v is None:
            if state not in (ValueState.KNOWN, ValueState.UNKNOWN):
                raise ValueError(f"an input {state} carries its value")
            return
        if not isinstance(v, Value):
            raise TypeError(f"value must be a Value or None, got {v!r}")
        if state is ValueState.ASSUMED:
            _check_assumed(self.parameter, v)
        elif v.state is not state:
            raise ValueError(f"an input {state} cannot carry a value {v.state}")

    def _key(self) -> tuple[str, str, str]:
        return (self.holder or "", self.parameter, self.role)


@dataclass(frozen=True, slots=True)
class Derivation:
    """The trace of a derived value: its rule, the inputs that fix it,
    and every input with its source.

    Every derived value (see :func:`derivations`: the envelope of a group,
    the class of a subject, the value a class selects, the length of a
    column) carries its derivation; the fingerprint of the value covers
    it, every input included, not only those that fix the value.

    The trace is in a canonical form, whatever the order of the members:
    ``fixed_by``, ``unknown`` and ``bound_fixed_by`` sorted and without
    duplicate, the inputs sorted by holder, parameter and role, the
    settings frozen.

    Attributes
    ----------
    name : str
        A derivation of the registry (see :func:`derivations`).
    rule : str
        One of the rules of the derivation.
    settings : mapping of str to object
        The declared options: the parameter read (``of``), the order, the
        comparison, the characteristics and the classes, the table, the
        spacing, the policy for the unknown and its justification.
    fixed_by : tuple of str
        The members (or characteristics, or class, or the holders of the
        values of a column) that fix the value; for a value to be set,
        none.
    inputs : tuple of DerivationInput
    assumptions : tuple of Assumption
        The values assumed for unknown inputs.
    left_out : tuple of LeftOut
        Members not applicable, excluded or of count 0, and unknown inputs
        left out by the policy ``known_only``.
    conversions : tuple of Conversion
        The inputs converted into the unit of their parameter.
    unknown : tuple of str
        The holders of the inputs without a value, whatever the policy (an
        input given directly is named by its parameter). A known value
        whose ``unknown`` is not empty was decided despite them (the
        strictest label of an order, or the highest rank of a
        classification, already reached); a value assumed or computed on
        the known inputs only says so in ``assumptions`` and ``left_out``.
    bound : int, float or str, optional
        For a value to be set by an envelope (``max``, ``min``,
        ``strictest``) or a classification by thresholds of which some
        inputs are known, or bounded themselves: the extreme they give,
        which the unknown value reaches at least (``max``: the value is at
        least the bound; ``min``: at most; ``strictest`` and a
        classification: at least as strict, in the order of its labels).
        The admissibility patterns read it (see :func:`evaluate`), and so
        do the derivations that read the value: an envelope, a
        classification.
    bound_fixed_by : tuple of str
        The inputs that fix the bound.

    Raises
    ------
    ValueError
        If the derivation or its rule is not in the registry, two inputs
        share a holder, a parameter and a role, two assumptions a
        parameter, or a bound comes without the inputs that fix it or
        without unknown inputs.
    TypeError
        If an element is not of its type.
    """

    name: str
    rule: str
    settings: Mapping[str, object]
    fixed_by: tuple[str, ...]
    inputs: tuple[DerivationInput, ...]
    assumptions: tuple[Assumption, ...] = ()
    left_out: tuple[LeftOut, ...] = ()
    conversions: tuple[Conversion, ...] = ()
    unknown: tuple[str, ...] = ()
    bound: Datum | None = None
    bound_fixed_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        info = DERIVATIONS.get(self.name)
        if info is None:
            raise ValueError(
                f"unknown derivation {self.name!r}; one of {list(DERIVATIONS)}"
            )
        if self.rule not in info.rules:
            raise ValueError(
                f"{self.name} has no rule {self.rule!r}; one of {list(info.rules)}"
            )
        set_ = object.__setattr__
        settings = dict(self.settings)
        for key in settings:
            _name("settings key", key)
        set_(self, "settings", freeze(settings))
        set_(self, "fixed_by", _sorted_names("fixed_by", self.fixed_by))
        set_(self, "unknown", _sorted_names("unknown", self.unknown))
        inputs = _typed("inputs", self.inputs, DerivationInput)
        inputs = tuple(sorted(inputs, key=DerivationInput._key))
        for a, b in itertools.pairwise(inputs):
            if a._key() == b._key():
                raise ValueError(
                    f"two inputs of {a.parameter!r} for {a.holder!r} as {a.role!r}"
                )
        set_(self, "inputs", inputs)
        assumptions = _typed("assumptions", self.assumptions, Assumption)
        assumptions = tuple(sorted(assumptions, key=lambda x: x.parameter))
        for one, other in itertools.pairwise(assumptions):
            if one.parameter == other.parameter:
                raise ValueError(f"two assumptions for {one.parameter!r}")
        set_(self, "assumptions", assumptions)
        left_out = _typed("left_out", self.left_out, LeftOut)
        set_(
            self,
            "left_out",
            tuple(
                sorted(left_out, key=lambda x: (x.name, x.cause, x.reason, x.instances))
            ),
        )
        conversions = _typed("conversions", self.conversions, Conversion)
        set_(
            self,
            "conversions",
            tuple(
                sorted(
                    conversions,
                    key=lambda c: (c.holder or "", c.parameter, c.unit, c.to_unit),
                )
            ),
        )
        self._check_bound()

    def _check_bound(self) -> None:
        bound = self.bound
        fixers = _sorted_names("bound_fixed_by", self.bound_fixed_by)
        object.__setattr__(self, "bound_fixed_by", fixers)
        if bound is None:
            if fixers:
                raise ValueError("bound_fixed_by is given without a bound")
            return
        if not isinstance(bound, str):
            number = _plain_number(bound)
            if number is None:
                raise TypeError(f"a bound is a number or a label, got {bound!r}")
            object.__setattr__(self, "bound", number)
            bound = number
        if isinstance(bound, float) and math.isnan(bound):
            raise ValueError("a bound cannot be NaN")
        if not fixers:
            raise ValueError("a bound comes with the inputs that fix it")
        if not self.unknown:
            raise ValueError("a bound stands for an unknown value: no unknown input")


def _typed[T](what: str, items: Iterable[object], kind: type[T]) -> tuple[T, ...]:
    out: list[T] = []
    for k, x in enumerate(items):
        if not isinstance(x, kind):
            raise TypeError(
                f"{what}[{k}] must be a {kind.__name__}, got {type(x).__name__}"
            )
        out.append(x)
    return tuple(out)
