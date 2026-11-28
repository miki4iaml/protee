# Derivations: values from the description of a subject

A requirement compares a value of the subject with an attribute of each
arc: a quantity with the limit of the arc, a capacity with what the arc
demands, a class with the class of the arc. When the subject is a group
of members, each described by its own technical sheet, or when a text
sets a value by a class, that value is derived from the description.
`protee.constraints` does it in a phase of its own, *derive*, by named
derivations; each derived value keeps its rule, the member that fixes it
and the source of every input. This page states the conventions; the
docstrings give the fields and the errors.

## The derive phase in the requirement chain

```
 members and groups           value sets of texts
 (technical sheets)           (limits, thresholds, tables)
         |                         |                |
         v       thresholds,       |                |
      derive <-- tables -----------+                |
         |                                          |
         v                                          v
 values of the subject --------------------> resolve_values
                                                    |
 requirements, by their patterns                    |
         |                                          |
         v                                          |
      evaluate <------------------------------------+
         |
         v
      compose --> transform --> solve --> verify --> explain
```

*Derive* comes first. A derivation reads the description of the subject
(its members, their sheets, the counts of a group) and, for a class or a
selection, value sets taken from texts (thresholds, tables). It returns a
`Derived`, whose value set enters `resolve_values` like any other, with
its precedence. Nothing after it changes: `RouteSearch`, `FlowSearch`,
`verify_route`, `verify_flow` and `requirement_table` read a derived
value as they read the others.

**A description gives values, never constraints.** Constraints come from
requirements, taken from texts: the pattern of a requirement compares a
value of the subject with an attribute of each arc. A sheet that says
that a member is 3.5 m wide constrains nothing until a requirement says
that the width stays within the limit of each arc. A constraint never
comes from data alone (objective 5 of [AGENTS.md](../AGENTS.md)).

## Members and groups

| Object | What it holds |
|---|---|
| `Member(id, sheets)` | a described subject and its technical sheets: value sets of rulebooks of kind `description` (`RulebookKind.DESCRIPTION`) |
| `Group(id, members, values=None)` | members or groups, each with its count; `values`, the values of the group itself (gaps, density, pace), with their sources |

- **Sheets.** A member may have several sheets: a default value taken
  from a text keeps its own rulebook. Two sheets never give the same
  parameter, nor share a rulebook and an edition. A member without a
  sheet is allowed: every value of it is unknown. A sheet is read in
  TOML like any value set (`protee-rulebook-values/0`, `kind =
  "description"`).
- **Counts.** A count is a positive integer. A count of 0 is refused by
  the constructor: a table of counts often has rows of 0 (a type not used
  in this group), and keeping or dropping them silently would hide it.
- **Identifiers.** One identifier names one member or one group in the
  whole tree, so that "fixed by B" is never ambiguous. Members are sorted
  by identifier: the order of a table never matters (the order of
  sub-groups along a route belongs to the time module).
- **Nested groups.** A member of a group may be a group. `flatten()`
  gives the members at the leaves, each with the product of the counts
  along its path, summed when a member appears in several sub-groups.
  `aggregate` reads the flattened group, `column_length` the levels.

```
 column                        flatten()
 |-- pair       x 3
 |   |-- A      x 2            A   3 x 2 = 6
 |   `-- B      x 1            B   3 x 1 = 3
 `-- C          x 1            C           1
```

Three constructors make a group from a table or from another group, and
record what they leave out:

| Constructor | Gives | Recorded in `Group.left_out` |
|---|---|---|
| `Group.from_counts(id, counts, zero_counts=...)` | a group from a table of counts; `ZeroCount.REFUSE` refuses a row of count 0, `ZeroCount.DROP` drops it | each row dropped: cause `zero_count`, reason `"count 0 in the table"` |
| `group.with_counts(id, counts, zero_counts=...)` | a variant with other counts of some direct members, under its own identifier (`variant_of`): the base of a sensitivity analysis | the rows of count 0 dropped |
| `group.without(id, members, reason=...)` | a declared sub-group: members or sub-groups excluded at any depth | each exclusion with its reason and its instances; a sub-group emptied, with `"all its members excluded: <reason>"` |

`zero_counts` has no default. Every derived value of a group repeats what
the tree left out: its trace says `left out: B (count 0 in the table),
C (excluded: sent ahead)`.

## The four states of a value

| State | How it is written | In a derivation |
|---|---|---|
| known | `Value(x, source, origin, unit=...)` | read by the rule |
| unknown | the parameter is absent from every sheet of the member, or `Value(None, ...)`, a value to be set | handled by the policy for the unknown (below), and counted |
| assumed | never on a member: a derivation replaces an unknown input by the value the caller assumes | read by the rule; the trace names the members it replaces |
| not applicable | `Value(None, ..., not_applicable="carried by A")`, or the TOML key `not_applicable`; never `NaN`, which protee refuses | left out under every policy, with its reason; never counted as unknown |

`Value.state` is `known`, `unknown` or `not_applicable`; `assumed` is a
state of an input of a derivation only (`DerivationInput.state`).

> **Declare what does not apply.** Under `propagate`, an unknown input
> leaves the derived value to be set: the rule is strict, and a gap in
> the data is never filled silently. A parameter that has no meaning for
> a member (a member carried by another has no fording depth of its own,
> a liquid bulk has no width) would be such a gap if its value were
> simply absent: it would leave the value of the whole group to be set
> for good, or push toward `known_only`, which leaves out every unknown
> input, real gaps included. Declared not applicable, with its reason,
> it is left out formally: the strict rule stays strict for the values
> really missing, and the trace says which member is left out and why
> (`left out: load-d (not applicable: carried by carrier-c)`). Declare
> it in the sheet whenever a value cannot exist; leave a value absent
> only when it exists and is not known.

If every input is not applicable, the derived value is not applicable
too (`"not applicable to any member of 'G': A (carried by B)"`), and a
requirement that needs it is not applicable, with that reason. In
`resolve_values`, a value not applicable and a value to be set of the
same precedence disagree: one of them must prevail by its precedence.

## The policy for the unknown

Each derivation takes the keyword `unknown`, an `OnUnknown`, without
default:

| Policy | Built by | An input without a value | Refused for |
|---|---|---|---|
| `propagate` | `OnUnknown.propagate()` | leaves the derived value to be set, naming the inputs without a value; an envelope keeps the bound of the known inputs (see [the partial envelope](#the-partial-envelope)) | nothing |
| `known_only` | `OnUnknown.known_only(justification)` | left out, counted, with the justification | the additive rules `sum`, `mean`, `threshold_count` and `column_length`, which it would shorten; `select_by_class`, which reads a single class |
| `assume` | `OnUnknown.assume({parameter: value})` | takes the value assumed for its parameter: a known value of origin `choice`, with its justification | nothing |

- **Every unknown is counted.** Whatever the policy, `Derived.unknown`
  counts the inputs without a value of each derived parameter (their
  names and instances), `Derived.assumed` those replaced by an assumed
  value, `Derived.left_out` those left out (objective 6: every result
  counts its unknowns).
- **An assumption is declared.** Under `assume`, an unknown input whose
  parameter has no assumed value is refused, and so is a value assumed
  for a parameter that no rule reads. A value that replaces no input is
  allowed, and not recorded: the same policy serves several variants.
- **One policy per call.** Two parameters that need two policies take
  two calls on the same group, joined by `Derived.merge`.
- **Counting the known members only.** `known_only` is refused for
  `threshold_count`, a count; assume instead a value that does not cross
  the threshold, justified as "an unknown member counted as not
  crossing": the choice is declared and traced.

**Refined propagation for ordered labels.** Under `propagate`, the known
inputs sometimes decide already, whatever the unknown ones:

- `strictest`, when a known value is the last label of the order: no
  member can be stricter;
- `classify_by_thresholds`, when a known characteristic reaches the
  highest rank of the scale.

The value is then computed, and its trace keeps the inputs without a
value: `decided by width despite unknown values for mass`. Never for a
number (`max`, `min`, even with `inf`), a sum, a mean, a count or the
length of a column: there the value stays to be set.

## The derivations

`derivations()` lists them, each with its rules, its use cases and its
reference (`DerivationInfo`); the registry is closed until version 1.0.

| Derivation | Rules | Reads | Use |
|---|---|---|---|
| `aggregate` | `max`, `min`, `strictest`, `sum`, `count`, `mean`, `threshold_count` | the members of a group, flattened | the envelope of a group, the pace of its slowest member, its number of members |
| `classify_by_thresholds` | `highest_rank` | characteristics of a subject, thresholds from a text | a category by length, width and mass |
| `select_by_class` | `table` | a class, a table, values from a text | a speed cap by category |
| `column_length` | `geometric`, `density` | a group, level by level, and the values of its groups | the length of a column |

What they share:

- **Vocabulary.** The keyword `parameters` gives the units and resolves
  the aliases of the sheets, as in `resolve_values`: the parameters of
  the requirements and those of the rulebooks read.
- **Exact arithmetic.** A float is read as the decimal it shows (`0.1`
  is one tenth), an integer exactly, `inf` as a known value (no limit).
  Every computation is exact, and its result rounded once: it depends on
  the members and their counts, never on their order, and a value at a
  threshold is compared exactly.
- **The derived value.** Origin `derived`, the unit of its output
  parameter, and a precedence (keyword `precedence`, 0 by default). Its
  value set is named after the group (`aggregate`, `column_length`) or
  after a declared `rulebook` (`classify_by_thresholds`,
  `select_by_class`), with the declared `edition`.
- **Units.** A derived value keeps the unit of its inputs: the maximum
  of a parameter in m goes into a parameter in m; a count, a class and a
  label have no unit. An input in another unit is converted with the
  [extra `units`](#the-optional-extra-units), refused without it.
- **Chains.** A classification reads derived values (an envelope), a
  selection reads the class. `Derived.merge` joins the values of several
  derivations of the same rulebook and edition into one value set:
  `resolve_values` takes one value set per rulebook and edition.

### aggregate

`aggregate(group, rules, *, parameters, unknown, edition)` gives a value
per output parameter, each by its rule (`Aggregation`). With *v* the
value of a member and *c* its count in the flattened group:

| Rule | Built by | Value | Fixed by | Unit |
|---|---|---|---|---|
| `max`, `min` | `Aggregation.max(of)`, `Aggregation.min(of)` | the largest or the smallest *v*; the counts play no part | the members that reach it, ties all cited | that of `of` |
| `strictest` | `Aggregation.strictest(of, order)` | the label of highest rank in `order`, given from the least to the most demanding | the members at that rank | none |
| `sum` | `Aggregation.sum(of)` | the sum of *c v* | the members read | that of `of` |
| `count` | `Aggregation.count()` | the sum of *c*; reads no value | every member | none |
| `mean` | `Aggregation.mean(of)` | the sum of *c v* over the sum of *c*; for additive quantities only (lengths, masses), which the code cannot check | the members read | that of `of` |
| `threshold_count` | `Aggregation.threshold_count(of, threshold, comparison)` | the sum of *c* over the members whose *v* crosses the threshold, a value with its source, by a declared `Comparison` | the members counted | none |

`aggregate` never reads the values of the group itself.

### classify_by_thresholds

Each characteristic (`Characteristic(parameter, thresholds, crossing)`)
names a parameter of the subject, its thresholds, taken from a value set
of a text, and when a value crosses them. The rank of a characteristic
is one plus the number of thresholds its value crosses; the class is the
label of the highest rank: the strongest characteristic decides. The
trace cites the characteristics at that rank (every one at rank 1), each
with the highest threshold it crosses and its source.

| `Comparison` | *x* crosses *b* when | For a text that says | Thresholds |
|---|---|---|---|
| `above` | *x* > *b* | "up to *b*": *b* stays in the lower class | increasing |
| `at_least` | *x* >= *b* | "from *b*": *b* moves up | increasing |
| `below` | *x* < *b* | a smaller value is stronger, *b* stays | decreasing |
| `at_most` | *x* <= *b* | a smaller value is stronger, *b* moves up | decreasing |

**Why the closure is declared.** Texts and sheets round their values, so
a value exactly at a threshold is common: a length of 25 m against the
"up to 25 m" of a text, a mass of 72 t against a threshold of 72 000 kg.
A default would place it on one side silently; the declared comparison
says what the text says. The comparison is exact: under `above`, 25 m
stays below the threshold of 25 m, and the next float beyond it crosses.

- One scale: each characteristic has one threshold fewer than there are
  classes, and its thresholds are strictly monotonic in the direction of
  its comparison.
- A characteristic is unknown when its value or one of its thresholds
  has none; a characteristic not applicable is left out; a threshold
  not applicable is refused (a threshold is a number).
- Under `propagate`, a known characteristic at the highest rank decides;
  otherwise the class is to be set, and its trace keeps the class of the
  known characteristics as a bound (the class is at least as strict).
  `known_only` classifies on the known characteristics, which may
  underestimate the class: its justification says why it may.

### select_by_class

`select_by_class` reads the class of the subject (`by`, derived or
given), and takes the value of the parameter its table names, resolved
in the values of a text, in the unit of the output.

- **A class without a value of its own** has the entry
  `NotApplicable(reason)`: the value selected is not applicable,
  `"class '2' has no value of its own: <reason>"`, and so is the
  requirement that needs it. Never an infinite limit: "no limit" is a
  value the text does not give, and a requirement would read the arcs
  and count their unknowns for a limit without effect.
- A class absent from the table is refused, never passed over.
- An unknown class leaves the value to be set under `propagate`, and
  takes the class assumed under `assume`; `known_only` is refused.
- A class not applicable, or a value selected not applicable, gives a
  value not applicable; a value selected to be set, a value to be set.
- A table with two keys (a class and a kind of road) takes one call per
  output, each bound to a requirement of its own scope.

### column_length

`column_length` gives the length a group occupies in a column, level by
level: the group at the head is at level 0, its sub-groups at level 1,
and so on. With *n* the sum of the counts of a group:

| Form | Given by | A group of members | A group of groups |
|---|---|---|---|
| `geometric` | `member_length` | the lengths of its members, each times its count, plus *g(n)* gaps | the lengths of its units, each times its count, plus *g(n)* gaps |
| `density` | `density` | *n* over its density, which holds the gaps between its members | as in the geometric form |

The number of gaps *g(n)* is declared for each level, without default
(`Gap(parameter, count, at_pace=False)`, `GapCount`):

```
 between    n - 1 gaps    [A]-[A]-[B]      units end to end, a line
 per_unit   n gaps        [A]-[A]-[B]-     each unit with its gap (a density)
```

- `spacing` gives one gap per level of groups; in the density form,
  none for the groups of members, whose density holds their gaps.
- A gap in time (`at_pace=True`) is a duration times the pace. A gap, a
  density and a pace are values of a group (`Group.values`), read on the
  group, else on its nearest ancestor that gives them, else in
  `context`: the pace of the slowest member, derived by `aggregate`
  (`min`), typically.
- A group holds members only or groups only, and its groups of members
  are all at the same depth.
- A member whose length is not applicable (it is carried) is out of the
  column, without length or gap.
- `known_only` is refused: it would shorten the column. The length is
  not rounded further: the time to pass a point belongs to the time
  module.
- Units: a length and a gap in distance in the unit of the output, a
  density in the inverse of that unit (write `1/km`, not `veh/km`), a
  pace in the unit of the output per the unit of the gaps in time.

Three members of 12 m with gaps of 50 m measure 3 x 12 + 2 x 50 = 136 m
`between`, and 186 m `per_unit`. Two sub-groups of 30 members at a
density of 10 per km, with 10 min between them at 60 km/h, measure
2 x 3 km + 10 km = 16 km (the pace converted from km/h to km/min).

## The trace of a derived value

Every derived value carries a `Derivation`, in a canonical form that
does not depend on the order of the members:

| Field | What it holds |
|---|---|
| `name`, `rule` | the derivation of the registry and its rule |
| `settings` | the declared options: the parameter read, the order, the comparison, the characteristics and classes, the table, the spacing, the policy for the unknown and its justification |
| `fixed_by` | the members, characteristics or class that fix the value, ties all cited; none for a value to be set |
| `inputs` | every input (`DerivationInput`): its role, parameter, holder, state, instances, and its value as read, with its source (and its own derivation, for a derived input) |
| `assumptions` | the values assumed, with the members they replace (`Assumption`) |
| `left_out` | the members or inputs left out, with their cause (`zero_count`, `excluded`, `not_applicable`, `unknown`) and reason (`LeftOut`) |
| `conversions` | each input converted into the unit it is read in, with the exact factor (`Conversion`) |
| `unknown` | the inputs without a value, whatever the policy |
| `bound`, `bound_fixed_by` | for a value to be set by an envelope or a classification, the extreme of the known inputs, and the inputs that fix it |

The trace keeps every input, not only those that fix the value. The
fingerprint of the inputs (`provenance`, `fingerprint`) covers them all:
a member that fixes no value still changes it, and a result replays only
on the same members. `Provenance.derivations` records, for each derived
value used and those it reads in turn, its parameter, subject,
derivation, rule and the inputs that fix it, for instance
`("length", "convoy", "aggregate", "max", ("load-3",))`.

### What the requirement table shows

`RequirementRow.to_dict()` gives each value, retained or discarded, the
reason it is not applicable (`"not_applicable"`) and its
`"derivation"` (`None` for a value that is not derived): the fields
above as data, each input with its own derivation, so that a chain is
shown whole (a speed selected by a category, the category, the envelope
it reads), and a `"summary"` in words. `to_dict(readable=True)` adds
`"shown"`, each value as a person reads it, at every depth.

Summaries, as the tests produce them:

- A maximum, fixed by one member:
  `max of 'length' over convoy: 27 m, fixed by load-3 (Technical sheet of load-3 (1), p. 2)`
- A class, fixed by the characteristic that crosses the highest
  threshold:
  `highest rank of length, mass, width: '3', fixed by 'length' (27 m above 25 m, art. 3)`
- A value selected by the class:
  `selected by 'category': 50 km/h, for class '3', from 'oversize_category_3_speed_road' (Arrêté du 4 mai 2006 relatif aux transports exceptionnels (consolidated, in force on 2026-11-18), art. 14)`
- A class without a value of its own:
  `selected by 'category': not applicable (class '2' has no value of its own: the 2nd category has a speed of its own in built-up areas only (art. 14))`
- A partial envelope:
  `min of 'fording_depth' over column: unknown, at most 0.5 m (fixed by truck-b (Technical sheet of truck-b (1), p. 3)); 1 member without a value: carrier-c; left out: load-d (not applicable: carried by carrier-c)`
- An assumed value:
  `min of 'fording_depth' over column: 0.5 m, fixed by truck-b (Technical sheet of truck-b (1), p. 3); assumed for carrier-c: 0.6 m (no sheet: the depth of a carrier of its class); left out: load-d (not applicable: carried by carrier-c)`
- A decision despite unknown values:
  `strictest of 'load_class' over M: 'C70', fixed by B (Sheet sheet-B (1), p. 4); decided by B despite unknown values for U`
- The known members only:
  `max of 'width' over M: 3.5 m, fixed by B (Sheet sheet-B (1), p. 4); left out: U (unknown: the members without a value are towed)`
- An additive value to be set:
  `sum of 'length' over M: to be set: no value of 'length' for U`
- A row of count 0 and an exclusion:
  `max of 'width' over Z2: 2.5 m, fixed by A (Sheet sheet-A (1), p. 4); left out: B (count 0 in the table), C (excluded: sent ahead)`
- A conversion:
  `max of 'vehicle_mass' over convoy: 40 t, fixed by A (Sheet (1), p. 4); converted: A 40000 kg to 40 t (x1/1000)`
- A column:
  `column_length (geometric) of pair: 70 m, fixed by A (Sheet sheet-A (1), p. 4), B (Sheet sheet-B (1), p. 4), pair`

## The partial envelope

Under `propagate`, an envelope with an unknown member is to be set. When
some members are known, its derivation keeps the extreme of the known
ones as `bound`, which says on which side the unknown value lies:

| Derivation and rule | The unknown value is |
|---|---|
| `aggregate`, `max` | at least the bound |
| `aggregate`, `min` | at most the bound |
| `aggregate`, `strictest` | at least as strict as the bound, in the declared order |
| `classify_by_thresholds` | at least as strict as the bound, in the order of the classes |

The three admissibility patterns (`threshold_admissibility`,
`capacity_admissibility`, `class_admissibility`) read it. On each arc in
scope:

- **certain failure**: an arc that fails whatever value the bound admits
  fails (`Verdict.FAIL`, `Reason.VIOLATED`): a known member already
  fails it;
- **unknown elsewhere**: every other arc in scope is unknown
  (`Reason.VALUE_TO_BE_SET`, or `Reason.MISSING_DATA` without data);
- **no bound**: without any known member, every arc in scope is unknown.

This is the Kleene conjunction of the verdicts of the members: the group
fails an arc when one member fails it, and passes it only when every
member does; a property the tests check.

**Never a certain pass.** A bound limits the unknown value on one side
only: the members without a value may need more than the known ones (a
larger quantity, a smaller capacity, a stricter class). An arc the
known members pass may fail for them, so it stays unknown, never
presumed compatible (objective 6). The rule is kept simple: even an arc
that would pass any value, an arc without a limit, stays unknown.

**The policy of the search.** The unknown arcs are counted, and
`RouteSearch` or `FlowSearch` applies its own policy to them
(`UnknownPolicy`: `exclude`, `penalize`, `admit_and_count`). Two
policies, at two levels: `OnUnknown` decides what a derivation does
with an input without a value, `UnknownPolicy` what a search does with
an arc of unknown verdict. `verify_route` and `verify_flow` give
`not_applied` when the result uses an arc that fails for certain,
`partial` when it uses unknown arcs, with the bound in their reason:
`1 arcs unknown; value of 'fording_depth' to be set: no value for
carrier-c; at most 0.5 m (truck-b)`. `check_inputs` says beforehand how
many arcs fail at the bound.

**Values to be set that stay not applicable.** A requirement whose value
is to be set is not applicable, with its reason (for a derived value,
the inputs without a value), when the value is not derived (a sheet or a
text that leaves it to be set), when it is derived by another rule
(`sum`, `mean`, `threshold_count`, `select_by_class`, `column_length`),
or when its pattern is not one of the three admissibility patterns (a
speed cap, occurrence bounds).

## The direction of an envelope

`capacity_admissibility` is the mirror of `threshold_admissibility`: the
arc demands, the subject is able. The demand is an attribute of the arc
(the depth of a ford, the grade of an approach), the capacity a value of
the subject (the depth it can ford, the grade it can climb). As for a
threshold, equality passes, an arc without data is unknown and counted,
an arc out of scope passes, and `verify_route`, `verify_flow` and
`check_inputs` check it.

The envelope of a group follows the direction of the requirement it
feeds:

| Pattern | An arc passes when | Envelope of a group | Bound of a partial envelope |
|---|---|---|---|
| `threshold_admissibility` | the quantity of the subject is at most the limit of the arc | `max`: the largest quantity | at least |
| `capacity_admissibility` | the demand of the arc is at most the capacity of the subject | `min`: the smallest capacity | at most |
| `class_admissibility` | the class of the arc is at least the class required, in a declared order | `strictest`, or a classification | at least as strict |

With every member known, the envelope in the right direction is exact:
its verdict on each arc is the conjunction of the verdicts of the
members. The code does not check the direction: the maximum of a
capacity would admit arcs that a member cannot cross. Choose it with the
pattern.

## The optional extra units

```
pip install "protee[units]"
```

The extra brings pint (0.26 or later), imported on first use, never by
`import protee.constraints`.

- **Exact conversions.** An input in another unit than the one it is
  read in is converted into it, exactly: the values of the members, the
  value assumed and a threshold into the unit of the parameter read; a
  threshold of a classification into the unit of its characteristic;
  the value selected into the unit of the output; the lengths and gaps
  of a column into its unit, a density into its inverse, a pace into the
  unit of the column per the unit of the gaps in time. Each conversion
  is recorded with its exact factor (`"1/1000"` from kg to t, `"5/18"`
  from km/h to m/s); a converted value is a float rounded once, `inf`
  stays `inf`, and comparisons stay exact: 72 t is in the 2nd category
  against a threshold of 72 000 kg.
- **Refusals.** A conversion is refused, never guessed, for a unit pint
  does not know (a unit of count: write `1/km`, not `veh/km`), two units
  of different dimensions, a unit with an offset (`degC`), a calendar
  convention (a year or a month: pint counts 365.25 days and a twelfth
  of it, a life-cycle profile 366 and 30.5 days; state such a duration
  in days), a text, and a value without a unit into a parameter with
  one, or the reverse. `resolve_values` converts nothing: every value it
  reads, derived or not, must be in the unit of its parameter.
- **Readable display.** `readable(value)` shows a value as a person
  reads it: a duration in days, hours and minutes (`"1 h 30 min"`), a
  length in km from 1 km on (`"12.4 km"`) and in m below (`"0.75 m"`),
  `"no limit"`, `"to be set"`, `"not applicable"`.
  `RequirementRow.to_dict(readable=True)` adds it to each value as
  `"shown"`; the default output is the same with or without the extra.
- **Without the extra.** A value already in the unit it is read in never
  needs pint. An input in another unit raises an `ImportError` that
  names the extra (`member 'A': 'mass' in 't', the parameter is in 'kg':
  converting needs pint, install the optional extra protee[units]`), and
  so do `readable` and `to_dict(readable=True)`. The values never differ:
  the extra gives a value where its absence gives an error.

## Example: the order of 4 May 2006

The order of 4 May 2006 on exceptional transport (France) sets the
category of a transport by its length, its width and its mass, with "up
to" thresholds (article 3), and the speed cap of each category by kind
of road (article 14); the 1st category follows the general limits, the
2nd has a speed of its own in built-up areas only. protee embeds these
values from the public text (`fr-oversize-transport-2006`). A group of
three invented vehicles goes through three derivations: its envelope,
its category by article 3, its speed cap on a road by article 14.

```python
from protee.constraints import (
    Aggregation, Characteristic, Comparison, Derived, Group, Member,
    NotApplicable, OnUnknown, Origin, Parameter, RulebookValues, Source,
    Value, ValueSet, aggregate, classify_by_thresholds, select_by_class,
)

text = RulebookValues.load("fr-oversize-transport-2006")
vocabulary = (
    Parameter("length", unit="m"), Parameter("width", unit="m"),
    Parameter("mass", unit="kg"), Parameter("category"),
    Parameter("speed_road", unit="km/h"), *text.parameters,
)

def vehicle(id, length, width, mass):
    """An invented vehicle, described by its technical sheet."""
    source = Source(f"Technical sheet of {id}", locator="p. 2")
    given = {"length": (length, "m"), "width": (width, "m"),
             "mass": (mass, "kg")}
    return Member(id, (ValueSet(f"sheet-{id}", "1", {
        k: Value(x, source, Origin.STATEMENT, unit=u)
        for k, (x, u) in given.items()
    }),))

convoy = Group("convoy", (
    (vehicle("load-1", 18.0, 3.0, 40000.0), 1),
    (vehicle("load-2", 22.0, 3.5, 60000.0), 2),
    (vehicle("load-3", 27.0, 3.2, 52000.0), 1),
))
envelope = aggregate(
    convoy, {p: Aggregation.max(p) for p in ("length", "width", "mass")},
    parameters=vocabulary, unknown=OnUnknown.propagate(), edition="1",
)
category = classify_by_thresholds(
    envelope,
    characteristics=[
        Characteristic(p, (f"oversize_{p}_category_1_max",
                           f"oversize_{p}_category_2_max"),
                       Comparison.ABOVE)  # "up to": a threshold stays below
        for p in ("length", "width", "mass")
    ],
    thresholds=text.values, classes=("1", "2", "3"), output="category",
    parameters=vocabulary, unknown=OnUnknown.propagate(),
    rulebook="oversize-category", edition="1",
)
speed = select_by_class(
    category, by="category",
    table={
        "1": NotApplicable("the 1st category follows the general limits "
                           "(art. 14)"),
        "2": NotApplicable("the 2nd category has a speed of its own in "
                           "built-up areas only (art. 14)"),
        "3": "oversize_category_3_speed_road",
    },
    values=text.values, output="speed_road", parameters=vocabulary,
    unknown=OnUnknown.propagate(), rulebook="oversize-category",
    edition="1",
)
subject = Derived.merge(category, speed)
```

The envelope is 27 m, fixed by load-3, 3.5 m and 60 000 kg, fixed by
load-2; the length alone crosses the second threshold, so the category
is `'3'`, fixed by `'length'`, and the speed cap on a road 50 km/h.
`resolve_values([envelope.values, subject.values], requirements)` gives
them to a `speed_cap` requirement of scope `road`, bound to
`speed_road`: the envelope and the category enter as values no
requirement reads, cited by the derivation of the speed, and the table
shows the whole chain (the summaries above). A group of load-1 and
load-2 alone is of the 2nd category by its three characteristics: its
speed cap on a road is not applicable, and so is the requirement, with
the reason of article 14. The test
[`tests/test_constraints_chain.py`](../tests/test_constraints_chain.py)
runs this chain to a verified route.

## Example: a group that crosses fords

The water of a ford must be no deeper than every vehicle of the group
can ford (`capacity_admissibility`: the envelope is the minimum), and
the ford as wide as every vehicle needs (`threshold_admissibility`: the
maximum). The sheet of carrier-c gives no fording depth: its depth is
unknown, as every value of a member without a sheet. load-d is carried
by carrier-c: it has neither a depth nor a width of its own, declared
not applicable.

```python
# The imports of the previous example.

def vehicle(id, **values):
    """An invented vehicle; a text is the reason a value does not apply."""
    source = Source(f"Technical sheet of {id}", locator="p. 3")
    return Member(id, (ValueSet(f"sheet-{id}", "1", {
        k: Value(None, source, Origin.STATEMENT, unit="m", not_applicable=x)
        if isinstance(x, str)
        else Value(x, source, Origin.STATEMENT, unit="m")
        for k, x in values.items()
    }),))

column = Group("column", (
    (vehicle("truck-a", fording_depth=0.75, crossing_width=2.5), 3),
    (vehicle("truck-b", fording_depth=0.5, crossing_width=3.0), 2),
    (vehicle("carrier-c", crossing_width=3.6), 1),
    (vehicle("load-d", fording_depth="carried by carrier-c",
             crossing_width="carried by carrier-c"), 1),
))
ford = (Parameter("fording_depth", unit="m"),
        Parameter("crossing_width", unit="m"))
envelope = aggregate(
    column,
    {"fording_depth": Aggregation.min("fording_depth"),    # a capacity
     "crossing_width": Aggregation.max("crossing_width")},  # a quantity
    parameters=ford, unknown=OnUnknown.propagate(), edition="1",
)
```

The width is 3.6 m, fixed by carrier-c. The depth is to be set, with
the bound 0.5 m fixed by truck-b: whatever carrier-c fords, the group
fords at most 0.5 m. Two requirements of scope `ford` read them,
`FORD-DEPTH` (`capacity_admissibility`, `parameters={"capacity":
"fording_depth"}`, `attributes={"demand": "water_depth"}`) and
`FORD-WIDTH` (`threshold_admissibility`, `parameters={"quantity":
"crossing_width"}`, `attributes={"limit": "ford_width"}`), on this
network:

```
          a0 road, 2 km             a1 ford, 0.6 m deep, 4 m wide, 2 km
   0 ----------------------> 1 ----------------------> 3
          a2 road, 2 km             a3 ford, 0.4 m deep, 3 m wide, 2 km
   0 ----------------------> 2 ----------------------> 3
          a4 ford, 0.3 m deep, 5 m wide, 6 km
   0 ------------------------------------------------> 3
          a5 road, 5 km             a6 road, 5 km
   0 ----------------------> 4 ----------------------> 3
```

- a1 fails for certain: 0.6 m of water is deeper than truck-b fords,
  whatever carrier-c fords.
- a3 fails: 3 m is narrower than the 3.6 m carrier-c needs.
- a4 is unknown: carrier-c may ford less than 0.3 m.

With `UnknownPolicy.ADMIT_AND_COUNT`, `RouteSearch` takes a4 (6 km, one
unknown arc counted); its verification gives `FORD-DEPTH` `partial` and
`FORD-WIDTH` `applied`. With `UnknownPolicy.EXCLUDE`, every ford is
barred and the route goes by road (10 km). With
`OnUnknown.assume({"fording_depth": Value(0.6, Source("Planning note"),
Origin.CHOICE, unit="m", justification="no sheet: the depth of a carrier
of its class")})`, the depth is 0.5 m, still fixed by truck-b, and the
trace says what was assumed, and for whom. The test
[`tests/test_constraints_derived_chains.py`](../tests/test_constraints_derived_chains.py)
runs these cases.

## Life-cycle profiles

An equipment may come in several variants, a packaging for instance,
each a member with its sheet: the occurrences and durations of each
situation it goes through. The members of a group crossing an arc are
all there at once, and their envelope is exact; the variants of an
equipment are alternatives, and their envelope (the `max` of each
maximum number of occurrences, of each duration) gives dimensioning
values that are only a bound, never the profile of a variant. The worst
case of a profile grows with its durations and its maximum occurrences,
so the worst case of the envelope is at least that of every variant
taken alone; it may be larger, since it can combine the longest duration
of one variant with the largest number of occurrences of another. In the
tests, three packagings whose worst cases are 10, 6 and 14 give an
envelope whose worst case is 14.

**Minima do not envelope as maxima do.** For a maximum, the most
demanding value of the variants, the largest, also admits every
variant: it is the dimensioning value and a bound at once. For a minimum
number of occurrences, these are two different values. The most
demanding, the largest minimum, restricts the profiles admitted and may
leave none (the problem becomes infeasible): it is no bound. The
smallest minimum admits every variant: a bound, but not a dimensioning
value. Where the variants differ in their minima, compute the worst case
of each variant alone.
