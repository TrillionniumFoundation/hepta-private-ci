# Adaptive reference and conformance implementation specification

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Specification:** `ALG-REFERENCE-CONFORMANCE`  
**Bound modules:** `objective.compiler`, `utility.ndu`, `neuron.runtime`, `intuition.policy`, `prompt.registry`, `prompt.optimizer`, `context.compiler`, `learning.ledger`, `learning.operator`, `learning.eval`, `learning.artifacts`, `learning.plasticity`, `intelligence.control`, `control.engineering`  
**Documentation state:** `closed`  
**Implementation state:** not implied

## 1. Scope, ownership and non-claims

This specification supplies the cross-cutting reference, reproducibility and conformance rules shared by every adaptive module. It prevents a mathematically detailed design from remaining ambiguous at language, serialization, randomness, fault, performance or evidence boundaries.

Each domain owner implements its own reference functions and fixtures. `platform.types` owns shared primitive semantics; `kernel.evidence` stores qualification evidence but does not issue promotion; adaptive modules cannot redefine fixed-point, digest, random-stream or error semantics locally. Documentation conformance does not establish runtime efficacy.

## 2. Symbols, dimensions, units and normalization

All public adaptive values are represented by registered typed protocols. IDs are canonical lowercase hexadecimal or validated opaque IDs. Time fields distinguish UTC observation time, monotone process time and logical episode sequence. Durations use integer microseconds. Probabilities and normalized utilities use signed or unsigned fixed-point with an explicit scale. Dimensions, units, feature order and missing-value masks are digest-bound.

Canonical fixed-point conversion is round-to-nearest, ties-to-even. Overflow is an error; saturation occurs only through an explicitly named projection whose counter is emitted. Negative zero is forbidden. Arrays have maximum count and encoded bytes. Maps use canonical key ordering. Unknown critical fields fail decoding.

## 3. Formal model and invariants

A conforming adaptive computation is a pure deterministic kernel surrounded by bounded adapters:

```text
validated immutable inputs
-> deterministic reference or generation-bound candidate kernel
-> validated typed output
-> append-only persistence/outbox
-> independent observation/evaluation
```

The following invariants apply globally:

1. exact objective, state, artifact, model/runtime and candidate-set revisions are inputs;
2. current-run artifacts are immutable;
3. hard constraints are neither learned nor approximated;
4. every stochastic operation has a counter-based stream identity;
5. durable outputs have canonical encoding and semantic digest;
6. retries with the same identity reproduce the same semantic output or report conflict;
7. all queues, payloads, loops, retries and resource consumption are bounded;
8. correction, deletion and revocation propagate through lineage;
9. a fixture, source file, green unit test or offline loss is not a production/efficacy claim;
10. independent decisions cannot be produced by the evaluated writer.

## 4. Deterministic reference algorithm

Each algorithm specification provides a scalar or tabular reference implementation using integer/fixed-point arithmetic where practical. The common runner:

```text
load fixture manifest and exact implementation/runtime tuple
verify every input digest, dimension, unit and bound
initialize counter-based random streams from fixture seed digest
execute reference kernel in canonical event/candidate order
encode output canonically and compute semantic digest
compare exact fields and declared numeric tolerances
repeat after process restart and after reordered parallel scheduling
emit ConformanceReceiptV1
```

Golden vectors are versioned, immutable and include success, boundary, rejection and rollback cases. A candidate implementation may use SIMD, GPU or floating point internally only when it produces outputs within the registered tolerance and remains deterministic under the declared device/runtime profile.

## 5. Trainable or estimated algorithm

Training conformance freezes dataset snapshot, split manifest, preprocessing, optimizer, precision, device/runtime, code digest and counter-based random-stream namespace. Parallel worker count may change only when the algorithm declares deterministic reduction semantics or the manifest explicitly scopes an allowed tolerance.

Every trainer emits learning curves, early-stop decision, gradient/update norms, non-finite counters, resource use and final artifact digest. A reproduced artifact may be bit-identical or tolerance-equivalent according to the qualification profile; the mode is declared before execution. Hyperparameter search records the complete evaluated set, not only the winner.

The reference baseline remains present in evaluation. The simplest sufficient learner rule requires a complex candidate to show bounded improvement after resource, risk, calibration and retention costs.

## 6. Data, protocol and lineage schema

The following records are canonical cross-module protocols registered in `docs/contracts/CONTRACTS.json` and `docs/contracts/PROTOCOL_SCHEMAS.json`; unregistered names in prose have no protocol authority.

```text
GoldenFixtureManifestV1 {
  fixture_id, algorithm_id, schema_versions,
  input_digests, expected_output_digest,
  exact_fields, tolerance_fields, rejection_class,
  seed_digest, runtime_profile, predecessor
}

ConformanceReceiptV1 {
  fixture_id, source_commit, source_tree,
  implementation_digest, runtime_tuple_digest,
  observed_output_digest, exact_comparisons,
  tolerance_comparisons, resource_metrics,
  restart_replay_result, decision
}

RandomStreamManifestV1 {
  root_seed_digest, algorithm_namespace,
  episode_id, decision_id, stream_id,
  counter_range, generator_id, generator_version
}

AlgorithmFaultReceiptV1 {
  algorithm_id, fixture_id, fault_point,
  predecessor_state_digest, observed_state_digest,
  recovery_result, rollback_result, decision
}
```

Lineage covers source commit/tree, schema, fixture, dataset, training code, runtime, artifact, evaluation and selected snapshot. Test fixtures contain synthetic or approved data only. A fixture derived from private data inherits deletion and retention requirements.

## 7. Numerical stability, complexity and resource bounds

Each specification declares dimensions, asymptotic complexity and measured envelopes. Common required metrics are p50/p95/p99 latency, throughput, CPU/GPU time, resident and peak memory, allocation bytes, queue depth/age, storage growth, file descriptors, sockets, model/token cost and recovery time.

Numeric diagnostics include maximum norm, minimum denominator, projection/saturation count, condition estimate, residual decomposition, underflow/overflow/non-finite count and tolerance budget. Error budgets use named additive or conservative components; an unmeasured component blocks the claim.

Benchmark fixtures cover minimum, nominal, maximum, contention, cold start, dependency degradation and process recovery. The reference host, compiler, flags, device, thread count and thermal/power policy are recorded. Relative improvements without an absolute safety/resource floor are insufficient.

## 8. Failure detection, fallback and rollback

The common outcome taxonomy is `rejected`, `unavailable`, `timed_out`, `conflict`, `cancelled`, `indeterminate`, `quarantined`, `failed_terminal` and `applied`. Queue acceptance is never terminal effect success. Timeout after an effect boundary is indeterminate unless a trusted acknowledgement proves terminal state.

Adaptive kernels fail closed on unknown schema, stale revision, non-finite value, artifact incompatibility, unsupported domain, certificate failure or integrity mismatch. A fallback cannot widen authority, candidate set or resource/risk budget. Every selected artifact names a tested predecessor. Rollback includes process kill, reload, store reopen, acknowledgement loss and backup/restore where applicable.

## 9. Security, authority, privacy and unlearning

Reference and test runners default to no production credentials or external effects. Untrusted text remains data. Logs and receipts contain safe IDs, bounded metrics and digests, not raw secrets, unrestricted prompts or private payloads. Model/runtime identity includes weights, tokenizer, preprocessor, quantization, template, tool schema, license/SBOM and device.

Authority checks occur immediately before effect adapters and consume operation/final-payload-bound grants. Adaptive algorithms never mint their consumed authority. Unlearning fixtures verify that correction/deletion propagates to caches, indexes, replay, datasets, checkpoints, sensor cores when derived, artifacts and restored backups.

## 10. Verification, golden vectors and property tests

Every adaptive package must include:

- schema round-trip, unknown-field and maximum-bound tests;
- deterministic golden vectors and independent oracle comparisons;
- property tests for boundedness, idempotency, revision monotonicity and no hard-axis mutation;
- metamorphic tests for ordering, batching and irrelevant metadata;
- fault injection at validation, transaction, outbox, acknowledgement, reload and rollback boundaries;
- exact-source and synthetic-merge execution;
- clean-worktree and generated-file drift checks;
- future-time, subgroup, OOD, retention and unlearning tests when adaptive behavior is claimed.

The same implementation may not generate the sole oracle for its test. For critical numeric kernels, at least one independent scalar/tabular implementation or analytic fixture is required.

## 11. Quantitative acceptance gates

| Gate | Requirement |
|---|---|
| Canonical encode/decode | exact round trip for all golden vectors |
| Unknown critical field | `100%` rejected |
| Non-finite durable value | `0` accepted |
| Deterministic replay | exact or preregistered tolerance on `100%` fixtures |
| Idempotent retry | identical semantic digest |
| Unbounded queue/retry/allocation | `0` paths |
| Hard-axis mutation | `0` |
| Fixture/oracle independence | present for every critical kernel |
| Mandatory fault rows | `100%` pass |
| Exact source execution | pass |
| Synthetic merge execution | pass |
| Rollback predecessor reload | pass |
| Unlearning restore resurrection | `0` |
| Capability claim advanced by docs | `0` |
| Positive authority flag in docs | `0` |

Package-specific thresholds in the NDU, Bellman, causal, biomimicry and iteration specifications are cumulative with these gates.

## 12. Paper traceability and Hepta extensions

`PAPER_TRACEABILITY.json` binds every used paper statement to one identified source artifact, an exact abstract sentence locator, a claim-specific SHA-256 and an explicit statement-only scope. The three SSRN working papers are locked to normalized publisher abstract bodies; no inaccessible PDF or access-denied HTML body is treated as paper bytes. `PAPER-HOLDER-Q-2026` is additionally locked to the immutable PMLR repository commit, Git blob, raw PDF SHA-256, byte count and page count. An abstract statement cannot be promoted into a theorem, equation, implementation guarantee or runtime result; theorem-level use requires a separately registered full-text artifact and assumption-to-certificate map.

Fixed-point durability, sensor geometry, monotone/positive reconstruction, near-greedy residual gating, counter-based reproducibility, typed authority separation, causal outcome ownership, exact Git identity, synthetic merge verification, rollback, unlearning and claim ladders are Hepta conformance extensions. They must not be attributed to the papers. Hostile conformance fixtures reject missing digests, altered source bytes, challenge-page substitution, missing locators, claim-text substitution, source-artifact substitution, abstract-to-theorem escalation and Hepta-extension attribution.

The shared conformance suite binds the immutable paper records `PAPER-NDU-FOUNDATIONS-2024`, `PAPER-NDU-UPA-2025`, `PAPER-NDU-EU-2025`, and `PAPER-HOLDER-Q-2026`. These identifiers select only their registered claim anchors and non-claims in `PAPER_TRACEABILITY.json`; none advances a runtime, efficacy, biomimicry, autonomy, selection, promotion, or release claim.

## 13. Implementation sequence and completion rule

Implementation order is shared numeric primitives → canonical protocols → random-stream manifest → scalar/tabular references → golden fixtures → fault runner → resource benchmark runner → trainer reproducibility → artifact reload/rollback → future-time and unlearning suites → exact source/merge receipts.

Documentation closure requires all six algorithm specifications, their registry, paper traceability, generated status, index links and CI verifier to agree. It does not imply any source module is materialized or that any capability claim passes. Capability advancement requires the evidence ladder in `docs/evidence/CLAIMS.json` and independent decisions.
