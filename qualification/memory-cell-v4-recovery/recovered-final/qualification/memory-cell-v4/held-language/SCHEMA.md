# Independent V4 language holdout

`query-templates.json` contains 216 individually authored English expressions:
24 for each supported intent and 72 near-neighbor unsupported requests in 12
families. Changing a series name or a date does not create a new independent
expression. These are authored fixtures, not sampled human conversations.

The capacity/transfer owner authored this file without executing a router on it.
The routing owner receives only this schema, counts and file digest during
development. Root materializes the formal rows only after source, protocol and
policy selection are frozen. A pre-freeze check may validate schema, unique IDs,
placeholders and exact overlap with V3; it must not score any router or choose
hyperparameters from these expressions.

## Materialization

Each row has `id`, `utterance`, `series_name`, `date`, `intent`, `partition`,
`scope`, `family`, `risk_group`, `provenance_offsets`, `operator`, `result_type`
and `allow_read`. Only the utterance and explicit `series_name` / `date` slots
are allowed into inference. The other fields belong to the evaluator.

Replace `{series}` with the declared source name and `{date}` with an existing
anchor in `YYYY-MM` form. Anchors must have two preceding recorded calendar
months. Use the same anchor schedule for all intents; dates must not encode
intent. Retain a `template_id` when creating concrete row IDs. The independent
language denominator is the 216 templates, even if several domains, anchors or
seeds instantiate each template.

All rows have scope `numeric-study` and partition `formal-held-v4`.
Supported rows have risk group `known`. Unsupported rows have risk group `near`
and intent `__reject__`; they require abstention and no source reads. Their
empty provenance is the required execution outcome, not a claim that the
requested unsupported computation would need no inputs.

## Evaluator semantics

Offsets are in calendar months relative to the explicit anchor. Provenance is
in chronological input order, matching the existing numeric typed executor.

| Intent | Required offsets | Reduction | Result |
| --- | --- | --- | --- |
| `at` | `[0]` | identity | One stored number |
| `previous` | `[-1]` | identity | One stored number |
| `change` | `[-1, 0]` | last minus first | Signed difference in source units |
| `mean3` | `[-2, -1, 0]` | arithmetic mean | Number |
| `range3` | `[-2, -1, 0]` | maximum minus minimum | Nonnegative number |
| `peak3` | `[-2, -1, 0]` | maximum value | Number, not the maximizing date |
| `__reject__` | `[]` | abstain | No numeric answer |

Actual target values are absent. The file contains no answer catalog, numeric
source payload, router scores, embeddings or training examples.
