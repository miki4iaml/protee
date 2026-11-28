# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Requirements as traceable constraints on graphs.

Here a *requirement* is an exigence: a normalized statement taken from a
source (a doctrine, a regulation, a standard, the specification of a
client), never a dependency of a package. Its pattern turns it into a
*constraint*: an immutable effect on the arcs of a graph.

The phases come in a fixed order:

0. **derive** (:func:`aggregate`): the values on the side of the subject,
   from its description. A :class:`Member` is described by its sheets (value
   sets of rulebooks of kind ``description``), a :class:`Group` holds
   members or groups with their counts; a derivation of the closed registry
   (:func:`derivations`) gives a value per parameter, each with its
   :class:`Derivation`: the rule, the members that fix it and the source of
   every input. A value of a member is known, unknown, assumed (by the
   derivation, :class:`OnUnknown`) or not applicable (declared, with its
   reason); the caller states the policy for the unknown, without default,
   and the :class:`Derived` values count their unknowns. A description
   produces no constraint: its values enter :func:`resolve_values` like any
   other;
1. **evaluate** (:func:`evaluate`): one :class:`Effect` per requirement,
   from the arc attributes (:class:`ArcData`) and the values retained by
   precedence (:func:`resolve_values`); an arc without data gets the
   ``UNKNOWN`` verdict, never a presumed pass;
2. **compose** (:func:`compose`): the effects become a
   :class:`ComputationView` (arcs excluded, weights, travel times under
   the speed caps, flow bounds), independently of their order; the policy
   for the unknown, stated by the caller, is applied once;
3. **solve** with a named method of :mod:`protee.paths`,
   :mod:`protee.routes` or :mod:`protee.flow`;
4. **verify** (:func:`verify_route`, :func:`verify_flow`): each requirement
   is evaluated again on the result, a speed cap and an objective on the
   weights or costs the result was computed with, which gives its
   :class:`RequirementStatus`; the solver never writes a status;
5. **explain** (:func:`requirement_table`): the table is generated from the
   verification.

:func:`check_inputs` says beforehand what the data allow to prove.
When requirements cannot hold together, :func:`minimal_conflict`,
:func:`minimal_relaxation` and :func:`relax_by_tiers` explain the failure
and propose relaxations, with their :class:`Impact`, on a
:class:`RouteSearch` or a :class:`FlowSearch`. Their results are built on
the common model of :mod:`protee.results` (status, guarantee, counters,
version, fingerprint of the inputs); :func:`methods` lists their methods,
always named by the caller. :func:`provenance` records how a result was
produced, with :func:`fingerprint` of its inputs.
:class:`RulebookValues` reads rulebooks and values from TOML, and loads
the ones embedded from public texts.

Patterns form a closed registry (:func:`patterns`). Arrays come from
NumPy and are read-only.

Provisional API (until version 1.0).
"""

from __future__ import annotations

from protee.constraints._aggregate import AggregateKind, Aggregation, aggregate
from protee.constraints._compose import ComputationView, UnknownPolicy, compose
from protee.constraints._data import ArcData, Attribute
from protee.constraints._derivations import DerivationInfo, derivations
from protee.constraints._derive import (
    Comparison,
    Derived,
    OnUnknown,
    Tally,
    UnknownRule,
)
from protee.constraints._effects import Effect, Reason, Verdict, evaluate
from protee.constraints._failure import (
    Conflict,
    FlowSearch,
    Impact,
    InfeasibleSubset,
    Relaxation,
    RouteSearch,
    RouteSearchResult,
    Tier,
    TieredRelaxation,
    minimal_conflict,
    minimal_relaxation,
    relax_by_tiers,
)
from protee.constraints._groups import Group, Member, ZeroCount
from protee.constraints._inputs import InputCheck, InputReport, check_inputs
from protee.constraints._model import (
    Assumption,
    Conversion,
    Correspondence,
    Derivation,
    DerivationInput,
    LeftOut,
    LeftOutCause,
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
    ValueState,
    resolve_values,
)
from protee.constraints._patterns import EffectKind, Family, Pattern, Subject, patterns
from protee.constraints._provenance import Provenance, fingerprint, provenance
from protee.constraints._registry import methods
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
    "AggregateKind",
    "Aggregation",
    "ArcData",
    "Assumption",
    "Attribute",
    "Comparison",
    "ComputationView",
    "Conflict",
    "Conversion",
    "Correspondence",
    "Derivation",
    "DerivationInfo",
    "DerivationInput",
    "Derived",
    "Effect",
    "EffectKind",
    "Family",
    "FlowSearch",
    "Group",
    "Impact",
    "InfeasibleSubset",
    "InputCheck",
    "InputReport",
    "LeftOut",
    "LeftOutCause",
    "Member",
    "OnUnknown",
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
    "RouteSearchResult",
    "Rulebook",
    "RulebookKind",
    "RulebookValues",
    "Source",
    "Subject",
    "Tally",
    "Tier",
    "TieredRelaxation",
    "UnknownPolicy",
    "UnknownRule",
    "Value",
    "ValueSet",
    "ValueState",
    "Verdict",
    "Verification",
    "ZeroCount",
    "aggregate",
    "check_inputs",
    "compose",
    "derivations",
    "evaluate",
    "fingerprint",
    "methods",
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
