# P2 training-cost frontier — one-active Head vs fixed/adaptive Cell Split

**2026-10-15 | Draft / DENY_ALL | research only**  
Direct child of PR #2235, *not* a replacement for historical P2/P1/Reader outcomes, NDU authorizers, original signed final-use owners, or `main`.

## The falsifiable question

Earlier P2 trials matched 40 SGD steps and 3,840 selected Head-row exposures for the single, fixed-Top-1, and adaptive-split arms. They did **not** match full CPU cost; the actual 8-round unprofiled cost crossover found extra routing/gradient/grouping overhead. Does an adaptive split retain accuracy **when its optimizer update count is reduced prospectively based on its train-only physical CPU cost**? Can a single Head reinvest its saved routing expense into *additional effective training updates*?

This test provides one limited answer under its own CPU/runtime; **it does not establish exact FLOP, full lifecycle, or equal data exposure parity**. Source material is frozen *retrospective public AG News*, not a genuine future task, independent time window, or multimodal generation evaluation.

## Registered comparison and critical protocol constraints

All four arms keep **14,868 resident FP32 Head parameters**, **7,434 active parameters/selected example**, exactly one expert gradient per training example, same initial FP32 two-Head bytes, same original train-only source, same learning rate (SGD .15), and unchanged frozen Encoder. The arms are: frozen no-change, trained single-active, fixed train-only Top-1, adaptive train-only clone/split. The previously sealed P2 predictions and independent audit are **required inputs**, not new target outcomes or weights to overwrite.

1. **Before human test-label opening**, independently reload the original exact pinned Granite R2 97M (or explicitly marked fake fixture in source-only tests) and perform 224 new actual feature encodes. Require exact original 96 per-case Q24 heldout features, model SHA, revision, original trained two-Head initialization, and train-only feature-0 routing cutoff. Every new real run pays an **additional model load plus 224 encodings**.
2. Execute **8 complete, balanced calibration rounds**: four arms in each round, each occupies each execution position twice. Each calibration is a **physical full 40-step re-training on training-only labels**, records CPU/wall, final original weight SHA, split and migration cost. The call **does not receive heldout labels or heldout tensors**. The 32 calibration re-trainings are *not free* and must be separately included in the lifecycle receipt.
3. Compute the reference training CPU budget as the median of eight completed `single_active` 40-step CPU durations. For each router arm, calculate its own median of eight 40-step CPU durations. Freeze an **even** number of updates in `[20,40]`: `n_arm = clamp(20,40,2*floor(floor(40*B_single/B_arm)/2))`. The trained single baseline remains 40; the frozen reference is zero. The number of old-only and mixed-training updates is exactly `n/2` each. No test labels, confidence, test accuracy or future proxies enter schedule selection.
4. Perform **one additional fresh actual SGD training** per arm using its frozen update budget. Only after fitting, produce **96 label-blind original features, route IDs, and two-class logits**, plus full FP32 learned Head weight byte payloads in a temporary create-only report. Charge actual training duration, router selection, group index work, diagnostic checks, parent-child parameter copy, clone-parity extra Head forwards, and shared model materialization. The receiver cannot silently discard a slow or low-quality arm.
5. **In a distinct independent scoring stage**, open the original public AG News source labels, first re-score the historical five-Head P2, one-active training, operator audit and balanced CPU receipt, then reconstruct all new logits from raw FP32 bytes in NumPy **without importing the Torch trainer**. Check 32 calibration + 64 test outcomes and original group/task identities exactly. Preserve both improved and worsened Cell Split results.

### Three distinct and non-equivalent concepts

- **CPU-preassigned budget:** arithmetic is independently auditable; real CPU scheduling noise can leave final Head work unequal. Report actual residual cost, never call this strict equal-compute or a processor-independent quantity.
- **Matched training examples:** original *40-step* trials match exposures. In this frontier, the single Head has 3,840 exposures; a routed Head with 34 steps gets only 3,264 exposures. The different exposure is the intended resource-allocation consequence, not a fair-data-constant estimate of routing's structural merit.
- **Lifecycle cost:** 32 paid calibration fits, 4 final fits, model load, 224 encodes, diagnostics, route/migration and scoring are all charged/disclosed. Dividing calibration cost across hypothetical millions of Cells without an observed amortization denominator is forbidden. This is *not* a measured production throughput or authenticated CPU counter.

## Actual local mechanism-only evidence

The offline source fixture uses a seeded **random 147,840-parameter Torch Stem**, synthetic public-AG-News-shaped source/labels and 40-step real one-expert Torch autograd. Three complete fixed seeds `41/47/53` had 32 physical calibration fits, four final fits, 96 original-label blind predictions, and full independent NumPy replays per seed. They are NOT pretrained Granite97 results.

No universal winner emerges from three synthetic seeds; because CPU time and chosen integer step counts vary by machine, **do not freeze a historical measured ratio or use test correctness to select the next calibration seed**. The sealed JSON preserves all complete source cost, weights, outcomes, p95/p99 nonclaims, and all unfavorable arms. A local failure or incomplete real CI stage remains failure, not replaced with these fixtures.

## Reproduce and proof gates

```sh
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_p2_train_budget_frontier.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_p2_train_budget_frontier.py' -v
python -m compileall -q qualification/stem-cell-v1/p2_train_budget_frontier*.py
```

The modified read-only workflow `.github/workflows/hepta-p2-equal-head-real-granite.yml` runs exact-SHA model/data source stages, actual CPU budgeted prelabel training **after the existing original cost crossover**, and independent full review **after** original owner-label opening. Model-free source integrity checks run in the first CI job. The real model job uploads only sanitized aggregate scores, source digests and failures; no raw source text, original model weights, private feature cache, learned Head full tensor bytes, or publisher secrets may be attached.

**Hard remaining blockers**: successful exact-head public pretrained job, independent publisher provenance beyond source self-consistency, prospective time/source family disjoint tasks and old-task retention, strict whole backward/optimizer/router CPU/GPU FLOPs parity, target Worker energy/request p95/p99, original signed FinalUse/CAS/WAL/revocation and Architecture/blocking-ci. No 10T/100T equivalence or NDU/System2 gain is claimed.

**Authority: DENY_ALL. Production selection: false. Do not merge to `main` or advance CURRENT.**
