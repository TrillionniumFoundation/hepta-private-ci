# HCSN research blocker ledger — 2026-10-30 (review-only)

**Authority: DENY_ALL. No neural runtime activation, main merge, release, or model scaling permission.**
This is a source-bound ledger of separate research claims, not a production
qualification receipt. Retain every frozen failed gate and raw prediction.
Do not silently pool already-observed heldout examples or replace checkpoints.

## Provenance

- Base, original HCSN financial/encoder study: [PR #4330](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4330), recorded HEAD b1934022821f3fdafd509b43cf0c4d7d45852e6e.
- Task/observation/finite-flow study: [PR #4367](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4367), original pinned head 8fc9bfcf5fc21a95facf36790e2d7f1463c7d04b.
- Independently stacked conservative acceleration campaign: [PR #4362](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4362). Hosted [70-job run 41059620366](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41059620366) succeeded at scientific execution seal 78b98ed8dd66294a3de6abce2fa0bbbd2c24f8d5, but PR head advanced and scientific gates remain negative.
- This checkpoint safety increment: [PR #4371](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4371), source test head fadc944d780f8bfb86f7bc3e3b1982214133d852; focused [18/18 integration checks](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41067715431).

These are distinct stacked branches with different experimental populations and
software versions. A successful workflow on one SHA cannot certify a newer SHA.

## Blocking gates (not all closed)

| Gate | Evidence so far | Remaining accepted completion condition |
| --- | --- | --- |
| G0 Precision/recovery | V2 opt-in guarded checkpoint passes 18/18 hosted; original FP64 finite time-flow checked | Migrate supported callers off unsafe loader without mutating historical baselines; test cold process restoration at FP32, FP64, mixed-dtype denial and actual model execution; close original 11/135 strict mass-ridge replay only by independently rerunning a prospectively frozen precision contract, not replacing failures |
| G1 Financial operator domain | Complete A7/Eq.8/Eq.12 checked; 24/712 candidate boundaries have negative local equity; two do not exist | Specify economically/neuronally admissible parameter domain, positive continuation, global stopping conditions and gradients; no assertion that matched boundary implies global optimality |
| G2 Continuous coupled dynamics | Frozen-coefficient finite FP64 process passes 28/28; two-phase Erlang refractory and reset | Verify spatial convergence, FP32 error budget, arbitrary input/schedule stability and an actual coupled continuous-time equation, preserving observation versus gap causality |
| G3 Endogenous control | Scalar regenerative QVI and owner decisions exist; task value v1 loses and v2 benefit interval includes zero | Task-level feasible-action QVI with calibrated future input/cost model; newly frozen heldout, lower bound >0 against identical-information ordinary policy, include full control/owner cost |
| G4 Selective memory | Bounded residual write improves overwrite but worsens long retention/interference/capacity; 0/8 financial-specific gates pass | Retention + overwrite + capacity + interference improve conjunctively under matched state, training/compute and unseen challenge; causal ablation separates financial template from generic gates |
| G5 Fair dynamic Head/backbone | Frozen encoder and synthetic comparisons have no stable net gain; hybrid retrieval overhead high | Compare against tuned GRU/CfC/ALIF/LIF/Mamba/optimized Transformer, with matched quality, state and full training/inference resource costs; positive effects survive multiple seeds, contexts and independent tasks |
| G6 Full multimodal scaling | Small offline audio/image/text probes and tiny backbone runs only | Real joint audio/video/image/text data with end-to-end backbone training, heldout modality/OOD tasks, GPU kernel, p95/p99 RSS/VRAM, energy or power receipts and multi-scale trend |

## Hard separation of outcomes

1. **Mathematical validity:** an analytic formula, QVI, or finite semigroup obeys
   the equations it explicitly declares. This is not learned task utility.
2. **Numerical validity:** actual dtype, spatial/time step, Jacobian, saved
   state, replay and reference comparisons meet frozen tolerances; a different
   discretization is a different claim.
3. **Empirical superiority:** independent training seeds, unseen tasks and
   exact compute receipts show a matched practical gain with a valid uncertainty
   interval. A local gain without cost/quality parity is insufficient.
4. **Production qualification:** separate owner/Final-use/CAS/CNS/Evidence
   gates, target hardware performance, independent authorization and fail
   closed recovery. Nothing in the HCSN research branches grants it.

Only mark a row closed when exact-head, independent, end-to-end evidence for its
acceptance condition is linked. Do not relax old gates or overwrite past
receipts. The new V2 checksum catches accidental changes, not an adversarial
checkpoint author; cryptographic source custody remains separate.
