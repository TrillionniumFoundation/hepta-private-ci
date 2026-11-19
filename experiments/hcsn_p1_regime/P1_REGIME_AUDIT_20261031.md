# HCSN P1 exogenous evolving risk: matched CPU negative control

2026-10-31. **RESEARCH_ONLY / DENY_ALL / NO_GO**. New isolated namespace; no edits to any historical negative result, production path, Rust host, CI, numerical HX financial kernel, or existing PR. Stacked on **Draft #4531 exact HEAD `042af0017b08f4316949cf9ba450ecd5e63350b3`**, which is based on **Draft #4527 exact HEAD `039c31aea3d0b359f602367b27d41662f8f75caf`**; protected `main` at review `732e934ba496d90fbe042b8d41d479ef901643e5`.

## New scientific fact and limits

Prior #4527 proved normalized `(Call/K, Put/K, log(V/b))` is rank at most one in `(V,K)` and is blind to common scale; #4531 restored contextual coordinate rank with `log K` and first-hit `Q(T)` but found no independent new information, since `Q(T)` is a deterministic invertible transform of observed `T` where conditioned.

This trial introduces an **independently evolving two-state stochastic volatility regime**: initial state `z0` independent of positive log-distance `m`, absolute scale `log K`, and horizon `T`. At each of 12 physical subintervals, `z` can switch according to an explicit Markov transition. Brownian increments and a conditional Brownian bridge determine the first-passage binary outcome. An OOD panel changes both horizons and switching parameters. **Both learned arms observe the same `(m, log K, log T, z0)`**. The analytic features are deterministic transformations, not new data. Real exogenous risk *exists* in the synthetic environment, but there is **no mechanism-exclusive independent information**.

Two equal-architecture 7-input/609-trainable-parameter MLP arms: ordinary uses smooth calibrated functions of m, mechanism uses normalized perpetual Call/Put, safety margin and *constant-regime* first-hit risk proxy. Both include identical absolute-scale `log K`, `log T` and regime `z0`; all first four channels have the same value `0.35` and signed derivative `+1` with respect to m at `m=0.35`, verified across both regimes and ten horizons. Frozen `PROTOCOL_20261031.json` was committed **before** primary training, with 8 paired seeds, training set size 3,072, IID and OOD 768 each, 2.0 seconds actual **process CPU** per arm including arm feature preprocessing, separate same-process per-seed runtime bootstrap exclusion, equal random model initialization and minibatch stream. The total-cost comparison is not complete: common task data generation, energy, storage, GPU and Rust are not measured as whole-system resources.

## Real execution and negative result

Environment Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0 and PyTorch 2.10.0 CPU. Eight targeted structural/unit tests passed; independent verifier recomputed all **24,576** paired ID/OOD per-example predictions from raw probabilities and labels and independently verified all 8 immutable per-seed SHA-256 receipts. Three corruption controls confirmed rejection of a tampered receipt, a second write to an existing output, and a forged significance result.

| Endpoint | Observation |
| --- | --- |
| OOD Brier improvement, ordinary minus mechanism | **+0.0020675812440314** |
| IID Brier improvement | **+0.0002192259551514** |
| Paired exact two-sided sign-flip p (8 seeds) | **0.609375** |
| Actual train+feature process CPU range across 16 arms | **2.000053106–2.001188992 seconds** |
| Model trainable parameters | 609 each |
| Precommitted exploratory screen | **FAIL**, not >0.01 and not p<=0.05 |
| New independent information | **NO** — features deterministic in strong-baseline inputs |
| Original financial HX / real training quality / full cost / GPU / Joules | **NOT SHOWN** |

The eight per-seed OOD differences, exact p value and receipt SHA identities are committed in `MARKOV_PAIRED_SUMMARY_20261031.json`. The full 8-seed raw JSON (all labels, predictions, CPU timings, training update counts and model-state digests), gzip+base64 raw byte stream and logs are preserved in the companion user-delivered evidence archive. **Raw uncompressed JSON SHA256:** `44f00dcaae4ef6ddc40e590614c60ece807dc5146cc9e4f612a183b26ce7df53`. Protocol JSON SHA256: `49c7cf2a2acaa17a91414571b6b1781a72e9a41c2831802efcb409663a1dafc1`. No raw outcome or failure was altered to make the screen pass.

Two attempted serial full runs failed to seal final receipts before session timeouts (the first reached six seed summaries, the second seven); their partial textual logs are retained, **not included as completed runs**, and not silently labeled successful. The create-only process-per-seed runner was committed before the successful full eight-pair run. The parallel version independently measures per-worker process CPU (not a shared global wall clock), seals each seed atomically and rejects incomplete/tampered final panels. Results across reruns can vary slightly because CPU-time budgets govern the number of optimizer updates.

### Seven-stage ledger (new user mapping)

- **P0 OPEN**: original coupled HX debt/equity free-boundary obstacle, whole-domain error/interval, FP32/BF16 and implicit gradients, regeneration QVI.
- **P1 OPEN**: historical #4517 negative 192-trainings, #4527 normalized rank-1/common-scale blind spot, #4531 no new information, this 8-seed evolving-risk negative pilot. No independent causal Call/Put/Margin gain or real-task transfer.
- **P2 OPEN**: Selective Copy/MQAR, irregular physical FIRE and full native crash recovery.
- **P3 OPEN**: actual text/speech/vision/video Encoders.
- **P4 OPEN**: temporal alignment/entity consistency/missing modality/cross-modal retrieval.
- **P5 OPEN**: fusion/CDF/sparse scheduling/actual 64–4096 Cell CPU+GPU RSS/p95/p99/Joules/recovery.
- **P6 BLOCKED**: medium Encoder distillation, continued pretraining, long-context equal-budget quality-cost frontier.

Historical P4=hardware corresponds to current P5; historical P5=scaling corresponds to current P6. The current independent P4 multimodal alignment gate is retained. Nothing enables production, no thresholds reduced, and no scientific blocker is declared closed.
