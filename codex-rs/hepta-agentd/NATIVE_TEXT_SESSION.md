# Original Root → native UI → Agentd text session

This entry uses the existing Root authority service, its installed writer
registration, its canonical issuer key/policy/sequence/store, the existing
Agentd control socket and one existing App Server thread. It starts no Agentd,
creates no thread and installs no trust or authority from renderer input.

## Development map and checks

| Source | Owner and responsibility |
| --- | --- |
| [bin/hepta-authority-host.rs](src/bin/hepta-authority-host.rs), [authority_host_native_launch.rs](src/authority_host_native_launch.rs) | Existing trusted host CLI; diagnose/launch exact verified UI bytes using existing authenticated inputs |
| [authority_host_text_ui.rs](src/authority_host_text_ui.rs) | Original Root UI registration, kernel peer/pidfd and session boundary |
| [deployment_text.rs](src/deployment_text.rs), [deployment_text_recovery.rs](src/deployment_text_recovery.rs), [deployment_text_retirement.rs](src/deployment_text_retirement.rs) | Original issuer's exact signed references, watermark, recovery and independently established terminal retirement |
| [text_session.rs](src/text_session.rs), [text_session_worker.rs](src/text_session_worker.rs), [text_session_worker_recovery.rs](src/text_session_worker_recovery.rs) | Existing Agentd/App Server route and bounded worker, cancellation, reconnect and lookup-only recovery |
| [text_session_history.rs](src/text_session_history.rs), [text_session_events.rs](src/text_session_events.rs), [text_session_approvals.rs](src/text_session_approvals.rs) | Original history pages, stream projection and original command/file callbacks |
| [text_session_provider.rs](src/text_session_provider.rs) | Original provider account/status path, separate from Hepta human authority |
| [authbus_dispatch.rs](src/authbus_dispatch.rs), [AUTHBUS_TEXT](AUTHBUS_TEXT.md) | Original signed ingress, queue reconciliation and dispatch failure semantics |
| [tests/authbus_text_product.rs](tests/authbus_text_product.rs) | Real supervised Agentd/App Server processes with explicit test trust and local mock model replies |
| [Desktop text adapter handoff](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/blob/main/services/hepta-session-host/TEXT_SESSION.md) | Same original ChatWorkspace, native renderer callbacks, feature build and presentation tests |

From `codex-rs`, use the repository toolchain and locked graph:

```sh
cargo build --locked --profile dev-small -p codex-hepta-agentd --bin hepta-authority-host --bin codex-hepta-agentd
just test --locked -p codex-hepta-agentd --lib -E 'test(text_session) | test(deployment_text) | test(authority_host_native)'
just test --locked -p codex-hepta-agentd --test authbus_text_product
```

The first test command covers protocol/store/worker fixtures; the process suite
starts only its own disposable supervised processes and local model endpoint.
Neither supplies an installed production human session or provider. Preserve
complete command results and actual source/binary identities separately; see
the trusted-input/startup sections below before using the existing host CLI.
The Desktop link is a navigation entry; read it at the exact companion commit
used by the two-repository build.

## Trusted startup inputs

The trusted launcher must already have authenticated the human, opened the
original Root state and registered the original daemon/writer. Its original
Agentd must have both `--authbus-trust-file` and
`--authbus-checkpoint-file`; the public issuer key, epoch and allowed thread
must match the installed Root signer. An App Server readiness observation
does not imply that these inputs exist.

The same original Root initializer accepts an exact text policy:

- subject: the registered Agent ID;
- destination: `DeploymentFinalUseIssuer::text_destination(existing_thread)`;
- scope: `DeploymentFinalUseIssuer::text_scope(registered_agent_id)`;
- lifetime: a bounded original policy, at most 300000 ms.

These are deployment registration inputs, never RPC fields that add policy.
An existing issuer is opened with its original pinned key. Missing policy or
state is refused; startup never initializes or replaces it automatically.

The Root service config explicitly selects `"issuer_record_profile":
"text_recovery"` for the native text lane. This new deployment profile uses
the original DeploymentFrontier's 64 KiB record ceiling in the protected
backend. An omitted profile remains `standard` and retains 16 KiB; clock,
lease and unrelated owners keep their original bounds. This storage profile
is an implementation addition, not evidence of a deployed native authority.

The trusted launcher writes one additional Root-owned mode0600, single-link
JSON registration in the existing protected configuration directory. Its
`HostAuthorityTextUiRegistration` fields are:

| Field | Source |
|---|---|
| `schema_version` | `1` |
| `socket_path` | Distinct private UI lane; parent is Root:peer-gid mode02710 |
| `peer_uid`, `peer_gid`, `peer_pid` | The actual launched UI process; UID must equal original Agentd owner UID |
| `boot_id`, `process_start_ticks` | Actual captured UI process lifetime |
| `principal_id`, `session_id` | Already authenticated human/session; restricted nonempty ASCII IDs |
| `permission_revision` | Original registered writer lease revision |
| `expires_at_ms` | Human session expiry, no later than the original writer lease |
| `route.control_socket`, `route.codex_home` | Exact original registered Agentd paths |
| `route.agent_id`, `route.spawn_generation` | Original registered Agentd identity |
| `route.thread_id`, `route.app_server_session_id` | Existing original App Server thread/session |
| `can_interrupt` | Explicit trusted-launcher permission for this thread |
| `can_resolve_approvals` | Explicit already authenticated permission to answer original command/file callbacks; omitted defaults to false |

The launcher retains the UI child and opens its pidfd before any client
connection. It passes that descriptor by inheritance; the service checks
kernel credentials and the descriptor's actual PID/lifetime. The file is not
accepted from an ordinary UI lane and cannot create a human identity itself.

## Start the existing service and UI

Run the original entry with its original daemon pidfd on stdin and the
additional pre-held UI pidfd on an inherited descriptor numbered at least 3:

```text
hepta-authority-host serve-session \
  --config ORIGINAL_ROOT_CONFIG \
  --registration ORIGINAL_DAEMON_REGISTRATION \
  --owner-pidfd-stdin \
  --text-ui-registration AUTHENTICATED_UI_REGISTRATION \
  --text-ui-pidfd INHERITED_UI_PIDFD
```

The launcher starts UI first in the waiting state so it can retain that exact
child's pidfd. Before any intent is accepted, the worker retries that same
endpoint for ten seconds while Root binds its optional lane. If startup takes
longer or fails, UI Refresh retries the same endpoint and shows the actual
failure. Automatic startup retry never applies to already accepted/unknown
signed input. Desktop uses `TRILL_UI_CHAT_SOCKET` and `TRILL_UI_CHAT_ROOT_PID` only
as endpoint hints; its worker requires the actual UID0 peer and a successful
live Root hello. Those variables contain no principal, key, grant or thread.
The original Root session's bounded lifetime is unchanged by reconnect.

### Executable startup from existing authenticated inputs

The same `hepta-authority-host` binary provides these additional entry points:

```text
hepta-authority-host diagnose-native --config ORIGINAL_ROOT_CONFIG \
  --registration ORIGINAL_DAEMON_REGISTRATION --native-profile EXISTING_HUMAN_UI_PROFILE \
  --owner-pidfd-stdin
hepta-authority-host launch-native --config ORIGINAL_ROOT_CONFIG \
  --registration ORIGINAL_DAEMON_REGISTRATION --native-profile EXISTING_HUMAN_UI_PROFILE \
  --owner-pidfd-stdin
```

Both consume the original daemon pidfd on stdin. The Root0600 native profile
contains `schema_version: 1`, the absolute installed UI `program`, its trusted
`program_sha256`, `arguments`,
`working_directory`, bounded display/local-state `environment`, `socket_path`,
and the already authenticated `principal_id`, `session_id`,
`permission_revision`, `expires_at_ms`, exact `route`, `can_interrupt`, and
optional `can_resolve_approvals`. The identity/session must come from the
existing trusted human authentication provider. Neither command creates those
identities, issues a lease, opens a new Agentd/thread, or calls `initialize` or
`register-writer`.

The program must be a Root-owned executable without shared writes. The launcher
hashes it against the supplied release SHA256 and executes that same open inode
through `/proc/self/fd`, binding the captured UI pidfd to those verified bytes.
`environment` must include the canonical existing `TRILL_UI_MAKEPAD_RESOURCES`
directory. The actual UI independently verifies the original embedded asset
inventory before opening its native window. With draft recovery enabled, an
explicit canonical `XDG_STATE_HOME` owned by the UI UID is required; optional
`HOME`, `XDG_RUNTIME_DIR` and `XAUTHORITY` paths are also checked for ownership
and shared writes. `TRILL_UI_DRAFT_RECOVERY` accepts only `0` or `1`. No `LD_*`
or arbitrary loader environment override is admitted.

`diagnose-native` checks protected files, the original mount, exact daemon
lifetime/pidfd, route and supplied expiry. It does not open authority stores
and explicitly returns `production_ready: false`. `launch-native` starts only
the UI at the original daemon UID/GID with no groups/capabilities and
NoNewPrivileges, captures its actual pidfd/lifetime, writes one temporary
Root0600 process registration, and calls the existing open-only
`serve_host_authority_session_with_text`. It supplies the fixed Root PID/socket
to the UI. The UI initially waits; Refresh attaches once the original lane is
available (automatically during the initial bounded retry, otherwise with
Refresh). A rejected resource/program/profile fails with a diagnostic; it does
not substitute a mock UI or initialize authority. The temporary registration is retired when this Root session ends;
no durable authority record is created or replaced.

### Original provider account/login, separate from Hepta authority

An owner-user0600 `--route` file contains only the exact existing
`AgentdTextSessionConfig`. Running as that original daemon owner:

```text
hepta-authority-host provider-status --route ORIGINAL_AGENTD_THREAD_ROUTE
hepta-authority-host provider-login --route ORIGINAL_AGENTD_THREAD_ROUTE
```

These connect through original Agentd `session_ingress`, verify the private
App Server home and existing thread/session, and use the original
`account/read` or `account/login/start` (`chatgptDeviceCode`) APIs. The login
command prints only the original one-time challenge and waits for the matching
`account/login/completed`; the original AuthManager retains tokens. Status
prints provider kind and configuration state, never token/email/account ID.
It does not refresh tokens or claim that a model request will succeed.

The existing account API has no Hepta principal/session/permission revision.
Provider login therefore never enables native Send or approval by itself.
If the existing deployment is absent, the required external inputs remain:
the original pinned Root state/key/policy, current daemon registration and
writer lease/proof, independently retained AuthBus trust/checkpoint, an actual
authenticated human-session profile, the exact existing thread route, and
provider configuration in that Agentd's own private home. A credential file
under another user's home or an OS username supplies none of these authority
bindings. No example/fixture profile is installed as production authority.

`AgentdTextWorker::start_authenticated` receives the route from that hello,
connects through the original Agentd `session_ingress`, and verifies the
existing App Server session/thread/home before emitting `Authenticated`.
Only this event installs the original `ChatWorkspace::OwnerSession`.
`Connected` and ordinary Session/health observations never enable Send.

## Send, stream, cancel and recover

UI `Submit` prepares one exact Root signature. `Prepared` contains only the
original signature's correlation metadata. The shared original ChatWorkspace
must accept the exact text and return its original dispatch ticket before UI
queues `Dispatch`. Only then does the worker call
`AgentdClient::submit_authbus_text`. All later duplicate/unknown attempts use
the original retained envelope and status/Core `ReconcileOnly` lookup.

Original App Server notifications supply assistant text, tools and artifacts.
Tool/artifact representations are inert timeline observations, not UI-issued
effects. Original command/file approval callbacks appear in the native UI with
their actual request details. Approve once and Decline require the distinct
live `can_resolve_approvals` permission; text and interrupt permissions do not
imply it. The worker rechecks the live original Root receipt before answering
the original callback through `resolve_server_request`. A file change can be
approved only after its exact original proposed item is loaded for review.
Oversized or incomplete previews cannot be approved. No session-wide grant,
execpolicy amendment or network-policy amendment is exposed here.

The original App Server retains and replays pending callbacks on resume. The
single per-connection event reader remains alive while a file preview awaits
the original item API. Native poll/history/command timers receive through a
one-entry bounded, cancellation-safe channel; they cannot consume and then
drop an in-progress callback. Only explicit subscription shutdown, connection
replacement or dropping that subscription cancels its reader. The UI fences
their RoomKey, physical connection and original request ID, sends
at most one response per observed callback, and waits for the original
`serverRequest/resolved` notification before closing the prompt. A transport
write is not a completion/effect receipt. Other requests (provider credential
refresh, dynamic tools, MCP elicitation and additional-permission requests)
continue to require their own original registered client; an explicit visible
diagnostic does not disconnect the whole text stream or auto-answer them.
Cancellation uses the original queue delete/turn interrupt and is not shown
as completed until the original owner reports its terminal state.
An explicitly permitted cancellation with no original Core admission uses
the same durable `closeIfAbsent` binding immediately. The worker rechecks the
live original Root receipt and `can_interrupt` permission before this action;
it does not wait for signature expiry or create a replacement input.

Reconnect fences old physical subscriptions, preserves exact signed inputs and
reconciles them against the same original thread. Replayed deltas without an
original replay cursor are suppressed while authoritative turn snapshots are
used. Missing Root at startup or failed reconnect keeps the command worker
alive for explicit retry; it does not replace an unknown message identity.
The worker fences its stream when the authenticated Root session expires;
reconnect cannot extend that session or change its original authorization.

## Original history and live observations

Recovery reads the latest bounded page through the original App Server
`thread/turns/list` before enabling Send. The renderer's Earlier messages and
Latest messages controls invoke this same existing-thread API with its opaque
cursor. Each page has at most 16 turns and 256 KiB. The original App Server
continues to own the complete transcript; the UI replaces only its visible
page, preserving the local draft. Large pages are re-read from the same cursor
with progressively fewer turns. A single turn exceeding the preview bound is
shown as original `notLoaded` metadata with an explicit content notice and its
original next cursor. It does not block recovery, sending or earlier-page
navigation, and the stored content is untouched. Tool display text has an
explicit bounded preview marker if pretty printing alone expands it too far.

History controls are fenced by the authenticated owner, original stream,
current RoomKey and IME composition. While viewing earlier messages, new
observations leave that page stable and ask the user to return to the latest
page before sending. No UI-controlled thread ID or history cursor can select
another conversation.

The live subscription also projects original-thread activity produced by
another authorized producer. Such observations carry no local admission ID
and cannot acknowledge the desktop's unsent input. Once a complete turn
snapshot is read, its unsequenced notifications are suppressed; active
snapshot turns are refreshed from the original owner. New live turns continue
to use the original notification stream. This avoids replaying deltas over a
full snapshot without inventing a durable cursor or transcript owner.
Large individual notifications switch that turn to snapshot presentation;
they do not fence the original transport or change its durable identity.
Terminal reconciliation is independent of the display bound: original turn
metadata and the exact original UserMessage are read through `thread/items/list`
pagination. The returned metadata is labelled `notLoaded`, never falsely
claimed to contain the full tool transcript. Unknown or mismatched input
remains unresolved, regardless of what the display can show.

## Bounded references with durable retirement

At most 32 unresolved signature references occupy the original issuer record,
subject also to its exact total serialized byte budget. Each original bounded
text body is retained atomically with its signature and sequence; 32 maximum
8 KiB inputs cannot fit a 64 KiB record. Capacity is checked before signing or
publication, refuses the new intent, and preserves every original reference.
The same record retains a monotonic text-intent watermark, atomically with
each signature and the original signing sequence. New numbers may skip an
unissued gap; a missing number at or below the watermark can never be signed.
Thus removing a proven terminal reference cannot resurrect its old input.

Unsigned preparations have a separate bounded recovery outcome in the same
original record. A failure before the first request byte is written proves
only that attempt was never transmitted; only a first attempt can release its
local unsigned correlation using that proof. Once a write begins, partial
frames, timeouts, refusal replies and lost replies all remain unknown. The
worker calls the original Root `close_unsigned` operation with the same exact
namespace, intent number, current registered generation and text.

Root serializes that operation with Sign under its existing request lock and
issuer CAS. If the exact original signature exists it returns that same
envelope; the worker restores it for lookup only and never dispatches it.
Otherwise Root advances only its existing monotonic intent watermark and
returns a typed closed outcome bound to the request payload digest. Signing
sequence and every retained signature remain unchanged. A delayed original
Sign cannot issue that closed number, including after Root reopens its store.
Lost closure replies are retried against the same number. This adds no
signature journal or second ledger. The UI can release only an unsigned
matching local correlation; signed references still require the independent
terminal retirement path below, and local drafts remain intact. Periodic
unsigned closure and original signed-reference reconciliation alternate so
repeated refused preparations cannot starve the original retirement work.

The registered UI may page these original references one entry per bounded
reply, limited to its Root-derived principal/agent/thread namespace and the
hello watermark. Other namespaces cannot be requested. This is a read of the
same issuer record and never signs, submits or advances a counter. Older
hash-only records without an exact retained body fail closed and still need
their original retained input; no migration guesses text from a draft.

The native worker restores every recovered identity with lookup-only semantics
before projecting it into the existing ChatWorkspace owner. Recovery has an
explicit completion barrier; Send remains unavailable until that barrier.
Recovered text never replaces or clears a local draft, even if its bytes match.
Current authenticated principal/agent/thread must match; older generations may
be observed, but neither recovery nor reconnect issues a replacement input.

Root handles retirement by independently connecting to the registered
original Agentd/App Server and requiring its original Core terminal or
cancelled outcome. AuthBus lookup returns typed absence only after its original
independent replay-checkpoint checks; an absent row or a quarantine is never
itself proof of rejection. UI JSON cannot supply the retirement proof.

For an expired original signature with no Core binding, Root may use the
original Core `closeIfAbsent` operation. The same per-thread dispatch guard,
durable client-ID/payload reservation, and complete rollout scan atomically
retain the original cancellation tombstone. Existing queued/persisted work is
unchanged. A delayed original `allowIfAbsent` cannot revive that identity after
the original owner restarts. An AuthBus QueueAccepted observation with missing
Core state remains inconsistent and is not converted to a rejection.

Only an observed original terminal or durable cancellation permits retirement.
The same issuer CAS frees
only that reference, leaving AuthBus/Core history untouched and preserving the
watermark. Lost retirement ACKs are idempotent. Unknown outcomes remain
retained; neither TTL nor an LRU evicts them. UI separately acknowledges
receipt consumption before its transient worker correlation is released.

Tests distinguish protocol fixtures, original-store tests and actual
Agentd/App Server process tests. Fixture keys or model responses are not
evidence that a deployment has its real Root registration or model configured.
