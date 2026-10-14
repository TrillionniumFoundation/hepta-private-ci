# E1–E6 final Stem selection: research-only paired screen

This is a **non-authorizing** downstream screener for Hepta Shared Stem/Cell
experiments. It does not load a model, train a Head, verify a signature, execute
physical Cells, certify a target host, or select a production artifact. It
expects independently produced and sealed observations. **No complete qualifying
real-data bundle was supplied or produced in this delivery.**

## Source and experiment producers

Feed real outputs from `execution.py`, `head_batch.py`, `paired_frontier.py`,
`qualification/neuron-stem/statistical_gate.py`, multimodal/temporal ablations
and the production owner's target-host scale traces. Converting those existing
receipts to a bundle requires an independent join on case/input/source/scope;
this component intentionally cannot supply or fake missing observations.

- E1 must include **mmBERT-small / Granite 97M R2 / ModernBERT-base / mmBERT-base**.
- E2 must include 2,048 / 8,192 / 16,384 / 65,536 / 262,144 Head budgets.
- E3 must include joint and shared-feature plus Cell-state fusion.
- E4 must include V1 / V2 / V3 / diagonal SSM / low-rank minGRU.
- E5 must include text Stem + Organ vs EmbeddingGemma 2 on identical tasks.
- E6 must include actual 64 / 256 / 1,024 / 4,096 Cell host counter traces.

The `coverage` digests are references to externally audited results, not an
execution claim. Every preregistered arm must include exactly the same
future_1/future_2 cases, input SHA, source group, event timestamp and old-task
membership; failed/abstained cases remain in the denominator. The Stem is frozen,
model revision is a full 40-hex commit, and tokenizer/Head/Stem are SHA-bound.
`baseline=no_change` and all arms share registered training steps and seed.
Outcomes must occur strictly after the declared freeze and future_2 after
future_1, with 30+ reported source groups in each window by default.

## Statistic and decision

For each candidate, form within-source-group mean differences against no-change
on **external** future net decision utility. Resample reported source groups with
replacement separately within future_1 and future_2. Each window must have a
positive one-sided LCB at alpha=0.05/(2 × number of preregistered candidates),
and the candidate is ranked by its worse-window LCB. Worst-window old-task
negative transfer also must pass. It is a conservative **exploratory cluster bootstrap**, not a
finite-sample proof: independent source identities are not authenticated by this
reader. The screen also rejects negative transfer, Brier/ECE/OOD/old-task
regression and any breached p99/RSS/GPU/recovery hard threshold.

If every claimed E1–E6 experiment is complete, the required candidate families
are observed, source-group counts pass, paired LCB is positive, and quality and
physical resource caps pass, the screener may return
`provisional_research_leader`. This is **not** a model winner because the
following remain hardcoded `false`: production accepted, model selection
authority, preregistration authenticity, independent groups, observer signature,
real model execution verification and target-host attestation. A separate
independent Evaluator, Selector and effectful Executor must remain distinct.

## Commands

```
python3 -m unittest -v experiments.shared_stem_cell.test_final_selection_gate
python3 -m experiments.shared_stem_cell.final_selection_gate \
  --bundle /approved/externally-sealed-e1-e6.json \
  --output /scratch/e1-e6-shadow-screen.json
```

`test_final_selection_gate.bundle()` is a **synthetic fixture only**; the
published smoke input uses `origin=fixture`. Even deliberately relabeling it
`measured` does not authenticate its rows. Do not record fixture-derived positive
statistics as model or production results.

Run from repository root. Missing metrics do not become zeros, missing arms do
not become competitors, and this CLI cannot access production routes.

## Real pretrained physical-study preflight (non-authorizing)

The separately executed `preflight_review.py` consumes one existing
`execution.py` producer's canonical manifest, original dataset, pre-sealed
predictions and producer report. It **does not** turn an AG News publisher
holdout into an artificial `future_1/future_2` window and **does not** make
the synthetic E1–E6 coverage map appear complete.

The review independently recomputes the four actual Head arms' class
predictions, Brier, same-initialization frozen-Head comparisons, exact source
input identities and case census; it verifies the producer report and data
file hashes and rejects rehashed contradictory scores. This verifies internal
prediction arithmetic and sample pairing, **not** physical model provenance,
external outcome authenticity, source-group independence, the native Worker,
signed NDU or production no-change. Every receipt therefore retains
`ready_for_e1_e6_selection=false` and `production_accepted=false`.

```sh
REPORT_SHA=$(sha256sum /real-study/execution/report.json | cut -d' ' -f1)
python3 -m experiments.shared_stem_cell.preflight_review \
  --manifest /real-study/manifest.json \
  --producer /real-study/execution \
  --report-sha256 "$REPORT_SHA" \
  --output /new-evidence/preflight.json
python3 -m unittest -v experiments.shared_stem_cell.test_preflight_review
```

The dedicated public-pretrained GitHub lane runs this check on actually
executed, pinned public weights and original publisher records, retaining
the report as a separate CI artifact. No signed future observations or
real 64–4,096 Cell native owner measurements are inferred or filled in.

## Independent frozen-feature -> Head-weight -> prediction replay

After a real pinned public/pretrained \`execution.py\` run and the previous
\`preflight_review.py\` score census, \`physical_head_replay.py\` performs a
separate numerical replay with NumPy and safetensors. It never imports Torch,
Transformers, \`execution.Head\`, an optimizer, the original Head forward path or
the original Head fitter.

The replay reopens the original scoped frozen f32 feature matrix and **all**
learned/frozen Cell Head safetensors. It checks source-row order, feature/Head
manifest and actual tensor SHA256, parameter count/bytes, weights, dataset and
Stem binding, then recomputes the explicit Linear, Gated, Low-rank and
Sparse-expert equations, normalized probabilities and choice identity. It
rejects incomplete checkpoints, changed values even after superficial hashes
are repaired, missing Cell/arm predictions and training-step mismatches.

The public AG News smoke expects two Cells, four Head architectures, both
learned and frozen roles: 16 physical Head checkpoints and 256 predicted
probability vectors (32 holdout × four architectures × two roles). Tolerance
for NumPy-vs-Torch floating arithmetic is 2e-5 absolute + 2e-4 relative.
CI retains the full source-bound JSON replay receipt with maximum discrepancy;
it never uploads the pretrained Encoder weight files.

\`\`\`sh
REPORT_SHA=$(sha256sum /real-study/execution/report.json | cut -d' ' -f1)
python3 -m experiments.shared_stem_cell.physical_head_replay \
  --manifest /real-study/manifest.json \
  --producer /real-study/execution \
  --report-sha256 "$REPORT_SHA" \
  --output /new-evidence/physical-replay.json
python3 -m unittest -v experiments.shared_stem_cell.test_physical_head_replay
\`\`\`

A clean numerical replay is **not** independent provenance of actual Encoder
execution, signatory identity, source-family independence, external objective/NDU
outcomes, a production no-change baseline or native 4,096-Cell capacity.
It provides a stronger model-data-plane consistency check for E1/E2, not E1–E6
completion and never production authority.

## E1 public two-Encoder execution pilot: frozen mmBERT-small vs ModernBERT-base

The public-pretrained execution lane now first executes the existing pinned
mmBERT-small/AG News program and independent 16-checkpoint replay. It then
runs **another genuine pretrained Encoder** in a separate Python invocation:
\`answerdotai/ModernBERT-base\` at the exact preselected model revision
\`fa3113d09d6dacfe5528708803dd92a62240237a\` (Apache-2.0).
Its publisher safetensors must be present, SHA-verified and materialized
without conversion, remote code or hidden synthetic weights. Failure is a
failed hosted job, not a fabricated fallback.

\`public_encoder_pair.py\` reuses the immutable baseline dataset bytes
verbatim (64 train, 32 calibration, 32 publisher holdout), with the same
two logical Cell assignments, 20 training steps, seed, batch settings,
Head architectures and controls; only the Encoder manifest is replaced.
The two Encoders have different hidden sizes, so **identical architecture does
not mean equal actual Head parameter count**. Both are constrained to
a **16,384 trainable parameter maximum per Cell**; physical parameter
counts and resident memory must be disclosed. Initial Encoder download
and separate-process loading are not treated as steady-state latency.

\`public_encoder_pair_review.py\` independently rechecks both published
preflight reports and all 16 learned/frozen saved Head checkpoint predictions,
rejects changed rows/train knobs/model revisions/missing prediction pairs,
and reports exactly matched correctness gains/losses/ties and Brier on
the publisher's 32 original holdout cases. Neither a synthetic fixture nor
any unsupported Encoder is silently counted as another observed arm.

This is **a two-Encoder feasibility comparison**, not the preregistered
full E1 four-Encoder evaluation, five-budget E2 curve, production no-change
baseline, Laya 421M comparator, real future NDU or 64–4096 physical Cell
scaling acceptance. No statistical independence is proved by AG News row IDs.
A clean result is retained as retrospective research only, with
\`four_encoder_e1_completed=false\`,
\`five_head_budgets_e2_completed=false\`,
\`future_ndu_utility_evaluated=false\` and
\`production_accepted=false\`.

Run the actual hosted \`public-pretrained-smoke\` lane; exact-source CI stores
the ModernBERT publisher hashes, bounded dataset, Head weights, sealed
predictions and paired-review receipt, **never any downloaded base-model
weights**. A failed provision or execution retains the job log and does
not synthesize a paired review.

## E2 physical frozen-feature budget sweep (research only)

\`e2_budget_sweep.py\` takes the PREEXISTING physical mmBERT-small public
\`execution.py\` report and the immutable scoped \`frozen-features\` safetensors.
It first replays all existing 16 pretrained-study frozen/learned Head
checkpoints using the existing independent NumPy arithmetic check. It does
not load an Encoder, download new data or regenerate feature rows.

The experiment preregisters five maximum **per-Cell trainable parameter**
ceilings: 2,048 / 8,192 / 16,384 / 65,536 / 262,144. It trains a
**new factorized two-layer tanh Head with no full dense base**, so even
a 768-dimensional input would permit a 2K-parameter Head. This family
is deliberately distinct from the earlier linear/Gated/post-Encoder
Low-rank/sparse-expert controls. For 384d and four target classes,
the exact formula is \`r*(384+4+1)+4\`; ranks are derived from the
precommitted ceiling, never selected on held-out results. Actual parameter
counts are recorded separately from ceilings.

The physical 384d AG News pilot uses the same source-authorized 64 train /
32 calibration / 32 retrospective holdout cases, 2 logical Cells,
20 optimizer steps, batch 16, seeds 11/23/47 and an identical
per-Cell minibatch index stream across all seeds and budgets. Each of
the 5 × 3 × 2 trials saves both original frozen and learned weights
(create-only safetensors), sealed probabilities, physical train work and
parameter counts. Held-out labels are NOT an argument to the optimizer.

\`e2_budget_review.py\` never imports Torch or the training module.
It independently reloads and checks all 60 real safetensors checkpoints
and recomputes 1,920 probability vectors on the original frozen features
(including calibration and publisher holdout), enforcing paired case/Scope,
fixed shape, exact train-step and minibatch accounting, weights and
prediction parity. It scores the 32 retrospective publisher holdout
cases separately. The original pretrained study's trained linear Head
is a descriptive strong control, **not** the production no-change baseline.
\`e2_budget_integrity.py\` exercises physical artifact tampering and
failure/abstention paths, including rehashed altered weights, removed
predictions, redirected checkpoint paths and invalid authority claims.

A successful execution can measure **learning within this frozen
Encoder/Head family on one retrospective data distribution only**.
It cannot establish an optimal universal Head, model capacity superiority,
statistical independence of data source families, a causal future NDU
gain, negative-transfer safety, Q24/native deployment, Laya comparison
or actual target-host 4,096-Cell performance. Outputs explicitly retain
\`e2_full_selection_qualified=false\` and \`production_accepted=false\`.
All historical producer records remain byte-for-byte unchanged.

Reproduction with a preexisting physical source:
\`\`\`sh
REPORT_SHA=$(sha256sum /real-study/execution/report.json | cut -d' ' -f1)
python3 -m experiments.shared_stem_cell.e2_budget_sweep \
  --manifest /real-study/manifest.json --producer /real-study/execution \
  --report-sha256 "$REPORT_SHA" --output /fresh/e2-budget
python3 -m experiments.shared_stem_cell.e2_budget_review \
  --manifest /real-study/manifest.json --producer /real-study/execution \
  --report-sha256 "$REPORT_SHA" --sweep /fresh/e2-budget \
  --output /fresh/e2-review.json
python3 -m experiments.shared_stem_cell.e2_budget_integrity \
  --manifest /real-study/manifest.json --producer /real-study/execution \
  --report-sha256 "$REPORT_SHA" --sweep /fresh/e2-budget \
  --output /fresh/e2-integrity.json
\`\`\`
