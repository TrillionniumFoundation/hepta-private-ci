# GRU7 comparator under the factorial pilot's resource ceilings

This package adds a real PyTorch GRU comparator to the synthetic HCSN boundary/content pilot. Three fresh CPU FP64 fits completed 32 Adam updates each. Saved logits, all training hidden states, optimizer states, checkpoints and source/data identities are retained. This is a bounded engineering comparison; neither adequate training nor a tuned strong baseline has been established.

## Common inputs and charged capacity

The comparator reads the already frozen factorial `DATA.json` and `PLAN.json`. It uses the same three seeds (11, 23, 37), exact episode order within each seed, 12 training episodes, 32 update opportunities, query-position cross entropy, Adam learning rate 0.003 and gradient clipping at norm 1. Each seed is evaluated on the same 24 development episodes, containing 192 scored queries across delayed copy, overwrite retrieval and pair composition. The three initializations share this development set; they are not three independently sampled test sources.

`BudgetGRU` constructs the same seed's `FactorialModel(c0_b0)` to copy its 21-to-4 frontend and 9-to-8 head, freezes both, then discards the HCSN instance. The body is PyTorch `nn.GRU(4, 7)` followed by a learned 7-to-9 linear projection. Copy construction is charged in the measured fit cost. Byte equality of the two common modules is checked at construction, throughout training, in tests and against the retained HCSN joint-arm checkpoints.

| Quantity | HCSN joint arm | GRU comparator |
| --- | ---: | ---: |
| Learned parameters | 391 | 345 |
| Total parameters | 812 | 513 |
| Persistent recurrent payload, FP64 bytes | 1,000 | 56 |
| Actual Adam updates per seed | 32 | 32 |
| Common frontend output / frozen head input widths | 4 / 9 | 4 / 9 |

These are common upper limits, not equal actual occupancy. Payload counts exclude parameters, optimizer state, clocks, inputs, retained traces and temporary training allocations. The learned projection also gives GRU additional effective readout flexibility: equal frozen head tensors do not imply identical effective readout hypothesis classes. The comparison therefore concerns the whole finite-budget model, not an isolated recurrence or boundary effect. GRU receives the same `log1p(dt)` feature but advances on event index without a continuous-time decay law.

## Actual local result

| Seed | GRU development CE | GRU accuracy | HCSN joint CE minus GRU CE | HCSN joint accuracy minus GRU |
| --- | ---: | ---: | ---: | ---: |
| 11 | 2.079586760 | 11.4583% | -0.002996616 | +4.6875 percentage points |
| 23 | 2.088608658 | 12.5000% | +0.012691389 | 0.0000 percentage points |
| 37 | 2.101796885 | 11.4583% | -0.002776804 | -2.6042 percentage points |

The descriptive mean HCSN-minus-GRU CE is +0.002305990, and the mean accuracy difference is +0.6944 percentage points. The directions disagree across seeds and metrics. Eight-class uniform prediction has CE `ln(8) = 2.079441542` and expected accuracy 12.5%; both models remain close to this scale after this short training schedule. The data do not establish a task-quality advantage. This stage was selected after some factorial results existed and before the full factorial run terminated; no configuration search was performed. It is a retrospective development control, not a preregistered independent confirmation.

The retained comparison script recalculates CE/accuracy directly from both models' raw development logits, verifies identical episode/label order and training schedules, checks the complete declared seed/arm rosters, checks source/data identity, and compares common interface tensors from SHA-bound checkpoints. It performs no model forward or optimizer step. `comparison.json` records these checks and the per-task differences.

## Observed cost and its scope

Both runs used Python 3.12.14 and PyTorch 2.8.0+cpu, deterministic CPU FP64 operations and one Torch intra/inter-op thread on host `05afa1b52275`. Both wrote to the same `/dev/shm` tmpfs. The GRU run explicitly recorded the concurrently running HCSN study, so these are observed shared-host costs, not an isolated performance benchmark.

| Seed | HCSN joint fit wall / CPU seconds | GRU fit wall / CPU seconds | GRU training compute wall seconds |
| --- | ---: | ---: | ---: |
| 11 | 58.3002 / 58.2004 | 1.5507 / 1.5398 | 0.3036 |
| 23 | 55.7344 / 55.0910 | 0.5788 / 0.5688 | 0.3103 |
| 37 | 48.6736 / 48.2089 | 0.4889 / 0.4877 | 0.3096 |

Each fit total includes model construction, training, complete state trace serialization/fsync, development evaluation, checkpoint retention and evaluation after loading into a new model. It excludes writing its final result JSON. The complete GRU child took 5.4679 wall seconds and 5.4126 waited child CPU seconds; those totals overlap the fit costs and must not be added to them. First-fit import/optimizer construction costs differ from later fits.

The GRU report separately measures training compute, trace retention, development compute, checkpoint/artifact retention and replay. Uninstrumented construction, input batching, digest work and other overhead remain in the fit total. The frozen HCSN producer did not measure those separate sections, so HCSN component values are explicitly null. The larger HCSN state trace has more serialization work; these totals cannot be presented as isolated kernel throughput, inference latency, energy savings or an equal-quality speed comparison. The first HCSN full attempt failed on ENOSPC and remains a separate preserved attempt; this comparison uses only the complete tmpfs retry `hepta-hcsn-full-002`.

## Verification and retained evidence

Three meaningful local tests passed: exact common interfaces/capacity, an actual backward/Adam update with checkpoint readback, and tail-padding invariance. The test receipt preserves the precise source identity at that time. Afterwards only `run.py` measurement instrumentation changed; `model.py` and `test_baseline.py` did not. The final instrumented CLI then completed all three real fits. This is local execution evidence, not a claim of hosted CI execution.

The original raw summary reports 3/3 completed fits, 96 completed Adam updates, no uncertain optimizer outcome, frozen common interfaces and exact retained-checkpoint prediction equality. An independent NumPy saved-byte review reconstructed all global and per-task CE/accuracy/macro-F1/Brier metrics with maximum error 8.88e-16. It verified all 96 trace rows, 3,584 recorded event positions, 768 training query visits, the exact schedules, checkpoints and stored Adam step counters. That independent review ran no model forward pass; the producer itself performed the checkpoint prediction replay.

The immutable compact receipts are in `evidence/gru7-20261112-8262/`. `ARCHIVE.json` identifies the full archive by content hash, Git blob and member manifest. The archive retains raw per-seed logits, every seven-dimensional hidden-state visit, checkpoints, original DATA/PLAN, source bytes, launch/termination records, tests and independent review. No interrupted training continuation or product recovery claim is made.

## Reproduction

Use the source identities and original factorial input bytes in the retained archive. A compatible CPU PyTorch environment is required; no dependency installation was performed for this experiment. From the repository root:

```bash
python -B -m unittest qualification.hcsn_budget_baselines.test_baseline -v
python -B -m qualification.hcsn_budget_baselines.run \
  --factorial-output /path/to/original-factorial-inputs \
  --output /path/to/new-empty-gru-output
```

Output directories must be new. Every episode starts from a fresh zero GRU state. This runner deliberately accepts only the retained three-seed, 32-update pilot plan, so a broader experiment needs its own declared configuration and evidence identity.

No usable local `ncps`/CfC or official S4/Mamba installation was found in the bounded dependency search. This package does not substitute a self-written approximation for those requested strong baselines. Real asynchronous sources, matched occupancy, a tuned baseline suite, adequate training, independent confirmation, full numerical qualification and product adoption remain separate requirements.
