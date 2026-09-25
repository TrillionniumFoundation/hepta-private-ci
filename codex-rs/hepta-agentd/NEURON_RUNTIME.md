# Agentd durable Neuron product composition

The existing `AgentdIntelligenceProductRunnerV1` now calls a shared
`AgentdNeuronOwner`, not `sparse_tick` over request-authored drive/prediction
vectors. The canonical Intelligence port, inference-control adapter, Neuron
journal/result store and run-start owner remain the existing owners.

## Host construction and lifetime

Construct/recover `NeuronRuntime` with its full immutable config, native profile,
journal, operation file and independent witness. Construct `AgentdNeuronOwner`
with a concrete `NeuronInferenceControlPort`, then consume it with
`into_shared(selected_admission)` to obtain `AgentdNeuronHandleV1`. The mandatory
selected-admission implementation checks authenticated current model selection,
calibration/OOD and source revocation; there is no permissive default guard.
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
