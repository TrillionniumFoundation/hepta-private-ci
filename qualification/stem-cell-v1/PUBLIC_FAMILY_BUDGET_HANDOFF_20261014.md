# Budgeted public-task family split

Remote parent: `3b3077c3a7e17ac0c7c9ad99c9e456ca0e31f91d` (#1833).
Tested code: `61c031f40fde619d964d18bef2396a4ecab7436f`.
Branch: `research/shared-stem-public-family-budget-20261014`.
No main merge, historical rewrite, native installation or production selection.

## Implemented experiment, not a new efficacy claim

The existing public learning entry point now has an explicit V3 `--family-split`
option. It compares two separate topologies: `family_direct32` starts with 32
independent Heads using parent-first routing; `family_split16to32` starts with 16
actual Heads at the final per-child width. Both end with the same actual Head+
gate parameter count and top-2 parent/one-child routing. This is separate from
the existing dense16/sparse16/flat direct32 studies; their V1/V2 identities and
algorithms remain compatible. No 421M label is borrowed for the public Encoder.

First-stage training has a fixed 40% cumulative formula-budget ceiling and half
the step safety ceiling. The common boundary is a resource limit, not an equal
number of updates. Each side releases its optimizer and resets it once. Only the
training residual can trigger the split (fixed threshold 0.05). Nontriggered,
unfunded or numerically invalid transitions retain a failed arm, not a renamed
direct control. This is a single offline population transition, not multi-generation
optimal topology selection, causal identification or an NDU decision.

The new path reuses CellBank/FamilyCellBank, the existing whole-update training
loop, sibling auxiliary loss, strict WorkLedger and numerical transition probe.
Copied independent children keep original parent scores and mixture weights;
new gate rows select siblings rather than stealing another parent's top-2 slot.
A training-only probe checks initial float parity before specialization. Real-
arithmetic preservation of identical children does not prove global float parity
or preservation after learning. No held-out label enters the training API, split
trigger, counterfactual sibling target or budget decision.

## Actual budget and memory accounting

Family update reservations include four additional detached Head/row probes and
sibling-selector supervision, not just the two selected inference Heads. The
normal bank's unconstrained numerical path is unchanged; the family path also
matches its original fixed-update AdamW trajectory when the budget is nonbinding.
Bounds are conservative formulas for this eager CPU FP32 implementation, not a
universal bound on arbitrary hooks/backends or hardware instructions. Actual
work, not reservations, is charged; unknown/failed operations still fail strict
execution. Allocation, copies and Python control are not free runtime work merely
because the floating-arithmetic convention assigns them no FLOPs.

Migration is separately metered. Its actual cost is subtracted from the remaining
training limit, so it cannot be added outside the shared train+transition budget.
Construction, residual evaluation and parity probing have a conservative preflight
reservation and a post-execution bound check. Overshoot fails the candidate; no
partial-update rollback is promoted to success. These are cooperative boundaries,
not native-kernel preemption or OS resource containment. Unused work is retained;
no dummy operations balance the two arms. Final matching is checked from observed
pooled costs, not common caps. More cheap updates imply different sample exposures.

The simultaneous model-parameter cap is twice final Head+gate capacity in BOTH
arms. A split actually holds parent plus successor; direct initialization does
not allocate a dummy copy. The caller retains its parent reference until the
training call returns, and this is included in the reported model peak. Gradient,
optimizer, activation, shared Encoder and process peak memory remain separate.
Shared feature extraction is paid once per experiment and must be added back to
a standalone arm comparison. Initial/final inference, scoring and publication
also remain separately scoped, not claimed as matched or fully measured.

## Verification actually run

The predecessor source was restored from a manifest-verified archive and passed
457 planned/executed tests. The final source then passed 473 distinct planned/
executed tests twice, both exit 0, zero failures/errors/skips/expected failures.
The 16 new tests cover family update bounds, numerical compatibility, stage limits,
actual cloning, storage independence, real low-residual rejection, corrupted
parity rejection, reservations, failures, scoring isolation and saved-weight
restoration. All six uploaded code/workflow blob hashes match the tested bytes.
Compileall, diff whitespace and workflow YAML parsing passed. The first new test
attempt hit a test-fixture name collision with unittest.run; that failure log is
retained, and no training/meter threshold was changed to fix it.

A separate actual tensor diagnostic used synthetic four-dimensional one-hot
features, four train/four test rows, width_units=4 and a 2,000,000 budget:

| Topology | Initial/final parameters | Live model peak | Updates | Examples | Train + migration | Remainder |
|---|---|---:|---:|---:|---:|---:|
| family_direct32 | 1152 / 1152 | 1152 | 150 | 592 | 1,923,441 + 2,020 | 74,539 |
| family_split16to32 | 576 / 1152 | 1728 | 189 | 751 | 1,916,469 + 6,876 | 76,655 |

Both completed with no unknown operators. Pooled costs differ by about 0.11%.
Initial split probe error was zero on four rows. These observations establish
mechanism/accounting behavior only, not real-model generalization or a statistically
supported winner. The package retains actual weights, predictions, per-update
charges, test logs and diagnostic source, including its synthetic-feature identity.

## Hosted execution and open acceptance

Existing fixed-step and fixed-budget public jobs are preserved. One additional
public study uses the same pinned material, its own feature extraction, a 5e9
pooled budget per arm and a 4096 total-update ceiling. A required stock-HF family
check is added without changing the dependency, time or scientific gates. Hosted
artifacts exclude weights, news text and feature payloads; failures are retained.

The local attempt to install Transformers/tokenizers failed; the installed-HF
suite failed at import, so zero of seven real Encoder checks ran locally and none
counts toward 473. The ordinary local tests use actual PyTorch but synthetic
Encoder features. No public-news/pretrained learning result was obtained in this
increment. The checked #1833 runs were still queued; new CI must be assessed against
its own checkout. No full repository/Rust/native/GPU, independently authenticated
observer, complete system cost/energy, retention, compression or 1024/4096-Cell
qualification is inherited. The public path does not enable the nine-arm NDU group,
SYSTEM2 integration, multimodal generation or 10T/100T equivalence.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --output /new/nonexisting/tests.json
python qualification/stem-cell-v1/shared_learning_probe.py \
  --snapshot /reviewed/local/snapshot --news-dir /pinned/local/news --family-split \
  --training-flops-budget 5000000000 --max-budget-steps 4096 \
  --output /new/nonexisting/family-learning
```
