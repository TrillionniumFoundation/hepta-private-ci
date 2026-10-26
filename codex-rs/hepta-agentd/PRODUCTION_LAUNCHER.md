# Original Root and native Runtime launch

`codex-hepta-agentd` has an explicit Linux production entry. Its ordinary
environment launch remains the ordinary Agentd path. The production entry uses
the original Registry Starting record, Config, writer lock, authenticated Root
session, protected checkpoint, Device/Notes FinalUse consumers and original
configured MCP machinery. It does not initialize those authority owners from
CLI values or ordinary JSON.

## Original capabilities supplied by the trusted launcher

The trusted Root process creates an unnamed `UnixDatagram::pair` before starting
the child. Root cannot seal the final consumer bootstrap before that child
exists: it includes the child's actual PID and process start time. After the
child has prepared its original Config and dropped to its dedicated owner, Root
publishes the original fresh state, captures the original sealed bootstrap and
transfers the sealed file plus its already retained Root pidfd in one
`send_root_production_handoff` message. The child does not rediscover a Root PID,
parse an authority pathname, or recreate a lease.

The two original public Agentd sockets are bound by Root and inherited without
listening. The actual Agentd owner validates and listens on those descriptors
after dropping credentials. This preserves Root custody of `run/` and the
Registry lifecycle while the peer credentials identify the actual Agentd. A
Root-listening socket would carry the wrong peer credentials. The production
path must not unlink and rebind those paths as the Agentd user.

The Linux implementation is `bind_root_agentd_socket` → inherited FD →
`AgentdConfig::with_root_bound_sockets` → the original `RuntimeTasks` control
and App Server workers. Root's bind helper creates only a new Unix stream
socket, sets that socket node to the dedicated UID/GID and `0600`, and returns
without calling `listen`. It refuses existing paths and never changes a
directory. Root retains pathname cleanup. Its parent chain must be canonical,
Root-owned and have no group/other write permission; ordinary shared `/tmp`
does not qualify, even with a private descendant.

The child retains the original Root-created socket inode and validates the
exact original control/App Server path, the private node, an unconnected stream
type and `SO_ACCEPTCONN=0`. The shared original credential validator requires
all real/effective/saved IDs to equal the dedicated owner, no supplementary
groups or capabilities, and NoNewPrivileges. Runtime then calls
`listen_root_bound_socket` as that owner and adopts the descriptor through
`codex-uds`; a descriptor already listened on by Root is refused. The same
function supplies the fixed Notes UI path. The actual socket pathname and
protected parent are rechecked around listen without modifying either.

App Server enters `run_main_with_inherited_unix_listener`, the same original
runtime with an explicit retained listener. It skips ordinary path preparation,
stale-path probing, binding, permission repair and pathname cleanup. The
original Agentd control server also leaves Root paths intact. Both inherited
control transports admit only the dedicated UID or actual UID0 supervisor
before reading protocol bytes, preserving Root's existing private-path access.
The Notes UI separately keeps its stricter exact Session PID/UID/pidfd gate.

The inherited App Server entry retains a shutdown guard across its fallible
startup. If authentication/configuration startup fails after the acceptor was
spawned, or the embedding cancels its future, the original cancellation token
closes the acceptor and its active or incomplete WebSocket connections. The
original WebSocket worker handles abort their child read/write tasks on drop,
including tasks blocked in I/O. Merely dropping a JoinHandle would detach
those tasks. None of these exit paths unlinks the Root rendezvous. Root must
close any producer copies after transferring the child descriptors, so a
producer copy cannot extend a failed or departed child's listener lifetime.

The socket descriptor's creator UID, its exact bound address and exclusive Root
pathname custody establish this handoff boundary. Linux socket-fd inode numbers
and filesystem socket-node inode numbers are different and must not be compared
as if they were the same inode. The unprivileged consumer does not use
`SIOCUNIXFILE`, whose kernel implementation requires `CAP_NET_ADMIN`; it never
regains that capability. Root remains the trusted pathname owner and must not
replace its rendezvous behind the retained descriptor.
Linux documents the credential capture points in
[unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html); its
[AF_UNIX implementation](https://github.com/torvalds/linux/blob/master/net/unix/af_unix.c)
captures the current process credentials in `unix_listen`. Target-machine tests
of this exact inherited-descriptor implementation are still required.

The fixed Android payload is a read-only, unlinked, Root-owned `0400` memfd with
all four original seals. It contains the exact existing `AndroidSetTextV1`, not
an authority grant. The trusted launcher must first qualify the original
Runtime host/peer, deployed fixed helper, Droidloom owner, installed candidate
APK bytes and original signer, then obtain the native observation for that
payload. A current APK matching the old baseline alone does not qualify the
strict candidate receiver. The source and signer gates in
[PRODUCTION_ANDROID_TEXT.md](../hepta-memory/PRODUCTION_ANDROID_TEXT.md) still
apply before this descriptor is issued.

| Flag | Existing input represented |
| --- | --- |
| `--root-production-profile` | `android` (default) or explicit `notes`; each selects a real primary target |
| `--root-production-handoff-fd` | The inherited unnamed Root pair, consumed once |
| `--root-production-uid`, `--root-production-gid` | Dedicated, nonzero original Agentd owner |
| `--root-production-control-fd` | Original Root-bound, not-yet-listening control socket |
| `--root-production-app-server-fd` | Original Root-bound, not-yet-listening App Server socket |
| `--android-runtime-server` | Name of one already enabled server in the Agent's effective MCP config |
| `--android-runtime-environment` | Exact original environment ID of that server |
| `--android-original-payload-fd` | The immutable original Android proposal and observation |
| `--android-original-deadline-ns` | Original absolute host `CLOCK_MONOTONIC` deadline, at most 30 seconds away |
| `--root-production-lifetime-ms` | Bound on the retained Root session, default/max 300,000 ms |
| `--notes-production-handoff-fd` | Original Session Notes application handoff; required for `notes`, optional for `android` |
| `--notes-literal-deployment-fd` | Root sealed finite Notes bindings and actual Session peer, with optional original previous-store recovery |
| `--notes-literal-ui-fd` | Root-bound UI listener at this original Agent's `run/notes-objective.sock` |
| `--notes-session-pidfd` | Already retained actual Session lifetime; not a numeric PID discovery request |

All required flags must be supplied together; repeated flags, shared descriptor
numbers, standard-stream descriptors and an expired/oversized deadline are
rejected. No URL, token, shell expression, new signer, generated operation ID or
replacement authority file is accepted. Original daemon configuration flags
continue to configure their original owners and admission policies.

The explicit `notes` profile requires all four Notes descriptors and rejects
Android parameters. It uses the actual inherited Notes target as its sole
primary, the original Notes FinalUse owner and the same protected writer. It
does not initialize a Runtime MCP session or require a device payload. The
five-lane Root receiver still authenticates its original consumer owners; an
unused original Device owner does not become a fabricated device destination.
Notes startup has the handoff's existing 30-second bound, while each later
Notes action retains its own original protected source/sender deadline.

## Startup and retained lifetimes

1. Original arg0 helper dispatch runs first. A synchronous preflight then takes
   the inherited descriptors and opens the original environment Config. The
   original Root preparation retains the same lock FD while temporarily
   releasing the lock for fresh publication.
2. In that same sole thread, the prepared Config drops all process credentials,
   groups and capabilities to the original owner and sets NoNewPrivileges.
   The same thread waits for the one original late handoff after Root finishes
   the original filesystem handoff. Helper aliases and the Tokio runtime are
   created afterwards, under the final owner with actual home access. A process
   that already has multiple threads is rejected.
3. The child authenticates the Root pidfd and sealed bootstrap and connects all
   five original Root lanes before
   requesting any observation. It activates the two original FinalUse owners,
   obtains the opaque current-cut token, and finishes the original Config on
   the same writer lock FD.
4. For `android`, `initialize_configured_mcp_server` uses App Server's original ConfigManager,
   AuthManager, environment registry and McpRuntime. It initializes only the
   explicitly selected, already configured server and freezes its ready
   binding. This is the original manager's new production-startup session; it
   is not an existing ChatGPT connector or an already running thread peer.
5. `AgentdAndroidRuntimeInputs::from_mcp_binding` retains exactly
   `process_start`, `process_wait` and `process_read`, subject to the original
   catalog and environment fences. All three must already have explicit
   unattended approval in the effective original MCP policy. This entry does
   not convert an interactive approval policy into an unattended one.
6. For `android`, the real Android target is the primary target of
   `attach_root_production_operation_host_with_startup`. Optional Notes is
   attached through its original Session channel before the same recovered
   writer is published. For `notes`,
   `attach_root_notes_operation_host_with_startup` receives that same original
   Root input bundle and uses the actual Notes target as the only primary.
   A staged Session reservation is activated once at this point, using the
   actual target and nonce retained by Root in the sealed Notes deployment.
   The original `run` then owns control/App Server and the operation runtime.
   The launcher retains the Root attachment and MCP manager until it exits,
   invalidates the one-shot Android effect lane and closes the original MCP
   session on normal/error completion.

The native Android deadline is never restarted during this sequence. Slow
Root/MCP startup may use up the original budget and fail before any action.
The concrete target represents one operation. It cannot become a general
remote shell or a multi-operation device controller after that deadline. Lost,
late, revoked or disconnected effect replies remain unresolved and do not
cause another POST, Runtime launch or native effect.

This entry registers the Android destination; registration does not prepare or
dispatch the payload. The existing durable writer and admitted Objective path
must retain that exact original operation before the original Device FinalUse
can enter it. The Notes literal Objective adapter described below is specific
to Notes and is not an Android operation caller. Until an original Android
Objective preparation/dispatch caller is connected and exercised, this entry
alone must not be reported as end-to-end Android control.

The retained HTTP capability disables the original SDK session reinitialization
and underlying replay mechanisms on that same transport. Static original
authentication is preserved. Managed OAuth refresh, opaque dynamic auth and
unsupported transports are refused for this one-shot effect capability; they
are not replaced with unauthenticated requests or newly resolved credentials.

## Notes and completion evidence

The application handoff alone supplies a Notes target and read-only observer.
With the three UI descriptors, the same caller configures
`with_root_notes_literal_adapter`, then `with_original_notes_ui`. The actual
Agentd owner listens on the inherited UI socket, and the original `RuntimeTasks`
owns its required task and shutdown. There is no second daemon or writer. The
Session's existing `ObjectiveCommand`/`ObjectiveObservation` wire remains the
UI boundary: it supplies navigation ID/text, never signed ingress or authority.

The read-only, unlinked, Root `0400` four-seal deployment file is at most 16 KiB
and has the following exact configuration fields; unknown/duplicate fields
reject. It is public deployment data, not a substitute for the separate live
Root authority handoff.

| Field | Required original value |
| --- | --- |
| `schema` | `hepta.agentd.original_notes_launch.v1` |
| `agent_id`, `spawn_generation` | Exact original Registry/Config identity of this launch |
| `session.uid`, `session.pid`, `session.boot_id`, `session.process_start_ticks` | Actual Session identity pinned by the separately inherited pidfd |
| `bindings.principal_scope`, `bindings.principal_scope_digest`, `bindings.issuer_id` | Original finite profile and issuer identity; the configured profile file must equal the shared literal Notes compiler profile |
| `bindings.policy_generation`, `bindings.locale` | Original nonzero policy generation and the admitted `en-US` or `zh-CN` locale |
| `bindings.runtime_body_digest`, `bindings.preference_state_digest`, `bindings.model_tuple_digest`, `bindings.prompt_registry_digest`, `bindings.artifact_set_digest` | Exact retained runtime/artifact inputs; no default, zero digest or invented no-model identity |
| Optional `previous_recovery` | Exact original `helper`, `helper_sha256`, `state_directory`, `previous_target`, `operation_id`; no directory discovery or new old-incarnation effect permission |
| Optional `startup_release` | Actual `target` and `nonce` from the original Session's staged reservation; no replacement target or generated nonce |
| Optional `model_route` | Existing original `thread_id`, `app_server_session_id`, the same `principal_scope_digest`, and `registered_tool_schema_sha256`; absent/null leaves the model Notes route unavailable |

The original Session bridge requires both private socket owner and peer UID to
equal its own UID. Therefore this profile uses the same dedicated UID for
Session and Agentd. The server independently pins the real Session PID, start
identity and lifetime on each accepted connection. It authenticates the original
control peer and Objective capability before preparing any new action, so a
startup gap is unavailable rather than an ambiguous attempted submission.

The same original writer prepares the literal operation, the retained Root
signer signs its typed Objective ingress, and the original sender retains it
before one authenticated control submission. Responses are retained through
that same sender. A repeated UI ID reads the original request/observation and
does not reissue it. The UI worker preserves the existing bounded action queue
and metadata-only observations. The original operations runtime also attaches
the current application's read-only previous-receipt channel. When the sealed
descriptor explicitly selects an older independent store, its existing
hash-bound recovery helper is attached through the original runtime; that old
target never becomes a dispatcher.

A real application commit and Root durable terminal checkpoint remain required
for completion. An application handoff ACK is not a Notes write receipt. A
configured chat socket also does not create that route. The Root service must
have registered this actual Session target with its retained original Notes
grant route before any effect can be admitted.

The original Session application offer allows two seconds for its attachment
ACK. Its explicit staged startup mode first holds the actual Notes endpoints
and sends only a reservation containing the real target and nonce to Root.
Root uses that reservation to register its original Notes grant route and fill
`startup_release`; no effect descriptor or attachment ACK is created by the
reservation. The launcher reads this sealed deployment once before composition
and passes its release to the protected factory. Only after Root recovery and,
for `android`, original MCP readiness does the factory send the matching
activation and receive the original two-descriptor offer. The independent
30-second reservation wait does not extend the original two-second offer/ACK
or any effect deadline. A missing or expired reservation fails closed. The old
nonstaged input continues to use its original offer deadline.

The Root late handoff is also the barrier before reading the Notes deployment.
If Root creates that deployment after the Agentd child exists, it must complete
and seal the original memfd before sending the late Root handoff. The child
inherits only an independently opened `O_RDONLY` descriptor; `dup` of Root's
`O_RDWR` producer descriptor would retain write access and is refused during
the child's preflight. Root can open `/proc/self/fd/<producer>` read-only before
the child drops credentials, then pass the two descriptions only to their
respective owners. The child cannot fill or reseal deployment data. The same
read-only input requirement applies to the sealed Android payload. Actual
process PIDs, births and pidfds remain mandatory at each boundary.

No test fixture, source compilation, listening socket or successful MCP
initialization proves a real device effect. Qualification must separately
record the original helper/receiver/signature deployment, source-bound Runtime
peer, actual Root writer/human policy and the exact native effect plus retained
terminal. Missing external inputs remain explicit startup/qualification errors.

## Existing-thread Notes model route

The original Root producer is
[`PreparedHostAuthoritySession::with_notes_startup_from_session`](src/root_notes_startup.rs),
selected by `hepta-authority-host serve-fresh-session --notes-launch-profile`.
The same protected `hepta.root.notes_launch_profile.v1` file can carry optional
`model_route` data. Root checks the route before consuming the Session
reservation or registering its existing Notes policy, then copies those exact
four declared values into the original sealed deployment. Missing or null
`model_route` remains absent; it never selects a default thread or creates one.
An incomplete, unknown-field, duplicate-field, different-scope or different-tool
declaration is rejected before that startup side effect.

The trusted launcher may obtain `thread_id` and `app_server_session_id` from
its already authenticated `HostAuthorityNativeProfile.route`, after checking
that this route names the same original Agentd/private home and human session.
That text profile alone does not contain the Notes principal-scope binding or
the registered tool definition. Both must already exist in the original trusted
registration material. The launcher must supply their exact evidence in the
Notes profile; copying the fixed tool hash without that registration does not
make an unregistered thread eligible. The producer reads no renderer-selected
route, provider credential or socket/PID hint to fill missing evidence.

Desktop's `ui/session/src/notes_bootstrap.rs` supplies only the actual Notes
target, reservation nonce and inherited application channels. It does not
produce this deployment JSON. The ordinary installed user-service startup in
`support/ui/product/desktop.py` starts `trill-session` without the trusted Root
bootstrap descriptors; its optional chat socket/PID also does not create them.
An authorized production launch must enter the existing Root staged handoff
with the registered original profile and Session lifetime. This wiring does
not turn a normal user-service launch into a Root deployment or constitute
installed-product acceptance.

`model_route` is an optional extension of the same sealed deployment. It has
exactly the four fields listed above. It cannot override the Agent ID,
generation, control socket, private home, issuer or Notes target. Runtime derives
those values from its actual original Agentd identity and keeps the unique
Notes adapter. The model route's principal digest must equal the existing
finite Notes profile's human scope. The trusted launcher must establish that
this is the same already authenticated human/session represented by the
existing native text profile; an equal digest supplied by a renderer cannot
establish that mapping.

The fixed tool is `trill_notes.propose_replace` with only `{ "text": "..." }`.
The complete registration definition is
`AgentdNotesModelRoute::TOOL_DEFINITION_JSON` in
[notes_model_route.rs](src/notes_model_route.rs). The sealed schema digest is
SHA256 of those exact UTF-8 bytes, without an added newline. The original tool
registration must contain this definition. The host additionally rejects
unknown argument fields, blank text and text exceeding 4096 UTF-8 bytes; the
JSON Schema character limit is not a replacement for this byte limit.

The declaration must come from the original trusted launcher's retained
thread-registration material. Computing the expected hash alone does not prove
that a live thread registered the tool. The current App Server protocol accepts
`dynamicTools` at `thread/start`; `thread/resume` cannot install them and its
response does not expose their schema for introspection. Missing registration
evidence therefore leaves this field absent and the model Notes route
unavailable. No existing thread is replaced or silently re-registered. The
checked-in source fixtures and historical acceptance receipts do not supply a
production human profile or an actual registered model-tool route.

The launcher only injects these validated inputs using
`AgentdNotesUiRuntime::with_model_route`. Connection belongs inside the existing
required runtime task after original control/App Server startup. It resumes
the declared thread through the original Agentd ingress and checks its actual
thread/session/home identity, with bounded startup and reconnect behavior.
No model turn, signature or device operation is implied by attachment.

Each observed call remains owned by the original App Server. Its thread, turn,
call ID and exact arguments are retained only in bounded transient state for
human review. A confirmation names that original proposal and preview digest;
it does not supply new text, a target or a callback ID. The same original Notes
adapter rechecks the preview with `prepare_reviewed` before preparation/signing
and uses its once-only sender. Recovery uses the stable original call-derived
intent and original operation/receipt APIs; it does not regenerate an effect
after an unknown result. A tool response write is not effect or callback
completion: the original `DynamicToolCall` completed item/history supplies the
callback result, while the original Notes terminal receipt supplies the
application effect evidence. Dynamic tools do not emit the command/file
approval lane's `serverRequest/resolved` notification.

### Original identity and recovery observations

The stable model intent is derived from the persistent Agent ID, human scope,
original App Server session, thread, turn and call ID. Arguments and transport
generation are excluded: changed text for the same original call must conflict
with its first retained operation. The separate preview digest binds the exact
replacement and the reviewed target, revision, previous text digest and pending
receipt state. Ordinary literal UI submissions cannot use the reserved
`model-` intent prefix to bypass review. A recovered operation has no fresh
review permission; its preview can be absent, while its original identity stays
available for observation.

The finite terminal observation budget starts again when the human confirms and
the original preparation begins. Time spent reading a preview does not consume
that settlement budget. A missing or source-only rejection receipt produces an
unknown application outcome. The response explicitly does not authorize another
effect or a replacement call.

`model_proposal.result` and its receipt digest describe the original callback
response. A later application receipt is projected separately as
`model_proposal.owner_terminal`; it never rewrites an earlier unknown answer or
causes a second tool response. The existing `Status(client_intent_id)` also
returns an optional top-level `notes_terminal`, read directly from the original
writer before sender/control reconciliation. This path works after the owner
reopens even if the completed callback is no longer replayed. It reconstructs
neither a model call nor a sending permission. Both terminal projections carry
the exact original operation ID, application receipt digest and event identity.
Previously observed terminal evidence is immutable under the same intent ID.

There are at most eight transient tracked proposals. A completed callback with
an unknown application outcome keeps its original lookup slot; it cannot be
silently evicted for another call. Capacity exhaustion returns an explicit tool
refusal while the existing operations remain observable. A private admission
state records whether original preparation may have started. A callback closed
before any preparation can release its preview slot; once preparation may have
started or an original retained operation is observed, its slot remains until
exact original terminal evidence is available. No absence lookup can reset
that state or prove that an earlier effect did not occur.

Temporary model socket failure marks the model route unavailable and retries
only the same sealed route with bounded backoff. Original writer receipt reads
remain independent of model connectivity. Root authority or Session lifetime
loss still fences the managed owner through its existing checks. After an App
Server process loses a pending callback, receipt recovery cannot fabricate the
missing callback or append a result to a different model turn.

The added regressions use the original SQLite writer, original Notes Objective
fixtures (including lost application replies), prior-receipt reconciliation,
and an actual App Server with a mocked model. They do not establish a real human
authorization, production model invocation or final installed-package result.
Those require the sealed production profile and original thread-registration
material described above.

## Development verification

Use the repository's `just test` entry, with separate scopes for the layers:

```text
just test -p codex-mcp retained_binding
just test -p codex-uds --lib inherited
just test -p codex-app-server-transport --lib inherited_socket
just test -p codex-app-server --lib configured_mcp_runtime
just test -p codex-hepta-agentd --lib production_launcher
just test -p codex-hepta-agentd --lib android_runtime
just test -p codex-hepta-agentd --lib notes_ui
just test -p codex-hepta-agentd --lib notes_literal
just test -p codex-hepta-agentd --lib notes_model_route
```

Build the actual `codex-hepta-agentd` binary as well: its manifest deliberately
sets `test = false`, so a passing library test does not compile the main entry.
Run `just fmt` and the changed-crate `just fix` as required by the repository;
dependency changes also require the original Bazel lock update. Record actual
commands and exit states instead of inferring success from a quiet log.

The ignored
`root_bound_socket::tests::original_root_bound_listener_preserves_peer_identity_and_path_custody`
is a separate actual-Root component check. Give it `HEPTA_SOCKET_TEST_ROOT`
pointing to an explicitly isolated, traversable Root-owned parent with a short
path (for example a newly provisioned directory beneath `/run`). It creates
only its own temporary fixtures and launches the same test executable through
the existing `/usr/bin/setpriv` to dedicated fixture UID/GID 60001 with zero
groups/capabilities and NoNewPrivileges. It checks the actual child's
SO_PEERCRED UID/GID/PID, the original UDS exchange, unchanged Root directory and
socket nodes, peer unlink denial, wrong-path refusal, and rejection of an
already Root-listening descriptor. Ordinary non-Root source tests do not run or
qualify this ignored check. It is not a Root authority, application receipt or
production device-effect qualification.
