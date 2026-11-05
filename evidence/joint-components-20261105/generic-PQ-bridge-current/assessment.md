# Ordinary generic tool/provider PQ bridge at e458

Status: **OPEN — concrete composition inputs and effect-entry interfaces are missing.** This is a finite exact-source assessment, not a complete sink inventory or native qualification. No production source, H1 checkout, branch, resource limit or authority configuration was changed.

Source: Hepta `e458e534017dd479e382e84331fa1a6078c3abb4`, tree `6f956a60bbdea7a968d0e138230adca745bac127`. The adjacent source inventory contains 43 freshly read files whose bytes were checked against their returned Git blobs. The independently read 1556→e458 comparison changes none of the 21 paths in the earlier interface inventory or the 17 paths in the ordinary-tool inventory. The current automation PQ implementation was read separately.

## Decision

There is no existing ordinary generic owner that can be connected by a small local call-site change while preserving its actual authorization domain. The repository has usable PQ verification, live-entry and external-issuer mechanisms, but the generic App Server composition supplies neither a required generic PQ owner nor a signed grant source for finalized model/tool attempts.

The narrowest plausible first implementation is a **required owner bridge for the admitted HTTP single-attempt provider path**, including both streaming and unary calls. It would use the existing finalized provider digests and terminal owner, and enter after asynchronous authentication immediately before transport invocation. This remains a proposed implementation boundary: it cannot be completed from the current composition without specifying the real operator-owned issuer/policy inputs below. Supporting only this path would not close WebSocket, tool or all-sinks acceptance; a required profile must refuse uncovered request kinds/transports rather than silently take a legacy fast path.

Consequently this review does not create a fixture root, synthesize grants, repurpose a turn-start grant, flip Shadow to Enforce, add an optional success-returning gate, or claim a component implementation as ordinary-path closure.

## What can actually be reused

| Existing mechanism | Verified current behavior | Reuse boundary |
| --- | --- | --- |
| `FinalUseAuthority::open_pq_state_dir_with_issuer_keys`, `VerifiedUseToken` | Explicit ML-DSA-65 owner, pinned issuer key ring, current revocation head, protected clock and independent frontier. The token is non-cloneable and non-serializable. Entry rechecks the live owner and the exact claimed revocation head. | The cryptographic/currentness owner is available. A generic request still needs a real grant for its exact binding and owner domain. |
| `FinalUseAuthority::with_verified_use_async` | Holds the active-effect revocation fence across the consumer future; no owner mutex is held across await. Completion, cancellation or panic releases the fence. | An opaque generic bridge must retain this consumer lifetime or an equivalently reviewed entry/fence API. Returning `Ok(())` during policy admission cannot carry that guarantee to a later transport. |
| `UnixFinalUseAuthorizer::open/from_pq_config` | An existing public client contacts an independently operated Unix issuer. It checks peer identity, fresh challenge, PQ grant, signed revocation feed, clock and frontier; it owns no issuer private key. | Its protocol operation is fixed to **`runtime.codex.turn_start`** and its public trait is `TurnStartAuthorizer`. Calling it for a generic provider send would reuse a different authorization domain. No generic operation/policy is configured in App Server. |
| Schema4 automation effect host | Operator-provided public keys and signed policy select its fixed HTTP/PoN target, Agentd generation, separate clock/frontier and revocation feed. `AutomationExecuteEffect` supplies `SignedFinalUseGrant`. `execute_ordinary` rechecks live Agentd admission and PQ freshness after store awaits. | The host/runtime fields are private and there is no Core extension binding. Its fixed provider contract and scope cannot authorize arbitrary model requests or tools. The generation callback is an existing pattern, not a transferable grant. |
| `SignedFinalUseGrantCourier` | Carries one exact externally signed grant, verifies the same current owner, and attaches to the already recovered cognitive production writer/destination. | It is not an issuer, dynamic grant service or generic provider capability. It explicitly does not establish production policy or issuer custody. |
| Supervisor signing helper / Bao host | Protected-key signing helper is internal to independently invoked signers. Bao consumes an explicit grant and approval for a registered secret consumer. | Neither is an ordinary Core generic issuer/composition hook. Pulling signing custody into Core would change the authority boundary. |
| `PromptRuntimeHost` | Preparation, durable dispatch and terminal callbacks. The installed provider contributor can return a no-op lease for non-Turn/non-generating requests or absent attachment. | It is prompt delivery/recovery infrastructure, with no PQ issuer, revocation owner or use token. It must not be relabelled as a generic PQ gate. |

The contracts API is in [final_use.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/hepta-contracts/src/final_use.rs) and [final_use_pq.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/hepta-contracts/src/final_use_pq.rs). The issuer domain is explicit in [final_use_authorizer.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs), and its actual PQ flow is in [pq.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/hepta-infer-worker-host/src/final_use_authorizer/pq.rs). The separate current automation scope is defined in [automation_effect_host_pq_policy.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/hepta-agentd/src/automation_effect_host_pq_policy.rs).

## The exact composition gap

`hepta-agentd/src/app_runtime.rs` builds `AppServerRuntimeOptions` with cognitive mutation and prompt host capabilities. `app-server/src/lib.rs::AppServerRuntimeOptions` and `app-server/src/extensions.rs::HeptaExtensionBindings` have no generic PQ owner, required issuer policy, grant source or generation-fenced effect-entry capability. `thread_extensions` calls `codex_hepta_governance::install` with the state database and a feature predicate. That installer initializes evidence and selects Shadow; it does not receive any PQ authority inputs.

The actual config has `automation_effect_host_file` and other domain-specific capability inputs, but no generic model/tool grant composition. The generic capability would have to cross **Agentd config → runtime options → Hepta extension bindings → governance installation/thread state**, with required-mode absence/staleness rejected independently of a permissive contributor fast path.

This is not solved by publishing the automation host fields or reusing its public keys. The missing policy must bind the correct effect domain and current Agentd generation, and the generic call must obtain a signed grant for the finalized request. Key availability alone does not grant that permission.

Sources: [app_runtime.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/hepta-agentd/src/app_runtime.rs), [AppServer runtime options](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/app-server/src/lib.rs), [extension composition](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/app-server/src/extensions.rs), [governance installation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/ext/hepta-governance/src/install.rs).

## The actual entry locations

### HTTP streaming and unary provider calls

Core already creates a unique physical `attempt_id` and a retry-stable `request_binding_id`, with endpoint, provider/model, logical-request and wire-semantic digests. Those are useful binding inputs; raw prompts and credentials do not need to cross the extension API.

The policy return value carries only a terminal `ModelProviderAttemptLease::finish`. Aggregation transfers these leases to a supervisor. `ProviderAttemptOwner` handles cancellation with NotDispatched or Indeterminate according to the transport witness. There is **no entry method** and no PQ capability attached to that witness.

The real shared HTTP locations are `codex-api/src/endpoint/session.rs::execute_with_retry_mode` and `stream_encoded_json_with_retry_mode`. In each single-attempt path:

1. Request construction/encoding and asynchronous `auth.apply_auth(req).await` complete.
2. Expected header state is checked.
3. `RequestDispatchMetadata::mark_transport_invoked` is set.
4. `transport.execute(req)` or `transport.stream(req)` is invoked.

A required PQ entry must be **after step 1 and before steps 3–4**, with the capability/fence retained through the intended consumer boundary. A check only in `core/client.rs` is earlier than authentication and can become stale during that await. The current ephemeral input guard is also before this await, limited to ephemeral HTTP input, and its trait explicitly excludes minting provider authority.

A refusal before transport must preserve NotDispatched cleanup for all acquired leases. Once transport has been invoked, missing terminal evidence remains Indeterminate. New physical retries need fresh entry claims; they must not clone a token or turn a stable logical operation identity into a blind retry permission.

Sources: [provider policy API](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs), [lease aggregation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/core/src/model_provider_policy/lifecycle.rs), [terminal owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/core/src/model_provider_policy/attempt_owner.rs), [actual HTTP transport boundary](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/codex-api/src/endpoint/session.rs).

### WebSocket

`responses_websocket.rs::stream_request_with_optional_dispatch` serializes the request, spawns the sender, waits for the connection lock and then exchanges a one-shot dispatch permit. The caller marks transport invoked before synchronously releasing that permit. The task subsequently runs the WebSocket response/send future.

This protocol is a useful existing cancellation/dispatch ownership boundary, but it is not PQ authorization. A gate placed only before the public method or only in an ephemeral HTTP hook misses the connection-lock wait and the separate sender lifetime. The token must be consumed with the chosen local irreversible handoff/actual send boundary, and any fence must survive the cross-task handoff rather than end when the public method returns its stream.

Source: [responses_websocket.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/codex-api/src/endpoint/responses_websocket.rs).

### Tools

`ToolPolicyDecision` is cloneable Allow/Block. `ToolInvocation` is cloneable. The registry may replace arguments through pre-tool hooks before authorization. The orchestrator later performs approval, sandbox selection, managed-network approval and possible retry before `ToolRuntime::run`.

A genuine tool bridge therefore needs a separate single-use capability carrier, binding the final approved payload and actual destination/attempt. It must survive approval/network waits and be revalidated at the selected runtime's effect entry. The existing approval, sandbox, attachment-owned network policy, escalation and cancellation behavior must remain authoritative and in the same order. One registry callback cannot establish physical-entry coverage for handlers that do not use the orchestrator.

Sources: [tool policy API](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/ext/extension-api/src/contributors/tool_policy.rs), [tool registry](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/core/src/tools/registry.rs), [orchestrator](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e458e534017dd479e382e84331fa1a6078c3abb4/codex-rs/core/src/tools/orchestrator.rs).

## Inputs required before a real component can be composed

1. **A trusted generic owner policy and current operator identity:** actual issuer public-key ring/epoch, revocation distributor and freshness lease, independent clock/frontier endpoints and pins, allowed provider/tool domain and destinations. These cannot be inferred from a provider URL, user prompt, existing federation grant or unrelated automation config.
2. **An authorized per-attempt grant source:** an existing externally operated issuer endpoint or protected signed-grant transport explicitly authorized for finalized generic provider/tool bindings. The currently read Unix protocol grants turn/start; the courier carries one different exact operation. Neither supplies this permission automatically.
3. **Canonical host binding:** actual Agentd agent/generation and live generation-admission check, stable logical operation ID, unique physical attempt identity, finalized request/payload and destination semantics, and the exact immutable owner-policy scope. PQ key epoch is not the Agentd generation.
4. **A required, fail-closed composition contract:** how the capability is supplied at ordinary startup and propagated to threads/turns; what exact transports/request kinds are covered; how missing/stale/unsupported scope is rejected without falling through NoPolicy or an optional no-op.
5. **An entry ownership interface:** provider admission must return an opaque one-shot entry capability in addition to terminal ownership, or an equivalent combined type whose composition preserves both. The codex-api transport path must receive it and retain the correct effect fence. The present terminal-only trait and cloneable metadata are insufficient.

The first four inputs have no existing generic ordinary source in the inspected composition. Implementing a synthetic issuer or fixture policy now would invent the missing authority relationship. This review therefore stops at the verified interface boundary instead of adding an unattached component whose tests could be mistaken for ordinary closure.

## Focused qualification required after those inputs exist

The necessary controls are not run or added here. They should cover: missing/unsupported/PQ-downgraded owner refuses before physical invocation; root/feed/frontier/clock refusal; current-root revocation during HTTP authentication or WS lock wait; Agentd generation change during a wait; changed finalized payload/destination; token reuse and per-attempt identity; cancellation before entry versus after transport; preservation of every original approval/sandbox/network denial; and a real ordinary configured positive path using the actual operator service, source tuple and binary. Fixture controls may test implementation semantics but cannot establish that deployment input.

No existing component result is promoted to these checks. The joint all-sinks PQ gate remains **HOLD**.

