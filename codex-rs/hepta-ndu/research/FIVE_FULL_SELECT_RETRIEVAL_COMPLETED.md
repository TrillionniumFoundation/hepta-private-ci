# Completed full SELECT frozen-feature retrieval

Date: 2026-10-15. Development evidence only; not an independent confirmation
set, answer-quality result, Reader-skipping policy or production admission.

## Exact completed execution

The fixed full-pool retrieval workflow completed successfully:

- source commit: `8e213b7585221ddf9fd279037caa4dc6f972af6c`;
- workflow run: `38540293994`;
- job: `115773087793`;
- artifact: `11885366683`, `hepta-full-select-retrieval-development`;
- GitHub artifact ZIP SHA256:
  `6534177c6974ee0e9fe0a331891ec5cb0b2443481198ece36cfcaf754003d436`.

The saved disposition records `model_execution_completed=true`, zero Reader
calls and zero new optimizer updates. The run passed the submitted retrieval and
inherited representation regressions, authenticated all three fixed upstream
origins, encoded only missing public features and sealed the complete score
matrices before producing summaries.

## Exact denominator and work

The registered development census is:

- 296 planned SELECT questions;
- 295 scored questions and one retained unavailable question;
- two source families;
- 249 unique scoped evidence candidates;
- 248 encodable evidence candidates and one retained unavailable candidate;
- 73,160 cosine comparisons and 73,160 lexical comparisons;
- one strict archived Encoder load and 19 actual new Encoder forwards;
- all 15 saved Head/seed objects reloaded and replayed read-only;
- zero Head, Encoder or Reader optimizer updates.

The answer body never entered feature text, lexical scoring, neural scoring,
candidate selection or the readout. Missing inputs remained in the planned
denominator and were not converted to zero scores.

## Retrieval result

All counts below use the same 295 scoreable questions. `Unique top-1` rejects
ties; `strict top-5` requires the pessimistic tie rank to be at most five.

| Method | Global unique top-1 | Global strict top-5 | Global MRR | Within-family unique top-1 | Within-family strict top-5 | Within-family MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen-vector cosine | 43/295 | 88/295 | 0.228930 | 46/295 | 91/295 | 0.246316 |
| Lexical Jaccard | 83/295 | 151/295 | 0.402532–0.409688 | 84/295 | 158/295 | 0.409927–0.417064 |
| Linear aligned Head, each seed | 1/295 | 5/295 | 0.024870 | 2/295 | 10/295 | 0.042974 |
| Gated aligned Head, seed range | 1/295 | 7–8/295 | 0.025901–0.027415 | 4–5/295 | 12–13/295 | 0.048260–0.050296 |
| Gated reversed Head, seed range | 2/295 | 6/295 | 0.026572–0.026679 | 3/295 | 11/295 | 0.042766–0.043078 |
| Evidence-only and frozen-gate controls | 0/295 | 0/295 | lower bound 0.004032 | 0/295 | 0/295 | lower bound 0.007969 |

The evidence-only and frozen-gate controls assign tied evidence-independent
scores. Their optimistic tie-aware top-1 count is therefore 295/295, but their
unique top-1 and strict top-5 counts are both zero; the optimistic count is not a
retrieval success.

## Paired complementarity

Lexical Jaccard does not merely dominate the cosine method on every item. On the
same global candidate pool:

- lexical rank is better on 193 questions;
- cosine rank is better on 76 questions;
- the ranks are equal on 26 questions;
- 20 questions are unique top-1 for both methods;
- 63 are unique top-1 only for lexical;
- 23 are unique top-1 only for cosine.

Thus the post-hoc best-of-two unique-top-1 union is 106/295 globally. Within the
source family the corresponding union is 109/295: 21 shared, 63 lexical-only and
25 cosine-only. These unions are diagnostic upper bounds, not deployable methods,
because the per-question better method is selected using the exposed target.

## Interpretation

The result rejects two convenient explanations:

1. the completed three-pair cosine geometry was not sufficient to make frozen
   cosine a strong full-pool retriever; lexical overlap is substantially stronger
   on this exposed development inventory;
2. the from-zero small Heads did not preserve or improve the useful relation
   geometry at full-pool scale. Every trainable saved Head family is far below
   both cosine and lexical baselines, while evidence-only and frozen-gate
   controls are degenerate.

At the same time, cosine-only successes not recovered by lexical show that the
Encoder relation is not reducible to the lexical baseline on every item. The
next justified learning experiment is therefore a preregistered TRAIN-only
fusion or residualization study that asks whether frozen cosine contributes
out-of-sample rank information after lexical overlap is controlled. It must use
SELECT read-only, report all fixed seeds/weights rather than choose the best on
SELECT, include lexical-only, cosine-only, fixed rank-fusion and reversed or
permuted controls, and preserve the one unavailable question/candidate.

This completed retrieval study remains previously exposed development evidence.
It does not establish source sufficiency, answer correctness, calibrated
abstention, independent generalization, Reader-call skipping, shared-versus-
replicated quality equivalence or production readiness.

`reader_adequacy_established=false`, `production_accepted=false`,
`five_experiments_completed=false`.
