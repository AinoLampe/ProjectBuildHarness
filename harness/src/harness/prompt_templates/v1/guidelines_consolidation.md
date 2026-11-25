Check the following concept and guidelines for conflicts. If any exist,
harmonise them with the concept winning ("what" outranks "how" — concept §7):

Concept:
{{concept}}

Guidelines:
{{guidelines}}

Respond with exactly one JSON object matching this schema — no prose, no
fencing:

{"conflict_found": bool, "conflict": string|null, "resolution": string|null,
"revised_concept": string|null}

`conflict_found` must be `true` only if there is an actual conflict between
the concept and the guidelines; otherwise `false` with the other fields
`null`. `revised_concept` should contain the complete, revised `concept.md`
content only if the concept itself needs to change to stay consistent with
the resolution — otherwise leave it `null`.
