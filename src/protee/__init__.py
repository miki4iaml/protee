# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""protee: operations research and adaptive solving of life-cycle profile graphs.

The package is at its very beginning: its model and its solvers are
designed in the first work items.
"""

from importlib.metadata import version

__all__ = ["__version__"]

#: Version of the installed distribution, declared only in pyproject.toml.
__version__ = version("protee")
