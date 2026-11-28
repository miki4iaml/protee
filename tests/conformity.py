# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Checks shared by the conformity suite (objective 3 of AGENTS.md).

Every method of every registry returns a result built on
:class:`~protee.results.ResultCore`. These checks hold whatever the
problem; the certificate itself is verified by each family's test, with a
computation independent of the method.

- :func:`check_registry`: the description of every method is complete;
- :func:`check_core`: the common fields, the rules of the status and of the
  guarantee, and determinism (same result, counters and fingerprint on a
  second run).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from types import MappingProxyType

import protee
from protee.results import (
    Guarantee,
    GuaranteeKind,
    MethodInfo,
    ResultCore,
    Status,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")


def check_registry(infos: Sequence[MethodInfo]) -> None:
    """Every method is fully described, and named once per problem."""
    assert infos, "a registry lists at least one method"
    seen: set[tuple[str, str]] = set()
    for info in infos:
        assert isinstance(info, MethodInfo)
        key = (info.problem, info.name)
        assert key not in seen, f"{key} is listed twice"
        seen.add(key)
        for text in (info.name, info.problem, info.summary, info.complexity):
            assert text.strip()
        assert info.reference.strip()
        assert isinstance(info.guarantee, Guarantee)
        assert isinstance(info.options, tuple)


def check_core(
    result: ResultCore, info: MethodInfo, run: Callable[[], ResultCore]
) -> None:
    """The common fields of ``result``, produced by the method ``info``;
    ``run`` computes it again from the same inputs."""
    assert isinstance(result, ResultCore)
    assert isinstance(result.status, Status)
    assert result.method == info.name
    assert result.guarantee == info.guarantee
    assert result.version == protee.__version__
    assert isinstance(result.parameters, MappingProxyType)
    assert set(result.parameters) <= set(info.options)
    assert isinstance(result.counters, MappingProxyType)
    assert all(isinstance(v, int) and v >= 0 for v in result.counters.values())
    if result.status in (Status.INFEASIBLE, Status.UNBOUNDED):
        assert result.certificate is not None
    if result.status is Status.OPTIMAL:
        assert result.certificate is None
    if (
        result.status is Status.FEASIBLE
        and info.guarantee.kind is GuaranteeKind.BOUNDED
    ):
        assert result.bound is not None
        assert result.gap is not None
    if info.guarantee.kind is GuaranteeKind.EXACT:
        assert result.status is not Status.FEASIBLE
    assert _SHA256.fullmatch(result.inputs)
    again = run()
    assert again == result
    assert dict(again.counters) == dict(result.counters)
    assert again.inputs == result.inputs
