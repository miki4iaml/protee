# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Fingerprints of inputs, and frozen copies of parameters.

NumPy, fractions and decimals are handled only when their module is
already imported: their objects cannot exist otherwise, and the modules
that need none of them stay light.

A sequence of floats only (NumPy's ``float64`` included, a subclass of
``float``), or of integers only that fit in 64 bits, is hashed by its bytes
in little-endian order, whatever the machine: the weights of a large graph
are hashed in a few milliseconds, where one tagged JSON item per number
took longer than a shortest path computation.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import sys
from array import array
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import Any

from protee._frozen import FrozenMap
from protee.graph import Digraph

__all__ = ["fingerprint", "freeze", "graph_fingerprint", "inputs_fingerprint"]


def _key(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def _packed(items: Sequence[Any]) -> dict[str, str] | None:
    """The digest of the bytes of a homogeneous sequence of floats (``f8``,
    subclasses of ``float`` included) or of 64-bit integers (``i8``, exactly
    ``int``: neither booleans nor other subclasses), or ``None`` for any
    other sequence."""
    if not items:
        return None
    if isinstance(items[0], float):
        if not all(isinstance(x, float) for x in items):
            return None
        code, tag = "d", "f8"
    elif type(items[0]) is int:
        if not all(type(x) is int for x in items):
            return None
        code, tag = "q", "i8"
    else:
        return None
    try:
        packed = array(code, items)
    except OverflowError:
        return None
    if sys.byteorder == "big":
        packed.byteswap()
    return {tag: hashlib.sha256(packed.tobytes()).hexdigest()}


def _exact_number(x: Any) -> dict[str, str] | None:
    """The tagged exact form of a fraction or a decimal, ``None`` for any
    other object: a fraction by its lowest terms, a decimal by its string
    (trailing zeros included, as the decimal keeps them)."""
    fractions = sys.modules.get("fractions")
    if fractions is not None and isinstance(x, fractions.Fraction):
        return {"fraction": str(x)}
    decimal = sys.modules.get("decimal")
    if decimal is not None and isinstance(x, decimal.Decimal):
        return {"decimal": str(x)}
    return None


_SUPPORTED = (
    "None, bool, str, int, float, Fraction, Decimal, enums, mappings, "
    "sequences, sets, dataclasses, Digraph, NumPy arrays and scalars"
)


def _canonical(x: Any) -> Any:
    """A JSON form in which every type that JSON would confuse is tagged:
    a float is not the string of its digits, a set is not a list, and the
    keys of a mapping keep their type. A graph is replaced by the
    fingerprint of its structure, computed once per graph. A float is
    written as the ``repr`` of the Python float of the same value, so that
    NumPy's ``float64``, a subclass, does not depend on NumPy's print
    options."""
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, enum.Enum):
        return _canonical(x.value)
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return {"float": repr(float(x))}
    if isinstance(x, Digraph):
        return {"digraph": graph_fingerprint(x)}
    np = sys.modules.get("numpy")
    if np is not None:
        if isinstance(x, np.ndarray):
            return {"ndarray": str(x.dtype), "values": _canonical(x.tolist())}
        if isinstance(x, np.generic):
            value = x.item()
            if isinstance(value, np.generic):
                # numpy.longdouble, for instance: no Python number holds it.
                raise TypeError(
                    f"no canonical form for numpy.{type(x).__name__}: "
                    f"supported are {_SUPPORTED}"
                )
            return _canonical(value)
    exact = _exact_number(x)
    if exact is not None:
        return exact
    if isinstance(x, Mapping):
        pairs = [[_canonical(k), _canonical(v)] for k, v in x.items()]
        return {"map": sorted(pairs, key=lambda kv: _key(kv[0]))}
    if isinstance(x, (list, tuple)):
        packed = _packed(x)
        return packed if packed is not None else [_canonical(v) for v in x]
    if isinstance(x, AbstractSet):
        return {"set": sorted((_canonical(v) for v in x), key=_key)}
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {
            "dataclass": type(x).__name__,
            "fields": {
                f.name: _canonical(getattr(x, f.name))
                for f in dataclasses.fields(x)
                if not f.name.startswith("_")
            },
        }
    raise TypeError(
        f"no canonical form for {type(x).__name__}: supported are {_SUPPORTED}"
    )


def _digest(form: Any) -> str:
    text = json.dumps(form, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(*objects: object) -> str:
    """SHA-256 of a canonical form of ``objects``.

    The same inputs give the same fingerprint on every machine; any change
    of a value, an attribute or the topology changes it, a change of type
    too (``1``, ``1.0`` and ``"1.0"`` differ). Supported: the objects of
    protee (frozen dataclasses), NumPy arrays and scalars, mappings,
    sequences (a tuple and a list with the same items are the same
    sequence), sets, numbers (``int``, ``float``, ``fractions.Fraction``
    and ``decimal.Decimal``, each exactly), strings and ``None``. A graph
    enters by the fingerprint of its structure, computed once per graph. A
    NumPy scalar counts as the Python number of the same value.

    Raises
    ------
    TypeError
        If an object has no canonical form (``bytes``, an instance of an
        ordinary class, ``numpy.longdouble``...); the message names its
        type.
    """
    return _digest([_canonical(o) for o in objects])


def graph_fingerprint(graph: Digraph) -> str:
    """Fingerprint of the structure of ``graph`` (nodes, arcs, labels),
    computed on first demand and kept in the graph."""
    found = graph._fingerprint
    if not found:
        found = _digest(
            {
                "n": graph.n,
                "tails": _canonical(graph.tails),
                "heads": _canonical(graph.heads),
                "labels": _canonical(graph.labels),
            }
        )
        object.__setattr__(graph, "_fingerprint", found)
    return found


def inputs_fingerprint(
    kind: str,
    method: str,
    parameters: Mapping[str, object],
    sources: tuple[object, ...],
) -> str:
    """Fingerprint of a computation: the type of its result (a method name
    may serve several problems), its method, parameters and inputs."""
    return fingerprint(kind, method, parameters, *sources)


def freeze(x: Any) -> Any:
    """A copy that cannot change: tuples, frozen mappings (which pickle,
    copy and hash) and read-only arrays."""
    if isinstance(x, Mapping):
        return FrozenMap({k: freeze(v) for k, v in x.items()})
    if isinstance(x, (list, tuple)):
        return tuple(freeze(v) for v in x)
    if isinstance(x, AbstractSet):
        return frozenset(freeze(v) for v in x)
    np = sys.modules.get("numpy")
    if np is not None and isinstance(x, np.ndarray):
        out = np.array(x, copy=True)
        out.flags.writeable = False
        return out
    return x
