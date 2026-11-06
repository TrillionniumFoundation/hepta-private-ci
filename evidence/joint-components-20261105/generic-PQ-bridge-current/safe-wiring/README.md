# Generic PQ: safe source work, required-owner selection, and effect lifetime

## Status and source identity

This is a source review and a proposed change boundary. No production source,
default permission, frozen candidate, grant, key, or operator configuration was
changed. No Cargo, desktop process, or native test was run for this review.

The reviewed 43 source files were retrieved at Hepta
`e458e534017dd479e382e84331fa1a6078c3abb4`. The root agent verified their Git blobs
against its complete tree and verified that all 43 are unchanged at frozen H1
`9f785cb201ba12ab0ae0f0d341c0f7912cc65efc`, tree
`24804b21d0306b617e12fa3f5b9454a12ed4ad41`. This follow-up rehashes the local raw
bytes against that inventory. The accompanying JSON records those checks and
the exact evidence inputs. This is a finite review, not an exhaustive sink
inventory or a successful PQ qualification.

**Work can proceed without production keys on explicit required-capability
selection, missing-owner rejection, and cancellation/ownership plumbing.
Successful generic authorization still needs an agreed signed binding and an
operator-authorized owner.** Existing FinalUse cryptography and owner machinery
are reusable. A generic owner is not currently injected into ordinary App
Server/Core composition. Defining an unused trait, changing Shadow to Enforce,
or treating a terminal receipt lease as entry authority would not close this
gap.

## 1. Actual selection points and defaults

| Current source | Actual behavior | Consequence for a required generic PQ profile |
| --- | --- | --- |
| `hepta-agentd/src/app_runtime.rs`, `app_server_runtime_options_with_writer` | Sets `required_feature_states` only for `HeptaCognitiveWrite`; other runtime options use their defaults. | There is no generic required-PQ selection here. The existing embedding-owned requirement pattern is reusable. |
| `app-server/src/lib.rs`, `AppServerRuntimeOptions` and `Default` | No generic PQ owner/profile field. `required_feature_states` defaults to an empty map; the optional Hepta hosts default to absent. | Ordinary defaults do not establish a mandatory generic owner. A new requirement must be explicit and validated. |
| `app-server/src/extensions.rs`, `HeptaExtensionBindings` | Contains cognitive, qualification-writer and prompt hosts, with no generic FinalUse owner. `validated()` filters the optional qualification writer to `None`. | Missing optional capability behavior must not be copied into a required PQ path: selected-required plus missing owner must return an error. |
| The same `thread_extensions` function | Calls `codex_hepta_governance::install` with a `Feature::HeptaGovernance` predicate. | Existing governance is an optional contributor, not a mandatory sink boundary. |
| `ext/hepta-governance/src/install.rs` | `install` delegates to `install_with_mode(..., GovernanceMode::Shadow, ...)`. A feature-disabled thread installs disabled state; `is_active` then returns false. | Shadow is the actual ordinary installer mode. Turning the feature off removes this policy contribution. A required PQ condition cannot depend on this optional predicate. |
| `core/src/model_provider_policy/lifecycle.rs` | Filters active contributors and has an explicit `NoPolicy` fast path. | Required authorization must be checked independently of an empty contributor list. |

The global `HeptaGovernance` feature-table default is not among these 43 source
files; this review does not infer whether that independent flag defaults on or
off. That uncertainty does not change the observed ordinary installer mode or
the absence of a generic required-PQ owner/selector. `required_feature_states`
is applied after ordinary configuration and per-request overrides, but today
Agentd uses it only for the cognitive write capability.

## 2. Reusable current-owner mechanisms and their limits

| Existing mechanism | Reusable behavior | What it does not provide |
| --- | --- | --- |
| `FinalUseAuthority` in `hepta-contracts/src/final_use.rs` | Clones share the actual owner, head, durable nonce registry and active counter. `claim` verifies the signed binding and current trust state; entry APIs compare the actual owner and revalidate head/time/frontier. | No automatic generic provider/tool permission. A second owner constructed with the same keys is not the same owner: entry compares the owner `Arc` identity. |
| `VerifiedUseToken::enter` / `FinalUseAuthority::enter_verified_use` | Consumes a non-cloneable token and produces a non-constructible `EnteredUseToken` after exact-binding, current-head, clock and external-frontier checks. | `EnteredUseToken` is an entry proof. Its fields are owner, binding and witness; it does not increment or retain the active-dispatch counter. Holding it in an `Arc` would not create an active fence. |
| `with_verified_use_async` / `with_verified_effect` | Private `enter_verified_effect` increments the owner counter under its state lock. `ActiveDispatchGuard` decrements on completion, unwind or future cancellation. Trusted revocation updates return `DispatchInProgress` while the counter is nonzero. | The fence lasts only as long as the supplied future/callback. It does not follow detached tasks or returned stream bodies automatically. It does not undo a remote effect or atomically transact with another store. |
| `with_dispatch_boundary` | Revalidates and holds the state lock over a short synchronous irreversible local publication/dispatch callback. | It must not hold the lock over network I/O, arbitrary awaits, remote completion or reconciliation. Returning an unpolled future from this callback is not execution of that future. |
| `ModelProviderAttemptLease` and `ProviderAttemptOwner` | A consuming terminal lease and cancellation-safe detached terminal recorder; the dispatch witness preserves `NotDispatched` versus `Indeterminate`. | The lease exposes only `finish`, not final PQ entry. Finishing the recorder does not prove a response pump or provider operation has stopped. |
| `PromptRuntimeHost` | Existing optional host injection with prepare, dispatch-record and terminal-record callbacks. | It exposes neither a generic trusted owner nor a generic per-request signed grant. Its optional-absence behavior is not required-PQ enforcement. |

The FinalUse entry checks are real, not missing placeholders. The missing work
is the authorization binding and lifecycle connection from ordinary composition
to the actual sink. Current external-frontier checking also must not be
described as cross-store atomicity with Agentd generation, a tool process, or a
remote provider.

### Why TurnStart and schema4 cannot supply generic grants

`UnixFinalUseAuthorizer` has a real PQ issuer port, signed response/feed checks,
protected clock and frontier machinery. Its request operation is fixed to
`runtime.codex.turn_start`, and its public implementation is
`TurnStartAuthorizer`. Its authority/runtime fields are private. An issuer that
authorized that operation has not thereby authorized model sends, shell/MCP
effects, or arbitrary tool descriptors. Factoring its transport/verifier code is
possible; reusing its operation or grant is not a legitimate generic adapter.

Schema4 AutomationExecuteEffect similarly signs an exact owner-policy scope:
agent, spawn generation, complete HTTP/PoN provider target and policy, authority
roles/keys, feed, clock, external frontier and bounded recovery references. It
accepts an externally signed FinalUse grant; it is not a general grant issuer.
Its current scope is required at dispatch; historical scope is restricted to
reconciliation. Reusing its owner keys, exposing its private authority, or
renaming its signed scope cannot authorize a different generic operation.

## 3. Smallest safe source changes without operator authority

These are proposed review units, not applied changes or claims that code has
compiled. Production defaults and `GovernanceMode::Shadow` remain unchanged.

### Unit A: an actual ordinary-composition refusal

The smallest useful first change is an embedding-owned **requirement** with an
explicit unsupported/missing-owner failure. This is a capability requirement,
not a new signed authorization domain. It must enter through the real Agentd
configuration/composition path; adding only a field or an unused trait is
insufficient.

The concrete file boundary is:

1. `hepta-agentd/src/config.rs`: represent an explicit request to require generic
   PQ at this embedding, preserving the existing unselected default. Do not
   infer it from environment variables or a test fixture.
2. `hepta-agentd/src/app_runtime.rs`: consume that request while constructing
   `AppServerRuntimeOptions`; reject it if there is no supported, validated
   generic owner. No current generic owner exists to populate the success arm.
3. `app-server/src/lib.rs`: expose and validate the embedding-owned requirement
   at the public runtime boundary so non-Agentd embedders cannot silently lose
   it. Missing or unsupported required capability is startup failure before
   accepting ordinary effectful requests.
4. `app-server/src/extensions.rs`: carry any future validated requirement/host
   without converting an invalid required value to `None`. Until a supported
   positive adapter exists, required generic mode fails here or earlier.
5. An ordinary CLI/composition integration control: selected-required with no
   owner returns the exact refusal and reaches zero provider/tool contacts;
   ordinary unselected behavior remains the existing behavior.

This slice needs no signing material and no guessed operation name. It closes a
misconfiguration/downgrade path for the newly selected requirement; it does not
turn the current default into PQ-enforced mode or satisfy the all-sink gate.
That product adoption decision remains explicit.

### Unit B: source plumbing that is actually consumed

Existing contributor interfaces already permit a deliberately denying backend
without cryptographic material: `ModelProviderPolicyContributor::begin` can
return `Block` using the existing `ModelProviderInvocationInput`, and the tool
policy interface can return `Block` for its existing input. If used for a
required-profile negative implementation, it must be installed as a mandatory
host requirement, remain active despite optional governance being disabled,
and be exercised by ordinary Core entry tests with zero sink calls. It is not a
successful PQ backend and must not return an `Allow` or a no-op lease.

For positive plumbing, a separate consume-once entry capability has to reach
the real transport/handler. The exact existing files where that connection is
consumed are:

| Boundary | Minimum existing files that must participate | Required behavior |
| --- | --- | --- |
| Provider preparation and optional-policy bypass | `ext/extension-api/src/contributors/model_provider_policy.rs`; `core/src/model_provider_policy/lifecycle.rs`; `core/src/client.rs` | Keep the required host gate independent of `NoPolicy` and optional contributors. Carry physical-attempt identity, retry-stable logical binding, endpoint and semantic request identity already represented by the existing input. No fake signed-descriptor digest. |
| HTTP final entry | `codex-api/src/dispatch_metadata.rs`; `codex-api/src/endpoint/session.rs`; relevant `responses.rs`/`compact.rs` callers | After async authentication and exact-header validation, consume the required entry capability immediately before mark/transport invocation. Missing/already-consumed capability fails closed. Cloned dispatch metadata must share one consume-once slot, not clone authority. |
| Async completion ownership | `core/src/model_provider_policy/attempt_owner.rs`; `core/src/client.rs`; HTTP response-pump and stream types | Keep terminal evidence ownership separate from actual effect/fence ownership. The response pump must own or join the authorization lifetime; a terminal recorder alone cannot do that. The actual SSE pump/type implementation lies outside this 43-file review and must be read before claiming a complete file list or implementing that handoff. |
| WebSocket send | `codex-api/src/endpoint/responses_websocket.rs` | Perform final entry in the actual task after waiting for the socket lock and before the first send. Move the active lifetime into that task through completion/cancellation; the outer returned stream handle is insufficient. |
| Tool effects and retry | `ext/extension-api/src/contributors/tool_policy.rs`; `core/src/tools/{context,lifecycle,registry,orchestrator}.rs`; the selected concrete runtime/MCP/process consumer | Add a consuming effect-attempt capability separate from the current `Allow/Block` result. Revalidate after approval waits for every physical attempt. Transfer lifetime to the actual child/remote call when handlers return before completion. |
| Existing owner API, if an owned transferable fence is chosen | `hepta-contracts/src/final_use.rs` and focused lifetime controls | Prefer the existing scoped callback when its future really owns the complete bounded effect. If transfer is necessary, expose a separately reviewed non-forgeable, non-cloneable owned guard using the same state check/counter/drop invariant; do not substitute `EnteredUseToken`. |

The table identifies required consumer sites, not a claim that changing those
files alone completes dependency/re-export plumbing. The Core registry/module
exports and stream implementation are not all in this finite source set. A
trait declaration alone would be dead code until these real sites consume it.
Without settled descriptor semantics, the only honest production result of the
new required backend is refusal. A compiling denying implementation and
negative ordinary-entry controls are meaningful progress; a positive fixture
must remain explicitly test-only.

## 4. Lifetime constraints that the positive implementation must prove

### HTTP unary versus streaming

`session.rs` authenticates asynchronously, validates admitted headers, marks
transport invocation, then awaits `execute` or `stream`. A gate placed before
authentication is stale after that await. The final check belongs after it.

For streaming, `transport.stream(req).await` returns a `StreamResponse`.
`responses.rs` then hands that object to `spawn_response_stream` and returns a
`ResponseStream`. Therefore
`with_verified_use_async(..., || transport.stream(req))` releases its active
fence when the stream object is returned, before the later pump/consumer
lifetime has necessarily ended. A fence chosen to cover the entire bounded
stream must be owned by that pump, including cancellation and join/termination.
Simply storing it in a caller that returns the stream or in the terminal
receipt recorder is insufficient.

### WebSocket background task

The current ordinary path spawns a task, waits for `stream.lock()`, exchanges a
ready/permit pair, and runs `run_websocket_response_stream` in that task. The
outer future marks dispatch before releasing the permit and then returns a
`ResponseStream`. There can be both a lock wait before entry and work after the
outer future returns. A guard in the outer future covers neither boundary
correctly. The real task must consume the capability after its wait and own the
fence while it is the effect consumer. Consumer cancellation must not let the
guard vanish while an independently running child/pump can still send.

### Tools and internal retry

`registry.rs` creates an outer `ToolDispatchAttemptId`, runs admission and
authorization, then awaits the handler. `orchestrator.rs::run_attempt` can wait
for network approval before `tool.run`; the orchestrator can call it again with
an escalated `SandboxAttempt`. Its cloned `ToolCtx` preserves the same call ID.
The outer dispatch identity is therefore not proof that every internal
physical retry has a fresh authorization. Each actual effect attempt needs its
own single-use claim and final check, while preserving the stable logical
operation identity. A previous unknown effect is not proof of safe absence and
must not be resent merely because another grant can be obtained.

Where a tool starts a persistent child or remote MCP operation and returns
early, the lifetime must move to that owned operation or the required profile
must reject the unsupported runtime. The reviewed orchestration code cannot
prove completion of all concrete tool implementations.

### Entry ordering is a policy distinction, not an implicit upgrade

`EnteredUseToken` deliberately permits later revocation to deny future entries
without claiming that already-entered work stopped. The active fence instead
makes revocation updates return `DispatchInProgress` until the bounded work
ends. Extending that owner-wide counter across a potentially unbounded stream
can delay all updates on that owner. A generic policy must explicitly choose
entry-only ordering versus a bounded active lifetime, cancellation semantics,
and resource limits. Neither API is evidence of remote cancellation or an
atomic transaction spanning authority, Agentd state and provider storage.

## 5. What genuinely needs an operator-authorized contract/input

The following choices can be specified and reviewed without secret keys, but
they cannot be inferred from existing grants or silently chosen as production
authority:

- A versioned operation and canonical descriptor: which model/tool action,
  destination and exact request semantics are granted; the issuer role and
  signed scope that distinguish HTTP, WebSocket, MCP and local process effects.
- An explicit owner policy and authentic public pins for root, grant issuer,
  revocation distributor, protected clock and independent frontier; current
  signed head and role/epoch rules. A numeric epoch alone is insufficient when
  the root/keyset or signed head changes.
- A real issuer or externally supplied grant flow authorized for those exact
  operations, not the TurnStart request operation or schema4's provider scope.
- Current agent/generation binding and a defined local dispatch linearization
  boundary after asynchronous composition. Reusing the current FinalUse check
  does not automatically make other stores atomic with it.
- Stable logical operation and fresh physical-attempt/nonce semantics,
  including safe handling of unknown results, provider lookup and explicit
  historical recovery authorization. New authority must not rewrite an old
  pending target or authorize automatic resend.
- The bounded streaming/tool lifetime discussed above, including who owns
  cancellation and when a local fence may be released.

Production signing keys need not enter Core or this workspace. The worker
should receive verified public policy and exact signed grants through its
authorized owner. Test fixtures can validate wiring but cannot substitute for
operator custody or qualify independent deployment.

## 6. Necessary future controls, without adding redundant coverage now

The first source change should exercise ordinary composition rejecting a
required profile with no owner, including disabled optional governance and a
per-request override attempt. No external effect should be reached. That
negative control does not require a new authorization domain.

When a positive descriptor/owner adapter is defined, targeted controls must
cover stale/revoked/generation-changed authority during auth or approval waits;
one-shot capability consumption through cloned metadata; HTTP body activity
after headers return; WebSocket activity after the outer future returns;
internal tool retry and detached operation ownership; and unknown-after-send
without automatic resend. For active lifetime semantics, verify the exact
`DispatchInProgress` behavior until the real consumer has ended, followed by
release on completion, cancellation and unwind. Do not claim each of these is
already implemented or tested.

H1 remains the frozen, independently testable candidate. This review adds no
native credit to it and does not remove the generic all-sink HOLD.
