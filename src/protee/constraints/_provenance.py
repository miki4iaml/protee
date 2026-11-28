# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Provenance of a result: method, parameters, version and fingerprints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import version
from types import MappingProxyType

from protee._fingerprint import fingerprint, freeze
from protee.constraints._model import RequirementSet, ResolvedValues

__all__ = ["Provenance", "fingerprint", "provenance"]


@dataclass(frozen=True, slots=True)
class Provenance:
    """How a result was produced, so that it can be replayed.

    Attributes
    ----------
    method : str
    parameters : mapping of str to object
        A frozen copy: lists become tuples, mappings read-only.
    version : str
        Version of protee.
    requirements : tuple of str
        Identifiers of the requirements.
    values : tuple of (str, str, str, bool)
        For each value: parameter, rulebook, edition (those of its value
        set), and whether it was retained (``False`` for a value set aside
        by precedence).
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
    params = freeze(parameters)
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
