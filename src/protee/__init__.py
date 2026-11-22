# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""protee: graph and operations research algorithms.

Their methods are chosen explicitly, compared, and backed by certificates
and diagnostics.

The subpackages are imported on demand, so that ``import protee`` stays
light:

- :mod:`protee.graph`: the immutable directed multigraph;
- :mod:`protee.io`: node-link JSON, CSV and DIMACS formats;
- :mod:`protee.structure`: components, degree-2 paths, spanning trees and
  cycle bases;
- :mod:`protee.paths`: shortest paths;
- :mod:`protee.routes`: routes through waypoints, k shortest paths,
  replacement paths, overlap and most reliable path;
- :mod:`protee.flow`: maximum flows, feasibility, minimum or maximum cost
  flows with named methods, disjoint paths and diagnostics;
- :mod:`protee.transforms`: reversible graph transformations;
- :mod:`protee.constraints`: requirements (exigences) turned into
  traceable constraints on graphs, composed, verified on results and
  reported in a table;
- :mod:`protee.viz`: drawing of node-link documents (selection, groups,
  loops, transitive reduction, Graphviz DOT text; SVG and a page to
  explore offline with the optional extra ``viz``).

The whole API is provisional until version 1.0: the formalization of the
problems is refined with the feedback of the 0.x versions.
"""

from __future__ import annotations

import importlib
from importlib.metadata import version
from types import ModuleType

__all__ = [
    "__version__",
    "constraints",
    "flow",
    "graph",
    "io",
    "paths",
    "routes",
    "structure",
    "transforms",
    "viz",
]

#: Version of the installed distribution, declared only in pyproject.toml.
__version__ = version("protee")

_SUBMODULES = frozenset(__all__) - {"__version__"}


def __getattr__(name: str) -> ModuleType:
    """Import a subpackage on first access (PEP 562)."""
    if name in _SUBMODULES:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SUBMODULES)
