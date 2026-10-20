# Read-only observer technical contract

This contract describes the default `ObserverClient` and CLI. The separately
enabled, default-off [ObjectiveStart transport](OBJECTIVE_TRANSPORT.md) is not a
method added to this observer or to `TrustedReadOnlyOrganV1`.
The independently enabled [Objective admission history](OBJECTIVE_HISTORY.md)
also uses a dedicated client and a separate original-owner source contract.
References below to the fixed protocol lacking history apply to `f8c9419d`,
not to that explicitly versioned extension.

## Version and provenance

The adapter targets Hepta commit
`f8c9419df6ddeb36ff8b522a50219981fb8d9345`, Agentd control schema **2** and
capability schema **1**. `UPSTREAM_CONTRACT.json` records SHA-256 content hashes
and Git blob IDs for twelve reviewed files. The conformance script requires
the exact checkout commit and content before extracting original declarations.

The dependency is a private, versioned client subset because the whole upstream
protocol crate imports automation and fleet types, and the daemon client crate
also imports the full Agentd/App Server composition. The subset does not invent
a new server protocol. It accepts no unknown payload type or field, and future
upstream schema changes require an explicit review and provenance update.
Additive capability **names** remain valid advertisements, but never add a
client method or grant authority.

| Source in fixed Hepta | Contract used |
| --- | --- |
| `hepta-agent-protocol/src/lib.rs:48-67,203-210,725-775` | Version, frame bound, exact overload frame, request/response envelopes |
| `hepta-agent-protocol/src/lib.rs:817-828,880-907` | Health DTO and lifecycle-event DTOs |
| `hepta-agent-protocol/src/capabilities.rs:12-95` | Capability schema, count/identifier bounds and duplicate rejection |
| `hepta-contracts/src/agent_id.rs:41-73` | Canonical lowercase UUID, supported version and variant |
| `hepta-agentd/src/client.rs` and `control.rs` | Existing UDS framing and per-request response semantics |
| `hepta-agentd/src/state_control.rs:148-170,523-531` | Health readiness calculation and read-only known-run lookup |
| `hepta-fleet/src/model.rs:140-189` and `hepta-agentd/src/state.rs:336-345` | Increment per lifecycle transition; exact serving phase/current-generation binding |
| `hepta-agentd/src/event_buffer.rs:13-70` | Retained suffix, gap, pagination and process-local cursors |
| `hepta-agentd/src/lane_b_runtime.rs:29-30,571-657` | Run identity/digest bounds and terminal-observed phases |
| `hepta-agent-protocol/src/authbus.rs` and `hepta-agentd/src/objective_runtime.rs` | ObjectiveStart authentication and owner admission, intentionally outside this client |

Paths in this table are relative to upstream `codex-rs/`. The manifest links the
repository and immutable commit. A successful source-derived check proves
agreement with the reviewed types and event-buffer code; it is not evidence of
a booted daemon or configured production owners.

## Wire and host boundary

Each request uses a new Linux AF_UNIX stream and one newline-terminated JSON
frame. The maximum frame is **65,536 bytes including the newline**. The response
reader consumes at most 65,537 bytes to distinguish an oversized frame and
discards the connection after one response. There is no generic send method,
TCP fallback, retry, session-ingress lookup, or mutation variant.

Before each connection, one bounded-admission filesystem job checks that the
parent is a canonical, non-symlink directory owned by the configured UID with
no group/other permission bits, and the endpoint is a non-symlink socket owned
by that UID with no group/other bits. A normalized absolute UTF-8 path no longer
than 107 bytes is required. The caller must not use shared or untrusted
filesystems for this local profile. Permissions may be stricter than Hepta
deployments that intentionally permit group sharing; those deployments are not
qualified by this profile.

After connecting, kernel peer credentials must supply the configured UID and a
nonzero PID. The returned `agent_id`, immutable `spawn_generation`, schema
version, and request ID must match the trusted configuration/request.
Both `HealthSnapshot.process_id` values must equal the kernel peer PID; every
connection within a poll must have that same PID. The original fleet owner
increments `current_generation` on each lifecycle transition. For this process
spawn, Agentd accepts exactly Starting at spawn, Running at spawn + 1, and
Draining at spawn + 2. The adapter validates that exact health phase mapping
with checked arithmetic; Stopped/Failed and all other offsets fail closed.
It permits monotonic phase advancement across the RPCs and reports the final
health response's actual current generation. One ephemeral read watermark
rejects regression below a prior successful observation in the same client;
it is not a durable operation record. A fenced health/event or inconsistent
phase fails the entire read as `generation_fenced`.

A process restart between polls is not hidden: the Session
must compare the prior observed PID, clear its old event window, and mark the
source change, even if a launcher reused the same generation incorrectly.
Normal current-generation advancement within the same spawn/PID preserves the
event window. A legitimate new spawn requires new trusted endpoint configuration
and a new client; an old client never rebinds itself to it.

The pathname checks can race other processes under the same UID or a privileged
host; peer credentials and the bounded method set remain enforced. This
mechanism does not establish remote cryptographic identity or code attestation.
It cannot compensate for granting the renderer direct OS access to the
privileged Agentd socket. The trusted launcher and Session isolation are
separate deployment responsibilities.

## Observation and cursor semantics

`poll(after_cursor, limit)` permits `1 <= limit <= 256` and makes exactly these
reads: **health → capabilities → events → health**. A shared deadline bounds
the entire asynchronous attempt to five seconds. It returns a complete safe
projection only after both health checks and all intermediate response checks
pass. The RPCs are separate observations and do not form a linearizable owner
transaction. Health can change immediately after the final response.
The upstream response captures runtime generation before separately locking
its event buffer. Promotion between those locks can yield a newer lifecycle
event than the captured envelope generation. This mixed cut is conservatively
discarded; the Session marks its prior observation stale and a later independent
read can recover. The client does not weaken event fencing to hide that race.

`health.ready` reports the daemon's current readiness calculation, not a model
answer, objective admission, resource-budget installation, or device-effect
completion. Workspace, home, and run paths are parsed for the pinned wire and
discarded. Capability IDs are restricted to the upstream 128-byte ASCII
alphabet (`A-Z`, `a-z`, digits, `.`, `_`, `:`, `-`), at most 64 entries with a
nonzero major and no duplicate IDs. They are sorted for stable display.

Events are restricted to `bootstrapped`, `lifecycle`, `app_server_ready`,
`draining`, and `generation_fenced`. They are process-local lifecycle metadata,
not the full task, token, operation, or device-event stream. Empty struct
variants enforce strict field rejection for the unit-shaped events; serde's
internally tagged unit-variant parser otherwise tolerates extra fields.
Historical lifecycle events use that event's own original phase offset and
may precede the current phase. They must not exceed the event response's current
generation. A prior Starting event remains valid after Running/Draining.

For a successful page, `next_cursor` is exactly the last event actually returned.
An empty page keeps the requested cursor and must be at the observed tail.
Events must be consecutive, ordered, within the requested limit, and no later
than `latest_cursor`. An incomplete page must reach the tail. A gap means the
oldest retained cursor is greater than `after_cursor + 1`; the first retained
event is returned without inventing the missing prefix. The Session can retain
a sticky history-gap indicator and a separate count of entries dropped from
its display window. Display truncation must not be reported as upstream loss.

`event_cursor_ahead` means the supplied cursor exceeds the daemon's observed
tail. The upstream buffer can return this after a process-local log resets. The
caller may reset **only its read cursor** to zero and resynchronize while
marking the history discontinuity. It must not replay a task, clear an operation
unknown state, retire history, or send any effect because of an event gap.

## Existing run observations

`run_status` accepts one already-known identifier in the upstream 1–128-byte
ASCII identity alphabet. It brackets the lookup with health/PID checks and
verifies that the returned receipt names the requested run. It projects only
run ID, revision, phase, authority epoch, generation, terminal-observed, and
idempotent. It drops context/fence digests, cancellation details, and deadlines.
The receipt's original generation can be older than the currently serving
daemon; observation does not renew that generation.

The original [RunStatus handler](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-agentd/src/state_control.rs#L523-L531)
reads the current in-memory run projection. A `null` result means this lookup
found no projected runtime receipt; it does **not** prove that an earlier
objective was not durably published. The fixed protocol has no separate
objective-publication status method. A caller must not clear a submission's
unknown state or create a new run because this lookup returns `null`.

The current upstream run-state owner computes `terminal_observed` for cancelled,
succeeded, and failed phases. An inconsistent flag is rejected. A consistent
run state is still not evidence that a specific OS/device operation took
effect. This client never writes run terminal state, acknowledges HOS2 results,
retires history, revokes authority, or persists a second operation record.

## Errors, freshness, and unsupported submission

Errors expose only the finite `ObserverError::code()` strings. Raw owner error
messages, transport diagnostics, socket paths, unknown payloads, and source
configuration are excluded from the renderer projection and `Display`. A
failed poll must preserve the last successful observation only as stale data.
The Session must expire its freshness from a monotonic last-success timestamp
independently of worker replies; it must not keep the connection healthy just
because an old object remains in memory.

ObjectiveStart remains absent from `ObserverClient`, `hepta-observe`, Session
IPC and the Rust Shell. The separate `hepta-submit` executable is available
only with the default-off `objective-transport` feature. The wire requires an
original `AuthBusObjectiveIngress` from an independently trusted configured issuer,
including signature and owner-bound immutable inputs. Neither a UI draft nor
an advertised capability is such an envelope. This candidate provides no UI
issuer, signing key, authority epoch allocator, generic high-authority ingress,
or UI/Session effect submission. The optional default-off transport accepts that
original envelope from a trusted host, checks structure and retains uncertain
delivery; it does not authenticate an issuer or assemble the provider.
The [2026-10-18 original-runtime evidence](../../results/integration/2026-10-18-objective-desktop/README.md)
qualifies the isolated test issuer's original-owner admission, journal binding,
revocation negative case and restart behavior. The next integration step is
assembly of the existing production issuer/provider, its durable request and
unknown-result handoff, and a restricted HOS2 effect adapter, with the
original durable operation owner responsible for K/D binding, uncertainty,
fencing, acknowledgement and retirement. That production and effect work
requires its own real admission/effect/revoke/restart evidence; the stopped-owner
journal check does not install an online recovery service. See
[S1–S5](../../docs/agents/R8_NEXT_SLICE.md) for the owner/API and completion gates.

The compiled original route is
[state_control.rs:206–228](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-agentd/src/state_control.rs#L206-L228)
calling `ObjectiveRuntimeHost::submit`; the original module declarations select
`objective_runtime`, not the undeclared file named `objective_ingress.rs`.
The existing owner
[publishes durably before its later trust and runtime checks](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-agentd/src/objective_runtime.rs#L206-L327).
Once a request may have reached that owner, a timeout, connection loss or error
without authoritative non-admission evidence is **SubmitUnknown**. `Admitted`
and `Conflict` are publication receipts; neither establishes a final device
effect. Even an admitted explicit abstention need not create a runtime run.

The owner permits an already-used sequence only for the exact recorded
authentication and run ID; signature expiry, revocation, readiness and spawn
fencing remain enforced. A future adapter must not refresh credentials, allocate
another run ID or rebind to another spawn to retry an unknown outcome. The
[live-source and trusted-ingress review](../../tests/integration/hepta/LIVE_SOURCE_REVIEW.md)
records the fixed source and the minimum external trust/profile/checkpoint
assembly. It supplies no signer or submission implementation, and does not
change this observer's read-only method set.
