# P2 exact-model Brownian sampled FIRE stream and checkpoint oracle — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Additive research; requires parent P0 independent QVI PR #4494 and P0/P2 finite-horizon expected-count PR #4492. No production route, neural model or historic evidence changed.

`renewal_spike_sampler.py` samples **physical spike times** under the *scalar, fixed-parameter* Brownian model `dX=mu dt+sigma dW` and fixed threshold `b`. For positive drift, first-hit time follows the inverse-Gaussian law. For negative drift, the hit is defective with probability `exp(2 mu d/sigma^2)` and, conditional on hitting, follows the positive-|mu| inverse-Gaussian law. At zero drift the Lévy first-hit law applies. A FIRE is immediate if initial `x>=b`; otherwise the first arrival is sampled. After each FIRE it resets to `r<b`, waits deterministic refractory `tau`, and samples the next independent first hit. These are **drawn event times**, not expected flux or a neuron with time-varying input.

A versioned canonical JSON checkpoint includes model parameters, stream ID, deterministic SplitMix64 counter state, causal clock, number of emitted spikes and the **pending pre-sampled event**. A digest checks accidental corruption, but is **not cryptographic authorization**. An `advance_to(deadline)` operation is transactionally staged, so event budget failure does not partially change state. Split deadlines and a new Python subprocess restored from the checkpoint reproduce the same event train and final checkpoint on the tested host. No claim is made about arbitrary host failure/atomic filesystem durability, cross-platform transcendental bitwise reproducibility, concurrent stream ownership or adversarially authenticated snapshots.

## Executed locally

Python 3.13.5 / SciPy 1.17.0:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_renewal_spike_sampler
```

**6/6 test methods PASS**, zero skips. Four independent 10,000-stream Monte Carlo groups (40,000 streams total), using a separately coded positive two-normal-tail finite-horizon series, give:

| Drift | 10,000-stream sampled discounted count | Analytic expected discounted count | Sample SE |
| ---: | ---: | ---: | ---: |
| -0.35 | 0.72237816 | 0.72827368 | 0.00793748 |
| 0 | 1.08959884 | 1.09203489 | 0.00910160 |
| 0.35 | 1.51567530 | 1.53117937 | 0.00971411 |
| 1.0 | 2.39343817 | 2.39292878 | 0.00920702 |

Each absolute discrepancy lies within the prespecified `5*SE + 0.005` acceptance tolerance. Additional tests: immediate spike at time zero; negative-drift defective absorption; no refractory; positive event-time ordering; same prefix under split deadlines; new-process restoration and exact checkpoint equality; transaction rollback after event cap; tampered or mismatched snapshots; malformed parameters and extreme numeric scales.

Source-seal expected blob SHA: sampler `df65b3b2a167e544b45e0f480a57fbe7a09d725b` (8288 UTF-8 bytes), tests `a7a6085d93368d7fefde4044008b536e6d898359` (6457 bytes). These are exact local tested byte identities, to be checked after remote publication.

## Open gates

This **does not** solve neural Selective Copy, MQAR, key overwrite, heldout sequence length, irregular changing drift/threshold, true content modalities, optimized native Rust/GPU, energy, persistent owner-ledger atomicity, or P1 matched mechanism superiority. The sampler adds a distinct physical-event reference and restart behavior; it is not a live production neuron and does not settle optimal stopping in financial HX. `production_activation=false`; all P0–P5 scientific blockers remain open.
