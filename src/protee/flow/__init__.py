# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Flows: maximum flow, feasibility, minimum or maximum cost flow.

The method is always the caller's choice: :func:`solve` and :func:`prepare`
take a ``method`` name from :func:`methods`, without default. Every method
returns the same :class:`FlowResult`: status, optimal flow and potentials,
certificate of infeasibility or unboundedness, deterministic counters.

- :func:`max_flow`: Dinic or Edmonds-Karp, with a minimum cut;
- :func:`check_feasibility`: a feasible flow, or a violated cut (Gale,
  Hoffman);
- :func:`solve`, :func:`prepare`: ``network_simplex``,
  ``cycle_canceling``, ``successive_shortest_paths``; a prepared problem
  is solved again for new costs, with a warm start for the network
  simplex;
- :func:`disjoint_paths`: ``k`` node- or arc-disjoint paths of minimum
  total cost;
- :mod:`protee.flow.diagnostics`: flow ranges, unattainable bounds,
  uniqueness of the optimum.

Provisional API (until version 1.0).
"""

from protee.flow._disjoint import DisjointPaths, disjoint_paths
from protee.flow._feasibility import Feasibility, check_feasibility
from protee.flow._maxflow import MaxFlowResult, max_flow
from protee.flow._methods import MethodInfo, Prepared, methods, prepare, solve
from protee.flow._problem import FlowProblem
from protee.flow._result import FlowResult, InfeasibleCut, Status
from protee.paths import NegativeCycle

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
