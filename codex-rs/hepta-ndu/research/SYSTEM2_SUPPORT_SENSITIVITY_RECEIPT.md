# System2: average few-shot gain survives, no-loss claim depends on support

Parent: `a552e6dbeb85f5f5675d3cba015e4558fa64efac`, PR #1546.
This stage changes no old fit, model, Reader, NDU/FBSDE definition or default policy.

## Completed parent hosted evidence

Run **38155170412** completed for parent `a552e6db...`, tree
`fbb9b2df466cae854237568883857b4744f4ca1c`. Artifact **11709075640**,
699,057 bytes, ZIP SHA256
`63d3b525ca09ee6944332d20cb66f484ea5d3851634fd6774e29bd88e3e764ee`.
All **421 manifest entries / 422 files** verified. Full regression discovery:
**1,028 passed, two skipped, 1,030 total**. The 240 few-shot predictions,
all 240 state-file hashes, prediction seal and question/support identities verify.
All selected candidates match the prior local run; maximum score drift is
2.384185791015625e-7. Two-support differentiated source hits remain **8/20**
versus frozen/shared **6/20**, local-only **7/20**, neighbor **4/20**.
This is full-repository replication on the SAME inputs, not independent evidence.

## Fixed exhaustive-support protocol

A favorable fixed support set does not establish stable behavior for other sets.
Before this stage's first native-feature fit, fix the following protocol:

- Keep the same 20 exposed TRAIN questions, five families, saved paired Encoder
  features, original forbidden roots, top-four proposals, hinge objective,
  regularization 0.01 and frozen stop control. No architecture or parameter search.
- Enumerate ALL one- and two-question support subsets from the same family,
  excluding the query. This yields 68 one-support and 99 two-support episodes.
  The inherited hash-ordered choice remains an anchor, never an optimized choice.
- Reuse the six prior methods and add `swapped_labels`: reverse eligible local
  singleton source-hit/miss labels, keeping feature tensors fixed. This is a
  deliberately synthetic supervision control, not another native/human claim.
  A support question without a contrast stays unavailable for learning.
- Fit each support snapshot ONCE, evaluate it on every other local question.
  There are 20 singleton and 34 pair support snapshots, five shared priors,
  and seven method variants per support snapshot: 378 state conditions.
- Average uniformly across subsets WITHIN each query, then average queries or
  source families equally. Do not let larger families gain weight merely because
  they admit more support combinations. Keep every failure and no-op case.

All 1,169 predictions are written and sealed before final query scoring. A query
label can be support for a DIFFERENT cross-validation episode but never for its
own predictor. Same-root local personalization remains intentional; this is not
root-disjoint, chronological, prospective or independent confirmation.

The primary budget stays two supports. A support-robust progression request
requires positive question-macro mean effect over EVERY fixed comparator and
no source-hit losses versus frozen on ANY admissible support subset. Even a
passing request would still require fresh data and Reader/evidence validation.

## Observed LOCAL cached-native results

**1,169/1,169 predictions succeeded**, zero failed states, zero new Encoder/Reader
calls. All 240 inherited anchor decisions match the completed hosted study.
The erased-update scores/choices equal the shared-prior scores/choices throughout.
All 378 snapshot state hashes verify; five prior state files are retained too.

| Method | One-support query-macro hit rate | Two-support query-macro hit rate | Two-support family macro |
| --- | ---: | ---: | ---: |
| Frozen | .300000 | .300000 | .280000 |
| Shared | .300000 | .300000 | .246667 |
| Local only | .327500 | .360000 | .356667 |
| Shared + local delta | **.342500** | **.395000** | **.380000** |
| Erased local update | .300000 | .300000 | .246667 |
| Support-neighbor memory | .275000 | .266667 | .253333 |
| Swapped support labels | .197500 | .113333 | .080000 |

These are exact averages of finite, previously exposed weak-source observations,
NOT QA accuracy, confidence intervals or statistically independent successes.
At K=2, differentiated has **42/99** raw subset hits and shared **43/99**, yet their
query-macro rates are .395 and .300. This is not contradictory: family sizes and
number of subsets differ. Pooled subset counts are not the declared estimand.

Against frozen at K=2: **14 subset wins, six losses**, spread across three
winning queries and two losing queries. Both losing queries are in conv-49:
`q128` and `q137` each lose their old hit for three of ten possible support pairs.
The old anchor happens not to use those harmful pairs. Average effect is still
**+0.095**, but the broad no-regression claim does NOT survive exhaustive supports.
Against shared: five subset wins/six losses; against local-only: ten wins/three
losses; against swapped labels: 22 wins/zero losses. These are correlated episode
counts, not independent sample sizes. The swapped-label contrast supports a
local diagnostic dependence on correct weak labels, not general semantic learning.

Disposition: **`stop_no_controlled_support_robust_gain`**. Retain the positive
average learning signal for fresh confirmation, but do not deploy the candidate
or describe every two-sample update as safe for existing capabilities.
No support subset or hyperparameter was selected from these observed outcomes.

## Implementation, resources and reproduction

`system2_support_sensitivity.py` reuses the existing prior fit, delta fit,
neighbor, prediction, source admission and saved-feature loader. The cached
snapshot and query must remain unchanged during inference; mutation aborts before
scoring. Per-state starts/fits, synthetic support labels, files, raw predictions,
seal, scoring, per-query counts and all missing/failure bounds are retained.
The maximum episode/snapshot bounds fail explicitly rather than sampling a subset.
The old three replay stages and full hosted regression/static checks are retained.

Local **143/143 System2 tests passed**, including 16 additions, real pinned-archive
checks and fixture integrations exercising the actual runner. The local context
is torch 2.10.0+cpu, safetensors 0.7.0, published source overlays and verbatim
repository data/StemHead forward ports, NOT a complete repository checkout.
Metadata records the overlay parent plus executing file digest. Full-repository
new-head execution is separate. Local Ruff/just are unavailable; no Rust source
changed or CI gate was waived. Syntax and patch checks passed.

Zero model calls does not mean zero cost: original encoding, historical data,
prior fits, all 378 state conditions, state copies/reloads and 1,169 predictions
consume resources. Shared/cached work is recorded separately; no exact
compute-matched or production-TCO claim is made. The weight-only Cell delta
remains 384 FP32 values, excluding shared weights, storage and other overhead.

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_support_sensitivity.py \
  /path/to/system2-content-38147248105.zip /new/output
```

Fresh independent sources, source-before-query timing, actual language answers,
sufficient-evidence judgments, retention checks, multimodal composition and
outcome-calibrated NDU continuation still require their own evidence.
