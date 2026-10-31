# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""The version comes from the installed distribution, declared in pyproject.toml."""

import tomllib
from importlib.metadata import version
from pathlib import Path

import protee

ROOT = Path(__file__).parents[1]


def test_version_is_the_one_declared_in_pyproject() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert protee.__version__ == declared["project"]["version"]
    assert protee.__version__ == version("protee")


def test_the_public_api_is_explicit() -> None:
    assert protee.__all__ == ["__version__"]
