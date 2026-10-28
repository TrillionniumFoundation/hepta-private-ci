# Native qualification: ownership and production boundaries

This draft implements a bounded native conversation and reuses real runtime
jobs. It does **not** install a native production session owner in Agentd.
The production interfaces below already exist; the missing work is their
composition with this loop, not the invention of another authority service.
Source links pin the reviewed #2963 base to
`88a43bece9428b091479712b4c29084720d87123`; they do not claim a later branch audit.

## What owns the implemented path

| Boundary | Implemented owner and meaning |
| --- | --- |
| Thread, turn, root operation and generation | The embedding host supplies `TurnBinding`; the loop consumes the external `TurnOwner` through `verify_current`, `checkpoint`, `admit_model` and `admit_tool`. The model never allocates these identities. |
| Qualification identity and checkpoints | `runner/src/owner.rs` supplies `SessionOwner`, with deterministic fixture identities, fixed generation 1, immutable admissions and private single-writer snapshots. This is an isolated experiment owner. |
| Context and pending work | The loop updates `TurnState`; the host must durably commit checkpoints before acknowledging them. Model request bytes, provider response ID and compiled tool request remain tied to their original operation. |
| Physical tools and jobs | `runtime_bridge` calls the existing `hepta-runtime` jobs owner. Start, original-request observation, cancellation, terminal publication and retained output use that owner; the agent adds no second physical-jobs registry. |
| Codex comparison sessions | Official Codex owns its actual thread/turn IDs. The driver correlates each original call with a qualification helper session; those identities are not interchangeable. |
| Canonical execution projection | `canonical_runtime_intent_v1` validates and projects correlation into execution-core. It does not mint a checked handle, signed grant, lease or dispatch permission. |

The core contract is in [state.rs](../../codex-rs/hepta-native-agent/src/state.rs).
See [CONTRACT_CONVERGENCE.md](CONTRACT_CONVERGENCE.md) for the projection seam.
An admission is a persisted request, `Accepted` is a nonterminal observation,
and only validated original terminal evidence permits tool completion. Receipt
projection retains `AuthorityPosture::DENY_ALL`; an outcome grants no new effect.

## Existing production owners and the unimplemented composition

| Existing source / interface | Existing responsibility | Gap in this draft |
| --- | --- | --- |
| [AgentdState][state]: `refresh_generation`, `current_generation`, `mark_fenced` | Reloads `FleetRegistry`, checks the Agent's roots/resources and lifecycle generation, closes admission and fences runs. Current lifecycle generation is distinct from process spawn generation. | No native `TurnOwner` is wired to this live Agentd/Fleet fence or its readiness and drain state. Fixed fixture generation is not a substitute. |
| [AgentRunCoordinator][lane]: `start_run`, `attach_context`, `mark_dispatched`, `cancel_run`, `observe_terminal`, `recover_indeterminate` | Owns run revisions, context attachment, deadlines and the admitted/dispatched/cancelling/indeterminate/terminal transitions. | Native root/child operations are not composed with the daemon's sole coordinator. This in-memory coordinator alone is not durable storage for a native pending model/tool checkpoint. |
| [ThreadStore][store]: `create_thread`, `resume_thread`, `append_items`, `persist_thread`, `load_history` | Storage-neutral thread persistence and recovery, including deletion fencing. | Native session creation and checkpoint/history representation are not mapped into the existing thread store. |
| [LiveThread][live]: `create`, `resume`, `append_items`, `persist`, `flush`, `shutdown` | Active-thread persistence lifecycle over the selected `ThreadStore`, including initialization cleanup. | The runner's private snapshot directory has not been replaced by this production lifecycle or a reviewed compatible native checkpoint representation. |
| [QueueStore][queue]: client-binding reserve/finalize, dispatch lock, claim/authorize/recover/complete | Durable ordered user input, payload/client identity and leased cross-process dispatch. Unsupported implementations reject the relevant operations. | JSON-lines fixture commands do not implement this queue contract or bind its leased dispatch to a native turn. |
| [History recovery records][history]: `TurnRecoveryRequestBinding`, `TurnRecoveryHistoryBoundary`, `TurnRecoveryReplayV1` | Bind a recovery generation to the exact semantic request, history prefix, context and replay-critical environment data. Missing boundary/replay data does not grant recovery authority. | Native exact-body/provider-response recovery has not been mapped to those records or qualified for existing persisted threads. |
| [AgentdProductionWriterHost][writer]: `open_with_recovery`, `attach_target`, `dispatch_to_with_grant_provider`, `reconcile` | Reuses an independently recovered writer/lease, requests an exact external signed FinalUse grant, dispatches to registered destinations, and reconciles by observation only. | Native model POST and runtime process entry are not composed with the production model/runtime targets, exact grant binding, current verifier and physical-entry checks. Qualification admission is not that composition. |
| [Agentd runtime startup][runtime] | Attaches production operations to the recovered writer, supervises the reconciler, generation monitor, App Server and AuthBus relay. | No native service replaces the `codex-app-server` startup task, readiness gate or drain accounting in this draft. |
| [AuthBus dispatch][authbus] | Revalidates trust/generation and relays into the existing `thread/queue/reconcile` path; uncertain redelivery uses the same client/payload identity with `ReconcileOnly`. | Native qualification ingress is not an alternate production delivery authority. A native composition must preserve that queue/reconciliation contract. |

`AgentdProductionOperationRuntimeConfig::attach` checks that operations use the
same recovered writer authority, lease ID and generation. Its external
`AgentdFinalUseGrantProvider` supplies a grant for the exact `FinalUseBinding`;
the host does not acquire signing authority from a native request. Multiple
destinations must be explicitly registered and named. Composing both model and
runtime targets must retain this separation and observer-only reconciliation.

### Concrete persistence and model-entry gaps

The reviewed local thread writer calls `record_canonical_items` followed by
`RolloutRecorder::flush`; `write_pending_once` calls `File::flush`, with no
`sync_data` or `sync_all` barrier in that recorder. A successful flush is not
evidence that a native pending-effect checkpoint survives power loss. Any
required durable barrier belongs inside this existing writer, including first
file creation, rather than in a second snapshot writer. See [live writer][live-writer]
and [recorder][recorder].

`load_rollout_items` counts malformed rows, but `get_rollout_history` discards
that count as `_parse_errors`. Native pending-effect recovery must use an
explicit strict path that rejects malformed or truncated checkpoint input and
validates the original identity, generation and checkpoint sequence; silently
falling back to an older valid checkpoint could redispatch an uncertain effect.
The tolerant ordinary-history loader does not establish that recovery property.

In this draft, [engine.rs](../../codex-rs/hepta-native-agent/src/engine.rs) accepts
the concrete `ResponsesModel`; after owner admission and checkpointing it calls
[ResponsesModel::open](../../codex-rs/hepta-native-agent/src/responses.rs), which
sends the HTTP POST. `ModelRequest` carries an operation ID and exact bytes, not
a checked FinalUse handle. Replacing `SessionOwner` alone therefore cannot
install the production check at model dispatch. A checked model transport/port
must compose that physical entry with the existing writer and FinalUse owner;
consuming a grant earlier in `admit_model` is insufficient across later awaits.

## Why SessionOwner is not promoted to production authority

The fixture's manifest, file permissions, OS lock and checkpoint hash chain
protect local experimental consistency. They do not authenticate a production
principal, establish a current Fleet generation, reserve an existing queued
submission, validate a live lease, or consume a destination-bound FinalUse grant.
Its fixed generation 1 cannot demonstrate generation rollover or replacement of
a daemon owner. Its three compiled read-only operations cannot demonstrate a
general command policy; the underlying qualification runtime uses operator mode.

Replacing these missing compositions with a permissive `verify_current`, a new
local grant ledger, or a synthetic signed capability would create competing
authority. This draft leaves the production entry path uninstalled. The real
jobs owner is reused and can be qualified independently of that missing wiring.
The loop's rechecks after asynchronous checkpoints are necessary, but a fixture
implementation of those checks is not evidence of live Fleet/FinalUse enforcement.

## Gates before a production native cutover

These are outstanding integration gates, not claims that the draft passes them.

1. **One session/run owner composition.** Supply the current Agentd/Fleet binding,
   existing thread lifecycle and queue dispatch lease to the native loop; map
   run/turn/child-operation identities and revisions without opening a second
   writer or allocating a replacement operation after an ambiguous response.
2. **Durable history and recovery mapping.** Persist the native pending state,
   exact model body, original provider response ID and compiled process request
   through the selected production owners. Validate old-thread resume, queue
   redelivery, corruption rejection and recovery-generation consumption.
3. **Checked model and runtime entry.** Attach the appropriate existing production
   targets and external grant provider; bind destination, payload, deadline,
   lease and generation. Revalidate currentness/revocation at the physical entry
   after waits and checkpoints. Qualification records and the converter cannot
   satisfy this gate.
4. **Original-operation fault evidence.** Inject crashes/lost acknowledgements
   around admission, dispatch and terminal publication under those owners. An
   unknown model outcome remains pending without another POST; an unknown tool
   outcome is observed under the same original request/job, never restarted to
   discover whether it ran. Provider response observation must be supported by
   the actual production model target; the live qualification gateway does not
   currently proxy retained-response GET recovery.
5. **Agentd service lifecycle and ingress.** Wire readiness, fencing, drain,
   cancellation, AuthBus queue reconciliation and supervisor shutdown to the
   native service; prove that an expired/revoked generation cannot perform new
   effects and that unresolved original work remains observable after restart.
6. **Cutover evidence for the chosen scope.** Pass same-model task/failure checks
   for the intended production tools and existing sessions. The three-operation
   benchmark and its helper-crash tests establish only their recorded scope.

[state]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-agentd/src/state.rs
[lane]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-agentd/src/lane_b_runtime.rs
[writer]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-agentd/src/production_writer_host.rs
[runtime]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-agentd/src/runtime.rs
[authbus]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-agentd/src/authbus_dispatch.rs
[store]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/thread-store/src/store.rs
[queue]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/thread-store/src/queue_store.rs
[live]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/thread-store/src/live_thread.rs
[history]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/history/src/lib.rs
[live-writer]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/thread-store/src/local/live_writer.rs
[recorder]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/rollout/src/recorder.rs
