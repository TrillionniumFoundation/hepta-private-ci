# Bounded sequential confirmation of the same frozen Cell candidate

This opt-in research successor keeps the old fixed-sample experiment and its
recorded bank decision unchanged. The existing pretrained job runs both. It
loads the same SHA-bound original teacher/shared/ridge panel; no optimizer,
SVD, new Head, learned gate, NDU subject or production selector is introduced.

## Evidence and scope of the conditional guarantee

For one Cell define D = 1(candidate correct) - 1(bank correct). For each fixed
lambda in {1/8, 1/4, 1/2, 3/4}, multiply (1 + lambda D). Use the arithmetic mean
of these FOUR capitals, not their maximum. Compute the equal mixture in log
space from integer gain/loss counts. Ties multiply by one and supply no evidence
for strict improvement; zero observed losses alone does not pass.

Under the null E[D_t | the entire observed past] <= 0, each nonnegative capital
is a supermartingale starting at one; the fixed mixture is too. Ville's
inequality gives P(ever crossing 1/a) <= a. We allocate a=0.025/Cells to each
Cell and apply a union bound. In the two-Cell profile the boundary is 80.
A numerical 1e-8 log margin makes the implemented comparison conservative.
Checks occur at batch boundaries. Freezing a crossed Cell and adapting which
Cell to observe next does not invalidate this result under the stated null.

For a fixed iid Cell distribution, crossing rejects nonpositive mean accuracy
advantage: it is stronger than merely failing to detect a loss. This is NOT a
confidence interval for excess risk and NOT evidence for arbitrary future drift.
The deterministic public-text hash order is not verified iid sampling. We do
NOT apply a finite-population without-replacement theorem to it. Source-family
dependence, pretraining overlap, independence from earlier development, and the
conditional null assumptions remain unverified. Reports never certify retention
or authorize production use. Alpha=0.025 belongs ONLY to this NEW stream; it is
not a 0.05 familywise guarantee over the entire prior adaptive research history.
No old labels/evidence are pooled, and restarting after a failed stream would
require a separately declared error budget. The opt-in continuation below only
replays this same stream; it never pools a fresh restart. The same source/data run
is reproducibility, not new evidence.

Method background: Waudby-Smith and Ramdas, *Estimating means of bounded random
variables by betting*, https://arxiv.org/abs/2010.09686; Howard et al.,
*Time-uniform, nonparametric, nonasymptotic confidence sequences*,
https://arxiv.org/abs/1810.08240. This implementation uses the elementary fixed
finite-mixture construction above, not all algorithms in those papers.

## Actual data and execution contract

The proposal is locked BEFORE acquisition. Reconstruct and SHA-check the prior
1,024-row cohort and exclude it, plus all 128 original producer records, with
casefold/whitespace normalization. Keep the same qualified mmBERT and AG News
revisions and original text-length rules. Reserve exactly 4,096 confirmation
rows (2,048 per Cell) plus a separate 512-row final evaluation (256 per Cell).
Reuse the existing label-free salted text ordering on the remaining records.
Insufficient eligible material fails; never shrink or label-filter the pools.
The reserved cohort includes even rows that later remain unencoded/unlabeled.

Each round predicts up to 32 new rows from each still-active Cell. Preserve ALL
four historical panel arms and explicitly charge their inference work. Seal
that batch before reading any of its labels. Keep a hash chain of prediction
and outcome records. A crossed Cell receives no further confirmation forwards
or label reads. At the cap, accept the original proposal in this offline
conditional diagnostic only when every Cell crossed and the proposal is smaller;
otherwise keep bank. Never choose another arm from the new labels. Seal this
decision BEFORE final inference, and final predictions BEFORE final labels.

The final 512-row evaluation always runs. Model loading, encoding, panel
inference, statistical bookkeeping and publication spans are retained. Saving
confirmation rows is measured by absent actual callbacks/forwards, not by merely
masking precomputed features. Comparing consumed counts to the reserved cap is
an avoided-work count, not a wall-time speedup benchmark. No claim of lower
end-to-end latency, energy, full-process peak memory or new learned capability.
Unknown effects/errors fail and retain prior evidence; there is no automatic
retry, model mutation, CURRENT change or product FinalUse integration.

```sh
python -m experiments.shared_stem_cell.sequential_confirmation \
  --study /public-study --consolidation /consolidation \
  --producer-sha256 <external-producer-report-sha> \
  --consolidation-sha256 <external-consolidation-report-sha> \
  --previous /previous-fixed-confirmation --previous-sha256 <external-report-sha> \
  --output /new/sequential-confirmation
```

## Interrupted-stream continuation (same evidence, no fresh restart)

`sequential_replay.py` seals a **quiescent** output prefix into a new checkpoint
folder. It requires the complete candidate/cohort lock and accepts only bounded,
canonical ordinary files. Before publication or continuation it runs the existing
stream on saved predictions and labels in a disposable directory, recomputing the
exact active-Cell schedule, counts, mixture evidence, hashes, decision and final
scores where present. It does not trust serialized statistical state. Missing
middle batches, orphan outcomes, changed evidence/scores, malformed trailing JSON,
wrong source/profile and a wrong externally supplied checkpoint hash reject before
live callbacks. No damaged file or negative historical result is repaired.

```sh
python -m experiments.shared_stem_cell.sequential_replay \
  --source /quiescent/interrupted-stream --checkpoint /new/checkpoint
# Save the printed SHA256 outside the checkpoint. Continue with the SAME original
# --study, --consolidation, --previous, and corresponding source report hashes:
python -m experiments.shared_stem_cell.sequential_confirmation \
  --study /original/study --consolidation /original/consolidation \
  --producer-sha256 "$PRODUCER_SHA" --consolidation-sha256 "$CONSOLIDATION_SHA" \
  --previous /original/fixed-confirmation --previous-sha256 "$PREVIOUS_SHA" \
  --resume-checkpoint /new/checkpoint --resume-sha256 "$CHECKPOINT_SHA" \
  --output /new/continued-stream
```

The destination is always NEW; original outputs, failure records and checkpoint
bytes remain untouched. Saved prediction batches avoid new Encoder/Head calls;
labels in complete outcome receipts avoid repeated label callbacks. A prediction
without an outcome is reused and its labels are then requested. If final predictions
are already saved, the CLI does not instantiate an Encoder. The caller must still
supply the original fixed source/model identities. Protocol changes cannot resume
an older checkpoint; this is deliberately not a cross-version migration facility.

Each resumed report binds the checkpoint and any original failure. Its continuation
section separates reused vs new prediction/label callback rows. Per-batch timing
records still describe the **whole logical stream**, including historical work;
do not sum them and claim they were all incurred by the new process. Prefix
validation, acquisition and any required model load are separately measured.

This is NOT exactly-once execution: work in flight without a complete saved record
is unknown and may repeat. A partially written file is refused, not silently
truncated. Quiescence and an externally managed latest checkpoint are required;
this helper is not an anti-rollback authority, distributed lock, automatic retry
manager or production ledger. It supplies no new error budget, evidence reset,
model selection or lifetime retention guarantee. Existing statistical assumptions
and failed historical decisions remain unchanged.

Regression coverage includes four actual child exits after prediction, outcome,
decision and final-prediction persistence, followed by fresh-process continuation.
A separate development demonstration uses archived 128x384 genuine mmBERT features
and the frozen original Head panel with three SIGKILL cuts. No Encoder or fitting
runs in that demonstration, and it is NOT fresh scientific confirmation evidence.
