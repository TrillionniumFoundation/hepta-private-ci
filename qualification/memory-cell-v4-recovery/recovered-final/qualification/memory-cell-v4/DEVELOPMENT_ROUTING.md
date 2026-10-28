# V4 semantic routing: development history and remaining blocker

## Status and isolation

The public development campaigns do **not** qualify semantic routing. The final
selection rule chooses `dense-mlp64-l20.0001` for both seeds. Correctly accepted
supported coverage is **3/36 = 8.33%** for 8011 and **5/36 = 13.89%** for 8017;
both reject all 34 unsupported development requests. Low false acceptance is not
a substitute for the unchanged **80% correct coverage / 5% OOD** requirements.

Only development seeds **8011 and 8017** were used. No v4 independent held
language body was read by the routing implementer, and no formal seed was run.
The earlier v3 held wording was already disclosed and is named
`v3-disclosed-regression`, never presented as a new independent holdout.

Each attempt has its own immutable output directory, all candidate weights,
corpus rows, cached features, predictions, source-module snapshot, and
`DEVELOPMENT_MANIFEST.json`. The supplied commit
`ddd2ec4f9167c5ccf22adb63f4ce7402ebd7ae19` is the **parent commit**, not an exact
executed v4 commit. The owned-module snapshots retain the exact development
implementation; the committed v2/v3 dependencies and pinned encoder are separate
bindings. No attempt was rewritten after seeing its outcome.

## Changes and their information dependencies

| Attempt | Training rows / candidates per seed | Change before execution | 8011 correct / OOD | 8017 correct / OOD |
| --- | --- | --- | --- | --- |
| `routing-initial-8011-8017` | 356 / 6 | Dense linear, dense MLP64, generic TF-IDF hybrid linear; class-balanced Adam | 16.67% / 8.82% | 8.33% / 2.94% |
| `routing-contrastive-8011-8017` | 2,590 / 8 | Training-only window/direction/statistic contrasts; group-balanced reject sampling weight 3; hybrid MLP64 added | 8.33% / 2.94% | 16.67% / 2.94% |
| `routing-unigrams-8011-8017` | 2,590 / 8 | Retain all training unigrams before frequent compound features; augmentation had displaced rare atomic words | 8.33% / 2.94% | 16.67% / 2.94% |
| `routing-factorized-8011-8017` | 2,854 / 12 | Training operand-order/alignment/output contrasts; independent intent and supportedness heads | 8.33% / 0% | 13.89% / 0% |
| `routing-sequence-8011-8017` | 2,854 / 14 | Two small attention heads over pinned contextual token states, with relative positions; same selection rule | 8.33% / 0% | 13.89% / 0% |

All columns are primary-policy outcomes on the same disclosed public development
set: 36 supported and 34 unsupported requests, including 26 near-OOD requests.
The 70-row selection set is separate in wording but similarly small. Observing
these development outcomes informed the next attempt; these rows are therefore
not independent evidence for final generality.

The final train set contains **370 known rows and 2,484 rejects**. There are
**108 authored positive base templates**. Wrappers, digit spellings and generated
operand-order examples explain the larger row count; these are not 370
independently authored positive paraphrases. The code contains no formal reader.

## Final candidate and selection rules

Seven feature/head pairs, each at L2 `0.0001` and `0.001`, yield fourteen candidates:

- Dense masked-mean MiniLM features: linear, MLP64, factorized MLP64.
- Dense plus training-only generic TF-IDF features: linear, MLP64, factorized MLP64.
- Contextual token features: attention32 with four learned attention heads and
  a shared 64-dimensional hidden layer, trained jointly for six-way supported
  intent and binary supportedness.

Every regular head has 600 Adam steps, batch 128, learning rate 0.015. Each
factorized candidate trains two components for 600 steps each, and both are
charged. Each attention candidate uses 600 joint steps, batch 32, at the same
learning rate. Sampling balances classes and their training families; ordinary
heads use reject sampling weight 3, while the factorized binary component is
balanced. All training, feature and calibration settings are serialized.

Calibration evaluates the fixed 12 confidence thresholds and 8 margin thresholds.
It first requires empirical overall and near-OOD false acceptance at most 5%, then
maximizes **correctly accepted supported coverage**. Primary candidate ties use
actual example-update count, serialized candidate bytes, then fixed candidate
name. Example updates are an explicit tie-break statistic, not FLOPs. The 80%
coverage requirement is checked separately and is never relaxed. Diagnostics,
unthresholded outputs and positional ablations cannot select the primary.

## Annotation and representation audit

Every sealed development payload was independently rehashed. The final training
corpus has zero cross-label conflicts for exact normalized text, tokenized text,
or exactly equal frozen encoder vectors. Train/selection and train/development
normalized-text overlaps are both zero. The automated multiple-negation scan
flags no reject rows. An independent reviewer inspected the public generator and
found no reversed subtraction-form or explicit-negation transformation error.
These checks do not certify every natural-language annotation.

There are **188 single-month aggregate reject rows**. The declared contract
accepts the specified requested operations, including only three-month aggregate
requests. A one-month mean or maximum can be extensionally equivalent to a single
read; rejection here is an **operation-contract restriction**, not a claim that
the system cannot calculate the value. Root explicitly retained this contract
before any v4 formal evaluation. Compound numeric-plus-list requests similarly
exceed the single-result request contract.

There are 36 word-bag groups with different labels due to operand order. Example
MiniLM sentence cosines are approximately 0.9908–0.9928, but vectors are not
identical: this motivates an order-aware head and does not prove information was
irretrievably lost. The attention implementation passes numerical gradient checks
and learns a controlled synthetic same-bag/reversed-order training task.

On public natural-language development, the final primary has unthresholded
correct-known rate **19/36 = 52.78%** in both seeds, and unthresholded OOD false
acceptance **9/34 = 26.47%** and **8/34 = 23.53%**. Correct-known confidence medians
are 0.9685 and 0.9664, while erroneous OOD confidence reaches 0.9944 and 0.9938.
Selection consequently sets confidence 0.995. Errors include reversed subtraction,
window alignment, requested output type, explanations and metadata requests.
Threshold changes alone cannot fix the raw classification errors.

The new attention candidates also fail to qualify:

| Seed | L2 | Raw known correct | Raw OOD false accept | Calibrated known correct | Calibrated OOD false accept |
| --- | --- | --- | --- | --- | --- |
| 8011 | 0.0001 | 63.89% | 23.53% | 13.89% | 2.94% |
| 8011 | 0.001 | 75.00% | 38.24% | 5.56% | 0% |
| 8017 | 0.0001 | 61.11% | 32.35% | 0% | 0% |
| 8017 | 0.001 | 72.22% | 29.41% | 13.89% | 2.94% |

Zeroing or permuting the head's auxiliary relative positions does not consistently
reduce quality. Frozen contextual states still retain original order during these
diagnostics, so this is not a complete encoder-order ablation. There is no claim
of an established natural-language positional advantage.

## Actual retention and compute costs

Across all five development attempts and both seeds, the ledger retains **96
candidate artifacts plus 10 selected copies**, **67,200 optimizer steps**, and
**8,371,200 example updates**. Candidate plus selected model files total
**55,057,512 B**; saved feature caches total **634,795,232 B**; corpus files total
**11,331,112 B**. These are accumulated research costs, not minimal serving state.
Recorded attempt elapsed times sum to **214.5972 seconds**. There are **24,328
native encoder calls**, plus 6 separately recorded encoder-parity verification
calls. Unit-test fitting is outside this research-candidate ledger.

The last round takes 87.27 seconds for both seeds. Per seed it trains 14 candidates
with 10,800 total optimizer steps and 1,267,200 example updates. Its retained
cache files occupy **122,077,808 B**, including explicit float16 token states and
int64 offsets. The selected router, feature metadata and pointer occupy
**202,762 B**, plus the shared **23,516,451 B** frozen encoder. The corpus/cache
is not deployed. These byte totals do not measure full process RSS or transient
float64 activation peaks.

One native token output produces both the original dense feature and the new token
feature. A real pinned-encoder parity check compares 1,152 dense values bit for bit;
the previous twelve candidates' complete artifact files match across the fourth
and fifth rounds in **72/72 file comparisons**. Token caches are independent per
seed; no cross-seed reuse is claimed. Maximum observed training length is 42
tokens, below the declared 128-token limit; overflow is explicitly rejected.

## Evidence and final implementation state

- `analyses/routing-development-findings.json` contains the five-attempt ledger,
  candidate diagnostics and 72 file identities.
- `validation/routing-*-development-audit.json` contains raw/calibrated confusion,
  confidence distributions, annotation checks and verified seal identities.
- `validation/token-encoder-parity.json` records the real encoder compatibility
  and overflow check.
- `results/development/routing-*/` retains every failed attempt and its exact
  executed routing-module snapshot.

After the fifth run, deployment helpers were moved without algorithm changes from
`routing_study.py` to `routing_bundle.py`. All seven mechanism tests pass after
this move. The older execution snapshots remain unchanged; root's integrated
development run will bind the final organization to its own exact frozen source.
No v1/v2/v3 file was modified by this implementation. No further model search,
threshold tuning or hidden-language inspection is authorized by this document.

An evidence-only timing correction after the fifth run makes final
`all_head_seconds` include auxiliary positional diagnostics, and reports normal,
diagnostic and total head-query evaluations separately. The older fifth-run
`all_head_seconds` field covers normal candidate heads only; its complete
`elapsed_seconds` already includes the diagnostics. Historical receipts remain
unchanged. This correction does not alter features, weights, decisions or selection.
