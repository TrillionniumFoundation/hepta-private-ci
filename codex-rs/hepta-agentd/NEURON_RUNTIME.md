# Agentd durable Neuron product composition

The existing `AgentdIntelligenceProductRunnerV1` now calls a shared
`AgentdNeuronOwner`, not `sparse_tick` over request-authored drive/prediction
vectors. The canonical Intelligence port, inference-control adapter, Neuron
journal/result store and run-start owner remain the existing owners.

## Host construction and lifetime

Construct/recover `NeuronRuntime` with its full immutable config, native profile,
journal, operation file and independent witness. Construct `AgentdNeuronOwner`
with a concrete `NeuronInferenceControlPort`, then consume it with
`into_selected_shared(artifact_owner, selector, selections, clock)` to obtain
`AgentdNeuronHandleV1` with the concrete `AgentdNeuronArtifactAdmissionV1`.
The lower-level `into_shared(selected_admission)` remains a native adapter hook,
not permission to use a permissive guard. There is no default product guard.
Keep this handle in the existing authoritative invocation-provider lifetime.
Clone the handle, not runtime state. Each `prepare` call binds run identity,
immutable run body context, actual canonical features, NDU result and predecessor.

`AgentdIntelligenceOwnerInputsV1.neuron` accepts only the opaque invocation.
`AgentdOwnerInvocationProviderV1::authoritative_provider` obtains it from the
host's registered Neuron owner. Its run-start validation requires matching run,
body generation and body-context digest. The private erased execution trait is
implemented only for the mutex-protected real owner; input producers cannot
replace it with a caller-authored checkpoint.

## Execution and currentness

At `NeuralSignalCollected`, verify actual objective/NDU/run bindings and invoke
`InferenceControlModelPort` through `NeuronRuntime::tick_guarded`. The stage guard
rereads the existing signed Intelligence owner-frontier file and checks the
selected calibration window, monotonic deadline and cancellation token. The
owner-installed selection guard additionally checks model/calibration/source
truth. Both run at each native admission/publication boundary.

An occupied owner returns bounded Unavailable rather than blocking beyond the
request deadline. Dropping/timing out the async runner cancels fresh admission.
A blocked backend still needs inference-owner physical interruption; aborting a
blocking task alone does not provide that guarantee. An already durable prepared
operation is reconciled once even when current-use delivery is denied.

The actual committed checkpoint replaces the downstream intuition state's
placeholder. A calibrated/OOD-abstaining result does not produce a ready fast
policy; it returns an explicit unavailable stage result. Intuition still owns
its candidate scores, calibration and action selection. No effect is dispatched
by this adapter.

## Qualification boundary

The focused fixtures use real journal/operation/witness files and the real
inference-control receipt adapter, with a deterministic test feature backend.
They test model-time frontier change, OOD rejection, exact result reuse and the
normal signed product preparation path. They do not prove a selected Laya model,
independent calibration, a production daemon deployment or training efficacy.

The shipped CLI still needs a concrete authenticated owner-input factory and
selected feature backend. Configuring a runner or providing this library handle
is not that deployment. V2 durable-state migration and actual base/organ/cell
parameter consumption remain separate implementation work. Retain false
production/activation/independent-acceptance claims until the corresponding
exact-candidate, process and target-host evidence exists.

## Selected model and evidence profile

`neuron_artifact_admission.rs` consumes the existing fenced
`LearningArtifactOwnerHost` and `ArtifactSelectionVerifierV1`; it creates neither
an artifact store nor a signing authority. The native host supplies its shared
publication lock, trusted clock and three independent signed selections from one
current registry head. Time values in this profile use Unix milliseconds.

The model must be a Model artifact whose full V2 manifest digest equals the frozen
`model_manifest_digest`, whose content digest equals `weights_digest`, and whose
generation matches the runtime. Calibration and OOD summaries are Policy artifacts
in separate content-digest domains and declared summary schemas. Their V2 metadata
must be dataset-derived and declare the exact expected payload length. The model's
lineage pins both complete evidence-manifest digests: the same numerical summary
from a different dataset/producer/metadata record cannot silently substitute for
its frozen evidence. Publish evidence manifests before the selected model manifest;
the execution-profile digest deliberately avoids the enclosing manifest hashes.
Every artifact must bind the execution profile, device, normalization and objective. Calibration/OOD artifact revisions are not
silently substituted for the runtime generation encoded in their payloads.

`NeuronRuntimeConfigV1::execution_profile_digest_v1` binds the config/model IDs,
runtime generation, encoder/head/weights/tokenizer/preprocessor/quantization,
runtime/device/normalizer/native-config digests and feature/state/modulator widths.
It deliberately excludes the enclosing manifest and calibration/OOD content hashes
so publication has no circular hash dependency. The operation header still freezes
the complete configuration, including every excluded reference and resource limit.
`calibration_evidence_payload_v1` and `ood_evidence_payload_v1` encode the profile,
calibration generation/window, residual bounds, confidence/OOD/sparsity/projection
limits and measured/maximum ECE and false-acceptance values, in their distinct
versioned domains. Their hashes must equal the configured evidence hashes.

Construction verifies the actual immutable payload bytes and complete manifests.
Each admission then rereads authenticated CURRENT and verifies all three selections,
eligibility and lifetimes before and after those reads under the same owner lock.
Immutable, support-hash-bound metadata is retained after construction; its own expiry
is checked even when a selector signature has a later expiry. This avoids redundant
full-registry reads through each manifest lookup. A live check uses two current views,
not cached authority, while retaining all three exact selection checks at both ends.
Weights and immutable manifests are not reread on every check; the inference owner must still verify
the exact selected execution tuple. A failed refresh closes this installed consumer;
restoring an old file or reversing its clock cannot reopen that handle. Historical
result queries remain non-authorizing and use the existing runtime result store.

Native composition must reopen the artifact owner against its independently retained
current frontier after a restart; this guard is not a substitute for that owner's
anti-rollback trust. Selector-trust changes require installing the new native trust
and rebuilding the selected consumer; this patch does not implement a new selector
revocation transport. Feature/NDU/modulator source currentness and physical backend
cancellation remain the corresponding owner duties. The supplied summary values are
cryptographically bound to selected artifacts, not independently measured by this
adapter. No empirical calibration or Laya execution is inferred from these checks.

The real-owner regression source is `tests/support/neuron_artifact_tests.rs`, in the
existing `terminal_cell_owner` integration test. It covers each artifact's live
revocation, signature corruption, runtime/measurement substitution, missing payload,
exact manifest binding, expiry and clock rollback. Keys and measurements are fixtures,
not deployment credentials or independent efficacy evidence.
