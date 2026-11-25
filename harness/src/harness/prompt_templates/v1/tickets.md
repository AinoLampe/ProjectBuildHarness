You are writing the Stage 2 implementation tickets from the frozen spec
(concept §9). Read in this order:

Frozen concept:
{{concept}}

Frozen guidelines:
{{guidelines}}

Active phase scope:
{{phasing}}

Write `## TICKET: 000-overview` **first** — it must define the dependency
graph, a valid build order, and the conventions every other ticket must
follow (naming, file locations, testing expectations, definition of done).

Then write one `## TICKET: NNN-slug` block per problem, each following the
schema: Goal, Creates/changes, Acceptance criteria, Out of scope,
Connections (plus optional sections). Apply the granularity rule: one
problem, one ticket — split anything too large to implement and review in
one pass, and merge anything too trivial to stand alone.

In each ticket's `### Connections` section, reference other tickets by
their bare 3-digit id (`010`, not `T-010`) under `depends on:`, `blocks:`,
or `relates to:`, comma-separated. `depends on`/`blocks` are inverse
declarations of the same ordering edge; `relates to` is informational and
never affects build order. Scope every ticket (except the overview) to the
active phase declared above — do not write tickets for a different phase.
