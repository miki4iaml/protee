# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""protee: operations research and adaptive solving of life-cycle profile graphs.

The subpackages are imported on demand, so that ``import protee`` stays
light:

- :mod:`protee.graph`: the immutable directed multigraph;
- :mod:`protee.io`: node-link JSON, CSV and DIMACS formats;
- :mod:`protee.structure`: components, degree-2 paths, spanning trees and
  cycle bases;
- :mod:`protee.paths`: shortest paths;
- :mod:`protee.flow`: maximum flows, feasibility, minimum or maximum cost
  flows with named methods, disjoint paths and diagnostics;
- :mod:`protee.transforms`: reversible graph transformations.

The whole API is provisional until version 1.0: the formalization of the
problems is refined with the feedback of the 0.x versions.
"""

import importlib
from importlib.metadata import version
from types import ModuleType

__all__ = [
    "__version__",
    "flow",
    "graph",
    "io",
    "paths",
    "routes",
    "structure",
    "transforms",
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
