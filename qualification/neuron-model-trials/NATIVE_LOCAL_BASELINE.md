# Owner-local Neuron checkpoint/model binding (non-authorizing)

NeuronRuntime::read_local_checkpoint_binding_v1() reads the actual frozen
NeuronRuntimeConfigV1 and currently committed JournalAnchor, and requires the
separately retained AnchorWitnessStore to acknowledge exactly that checkpoint.
Missing state, unacknowledged commits, and mismatched witness fail closed.

The returned NeuronLocalCheckpointBindingV1 captures the model, encoder, head,
weights, tokenizer, quantization, normalization, calibration, objective/scope,
declared resource envelope and checkpoint, with one recomputable digest and
AuthorityPosture::DENY_ALL. Resource entries are LIMITS, NOT measurements.

A recomputable digest is not a signature. This is only owner-local evidence,
not the actual production no-change. To prove a selected baseline, an
independent runtime/CNS/artifact owner must bind the same generation,
current route and policy, current weight/Artifact CAS, source-use permission,
host identity and final-use fence. The actual current owner must be queried;
calling this API on a fixture or unselected runtime grants no authority.

The Agentd product wrapper now exposes the same read-only operation as
AgentdNeuronOwner::read_local_checkpoint_binding_v1(). This is only a pass-through
to its existing, exclusively owned NeuronRuntime; it does not construct a
replacement model, infer a route, or bypass the Journal/Witness checks.
The Agentd type-check test pins the concrete owner API. The native runtime
tests exercise real checkpoint and witness behavior.

The Agentd product wrapper exposes no mutable reference to the underlying
NeuronRuntime or inference-control port. The old public runtime_mut() and
inference_control_mut() escape hatches were removed: external callers must
enter the bounded InferenceControlModelPort path through tick(), and cannot
inject a raw NeuronModelPort by obtaining the runtime from the wrapper.
This closes a bypass in the wrapper API; the public lower-level NeuronRuntime
and host-supplied trait still require independently authenticated startup
composition, not local-model fixture authorization.

No model is invoked and no state, authority or production route is mutated.
Tests cover initial missing checkpoint, correct local tuple, mutation of
immutable fields, witness regression/false advance and pending post-commit
reconciliation. CI uses the exact branch SHA and the installed Rust toolchain.

Verification: from codex-rs run cargo fmt --package codex-hepta-neuron -- --check;
cargo check --locked -p codex-hepta-neuron --all-targets;
cargo test --locked -p codex-hepta-neuron --lib;
cargo clippy --locked -p codex-hepta-neuron --lib -- -D clippy::correctness.

No result from this entrypoint establishes independent labels, genuine elapsed
future windows, NDU net gain, target-host resource benefit, or promotion.
