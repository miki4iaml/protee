# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Fingerprints of inputs, and frozen copies of parameters.

NumPy, fractions and decimals are handled only when their module is
already imported: their objects cannot exist otherwise, and the modules
that need none of them stay light.

A list or tuple of floats only, or of integers only that fit in 64 bits,
is hashed by its bytes in little-endian order, whatever the machine;
NumPy's integers and floats count as the Python numbers of the same value.
The weights of a large graph are hashed in a few milliseconds, where one
tagged JSON item per number took longer than a shortest path computation.
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


_TAGS = {"d": "f8", "q": "i8"}


def _code(kind: type) -> str | None:
    """The array type code that packs the numbers of type ``kind``: ``d``
    for floats (subclasses such as NumPy's ``float64`` included) and NumPy's
    other floats but ``longdouble``, which no Python float holds; ``q`` for
    ints (exactly ``int``: neither booleans nor enumerations) and NumPy's
    integers but ``timedelta64``, a duration; ``None`` for any other
    type."""
    if kind is int:
        return "q"
    if issubclass(kind, float):
        return "d"
    np = sys.modules.get("numpy")
    if np is not None:
        if issubclass(kind, np.integer) and not issubclass(kind, np.timedelta64):
            return "q"
        if issubclass(kind, np.floating) and not issubclass(kind, np.longdouble):
            return "d"
    return None


def _packed(items: Sequence[Any]) -> dict[str, str] | None:
    """The digest of the bytes of a list or tuple of floats only (``f8``)
    or of 64-bit integers only (``i8``), each read as the Python number of
    the same value; ``None`` for any other list or tuple."""
    codes = {_code(kind) for kind in set(map(type, items))}
    code = codes.pop() if len(codes) == 1 else None
    if code is None:
        return None
    try:
        packed = array(code, items)
    except OverflowError:  # an integer beyond 64 bits
        return None
    if sys.byteorder == "big":
        packed.byteswap()
    return {_TAGS[code]: hashlib.sha256(packed.tobytes()).hexdigest()}


def _exact_number(x: Any) -> dict[str, Any] | None:
    """The tagged exact form of a fraction or a decimal, ``None`` for any
    other object: a fraction by its lowest terms; a decimal by its sign,
    digits and exponent (trailing zeros included, as the decimal keeps
    them; ``F``, ``n`` or ``N`` for an infinity or a NaN), which, unlike
    its string, do not depend on the decimal context of the thread."""
    fractions = sys.modules.get("fractions")
    if fractions is not None and isinstance(x, fractions.Fraction):
        return {"fraction": str(x)}
    decimal = sys.modules.get("decimal")
    if decimal is not None and isinstance(x, decimal.Decimal):
        sign, digits, exponent = x.as_tuple()
        return {"decimal": [sign, "".join(map(str, digits)), exponent]}
    return None


_SUPPORTED = (
    "None, bool, str, int, float, Fraction, Decimal, enums, mappings, "
    "lists and tuples, sets, dataclasses, Digraph, NumPy arrays, NumPy "
    "booleans, integers, floats (not longdouble), datetime64 and timedelta64"
)


def _numpy_scalar(np: Any, x: Any) -> Any:
    """The canonical form of a NumPy scalar other than ``float64`` (a
    ``float``): a boolean, an integer or a float as the Python number of
    the same value; a date or a duration tagged with its dtype (its unit
    included), by its count of units, so that it never meets a number."""
    # Before the integers: NumPy makes timedelta64 one of them.
    if isinstance(x, (np.datetime64, np.timedelta64)):
        return {"numpy": str(x.dtype), "value": int(x.astype(np.int64))}
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating) and not isinstance(x, np.longdouble):
        return _canonical(float(x))
    # numpy.longdouble, complex numbers, bytes: no Python number holds them.
    raise TypeError(
        f"no canonical form for numpy.{type(x).__name__}: supported are {_SUPPORTED}"
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
            return _numpy_scalar(np, x)
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

    The same inputs give the same fingerprint on every machine and in
    every thread; any change of a value, an attribute or the topology
    changes it, a change of type too (``1``, ``1.0`` and ``"1.0"`` differ).
    Supported: the objects of protee (frozen dataclasses), NumPy arrays,
    mappings, lists and tuples (a tuple and a list with the same items are
    the same sequence; another sequence, such as a ``range``, is not
    supported), sets, numbers (``int``, ``float``, ``fractions.Fraction``
    and ``decimal.Decimal``, each exactly, a decimal whatever the decimal
    context), strings and ``None``. A graph enters by the fingerprint of
    its structure, computed once per graph. A NumPy boolean, integer or
    float (``float32`` included) counts as the Python number of the same
    value, alone or in a list; a ``numpy.datetime64`` or
    ``numpy.timedelta64`` by its dtype, unit included, and its count of
    units.

    Raises
    ------
    TypeError
        If an object has no canonical form (``bytes``, a ``range``, an
        instance of an ordinary class, ``numpy.longdouble``, a complex
        number...); the message names its type.
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
