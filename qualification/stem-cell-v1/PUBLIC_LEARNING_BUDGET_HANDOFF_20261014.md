# Public learning publication and measured-budget training

Remote parent: `805ffeae04db9c0d7d3386cb2a2644dd29f39b07` (#1804).
Recovered code: `2892b82ca5c4da66c2d16ca2e861c8e9df89886c`.
Final tested code: `43fb3b11965a29b18210295bc0c79bce2f074298`.
PR #1833, branch `research/shared-stem-public-learning-budget-20261014`.
No main merge, force rewrite, native model installation or production selection.

## Publication of the previously local stage

The delivered public-task-learning archive has SHA256
`b1f200d6cc0b072faeae3db8e55bef0cb2ac356222d8b8847b4df2f7683f9a24`.
Its manifest was verified before extraction. Six executable/test/workflow files
were uploaded byte-for-byte and rerun: 441 planned and executed tests, exit 0.
The original three historical handoff/receipt/public-observation files remain
unchanged in the delivery package's historical area, not rewritten as if the
previous session had published them. This handoff records the subsequent push.

The recovered study pins public news file identities, selects a fixed balanced
64-training/64-test panel, uses one frozen Encoder feature set, and trains the
actual dense16/sparse16/direct32 CellBanks. It does not borrow 421M arm labels for
a roughly 149M model. Input overflow fails instead of truncating or resampling.
Raw news, features and model weights are not uploaded as hosted artifacts. The
corpus research-use restriction is not a production/material approval grant.

## What changes under the new optional budget schedule

`budgeted_learning.py` uses the existing CellBank, loss, clipping and AdamW
hyperparameters. When budget is nonbinding its updates reproduce the original
train_bank weights and losses exactly. V1 fixed-update behavior and study ID
remain compatible. V2 is explicitly `formula_budget_whole_updates_v1`; its active
limits are training_flops_budget and max_budget_steps. The retained train_steps
field is the legacy fixed-step setting, not the V2 update count. Actual steps and
examples are reported rather than inferred from that field.

Before an update, a conservative shape-derived upper bound must fit the remaining
budget. It includes all parameters for the AdamW/clipping envelope, even when only
some experts have gradients, and covers forward/backward linear products, GELU,
gate and loss work under the pinned eager FP32 formula profile. Batch size can
halve down to one based only on available budget, never a held-out outcome. There
is one persistent optimizer and one deterministic sampler, not optimizer resets
between steps. There is no dry-run profiling, dummy computation or retry loop.

The reservation is NOT the charged cost. The existing strict WorkLedger observes
actual dispatch during each admitted update and checks its phase cap. Actual work
exceeding the declared update bound fails the arm, as do unknown operators,
exceptions, nonfinite values or a budget that funded no complete parameter update.
No mid-update model is promoted by rolling back its visible parameters while
hiding consumed work. Normal stopping happens only between completed updates;
a step-count safety limit has its own disposition and may leave a large remainder.

This bound is for the named eager CPU FP32 CellBank/AdamW implementation, not an
arbitrary optimizer, hook, fused/compiled backend or precision. The tests check
actual dispatch over 18 geometry/batch combinations (two updates each), but they
are not a universal mathematical or hardware guarantee. The live cap and
post-step bound check remain active. Copies, indexing and Python control still
cost time/memory even where the formula convention assigns zero floating work.

## Fair comparison and accounting

The common per-arm train budget includes Head/gate initialization, validation and
optimizer work. Frozen Encoder encoding is recorded separately, paid once within
each three-arm campaign, and must be added back to each standalone comparison.
The fixed-step and fixed-budget campaigns independently encode their inputs and
pay those costs separately; sharing a downloaded checkpoint is not a free forward.
Initial untrained predictions, final inference, source checks, scoring and I/O
remain separate. Equal train formula work is not equal total service cost, energy,
latency or sample exposure. More cheap updates/examples are part of the fixed-cost
estimand, so it must not be described as a fixed-data-exposure ablation.

Every score report validates actual work against the frozen budget, complete step
records, reservations, remaining amount and stop reason. The one-percent matching
flag is computed from observed counts, not shared caps or reserved sums. Failed
arms remain in the complete arm inventory, and unknown cost remains null. There
is no gate declaring scientific superiority from matching compute alone.

## Actual local results

After the recovered 441-test baseline, final source passed 457 distinct planned/
executed tests twice, both exit 0, zero errors/failures/skips/expected failures.
The new 16 tests cover whole-update bounds, legacy numerical parity, invalid
shapes/precision, no affordable update, policy/cap mismatch, dishonest reservations,
real failures, data isolation, scoring integrity and fixed-budget integration.
Development logs preserve the test-name collision with unittest.run and fixture
allocation under a strict meter; both fixtures were corrected without weakening
the meter or admission checks. Complete raw logs and structured inventories are
retained. No downloaded weights were used in those 457 tests.

An extra actual PyTorch diagnostic uses four-dimensional synthetic one-hot
features and 864-parameter banks, not a pretrained Encoder:

| Topology | Complete updates | Examples seen | Actual train formula work | Remainder |
|---|---:|---:|---:|---:|
| dense16 | 50 | 197 | 1,954,973 | 45,027 |
| sparse16 | 193 | 772 | 1,951,506 | 48,494 |
| direct32 | 215 | 857 | 1,943,631 | 56,369 |

All use a 2,000,000 budget and finish without an unknown operator or sticky stop.
The largest observed cost difference is about 0.58%; utilization is about
97.18%-97.75%. The unused budget is retained, not padded. This establishes a
mechanism-level compute comparison only; the simple task scores are not evidence
of real model generalization, better neural scaling, or independent learning gain.

## Hosted execution and reproduction

The original public-learning workflow is preserved and a second independent
fixed-budget study is added, using 5e9 training formula work per arm and at most
4096 complete updates. It reuses the pinned downloaded model and news material,
not the first study's trained Heads. A real stock-HF budget-training check is
required separately. Hosted outcomes must be read against their exact head and
checkout; this local receipt does not inherit a prior job's success. At evidence
preparation no new public-task learning result had been obtained.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --output /new/nonexisting/tests.json
python qualification/stem-cell-v1/shared_learning_probe.py \
  --snapshot /reviewed/local/snapshot --news-dir /pinned/local/news \
  --training-flops-budget 5000000000 --max-budget-steps 4096 \
  --output /new/nonexisting/budget-learning
```

The local installed-HF attempt failed during import because Transformers is
absent. None of its six real Encoder checks is counted in the 457. The working
copy is a CPU source slice, not a full codex-rs checkout; the requested fmt attempt
failed because that directory is absent. No Rust/full-repository/native/GPU,
independent public-task benefit, complete system cost, energy, production approval,
matrix-NDU activation, multimodal generation or 1024/4096-Cell claim is made.
