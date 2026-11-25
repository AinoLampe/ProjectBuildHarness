You are implementing ticket {{ticket_id}} of an active harness run (Stage 3,
concept §10).

Read, in this order, once at the start of your session (this bootstrap
instruction is re-sent fresh for every ticket, since each `claude -p` call
has no memory of a prior ticket's session):

1. The frozen concept (architectural source of truth): {{frozen_concept_path}}
2. The frozen guidelines (engineering source of truth): {{frozen_guidelines_path}}
3. The overview ticket (dependency graph, build order, conventions): {{overview_path}}
4. This ticket's own text, below.

If the concept and guidelines conflict, resolve it with a reasonable
decision and log it to {{journal_dir}}/DECISIONS.md — the concept always
wins ("what" outranks "how"). If something is genuinely ambiguous, do not
guess: stop and escalate to the user.

Ticket text:
{{ticket_text}}

Implement exactly this ticket's scope. Do not implement anything the ticket
marks "Out of scope" — that is deferred to a later ticket by design.
