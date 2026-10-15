# V7.7 — One frozen V6 BridgeReader, physically shared by 256 specialized gated Heads

**Date:** 2026-10-15. **RESEARCH / SHADOW_ONLY / DENY_ALL.** No main merge, selected Stem, native NDU/FBSDE upgrade, CellSplit promotion or product effect authority. Builds on [V7.6 original V6/V7 source-cluster negative-transfer diagnosis](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2383) and unchanged V6 parent [#2338](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2338). Does not change historical runtime, original warmup tensors, V1/Q24 interface or historical results.

## Why this is a substantive next step

The authentic V6 and V7 historical Natural MultiRC internal panels show that seven previous whole-Reader continuation schemes lost internal F1a against the frozen starting Bridge model. This motivates a distinct physical architecture, **freeze the old shared BridgeReader exactly** and train only a *new task-specific Cell Head*. It is more meaningful than just an extra training loop, but it remains a **mechanistic candidate**, not evidence that Natural MultiRC was learned.

## New source and actual ownership

- `bridge_split_cell_v77.py` implements `SplitBridgeCell` holding the **same reference to exactly one original, frozen, 42,562-scalar FP32 BridgeReader**, verified using original V6 *training* parameter-digest naming and geometry. It never deep-copies the Reader. The `GatedNewHead` adds exactly **1,700 scalars**: a 97→16 projection, a 97→1 sigmoid gate and a 16→2 correction. The correction output initializes to zero. Its new-task prediction is `frozen_logits + sigmoid(gate) × learned_correction`.
- The original Binding route calls only the original trained V6 Reader under `no_grad`, **entirely bypassing the new gate/Head**. The new natural-task candidate route extracts exactly 97 pre-head features using a narrowly scoped V6 head-input forward hook. All Cells sharing the physical Reader reuse the **same shared lock**, preventing overlapping extraction hooks. The original Reader always stays in evaluation mode with no gradients.
- `RouteEvidence` binds task family, case identities, source SHA256s, exact public feature tensor bytes, original frozen Reader SHA, caller principal/preprocessing/Encoder identifiers and non-production scope. **These are caller-provided commitments, not a signature, authorization, actual Encoder provenance, or an authenticated route owner**. An upstream trusted source owner would be necessary for any later product integration.
- `collect_new_task_cache` accepts only new-task TRAIN public source groups, rejects conflicts with specified old Binding source IDs, materializes actual **frozen Reader** 97D features **once per batch**, and does not contain labels. `fit_new_task_head` consumes labels **only for the new Head's cross-entropy loss**, updates its **six** tensors using a bounded fixed-budget Adam schedule, never includes parent tensors in the optimizer, checks parent SHA and absence of gradients afterward, then freezes the learned Head. Captures parent forward/cached bytes, attempted optimizer updates, actual CPU/wall/optimizer state. No history rewrite or online mutation of the selected old task weights.
- `run_v77_archived_cell_split.py` executes physical CPU trials on the **three actual historical V6 frozen warmup checkpoints** from immutable user-owned archive `hepta_bridge_learning_v6_20261015.zip` (20,928,479 bytes; SHA256 `197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a`). All 3 original archived FP32 tensors and model SHA records are checked before use. **NO original Granite Encoder or natural language token vectors were loaded.**
- `bridge_split_v77_review.py` independently reopens the entire original V6 archive and both complete repeated-run JSONs **using Python stdlib only**, revalidates original weight/file identities, strictly checks all fields and DENY_ALL limitations, verifies authentic seed and count/accounting, and compares the three trained Head digests and all synthetic scores across two separate physical CPU runs. This is a **receipt consistency and deterministic repeat audit**, not a reimplementation of Adam or a true physical host attestation.

## Actual bounded, genuine-weight CPU experiment

**Model material:** three genuine old V6 warmup Readers (seeds `41,47,53`), each `42,562` frozen FP32 scalars; **not** three replicas of 97M Granite. Physical inputs: deliberately **synthetic non-Granite** random 384D tokens and masks. Synthetic teacher label: positive iff `frozen Reader pre-Head latent[0] − latent[1]` is above the **median of the 160 synthetic TRAIN** observations. Those labels contain **zero** real MultiRC task truth; the operation is deliberately constructed to test whether a small Head can learn a property demonstrably present in its existing representation. This task is far easier than reasoning over source text. Repeated synthetic held-out source identities are separate from synthetic training identities, but do **not** constitute independent human data or authentic task generalization.

Training per original seed: `160` synthetic train rows, fixed `420` Adam updates, mini-batch `16`, LR `0.04`, one forward of old Reader per unique cache batch (`10`), **no extra Reader forwards during Head optimization**, then evaluate on 48 independently generated synthetic token observations. No hidden checkpoint/metric selection during optimization. Original old-route logits were checked with `torch.equal()` **before AND after** each training run; frozen parent state SHA remained identical and parent parameter gradients were never created.

| Authentic original V6 weight seed | Synthetic train baseline → gated Head (out of 160) | Separate synthetic inputs baseline → gated Head (out of 48) | Frozen old route bytewise identical? |
|---|---:|---:|---|
| 41 | 88 → 160 | 26 → 42 | Yes |
| 47 | 70 → 160 | 19 → 41 | Yes |
| 53 | 79 → 160 | 22 → 41 | Yes |

Two separately executed full CPU campaigns produced the **same three new Head tensor digests, every synthetic score and old-route invariance observation**, while independently measured CPU/wall durations varied normally. Numerical improvement is only on a **teacher-defined synthetic latent task** and must **not** be represented as real Natural MultiRC improvement, multimodal transfer or automatic reasoning emergence.

### Physical 256-Cell parameter-memory accounting

- Actually allocated **256 distinct gated Head objects** on one verified seed-53 original Reader; every Head weight storage address was different, **all 256 parent Reader tensor pointers were the same physical storage** (one original module object). This is a live memory/reference identity test rather than 256 logical-counter receipts.
- One shared FP32 Reader: `42,562 × 4 = 170,248 bytes`.
- One 1,700-scalar Head: `6,800 bytes` (~3.99% of the Reader parameter count).
- **Actual cohort parameter weight budget:** `170,248 + 256 × 6,800 = 1,911,048 bytes` (~1.82 MiB).
- Replicating the 42,562-scalar Reader 256 times would require `43,583,488 bytes` (~41.56 MiB) in weights alone; this weight-only comparison is ~22.8×, **NOT a measured latency/energy/total RSS saving and NOT a 421M/97M model-equivalence claim**. Each per-Head Adam optimizer has additional (~13.6 KB) tensors during training, in addition to feature caches, Python module objects and temporary activations; the shared original Granite97 Encoder and any video/audio/image decoders are **NOT INCLUDED**.

## Verified tests and reproduction

The new test suites include real original 3-seed archive reads (only when exact bytes available), CPU PyTorch forward/backward/Adam, deterministic 97D extraction, exact old-route preservation after new-only training, two simultaneous Cell Head instances on the same Reader, shared extraction-hook locks, invalid route/model/task/scope and feature SHA denial, source overlap denial, no labels in cache, full original checkpoint identity, original shadow-claim rejection, fake archive/future/production/model status rejection, duplicated JSON properties, and strict model/optimizer cost checks.

```bash
cd qualification/stem-cell-v1
export HEPTA_ORIGINAL_V6_ZIP=/sealed/hepta_bridge_learning_v6_20261015.zip
python -m unittest -q test_bridge_split_cell_v77 test_bridge_split_v77_review
python -O -m unittest -q test_bridge_split_cell_v77 test_bridge_split_v77_review
python run_v77_archived_cell_split.py \
  --original-v6-zip "$HEPTA_ORIGINAL_V6_ZIP" --physical-cohort 256 \
  --output /sealed/first-result.json
python run_v77_archived_cell_split.py \
  --original-v6-zip "$HEPTA_ORIGINAL_V6_ZIP" --physical-cohort 256 \
  --output /sealed/second-result.json
python -S bridge_split_v77_review.py \
  --original-v6-zip "$HEPTA_ORIGINAL_V6_ZIP" \
  --first /sealed/first-result.json --replica /sealed/second-result.json \
  --output /sealed/independent-review.json
```

Local-only test copies of `token_reader.py` and `bridge_reader.py` were created to execute tests in the isolated container and **are not committed or substituted into GitHub**. The tracked repository's original V6 sources remain in use in the branch. The exact V6 tracked TokenReader and BridgeReader blob identities are `ca814a855c35e3d6fcf50883dba6d66b325d5c54` and `a9e7fba84fdff03e3f65c9d67bf42d59ee931cd1`. Running the above scripts from the actual GitHub branch uses those original source implementations.

## Nonclaims and next scientifically required gates

This does **not** solve real task negative transfer. The new Head's synthetic target is defined directly from its own frozen latent. It has not learned authentic human MultiRC ground truth, nor proven future-source retention, multimodal generation, sparse 4096-way dispatch latency, optimal Stem, neural FBSDE/System2 net gain, NDU-controlled Cell Split, direct device/computer authority or a 10T/100T equivalent system. The already published old V6 Natural MultiRC and historical V7 negative results remain valid, and no old real-world correctness metric was replaced.

Next: acquire and byte-verify **the exact original 97M Granite pretrained Encoder plus matching V5 TokenBank**, reproduce old Binding train predictions against original sealed V6 saved probabilities before training; execute a source-disjoint, fixed-cost comparison between (A) unchanged parent + separate trained new Cell Head, (B) existing V7.4 whole-Reader update, (C) no-change frozen baseline, and (D) parameter-/optimizer-byte-matched ungated control. Only use independent untouched future sources to decide whether any source-authenticated router may select the split Cell. Until then the complete candidate remains **DRAFT / SHADOW_ONLY / DENY_ALL**, no production actions or memory mutation on deployed models.
