# E2: exact-source original-human gated-vs-additive Head score — RESEARCH / DENY_ALL

## Frozen ancestry and scope

Parent: E1 #2257 at `67725a70621872ecd3557f6b4d1bca11f3792ed2`.
Original four-model P0 owner: #2233 at `b3b3712828cb5814e1a87d1e69a030ec947c43c1`, GitHub run `38686023757`.

This is an **additive research scorer**, not a selected production model.
No existing E1/P0 model loader, Rust production Cell, NDU, FinalUse, Control,
CNS, CAS, WAL, Trainer or original held label owner is modified.

## The gap being closed

E1 first proved physically trained 4,145-parameter gated and additive Heads
could be replayed numerically from the same feature snapshots. It did **not**
create an independent human-label quality comparison. The new pipeline emits a
source-bound, prediction-only prelabel seal AFTER E1 independent NumPy replay,
and opens original MultiRC labels only in a **separate post-producer job**.

There are **three original compact models** in this P0 lineage: Granite97,
mmBERT-small and EmbeddingGemma 2 text; Laya421 remains original native
no-change context, not an equal-sized trained Head. ModernBERT does not yet
have a registered original-weight loader in this experiment. Synthetic 768D
code tests are not a real ModernBERT experiment.

## Integrity and isolation

- Source Python tests run ordinarily and under `-O`. Exact SHA checkout enforced.
- Each E1 physical run reuses immutable source features and runs the original
  P0 V5 numeric reviewer. 40 SGD updates/train-only, six CAL temperatures,
  three fixed seeds and four Head arms are unchanged.
- The seal process takes original blind input, E1 COMMITTED Head manifest and
  E1 NumPy replay. It emits only bounded case IDs, view/group/condition hashes,
  the 12 prelabel probability vectors, model/source identities and hashes. No
  model weights, TRAIN/CAL labels or held human labels are uploaded.
- Missing P0 run success, a model artifact, one of three E1 arms, one numeric
  review, a source group, a finite forecast, the exact commit, or a strict
  P0 source/label replay **fails closed**, not zero-score or fallback.
- A separate independent human-label job downloads original pinned FIT/blind
  and the original human owner artifact. It reacquires original train/validation
  MultiRC Parquets pinned at the original dataset revision, checks SHA256 and
  **re-runs the existing full four-model P0 human reviewer**.
- It also cross-checks each E1 sealed prediction with the separately archived
  independent numeric receipt hash. The model producer never receives held
  labels. The human job imports no E1 trainer or Torch.
- It scores only original labeled input, not transformed no-evidence cases
  (which have no new human truth). Reported quality is accuracy/Brier per arm,
  descriptive paired `additive_brier_minus_gated_brier` per original passage,
  and separate frozen/trained comparison within each seed.
- An original source passage, NOT each correlated answer, is the paired
  unit. There are just eight source passages in this preliminary panel.
  No 95% statistical advantage or genuine future-window inference is claimed.

## Execution evidence and known blockers

Local actual CPU Torch + NumPy tests on **synthetic feature data**:
`test_e1_matched_gated_head.py` (22) and
`test_e2_original_human_score.py` (16), **43/43 each** in normal and `-O`
mode. New E2 negative source tests include altered/rehashed model references,
missing/malformed labels, case permutation, missing/duplicated trials,
nonfinite predictions, forged authorization and numeric reviewer mismatch.
The original pretrained model source/labels and actual full deployment were
**not** run locally. This local result is only test of the research mechanism.

Exact-head GitHub Actions, original P0 real-model completion, all 3 E1
replays, and this E2 human score job remain mandatory hosted gates. Original
weight publisher, independently signed execution, NDU utility, complete
training/serving TCO and energy, future task windows, old task retention,
4096-Cell latency/RSS and final use authority are **not established**.

**DRAFT / DENY_ALL / no main merge / no model selection / no physical split
or deployment.**

## E2 v2 verified producer-to-score forecast binding

The first E2 implementation could check a probability vector's shape, source
identity and numeric-review SHA, but did **not** recompute its contents from
the original E1 producer report. A modified, valid-length prediction vector
could have been scored without matching the actual reviewed E1 report.

The independent E1 NumPy reviewer now emits, **only after all 40 original
TRAIN-label updates, CAL-temperature choices and blind forecasts replay**,
SHA256 identities of its reviewed E1 producer report, probe safetensors,
original P0 report, blind source and registered model. The E2 prelabel seal
refuses any mismatch with those independent reviewer identities.

The E2 human scorer also downloads the original E1 producer COMMITTED.json
for **each** registered model from separate non-merged artifacts, checks
its digest against the reviewed summary, and rebuilds the complete prelabel
seal from the original producer report and independent numeric result.
A detached/rehashed forecast fails, even when it remains a finite valid
probability and its self-reported hash is updated. The E1 producer report
contains original unscored forecasts and metadata, NOT raw Head weights or
held human labels.

New local focused suites: **43/43** normal and **43/43** under `python -O`
(synthetic CPU feature test data only). No authentic pretrained E1 task
efficacy can be claimed from the source-only tests. A coordinated compromise
of producer plus numeric-review runner remains possible: SHA256 is a content
identity, **not independent signed physical execution authority**.
