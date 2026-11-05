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
| `--root-production-profile` | `android` (default), explicit `notes`, or the separate `desktop` Notes/Calculator candidate |
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
| `--desktop-production-handoff-fd` | Joint Session reservation/activation and ordered Notes then Calculator offers; required only for `desktop` |
| `--desktop-thread-deployment-fd` | Distinct Root-sealed Desktop profile, two actual targets and new original Core seed |
| `--desktop-session-pidfd` | Actual joint Session lifetime, independently pinned to the sealed process birth |

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

## Separate Notes and Calculator candidate

The explicit `desktop` profile requires all three Desktop descriptors and the
same original Root handoff/control/App Server/owner inputs. It rejects Android
parameters and all legacy Notes descriptors, including the Notes UI listener.
The dedicated `PrimaryInputs::Desktop` branch does not reinterpret a Notes
deployment or attach Calculator under a Notes target identity.

The trusted Root caller uses
`PreparedHostAuthoritySession::with_desktop_startup_from_session_before` with a
`hepta.root.desktop_launch_profile.v1` profile whose `profile` is exactly
`notes_calculator_v1`. The actual Session reservation supplies both targets
and a nonce. It is metadata, not application rights or an attachment ACK.
Root validates the actual Session sender credentials, held pidfd and target
pair before sealing the late deployment.

The child inherits a separately opened read-only descriptor before Root fills
the deployment. Root must finish and seal the producer before its late handoff;
the child reads only after authenticating that original handoff and its lanes.
The loader requires the original unlinked, Root-owned `0400` four-seal file,
at most 16 KiB, and the actual post-drop owner. Its strict fields are:

| Field | Required value |
| --- | --- |
| `schema`, `profile` | `hepta.agentd.original_desktop_launch.v1`, `notes_calculator_v1` |
| `agent_id`, `spawn_generation` | Exact original Agentd Registry/Config identity |
| `session` | Actual `uid`, `pid`, `boot_id`, `process_start_ticks`, independently checked against the retained Session pidfd |
| `bindings` | The same ten original fields listed for Notes below: scope, scope digest, issuer, policy generation, locale and five input digests |
| `startup_release` | Required exact `notes`, `calculator`, `nonce`; task IDs 1 and 2, same Session instance and distinct application incarnations |
| `interaction` | Required `kind: original_desktop_thread_tool_v1`, actual `route` and `DesktopThreadSeedReceipt` |

Unknown fields, an absent/null required interaction, a legacy Notes seed or
`previous_recovery` are not supported. The new seed must match the actual
six-tool SessionMeta, execution configuration and observed model/provider
tuple. Its data does not authorize a model turn or replace the original human
admission. Existing Notes threads and their three-tool catalogs are unchanged.

`attach_root_desktop_operation_host_with_startup_before` receives the launcher's
original absolute `CLOCK_BOOTTIME` deadline. It recovers the same protected
writer once, verifies its live authority, activates the sealed reservation and
accepts Notes's original two-descriptor offer/ACK followed by Calculator's.
Notes uses the original Notes FinalUse consumer; Calculator uses the original
Device consumer with its distinct exact admission. The original atomic host
installer publishes the composition after both handoffs and live checks.
`with_root_desktop_thread_tools` installs the six-tool Core callback runtime on
that attachment. The launcher retains the entire
`AgentdDesktopProductionAttachment { root, calculator }` until `run` ends.

One 30-second budget is created while parsing the `desktop` inputs and is
checked through Root preparation, late handoff, deployment loading, protected
recovery, activation and both attachment phases. Shorter phase limits cap that
deadline. Successful I/O and ACKs are checked again before being accepted; a
late response cannot reset the budget. The original Session's independently
bounded reservation still has to be alive. The new effect path similarly
carries its total preparation/admission budget through retained writer and
sender work; late acknowledgement leaves the existing result unknown and
does not create another dispatch opportunity.

This is a finite session under the existing Root lifetime maximum of
300,000 ms. It provides no issuer-renewal service, epoch continuation or
qualified joint product restart. Use the new profile only with the matching
Desktop Root/Session implementation and a newly seeded original thread. See
[the candidate handbook](DESKTOP_ORGAN_CANDIDATE.md) for source ownership,
verification commands and the current unexecuted joint-runtime gates.

## Startup and retained lifetimes

The Root text-UI lane accepts one frame per connection. Each accepted connection
uses the smaller of its existing exchange timeout and the remaining Root
lifetime, including the wait for the first byte, complete frame, handler and
response. Receiving the first byte does not grant a new budget. An idle Shell
connection therefore cannot retain this worker for the whole Root lifetime
after Agentd exits; the lane checks the original daemon pidfd again after the
bounded exchange. An already running handler is not forcibly cancelled. Its
existing authority checks and the peer channel's post-handler deadline checks
still determine whether any response can be accepted. This does not renew the
writer or issuer, change peer admission, or qualify a product recovery run.

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

The sequence above describes the existing Android/Notes branches; the joint
Desktop branch has the separate ordered startup specified above.

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

## Notes adapter and sender checkpoint deadlines

The literal Notes UI, original Notes thread and joint Desktop thread all enter
the same `AgentdConfig::with_root_notes_adapter` composition. Their production
launcher passes the existing ten-second adapter duration. The shared adapter
validates a nonzero duration of at most ten seconds and retains that exact
value for its original preparation, human verification, control-query and
retained-view checks.

The original Objective sender has a separate checkpoint limit of five seconds.
The adapter supplies `min(adapter_duration, five_seconds)` only to
`original_objective_sender`; the adapter's own duration remains unchanged.
A shorter caller duration stays shorter. The original sender still rejects a
zero checkpoint duration, a duration above five seconds, an invalid process
generation or rejected live authority. No Memory limit, retained-request quota,
Root lifetime, source expiry, IPC exchange limit or enclosing deadline changes.
Cancellation and late acknowledgement keep their existing unknown/fencing
semantics; this selection does not restart a call or permit another send.

The installed Desktop `6533247104f3cdbf9c9ef68ac5369eb097467244` /
Hepta `14e2d89b3367232ec5dbe6187f09feed0f2b68d3` diagnostic exposed the
old composition passing all ten seconds into that five-second constructor.
The original Agentd exited with code 1 before Supervisor cleanup and reported
`Objective sender input exceeds its retention profile`. The private original
diagnostic SHA256 is
`f1ba41c2bdced7cf3073d17fc19434d686101c0f024c03d133e11fc9fba82b0d`.
This failure concerns the constructor's duration bound, not a full request
ledger; increasing request retention or the sender's limit is not a repair.

Owning package tests and lint remain required. The production regression gate
is the same installed Root-to-launcher-to-adapter path with its original
ten-second adapter duration, followed by actual Notes and joint application
acceptance on one new, source-bound product pair. Formatting, source review or
a test checkpoint provider cannot stand in for that result. The historical
installed failure remains retained until the new run produces its own evidence.

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

Previous Notes recovery accepts `selector: {"kind":"exact_operation",
"operation_id":"..."}` or `selector: {"kind":"latest_recorded_original_notes"}`.
The legacy top-level `operation_id` is accepted only without `selector`. Unknown
fields and mixed selections are rejected. The canonical writer is opened first;
original-thread seed and Session guards are installed before
`with_original_notes_previous_recovery_request` resolves a latest selection
through the complete protected sender cut. It must match the same original
thread/model/principal and exact previous target in Indeterminate/Committed
state. The existing helper receives only the resolved exact operation; absence,
legacy missing reference or ambiguity creates no fresh operation or authority.
