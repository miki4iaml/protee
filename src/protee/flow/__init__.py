# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Flows: maximum flow, feasibility, minimum or maximum cost flow.

The method is always the caller's choice: :func:`methods` lists every
problem of the module and its methods, each with its guarantee. Every
result is built on the common result model of :mod:`protee.results`:
status, solution, certificate of infeasibility or unboundedness,
guarantee, parameters, deterministic counters, version and fingerprint of
the inputs.

- :func:`max_flow`: ``dinic`` or ``edmonds_karp``, with a minimum cut
  (:class:`MaxFlowResult`);
- :func:`check_feasibility`: a feasible flow, or a violated cut (Gale,
  Hoffman), by ``dinic`` or ``edmonds_karp`` (:class:`Feasibility`);
- :func:`solve`, :func:`prepare`: ``network_simplex``,
  ``cycle_canceling``, ``successive_shortest_paths``, without default
  (:class:`FlowResult`); a prepared problem is solved again for new costs,
  with a warm start for the network simplex;
- :func:`disjoint_paths`: ``k`` node- or arc-disjoint paths of minimum
  total cost, by a minimum cost flow method (:class:`DisjointPaths`);
- :mod:`protee.flow.diagnostics`: flow ranges, unattainable bounds,
  uniqueness of the optimum, each a method of its own.

Provisional API (until version 1.0).
"""

from __future__ import annotations

from protee.flow._disjoint import DisjointPaths, disjoint_paths
from protee.flow._feasibility import Feasibility, check_feasibility
from protee.flow._maxflow import MaxFlowResult, max_flow
from protee.flow._methods import Prepared, prepare, solve
from protee.flow._problem import FlowProblem
from protee.flow._registry import methods
from protee.flow._result import FlowResult
from protee.results import InfeasibleCut, MethodInfo, NegativeCycle, Status

__all__ = [
    "DisjointPaths",
    "Feasibility",
    "FlowProblem",
    "FlowResult",
    "InfeasibleCut",
    "MaxFlowResult",
    "MethodInfo",
    "NegativeCycle",
    "Prepared",
    "Status",
    "check_feasibility",
    "disjoint_paths",
    "max_flow",
    "methods",
    "prepare",
    "solve",
]
