# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Rulebooks and their values, read from TOML."""

import tomllib
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


def _table(where: str, x: object) -> dict[str, Any]:
    if not isinstance(x, dict):
        raise TypeError(f"{where} must be a table")
    return x


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
    The TOML format (``protee-rulebook-values/0``)::

        format = "protee-rulebook-values/0"
        notice = "..."

        [rulebook]
        id = "..."
        kind = "regulation"
        edition = "..."
        link = "..."
        title = { en = "...", fr = "..." }

        [source]                # defaults of every value
        document = "..."
        link = "..."
        citation_checked = true

        [[parameters]]
        name = "..."
        unit = "m"

        [values.<parameter>]
        value = 20.0            # inf for no limit
        unit = "m"
        origin = "rulebook"
        locator = "art. 3"
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
            If the format is not ``protee-rulebook-values/0``, a table is
            missing, or a value does not fit its parameter.
        """
        doc = tomllib.loads(text)
        if doc.get("format") != FORMAT:
            raise ValueError(f"expected format {FORMAT!r}, got {doc.get('format')!r}")
        book = _table("rulebook", doc.get("rulebook"))
        rulebook = Rulebook(
            book["id"],
            RulebookKind(book["kind"]),
            _table("rulebook.title", book.get("title")),
            book["edition"],
            link=book.get("link"),
        )
        default = _table("source", doc.get("source", {}))
        parameters = tuple(
            Parameter(p["name"], unit=p.get("unit"), aliases=p.get("aliases", {}))
            for p in doc.get("parameters", [])
        )
        units = {p.name: p.unit for p in parameters}
        values = {}
        for name, entry in _table("values", doc.get("values", {})).items():
            v = _table(f"values.{name}", entry)
            if name not in units:
                raise ValueError(f"value of undeclared parameter {name!r}")
            source = Source(
                v.get("document", default.get("document", rulebook.title["en"])),
                rulebook=rulebook.id,
                edition=v.get("edition", default.get("edition", rulebook.edition)),
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
            )
            if values[name].unit != units[name]:
                raise ValueError(
                    f"{name}: unit {values[name].unit!r}, expected {units[name]!r}"
                )
        return cls(
            rulebook,
            parameters,
            ValueSet(rulebook.id, rulebook.edition, values),
            str(doc.get("notice", "")),
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
