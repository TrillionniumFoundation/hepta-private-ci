# Notes durable Organ: development and protocol

This module connects the original Hepta writer, operation outbox and FinalUse
consumer to the original Linux Session/App. It does not create a second issuer,
writer, operation ledger or kernel. Notes-only production installation uses
`attach_production_notes_host` with `AgentdProductionNotesHostInputs`; it derives
the sole primary target from the real Session handoff. Multi-target installation
uses `attach_production_operation_host`; see [PRODUCTION_COMPOSITION.md](PRODUCTION_COMPOSITION.md)
and [FINAL_USE_ISSUER_PORT.md](FINAL_USE_ISSUER_PORT.md). All seven external
trust inputs remain mandatory. The library entry point does not certify that a
particular deployment has supplied those inputs correctly.

## State ownership and source map

| Responsibility | Owner |
| --- | --- |
| Exact semantic operation, predecessor, retained payload and terminal event | `hepta-memory/src/production_writer.rs`, existing `local_lease_outbox.rs` |
| Exact Notes response verification and synchronous effect entry | `hepta-memory/src/production_notes.rs` |
| Terminal evidence / durable receipt retirement under original SQLite write lock | `hepta-memory/src/production_notes_owner.rs` |
| Old-operation observation, with no effect descriptor | `hepta-memory/src/production_notes_recovery.rs` |
| Current revision/hash observation on the independent lane | `hepta-memory/src/production_notes_read.rs` |
| Bounded private transport and correlation | `hepta-agentd/src/notes_channel.rs` |
| Session offer validation / descriptor custody / explicit recovery handoff | `hepta-agentd/src/notes_bootstrap.rs` |
| Document bytes, revision and retained application receipt, atomically fsynced | Companion Desktop `ui/core/src/notes/persistence.rs` |

A stable private document directory is not a target identity. Session restarts produce a fresh
`(session_instance, task_id, incarnation)` triple and fresh destination/scope.
The old operation keeps its original bytes and old triple. The new process may
observe an old persisted receipt, but the old FinalUse grant cannot mutate the
new target. No disk path enters the effect request or issuer binding.

## Bootstrap and wire contracts

The trusted parent starts the companion Session with either:

```
trill-session --notes-bootstrap-v2-stdin --notes-new-document /absolute/private/notes-document
trill-session --notes-bootstrap-v2-stdin --notes-document /absolute/private/notes-document
```

Standard input is an inherited unnamed Unix datagram socket, not terminal input.
The existing `offer_notes_target` JSON uses `schema_version: 2`. SCM_RIGHTS must
contain exactly `[effect SOCK_STREAM, recovery SOCK_DGRAM]`, in that order.
`attached` acknowledges verified owner composition only: it does not prove that
an issuer approved a request, an application effect occurred or a terminal event
was published. Legacy v1 companion startup remains separate.

`replace_note` effect payload schema 1 is unchanged. Original exact UTF-8 bytes
bind operation ID, destination, target, expected revision and text. Request
bounds are 8192 bytes and 4096 text bytes. Responses are bounded at 2048 bytes.
The effect stream is length-prefixed and permanently disabled after ambiguity.
No effect retry occurs on the recovery lane.

The recovery lane admits only these actions:

* `observe`: exact old target, operation ID and payload SHA-256. An applied
  response is the original response bytes. Absence stays `unknown`; it cannot
  imply that a timed-out effect did not occur.
* `acknowledge_terminal`: same binding plus SHA-256 of the exact response UTF-8
  bytes persisted by the original writer. A matching `released` or
  `already_released` ACK releases the single pending application receipt.
* `read_document_state`: current target plus a fresh 32-lowercase-hex request ID.
  Response action is `document_state`, echoing target/request ID and reporting
  durable `revision` and `text_sha256`. This is observation, not authorization.

ACK responses have no `action` field; their fields are schema_version, target,
operation_id, payload_sha256, receipt_sha256, status. Observe responses have
`result` instead. Correlation rejects late or unrelated frames, and every
transport exchange has one two-second deadline and bounded receive count.

## Recovery lifecycle

1. The original writer admits immutable operation and exact payload.
2. The original FinalUse consumer enters the exact effect synchronously.
3. App persists text + revision + exact receipt atomically before Applied.
4. Original writer validates and appends the complete receipt in its existing
   event chain. Generic apply/reject/reconcile cannot forge a Notes terminal.
5. Only then does the original writer issue metadata retirement while holding
   its SQLite write lock and rechecking the live authority.
6. A dropped effect reply leaves source Indeterminate. Independent observation
   can resolve that same operation without obtaining another grant or effect.
7. After App restart, `recover_notes_from_session` validates the old retained
   operation through the original writer and narrows its capability to the new
   process's recovery descriptor. It returns the fresh current target separately;
   future effects require a new operation and grant for that target.
8. Original source reopen still requires an independently retained current cut.
   Neither the application state directory nor a locally calculated digest supplies it.

Multi-destination reconciliation shares a rotating start cursor across host
clones. An earlier destination that remains Unknown consumes its bounded work
budget, but cannot indefinitely prevent a later Notes destination from observing
its terminal receipt and releasing its one pending receipt slot. Rotation never
changes Unknown into rejection or authorizes a resend.

This slice guarantees local SQLite terminal durability and companion document
persistence under the tested filesystem semantics. It does not import later
whole-owner external checkpoint publication or qualify a native kernel, LAN
issuer, mobile lifecycle, GPU compositor or physical device firmware.

Initialization and shutdown are not cancellation-safe in this slice. The
embedding supervisor must await these futures to completion rather than drop
or externally time out them after the source owner opens. Ordinary error paths
after an owner/store is acquired await the original pool's close barrier while
retaining its source fence. This does not certify all lower-level
`CognitiveStore` recovery publication failures or arbitrary task cancellation.
A shared writer/host cannot close another live writer's pool.

## Development and validation

Base: Hepta `6d6097da843f5831dfaf9cee3530da512d072a15`. Narrow reused slices:
Notes recovery from `0adaca4375fdfefe0fbae7f1cb7f25c437360c6e` (#3366), original
protected composition / issuer transport from `a5bf15516e744fd86d6564bda5a60e8b942a2eb6`
(#3398), and Notes no-bypass ideas from `08e22214a1a5213ef093fdbcde07097ac449ddad`
(#3452). No large candidate branch was merged. Review in dependency order:
transport/receipt evidence, protected composition, persistent restart recovery.
These are three logical review stages of one coherent, buildable integration change.

Run normal owning-package tests with `just test --locked -p codex-hepta-memory
-p codex-hepta-agentd`. The two real-App tests are intentionally ignored by
ordinary CI because they launch a pinned external companion build. Run them
only against an owned isolated Xvfb with:

```
TRILL_NOTES_PROBE_ISOLATED=1 DISPLAY=:<owned-display> \
HEPTA_NOTES_SESSION_BIN=/absolute/companion-build/trill-session \
HEPTA_NOTES_QUALIFICATION_OUTPUT=/absolute/roundtrip.json \
HEPTA_NOTES_CRASH_QUALIFICATION_OUTPUT=/absolute/crash.json \
just test --locked -p codex-hepta-agentd --lib \
  -E 'test(notes_actual_)' --run-ignored ignored-only --test-threads 1 --retries 0
```

The first actual test covers refusal before effect, two successful edits,
capacity release, lost effect reply and same-process recovery. The second sends
one actual effect, observes durable application state independently, SIGKILLs
only its owned Session/App process group, cleanly closes and reopens the original source owner and
the same document in a fresh process, and reconciles the old operation without
another effect or grant. A separate normal memory-owner test starts the real original writer in a
subprocess, retains an Indeterminate operation, SIGKILLs that process without
closing its pool, then starts another process to reopen the same original
SQLite/outbox and verify the original payload and unresolved state without
dispatch. That source-crash case uses an application-observer fixture, while the
GUI case uses the actual companion App. Neither kills the machine or simulates
storage hardware power loss. Unit tests also force source-terminal persistence failure,
verify no premature ACK, reopen the owner, and reject generic terminal bypasses.
The byte-identical cross-repository bootstrap-v2 and recovery-v1 fixtures are
consumed by the real descriptor receiver and original writer/Notes APIs. The
recovery test checks current document observation, Unknown retention, complete
receipt persistence, rejection of an ACK for semantically equal but differently
formatted JSON, and idempotent exact-byte retirement. A separate two-destination
test exercises the rotating reconciliation budget over real private sockets.

Every test issuer / compatibility FinalUse / captured-cut fixture is explicitly
qualification-only. JSON evidence includes `production_authority: false`.
Success is a development integration result; production acceptance additionally
requires deployment-specific evidence for the seven real external inputs.
