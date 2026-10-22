# Required text/image inference contract — actual retained-Head check

The new `predict_text_image_required(head, bundle)` research entry point rejects
rows missing either required modality **before any Head forward**. Complete
rows retain the original predictions, calibration and confidence threshold.
Every output remains `SHADOW_ONLY`, `DENY_ALL`; confidence acceptance grants
neither task admission nor action execution.

This check ran at **2026-10-22 05:47:04 UTC** against both real, saved joint Heads
from the [fixed multimodal experiment](../20261022-real-multimodal/RESULTS.md).
It does not retrain, recalibrate, modify the original report, or constitute a new
independent task-quality trial.

## Actual result

Each row below is a 256-row input case. A forward hook independently observes the
actual Head batch sizes; it does not rely only on the wrapper's counters.

| Input case                              | Gated / linear rows scored | Missing rows rejected | Actual forward batches per Head | Gated / linear confidence accepted |
| --------------------------------------- | -------------------------: | --------------------: | ------------------------------- | ---------------------------------: |
| Correct original pairs                  |                  256 / 256 |                     0 | One batch of 256                |                          255 / 252 |
| Text missing                            |                      0 / 0 |                   256 | None                            |                              0 / 0 |
| Image missing                           |                      0 / 0 |                   256 | None                            |                              0 / 0 |
| Image shuffled, both modalities present |                  256 / 256 |                     0 | One batch of 256                |                          255 / 252 |
| Mixed complete/missing input            |                    86 / 86 |                   170 | One batch of 86                 |                            85 / 85 |

All scored logits, probabilities, class IDs and confidence acceptance match the
original task API exactly on the corresponding valid sub-batch. Head tensor
digests, original feature bytes and source ordering remain unchanged. Rejected
rows have null logits, probabilities and class IDs, an explicit missing-modality
reason, and `accepted=false`.

Zero accepted missing rows means abstention, not perfect accuracy or zero
selective risk. There are no scored rows from which to estimate that risk. The
original high-confidence missing-input failures remain in the original report.

## Evidence and reproduction

[report.json](report.json) binds ten per-row JSON result files, the exact guard
and replay-script digests, the original report, and the externally pinned archive
manifest. Each result also retains the parent bundle/source digests, Head tensor
digest, contract digest and actual scored row indices.

From the repository root in the pinned research environment:

```bash
python qa/stem-bakeoff/replay_presence_guard_v1.py \
  --archive-directory qa/stem-bakeoff/evidence/20261022-real-multimodal \
  --output /tmp/hepta-presence-review
```

The output must be a new directory. The script first restores and verifies all
91 archived members, checks the fixed original report and scientific source
hashes, loads the immutable bank and Heads, then checks the new input contract.
No Encoder checkpoint, photo download, labels for the guard, or new training is
needed. The research workflow runs this retained-Head regression separately from
the newly executed scientific experiment and preserves its result files.

The guard also has 11 behavior tests using actual tiny deterministic Head
modules. They cover mixed-batch isolation, preservation of optional tensor
views, refusal even when the old API would be very confident, identity/mask/
source/weight drift, mutations during inference and unchanged authority.
The final composed Stem suite passed **257/257 tests in 7.633 seconds**; the
source-bound [validation.json](validation.json) and [stem-tests.txt](stem-tests.txt)
retain that separate unit-test evidence. Native CI is still an independent gate.

## What remains outside this fix

Presence is an integrity-bound claim from the feature producer, not independent
source authentication. A valid pair and a semantically wrong pair can both have
text and image present. The shuffled cases deliberately continue to be scored.
The guard does not establish missing-modality robustness or a validated unimodal
fallback, and it is not integrated into a production native caller.

The new native [shared-Encoder](../../../../codex-rs/hepta-neuron/src/shared_encoder.rs)
and affine [CellHeadV1](../../../../codex-rs/hepta-neuron/src/cell_head.rs) APIs accept
inputs up to 4096 dimensions; the 3073-dimensional research view fits that width. However,
the trained PyTorch gated/GELU Head has no demonstrated native artifact export
or numerical equivalence to that Q24 affine Head. The older runtime/inference
request path has a separate [512-dimensional limit](../../../../codex-rs/hepta-neuron/src/runtime_types.rs). Choosing a native adapter
must preserve the actual model semantics and identity; converting features
alone does not establish Head equivalence.

Full policy training additionally needs real product episodes, state
transitions, a legal action vocabulary and independent outcomes/rewards. Existing
[learning-ledger dataset freeze/read interfaces](../../../../codex-rs/hepta-learning-ledger/src/lib.rs) should supply that evidence.
The current static COCO task supplies none of those episode or action targets.
Target-device qualification still needs an identified device/runner, real
concurrent load and measured queue-inclusive latency, memory and energy.
