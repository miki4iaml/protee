# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Provenance of a result: method, parameters, version and fingerprints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import version

from protee._fingerprint import fingerprint, freeze
from protee._frozen import FrozenMap
from protee.constraints._model import RequirementSet, ResolvedValues
from protee.results import ResultCore

__all__ = ["Provenance", "fingerprint", "provenance"]


@dataclass(frozen=True, slots=True)
class Provenance:
    """How a result was produced, so that it can be replayed.

    A value, like a result: it compares by its fields, hashes, pickles and
    copies.

    Attributes
    ----------
    method : str
    parameters : mapping of str to object
        A frozen copy: lists become tuples, mappings immutable.
    version : str
        Version of protee that produced the result.
    requirements : tuple of str
        Identifiers of the requirements.
    values : tuple of (str, str, str, bool)
        For each value: parameter, rulebook, edition (those of its value
        set), and whether it was retained (``False`` for a value set aside
        by precedence).
    inputs : str
        Fingerprint of the inputs, the method and its parameters; of the
        fingerprint of the result's own inputs too, when the result is
        built on :class:`~protee.results.ResultCore`.
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", freeze(dict(self.parameters)))
        object.__setattr__(self, "counters", FrozenMap(self.counters))

    def replays(self, other: Provenance) -> bool:
        """Whether ``other`` has the same inputs, method, parameters and
        version: it answers the same question on the same inputs (the same
        status and, for an exact method, the same optimal value), so its
        result can be reused instead of recomputed.

        Its solution and counters may differ from a recomputation: after a
        warm start, when several optima exist, or when an input that
        decides the result is left out of the fingerprint (the feasibility
        test of a conflict or a relaxation, a callable). See
        :attr:`protee.results.ResultCore.inputs`.
        """
        return (self.inputs, self.version) == (other.inputs, other.version)

    def differences(self, other: Provenance) -> tuple[str, ...]:
        """The fields that differ.

        ``result`` alone means a recomputation from the same inputs gave
        another result. It is expected after a warm start that found
        another optimum, or when a callable input (a feasibility test) has
        changed; otherwise it must be reported.
        """
        names = ("method", "parameters", "version", "inputs", "result")
        return tuple(n for n in names if getattr(self, n) != getattr(other, n))


def provenance(
    method: str | None = None,
    parameters: Mapping[str, object] | None = None,
    *,
    inputs: Mapping[str, object],
    requirements: RequirementSet,
    values: ResolvedValues,
    result: object,
    counters: Mapping[str, int] | None = None,
) -> Provenance:
    """Record the provenance of a result.

    A result built on :class:`~protee.results.ResultCore` carries its
    method, parameters, counters and version: they are taken from it,
    unless given; the fingerprint of its own inputs enters
    :attr:`Provenance.inputs`. Any other result needs its method and
    parameters.

    Parameters
    ----------
    method : str, optional
        Name of the method; by default, that of the result.
    parameters : mapping of str to object, optional
        By default, those of the result.
    inputs : mapping of str to object
        The inputs by name (graph, data, base weights...).
    requirements : RequirementSet
    values : ResolvedValues
    result : object
    counters : mapping of str to int, optional
        By default, those of the result (none for a result without them).

    Returns
    -------
    Provenance

    Raises
    ------
    TypeError
        If the method or the parameters are missing for a result that does
        not carry them.
    ValueError
        If ``method`` is not the method that produced the result.
    """
    core = result if isinstance(result, ResultCore) else None
    if core is None:
        if method is None or parameters is None:
            raise TypeError(
                "a result not built on ResultCore needs its method and parameters"
            )
        recorded_by = version("protee")
        own: tuple[str, ...] = ()
    else:
        if method is not None and method != core.method:
            raise ValueError(
                f"the result was produced by {core.method!r}, not {method!r}"
            )
        method = core.method
        parameters = core.parameters if parameters is None else parameters
        counters = core.counters if counters is None else counters
        recorded_by = core.version
        own = (core.inputs,)
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
        version=recorded_by,
        requirements=tuple(r.id for r in requirements),
        values=tuple(recorded),
        inputs=fingerprint(method, params, inputs, requirements, values, *own),
        result=fingerprint(result),
        counters=FrozenMap(counters or {}),
    )
