# P2 physical-timestamp FIRE content audit — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Stacked on #4501 exact head `0898cac14d8e8edf575a667a849d92e6264fb48d`. Protocol `TIMED_FIRE_PROTOCOL_20261031.json` was committed first at `a775ec8c645585ddb7c9486a089cc608b08cee3c`, **before** the complete 256-actor confirmation run. The 64-actor development probe predates the frozen protocol and is not advertised as blind confirmation. No production, Rust host, original P0/P1/P2 negative evidence or CI workflow is changed.

## Scientific question and implementation

Earlier #4501 `TrainableEventContent.step` applied one `tanh(count)*event(h)` transform **at each observation**, collapsing all prior sampled Brownian FIRE events in the interval. The new `timed_fire_content.py` instead propagates the same trainable float32 hidden state continuously to each *actual* sampled Brownian FIRE time and applies exactly one learnable event operator **at each FIRE**, propagates through the remaining gap, and finally applies the observation GRU write. This retains the original externally sampled `SpikeStream` RNG and physical time law unchanged, and is **not** claiming differentiable Brownian event-time sampling or an optimal task-value trigger.

Session checkpoints include exact model-weight hash, SPIKE snapshot, causal observation time, total FIRE count, chained hex-timestamp event digest, content vector and logit. Ingest is in-process transactional: invalid event cap, bad timestamps, malformed observation, invalid model or nonfinite state do not commit either the event stream or neural state. No host disk WAL, crash-consistent journal, signing, native Rust or CUDA.

## Executed focused local tests

`python -m unittest -v experiments.hcsn_p2_memory.test_timed_fire_content` -> **6/6 methods PASS**, zero skips, Python 3.13.5 / NumPy / PyTorch 2.10.0+cpu. The inherited `event_content.py` and `renewal_spike_sampler.py` were the matching published Git blobs `d180a30b790f516406ff36891e2c5350f8b81973` and `df65b3b2a167e544b45e0f480a57fbe7a09d725b`, respectively. Source and test Git blob identities were checked after uploading.

The tests cover: different timestamps with identical FIRE counts really change content; gradients reach event and decay parameters; bitwise entire session vs partition-and-restore; actual new Python process with saved model and model-bound snapshot; invalid event budgets/time/checksum/model/stream fail without state mutation; bad event order/horizon rejected.

## Frozen-weight paired confirmation — **negative migration result**

**This is NOT equal-budget retraining.** Both arms have **exactly the same frozen 400-step seed-0 weights trained only on the older aggregate-count operator**; weights regenerate from existing `train_pilot`, and mismatch against the frozen model digest refuses. The same actor observation packets, stream ID/seed, full sampled Brownian event timestamps and query labels are used for both modes. Each dataset has 256 actors. No scores are deleted. Timing is single-threaded resident process CPU and wall including model inference + sampled FIRE stream/transaction, excluding training and model initialization.

| Task / test length | Queries | Aggregate accuracy | Timestamp accuracy | Difference | CPU aggregate / timestamp |
| --- | ---: | ---: | ---: | ---: | ---: |
| Copy T16 ID | 256 | 100.00% | 96.875% | -3.125 pp | 1.295s / 1.581s |
| Copy T32 OOD | 256 | 90.625% | 84.375% | -6.250 pp | 2.827s / 3.498s |
| MQAR4 T16 ID | 1024 | 62.598% | 57.324% | -5.273 pp | 1.309s / 1.592s |
| MQAR4 T32 OOD | 1024 | 63.867% | 56.934% | -6.934 pp | 2.861s / 3.479s |

The physical FIRE trains match exactly between arms; paired query action disagreements: 8 / 16 / 222 / 281, respectively. 4 groups cover **1,024 actors and 2,560 queried predictions** (2×256 + 2×1024). All 256 streams per group contain at least two FIREs. Event counts: 3016 / 5755 / 2946 / 5839.

**Interpretation:** The physically timestamped operator is functionally non-equivalent and has an actual CPU penalty under the inherited frozen model. Because the model was trained only for *aggregate-count* updates, these results are a **migration/regression warning**, not a scientific claim that newly *trained* physical FIRE networks are necessarily inferior. No statistical population generalization or favorable P2 mechanism inference follows from this single frozen seed.

Lossless measured data: `CONFIRM_256_TIMED_FROZEN_20261031.json`, SHA-256 `6f2590cbd9179efeff7dfab36e9fffdfe18f0141e033f1ab8e6348c59727dac4`.

## Reproduction

From repository root with the published P2 source and CPU Torch/SciPy:

```bash
python -m unittest -v experiments.hcsn_p2_memory.test_timed_fire_content
python -m experiments.hcsn_p2_memory.frozen_timed_inference_audit \
  --regenerate --actors 256 --output /tmp/confirm_256_timed.json
```

CPU/wall seconds vary by host; deterministic actor labels, event counts, model digests and prediction outcomes are the replay-critical fields. Strict SHA256 of the raw JSON includes machine-dependent timing, so do not expect byte-identical wall/CPU fields across hosts.

## P0–P5 scientific blockers — unchanged

- **P0 OPEN:** Financial self-consistent free-boundary equilibrium, rigorous continuum/interval tolerance, full financial active-set and low-precision GPU proof; #4499 discrete certificate does not imply continuous HX viability.
- **P1 OPEN:** Existing #4500 matched pilot has no multiplicity-adjusted positive causal Call/Risk/Margin effect; retain all negative results.
- **P2 OPEN:** Train the timed operator from scratch with same information and **equal measured cost**, true overwrite/retrieval controls, long/OOD lengths, independently signed durable restart journal; no claim of memory superiority yet.
- **P3 OPEN:** Separate actual four-modal encoders, true paired retrieval/temporal alignment and OOD.
- **P4 OPEN:** Native Rust/GPU kernel; 64/256/1024/4096 Cell CPU/GPU/RSS/p95/p99/Joules and failure/recovery.
- **P5 BLOCKED:** Only scale if fixed protocols establish quality-and-cost-matched superiority against tuned ordinary gates/SSM/Transformer.

`production_activation=false`, `all_scientific_blockers_closed=false`; keep this branch/PR draft and unmerged until independent scientific review.
