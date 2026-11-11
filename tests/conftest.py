# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Shared test settings: property-based tests are reproducible.

``derandomize`` draws the same examples on every run and every machine,
and no example database is written to the working tree.
"""

from hypothesis import HealthCheck, settings

settings.register_profile(
    "protee",
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("protee")
