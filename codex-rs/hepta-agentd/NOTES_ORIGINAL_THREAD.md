# Original-thread Notes tools

The product composition selects `organ.notes.thread-tool.v1` for Notes requests
made by the model in one original App Server thread. The existing literal Notes
adapter retains its separate `organ.notes.literal.v1` profile and no-model
meaning. The two operation modes are mutually exclusive in one Agentd config.

## Trusted startup

The human-authenticated Root launcher must supply the existing original writer,
live authority session, Session Notes observer, protected checkpoint, fixed
`AgentdTextSessionConfig`, and actual runtime/model/prompt/artifact digests. None
of these values is accepted from model arguments or inferred from an OS user or
provider credential. This API does not initialize Root, a human session, provider
login, a lease, or an existing conversation.

At the original `thread/start`, register `original_notes_thread_tools()` in
`dynamic_tools`. Keep that thread's returned ID and App Server session ID in the
trusted route. A resumed thread must already retain this catalog; resume does
not add it. Select `thread_notes_admission_profile_json_v1` for the retained
principal/issuer, then use:

For first deployment, `seed_original_notes_thread` accepts a real connected
original App Server client and the exact expected Core home. It calls actual
`ThreadStart` with this fixed catalog, persistence and no model fallback, then
immediately rejoins that same running thread using `ThreadResume` with no
overrides. The original store writer thereby materializes the otherwise lazy
rollout even without a user/model turn. The helper reads the actual bounded first
`SessionMeta` line and compares exact thread/session IDs, provider and catalog;
its receipt records real responses, catalog hash and metadata hash. It submits no
user message, starts no turn, stops no process and creates no human authorization.
A lost Start acknowledgement is unknown and is never retried automatically.

The seed receipt is now schema 2. Its model tuple also binds the finite
`hepta.notes.core-execution.v2` profile, actual canonical execution cwd, and exact
`config.toml`/`environments.toml` byte hashes. The helper semantically checks the
fixed public execution configuration before creating a thread. Shell, image,
browser, computer, agent, plugin, MCP, web and utility tool sources are disabled;
the original three dynamic Notes tools remain registered. Start explicitly
selects no environments or capability roots and ReadOnly/Never permissions.
The persistent environment file must contain `default = "none"` and
`include_local = false`, with no configured environments. Empty Start
environments alone are insufficient: an unused rollout contains SessionMeta,
and a different owner would otherwise select its manager's default environment.

Before and after the original Start/Resume, `config/read` observes the effective
cwd configuration, including requirements and project layers. The public API
omits two utility tool settings, so their effective origins must remain the
inspected original user config; the corresponding file semantics are checked.
The selected model/provider and every supplied provider field must also retain
that original user-config origin. The complete normalized provider definition,
including endpoint and authentication/header options, must equal the frozen
home configuration; a matching provider name alone is insufficient.
Actual Start and Resume replies must report Never and read-only with network
access disabled. The finite profile does not itself grant any Notes operation.
These observations do not replace installed-product evidence of the model's
actual outgoing tool catalog or a human-authorized Notes effect.

The final owner embeds Core inside Agentd, whose ordinary production mode
enables Hepta Memory and cognitive mutation tools. Original Notes mode instead
selects a deny-only model-tool profile from its installed Notes runtime. Both
`hepta_memory` and `hepta_cognitive_write` remain false in the persistent
configuration and the embedding's required feature states, after per-request
overrides. This prevents the general cognitive extension from creating its
model-tool state. The same original Root Notes writer, protected cognitive
store, governance and turn-recovery owners remain outside that tool profile;
other production modes retain their existing feature selection. A standalone
App Server seed test alone cannot qualify this embedding distinction.

Schema 1 did not establish this execution scope and is rejected. There is no
automatic schema upgrade, config repair, replacement thread or fallback to
unrestricted Core defaults. A changed configuration byte also invalidates the
original tuple, even when a change only adds whitespace. An administrator must
preserve the old deployment and investigate it; this helper never rewrites old
conversation metadata.

The status discovery selector below changes the exact three-tool catalog bytes.
It must be present at the first product Start. Schema 2 alone does not make an
older catalog compatible: seed validation and Resume compare the full catalog
hash and original SessionMeta, including the status schema and description.
Existing receipts/catalogs are refused, never dynamically extended, repaired or
reseeded into a replacement thread. The first installed product must select one
source combination containing this catalog before its seed is created.

The trusted launcher can then gracefully stop the seed owner and launch the
final Agentd with that same Core home. `verify_original_notes_thread_seed` must
resume the original thread on the final actual App Server and compare the real
home, thread/session, model/provider, rollout path and original metadata/catalog
hashes. It neither supplies overrides nor repairs a missing catalog. SessionMeta
persists the catalog and provider; it does not by itself prove that an unused
thread's model setting survived. Final response equality is mandatory. Provider
availability is established only by the subsequent real model turn.

```rust,ignore
config.with_root_notes_thread_tools(
    &original_attachment,
    actual_runtime_bindings,
    fixed_original_route,
    std::time::Duration::from_secs(10),
)?;
```

The production launcher must then install
`AgentdNotesSessionLifetime::from_inherited(session_pidfd, &actual_session_peer)`
with `with_original_notes_thread_session`. It reuses the literal endpoint's exact
same-UID, held pidfd, boot and birth checks. Model mode requires this guard and
retains it around the entire required task; Session exit cancels the task even
while preparation or original control I/O is awaiting a reply. It installs no
literal UI listener. An already started original effect retains its uncertainty
and durable sender fence; Session exit does not mint a replacement send.

The builder checks exact Agentd ID/generation/control socket/home, original
writer pointer, target, Root authority and selected profile. Runtime supervision
starts a required `notes-original-thread-tools` task. It waits for the existing
App Server readiness signal within ten seconds and opens its own bounded
original connection through Agentd's session ingress. A gap or disconnect ends
the task; it cannot create a replacement writer or rearm a request.

## Tools and caller evidence

`hepta_notes_state({})` returns the attached target, current revision, exact text
hash and pending-receipt flag. This state is an observation, not permission.
`hepta_notes_replace({"text": "…", "expected_revision": 7})` accepts only these
two arguments. `hepta_notes_status({"turn_id":"…","call_id":"…"})` reads the
exact result of a retained original replace item in the fixed thread, including
an original item whose tool reply was unknown. These are navigation IDs; the
original item and operation are independently checked, and this path never
prepares, signs or resends.

After a lost tool reply or model-context compaction, use
`hepta_notes_status({"selector":{"kind":"latest_original_replace"}})` when the
old turn/call IDs are unknown. This selector and explicit IDs are mutually
exclusive. On the same seed-verified physical Core connection it requests
`thread/turns/list` descending with `NotLoaded`, at most 16 turns, then reads
`thread/items/list` ascending with 64 items per page and at most four pages per
turn. The entire lookup permits at most 1024 items, 64 RPCs and five seconds.
The latest matching turn's **first** original replace is selected, including an
item with no tool reply. No old model result, summary or directory supplies the
reference. The existing read-only operation proof and original writer then
verify its exact identity, signed request and retained receipt. No history page
is injected into model context. Only the selected reference/result is returned.

An incomplete newer turn cannot be skipped to select an older write. Exhausted
bounds return `status: unknown` with `reason: window_exhausted` or
`deadline_elapsed`; a completed window without a verified replace returns
`original_replace_not_observed`, not proof that no effect exists. None permits
a repeat write. Discovery cannot recover an original item absent from Core.

UTF-8 text is bounded to 4096 bytes. A changed predecessor or
pending receipt prevents preparation. The application still performs its atomic
predecessor check at the effect boundary.

Core's existing dynamic tool handler emits an in-progress `DynamicToolCall`
item and App Server issues `item/tool/call`. Thread, turn and call IDs come from
this original callback envelope. The Agentd connection verifies its connection
ID, fixed thread/session and exact in-progress original item through
`thread/items/list`. Only then can the private non-serializable
`VerifiedNotesThreadCall` exist. Extra arguments such as principal, target,
authority, policy, operation ID or thread ID are rejected.

A model callback is not by itself a human authorization. Before **any** Notes
tool, the worker reads the original turn's first UserMessage. Its exact
`hepta.authbus:<delivery-id>` client identity must resolve to an original retained
AuthBus outbox message with the same Agentd subject/scope, canonical text input,
delivery digest and retained Core acknowledgement. A direct `turn/start` without
that original delivery is refused. `thread/queue/reconcile` is then called only
with `ReconcileOnly`; it must return the same client/payload and `Persisted` for
that exact turn. It can never admit a missing user input as a new message.

The original held Root channel must independently verify the exact
`AuthBusTextIngress` against its original issuer record. Root's real human UI
lane atomically retains a human binding with the original text signature; a
generic signature, matching request namespace, legacy unstamped record, provider
login or OS username cannot supply it. Root checks its current human
principal/session, permission revision, expiration and held UI lifetime, then
returns only an observed `TextOwnerReceipt`. The worker checks the exact frozen
route and protected-clock expiry. A private `VerifiedHumanTurn` carries this
comparison data through preparation; it grants no authority and is never read
from renderer JSON.

The same Root verification is repeated before preparation and immediately
before Objective signing. Its human authorization must remain identical and the
finite Objective deadline cannot exceed that human session's expiration. These
checks add neither an issuer record format owned by Desktop nor a second
AuthBus, admission or conversation ledger.

Each original turn permits at most one Notes write attempt. The original
ordered thread items designate its first `hepta_notes_replace` call. Later
replace calls can only read that original result, even if they change call ID,
text or expected revision. State and status remain available. A subsequent
human-authenticated turn is a separate intent domain.

The fixed original session/thread/turn tuple derives one `notes.thread.*`
operation ID in the original writer. The signed source separately retains the
complete original call digest in its request ID. Replayed calls compare that
retained call digest and exact text/predecessor. A prepared operation without a
signed sender is retained uncertainty and cannot be signed or rearmed by a new
worker, reconnection or process; it remains available for readback. This may
require a later human turn after a preparation failure, rather than an automatic
retry. These fences use the existing original writer/sender and ordered original
thread items, not an in-memory flag or a new ledger.

Status also verifies that the referenced original item was the turn's first
Notes call and that its digest matches the retained signed source, so an old
receipt cannot be attributed to a later call. The operation semantic digest binds
the fixed target, exact text and predecessor. The signed Objective body retains
the actual model/runtime/prompt/artifact digests. This provenance describes an
original Core tool callback; a real model execution is established only by the
corresponding installed-product run, never by these protocol tests.

## Effect and result ownership

Preparation uses the existing Notes intent validator and same
`ProductionDurableWriter`. Root signs the registered Objective; the existing
protected sender retains the exact signed request before its one send. The
original Objective coordinator and FinalUse dispatcher perform the action. A
replayed callback recovers the original retained request and cannot resend it.

`retained_notes_terminal_receipt` reads this writer's existing terminal event,
checks its payload hash and exact typed Notes receipt against the retained
operation, and verifies live authority. It writes no event, grants no permit and
does not retire a receipt. The tool result includes operation and semantic IDs,
exact signed-request hash, original callback provenance and exact receipt bytes.
`original_target` belongs to that retained operation and `receipt_utf8`;
`current_document` and `current_document_readback_available` describe only the
currently attached observer. After recovery this may be a different target.
Neither a new empty document nor failed current readback invalidates an old
verified receipt, and no old-document freshness is claimed. State-only reads
still use their existing `document` field. Only a committed original receipt
reports success.
Unknown results retain their original call/operation identity and instruct the
caller to reconcile it; a missing result is never proof of no effect.

The original connection resolves the exact pending `item/tool/call` handle.
App Server's existing `Op::DynamicToolResponse` updates the original Core item
and resumes the model in that same thread. There is no second transcript,
tool ledger, outbox, issuer or authority path.

## Development checks and remaining product evidence

Use repository `just test`, zero retries and nonzero test selection. The finite
source tests must admit their own profile and reject the literal profile. Caller
tests must reject changed items, completed calls, foreign threads, namespaces,
authority arguments and oversized UTF-8. Original SQLite owner tests must read
the same complete receipt after reopen without changing its recovery anchor.

These checks do not establish a real human grant, provider turn, original-thread
tool callback, or installed Notes effect. Product acceptance must record the
actual original thread/turn/call, Root registration and human session, model
provenance, operation ID, signed request hash, complete retained receipt and
application readback from the final source and package. The launcher's binding
and actual run remain part of the product acceptance, not a protocol fixture.

## Protected original reference when Core history is unavailable

The verified original write callback also supplies bounded raw navigation data
for `ObjectiveSenderOrigin.original_notes_thread`. It is recorded with the same
signed request and protected sender binding before the original checkpoint ACK
and first send. It grants no authority. This covers the case where best-effort
Core rollout I/O failed but its live item was observable before Notes saved.
Normal successful Core appends already await a file flush before tool execution;
that flush must not be described as an fsync/power-loss guarantee.

Status first reads original Core items and also checks a complete original-owner
sender cut (one read-only SQLite snapshot, at most 1024 requests / 32 MiB, five
seconds). Only the selected reference/result is returned, never that history.
Matching Notes records are ordered by the original adapter's existing
`(spawn_generation, request_id)` counter, never request SHA, rowid or a new clock.
The installed thread runtime owns one non-cloneable adapter; configuration
refuses a second Notes mode, and only the verified write path produces matching
raw references. Duplicate order values still return explicit ambiguous Unknown.
An incomplete/failed cut cannot establish a latest result.

A lost later Core item must not make an older retained Core item appear latest.
The result labels `source_domain` as `original_core_dynamic_tool` or
`original_protected_sender_reference`; fallback selection explicitly describes
`latest_retained_original_operation`. The independent recorded-source proof
checks raw IDs against the original signed request ID, turn-derived operation,
agent, principal/model tuple, all frozen provenance, exact Notes operation and
callback digest. It never fabricates a Core item or enters write preparation.
An exact reference may use the same protected read when its old Core item is
unavailable. Legacy `None` without a verifiable Core item remains Unknown. The
original receipt/target and current document stay separate.
