# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Fingerprints of inputs, and frozen copies of parameters.

NumPy is handled only when it is already imported: an array cannot exist
otherwise, and the modules that need no NumPy stay light.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import sys
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from types import MappingProxyType
from typing import Any

from protee.graph import Digraph

__all__ = ["fingerprint", "freeze", "graph_fingerprint", "inputs_fingerprint"]


def _key(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def _canonical(x: Any) -> Any:
    """A JSON form in which every type that JSON would confuse is tagged:
    a float is not the string of its digits, a set is not a list, and the
    keys of a mapping keep their type. A graph is replaced by the
    fingerprint of its structure, computed once per graph."""
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, enum.Enum):
        return _canonical(x.value)
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return {"float": repr(x)}
    if isinstance(x, Digraph):
        return {"digraph": graph_fingerprint(x)}
    np = sys.modules.get("numpy")
    if np is not None:
        if isinstance(x, np.ndarray):
            return {"ndarray": str(x.dtype), "values": _canonical(x.tolist())}
        if isinstance(x, np.generic):
            return _canonical(x.item())
    if isinstance(x, Mapping):
        pairs = [[_canonical(k), _canonical(v)] for k, v in x.items()]
        return {"map": sorted(pairs, key=lambda kv: _key(kv[0]))}
    if isinstance(x, (list, tuple)):
        return [_canonical(v) for v in x]
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
    raise TypeError(f"no canonical form for {type(x).__name__}")


def _digest(form: Any) -> str:
    text = json.dumps(form, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(*objects: object) -> str:
    """SHA-256 of a canonical form of ``objects``.

    The same inputs give the same fingerprint on every machine; any change
    of a value, an attribute or the topology changes it, a change of type
    too (``1``, ``1.0`` and ``"1.0"`` differ). Supported: the objects of
    protee (frozen dataclasses), NumPy arrays, mappings, sequences (a
    tuple and a list with the same items are the same sequence), sets,
    numbers, strings and ``None``. A graph enters by the fingerprint of its
    structure, computed once per graph.

    Raises
    ------
    TypeError
        If an object has no canonical form.
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
                "tails": list(graph.tails),
                "heads": list(graph.heads),
                "labels": None if graph.labels is None else list(graph.labels),
            }
        )
        object.__setattr__(graph, "_fingerprint", found)
    return found


def inputs_fingerprint(
    method: str, parameters: Mapping[str, object], sources: tuple[object, ...]
) -> str:
    """Fingerprint of a computation: its method, parameters and inputs."""
    return fingerprint(method, parameters, *sources)


def freeze(x: Any) -> Any:
    """A copy that cannot change: tuples, read-only mappings and arrays."""
    if isinstance(x, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in x.items()})
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
