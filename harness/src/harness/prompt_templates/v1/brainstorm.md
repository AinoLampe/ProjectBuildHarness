You are running Stage 1a brainstorming for an AI implementation harness
(concept §6.1). This is a bounded, structured exchange — not free-form
chat: every round produces the same three-section document below, and the
loop terminates either when no blocking items remain or when the round cap
is reached (documented assumptions are recorded instead of looping).

Requirements:
{{requirements}}

Instructions (optional, may be empty):
{{instructions}}

Prior rounds — questions already asked and the user's answers. Incorporate
them: do not re-ask a question that has already been answered.
{{qa_transcript}}

Produce a structured, severity-tagged `open-questions.md` with exactly
three sections, in this order:

## Assumptions (proceeding unless corrected)
- [severity] assumption text

## Decisions needed (blocking)
- [severity] question text

## Suggested improvements (optional)
- [severity] suggestion text

Tag each item `[low]`, `[med]`, or `[high]`. Leave the "Decisions needed"
section with no bullets once every blocking question from prior rounds has
been resolved. Be concise and concrete.
