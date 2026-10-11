# Measured failed views and source-fold-selected joint backoff

This continuation of #1550 starts from
`7646735fb30f580798211ee6dd2a2f3c760cfa6b`. The single existing study entrypoint,
all historical profiles, native owners and acceptance floors are retained.
No fitted-law optimum is relabelled as a real-outcome or general FBSDE optimum.

## Actual parent failure, not a missing model or a waived budget

The parent semantic-acquisition mmBERT job 114513298964 in run 38154072408 failed
on `per-view CPU budget exceeded`. Original artifact 11708008731 was downloaded;
archive SHA256 is `4523f473913b4bc882ec8a7b667914cf85e0b7186b6e07dd79ffac73ff6eae5a`.
It contains partial validation records but no completed test result. Successful
view medians in those records are about 30 ms; the failed view's actual duration
was not retained. Its cause cannot be identified as warmup, contention or model
cost from that missing record. A single unchanged job retry was requested; a
retry is not removal of the original failure or evidence of budget stability.

Every new requested view now records text preparation, Encoder, Head and receipt
CPU, a hash chain and the unchanged 100,000,000 ns ceiling. Tensor hashing and probability materialization
are inside the view measurement. Journal hashing, serialization and I/O are
outside that ceiling but inside request/run envelopes. An overrun is fsynced before throwing, never
returned to the policy as an accepted observation. No timing is clamped. These
are post-call checks, not preemption. Failed trials retain completed preparation,
small Head, normalizer, run failure and partial request records. They cannot
produce a completed science report. The journal is not native WAL or attestation.

## Coherent joint shrinkage, selected before evaluation

The old `uniform_joint_v1` keeps the identical +.01 atomic count model. Optional
`joint_backoff_cv_v2` retains raw counts n(y,a,b,c) and compares that legacy model
with four anchored priors of total mass tau in {8,32,128,512}:

    count_tau(y,a,b,c) = n(y,a,b,c) + tau P_hat(c) P_hat(y|c) P_hat(a,b|c).

Here c is the full-text Head symbol. Each marginal uses +.5 categorical smoothing
on its fitting fold. All tables are positive; total prior mass equals tau. The
anchor expresses a reviewable regularization preference for the full view, not
an established sufficient-state theorem. Empirical joint interactions remain;
view likelihoods are not multiplied as independent label evidence.

Four folds use the first 16 hex digits of each original text hash modulo four.
Duplicate source hashes reject. Hyperparameters minimize held-out label log loss,
equally averaged over the four allowed history subsets containing the initial
view. The same row's dependent histories remain in one fold. Only the 320 kernel
rows participate. Selection, validation and test labels do not enter this API.
The fixed grid and objective were chosen after the historical V1 result had been
seen: ensuing test reuse is exploratory, NOT fresh confirmation.

The winning table is refit on all kernel rows and bound to its complete selection
record. The existing neutral/risk BSDE and compiled controls consume this same
law. Original controls remain; V2 additionally runs `full_symbol`, which reads
full text and directly returns its Head argmax without posterior remapping.
It is a research comparator, not the currently deployed production no-change.

After scoring, report raw source support and label log loss/Brier by zero, 1--4,
and >=5 matching training observations. Pseudo-counts NEVER count as independent
support. These are descriptive diagnostics, not calibrated uncertainty bounds.

## Actual original-label lexical result

Same 480/320/80/80/240 source partition, shared Head/96-step optimizer, views,
fees and random seed. Cross-validation selected anchor:128. Conditional log loss
was .82415155 for legacy versus .68805720 for the selected prior. The final
240-case lexical test run (not a new mmBERT forward) gave:

| Policy/law | Correct / answered | External score minus fees | Test view calls |
| --- | ---: | ---: | ---: |
| Legacy neutral BSDE | 189 / 193 | .72283333 | 601 |
| Supported neutral / compiled | 227 / 240 | .84983333 | 502 |
| Supported myopic | 227 / 240 | .84983333 | 502 |
| Supported fixed full view | 226 / 239 | .84750000 | 480 |
| Direct full Head symbol | 227 / 240 | .85166667 | 480 |
| Supported risk NDU | 226 / 239 | .84541667 | 505 |

The supported policy improves substantially over its historical fitted-law
counterpart but still does NOT beat the new cheaper full-symbol control. Equality
with myopic outcomes supplies no incremental multi-step benefit. No test label
retuning, scorer change, future-volume cost amortization or threshold relaxation
was performed. Eighteen selected neutral terminal contexts have zero raw fitting
support; their mean log loss is 1.74378 versus .107985 in the >=5 support bin.
Sparse-law uncertainty remains substantive despite a good aggregate score.

The legacy path was rerun and reproduced its original nine arms' decisions and
view symbols. All actual attempts and both input/output inventories are retained.
Physical CPU, prior mass and modeled utility fees use different units. Each
backend/kernel profile is a separate workflow job; no public hashing result is
silently substituted for mmBERT. Extra CV preparation is charged once and remains
part of total experiment cost. Per-arm full lifecycle allocation is still false.

## Verification

An independent dense arithmetic module reconstructs all CV folds, losses, winner
and final counts without importing the policy, fitting implementation or model.
The existing original-file audit verifies each returned observation against its
attempt chain, prohibits missing/duplicate/over-budget attempts, and reconstructs
raw-support diagnostics and full-symbol decisions. It does not authenticate
source independence, execution or observation truth.

Final local checks: 257 model-free and 47 actual Torch tests, no skips. Clock-
controlled boundary tests are not performance benchmarks; Tensor fixtures are
not pretrained evidence. The original 100 ms admission remains unchanged.
Full repository/native builds and exact final-head hosted outcomes are separate.

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile semantic_acquisition_v1 --backend hashing_reference_v1 \
  --kernel-profile joint_backoff_cv_v2 --publisher-root /original/publisher \
  --output /new/support-study
```

Use `--backend mmbert --model-dir /model/cache` for the actual pretrained path.
Keep Draft. Continuous nonlinear semantic FBSDE integration, unseen future tasks,
production no-change, risk/retention and native final-use/recovery remain open.
