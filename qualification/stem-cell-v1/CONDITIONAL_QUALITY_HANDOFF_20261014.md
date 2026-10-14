# Conditional Reader quality pilot | 2026-10-14

Parent #1925: `433e933a9716877057fcfd9e351326f325db3580`.
Code commit: `b66b7386bca9d27e3effbe6d3c01b6945547d0c4`. Draft PR #1941.

## Implemented

- Four actual CPU FP32 Reader training arms: full token-conditioned evidence, mean pooling, no evidence, no query representation. Equal weight shapes but measured optimizer/attention FLOPs are NOT equal.
- Balanced synthetic source-group panels, complete 2-query per-document denominators, training cutoff and no final labels or future evidence in the training API.
- Frozen features must be copied out of inference mode before autograd; evaluation features are encoded only AFTER all four candidates are trained.
- Sealed predictions and Reader safetensors precede a separate score-only invocation. The synthetic oracle is deterministic, not independent human ground truth or an OS isolation boundary.
- Relevant/irrelevant premise removal causes additional physical Encoder execution with independent observation. Accuracy after removing an indispensable premise is undefined, not a fabricated fail score.
- Versioned V4 Reader ATen accounting, explicit source/retained-feature caps, and three separate remote jobs (source, stock Transformers, pinned public-pretrained). No new energy measurement, native deployment or NDU activation.

## Actual verified local results

Two full source-slice test runs: 547 unique planned/executed tests, 0 failures/errors/skips each, exit code 0, identical test ID and file-hash inventories. The 21 new tests cover weight training, posterior scoring isolation, chronological order, balanced samples, missing evidence, storage caps, tampering and no retraining in scoring. Source blob hashes appear in the receipt. Python compilation and workflow YAML parsing passed; exact six-file patch replay passed.

16 synthetic heldout questions over 2 evaluation source groups (16 train documents, 8 eval documents; 32/16 train/eval questions); each Reader = 42 parameters. Conditioned 16/16 (Brier .08383), pooled 12/16 (.33046), no-evidence 8/16 (.50116), no-query 12/16 (.33046). Mean probability shift when omitting relevant premise .29770; omitting irrelevant premise .000134. Different training formula costs are in the receipt. None of these measures establish independent real-world QA generalization.

## Remaining experiments

The new stock HF and pinned public ModernBERT CI jobs were queued at source publication and are not counted as success. Real pilot execution will run 4 training source groups and 2 heldout groups under the same public checkpoint and stage its *synthetic* score only after sealed model predictions. The actual result may fail: do not relax thresholds or suppress failures.

An independent natural-language multiquestion dataset with separately governed labels, multiple seeds, group-disjoint splits, encoder/readout ablations, complete service cost and calibrated retention is required before selection. This does not establish multimodal generation, native NDU/System2, 1024/4096 Cells, or 10T/100T equivalence.
