# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Checks shared by the conformity suite (objective 3 of AGENTS.md).

Every method of every registry returns a result built on
:class:`~protee.results.ResultCore`. These checks hold whatever the
problem; the certificate itself is verified by each family's test, with a
computation independent of the method.

- :func:`check_registry`: the description of every method is complete;
- :func:`check_options`: the options of a method are keyword arguments of
  its function;
- :func:`check_core`: the common fields, the rules of the status and of the
  guarantee, determinism (same result, counters and fingerprint on a second
  run), and the result as a value (it pickles, copies and hashes, and its
  docstring names its counters).
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
import pickle
import re
from collections.abc import Callable, Sequence

import protee
from protee._frozen import FrozenMap
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
        # The implementations use a binary heap, not a Fibonacci heap.
        assert "n log n)" not in info.complexity, info.complexity


def check_options(info: MethodInfo, function: Callable[..., object]) -> None:
    """Every option of ``info`` is a keyword argument of ``function``: a
    result's parameters can be passed back to replay the call."""
    accepted = inspect.signature(function).parameters
    for name in info.options:
        assert name in accepted, f"{function.__name__} takes no {name!r}"
        assert accepted[name].kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )


def _names(doc: str | None, name: str) -> bool:
    """Whether ``doc`` names ``name`` as a word of its own."""
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", doc or "") is not None


def check_value(result: ResultCore) -> None:
    """The result is a value: it pickles (keeping its fingerprint), copies,
    hashes and converts to a dictionary."""
    assert hash(result) == hash(copy.deepcopy(result))
    assert copy.deepcopy(result) == result
    again = pickle.loads(pickle.dumps(result))
    assert again == result
    assert hash(again) == hash(result)
    assert again.inputs == result.inputs
    assert dataclasses.asdict(result)["method"] == result.method


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
    assert isinstance(result.parameters, FrozenMap)
    assert set(result.parameters) <= set(info.options)
    assert isinstance(result.counters, FrozenMap)
    assert all(isinstance(v, int) and v >= 0 for v in result.counters.values())
    for name in result.counters:
        assert _names(type(result).__doc__, name), (type(result).__name__, name)
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
    check_value(result)
    again = run()
    # Pickled before its fingerprint is read, it computes the same one.
    assert pickle.loads(pickle.dumps(again)).inputs == result.inputs
    assert again == result
    assert dict(again.counters) == dict(result.counters)
    assert again.inputs == result.inputs
