# V5 sealed English routing corpus

This is a newly authored synthetic evaluation corpus. It was prepared by the
evaluation assistant `/root/v3_capacity_codec`, separately from the assistant
building the V5 router. It is not a collection of real user requests, a human
survey, or an independent human annotation study. The author did not read the
new V5 training/development corpora, candidate predictions, scores, or selected
thresholds. No routing model was executed during authoring or review.

The corpus contains 216 independently written English expressions: 24 for each
of six supported intents, and 72 nearby unsupported requests across 12 families.
Date/entity substitution does not create additional independent expressions.
There is no Chinese challenge set in this sealed primary corpus.

## Authoritative task boundary

Let `t` be the calendar month in the explicit date slot, and let `x[k]` denote the
stored value of the same named monthly series at `t + k calendar months`. The
contract is taken from the restored V3 `route_language.DESCRIPTIONS` and the
independent `numeric_graph.target_for` grader. The latter also fixes support order.

| Label | Required operation | Ordered support offsets | Result |
| --- | --- | --- | --- |
| `at` | `x[0]` | `[0]` | One stored numeric value |
| `previous` | `x[-1]` | `[-1]` | One stored numeric value |
| `change` | `x[0] - x[-1]` | `[-1, 0]` | Signed difference in original units |
| `mean3` | `(x[-2] + x[-1] + x[0]) / 3` | `[-2, -1, 0]` | Equal-weight arithmetic mean |
| `range3` | `max(x[-2], x[-1], x[0]) - min(x[-2], x[-1], x[0])` | `[-2, -1, 0]` | Numeric range width |
| `peak3` | `max(x[-2], x[-1], x[0])` | `[-2, -1, 0]` | Maximum numeric value, not its month |

Every supported task is a single-series scalar request. Three-month windows
include the anchor month and the immediately preceding two calendar months.
Previous means exactly one calendar month, including year-boundary rollover.
The requested operation determines the label; accidental equality of two
operations on particular data does not make their labels interchangeable.

A request is unsupported if its operator, temporal support, input arity, or
output type differs from these six tasks. This includes relative percentage
change, ratios, fitted regression slopes, population z-scores, min-max scaling,
medians, alternative windows, other aggregates, peak-month outputs, forecasts,
cross-series operations, and transformed or reversed adjacent differences.
Some V3 graph distractor callbacks can compute other aggregates; their existence
does not add admitted intent labels. The corpus follows the six-label whitelist.

The literal separate series name used in cross-series requests refers to a
different variable, never to an alias of the main series. Such requests are
unsupported because they require multiple series, independently of whether the
extra data happen to exist.

## Data and inference schema

`queries.en.json` has top-level keys `schema` and `queries`, with schema
`hepta.memory.v5.sealed-language.v1`. Each row has:

- `query_id`: neutral stable expression identity.
- `utterance`: a template using only `{series_name}` and `{date}`.
- `series_name` and `date`: corresponding slot placeholders; the concrete date
  supplied during materialization has format `YYYY-MM`.
- `gold_intent`: one of the six labels, or JSON `null` for unsupported requests.
- `ood_family`: `null` for supported requests, otherwise a grading-only family.
- `risk_group`: `known` or `near`.
- `partition`: `sealed_held_v5`; `language`: `en`.
- `allow_numeric_read`, `expected_provenance_offsets`, `requested_operator`, and
  `label_reason`: grading metadata, never model inputs.

**The inference function receives only `utterance`, `series_name`, and `date`.**
The evaluator may map a null gold label to `__reject__` internally. Query IDs,
gold labels, family names, requested operators, support offsets, permission
labels, and judgement explanations must not enter features or model decisions.
No numeric answer values appear in this corpus. Numeric targets must be graded
separately from independently decoded source facts.

The root evaluator materializes slots only after model/source/threshold freeze.
It must choose dates whose required supported monthly facts exist and apply the
same slot policy to supported and unsupported queries. Reusing an expression at
other dates, in other domains, or under other seeds is a repeated measurement of
that expression, not an additional independently authored language sample.

## Seal and review boundary

`author_corpus.py` contains the phrases as well as their labels; it is as sensitive
to heldout leakage as the JSON corpus. Do not read either from model development.
`seal_held.py` records schema checks, within-corpus deduplication, and an exact
normalized overlap check against the restored legacy V3 templates. That check
does not prove distributional independence or absence of overlap with every
historical corpus. V4 held wording was not used to construct these expressions.

The same evaluation author reviewed all 216 rows for operation, direction,
calendar scope, scalar versus date output, and single-series versus multi-series
meaning. This is an author semantic review, not a second independent adjudication.

`SEAL.json` binds the raw corpus bytes and the authoring/review/control files.
Its own SHA-256 must be registered in the root freeze record before opening the
held corpus. The seal excludes itself to avoid a circular hash. Once sealed,
these files are not edited in response to model results. Any later discovered
language issue requires a separate erratum preserving this original corpus and
its originally declared evaluation identity; it must not silently replace the
primary benchmark or retune the model/thresholds on its labels.
