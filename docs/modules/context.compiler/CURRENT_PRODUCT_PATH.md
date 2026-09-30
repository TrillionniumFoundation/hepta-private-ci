# context.compiler current product path
<!-- GENERATED CURRENT STATE: edit CURRENT_STATE.json; detailed design is retained separately. -->

State SHA-256: `379c3db3511f983c18b52a597aa6ecdcfa6dfc1c30ef1cb013df6025b2337cbc`. Source anchor: `c2d044272bcf106f6fd9e5aa40656cdc7069a702`.
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

- Earlier direct-source follow-up added the Responses developer/input_text slot guard and before-await exact observer reservation, plus exclusive expiry checks. Those changes and their nineteen unexecuted Rust regressions are retained.
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
- Seventeen new native regressions cover 257 sequential exact-owner turns, runtime validation/capacity/post-rename failures, preparation-clear exclusion, tool/unknown retention, schema retirement/reopen, terminal headroom and bounded timing. These are registered source tests, not locally executed Rust evidence.
- Exact-candidate qualification now requires the reviewed fully qualified native test names as well as command success and aggregate counts. It binds a 257-turn protocol-fixture profile to the command log and source/merge identity without promoting it to provider or selected-host acceptance.
- Consumer execution rows distinguish actual source callsites from absent authenticated ingress and absent external-security consumption. Receipt projection records native results separately from unverified authenticated product E2E, independent acceptance, activation and release.
- Exact-attempt observer terminal binding was already implemented in ext/hepta-prompt/src/exact_body.rs before this follow-up; it is retained rather than repeatedly listed as missing source.
- Live attempt completion measures final-request observation through durable final persistence, including the intervening transport interval. Recovered reconciliation is a separate attempted phase and does not invent pre-crash elapsed time. Neither is a full authenticated user-turn SLO.
- Durable schema 4 atomically replaces each final raw pre-send, provider receipt and nonfinal-observation set with a bounded deny-all settlement tombstone in the same persisted transition. Indeterminate and unresolved attempts retain their complete recovery material and still block blind replay.
- The newest 1024 settlement tombstones remain individually verifiable. Older final records advance a versioned digest chain and fixed fail-closed attempt/turn membership filters; filter collisions may deny fresh work but never authorize replay or erase an unresolved attempt.
- The existing exact-delivery store now binds its root device/inode/owner, requires private directory/file modes and single-link regular files, uses no-follow/create-new file opens, rejects stale temporary files, and permanently fences the owner after root replacement or an uncertain post-rename identity check.
- The production exact-delivery owner now shares the one-time ContextSecurityRuntimeV3 attached to AgentdPromptPipelineOwner and fails before tokenizer execution when the complete external capability set is absent. Owner-local qualification fixtures use an explicit cfg(test)-only constructor; no process-local production fallback exists.
- Ten additional named native regressions cover settlement compaction/checkpoint tamper, schema-3 migration, unresolved retention, second-writer denial, symlink/hard-link/mode/root replacement, and the production external-security presence gate. Their definitions are source facts until exact source/merge execution succeeds.
- Consumer execution mapping now links settlement and storage definitions to their actual exact-delivery owner callsites and distinguishes the composed external-security presence gate from the still-uncomposed lease, journal, generation, immutable-tokenizer and independent-terminal effect capabilities.

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

## 5. Remaining implementation and qualification gates

- Wire the named Agentd compile_and_stage_v3 entrypoint into ordinary authenticated App Server turn admission and prove that exact product call on the immutable source/merge objects.
- Provision and independently qualify the real provider/model tokenizer, immutable executable/interpreter/runtime, vocabulary and normalization. Hash pins detect observed artifact drift but do not attest semantic token accuracy or exclude a privileged replace-and-restore adversary.
- Integrate transport-owner final-use/cancellation authority after the durable authorization linearization point; a revocation committed before authorization is rejected, while post-authorization cancellation remains a separate effect-owner contract.
- Finish cross-holder raw-content redaction, remaining provider typed slots and provider/model-specific framing policies beyond the current developer-only profile.
- Source-level no-follow, private-file, single-link and root-identity fencing is composed. Independently qualify selected-host ownership, power-loss behavior, external anti-rollback anchoring, backup restore, filesystem substitution races and retention capacity; local path checks are not target-host durability evidence.
- Run pinned formatting, compilation, native regressions, product E2E, strict lint, dependency policy, exact-head and deterministic synthetic-merge qualification for the final committed source.
- Measure named-host p50/p95/p99, allocation and peak memory, concurrent admission, cold/warm tokenizer, revocation contention and long-lived recovery/backlog capacity.
- Obtain independent security acceptance and operator-controlled activation/release; repository source changes grant none of these authorities.
- Qualify the independent provider evidence owner and its authenticated receipt acquisition; Agentd remains an evidence consumer and must not self-attest provider truth.
- Qualify schema-4 settlement migration and compact-history storage on the selected host for power loss, rollback/restore, long-horizon capacity and operator recovery. The bounded local checkpoint is not an independently anchored external journal.
- Run immutable source-head and deterministic synthetic-merge qualification over the final direct-source commit; pre-commit materialization tests do not transfer qualification to the generated successor commit.
- The actual product owner now consumes the ContextSecurityRuntimeV3 presence gate and fails closed when capabilities are absent. It still must consume and independently qualify external lease/journal/generation operations, immutable-tokenizer custody and terminal attestation at their exact effect boundaries; attachment alone is not provider truth.
- Bounded schema-4 source compaction/checkpointing is implemented without deleting unresolved work. Complete the externally append-only journal and independently anchored rollback frontier, plus versioned export/restore and selected-host long-horizon qualification; do not raise limits or treat a probabilistic fail-closed membership filter as an audit archive.
- Execute all twenty-seven lifecycle/capacity/metrics/settlement/storage/security Rust regressions on the final source and merge candidates, including named-output and bounded-profile validation. No local Rust toolchain was available for this follow-up.
- Connect public cleanup and raw-free diagnostics to authenticated turn lifecycle/operations consumers; a method definition or a direct owner fixture is not proof of ordinary App Server ingress, cross-host safety or production operations.
- Execute cross-process and cross-host duplicate-attempt qualification against one real external lease authority, including identical and conflicting body/semantic keys, host death, settlement loss and restart reconciliation. Repository-local fixtures cannot establish distributed exactly-once denial.

## 6. Verification

The final ordinary-source candidate must pass deterministic generated-truth checks, default V3 and explicit legacy profiles, V3 product regressions, typed-slot and attempt-bound terminal tests, tokenizer revocation/expiry races, process-reopen recovery, strict all-feature Clippy, dependency policy, exact source-head and deterministic synthetic-merge qualification. Read-only CI and source generation cannot self-certify independent acceptance, activation or release. The lifecycle, capacity and metrics command groups additionally require 17 exact native names; the lifecycle group retains a 257-turn owner protocol-fixture measurement. Neither source navigation nor native fixture evidence grants authenticated product E2E or target-host acceptance.

The canonical workflow uses separate source-head and deterministic synthetic-merge lanes. Both must retain passing receipts with source/base/tested commit/tree, run/attempt, command exit codes, nonempty native test counts and log digests. Candidate identity is revalidated before and after each command. Pending, skipped, cancelled and missing artifacts are not passes.

## 7. Retained detailed design

The complete previous technical guide, implementation map, dossier and product-path design are preserved byte-for-byte below. Their earlier completion statements are historical, not current acceptance evidence. Algorithms, proof objects, byte identities, capacity requirements, threat controls, migration targets and test design remain available in full.

- [TECHNICAL.md](design-baseline/TECHNICAL.md) — retained Git blob `ffe234853d9be0666ce1980607227a4b1f05997a`
- [IMPLEMENTATION_MAP.json](design-baseline/IMPLEMENTATION_MAP.json) — retained Git blob `ccd04f04efde519b7deaf020e49d631dc09ffdf2`
- [context.compiler.md](design-baseline/context.compiler.md) — retained Git blob `4cbb4f33e5ab1984ca851f3dcbb3c1c22b361f15`
- [CURRENT_PRODUCT_PATH.md](design-baseline/CURRENT_PRODUCT_PATH.md) — retained Git blob `3e0574772391b71b247c25514507826860543a83`
- [MODULE_MANIFEST.json](design-baseline/MODULE_MANIFEST.json) — retained Git blob `938477695f05fbf08818e3387f73964c1442c04a`

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
| `settled-history-compaction` | `codex-rs/hepta-agentd/src/exact_context_delivery/settled_history.rs::settle_final_attempt` | `codex-rs/hepta-agentd/src/exact_context_delivery.rs::commit_terminal` | `owner-settlement-regressions` | unverified |
| `store-path-hardening` | `codex-rs/hepta-agentd/src/exact_context_delivery.rs::private_directory_identity` | `codex-rs/hepta-agentd/src/exact_context_delivery.rs::ExactDeliveryStore` | `owner-storage-hardening-regressions` | unverified |
| `external-security-presence-gate` | `codex-rs/hepta-agentd/src/context_security_runtime.rs::ContextSecurityRuntimeV3` | `codex-rs/hepta-agentd/src/exact_context_delivery.rs::require_external_security` | `owner-security-presence-regression` | unverified |
| `external-security-effect-capabilities` | `codex-rs/hepta-agentd/src/context_security_runtime.rs::ContextSecurityCapabilitiesV3` | Not composed | `none` | unverified |

These are reviewed source anchors, not compiler reachability or execution evidence. The exact-candidate receipt records each required native name and command/log identity; native fixture passes never qualify authenticated ingress, independent provider truth or a target host.

## 9. Change discipline

Edit `CURRENT_STATE.json`, run `python3 scripts/generate_context_compiler_module_docs.py --write`, and commit all five projections together. CI uses `--check` only. Source-navigation checks are deliberately not described as compilation or independent security acceptance. No candidate workflow may rewrite Rust source or push remediation commits.
