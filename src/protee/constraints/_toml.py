# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Rulebooks and their values, read from TOML."""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from protee.constraints._model import (
    Origin,
    Parameter,
    Rulebook,
    RulebookKind,
    Source,
    Value,
    ValueSet,
)

__all__ = ["RulebookValues"]

FORMAT = "protee-rulebook-values/0"

_ROOT = ("format", "notice", "rulebook", "source", "parameters", "values")
_RULEBOOK = ("id", "kind", "edition", "title", "link")
_SOURCE = ("document", "link", "citation_checked")
_PARAMETER = ("name", "unit", "aliases")
_VALUE = (
    "value",
    "unit",
    "origin",
    "precedence",
    "justification",
    "not_applicable",
    "document",
    "locator",
    "link",
    "citation_checked",
)


def _table(
    where: str, x: object, allowed: Iterable[str] | None = None
) -> dict[str, Any]:
    if not isinstance(x, dict):
        raise TypeError(f"{where} must be a table")
    if allowed is not None and (unknown := sorted(set(x) - set(allowed))):
        raise ValueError(f"{where}: unknown keys {unknown}")
    return x


def _required(where: str, table: dict[str, Any], key: str) -> Any:
    if key not in table:
        raise ValueError(f"{where}: missing key {key!r}")
    return table[key]


@dataclass(frozen=True, slots=True)
class RulebookValues:
    """A rulebook, the parameters it gives values to, and its values.

    Attributes
    ----------
    rulebook : Rulebook
    parameters : tuple of Parameter
    values : ValueSet
    notice : str
        Where the values come from, and under which conditions they are
        reused.

    Notes
    -----
    The TOML format (``protee-rulebook-values/0``); keys in brackets are
    optional, any other key is refused::

        format = "protee-rulebook-values/0"
        notice = "..."                  # source and conditions of reuse

        [rulebook]
        id = "..."
        kind = "regulation"             # doctrine, regulation, standard,
                                        # client_specification, description
        edition = "..."
        title = { en = "...", fr = "..." }   # English required
        [link] = "..."

        [source]                        # defaults of every value
        [document] = "..."              # the English title by default
        [link] = "..."                  # the link of the rulebook by default
        [citation_checked] = true       # false by default

        [[parameters]]
        name = "..."
        [unit] = "m"
        [aliases] = { other-rulebook = "..." }

        [values.<parameter>]            # a declared parameter
        [value] = 20.0                  # inf for no limit; absent: to be set
        [unit] = "m"                    # the unit of the parameter
        [origin] = "rulebook"           # rulebook by default
        [precedence] = 0
        [justification] = "..."         # required for a chosen objective
        [not_applicable] = "..."        # why the parameter has no value
                                        # (then without value)
        [document], [link], [citation_checked]   # override [source]
        [locator] = "art. 3"

    Every value takes the edition of the rulebook. A technical sheet of
    a member is a rulebook of kind ``description``. A derived value carries
    its derivation, which TOML does not hold: the origin ``derived`` is
    refused.
    """

    rulebook: Rulebook
    parameters: tuple[Parameter, ...]
    values: ValueSet
    notice: str

    @classmethod
    def from_toml(cls, text: str) -> RulebookValues:
        """Read a rulebook and its values from TOML text.

        Raises
        ------
        ValueError
            If the format is not ``protee-rulebook-values/0``, a table or a
            required key is missing, a key is unknown, the notice is empty,
            or a value does not fit its parameter.
        TypeError
            If a key that holds a table holds another type.
        """
        doc = _table("the document", tomllib.loads(text), _ROOT)
        if doc.get("format") != FORMAT:
            raise ValueError(f"expected format {FORMAT!r}, got {doc.get('format')!r}")
        notice = _required("the document", doc, "notice")
        if not isinstance(notice, str) or not notice.strip():
            raise ValueError("the notice must say where the values come from")
        book = _table("rulebook", _required("the document", doc, "rulebook"), _RULEBOOK)
        rulebook = Rulebook(
            _required("rulebook", book, "id"),
            RulebookKind(_required("rulebook", book, "kind")),
            _table("rulebook.title", _required("rulebook", book, "title")),
            _required("rulebook", book, "edition"),
            link=book.get("link"),
        )
        default = _table("source", doc.get("source", {}), _SOURCE)
        parameters = []
        for k, entry in enumerate(doc.get("parameters", [])):
            where = f"parameters[{k}]"
            p = _table(where, entry, _PARAMETER)
            parameters.append(
                Parameter(
                    _required(where, p, "name"),
                    unit=p.get("unit"),
                    aliases=p.get("aliases", {}),
                )
            )
        units = {p.name: p.unit for p in parameters}
        values = {}
        for name, entry in _table("values", doc.get("values", {})).items():
            v = _table(f"values.{name}", entry, _VALUE)
            if name not in units:
                raise ValueError(f"value of undeclared parameter {name!r}")
            source = Source(
                v.get("document", default.get("document", rulebook.title["en"])),
                rulebook=rulebook.id,
                edition=rulebook.edition,
                locator=v.get("locator"),
                link=v.get("link", default.get("link", rulebook.link)),
                citation_checked=v.get(
                    "citation_checked", default.get("citation_checked", False)
                ),
            )
            values[name] = Value(
                v.get("value"),
                source,
                Origin(v.get("origin", "rulebook")),
                unit=v.get("unit"),
                precedence=v.get("precedence", 0),
                justification=v.get("justification"),
                not_applicable=v.get("not_applicable"),
            )
            if values[name].unit != units[name]:
                raise ValueError(
                    f"{name}: unit {values[name].unit!r}, expected {units[name]!r}"
                )
        return cls(
            rulebook,
            tuple(parameters),
            ValueSet(rulebook.id, rulebook.edition, values),
            notice,
        )

    @classmethod
    def load(cls, name: str) -> RulebookValues:
        """An embedded rulebook (see :meth:`names`), taken from a public text.

        Raises
        ------
        ValueError
            If no embedded rulebook has this name.
        """
        if name not in cls.names():
            raise ValueError(f"no embedded rulebook {name!r}; one of {cls.names()}")
        resource = files("protee.constraints").joinpath("data", f"{name}.toml")
        return cls.from_toml(resource.read_text(encoding="utf-8"))

    @staticmethod
    def names() -> tuple[str, ...]:
        """The names of the embedded rulebooks."""
        folder = files("protee.constraints").joinpath("data")
        return tuple(
            sorted(
                p.name.removesuffix(".toml")
                for p in folder.iterdir()
                if p.name.endswith(".toml")
            )
        )
