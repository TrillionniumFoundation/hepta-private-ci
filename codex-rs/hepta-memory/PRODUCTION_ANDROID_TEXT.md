# Original Android text target: development and technical contract

## Scope and current qualification

`ProductionAndroidTextTarget` adapts one explicitly qualified original Android
editor to the existing `ProductionFinalUseOutboxDispatcher`. It neither opens a
writer nor issues authority. It is not registered by default Agentd startup.
The original host must supply its existing production lease/verifier, FinalUse
authority and grant provider, and the already retained device capability.

The matching [Desktop receiver manual](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/blob/main/support/android/receiver/README.md)
lives beside `support/android/receiver/`: it patches
the same original Pocket4 fixed helper and the same original ActionRunner APK.
There is no new runtime, device discovery service, ADB route or operation DB.
That manual supplies source generation, actual SDK, preserved APK resources,
original signer, installed-byte and rollback gates. Resolve it at the exact
Desktop source-profile commit for execution; the link itself is not a pin.

Source qualification includes the synthetic cross-language wire fixture,
owner-adapter cases, retained MCP HTTP/session failure cases, and the concrete
Agentd connector exercised against the original Runtime process wire contract.
Compilation, protected FinalUse/owner runtime composition and real device
effects must be recorded separately. A
trait implementation or synthetic reply does not establish a trusted host,
original helper/source pin, package signature, peer identity or live grant.

## Development map

| File | Responsibility |
| --- | --- |
| [src/production_android_wire.rs](src/production_android_wire.rs) | Bounded canonical native observation and exact text payload |
| [src/production_android.rs](src/production_android.rs) | Original intent, typed device seam, synchronous FinalUse destination |
| [src/production_android_response.rs](src/production_android_response.rs) | Actual apply acknowledgement and independent native readback validation |
| [src/production_android_tests.rs](src/production_android_tests.rs) | Exact bytes, no deferred entry, lost ack, stale/changed identity regressions |
| [tests/fixtures/android-bound-text-v1.json](tests/fixtures/android-bound-text-v1.json) | Python-generated UTF-8/hash fixture, explicitly synthetic |
| [hepta-agentd/src/deployment_notes_route_tests.rs](../hepta-agentd/src/deployment_notes_route_tests.rs) | Original issuer routing with Notes installed, exact non-Notes policy/lease, and no fallback after Notes denial |
| [hepta-agentd/src/android_runtime.rs](../hepta-agentd/src/android_runtime.rs) | Concrete retained device capability and recovered-writer bootstrap |
| [hepta-agentd/src/android_runtime_job.rs](../hepta-agentd/src/android_runtime_job.rs) | Fixed `process_start` entry, bounded original job wait, lossless terminal stdout |
| [hepta-agentd/src/android_runtime_tests.rs](../hepta-agentd/src/android_runtime_tests.rs) | Actual MCP wire faults, lost start, deadline, invalidation and independent read job |
| [rmcp-client/src/retained_tool_session.rs](../rmcp-client/src/retained_tool_session.rs) | Original peer lifetime, hard call deadline, no reconnect/replay |
| [rmcp-client/src/retained_tool_session_tests.rs](../rmcp-client/src/retained_tool_session_tests.rs) | HTTP 404/401/502, delayed reply and original-session closure |

Run from `codex-rs` with the repository toolchain:

```sh
just fmt
just test -p codex-hepta-memory production_android
just test -p codex-rmcp-client --lib retained_tool_session
just test -p codex-hepta-agentd --lib android_runtime
just fix -p codex-hepta-memory
just fix -p codex-rmcp-client -p codex-hepta-agentd
```

The focused cases do not launch Android. Original device acceptance must use
the separately recorded native runner/helper sources and the actual original
host capability. Agentd now uses the existing `codex-rmcp-client` and workspace
`base64` crates; update the Cargo and Bazel dependency locks with this change.

## Payload and recipient identity

`AndroidSetTextV1::from_json` accepts at most 16 KiB of exact canonical UTF-8.
Unknown/duplicate fields, noncanonical JSON, malformed native identities,
inconsistent node hashes, text over 4,096 UTF-8 bytes, and invalid original
StableId characters reject. Every serialized struct is ordered lexicographically
to match the Python and Java receiver. Chinese text and emoji retain exact
UTF-8 bytes.

The observation binds the actual host boot/init/namespace generation, target
application PID/start time, focused WindowManager token/activity/bounds, exact
resource/class/bounds/prior-text node hash, native pixel-scope hash and monotonic
time. `atomic_snapshot=false` is required. Numeric PIDs alone are insufficient.

The canonical scope object has exactly `application`, `generation`, `package`
and `resource_id`. Its SHA256 is both the operation scope digest and the suffix
of `pocket4.android:<scope-sha256>`. That 79-byte destination fits the original
128-byte StableId bound. Different incarnations or different editors cannot
collide by merely reusing an application name. The complete immutable native
observation, replacement text and original expiry are included in the payload
digest and original semantic operation digest.

The original `OperationIntentV1` contains no destination-transaction predecessor
capability. Android accessibility can re-read preconditions immediately before
performing the action, but it does not expose an atomic compare-and-set with
application state. Claiming the Notes CAS contract here would be inaccurate.
Any supplied `expected_predecessor_sha256` is therefore rejected by this target.

## Original owner composition

The existing trusted host obtains a native `organ-observe` response through
the original qualified helper capability. It validates that reply's actual
host/source/package identity and creates the target with the native observation
and an `Arc<dyn OriginalAndroidTextDevice>` supplied by that same host. It can
attach the target using the existing
`AgentdProductionOperationRuntimeConfig::with_additional_target`, together with
the original corresponding FinalUse authority. No second writer is opened.

For a proposed text change, construct the canonical payload, call
`android_text_operation_intent` with the original subject and policy generation,
and persist that intent plus the same payload using the original writer's
`prepare_operation` path and topic `hepta.android.set-text.v1`. Dispatch remains
through the original queued receipt and FinalUse dispatcher. Do not call this
target directly as a replacement for original authorization.

`OriginalAndroidTextDevice` is an explicit bootstrap boundary, not an ambient
shell or a discovery mechanism. Its implementation must use the already
authorized original Runtime/host connector, preserve its peer/host and fixed
tool/source pins, send only the provided fixed-helper operation, and perform
bounded synchronous calls without reconnect/replay. `apply` accepts only
`organ-set-text`; `readback` accepts only `organ-readback` and must start a
separate read-only invocation. The adapter passes the exact original payload
base64 and SHA256 in both calls. Changing operation identity, rebinding a
deadline or routing to a fresh cell is forbidden.

The concrete connector below accepts the original retained peer capability.
A hostname, user request, JSON boolean or synthetic grant cannot establish
that peer's qualification. Its measured deployment remains required composition
evidence. The default read-only Desktop profile stays unchanged.

### Concrete original bootstrap and retained connector

The original source audit found only a synthetic `OriginalAndroidTextDevice`
implementation. `AgentdAndroidTextDevice` now provides the concrete production
transport. It does not install a Runtime server or load new credentials. The
installed ChatGPT Runtime connector's availability still does not put its
authenticated client into an Agentd process.

The original trusted embedding retains its already initialized `RmcpClient`
with `retain_tool_session`. The client must keep its original lifetime alive.
HTTP requires the original authenticated peer and legacy MCP request protocol.
Retention monotonically enforces `HttpRedirectPolicy::Stop` on that same
adapter, including ordinary configured servers whose initial redirect policy
was `Legacy`; an agent-plugin source label is not the no-replay guarantee.
OAuth-managed transports, including the SDK's
access-token-only OAuth path, are refused because challenge handling can resend
a request below the application layer. Opaque delegated bearer credentials and
dynamic authentication providers are also refused. The existing HTTP capability
must explicitly implement a single-attempt request. Local `RouteAwareHttpClient`
uses the original route factory with reqwest retries, redirects and TLS fallback
disabled for that call; ordinary HTTP availability is insufficient. Remote
exec-server HTTP and opaque wrappers default to unsupported, so an older or
unproved transport cannot silently ignore this requirement. There is no new
authentication client or wire-protocol fallback.
Changing the original `RmcpClient` session or shutting it down revokes all
retained handles from that session. A handle never follows a replacement peer.

The locked SDK is `rmcp` 3.1.3. Its
[`AuthClient`](https://github.com/modelcontextprotocol/rust-sdk/blob/rmcp-v3.1.3/crates/rmcp/src/transport/common/auth/streamable_http_client.rs)
can refresh after HTTP 401 and repeat the same POST with a new token. This is
why the retained constructor refuses that wrapper, including its stored-token
fallback, instead of relying only on application-level retry policy. The SDK's
[`StreamableHttpClientTransportConfig`](https://github.com/modelcontextprotocol/rust-sdk/blob/rmcp-v3.1.3/crates/rmcp/src/transport/streamable_http_client.rs)
also enables transparent 404 reinitialization by default. The original plain
transport explicitly disables it. Its adapter additionally reports 404 as its
own `Client(SessionExpired404)` error, leaving ordinary client recovery with
`RmcpClient`, where replacing the peer revokes old retained handles. Resuming
an interrupted SSE response uses GET on the same original session and does not
resubmit the effect POST. The authenticated HTTP tests exercise real original
adapter construction with a resolved bearer or `X-Hepta-Runtime-Token`, and
count effect requests after 404, 401, nonce challenge, redirect and late replies.

Supply that handle, its live multithread Tokio runtime, the exact canonical
original payload and the already bounded local monotonic deadline in
`AgentdAndroidRuntimeInputs`. Call
`AgentdProductionOperationRuntimeConfig::with_android_from_runtime` with the
original unregistered recovered writer and original Android FinalUse owner.
It rechecks the same writer/lease/verifier, attaches the fixed destination and
returns an `Arc<AgentdAndroidTextDevice>` for original-job correlation. It does
not issue a grant or call the helper during bootstrap. Normal runtime attachment
rechecks the recovered owner again. The original embedding must provide this
composition explicitly; no environment-based production preset was added.

For a ready original `codex-mcp::McpBinding`,
`AgentdAndroidRuntimeInputs::from_mcp_binding` retains only `process_start`,
`process_wait` and `process_read` in the independently selected original
environment. It preserves the frozen tool catalog, its read fence throughout
each request, the original client and the smaller original server timeout.
Disabled, unready or app-only tools cannot trigger server startup. The existing
MCP policy must explicitly approve unattended use; an interactive approval
requirement is not silently discharged by a FinalUse grant. No bare manager
client is exported. `prepare_android_runtime_target` supplies this actual
Android target as the primary destination of the existing production host,
allowing Notes to use its original separate consumer without a synthetic
primary target. The original manager must remain owned until Agentd ends.

This connector intentionally binds one exact operation/payload. Its effect
entry is consumed on the first attempt, including failed or ambiguous attempts.
It is a bounded first-action composition, not yet a live multi-action mobile
session or a destination-replacement API. A subsequent operation needs explicit
original-owner composition from its fresh native observation. No hidden second
writer, operation ledger or implicit renewal is introduced to bypass that limit.

Within synchronous FinalUse entry, the connector executes inline using the
existing multithread runtime. It does not detach or enqueue an effect future.
The original absolute deadline covers start, polls and immediate readback;
native payload expiry is unchanged. `invalidate` permanently closes the effect
lane. A later read-only observation receives a separate bounded transport
budget while retaining the same original payload and peer; it cannot establish
causal completion or authorize another effect.
Dropping a timed-out MCP call does not prove cancellation of remote work that
was already submitted. Such a result stays Indeterminate, and the native
receiver still enforces the immutable original expiry.

The existing integration points are:

- [hepta-agentd/src/production_composition.rs](../hepta-agentd/src/production_composition.rs): constructs the existing
  `AgentdProductionOperationRuntimeConfig` using the original recovered owner.
- [hepta-agentd/src/production_writer_host.rs](../hepta-agentd/src/production_writer_host.rs): `with_additional_target` accepts
  the original destination-specific FinalUse authority and target; `attach`
  verifies that it is the same recovered writer/lease before registration.
- [hepta-agentd/src/notes_bootstrap.rs](../hepta-agentd/src/notes_bootstrap.rs): existing channel-factory → target →
  additional-target wiring is a useful model. Its inherited Notes descriptors
  are not Android capabilities and cannot be repurposed as such.

The concrete connector implements this fixed one-shot contract:

| Boundary | Exact input / required behavior |
| --- | --- |
| Original Runtime target | Existing configured host alias `pocket4`, retained authenticated client/peer; no raw SSH address or new login |
| Fixed process entry | `/usr/bin/sudo`, argv `-n`, `/usr/local/libexec/android-digitalis-observe-helper`; no shell command fragments |
| `apply` stdin | The exact JSON bytes supplied by this target: `op=organ-set-text`, original `payload_base64`, original `payload_sha256`; write once and close stdin |
| `readback` stdin | Same original payload and hash, `op=organ-readback`; a new read-only invocation, never a cached earlier observation |
| Original host observation before bootstrap | `{"op":"organ-observe","package":"<verified exact package>","resource_id":"<observed exact full ID>"}` through the same fixed helper; the connector itself accepts the resulting original payload, not a discovery request |
| Input bound | At most 24 KiB for the outer helper request; the decoded original payload remains at most 16 KiB |
| Result | Require same job, `succeeded`, zero exit, `output_complete`, no cancellation/timeout/log errors/truncation, and complete terminal byte accounting. Read `stdout.bytes_hex`, verify exact UTF-8 and matching text, size/offset/eof and terminal size; at most 8 KiB. Running-job EOF, old text-only Runtime responses and incomplete output stay unresolved. |
| Runtime job identity | Require the original operator backend (`execution_mode=operator`, `system_jobctl=false`), fresh launch ACK, audited start, durable launch record and exact full request digest including stdin and timeout. Retain its original job ID with the same operation. A successful `process_start` acknowledgement is not a native effect receipt |
| Deadline and cancellation | Bound the synchronous host call and every poll; never reset native payload expiry. Cancellation invalidates the effect lane; stopping a process does not prove that Android did not act |
| Source gates | Exact deployed root-owned helper hash, original Droidloom file/owner, installed APK hash and original signer, original host/peer and same cell generation before use |

The connector binds the first effect attempt's idempotency key to a
domain-separated digest of the original operation ID and payload hash.
Do not invent another operation ID on reconnect. An unknown start result without
a retained original job/receipt stays unknown; this adapter must not start an
effect again merely to rediscover its result. A new read-only recovery query can
observe state, but cannot upgrade that unknown result to Committed.

Desktop's `support/android/receiver/qualify_receiver.py` provides local `java`,
`apk` and `installed` gates for the source/signature part of this contract.
The native process envelope is based on original Runtime commit
[`e023ce671650aa752e3efac1d9d5ed67dad8c8d6`](https://github.com/TrillionniumFoundation/hepta-runtime/commit/e023ce671650aa752e3efac1d9d5ed67dad8c8d6),
whose exact `src/mcp/runtime/jobs.rs` is SHA256
`84716d569b266a494a1ee54c3e8737464b379032ade12f5d66465b50a49dfcb7`.
That source selects system jobctl only for Linux **isolated** hosts. Its
operator backend deliberately uses the configured SSH account's existing OS
rights; the original fixed `sudo -n` helper does not gain privileges from this
connector. Requiring `system_jobctl=true` was an incorrect inference from the
older default source, rather than an original Android authority requirement.
The connector now accepts only the explicit original operator profile, not a
bare false flag or a mode inferred from tool availability. Native MCP results
use the original `job`/`launch` JSON envelope; presentation wrappers that rename
these fields are not silently normalized.

The original source persists the job and complete request digest before remote
launch, holds its configured owner admission fence during submission, and
retains `launch_unknown` after a lost ACK. Its operator supervisor uses an
exclusive lifetime lock, durable intent and launch nonce, original UID/start
identity, atomic terminal record and complete output accounting. Same-key
operator launches never retry an uncertain prior workload. References:
[request/host binding and start](https://github.com/TrillionniumFoundation/hepta-runtime/blob/e023ce671650aa752e3efac1d9d5ed67dad8c8d6/src/mcp/runtime/jobs.rs),
[configured account rights](https://github.com/TrillionniumFoundation/hepta-runtime/blob/e023ce671650aa752e3efac1d9d5ed67dad8c8d6/src/mcp/runtime/config.rs),
[host-key-checked single SSH submission](https://github.com/TrillionniumFoundation/hepta-runtime/blob/e023ce671650aa752e3efac1d9d5ed67dad8c8d6/src/mcp/runtime/ssh.rs).
The request digest binds every original `ProcessStartParams` field except its
separately checked idempotency key, using sorted JSON object keys. Start audit
failure, pending record publication, a different mode/digest, a reused launch
or an incomplete terminal log remains unresolved even if the helper ran.

The deployed executable, release manifest and original authenticated native
endpoint must still be bound to this source profile. A release directory name
or successful read-only probe alone is insufficient. The Runtime's existing
[effect-owner fence](https://github.com/TrillionniumFoundation/hepta-runtime/blob/e023ce671650aa752e3efac1d9d5ed67dad8c8d6/src/mcp/runtime/effect_owner_fence.rs)
is optional in legacy deployments; source presence does not prove it is
configured or that an owner transfer is qualified. This connector neither
creates that authority nor changes the original Runtime deployment.
Successful `process_start` is never interpreted as a device receipt. Its
original job ID remains available through `AndroidRuntimeAttempt`; the Runtime
owns persistence and the original writer owns effect outcomes. An unknown start
without a job ID remains explicitly unknown, with no second start attempt.

Installed inspection requires the existing original root inspection capability;
the tool does not self-elevate or create a new helper lane. These gates produce
reviewable source evidence while the original authenticated connector bootstrap
and live grant remain explicit composition blockers.

### Original authority inputs and activation sequence

The source review used Desktop
`b4da9463461badf8ad53732a043db32d6a311666` and Hepta
`8c7133b5dbef2664723a0c9138a8c94aba939710`. The issuer routing correction described
below preserves the existing authority path; it does not authorize an Android
target or provision its source-qualified retained Runtime peer.

The trusted embedding needs the following original inputs. These are concrete
Rust types and retained capabilities, not a JSON configuration that can be
made valid by inserting example identifiers or public keys.

| Input and source entry | Required provenance and check |
| --- | --- |
| `AgentdProductionHostInputs.current_cut`, `authority`, `verifier`, `lease_id`, `lease_generation` in [production_composition.rs](../hepta-agentd/src/production_composition.rs) | Original independently retained `ExactCurrentCut`, same Agent and spawn, original production lease including its opaque token, and its live verifier. `Revoked` is refused; bootstrap never creates a replacement current cut. |
| `AgentdRootAuthoritySession::connect` in [root_authority_session.rs](../hepta-agentd/src/root_authority_session.rs) | Already connected original Root observation stream, independently pinned peer, launcher's pre-held actual Root pidfd, bounded lifetime, and `AgentdRootWriterTrust`. Keep the session alive; its verified clock/head/proof fence when the original Root lifetime or observation freshness fails. |
| `AgentdFinalUseHostInputs` in [production_authority.rs](../hepta-agentd/src/production_authority.rs) | Existing original Device consumer journal, canonical signer identity and trusted public key, current authenticated revocations, protected clock and independent original frontier store. An added Android destination does not justify a second nonce journal or a newly initialized frontier. |
| `AgentdUnixFinalUseGrantProvider` in [final_use_issuer.rs](../hepta-agentd/src/final_use_issuer.rs) and [root_issuer_client.rs](../hepta-agentd/src/root_issuer_client.rs) | Preconnected original issuer stream and exact peer. The Root host path additionally retains the actual Root pidfd and lifetime with `from_root_stream`; it does not discover, reconnect to, or replace the issuer. |
| `DeploymentGrantPolicy` and `ProtectedLease` in [deployment_issuer.rs](../hepta-agentd/src/deployment_issuer.rs) and [deployment_issuer_root.rs](../hepta-agentd/src/deployment_issuer_root.rs) | Original policy must match subject, destination and scope. The pinned original effect lease ID/revision must match principal, `runtime.agentd.production_operation`, destination, scope and the exact payload hash, and remain live under the original registry fence. |
| `Arc<dyn OriginalAndroidTextDevice>` in [production_android.rs](src/production_android.rs) | `AgentdAndroidTextDevice` supplies the fixed-helper implementation. Its original Runtime client, independently checked source/signer/peer qualification and live FinalUse inputs must still be supplied by the trusted host. Generic process execution permission is not source qualification or a FinalUse grant. |

[HostAuthorityPublicBootstrapV1](../hepta-agentd/src/authority_host_bootstrap.rs)
contains public handoff metadata for the original writer, checkpoint and two
Device/Notes consumers. Its JSON is not an authority token. The trusted launcher
separately transfers already held process descriptors and the sealed handoff;
the consumer still verifies the original proof, live feed and current-cut
checkpoint. Do not copy its public fields into a new signer or registry.

The original host's activation order is:

1. Verify the original helper, APK signer/installed bytes, Droidloom owner and
   retained Runtime peer, then obtain the exact native observation. A returned
   observation supplies a destination identity, not execution permission.
2. Open the original consumer owners and obtain the current Root observation.
   Call `activate_final_use_owners` with those actual existing owners before
   using the Root session's production verifier. Activation synchronizes the
   authenticated revocation head; it is one-shot and remains fenced on failure.
3. Construct `ProductionAndroidTextTarget` from that observation and the real
   retained device capability. For an Android primary destination,
   `attach_production_operation_host` already accepts this target in its
   `AgentdProductionHostInputs`; it also supports the existing optional Notes
   handoff. For an additional destination, compose it with the existing
   `AgentdProductionOperationRuntimeConfig::with_additional_target` before
   installing the runtime config, or use `with_android_from_runtime` for the
   concrete connector and original recovered-owner check. None of these entries
   grants a new policy. The same recovered writer/lease is checked again
   before targets attach.
4. Retain the operation and exact payload through the existing writer, request
   its original exact FinalUse binding, and dispatch only its original queued
   receipt. Confirm both actual native replies and the original durable status.
   An issuer denial is an authorization failure, not a reason to issue directly
   through the helper or to construct another lease.

The non-Notes generic issuer is pinned to one original lease ID and revision.
If a deployment currently pins a `runtime.agentd.production_writer` lease,
that lease cannot pass its `runtime.agentd.production_operation` binding check.
Adding a policy or fixing routing does not change this. The original authority
must already supply the exact authorized Android effect lease through its
existing trusted registration/configuration path. This adapter does not widen
the lease, invent a device-specific admission provider, renew an expired
registration or turn a host process privilege into payload authorization.

### Notes coexistence on the original issuer lane

[HostAuthorityService](../hepta-agentd/src/authority_host_service.rs) uses
`RootNotesGrantAdmission::issue_registered_route` when the original Notes
delegation is installed:

| FinalUse request | Original path |
| --- | --- |
| Registered Notes destination, exact owner and scope | Original Notes admission, joint writer/effect lease fence, canonical issuer policy and shared durable sequence |
| Registered Notes destination, wrong owner/scope or denied/revoked writer | Notes rejection; neither `None` nor an error falls through to the generic issuer |
| Another destination | Existing `DeploymentFinalUseIssuer::issue`, with its unchanged exact original policy and pinned live effect lease |

The former service routed every destination to Notes whenever Notes was
installed, which incorrectly denied independently authorized non-Notes routes.
The correction changes routing only. In particular, it does not make another
target trusted by default or register an Android effect lease. Its focused
component regressions use the actual original registry, signer and counter:

```sh
just test -p codex-hepta-agentd deployment_notes_route
```

The cases cover a valid non-Notes grant alongside Notes, absent policy, wrong
target/scope/payload/owner, revoked effect lease, and a revoked Notes writer for
which a direct generic grant would otherwise succeed. That last control proves
that Notes denial does not cause fallback. These are ordinary-owner component
fixtures, not protected Root deployment or real Android effect qualification.

## Completion, loss and recovery

The actual device `apply` call and independent `readback` call execute during
the existing synchronous FinalUse consumer-entry closure, before a future is
returned. Polling or dropping that future cannot schedule a new effect. The
receiver checks the immutable at-most-30-second action expiry; it is never
refreshed by this adapter.

Immediate `Committed` requires all of the following evidence together:

1. An actual original receiver success response for the same operation/payload
   and original cell, confirming exact preconditions, action submission,
   non-password UTF-8 readback and restoration of accessibility mode.
2. A separate original readback for the same cell, application incarnation,
   WindowManager token and exact node, containing the requested text hash.
3. A native readback timestamp no earlier than the native action-observation
   timestamp. The adapter recomputes matching text instead of trusting only
   `state_matches_requested_value`.

The resulting receipt retains both exact receiver JSON replies. The existing
original writer owns durable publication of that receipt and terminal status.
This proves an acknowledged text-field effect and its observed postcondition;
it does not assert arbitrary app business success or persistence of the field
after application termination.

Any lost/malformed apply acknowledgement, failed later readback, changed
incarnation, stale timestamp or contradictory operation stays Indeterminate.
The effect lane is invalidated and never re-entered automatically. The retained
read-only lane can inspect the same original operation.

`observe_terminal` always treats matching current text as **Indeterminate**.
Readback alone cannot prove that the original operation caused the state. A new
application/cell with identical text is unavailable to the old operation, not
an alternative destination and not proof of NotApplied. A source crash after
the effect but before durable receipt publication therefore stays unresolved
unless the original source already has a terminal receipt. There is no new
receipt ledger or state-based replay heuristic to conceal this limitation.

## Runtime acceptance that remains required

Record one source pair, native package signer equality and the deployed helper
hash. Select an actual harmless Settings search editor or an owned test
application and discover its exact resource ID. Use the original lease,
authorization entry, FinalUse grant and retained operation to perform one
Chinese-text effect and independent readback, then read the durable original
writer status.

Exercise lost reply, cancellation, revocation, owner restart, application
restart and cell generation change. A surviving terminal source receipt should
remain terminal; absent causal evidence must remain unresolved with zero new
effect attempts. This contract intentionally does not claim that a generic
Android editor can recover an unacknowledged effect causally across process
death. Closing that stronger property requires an application-owned causal
receipt contract on the selected real application, not another device ledger.
