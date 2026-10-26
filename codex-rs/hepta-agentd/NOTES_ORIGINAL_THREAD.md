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
prepares, signs or resends. UTF-8 text is bounded to 4096 bytes. A changed predecessor or
pending receipt prevents preparation. The application still performs its atomic
predecessor check at the effect boundary.

Core's existing dynamic tool handler emits an in-progress `DynamicToolCall`
item and App Server issues `item/tool/call`. Thread, turn and call IDs come from
this original callback envelope. The Agentd connection verifies its connection
ID, fixed thread/session and exact in-progress original item through
`thread/items/list`. Only then can the private non-serializable
`VerifiedNotesThreadCall` exist. Extra arguments such as principal, target,
authority, policy, operation ID or thread ID are rejected.

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
exact signed-request hash, original callback provenance, exact receipt bytes and
fresh document readback. Only a committed original receipt reports success.
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
