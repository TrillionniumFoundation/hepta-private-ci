# Real public-learning outcomes and encoding-inclusive comparison

Remote parent: `b7c09fb20180fd927820f84a4501bfb472e472f9` (#1861).
Tested code: `b921ab8bdc02a3b8273dc6adfa30c406c460ec29`.
Branch: `research/shared-stem-public-quality-cost-20261014`, PR #1873.
No main merge, model selection, deployment or history rewrite.

## A real earlier public-learning run, not a new capability claim

The original public experiment completed in workflow 38525101021, job
115734312489, at head 2892b82ca5c4da66c2d16ca2e861c8e9df89886c and actual checkout
571224a4a4571d479aac29b4bad2fe90f439d3bf. Artifact 11878438336 has SHA256
37b02f390f0f7d55e5bd8cea3247b72cf389cd97d920a94918f077e4751a6630.
The downloaded original ZIP, inner/outer seals, per-arm records and selected
sample identities were checked and retained. Original weights and label vectors
are intentionally absent from hosted artifacts: their byte identities are recorded,
but this retrospective analysis cannot independently reload the weights, rescore
raw labels or reconstruct per-row paired correctness. It does not pretend otherwise.

One frozen ModernBERT-base checkpoint (149,655,232 retained parameters) served
64 training and 64 held-out news rows, balanced at 16 rows/class. Each arm used
791,552 trainable bank parameters, seed 7347 and 32 updates. Dense16 and sparse16
initial tensor digests are identical; routing differs. The observed results are:

| Arm | Initial correct / 64 | Trained correct / 64 | World / Sports / Business / Science-Tech correct (each /16) | Brier |
|---|---:|---:|---|---:|
| dense16 | 14 | 39 | 8 / 16 / 5 / 10 | 0.5163881104 |
| sparse16 | 15 | 38 | 8 / 16 / 11 / 3 | 0.5159358023 |
| direct32 | 16 | 38 | 9 / 16 / 10 / 3 | 0.5469502636 |

This is actual public-pretrained feature extraction plus learned Heads, not the
older synthetic Encoder fixture. It remains a one-seed, 64-row, fixed-update
experiment with unequal training work. One fewer correct answer is not proof of
equivalent quality; category gains can conceal losses. No parameter or threshold
was changed in response to these results, and no winner or noninferiority claim
is issued. Pretraining contamination, independent observation, temporal retention
and broader generalization are not established. This run contains no family split.

## The measured bottleneck changes the interpretation of local savings

Shared training encoding used 1,450,761,357,642 formula operations; held-out
encoding used 1,437,031,931,902. Head/gate training used 2,067,124,032 (dense16),
314,369,576 (sparse16), and 211,935,472 (direct32). All are the same explicit V3
CPU FP32 ATen formula unit, not measured hardware instructions or elapsed time.

Sparse16 reduces bank training work by 84.7919% relative to dense16. Charging
training encoding in full reduces the standalone training subtotal by only
0.120644%. Including both encoding passes, initialization/training, the extra
initial-control predictions and final inference reduces that observed trial
subtotal by 0.066703%. Dense16's encoding fraction in that subtotal is 99.9214%.
This supports investigating Encoder efficiency and valid reuse, not a claim that
all workloads or long-running services have this same bottleneck. Many more Head
updates, reusable inputs or smaller Encoders can change the balance and require
measurement. The three-arm campaign physically paid encoding once; a standalone
arm cannot divide its required encoding by three to appear cheaper.

## Implementation integrated into the existing scorer

`public_comparison.py` is called by `shared_learning_probe.score_sealed` after
existing study, seal, budget and topology validation. There is no second trainer,
new experiment namespace, hidden retry or altered arithmetic definition. It:

- validates phase records and unit/policy compatibility, retaining failed prefixes
  and missing stages rather than successful-only cost averages;
- separates bank-only, encoding-inclusive training, final prediction, and the
  complete *observed formula* trial subtotal; family migration belongs to training;
- records all pairwise recovered/lost answers and each class delta, as well as
  before/after changes, using the one shared scorer label vector;
- refuses false complete totals, unexpected omitted phases, duplicate identities,
  reordered/missing arms, failed-success predictions and incompatible cost units.

This new paired report is available on future scoring calls with actual labels.
Historical raw labels are not inferred from class totals. Summaries expose no raw
news or labels and do not grant statistical equivalence, source independence or
production authority. Failed candidates remain unavailable, not zero-quality
models; their known costs and expected request counts still remain. No confidence
interval or significance test is manufactured after seeing these results.

## Verification and reproduction

The exact predecessor passed 473 planned/executed tests. Final code passed 487
planned/executed distinct tests twice, exit code 0, with zero failures/errors/skips.
Fourteen new tests include actual ordinary/family PyTorch training, sealed scoring,
shared-work accounting, paired class tradeoffs, artifact immutability and rejected
incomplete costs. An initial test fixture shadowed unittest.run; its failure log
is retained and the fixture was renamed. A transcription mismatch in an uploaded
blob was caught by hash comparison before any commit; only exact tested blobs
were committed. The three source hashes match remote objects. Compileall and
whitespace checks passed; training functions and workflow files are unchanged.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --output /new/nonexisting/tests.json
python evidence/reproduce_public_result.py --source source \
  --artifact evidence/hosted/public-news-fixed-steps-raw-20261014.zip \
  --output /new/nonexisting/public-result.json
```

The source package includes the original hosted ZIP, extracted observations,
reproduction script, baseline/final/failure logs, detailed result and hashes.
`PUBLIC_QUALITY_COST_OBSERVATION_20261014.json` is a compact, explicitly retrospective
projection; the original scores and predictions are never rewritten. New-code
hosted success is not inherited from that earlier model run. Local Transformers
is absent, and no new local pretrained run was attempted or counted in 487.
This is a CPU source slice; codex-rs/just fmt and full Rust/native/GPU tests were
not available. Full service/energy costs, fixed-budget/family task results,
independent replication, NDU matrix activation, multimodal generation and
1024/4096-Cell qualification remain separate acceptance work.
