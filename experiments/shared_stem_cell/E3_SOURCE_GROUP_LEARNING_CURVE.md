# E3 — Nested source-group sample efficiency (strict research, DENY_ALL)

**Parent:** E2 reviewed-forecast custody on Draft PR #2314 at exact commit
`72c2316348b7537921ab5e3ef478c46be27a895e`. Original P0 V12 model/source
at `b3b3712828cb5814e1a87d1e69a030ec947c43c1`, official experiment run
`38686023757` (must reach `completed/success` at that exact SHA before any model job runs).

## Reason

P0 has 12 original TRAIN, four CAL, eight TEST independent source passages.
Multiple question-answer rows in a passage are correlated. E1/E2 match 4,145
Head parameters and 40 SGD updates but do not measure sample efficiency.
This additive E3 experiment measures **4, 8, 12 TRAIN source passages**, not
4/8/12 individual answer rows. Source ordering uses a **fixed domain-separated SHA256 of each original
source-group digest only**. The original `panel_id` hashes the complete
FIT including original TRAIN labels, so it is deliberately NOT used as a salt.
Group ordering is invariant to TRAIN label changes and panel digest changes. Original
CAL and TEST source groups never enter TRAIN. If a nested budget has only one
class, its cells are marked **infeasible**, not assigned zero score or trained
against fabricated labels.

## Physical and numerical invariants

- Three existing P0 compact models: Granite97, mmBERT-small, EmbeddingGemma 2
  text; **no registered ModernBERT model** in this frozen source lineage.
- Same actual original pretrained E1 256/384D FP32 feature bank, original fixed
  128D projection, exact original seed-41/47/53 frozen Head weights. Each
  eligible budget uses actual Torch SGD for 40 full-batch steps, learning rate
  0.1, two architectures (`additive`, `gated`), 4,145 params each.
- Original CAL-only temperature choices, original blind probabilities.
  **The 12-source budget must reproduce the actual original E1 trained tensors
  within 1e-6, otherwise the experiment fails.**
- E3 creates a *new physical projection bank*. This extra projection costs
  actual CPU time, one full additional matrix multiply and FP32 cache bytes;
  it is recorded, not disguised as free shared compute. No additional Encoder
  load or forward is claimed **within this E3 sidecar**. The CI job ALSO
  physically re-trains E1 on original inputs first; that duplicated E1 cost
  is outside the E3 sidecar and must be charged in any full TCO study.
- The E3 producer cannot read held human labels; all raw new Head weights
  are saved only locally in an fsynced safetensors archive, with a create-only
  COMMITTED.json published last. No raw weights are uploaded to human scorer.
- A separate NumPy-only process fully replays TRAIN-label SGD and CAL-only
  temperature, recomputes each blind probability, checks nested source plan,
  resource accounting, actual tensors and E1 full-budget parity. It also
  binds the report/weights to the original verified E1/P0 receipts.
- The final human-label job starts **only after** all three physical model
  lanes succeed. It independently reacquires pinned original MultiRC TRAIN
  and VALIDATION parquets with byte-exact SHA, re-runs original P0 all-four
  source/label scorer, independently scores the source-bound E2 forecasts,
  and finally scores E3 4/8/12 only on the original human-labeled TEST rows.
  The result includes every unfavorable seed and per-source paired Brier gain
  with source groups as independent units. Never assign labels to the
  no-evidence counterfactual.

## Evidence and nonclaims

New focused tests, executed locally on **synthetic FP32 feature banks only**:
15/15 physical TRAIN+independent NumPy/negative cases and 12/12 original-human
score/negative cases, plus 27/27 under `python -O`; zero skipped.
Original v2 E1/E2 sources are not rewritten. Workflow YAML and all GitHub
Actions shell scripts pass local parse/syntax checks. The **actual pretrained
P0 task and this exact new branch CI are still not accepted at creation**.

Not established: task-quality improvement, superiority at 95%, exact full
backward FLOPs, energy, real target p95/p99, complete training cost,
chronological future windows, old-task retention, original model publisher
signatures, independent NDU promotion, Artifact CAS/CNS/FinalUse or production
Cell Split. SHA digests are content evidence, not independent host signatures.

**Keep Draft / DENY_ALL / NO MAIN MERGE / NO MODEL SELECTOR CHANGE.**
