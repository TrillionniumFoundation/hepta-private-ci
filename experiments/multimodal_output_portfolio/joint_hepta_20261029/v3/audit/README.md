# Independent retained-evidence audit

This additive audit reads the frozen V3 evidence and selected weights. It does
not train a model, edit a result, repair a failed artifact, change an original
gate or reinterpret the superseded pilot. Accounting and media scoring are
implemented independently of `runtime.execute`, `media.read_bundle` and
`media.utility`. Only the registered mechanism source generator is reused to
reconstruct the exact public input and target from its namespace and identity.

## Executed coverage

| Component | Actual retained evidence checked |
| --- | --- |
| Six-cell, eight-arm factorial | 6,144 training, 2,304 analysis and 2,304 inference-control trajectories |
| Paired prefix diagnostics | 2,048 actual continuation trajectories; all prefix/input/NPZ/readback identities |
| First-choice critic consumption | 256 additional trajectories; actual original/calibrated candidate values, selected first actions and original-actor control |
| Critic calibration | Both heads, training/validation and before/after weights: eight metric cells; all 32 metric values independently recomputed |
| Free-text adapter | Twelve completions, 544 token IDs, actual local tokenizer decode and all local LM/tokenizer file identities |
| Native content backend | Source/selected-checkpoint binding, fresh compilation, full semantic journal replay and exact newly encoded media |

All **13,056 unique actual trajectories** passed with no reconciliation errors.
Every successful outcome's actual PNG, WAV, GIF and UTF-8 files was reopened.
The maximum difference between independently computed FP64 mechanism utility
and the retained Torch FP32 score was **1.0963386576356982e-7**, below the declared
2e-7 comparison tolerance. Failure fields, complete expected grids, counts and
aggregates were checked; the final runs retained zero executed failures.

The 12,800-trajectory main audit took 173.56 wall seconds after its imports and
performed 1,017,329 validation assertions, excluding its trajectory/statistical
counters. Later checks process only the additional consumer/calibration data;
the main trajectories are not re-executed or regenerated.

## What is independently reconciled

The on-disk `TRAJECTORY.json` ends before the final seal write. The audit adds
the separate `SEAL_COST.json`, checks CPU/wall tariff arithmetic, service fees,
continuous suffix meter boundaries, inherited prefix costs, state-hash links,
remaining budget and final return, then compares the reconstructed return with
the actual evaluation/diagnostic rows. Consumer outcomes additionally include
their recorded planning events and caller close. This avoids treating a
pre-seal number as the executed training/evaluation return.

All sixty pretrained/final matrix checkpoint files and parameter groups are
bound to their reported identities. Every arm starts from its mode's same
pretrained parameters; all frozen-generator and fixed-actor groups are checked
against actual saved tensors. Calibration changes only its permitted critic
parameters. Final checkpoint identity is shared by the matrix, diagnostics,
free-text adapter and native qualification.

Population CEs and all matrix/consumer source-bootstrap comparisons are
recomputed from actual sealed outcomes. Diagnostic predictions are compared
with matching suffix returns; calibration feature/target/source weights and
proper exponential-moment metrics are recomputed using actual before/after
weights. No empirical best action is promoted to a known optimal action.

The final combined audit verifies original source identities and reconstructed
public-input hashes are disjoint across matrix training, matrix analysis,
critic fit, critic analysis and first-choice analysis. Repeated arms/draws remain
the same original source. The audit observed 238 distinct source IDs in the
retained joint-training rollouts; 384 is the registered training source universe,
not a claim that every one appears in those rollout files. Supervised pretraining
does not produce those media trajectories. Free-text fit/analysis separation is
checked at the declared CPython module level; foundation-model pretraining may
overlap those public documents.

The superseded pilot's explicit status and raw training traces remain present.
Its results are excluded from the final factorial; the audit does not relabel
the interrupted attempt as a successful primary run.

## Reports and source modules

- `evidence/SUMMARY.json` and `SUMMARY.md` bind all completed component reports,
  their source/log hashes, 13,056 unique paths and all five data-role overlaps.
- `evidence/final_20261031/` contains the main `AUDIT.json`, `AUDIT.md` and
  12,800-line `TRAJECTORY_AUDIT.jsonl`.
- `evidence/consumer_20261031/` contains the separate 256-row audit and its
  report, including actual first-choice and complete accounting checks.
- `evidence/calibration_20261031/AUDIT.json` contains independently recomputed
  proper losses, moment biases and CE errors from actual fitted tensors.

`core.py` owns ledger/source/media primitives; `matrix.py`, `diagnostic.py` and
`adjacent.py` cover the three related evidence groups. `consumer.py` and
`calibration.py` add later evidence without modifying the completed main run.
Each source module remains under 250 lines. The audit reports bind the exact
source files present during their execution.

## Reproduction

Use Python with Torch, NumPy and Pillow. The native section requires the
declared Rust compiler; free-text token decoding requires the already downloaded
model/tokenizer directory and a Python environment with Transformers. No network
download is needed. Run from the repository root with a new output directory:

```bash
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.audit.run \
  --output /tmp/hepta-new-independent-audit \
  --rustc /absolute/path/to/rustc \
  --model-directory /absolute/path/to/verified/local/model \
  --tokenizer-python /absolute/path/to/python

python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.audit.consumer \
  --output /tmp/hepta-new-consumer-audit

python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.audit.calibration \
  --output /tmp/hepta-new-calibration-audit
```

The repository's combined `summary.py` binds the three published evidence
directory names above. Individual reruns in other directories remain separate
receipts and do not overwrite the published execution records.

## Limits

This is evidence reconciliation. It does not independently recreate physical
CPU/wall measurements from an external clock, assume those timings are
exogenous, or model their direct gradient. It does not replay optimizer updates.
It verifies actual selected weights and retained outcomes, not an optimal NDU
solution or statistically confirmed gain.

All free-text fixed factual predicates still fail in all three arms; human
ratings remain pending. Native fresh replay demonstrates the declared local
content/prefix profile and reproduces the original binary hash. It does not
establish production owner adoption, prefix-aware learned coherence, an
automatic external witness service, transport acknowledgment, or hardware
power-loss qualification.

The packaging helper was separately read through for relative-path admission,
chunk/archive/member hashes, duplicate/link rejection and fresh-destination
restoration. No general concurrent hostile-filesystem or resource-exhaustion
security claim follows from that scoped review.
