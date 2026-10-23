# Production NeuronRuntime integration contract

## Status and evidence boundary

This document records open blocker **E03** and the minimum concrete integration work.
It does not report a completed production port, deploy a service, or promote a registry entry.
The v3 experiment is frozen at `9653b066563df803b6f18c0045c49b9f73312c50`.
This read-only source inventory used checkout `9edc598080e43aa706a20a2dc5101099a1bd3052` on 2026-10-23.
All code paths below are relative to the repository root; symbols identify the exact contract.
The existing evidence in `evidence/review_confirmation.json` establishes executed research
native action/budget/sealing behavior, not an authenticated production model invocation.
`evidence/review_source_control.json` establishes finite source-policy correctness only.

## Existing composition and the missing calls

| Layer | Source and exact symbols | Observed boundary |
|---|---|---|
| Agentd owner | `codex-rs/hepta-agentd/src/neuron_runtime.rs`: `AgentdNeuronOwner::new`, `AgentdNeuronOwner::tick` | Owns runtime and inference-control port; construction alone does not activate daemon startup. |
| Feature adapter | `codex-rs/hepta-neuron/src/inference_control.rs`: `InferenceControlModelPort::execute`, `NeuronInferenceControlPort::execute_feature` | Builds the exact feature request, invokes the supplied port, verifies receipt, maps observed output. |
| Runtime | `codex-rs/hepta-neuron/src/runtime.rs`: `NeuronRuntime::bootstrap`, `NeuronRuntime::tick`, `NeuronRuntime::recover` | Executes `NeuronModelPort`, validates output, commits Q24 sparse state and checkpoint witness. |
| Worker | `codex-rs/hepta-infer-worker-host/src/model_worker.rs`: `InferenceWorker::run_neuron_features_receipt`, `InferenceWorker::run_neuron_features` | Checks grant, loaded model, reservation/lease payload, cancellation and capacity before invoking driver. |
| Backend | Same worker file: `NeuronFeatureDriver::run_neuron_features`, `DriverNeuronFeatureObservation` | Requires execution of the loaded encoder/head and actual invocation measurements. |
| Typed receipt | `codex-rs/hepta-infer-core/src/neuron_feature.rs`: `build_neuron_feature_receipt_v1`, `verify_neuron_feature_receipt_v1` | Checks canonical request/runtime/output binding; does not authenticate the invocation independently. |
| Persistence | `codex-rs/hepta-neuron/src/witness.rs`: `FileAnchorWitnessStore::open`, `AnchorWitnessStore::compare_and_swap` | Real retained checkpoint-witness implementation exists; deployment must supply its ownership and file lifecycle. |

The implemented owner calls the adapter through `NeuronRuntime::tick` and `NeuronModelPort::execute`.
A concrete `NeuronInferenceControlPort` must connect that adapter to the worker; the table
does not imply this dispatch adapter already exists in the product startup path.
Current source searches found concrete `NeuronInferenceControlPort` implementations in
`codex-rs/hepta-neuron/src/inference_control_tests.rs` (`Control`) and
`codex-rs/hepta-agentd/src/neuron_runtime_tests.rs` (`StubInferenceControl`).
The concrete `NeuronFeatureDriver` found is `Driver` in
`codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs`.
`AgentdNeuronOwner` references found were its definition, export and type-level test;
an actual daemon startup construction and routed tick were not established.
These are scoped source observations, not a claim that every external deployment was inspected.

## The 512-element feature contract and 4,904 raw outputs

`codex-rs/hepta-infer-core/src/neuron_feature.rs` sets `MAX_FEATURES = 512` and bounds
both `feature_vector_q24.len()` and `expected_output_width` in the feature request.
The worker mirrors this with `MAX_NEURON_FEATURES`; runtime input uses `MAX_INPUT_FEATURES`.
Feature values use Q24 with the current magnitude bound `8 * (1 << 24)`.
Runtime state width must additionally match `SparseConfig`; 512 is not a promise that
every vector width is accepted by every layer of the runtime.

The synthetic generator dimensions come from `experiments/multimodal_output_portfolio/world.py::SHAPES`:

| Output | Shape | Scalar elements |
|---|---|---:|
| Text | 4 tokens × 10 vocabulary entries | 40 |
| Audio | 1,024 samples | 1,024 |
| Image | 16 × 16 × 3 | 768 |
| Video | 4 × 16 × 16 × 3 | 3,072 |
| Total | Four raw tensors | **4,904** |

`OutputModel` in `experiments/multimodal_output_portfolio/model.py` uses a 64-wide latent.
A latent/head mapping could fit the feature contract, but its semantics, normalization,
Q24 rounding/saturation and prediction target still require an explicit implementation.
The four raw outputs require a separate bounded artifact/stream contract tied to the
same request, model generation, final latent and terminal emission. Their hashes alone
cannot establish that the driver executed or that an authenticated host observed them.

## Authentication is a separate asset

`codex-rs/hepta-neuron/src/runtime_types.rs::NeuronModelPort` explicitly requires
authenticated underlying invocation and measurements from that invocation.
The feature receipt builder/verifier supplies consistency checks, not a signature,
deployed trust root, resource observation, or authority to perform another effect.
`NeuronRuntime::tick` returns `AuthorityPosture::DENY_ALL` and binds the supplied
`NeuronTickInputV1::ndu_snapshot_digest` into `SparseTick::ndu_digest`; it does not
thereby execute `FeedbackGenerationSessionV1` from `codex-rs/hepta-ndu/src/feedback_generation.rs`.

`codex-rs/hepta-infer-worker-host/src/native_app_server.rs::AppServerModelDriver`
is an existing hosted `turn/start` path with `TurnStartAuthorizer` and `VerifiedUseToken`.
It is not a concrete `NeuronFeatureDriver` for the local latent/encoder/head contract.
`codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs` provides
`UnixFinalUseAuthorizer` and `FinalUseAuthorizerConfig` for that hosted path.
Their presence does not establish a running independent issuer or authorize feature execution.
The applicable boundary must be selected and implemented explicitly for the chosen backend.
`codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md` documents the existing
issuer/peer/key/time/revocation requirements and the limits of mock-provider evidence.

## Implementation stages and concrete completion criteria

### P1. Admit real model assets and define the feature/output mapping

Supply legitimately available encoder/head/weights and preprocessing artifacts, a precise
model manifest, normalization and quantization rules, and the intended runtime/device tuple.
Use `NeuronRuntimeConfigV1`, `NeuronCalibrationProfileV1`, and `NeuronResourceEnvelopeV1`
from `codex-rs/hepta-neuron/src/runtime_types.rs`; retain the corresponding artifact bytes.
Match generation, head, normalization, dimensions and native digest to the actual `SparseConfig`.
Specify how the model's observed features become drive/prediction Q24 vectors and how all
four emitted output artifacts are correlated without exceeding the feature-vector contract.
**Complete when:** a real loader resolves every artifact; independent reference execution
meets declared numerical tolerances; malformed dimensions and mismatched tuples are rejected;
calibration/OOD and latency/memory envelopes derive from retained measurements for that tuple.

### P2. Implement and execute the concrete feature driver

Implement `NeuronFeatureDriver` on a real `ModelDriver` backend using its loaded
`DriverModelHandle`; execute the requested encoder/head rather than returning canned vectors.
Return `DriverNeuronFeatureObservation` with actual output identities, terminal status,
latency, queue age, resident memory and transient allocation from that invocation.
**Complete when:** `InferenceWorker::run_neuron_features_receipt` executes real weights;
independent raw-output comparison passes; failures, cancellation and incomplete terminal
observation retain their correct statuses; changing input/weights causes the expected
execution-derived output change and any stale binding is rejected.

### P3. Bind inference control to an authorized worker

Implement `NeuronInferenceControlPort::execute_feature` as an actual dispatch adapter
to the admitted worker, preserving request/model/generation identity and receipt correlation.
Acquire real owner admission, reservation/lease and applicable grant/cancellation state.
For a boundary requiring the existing final-use mechanism, provision an independently
operated issuer, trusted public configuration, signer custody, socket/peer identity,
trusted time, revocation distribution and retained anti-replay state; the worker holds no issuer key.
**Complete when:** an authorized real request traverses the adapter and driver, while
wrong model/payload/generation, denied or expired/revoked authorization, and cancellation
fail at the relevant boundary before an unauthorized effect. Test grants remain test evidence.

### P4. Connect the real Agentd owner and retained runtime lifecycle

Construct `AgentdNeuronOwner` in an actual daemon startup/service route with the concrete
port, validated runtime configuration, owned journal, and `FileAnchorWitnessStore`.
Use `NeuronRuntime::bootstrap` for new state and the applicable recovery path for retained state.
Make owner readiness, generation, shutdown and cancellation control routed `tick` requests.
**Complete when:** a real Agentd process invokes the feature driver through `tick`;
the observed output is committed to the journal and witness; restart recovers the same
accepted generation/sequence; stale checkpoints, mismatched witnesses and interrupted
dispatches are rejected or remain explicitly indeterminate according to their contract.

### P5. Bind feedback actions to real execution and complete emission

Integrate `FeedbackGenerationSessionV1` with that owner path, retaining current observed
latent identity, action values, budget, action commitment, resulting feedback and output identity.
Each REFINE must invoke the actual neural operation before the next observation; EMIT must
produce all required outputs once and seal the stream. Keep controller, IPC and neural work
separately measurable; the v3 Linear-MAC model is not physical latency or total service cost.
**Complete when:** one reproducible trace connects owner request → native action → executed
neural operation → observed feedback → final four-output artifacts, with exact budget
accounting and rejected stale, over-budget and post-seal operations. A stored NDU digest alone fails this criterion.

### P6. Qualify the intended host and close only the proven scope

Retain source/binary/artifact identifiers, host/runtime identity, authorized request records,
measured resources, actual outputs, journal/witness records and independent replay results.
Exercise the real backend's refusal, cancellation, revocation and recovery boundaries on
the intended host. Record unavailable external services as blockers rather than substitute identities.
**Complete when:** independent acceptance validates P1–P5 on the intended deployment and
the applicable activation/canary/rollback requirements are met. Repository tests or a local
composition using a test authority can close their own integration scope, not target-host qualification.

## Required evidence bundle and current disposition

- Loaded model/encoder/head and manifest bytes; explicit feature/output mapping and Q24 contract.
- Measured calibration/OOD/resource artifacts tied to the exact runtime/device/model generation.
- Concrete driver and dispatch adapter source, binaries, startup configuration and executed traces.
- Applicable independent authorization/trust configuration and refusal/revocation observations.
- Retained raw outputs, journal/checkpoint/witness state and independent end-to-end comparison.
- Separate research-composition and intended-host acceptance records with their actual limitations.

The current v3 artifacts do not contain this complete bundle. E03 therefore remains
`not_implemented`. No nonzero digest, synthetic receipt, self-issued test grant, or canonical
registry declaration closes it. Future implementation should preserve the frozen v3 evidence
and publish a new, explicitly scoped execution receipt rather than relabel the existing bridge.
