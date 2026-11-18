# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Provenance of a result: method, parameters, version and fingerprints."""

import dataclasses
import enum
import hashlib
import json
import math
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from importlib.metadata import version
from types import MappingProxyType
from typing import Any

import numpy as np

from protee.constraints._model import RequirementSet, ResolvedValues

__all__ = ["Provenance", "fingerprint", "provenance"]


def _canonical(x: Any) -> Any:
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, enum.Enum):
        return _canonical(x.value)
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return repr(x) if math.isfinite(x) else str(x)
    if isinstance(x, np.ndarray):
        return {"dtype": str(x.dtype), "values": _canonical(x.tolist())}
    if isinstance(x, np.generic):
        return _canonical(x.item())
    if isinstance(x, Mapping):
        return {
            str(k): _canonical(v)
            for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(x, (list, tuple)):
        return [_canonical(v) for v in x]
    if isinstance(x, AbstractSet):
        items = [_canonical(v) for v in x]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {
            "type": type(x).__name__,
            **{
                f.name: _canonical(getattr(x, f.name))
                for f in dataclasses.fields(x)
                if not f.name.startswith("_")
            },
        }
    raise TypeError(f"no canonical form for {type(x).__name__}")


def fingerprint(*objects: object) -> str:
    """SHA-256 of a canonical form of ``objects``.

    The same inputs give the same fingerprint on every machine; any change
    of a value, an attribute or the topology changes it. Supported: the
    objects of protee (frozen dataclasses), NumPy arrays, mappings,
    sequences, sets, numbers, strings and ``None``.

    Raises
    ------
    TypeError
        If an object has no canonical form.
    """
    text = json.dumps(
        [_canonical(o) for o in objects], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    """How a result was produced, so that it can be replayed.

    Attributes
    ----------
    method : str
    parameters : mapping of str to object
    version : str
        Version of protee.
    requirements : tuple of str
        Identifiers of the requirements.
    values : tuple of (str, str, str, bool)
        For each value: parameter, rulebook, edition, and whether it was
        retained (``False`` for a value set aside by precedence).
    inputs : str
        Fingerprint of the inputs, the method and its parameters.
    result : str
        Fingerprint of the result.
    counters : mapping of str to int
        Deterministic work counters.
    """

    method: str
    parameters: Mapping[str, object]
    version: str
    requirements: tuple[str, ...]
    values: tuple[tuple[str, str, str, bool], ...]
    inputs: str
    result: str
    counters: Mapping[str, int]

    def replays(self, other: Provenance) -> bool:
        """Whether ``other`` comes from the same inputs, method, parameters
        and version: its result can be reused instead of recomputed."""
        return (self.inputs, self.version) == (other.inputs, other.version)

    def differences(self, other: Provenance) -> tuple[str, ...]:
        """The fields that differ; ``result`` alone means a recomputation
        from the same inputs gave another result, which must be reported."""
        names = ("method", "parameters", "version", "inputs", "result")
        return tuple(n for n in names if getattr(self, n) != getattr(other, n))


def provenance(
    method: str,
    parameters: Mapping[str, object],
    *,
    inputs: Mapping[str, object],
    requirements: RequirementSet,
    values: ResolvedValues,
    result: object,
    counters: Mapping[str, int] | None = None,
) -> Provenance:
    """Record the provenance of a result.

    Parameters
    ----------
    method : str
        Name of the method.
    parameters : mapping of str to object
    inputs : mapping of str to object
        The inputs by name (graph, data, base weights...).
    requirements : RequirementSet
    values : ResolvedValues
    result : object
    counters : mapping of str to int, optional

    Returns
    -------
    Provenance
    """
    params = MappingProxyType(dict(parameters))
    recorded = []
    for name, value in sorted(values.values.items()):
        for v, retained in (
            (value, True),
            *((d, False) for d in values.discarded.get(name, ())),
        ):
            recorded.append(
                (name, v.source.rulebook or "", v.source.edition or "", retained)
            )
    return Provenance(
        method=method,
        parameters=params,
        version=version("protee"),
        requirements=tuple(r.id for r in requirements),
        values=tuple(recorded),
        inputs=fingerprint(method, params, inputs, requirements, values),
        result=fingerprint(result),
        counters=MappingProxyType(dict(counters or {})),
    )
