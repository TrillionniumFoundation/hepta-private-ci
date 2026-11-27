# HCSN P1–P5 continuation: proposed gates, not an executed experiment

Status: `DESIGN_ONLY_NOT_PREREGISTERED`. No previously observed datasets or
negative results can be relabeled as fresh confirmatory evidence. The immutable
seed/data split and executable source SHA must be registered **before** the next
confirmatory sample or hyperparameter search. This document is an admission
contract, not permission to deploy.

## P1: Mechanism identification rather than feature-name attribution

- Neural latent coordinate is a versioned positive transform V(z), separate
  from financial asset value. HX equity E(V), maturity default probability
  F(V), and rollover margin d(V,T)-p/T are numeric *features*, not normative
  neuronal utilities. Risk also includes a testable 1-F complement. Reject
  undefined, zero-derivative and negative-equity regions; count every rejection.
- Compare individually **Call**, **Risk**, **Margin**, each pair, triple,
  separately fitted two-gate ordinary MLP, fixed-threshold LIF, and a
  no-renewal control. For any one-vs-one comparison, enforce identical base
  input/readout/head, trainable active-parameter count (no padding), optimizer,
  seeds, token streams and checkpoint selection rule. Report unequal FLOPs and
  complete worker wall/CPU even if training CPU budgets are matched.
- Local-slope matching: at a training-only anchor z0 choose frozen affine
  calibrations alpha+beta*channel(V(z)); match value and signed d/dz to the
  ordinary gate, independently of holdout labels. Treat near-zero derivatives,
  sign flips, multiple anchors and clipping as prespecified robustness tests.
  Do not call different slope magnitudes a causal mechanism effect.
- Register paired ≥10 independent fresh seeds per task, untouched OOD panel,
  exact model/data/protocol digests and a four-contrast Holm family; primary
  metric is *held-out complete task utility net of resource/latency cost*,
  secondary metrics include accuracy, loss, event counts, calibration, ECE,
  NLL, throughput and gradients. The effect gate must beat zero with adjusted
  two-sided 95% lower confidence bound and a prespecified practical threshold.
  Pilot synthetic tasks, already-observed MNIST/FSDD, and prior 0/4 outcomes
  remain exploration, not reused confirmation.

## P2: Real time, repeated impulses and bounded memory

- Bind continuous event state (pressure distribution, active/refractory phases,
  residual hazard, pending inputs, RNG if stochastic, reset law, clock, stream
  ID, causal event ledger) to a versioned checkpoint and replay hash.
- Test Selective Copy and MQAR at train-disjoint lengths; overwrite with
  conflicting keys, delayed multi-hit retrieval, irregular time deltas,
  multiple regeneration cycles, simultaneous-event tie rules, zero-duration
  input and adversarial long gaps. Separate expected-event flux from physical
  sampled spike trains. Include a true continuous-event likelihood baseline.
- No future-suffix leakage: identical input prefixes produce identical
  bitwise physical transitions under a fixed finite generator and numerical
  profile; for moving boundaries use tolerance/mesh studies rather than falsely
  demanding a semigroup identity under remapping.

## P3: Truly paired multimodal inputs

- Require distinct versioned text, image, audio and video encoders; verify
  source modality and aligned entity/time labels (not just digit-class proxy).
- Tasks: cross-modal retrieval, missing-modal completion, temporal grounding,
  noise and OOD robustness, entity swap and pairing shuffles. Compare an
  independently optimized fusion Transformer and a no-HX hybrid backbone with
  identical source encoders, labels and loss exposure; report recall@K, mAP,
  calibration, latency and actual resource measurements.

## P4: Native Rust/GPU gates before any performance claim

- Rust single-owner state and GPU-native kernels must preserve generator
  positivity, probability mass, event reward conservation, zero-time boundary
  firing, refractory eligibility, deterministic retry and generation fencing.
- Independent f64 SciPy oracle and actual f32/bf16/f16 kernels are compared at
  boundaries, stiff drift/sigma/discount limits, timing branch changes,
  repeated spikes and independent hardware; report absolute/relative errors,
  gradient residuals and fallback/rejection rate.
- Freeze hardware/driver/toolchain/data and run 64/256/1024/4096 Cells with
  p50/p95/p99 per-event and per-sequence latency, throughput, RSS/VRAM,
  CPU/GPU utilization, energy and recovery time; charge preparation, transfer,
  backward, compilation, empty batches and failed attempts, not just a cached
  inner matrix multiply.

## P5: Gate expansion on *net* benefit, not favorable toy evidence

- On new untouched tasks, compare equal data, tokens, updates, active params,
  GPU-hour and full measured inference/training budgets versus tuned ordinary
  gates, tuned LIF, a Transformer/SSM, and a no-HX hybrid. Include single-channel
  and recurrence/no-regularization controls.
- Require repeated seed-positive adjusted confidence bounds for net utility,
  controlled negative transfer, stable calibration, no new authority/safety
  regressions, and an end-to-end compute advantage before changing model scale.
  Until then keep the HX oracle behind offline feature/research interfaces.

## Existing registered negative evidence remains binding

The parent HCSN distributional-v2 draft reports 0/4 mechanism wins, 0/6 ID
content proximity screens, and its selected complete Adam CPU step costing
18.12x an ordinary dual gate. Neither the current independent P0 reference
nor a lucky exploratory seed can reverse those outcomes. Explicit new frozen
confirmatory protocols and genuinely new paired data are mandatory.
