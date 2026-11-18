# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Arc attributes, with an explicit unknown."""

import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np
import numpy.typing as npt

from protee.constraints._model import Source, _name

__all__ = ["ArcData", "Attribute"]

#: Code of an unknown category.
UNKNOWN_CODE = -1


def _frozen(array: npt.NDArray[Any]) -> npt.NDArray[Any]:
    out = np.array(array, copy=True)
    out.flags.writeable = False
    return out


@dataclass(frozen=True, slots=True, eq=False)
class Attribute:
    """One column of arc data, with its source.

    A missing value is unknown, never presumed compatible: ``NaN`` for a
    number, the code ``-1`` for a category. Build one with
    :meth:`numeric` or :meth:`categorical`.

    Attributes
    ----------
    name : str
    values : numpy.ndarray
        Read-only: ``float64`` for a number, ``int32`` category codes
        (indices into ``labels``) for a category.
    unit : str, optional
    source : Source, optional
        The single source of the column.
    labels : tuple of str, optional
        For a category: the labels, in their declared order (lowest first).
    derived : bool
        Whether the column is computed from other data.
    quality : str, optional
        What a derived value guarantees (for instance, a mean slope is only
        a lower bound of the local slope).
    """

    name: str
    values: npt.NDArray[Any]
    unit: str | None = None
    source: Source | None = None
    labels: tuple[str, ...] | None = None
    derived: bool = False
    quality: str | None = None

    def __post_init__(self) -> None:
        _name("attribute name", self.name)
        values = np.asarray(self.values)
        if values.ndim != 1:
            raise ValueError(f"attribute {self.name}: expected one value per arc")
        if self.labels is None:
            if values.dtype != np.float64:
                raise TypeError(f"attribute {self.name}: numbers must be float64")
        else:
            labels = tuple(self.labels)
            if len(set(labels)) != len(labels):
                raise ValueError(f"attribute {self.name}: labels repeat")
            if values.dtype != np.int32:
                raise TypeError(f"attribute {self.name}: codes must be int32")
            if values.size and (
                values.min() < UNKNOWN_CODE or values.max() >= len(labels)
            ):
                raise ValueError(f"attribute {self.name}: code out of range")
            object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "values", _frozen(values))

    @classmethod
    def numeric(
        cls,
        name: str,
        values: Iterable[float | None],
        *,
        unit: str | None = None,
        source: Source | None = None,
        derived: bool = False,
        quality: str | None = None,
    ) -> Attribute:
        """A numeric column; ``None`` (or ``NaN``) is unknown."""
        numbers = []
        for v in values:
            if v is None:
                numbers.append(math.nan)
            elif isinstance(v, (int, float)):
                numbers.append(float(v))
            else:
                raise TypeError(f"attribute {name}: {v!r} is not a number")
        return cls(
            name,
            np.array(numbers, dtype=np.float64),
            unit=unit,
            source=source,
            derived=derived,
            quality=quality,
        )

    @classmethod
    def categorical(
        cls,
        name: str,
        values: Iterable[str | None],
        labels: Sequence[str],
        *,
        source: Source | None = None,
        derived: bool = False,
        quality: str | None = None,
    ) -> Attribute:
        """A category column; ``None`` is unknown.

        ``labels`` lists the categories in their declared order, lowest
        first; every value must be one of them.
        """
        index = {label: k for k, label in enumerate(labels)}
        codes = []
        for v in values:
            if v is None:
                codes.append(UNKNOWN_CODE)
            elif v in index:
                codes.append(index[v])
            else:
                raise ValueError(
                    f"attribute {name}: {v!r} is not one of {list(labels)}"
                )
        return cls(
            name,
            np.array(codes, dtype=np.int32),
            source=source,
            labels=tuple(labels),
            derived=derived,
            quality=quality,
        )

    @property
    def known(self) -> npt.NDArray[np.bool_]:
        """Mask of the arcs whose value is known."""
        mask: npt.NDArray[np.bool_] = (
            ~np.isnan(self.values)
            if self.labels is None
            else self.values != UNKNOWN_CODE
        )
        return mask


@dataclass(frozen=True, slots=True, eq=False)
class ArcData:
    """The attributes of the arcs of a graph, one column each.

    The graph holds the topology only; its attributes live here.

    Attributes
    ----------
    m : int
        Number of arcs.
    attributes : tuple of Attribute
        Distinct names, one value per arc each.
    element : str, optional
        Name of the category column that tells what each arc is (a bridge,
        a tunnel, the link of a life-cycle profile); it decides the arcs in
        the scope of a requirement.

    Raises
    ------
    ValueError
        If a column has another size, a name repeats, or ``element`` is not
        a category column.
    """

    m: int
    attributes: tuple[Attribute, ...] = ()
    element: str | None = None
    _index: Mapping[str, Attribute] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.m) is not int or self.m < 0:
            raise ValueError(f"m must be a non-negative integer, got {self.m!r}")
        attributes = tuple(self.attributes)
        index: dict[str, Attribute] = {}
        for a in attributes:
            if a.name in index:
                raise ValueError(f"duplicate attribute {a.name!r}")
            if a.values.size != self.m:
                raise ValueError(
                    f"attribute {a.name}: expected {self.m} values, got {a.values.size}"
                )
            index[a.name] = a
        if self.element is not None and (
            self.element not in index or index[self.element].labels is None
        ):
            raise ValueError(f"element {self.element!r} is not a category column")
        object.__setattr__(self, "attributes", attributes)
        object.__setattr__(self, "_index", MappingProxyType(index))

    def __getitem__(self, name: str) -> Attribute:
        """The column named ``name``."""
        return self._index[name]

    def __contains__(self, name: object) -> bool:
        return name in self._index

    def __iter__(self) -> Iterator[Attribute]:
        return iter(self.attributes)

    def in_scope(self, scope: frozenset[str] | None) -> npt.NDArray[np.bool_]:
        """Mask of the arcs in ``scope``.

        Every arc is in scope when ``scope`` is ``None``. Otherwise an arc
        is in scope when its element is one of ``scope`` or is unknown: an
        unknown element is never presumed out of scope. Without an
        ``element`` column, every element is unknown.

        Raises
        ------
        ValueError
            If a label of ``scope`` is not a label of the ``element``
            column: an unresolved name is refused, never read as an empty
            scope.
        """
        if scope is None or self.element is None:
            return np.ones(self.m, dtype=np.bool_)
        codes = self[self.element].values
        mask: npt.NDArray[np.bool_] = np.isin(codes, self._codes(scope)) | (
            codes == UNKNOWN_CODE
        )
        return mask

    def scope_unknown(self, scope: frozenset[str] | None) -> npt.NDArray[np.bool_]:
        """Mask of the arcs presumed in ``scope`` because their element is
        unknown (none when ``scope`` is ``None``).

        Raises
        ------
        ValueError
            As :meth:`in_scope`.
        """
        if scope is None:
            return np.zeros(self.m, dtype=np.bool_)
        if self.element is None:
            return np.ones(self.m, dtype=np.bool_)
        self._codes(scope)
        mask: npt.NDArray[np.bool_] = self[self.element].values == UNKNOWN_CODE
        return mask

    def _codes(self, scope: frozenset[str]) -> list[int]:
        assert self.element is not None
        labels = self[self.element].labels
        assert labels is not None
        if unresolved := sorted(set(scope) - set(labels)):
            raise ValueError(
                f"scope labels {unresolved} are not elements of {self.element!r} "
                f"({list(labels)})"
            )
        return [k for k, label in enumerate(labels) if label in scope]

    def element_labels(self) -> tuple[str | None, ...]:
        """The element of each arc, ``None`` when unknown or undeclared."""
        if self.element is None:
            return (None,) * self.m
        column = self[self.element]
        assert column.labels is not None
        labels = column.labels
        return tuple(None if c == UNKNOWN_CODE else labels[c] for c in column.values)
