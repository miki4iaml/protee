# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""An immutable mapping that results can pickle, copy and hash.

:class:`types.MappingProxyType` is read-only but can be neither pickled
nor hashed, so a result holding one could not leave a worker process or
enter a set. :class:`FrozenMap` keeps a private copy of its items.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any, NoReturn

__all__ = ["FrozenMap"]


class FrozenMap[K, V](Mapping[K, V]):
    """A mapping that cannot change after construction.

    It equals any mapping with the same items (a ``dict`` included), hashes
    from its items when they are hashable, and pickles and copies like the
    ``dict`` of its items.
    """

    __slots__ = ("_items",)

    _items: dict[K, V]

    def __init__(self, items: Mapping[K, V] | Iterable[tuple[K, V]] = ()) -> None:
        object.__setattr__(self, "_items", dict(items))

    def __getitem__(self, key: K) -> V:
        return self._items[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return hash(frozenset(self._items.items()))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return self._items == dict(other.items())
        return NotImplemented

    def __repr__(self) -> str:
        return f"FrozenMap({self._items!r})"

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self._items,))

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError(f"{type(self).__name__} is immutable")
