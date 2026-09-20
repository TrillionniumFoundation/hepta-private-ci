# Neuron runtime execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness
**Bound modules:** `neuron.runtime`, `intuition.policy`, `learning.ledger`, `learning.eval`, `learning.artifacts`
**Source target:** `codex-rs/hepta-neuron`

## 1. Scope and authority boundary

`neuron.runtime` is a bounded temporal signal engine. It does not represent a biological identity, execute tools, call providers, issue capabilities or replace the selected model or topology during a run. The selected encoder, head, inhibition graph, threshold profile and checkpoint generation are immutable inputs.

The runtime consumes `NeuronRuntimeConfigV1` and `NeuronTickInputV1`, emits `NeuronTickReceiptV1` plus canonical checkpoint and signal receipts, and may accumulate only next-snapshot plasticity sufficient statistics. Model output is advisory and cannot override the objective, authority kernel or reflex veto.

## 2. Runtime state layout

One shard owns state for a bounded set of subject IDs. Per subject, the canonical state is:

```text
generation and logical sequence
encoder/head/runtime tuple digests
bounded temporal state h[d_h] in signed Q24
previous sparse activation a[d_z] or sparse index/value form
adaptive thresholds theta[d_z or groups]
activation moving averages
bounded eligibility summary or exact trace digest
OOD/calibration state
checkpoint predecessor and expiry
```

Pilot bounds are `d_h<=256`, `d_z<=512`, top-k ratio `1%..20%`, modulator dimension `<=8`, state range `[-8,8]`, eligibility norm `<=4` and checkpoint bytes `<=1 MiB`. Raw prompts, credentials, unrestricted media and authority tokens are forbidden state.

## 3. Tick ordering and fixed-point semantics

Every tick executes exactly this order:

```text
validate config, generation, sequence, clock and feature dimensions
verify input/objective/NDU/body digests
update recurrent temporal state with checked wide intermediates
compute pre-competition activation
subtract registered lateral inhibition and thresholds
apply deterministic top-k-positive selection
update activation moving average and bounded homeostatic threshold
update eligibility from registered local pre/post rule
compute prediction error, confidence, OOD and abstention
canonicalize receipt and checkpoint
commit checkpoint and append signal receipt atomically
```

Signed Q24 conversion uses round-to-nearest, ties-to-even. Overflow is rejection; saturation occurs only at named projections and increments a counter. Equal activation is broken by canonical unit ID. Competition is first per registered population, then global. No unbounded convergence loop is allowed.

## 4. Concurrency, clock and checkpoint model

A subject has exactly one checkpoint writer. Routing may shard subjects, but two workers cannot advance the same predecessor revision. The compare-and-swap key is `(subject_id, generation, logical_sequence, checkpoint_digest)`. A duplicate tick with identical semantics returns the committed receipt; a reused tick ID with different semantics is conflict.

`monotonicTimeMicros` must increase within a process generation. A bounded reordering window may buffer observations only when declared; otherwise out-of-order input is rejected. Wall-clock time is evidence metadata, not update order. Generation rollover drains old writers before selecting a new config.

The checkpoint and receipt share one transaction or an outbox-backed atomic boundary. Crash before commit preserves the predecessor. Crash after commit but before acknowledgement is reconciled by tick ID and digest. Partial state mixing is forbidden.

## 5. Failure detection and fallback

Failures include encoder/head/tokenizer mismatch, stale generation, sequence gap, clock regression, dimension drift, state explosion or collapse, all-active or dead-unit collapse, threshold saturation, eligibility overflow, untrusted modulator, OOD false acceptance and attempted current-artifact mutation.

Fallback order is valid temporal checkpoint, stateless selected head, deterministic calibrated rule, then slow-path/abstain. A corrupt checkpoint is quarantined and rebuilt from the last valid checkpoint plus ordered events when replay bounds permit. Rebuild may not consume deleted or revoked rows.

## 6. Security and privacy

Features are purpose- and principal-scoped. Runtime logs expose digests and bounded summaries, not source payloads. The modulator contains only registered low-dimensional outcome, prediction, resource and safety signals. Authority, credentials and secret material are rejected at admission.

Negative tests cover adversarial activation flooding, poisoned feature manifests, model identity drift, checkpoint replay across principals, hidden prompt text, oversized sparse indices and a candidate attempting to select its own weights.

## 7. Performance envelope

The sparse path is bounded by `O(d_h*k_f + |E_I| + k log k)` under registered fan-in and inhibition edges. Pilot signal latency is p95 `<=3 ms`, p99 `<=8 ms`, transient allocation `<=512 KiB`, active checkpoint `<=1 MiB` and checkpoint write amplification `<=4x`. No dense `d_h^2` path is allowed above `d_h=256` without a separate qualification profile.

Backpressure rejects ticks before mutation. A missed optional consolidation window is recorded degradation and does not create an unbounded catch-up queue.

## 8. Lesion, ablation and golden fixtures

`BIO-GV-001` remains the fixed-point tie, inhibition, threshold and eligibility reference. Additional fixtures are:

- `NEU-GV-002`: tick replay after process restart produces the same receipt digest.
- `NEU-GV-003`: two writers race on one predecessor; exactly one commits and the other conflicts.
- `NEU-GV-004`: clock regression and generation mismatch reject before state update.
- `NEU-GV-005`: all-unit activation triggers collapse detection and stateless fallback.
- `NEU-GV-006`: deleted-row replay is excluded and cannot reproduce a revoked checkpoint.

Ablations remove inhibition, homeostasis, eligibility, replay, temporal state or the true modulator. Lesions remove registered units or edges. Evaluation measures utility, stability, calibration, OOD, forgetting and resources; functional-biomimicry claims remain withheld unless the full mechanism beats preregistered ablations on future windows.

## 9. Implementation sequence

Implement config and tick types, scalar fixed-point primitives, checkpoint CAS, deterministic temporal cell, inhibition/top-k, homeostasis, eligibility, calibration/OOD, replay recovery, resource benchmarks and ablation fixtures. Attach a real local model only after exact weights, tokenizer, preprocessor, quantization, license/SBOM, runtime and device manifests are qualified.

## 10. Coding-entry checklist

Coding may start when the three readiness protocols and canonical Neuron protocols are generated, the Q24 profile and tie order are frozen, checkpoint ownership is exclusive, fault injection points are enumerated, benchmark host/profile is named, local-model use has a deterministic fallback, and every package preserves zero current-run parameter or topology mutation.

## Appendix A. Closed gap and protocol mapping

This appendix is a closed-world traceability projection. Each identifier is normative in `READINESS.json`, `PROTOCOLS.json` or `GAPS.json`; this Markdown file does not redefine the registry record.

Protocols:

- `NeuronRuntimeConfigV1`
- `NeuronTickInputV1`
- `NeuronTickReceiptV1`

Closed documentation gaps:

- `RDY-GAP-NEU-001`
- `RDY-GAP-NEU-002`
- `RDY-GAP-NEU-003`
- `RDY-GAP-NEU-004`
- `RDY-GAP-NEU-005`
- `RDY-GAP-NEU-006`

Bound work packages:

- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `BIO-1-ELIGIBILITY-HOMEOSTASIS`
- `DOC-3E-PRECODING-READINESS-CLOSED-WORLD`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `INT-1-CALIBRATED-INTUITION-POLICY`
- `LONG-1-TEMPORAL-HOLDOUT`
- `LONG-2-RETENTION-FORGETTING`
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `LRN-2-CAUSAL-EVALUATION`
- `NEU-1-LOCAL-MODEL-BAKEOFF`
- `NEU-2-TEMPORAL-SIGNAL-RUNTIME`
