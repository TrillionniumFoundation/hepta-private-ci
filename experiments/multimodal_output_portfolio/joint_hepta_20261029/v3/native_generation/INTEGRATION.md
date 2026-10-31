# Target-owner integration boundary

## What this change executes

The native executable performs the selected small generator's complete forward
computation, content recurrence, trained actor/critics, media decoding, prefix
commit and state recovery. `qualify.py` verifies selected checkpoint weights
against original Torch and executes native streamed content. This closes a
specific implementation gap: the content computation now runs in Rust.

The runtime is an additive Linux research owner. **Adoption into the existing
Agentd / inference-control / neuron-owner chain remains unimplemented.** No
production owner, serialized V1 type, permission or default backend is changed.
Wrapping the executable in the existing research `NativeGuard` would still
leave that guard's original diagnostic head in the model port; it would not
complete the target-owner integration below.

## Exact inspected owner baseline

These source files were fetched through the GitHub connector at
`a50c8974ac23c20c5174f7c3ad542a96e5652854`, the original native guard's source pin.
The research starting head is `7db3b8347080326ded0cba037fc770df76c94a6a`.

| Path | Git blob | Existing call or contract |
| --- | --- | --- |
| `codex-rs/hepta-agentd/src/neuron_runtime.rs` | `3e880ef975af2b7210a7466b9fb4e12f62937d9c` | `AgentdNeuronOwner::tick` constructs `InferenceControlModelPort` and calls `NeuronRuntime::tick` |
| `codex-rs/hepta-neuron/src/inference_control.rs` | `8a85a1e433f29b1354b4ee3c73f27b85a1842b31` | `NeuronInferenceControlPort::execute_feature` consumes `NeuronFeatureRequestV1`; the adapter verifies its receipt |
| `codex-rs/hepta-neuron/src/runtime.rs` | `d483e00a69756339254124a633eb4fdcd05664d7` | `tick` calls `model.execute`, then unconditionally forms `SparseTick` and calls `SparseJournal::commit` |
| `codex-rs/hepta-neuron/src/runtime_types.rs` | `d15b3a4f8be07c35d1884f660b6a20d494c8e5e4` | `NeuronModelRequestV1` carries bounded Q24 features; output carries drive/prediction vectors and model/resource receipts |
| `codex-rs/hepta-infer-worker-host/src/model_worker.rs` | `26ee6559a9de6baf5846ea367d02e5ffb01a40d6` | `InferenceWorker::run_neuron_features` admits the reservation, calls `NeuronFeatureDriver`, checks resources, and projects the execution receipt |

Source links: [Agentd owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a50c8974ac23c20c5174f7c3ad542a96e5652854/codex-rs/hepta-agentd/src/neuron_runtime.rs),
[runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a50c8974ac23c20c5174f7c3ad542a96e5652854/codex-rs/hepta-neuron/src/runtime.rs),
[model types](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a50c8974ac23c20c5174f7c3ad542a96e5652854/codex-rs/hepta-neuron/src/runtime_types.rs),
[worker](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a50c8974ac23c20c5174f7c3ad542a96e5652854/codex-rs/hepta-infer-worker-host/src/model_worker.rs).

## Why a driver-only adapter is insufficient

The original `NeuronModelPort` can execute a real model and return a projected
drive/prediction. Its request contains no full generation predecessor,
per-modality cursor, already committed prefix or output delta. The owner then
commits the fixed sparse-kernel state. A model driver that privately commits
generation bytes before that owner commit would create two durability owners
and an observable failure window. A rejected/abstaining owner could follow an
already emitted output. A driver that only returns a content digest would
instead omit the actual state/decoder adoption.

The existing feature driver is useful for stateless feature computation. The
durable generation lifecycle requires a distinct registered version and an
explicit state-backend dispatch point at the owner. Existing V1 bytes must
retain their meaning.

## Minimal additive integration design

Names in this section are design records, **not implemented exported APIs**.

1. Add a disabled-by-default `JointGenerationV3` backend profile beside the
   existing sparse profile. Its manifest binds this tensor inventory, numeric
   profile, content-state format, sampler, clocks, complete legal actions,
   decoder format and prefix-commit semantics. Old sparse configurations keep
   their current behavior.
2. Add a versioned inference-control generation request/receipt. The request
   binds owner scope/generation, model/input identity, exact predecessor,
   immutable committed-prefix frontier, remaining resources and the proposed
   legal action. The receipt contains an actual computed successor proposal,
   proposed uncommitted output delta, measured cost, runtime identity and
   explicit terminal/disposition fields. No receipt grants execution authority.
3. Reuse the existing worker reservation/resource/identity admission before
   dispatching `Model::encode`, `Model::advance`, `Model::inspect` or decoding.
   The worker computes candidates; it must not publish externally visible
   prefixes or mutate the authoritative owner checkpoint from inside inference.
4. Extend the existing neuron owner's state-backend dispatch to prepare the V3
   successor and atomically commit the generation checkpoint, prefix delta and
   output outbox under one writer/CAS. Use independently retained owner witness
   semantics for recovery. The local research packet journal is a reference for
   required content, not a second production store to bolt onto V1.
5. Deliver an already committed outbox chunk by exact semantic operation ID.
   Record transport acknowledgment separately; retries reuse the same bytes and
   operation ID. Reconcile uncertain commit/delivery before selecting another
   output action. A live speaker/player cannot erase an already delivered prefix.
6. Bind planner/student behavior and critic profile to the registered model
   bundle. Keep source masks, targets used only for supervised/outcome scoring,
   and owner authorization outside approximate tensors. Aggregate generation,
   planning, validation, codec, queue, persistence and transport costs once.

The smallest reviewable production patch is the new disabled versioned contract
and an owner-path integration fixture. Subsequent patches add actual backend
dispatch and atomic state/outbox adoption. This requires inspecting the current
production module/manifest registries, owner serialization and target build;
the current task's selected source checkout has only the research subtree.
No full production workspace compilation or existing-owner V3 integration test
was run here. This is a concrete unclosed integration item, not a request for
further authorization.

## Required target-chain evidence

An integration run must enter through the actual Agentd owner, execute these
selected trained weights through the inference-control worker, and return
content/state bytes attributable to that invocation. It must cover a nontrivial
content update, actual trained action decision, partial delivery, a later
content revision, STOP and a new-owner-process restore. Numerical comparison
uses the original independent Torch model. No constant diagnostic head may
stand in for that content route.

Faults must include worker failure before owner commit, owner crash after state
commit before transport acknowledgment, acknowledgment loss, cancellation,
expired reservation, changed model/input generation and whole-suffix loss with
an independent retained head. Committed output must remain byte-identical;
uncommitted content may evolve. Existing hard constraints remain enforced by
the owner, and the model/receipt retains `DENY_ALL`.

## Streamed consistency and learning

This native profile preserves early committed bytes and can generate later
chunks from a later recurrent state. The resulting final portfolio can contain
parts from several content revisions. Its truthful evaluation must score that
actual reconstructed portfolio, not a newly sampled final-state bundle.

The current actor was trained on buffered final delivery and has no committed
prefix features. Prefix persistence therefore does not prove learned streaming
coherence, successful synchronization under partial feedback, or optimal
portfolio allocation. Training the policy on prefix-aware states and actual
incremental delivery is a separate remaining experiment. The current output
unit clocks are explicit, but there is no live network/audio/video transport
or observed external consumption acknowledgment in this backend.

An independent review confirmed that semantic replay checks actual regenerated
state/chunk bytes and that expected-head admission rejects stale writers. It
also confirmed the witness boundary: a shortened but self-consistent chain is
accepted by ordinary load/status without a supplied retained head. The tests
provide that caller witness; no automatic, separately durable witness service
has been implemented. The review was scoped to these source contracts, not a
general adversarial-filesystem or hardware power-loss audit.
