# HCSN P0–P5 consolidated gate ledger — 2026-10-31

**Research-only, fail closed**. The results below are from the current additive research stack, *not* an entire upstream repository checkout. Historic failed experiments are retained; nothing grants production permission.

## Exact code/evidence ancestry

- Existing P0 corrected maturity-tail / high-precision reference: draft [#4498](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4498). Original erroneous 112-ish stop upper bound **retracted**, corrected finite-grid high-liquidity observed STOP upper roughly 103–105.
- Independent PDE and financial obstacle: draft [#4499](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4499). A coarse 101-node PDE audit **missed** extra STOP detected by independent first-hit quadrature. No continuum certification.
- P1 eight-arm pilot: draft [#4500](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4500). 80 trainings, 8 arms × 2 tasks × 5 seeds; 561 active parameters per arm; all 14 Holm-adjusted P=1; OOD all-three Copy ~59.43% vs ordinary ~83.80%, retained negative.
- P2 event/content pilot: this stack; 6 trainings, 2 tasks × 3 seeds, 400 updates each; trainable event-content model + physical Brownian sampled renewal. Copy ID ~99.87%, T32 ~95.05%; four-key MQAR ID ~63.83%, T32 ~62.60%. Exact six-record raw JSON is committed under `experiments/hcsn_p2_memory/P2_PILOT_RESULTS_20261031.json`, SHA-256 `262156070654bb782c21724345132e20e4361f8eb020dee0f53021c53806ceaa`.

## Local combined regression / experimental evidence

On local Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, PyTorch 2.10.0+cpu, **50/50 targeted unittest methods passed**, 0 failed, 0 skipped: 39 P0 reconstructed finance/precision/grid/reference methods, 5 P1 pilot contract methods, 6 P2 actual sampled-event/learned-content/cold-process replay methods. The P0 modules are a reconstructed HX subset, **not** a byte-identical full repository checkout. Exact sampled-event original source blob `df65b3b2a167e544b45e0f480a57fbe7a09d725b` was copied byte-identically for the local P2 tests; new P1/P2 source and test blobs were each Git-readback-matched to the locally executed bytes. This is NOT a claim of successful whole-repository CI, Rust or GPU tests.

A successful unit test, a local finite-grid Bellman residual, or a scalar restoration is **not** a scientific closure certificate.

## Main acceptance table (no unmeasured values invented)

| Stage | Primary evidence from this research stack | Most important still-unclosed blocker | Status |
| --- | --- | --- | --- |
| P0 original HX / scalar / regenerative QVI | Corrected surviving-principal maturity tail, independent finite-maturity PDE, high precision first-hit reference, exact finite-grid certificate, genuine CPU bond FP32/BF16 screens and locally passing bounded tests | Self-consistent **globally admissible** financial obstacle and all-domain/continuum error certification; financial equity full low-precision / implicit active-set derivative | **OPEN** |
| P1 Call/Risk/Margin cause | Eight-arm same-input, local signed-slope, 561-parameter, 80-run Copy/last-write pilot; no significant positives, material negative all-three Copy | True task-endogenous trained HCSN dynamic channels and independent confirmed same-budget benefit vs tuned ordinary gates/SSM/Transformer | **OPEN** |
| P2 continuous event + memory | Genuine sampled Brownian multi-FIRE, trainable content GRU, irregular times, overwrite/MQAR4, transactional composite snapshot, new-process bitwise recovery; 6 actual training jobs | Per-FIRE-timestamp content dynamics, reliable MQAR/long-context accuracy, trainable shared model and native durable journal/crash recovery | **OPEN** |
| P3 four-modal Encoder | Previous constrained audio/visual features and small tasks; no new four-modal evidence in this turn | Real text/image/audio/video paired encoder training, heldout cross-modal alignment and noise robustness | **OPEN** |
| P4 Rust/GPU | Historical native owner/process tests, local CPU PyTorch research; no GPU available here | Fully native Rust/GPU kernel; 64/256/1024/4096 Cells throughput, RSS, p95/p99, transfer, real energy and host recovery | **OPEN** |
| P5 hybrid expansion | Negative/equivocal P1 and deficient P2 MQAR controls retained | Preregistered equal data/token/FLOPs/energy/time and superior heldout quality **before** scale up | **BLOCKED** |

**Hardware evidence:** this local environment has no CUDA device or Rust compiler/Cargo. Measured Joules, GPU throughput, and 4096-cell native p99 are **unavailable**, not zero. No genuine four-modal dataset or pretrained encoder comparison was run in this turn.

**Hard invariant:** `production_activation=false`; `all_scientific_blockers_closed=false`; P5 never promoted on a local or underpowered pilot. Keep stacked PRs as drafts and do not squash away the failed grids, weak memory results or negative mechanism arms.

## Next decision-critical implementation

1. P0: solve the self-consistent financial equity/bond obstacle *with* endogeneity, and prove global admissible-domain + tail, rounding and gradient bounds; preserve the 101-node PDE disagreement as a fail-closed test.
2. P1: design an actually trainable endogenous HX-like Call/Risk/Margin neural operator and compare to optimized ordinary gates, full information/signed slopes/active parameters/**measured total costs**, fresh blind seeds and sufficient statistical power.
3. P2: apply event operator at **each physical FIRE time** before irregular observations; improve four-key MQAR and show matched ordinary-control benefit; stage model checkpoint into a durable owner with crash/restart semantics.
4. P3/P4: only after certified inputs and access to genuine datasets and native GPU hardware, execute four-modal and 64–4096-cell performance experiments.
5. P5: block capacity expansion until a robust prespecified quality–total-cost benefit is independently confirmed.
