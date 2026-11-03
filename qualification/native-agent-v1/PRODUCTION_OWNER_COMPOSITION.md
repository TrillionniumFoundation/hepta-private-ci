# Native execution under the original production owners

This candidate continues private-ci #4151 and runtime #75 from
`2277a2f0f2e23d96f688a78d455ab2c6c926d7ee`. The historical
[ownership boundary report](OWNERSHIP_BOUNDARIES.md) describes that base; its
isolated, fixed-generation qualification `SessionOwner` is not promoted into
production authority by this change.

**Scope:** explicit embedded Agentd composition, original Core/Queue/ThreadStore
ownership, original production-writer entry, and bounded native model/process
adapters. Ordinary CLI bootstrap and production cutover remain separate gates.
Validation results must name the tested source and the actual test scope.

## One owner for each production fact

| Fact | Existing owner used by this candidate | Main implementation |
| --- | --- | --- |
| Agent, workspace, lifecycle and current generation | `AgentdState` and `FleetRegistry`; spawn generation is distinct from current lifecycle generation and writer-lease generation | `hepta-agentd/native_state.rs`, `hepta-fleet/lifecycle_fence.rs` |
| Signed Objective and canonical preparation | Existing AuthBus ingress, seven canonical owners, original run coordinator and `DurableRunStartJournal` | `objective_runtime.rs`, `canonical_prepared*.rs`, `hepta-learning-ledger/run_prepared.rs` |
| User input, client identity and ordered dispatch | Original `QueueStore`, SQLite queue, dispatch process lock and claim/CAS | `ext/queue/service.rs` |
| Logical thread and turn | Original Core active-turn reservation, exact attached task/epoch, and typed recovery records | `core/hosted_turn*.rs`, `core/hosted_turn_entry.rs`, `core/session/hosted_*.rs` |
| History and native pending state | Selected `ThreadStore` and `LiveThread`; original writer epoch, strict history reader and checkpoint hash-chain/CAS | `thread-store/local/native_history.rs`, `native_checkpoint.rs` |
| Effect admission, single use and unknown outcome | Same recovered `ProductionDurableWriter`, original operation ledger/outbox and retained lifecycle fence | `hepta-memory/production_effect_entry.rs`, `production_operation_resolver.rs` |
| FinalUse grant | Explicit external `AgentdFinalUseGrantProvider`; both native destinations select one named, already registered authority and share its revocation and consumed-nonce state | `hepta-agentd/production_writer_host.rs` |
| Model POST and retained-response GET | Registered Responses target; exact original request/body/response identity | `native_model_target.rs`, `hepta-native-agent/responses_entry.rs` |
| Physical process and its retained output | Existing hepta-runtime job owner and original request key | `native_runtime_target.rs`, `native_process_compiler.rs` |

The native adapters add no parallel user queue, authorization journal, outbox,
physical-job registry, or grant issuer. `ProductionUnusedScope` is a temporary,
nonserializable observation under the existing writer's exclusive lifecycle
fence. The history reader's bounded set of seen turn IDs exists only during a
read; it is not a registry or an authority source.

`AgentdNativeRuntimeConfig.final_use_authority_destination` names an existing
production destination. The dispatcher derives both native targets by cloning
that destination's existing authority handle; native configuration accepts no
replacement `FinalUseAuthority`. An empty or unknown name fails before runtime
configuration, host health checks or durable-store preparation. Selection is
explicit and does not depend on registry ordering.

## Fresh execution and physical entry

The canonical path retains the original signed Objective, seven-owner result,
selected material and context/compilation receipts. Complete preparation is
sealed into the existing run-start journal before the original Queue relay.
Replaying a durable Prepared record revalidates its owners and the signed
input; it does not run the seven stages again or mint replacement receipts.
A RunStart-only record cannot be treated as completed preparation.

The original Queue owns its process lock and dispatch claim while Core reserves
the logical turn. Core persists the exact typed provenance and original input.
The host commits the first native checkpoint through the original live thread.
Core acknowledges that persistence, the same Queue completes its claim, and
the execution task waits for that completion before any native effect.

Native effects use complete original operation intents. The same writer
prepares the operation and outbox identity together. An external provider signs
the exact destination-bound FinalUse binding. Preparation durably claims the
original operation as indeterminate but retains its signed grant without
claiming a FinalUse nonce. The token, current run, lease,
deadline, cancellation, policy, AuthBus state and Fleet generation are checked
at the concrete HTTP/process entry after earlier awaits. A non-cloneable entry
and its observation receipt refer to one original operation only.

Fresh hosted execution must carry Core's opaque original-task handle. Its
`active_turn` and `start_admission_gate` locks enclose the synchronous Agentd,
Fleet, writer and FinalUse callback. The callback claims and enters the exact
grant only after those original owners agree. Missing, replaced, cancelled,
unconfirmed or busy Core ownership refuses entry; there is no fallback to the
independent Agentd entry. A successful callback is ordered before a later Core
abort or shutdown; it does not establish asynchronous destination completion.

An owner rejection before the callback leaves the nonce unclaimed, while the
original claimed operation remains indeterminate and cannot be resent. Once
FinalUse claiming starts, an expiry, uncertain durable claim or subsequent
entry-phase failure can retain the nonce. There is no nonce refund or new
operation identity on failure. The existing public `AgentdNativeHost::run_turn`
remains an explicit independent Agentd-owned live entry; it is not the hosted
entry or an error fallback.

An entered transport failure or lost acknowledgement remains indeterminate.
The model path retains the exact POST body and original provider response ID;
observation uses the original response query. The process path retains the
compiled request and original runtime job. An admission, local entry, timeout,
or transport error is not destination terminal evidence.

The Fleet fence coordinates physical entry with the existing lifecycle CAS.
Temporary contention is `LifecycleBusy`, not proof of a failed process.
Supervisor retains the already-owned start, release, rollback or observed-exit
intent and retries that transition without respawning or signalling a consumed
process identity. The stable lock inode contains no generation or grant data.

## Recovery is divided by the original durable boundary

| Original durable state | Candidate behavior | Remaining restriction |
| --- | --- | --- |
| Prepared journal exists; queued input has not started | Replay the same signed client/payload through the original Queue | No original cancellation/closed fact; current owners, generation, deadline and AuthBus must still agree |
| Original cancellation/closed fact and exact signed queued input | Observe the existing Queue admission and immutable original publication receipt | ReconcileOnly cannot create a missing input or restore fresh preparation; original stop facts remain authoritative |
| Core provenance exists; no first native checkpoint | Reserve the same logical turn, verify retained provenance/configuration, restore original preparation using the same writer's unused-scope proof | Any original operation in that scope, including an older generation, holds this path |
| Provenance exists but original user input is wholly absent | Append that input through the original Core API in the same turn, then flush and verify exact readback | Partial, duplicated, reordered or conflicting input is held |
| Exact first checkpoint exists, with no original operation | Reuse the original persisted Queue completion and Core turn; verify the pristine canonical state and same writer unused-scope proof before rearming | Any admitted operation, changed head/configuration, cancellation, revocation or stale generation holds continuation |
| Complete checkpoint chain ends at a next-step boundary | Fold every transition against the complete original operation/outbox/event/claim frontier, then rearm the same run | Every operation must be Committed with its original terminal event and last claim Settled; missing raw output or uncovered operations hold continuation |
| Pending original model/process effect | Observe the same request, response ID or runtime job; accept only validated terminal evidence | Unknown outcomes are never retried with a new identity |
| Technical executor/observer failure | Publish the error and retain the unfinished logical turn; release the live task fence after persistence cleanup | A new queued input cannot cross that unfinished tail |
| Actual Core cancellation | Preserve original cancellation and terminal semantics | Cancellation cannot be relabelled as fresh preparation |
| Cold writer/Fleet relaunch | Bind the recovered writer to the full original Agentd identity and immutable lease attachment; observe older work under its original identity | A new Fleet launch counter does not manufacture a new writer lease or fresh permission for an old generation |

New-turn admission reads the original durable tail under Core's idle
reservation lock. A held tail returns a definite refusal so the next Queue row
and input remain intact and the original dispatch lock can be released.
Same-turn recovery has its own entry and remains available.

The strict history reader validates each logical turn independently, including
completed predecessors' typed recovery successors. It supports a legitimate
Core cancellation before the first TurnStarted without granting recovery to
that unstarted turn. It rejects cross-turn markers, missing bindings, changed
fingerprints/routes, wrong generations, duplicate terminals and reused logical
IDs. Each line is bounded to 16 MiB. Identity bookkeeping is bounded to 262,144
unique turns and 16 MiB of ID bytes; exhaustion holds recovery without evicting
the earlier identities needed for duplicate detection.

Within one native turn owner, a local semaphore serializes checkpoint load,
commit and history synchronization across awaits. Its cursor uses only short
synchronous mutex sections. A pending exact successor is recorded before the
original ThreadStore-owned commit; cancellation of its waiting caller does not
cancel that owned commit. The next caller reconciles that same successor
before proposing a different checkpoint. This adds no durable store or
replacement writer. Its cancellation regressions exercise concurrency in one
process, not an operating-system crash.

New provenance binds the full native execution configuration: model,
instructions, tools, response storage and all eight execution limits, including
exact duration seconds/nanoseconds. An identical first model body is insufficient
if those execution limits changed. Legacy provenance remains readable for
observation, but its missing configuration digest cannot be invented to enable
preparation.

### Fresh continuation under the original owners

The candidate has two explicitly verified continuation boundaries. The first
accepts only revision 1 whose full encoded state equals the original canonical
initial state, whose first model request has the original fingerprint, and
whose entire original execution scope has no admitted operation. The second
accepts a clean next-step boundary only after validating the complete original
checkpoint chain and execution scope. Pending effects and final answers retain
the original observation path; a checkpoint or a successful GET alone is not
fresh permission.

Core constructs a private continuation origin from its exact current task,
executor, original live thread and installed QueueStore. The Queue read returns
only an already persisted client/payload/turn/revision tuple and checks the
original deletion fence. Completion has cleared `queued_item_id`; that identity
comes from immutable Core provenance. Confirmation revalidates this same tuple
and publishes readiness under the original Core task gate. It creates no queue
item, dispatch claim or second completion transaction.

For the second boundary, ThreadStore exposes all original revisions through a
bounded read in one SQLite snapshot, retaining its original epoch, deletion
checks and hash-chain validation. Bounds remain 4 MiB per checkpoint and 4096
revisions, with a 64 MiB aggregate source-byte limit. The writer independently
reads all operations, matching outboxes, original events and complete claim
chains in the original lease/scope. It does not omit an older generation: such
material is explicitly held instead of being rebuilt with a current grant.
The scope limits are 4096 operations, 32768 event/claim rows and 64 MiB of source
fields, checked before loading their content. Text budgets count UTF-8 bytes.

The pure fold starts from the exact canonical initial state. Every checkpoint
successor must equal the shared live engine's state projection. Model admission
must preserve the original operation identity and request body; complete model
output and usage must reproduce the original terminal receipt digest. Tool
admission preserves the original compiled arguments and intent, and completion
uses original raw stdout/stderr bytes and the original runtime terminal receipt.
Lossy UTF-8 output in model context cannot reconstruct that raw evidence.
The production tool port settles its writer and returns model feedback from
one complete raw observation, so its receipt cannot refer to a second fetch.
The native engine validates that complete receipt, raw digests and retention
bound before invoking `ToolPort::present_output`. Presentation has the same
remaining tool deadline; timeout preserves the original pending operation.
The default renderer is shared with the pure recovery fold. A qualification
port may instead return a bounded excerpt and original-owner reference, but
production continuation still requires a frozen presentation policy and an
exact recovery proof; arbitrary excerpt strings are not accepted by the
production fold.
Unexplained operations, missing transitions, mismatched output, exhausted
budgets or incomplete claims hold the turn.

When an original pending response or job settles during recovery, Core may
perform one additional continuation check in that same task. The observer runs
once; a missing next-step proof preserves its result, and conflicting proof
holds the turn. Completed, cancelled and TurnAborted results, a cancelled token
or an interrupted original preparation never enter this second check. This
creates no second typed successor and does not turn observation into authority:
the original Queue, task, canonical owners, checkpoint chain and writer frontier
are independently checked again before the next effect.

The original writer's exclusive fence excludes new scoped operation admission.
Some legacy observation methods can still advance a nonterminal claim or
outcome; therefore a nonterminal frontier is only a snapshot. Continuation
requires both the immutable terminal event and the original last claim in
`Settled`. An operation marked `Committed` while its claim remains `Entered`
is still held. This adds no durable authorization log or execution outbox.

All ThreadStore and runtime observation awaits finish before retaining that
writer fence. While retaining it, the adapter performs the pure fold and
synchronously rearms the original coordinator. It releases the fence before
ThreadStore recovery, then requires the exact verified checkpoint version and
payload before proceeding. Physical entry still consumes a fresh FinalUse grant
under the original Core, Agentd/Fleet and production-writer gates.

### A replaced worker never inherits a successor's execution revision

An actual same-live continuation advances the original run revision, including
when its old phase is still `Dispatched`. Replacing `ContextAttached` skips the
old plan's already predicted first dispatch revision. The durable canonical
preparation receipt is retained unchanged; no replacement run is introduced.

An operation admission and checkpoint commit acquire the original writer read
lease before rechecking their captured run revision. Rearm holds the exclusive
side of that same fence, so a waiting old admission cannot become valid after
a successor has taken over. Physical entry checks the captured revision under
the original run lock. Guard cleanup, worker completion and observer settlement
also compare their own revision before the original reducer's idempotent
branches. A late checkpoint reader cannot downgrade a new dispatched run.
The current attempt may finish its own cancellation transition; an older
attempt cannot finish or abandon the successor's cancellation.

### Cancellation and closure survive removal of the in-memory run

The original `DurableRunStartJournal` retains two additional immutable
lifecycle facts: the original owner's accepted cancellation decision and its
terminal decision. Both bind the full original RunStart record digest, the
actual run revision and the original cancellation reason. They use the same
file, hash chain, projection, fsync and capacity limits as the existing RunStart
and Prepared records. They confer no execution permission.

Original cancellation and terminal control requests persist their accepted
decision before returning success. Release requires that the original closed
fact is durable before removing the in-memory run. Fresh RunStart projection,
canonical preparation and checkpoint continuation consult those same facts
under the original journal and run locks. A missing in-memory entry therefore
cannot revive a cancelled or closed run from an older Prepared receipt.

These facts do not erase Prepared audit data or the original pending effect.
Cold observation retains the original lifecycle phase, cancellation reason and
current observer revision, while keeping the checkpoint's immutable original
anchor unchanged. It may settle the same request or job without a fresh grant.
An exact signed queued retry after a stop uses only the journal's immutable
original receipt and the existing Queue's `ReconcileOnly` operation. It neither
recompiles the objective nor appends another journal frame. Missing/cancelled
queue admission remains held. ReconcileOnly may reconcile an existing binding
and wake its original queued dispatch owner; it is not a promise of zero Queue
activity. It cannot create a missing input, and fresh preparation/physical
entry still consult the original stop facts. Fresh preparation getters and
creating queue routes retain their stop fence. A queue reply already in flight is validated
against the original signed route, trust and generation even if the same run
has completed before its ACK; the reply grants no subsequent execution.
A technical Indeterminate result with no cancellation decision remains eligible
for the independently verified A/B continuation boundaries above.

The lifecycle frames share the original journal's 4096-frame and 64 MiB limits;
there is no separate native quota. A failed or uncertain durable write cannot
produce a successful control acknowledgement. Recovery still uses the existing
journal recovery and acknowledgement-anchor contract; this change does not
manufacture an external recovery cut. Older binaries do not recognize the new
frame domains and fail closed, so rollback after these records are written is
not a transparent binary downgrade.

## Agentd startup and lifecycle qualification

`AgentdConfig::with_native_runtime` composes the native host with the configured
original recovered production writer and production-operation service.
`run(config)` performs the real runtime health probes, attaches the existing
stores and registers the hosted executor on the original App Server.
For explicitly configured native execution, startup first rejects an incomplete
owner composition before opening stores or probing hosts. Native requires the
original recovered writer and operation service; a configured canonical runner
and invocation provider must be paired, and CanonicalObjective additionally
requires the original profile and AuthBus trust/checkpoint inputs. This presence
check does not replace attachment-time authority, lease or currentness checks.
Non-native startup keeps its existing compatibility behavior.
Readiness remains owned by Agentd's existing prerequisites, UDS probe and Fleet
promotion. Drain and shutdown retain the existing control and task host.

The ordinary CLI does not yet assemble a recovered production writer,
production FinalUse provider, native runtime configuration and canonical
intelligence invocation provider. A complete source search found the concrete
`AgentdFinalUseGrantProvider` implementation in the controlled test fixture, not
an ordinary production loader. The existing `runtime.codex.turn_start`
authorizer returns an already-claimed token for another boundary; it cannot be
substituted for an unused grant consumed by the production writer at the native
effect entry.

Completing that executable path requires the deployment's existing production
bootstrap and external grant-provider integration point. This candidate does
not synthesize signing authority or silently select a provider from model text.

## What the regression fixtures establish

| Regression family | Actual components exercised | Qualification boundary |
| --- | --- | --- |
| Core/Queue held-tail and preparation recovery | Real Core, original queue database/dispatch lock, original rollout and ThreadStore; two inputs and a reconstructed Tokio runtime | Synthetic executor checks Core/Queue behavior; its counters are not FinalUse evidence |
| Provenance-before-input crash window | Original store decorator pauses the actual first append; first runtime is shut down, handles disappear, then original paths reopen | Runtime reconstruction, not an operating-system crash |
| Signed Objective to model/process | Original seven owners, AuthBus, Queue, Core, checkpoint, production writer and final entry gates | Controlled signing/model providers; process transport is explicitly isolated |
| Core cancellation after a signed grant | Original Core interrupt, Queue, checkpoint, production writer and actual native model port; an independent in-flight worker deliberately bypasses the engine cancellation loop | Controlled signer/HTTP; checks the final model-entry gate, not full engine cancellation or live-provider behavior |
| Same-turn continuation and replaced holders | Real signed preparation, Core task, original persisted Queue tuple, original writer scope proof and original checkpoint CAS | Controlled model/process providers; explicit old worker, cleanup, observation and waiting-commit adversaries |
| Cancelled checkpoint waiter and lost acknowledgement | Original ThreadStore-owned commit, checkpoint CAS and a distinct successor under the same native turn owner | Same-process concurrency; no claimed operating-system crash |
| Cold writer/Fleet relaunch | Exact original recovery cut, same writer lease, real Fleet lifecycle 1 through 6, original pending response | Handle/owner reconstruction; no claimed operating-system restart or live provider GET |
| Embedded daemon lifecycle | Actual `run(config)`, native attachment, fixed runtime health subprocess, control UDS, App Server, original Queue and ThreadStore, readiness, drain and normal joined shutdown | Controlled providers/transport; ordinary CLI bootstrap and SSH authentication remain unqualified |

The process acceptance fixtures require explicit opt-in and run in their own
namespace. Their transport permits only the original controlled runtime helper
and the exact fixed health command/argv. The daemon fixture signals only that
isolated test child and checks that original state/native/writer references
are released after `run()` returns.

Fresh verification must include affected packages, the CLI binary and the
repository-required complete test suite. Earlier qualification counts cannot
be carried over to later source edits. Baseline failures, candidate regressions,
environment failures, ignored opt-in cases and unexecuted cases must remain
separate in the evidence record. Final scoped Clippy fixes and formatting follow
the test phase under this repository's instructions.

## Review and replacement decisions

The smallest coherent review stage is the Fleet lifecycle-entry fence and its
cross-process tests. Follow it with Supervisor contention handling and its
fault regressions, writer lifetime/entry and scope observations, ThreadStore
history/checkpoint support, Core/Queue hosted lifecycle, then Agentd canonical
composition and end-to-end fixtures. The integrated candidate spans those
dependencies; it should not be represented as one small change.

The native loop is a module boundary inside the existing production ownership
path. It does not require an additional process for each module. This candidate
keeps the original resident App Server and Core session/turn owner, so memory
savings from the isolated qualification runner must be remeasured on this full
composition. No new native-versus-Codex performance ratio is established here.

The three replacement lanes remain resident App Server, Codex in-process and
Hepta native. Matched-input/behavior measurements and separately optimized
product configurations answer different questions. Representative editing,
failed-test repair, multi-tool turns, long output, PTY, third-party tools,
cancellation and recovery must pass before a cutover claim. A small-sample
maximum is an observed maximum, not a stable tail-latency estimate.

Cell addressing/composition, equal-information baselines, lifecycle costs,
retention and cross-node reuse remain a separate qualification gate. Executor
resource savings establish no cell-learning or general-intelligence result.
