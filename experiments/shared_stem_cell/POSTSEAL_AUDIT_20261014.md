# Sealed public Stem + multimodal research: exact historical audit (2026-10-14)

**Research-only.** These are read-only, historical observations from completed Actions run
[38514532798](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38514532798),
at model-generating source commit \`b43cefc80e1855db7581b58ab527af44d15c0d50\`.
They do **not** describe model generation at this document's HEAD, independent
future-world task evidence, or an authorized production model. No model was
trained or selected by the later post-seal replay.

## Pinned evidence

- Public pretrained archive: artifact **11872205556**, ZIP SHA-256
  \`05b6ec4b33a7563ea368f7d5be212ad1dbf1220bbccb9195ac900ac5adde34a6\`.
  Inspect \`hepta-fresh-confirmation/candidate-lock.json\`, \`cohort.json\`,
  \`predictions.json\`, \`confirmation.json\`, \`report.json\`.
- Public multimodal archive: artifact **11871262545**, ZIP SHA-256
  \`777d4250ae174eb4ef6c645d53b25aca7deddb388df7c73d3d21f1a4ecf993eb\`.
- Both archives were downloaded and CRC-checked; their digest pins identify
  **exact received ZIP bytes**, not independent authorship or semantic correctness.
- \`postseal_historical_audit.py\` independently recalculates raw probability
  scores and per-Cell confirmation gains/losses; it is intentionally limited
  to this **negative** registered study and refuses a re-labeled positive gate.
  Unit regressions do not substitute for the original archive replay. A distinct
  read-only CI job downloads the preexisting archive and re-verifies its SHA.

## Two genuinely separate 512-example phases

Fixed candidate before confirmation: **shared supervised Head plus per-Cell
linear ridge residual**, \`residual_corrected\`; comparator: existing two-Cell
\`bank\`. Confirmation uses exactly 512 newly acquired original-content
examples, 256 per Cell. A separate 512-example set (256 per Cell) is reserved
for evaluation. Both sets exclude exact/normalized text from the earlier
producer cohort; that does **not** establish independent source families.

| Fixed frozen arm | Confirmation correct / 512 | Evaluation correct / 512 | Eval Cell 0 / 256 | Eval Cell 1 / 256 |
| --- | ---: | ---: | ---: | ---: |
| bank | 295 | 313 | 118 | 195 |
| shared | 342 | 356 | 176 | 180 |
| linear_distilled | 296 | 311 | 117 | 194 |
| residual_corrected | 310 | 332 | 122 | 210 |

The actual **pre-registered** candidate's confirmation paired changes relative
to the bank: Cell 0 gained 7 and lost 3; Cell 1 gained 18 and lost 7.
Its one-sided per-Cell nonregression support did **not** pass for either Cell,
under the declared hypothesis/threshold. The confirmation \`chosen\` is
**bank**, not a deployment approval. \`assumptions_verified=false\`,
\`retention_certified=false\`, \`production_accepted=false\`, and
\`independent_source_families_verified=false\`.

The \`shared\` arm has the highest aggregate evaluation count, but loses **15
correct cases in Cell 1** (180 vs 195 for the bank). More importantly, choosing
\`shared\` based on the supposedly final evaluation data would violate the
frozen-candidate protocol. A higher aggregate score is not permission to switch
models or suppress negative transfer.

Development (separate reused 32-case holdout, **not** either fresh phase):
gated 22/32, linear 18/32, low-rank 21/32, sparse expert 13/32.

### Physically inspected Head tensors (not full resident model memory)

The original public ZIP retains real safetensors weights. A read-only
tensor count on the seven *actually used* components confirms these
historical parameter allocations in **float32**:

| Frozen Head deployment alternative | Physical Head parameters | Head tensor bytes | Relative to bank |
| --- | ---: | ---: | ---: |
| Original two gated Cell Heads (bank) | 12,384 | 49,536 | reference |
| One shared supervised gated Head | 6,224 | 24,896 | 49.74% fewer parameters |
| Shared supervised Head + two linear residuals | 9,304 | 37,216 | 24.87% fewer parameters |
| Two independent linear ridge Heads | 3,080 | 12,320 | 75.13% fewer parameters |

These are **Head tensor counts only**. They exclude the shared Encoder,
KV/activation/cache, training optimizer, materialization and all producer/
migration/evaluation costs. Two-Head corrected inference actually executes
one shared Head plus its Cell-specific residual, so parameter savings do
not imply fewer active Head forwards or better total-device latency. The
historical script's separate sampled running-process RSS endpoints are not
a deployment peak-memory or energy measurement.

## What was physically measured

Shared mmBERT-small 128-record source batch used 16 physical Encoder forwards.
On a *repeated-input* eight-example replay, 32 requests with a bounded cache
required one physical Encoder forward and recorded 24 reuses, versus four
forwards in the no-cache batched arm. This demonstrates one workload's
byte-/shape-compatible feature reuse, **not** a measured 421M-vs-small-Stem
421M replicated cost frontier or a 4096-Cell service benchmark.

Real CLIP/ScienceQA four-choice initial holdout (32) had image 9/32 and
image+text 8/32 correct. Later non-equivalent calibrated 64-case views
measured image+text 21/64 and a chosen strategy 22/64. The separate
64-case four-choice comparison included an 18/64 visual-prior control.
These views are not independent confirmatory evidence and should not be
pooled as one same-sample controlled win. No stable cross-modal advantage
has been established.

Real physical model execution is established for its limited public profiles;
complete total FLOPs/energy and independently verified task support are **not**
established. Null measurements remain null. Research mechanics, artifact
integrity, Model/Reader capacity and future production acceptance are distinct
questions.

## Reproduction without rewriting the source archive

\`\`\`bash
python3 -m unittest -v experiments.shared_stem_cell.test_postseal_historical_audit
python3 -m experiments.shared_stem_cell.postseal_historical_audit \
  --root /path/to/hepta-public-pretrained-38514532798.zip \
  --zip-sha256 05b6ec4b33a7563ea368f7d5be212ad1dbf1220bbccb9195ac900ac5adde34a6 \
  --output /new/readonly-negative-replay.json
\`\`\`

The local replay was run against the exact first ZIP and recomputed all
1,024 rows and 4 arms. The executable CI replay remains a separate check
on its exact HEAD; do not report a queued job as passed.

### Next scientific gate

Keep the fixed bank and \`shared\` variants as eligible *candidates only*;
preregister different-source, genuinely forward-window cohorts with independently
scored old/new Cell distributions and a cost-matched training/inference lifecycle.
Require each affected Cell's retention floor, negative-transfer analysis,
complete resource observations and external authority before replacing \`bank\`.
Prior reused AG News and ScienceQA records cannot be their own independent confirmation.
