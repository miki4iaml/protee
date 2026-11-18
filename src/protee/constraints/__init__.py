# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Requirements as traceable constraints on graphs.

Here a *requirement* is an exigence: a normalized statement taken from a
source (a doctrine, a regulation, a standard, the specification of a
client), never a dependency of a package. Its pattern turns it into a
*constraint*: an immutable effect on the arcs of a graph.

The phases come in a fixed order:

1. **evaluate** (:func:`evaluate`): one :class:`Effect` per requirement,
   from the arc attributes (:class:`ArcData`) and the values retained by
   precedence (:func:`resolve_values`); an arc without data gets the
   ``UNKNOWN`` verdict, never a presumed pass;
2. **compose** (:func:`compose`): the effects become a
   :class:`ComputationView` (arcs excluded, weights, flow bounds),
   independently of their order; the policy for the unknown, stated by
   the caller, is applied once;
3. **solve** with a named method of :mod:`protee.paths`,
   :mod:`protee.routes` or :mod:`protee.flow`;
4. **verify** (:func:`verify_route`, :func:`verify_flow`): each requirement
   is evaluated again on the result, which gives its
   :class:`RequirementStatus`; the solver never writes a status;
5. **explain** (:func:`requirement_table`): the table is generated from the
   verification.

:func:`check_inputs` says beforehand what the data allow to prove.
When requirements cannot hold together, :func:`minimal_conflict`,
:func:`minimal_relaxation` and :func:`relax_by_tiers` explain the failure
and propose relaxations, with their :class:`Impact`, on a
:class:`RouteSearch` or a :class:`FlowSearch`. :func:`provenance` records
how a result was produced, with :func:`fingerprint` of its inputs.
:class:`RulebookValues` reads rulebooks and values from TOML, and loads
the ones embedded from public texts.

Patterns form a closed registry (:func:`patterns`). Arrays come from
NumPy and are read-only.

Provisional API (until version 1.0).
"""

from protee.constraints._compose import ComputationView, UnknownPolicy, compose
from protee.constraints._data import ArcData, Attribute
from protee.constraints._effects import Effect, Reason, Verdict, evaluate
from protee.constraints._failure import (
    Conflict,
    FlowSearch,
    Impact,
    Relaxation,
    RouteSearch,
    Tier,
    TieredRelaxation,
    minimal_conflict,
    minimal_relaxation,
    relax_by_tiers,
)
from protee.constraints._inputs import InputCheck, InputReport, check_inputs
from protee.constraints._model import (
    Correspondence,
    Origin,
    Parameter,
    Relation,
    Requirement,
    RequirementSet,
    ResolvedValues,
    Rulebook,
    RulebookKind,
    Source,
    Value,
    ValueSet,
    resolve_values,
)
from protee.constraints._patterns import EffectKind, Family, Pattern, Subject, patterns
from protee.constraints._provenance import Provenance, fingerprint, provenance
from protee.constraints._table import RequirementRow, requirement_table
from protee.constraints._toml import RulebookValues
from protee.constraints._verify import (
    RequirementCheck,
    RequirementStatus,
    Verification,
    verify_flow,
    verify_route,
)

__all__ = [
    "ArcData",
    "Attribute",
    "ComputationView",
    "Conflict",
    "Correspondence",
    "Effect",
    "EffectKind",
    "Family",
    "FlowSearch",
    "Impact",
    "InputCheck",
    "InputReport",
    "Origin",
    "Parameter",
    "Pattern",
    "Provenance",
    "Reason",
    "Relation",
    "Relaxation",
    "Requirement",
    "RequirementCheck",
    "RequirementRow",
    "RequirementSet",
    "RequirementStatus",
    "ResolvedValues",
    "RouteSearch",
    "Rulebook",
    "RulebookKind",
    "RulebookValues",
    "Source",
    "Subject",
    "Tier",
    "TieredRelaxation",
    "UnknownPolicy",
    "Value",
    "ValueSet",
    "Verdict",
    "Verification",
    "check_inputs",
    "compose",
    "evaluate",
    "fingerprint",
    "minimal_conflict",
    "minimal_relaxation",
    "patterns",
    "provenance",
    "relax_by_tiers",
    "requirement_table",
    "resolve_values",
    "verify_flow",
    "verify_route",
]
