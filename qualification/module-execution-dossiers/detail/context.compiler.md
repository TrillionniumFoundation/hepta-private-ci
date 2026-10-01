# context.compiler execution dossier
<!-- GENERATED CURRENT STATE: edit CURRENT_STATE.json; detailed design is retained separately. -->

State SHA-256: `6a00122845fae17eb374ba51f3982b06eb7f33f29c80fdbfc85d3e4265963739`. Source anchor: `3cded1578fdde5c6c081883c1c2a37c439375623`.
The source anchor is provenance, not the final tested head. Only external execution receipts bind a final source/merge object.

## 1. Current implementation and evidence state

| Dimension | Current state |
|---|---|
| `sourceExists` | `true` |
| `compiledModuleReachability` | `source_composed_pending_exact_head_execution` |
| `productCallPath` | `named_agentd_entrypoint_source_composed` |
| `exactHeadExecution` | `unverified` |
| `independentAcceptance` | `false` |
| `activation` | `false` |
| `release` | `false` |

## 2. Direct-source changes in this follow-up

- Earlier direct-source follow-up added the Responses developer/input_text slot guard and before-await exact observer reservation, plus exclusive expiry checks. Those changes and their nineteen registered Rust regressions are retained.
- Agentd now reserves one preparation per turn before tokenizer await; concurrent preparation and unresolved durable attempts cannot authorize another physical send. Cancellation releases only the pre-commit reservation.
- Tokenizer stdin, stdout and exit share a deadline. Input and bounded output progress concurrently; errors kill the child and bound the cleanup wait. Cancellation retains kill-on-drop rather than claiming guaranteed synchronous reaping.
- Tokenizer executable and vocabulary require externally supplied expected SHA-256 pins. Configuration freezes after first successful load, artifacts are streamed through SHA-256 and rechecked around execution. Immutable interpreter/runtime and replace-and-restore qualification remain open.
- After tokenization, Agentd reads the current registry again and holds the same registry lock through exact proof construction and durable pre-send authorization. Expiry and wall-clock rollback are checked before authorization and expiry is checked after fsync. Post-authorization transport cancellation is not silently claimed.
- The Agentd final framing verifier also requires exactly one complete developer/input_text context string and rejects recursive duplicate JSON keys, wrong context roles, metadata-only placement and context concatenation.
- Durable schema 2 separates nonfinal observations from final receipts; Indeterminate remains unresolved across reopen, monotone final observations retain unknown history, and semantic retries do not depend on a later callback timestamp. New observations retain canonical provider receipt data; legacy digest-only history is not promoted into authenticated evidence.
- An uncertain post-rename directory sync fences the exact-delivery store until reopen; poisoned mutexes are not silently recovered. New owner errors expose only stable reason codes in Display and Debug.
- Compiled context is shared by Arc instead of repeatedly copying raw payloads. This is a source-level allocation reduction, not a measured target-host performance result.
- Twenty-one additional Rust regression functions are registered in the active Agentd module, including real signed-registry revocation during a child-process barrier, expiry, concurrent preparation, durable migration and failure fencing. Native execution is not asserted.
- Registry-owned context authority is registered by hepta-prompt-registry and consumed through construction-closed V3 snapshots and successors.
- hepta-intelligence exports the canonical V3 compiler-owned serializer and exact-tokenizer contract; the legacy V1/V2 composition surface is default-off and remains available only through an explicit compatibility feature.
- Agentd exposes compile_and_stage_v3 on the existing prompt pipeline owner and stages the same V3 object into the existing exact encoded-body owner; no second provider execution spine is activated.
- The exact-body owner preserves tokenizer-before-final-authority ordering, then holds the registry owner through proof construction and durable pre-send with no await in the authorization interval.
- Concrete tokenizer configuration is additionally bound to the V3 provider/model/version/binary/vocabulary/normalization execution profile while retaining external artifact pins and before/after drift checks.
- Canonical status now distinguishes direct source, module reachability, named product entrypoint, exact-head execution, independent acceptance, activation and release.
- A construction-closed ContextDeliveryRecoveryBindingV2 archives preparation identity, final-request proof identity and exact ProviderInvocationIntent without raw prompt bytes or dispatch authority.
- Agentd schema 3 persists the bounded recovery archive before transport release; after process reopen it can reconcile Indeterminate and final observations for the same attempt without invoking the request observer or transport again.
- Schema-2 digest-only pre-send history remains fail-closed and non-recoverable; migration never fabricates missing recovery evidence.
- Recovery archive tampering, intent drift, request-body drift, wire-semantic drift, context attachment drift and conflicting terminal replacement are rejected.
- V2 compiler errors and raw payload holders use stable redacted diagnostics; dynamic error detail and prompt bytes are excluded from Debug and Display output.
- Lifecycle follow-up: the existing exact owner publishes the runtime projection under one exclusive exact-state reservation before inserting the exact stage. Validation, capacity and uncertain runtime persistence errors cannot leave a newly usable half-published exact context.
- Completed end-turn and rejected terminals retire raw exact context after the last preparation/attempt settles; tool-continuation and Indeterminate contexts remain retained. Attempt/proof/observation history is not removed. Existing capacity limits are unchanged.
- AgentdPromptPipelineOwner::clear_turn coordinates explicit unused/settled-turn retirement with the same two owners. Runtime schema 2 records raw-free retired turn identities; schema 1 remains readable and cannot carry invented retirement. Old dispatches remain queryable and cannot admit new attempts.
- New admissions preserve bounded terminal headroom: 64 KiB per unresolved exact attempt and 128 KiB per unresolved runtime projection attempt. Producer-side record limits protect the reservation. Unknown observations cannot spend the final reserve, and final reconciliation can consume its own reservation. Legacy states acquire no fabricated historical reservation.
- The existing owner records seventeen bounded process-local phase measurements, including failed/cancelled scopes, with last-256 nearest-rank p50/p95/p99 and lifetime saturating totals/maxima. Unobserved phases remain null. Nested measurements overlap and are not additive latency; no target-host improvement is asserted.
- Seventeen new native regressions cover 257 sequential exact-owner turns, runtime validation/capacity/post-rename failures, preparation-clear exclusion, tool/unknown retention, schema retirement/reopen, terminal headroom and bounded timing. These are registered source tests, execution status belongs to exact-candidate receipts.
- Exact-candidate qualification now requires the reviewed fully qualified native test names as well as command success and aggregate counts. It binds a 257-turn protocol-fixture profile to the command log and source/merge identity without promoting it to provider or selected-host acceptance.
- Consumer execution rows distinguish actual source callsites from absent authenticated ingress and absent external-security consumption. Receipt projection records native results separately from unverified authenticated product E2E, independent acceptance, activation and release.
- Exact-attempt observer terminal binding was already implemented in ext/hepta-prompt/src/exact_body.rs before this follow-up; it is retained rather than repeatedly listed as missing source.
- Live attempt completion measures final-request observation through durable final persistence, including the intervening transport interval. Recovered reconciliation is a separate attempted phase and does not invent pre-crash elapsed time. Neither is a full authenticated user-turn SLO.
- Admission and attachment retain a shared immutable revocation frontier; every selected admission baseline and the attachment baseline must advance monotonically even when a replacement snapshot was independently root-verified.
- Empty selections validate compilation scope and revocation domain before attachment or delivery preparation.
- Unix exact-delivery storage pins a private directory descriptor, rejects symbolic/hard links and non-private files before truncation, and permanently fences an owner whose directory or lock identity changes. Six previously dormant/new storage regressions are registered in the owner module and qualification command.
- Strict compiler all-targets Clippy findings are resolved without changing the published V2 evidence-owner call shape.
- Pipeline/runtime diagnostics redact dynamic adapter, registry and compiler errors. Public exact-delivery diagnostics expose stable reason codes through an opaque wrapper rather than a private internal error type.
- The 257-turn full-owner fixture retains subprocesses and fsync with a bounded dedicated watchdog and disk-workload group. CI records disabled debug/incremental artifacts to reduce combined Cargo/Bazel disk pressure; no test or security gate is skipped.

## 3. Current product call path

```text
registry-owned V3 authority / optimizer portfolio
  -> compile_prompt_registry_v3 -> compile_v2
  -> compiler-owned canonical bundle -> typed attachment
  -> AgentdPromptPipelineOwner::compile_and_stage_v3
  -> exact encoded HTTP body -> strict developer/input_text slot
  -> bounded real tokenizer -> current authority successor
  -> registry lock: final proof + schema-3 durable pre-send (no await)
  -> same encoded body transport
  -> canonical provider observation
  -> live terminal path OR process reopen
       -> raw-free recovery archive
       -> same ProviderInvocationIntent only
       -> local intent/byte verifier (independent provider evidence still open)
       -> monotone Indeterminate/final durable observation
```
The recovery archive grants no dispatch authority and cannot re-release request
bytes. Legacy digest-only records continue to block blind replay and require
external reconciliation rather than being upgraded into evidence.

Stage publication uses exact-state -> runtime-state lock order, with no await or provider effect. Terminal retirement frees raw payload but retains proof/history. Ordinary authenticated ingress and external security-capability consumption are not yet composed.

## 4. Dormant integration inputs

- `codex-rs/hepta-agentd/src/prompt_product_v3.rs`: Historical alternate owner remains unregistered and is not part of the product call graph; the canonical path is prompt_runtime plus exact_context_delivery.
- `codex-rs/hepta-agentd/src/exact_context_delivery/settled_history_tests.rs`: Unregistered future settlement tests reference an absent settled_history implementation; they are not executable coverage or evidence that bounded history rollover is complete.

## 5. Remaining implementation and qualification gates

- Wire the named Agentd compile_and_stage_v3 entrypoint into ordinary authenticated App Server turn admission and prove that exact product call on the immutable source/merge objects.
- Provision and independently qualify the real provider/model tokenizer, immutable executable/interpreter/runtime, vocabulary and normalization. Hash pins detect observed artifact drift but do not attest semantic token accuracy or exclude a privileged replace-and-restore adversary.
- Integrate transport-owner final-use/cancellation authority after the durable authorization linearization point; a revocation committed before authorization is rejected, while post-authorization cancellation remains a separate effect-owner contract.
- Finish cross-holder raw-content redaction, remaining provider typed slots and provider/model-specific framing policies beyond the current developer-only profile.
- Qualify durable filesystem ownership, rollback resistance, symlink/race resistance and safe retention/retirement beyond bounded JSON state.
- Run pinned formatting, compilation, native regressions, product E2E, strict lint, dependency policy, exact-head and deterministic synthetic-merge qualification for the final committed source.
- Measure named-host p50/p95/p99, allocation and peak memory, concurrent admission, cold/warm tokenizer, revocation contention and long-lived recovery/backlog capacity.
- Obtain independent security acceptance and operator-controlled activation/release; repository source changes grant none of these authorities.
- Qualify the independent provider evidence owner and its authenticated receipt acquisition; Agentd remains an evidence consumer and must not self-attest provider truth.
- Qualify schema-3 storage on the selected host for ownership, rollback resistance, power-loss behavior, symlink/race resistance, retention and capacity; bounded JSON source semantics are not target-host durability evidence.
- Run immutable source-head and deterministic synthetic-merge qualification over the final direct-source commit; pre-commit materialization tests do not transfer qualification to the generated successor commit.
- Compose ContextSecurityCapabilitiesV3 into the existing actual exact-delivery owner: external lease/journal/generation, immutable tokenizer custody and independent terminal attestation remain defined interfaces rather than consumed runtime capabilities. The current local verifier binds intent and bytes but is not independent provider truth.
- Long-lived history rollover is not implemented by raw-payload retirement. The 1024 runtime dispatch and 4096 exact pre-send limits, bounded whole-JSON persistence and replay cost remain. A versioned append-only journal/checkpoint/archive migration must retain every attempt tombstone, unresolved binding and independently anchored frontier; do not delete history or increase limits as a substitute.
- Execute all seventeen lifecycle/capacity/metrics Rust regressions on the final source and merge candidates, including their named-output and bounded-profile validation. Local toolchain availability and local passing tests do not replace immutable CI lane receipts.
- Connect public cleanup and raw-free diagnostics to authenticated turn lifecycle/operations consumers; a method definition or a direct owner fixture is not proof of ordinary App Server ingress, cross-host safety or production operations.
- Unix descriptor-relative storage defenses do not establish Windows parity, target-host power-loss durability or resistance to a privileged same-user replace-and-restore adversary.

## 6. Verification

The final ordinary-source candidate must pass deterministic generated-truth checks, default V3 and explicit legacy profiles, V3 product regressions, typed-slot and attempt-bound terminal tests, tokenizer revocation/expiry races, process-reopen recovery, strict all-feature Clippy, dependency policy, exact source-head and deterministic synthetic-merge qualification. Read-only CI and source generation cannot self-certify independent acceptance, activation or release. The lifecycle, capacity and metrics command groups additionally require 25 exact native names (17 lifecycle/capacity/metrics, 6 Unix storage and 2 raw-free diagnostic cases); the lifecycle group retains a 257-turn owner protocol-fixture measurement. Neither source navigation nor native fixture evidence grants authenticated product E2E or target-host acceptance.

The canonical workflow uses separate source-head and deterministic synthetic-merge lanes. Both must retain passing receipts with source/base/tested commit/tree, run/attempt, command exit codes, nonempty native test counts and log digests. Candidate identity is revalidated before and after each command. Pending, skipped, cancelled and missing artifacts are not passes.

## 7. Retained detailed design

Active V3 contracts and development workflow: [V3 development guide](../../../docs/modules/context.compiler/V3_DEVELOPMENT.md).

The complete previous technical guide, implementation map, dossier and product-path design are preserved byte-for-byte below. Their earlier completion statements are historical, not current acceptance evidence. Algorithms, proof objects, byte identities, capacity requirements, threat controls, migration targets and test design remain available in full.

- [TECHNICAL.md](../../../docs/modules/context.compiler/design-baseline/TECHNICAL.md) — retained Git blob `ffe234853d9be0666ce1980607227a4b1f05997a`
- [IMPLEMENTATION_MAP.json](../../../docs/modules/context.compiler/design-baseline/IMPLEMENTATION_MAP.json) — retained Git blob `ccd04f04efde519b7deaf020e49d631dc09ffdf2`
- [context.compiler.md](../../../docs/modules/context.compiler/design-baseline/context.compiler.md) — retained Git blob `4cbb4f33e5ab1984ca851f3dcbb3c1c22b361f15`
- [CURRENT_PRODUCT_PATH.md](../../../docs/modules/context.compiler/design-baseline/CURRENT_PRODUCT_PATH.md) — retained Git blob `3e0574772391b71b247c25514507826860543a83`
- [MODULE_MANIFEST.json](../../../docs/modules/context.compiler/design-baseline/MODULE_MANIFEST.json) — retained Git blob `938477695f05fbf08818e3387f73964c1442c04a`

## 8. Consumer execution trace

| Capability | Definition | Actual source consumer | Native command | Authenticated product E2E |
|---|---|---|---|---|
| `stage-publication` | `codex-rs/hepta-agentd/src/exact_context_delivery/lifecycle.rs::stage_with` | `codex-rs/hepta-agentd/src/prompt_runtime.rs::compile_and_stage_v3` | `owner-lifecycle-regressions` | unverified |
| `raw-turn-retirement` | `codex-rs/hepta-agentd/src/exact_context_delivery/lifecycle.rs::retire_completed_stage` | `codex-rs/hepta-agentd/src/exact_context_delivery.rs::commit_terminal` | `owner-lifecycle-regressions` | unverified |
| `runtime-retirement` | `codex-rs/hepta-agentd/src/prompt_runtime.rs::clear_turn` | `codex-rs/hepta-agentd/src/exact_context_delivery/lifecycle.rs::clear_turn_with` | `owner-lifecycle-regressions` | unverified |
| `terminal-headroom` | `codex-rs/hepta-agentd/src/exact_context_delivery/terminal_state.rs::completion_reserve` | `codex-rs/hepta-agentd/src/exact_context_delivery.rs::commit_pre_send` | `owner-capacity-regressions` | unverified |
| `runtime-headroom` | `codex-rs/hepta-agentd/src/prompt_runtime.rs::pending_completion_count` | `codex-rs/hepta-agentd/src/prompt_runtime.rs::commit_state` | `owner-lifecycle-regressions` | unverified |
| `phase-observation` | `codex-rs/hepta-agentd/src/exact_context_delivery/metrics.rs::Metrics` | `codex-rs/hepta-agentd/src/exact_context_delivery.rs::observe_final_request` | `owner-metrics-regressions` | unverified |
| `authenticated-app-server-ingress` | `codex-rs/hepta-agentd/src/prompt_runtime.rs::compile_and_stage_v3` | Not composed | `none` | unverified |
| `external-security-consumption` | `codex-rs/hepta-agentd/src/context_security_runtime.rs::ContextSecurityCapabilitiesV3` | Not composed | `none` | unverified |
| `private-storage` | `codex-rs/hepta-agentd/src/exact_context_delivery/storage.rs::verify_identity` | `codex-rs/hepta-agentd/src/exact_context_delivery.rs::ensure_available` | `owner-storage-regressions` | unverified |
| `raw-free-owner-diagnostics` | `codex-rs/hepta-agentd/src/prompt_runtime_errors.rs::reason_code` | `codex-rs/hepta-agentd/src/prompt_runtime_errors.rs::impl fmt::Display for AgentdPromptPipelineError` | `owner-diagnostic-regressions` | unverified |

These are reviewed source anchors, not compiler reachability or execution evidence. The exact-candidate receipt records each required native name and command/log identity; native fixture passes never qualify authenticated ingress, independent provider truth or a target host.

## 9. Change discipline

Edit `CURRENT_STATE.json`, run `python3 scripts/generate_context_compiler_module_docs.py --write`, and commit all five projections together. CI uses `--check` only. Source-navigation checks are deliberately not described as compilation or independent security acceptance. No candidate workflow may rewrite Rust source or push remediation commits.
