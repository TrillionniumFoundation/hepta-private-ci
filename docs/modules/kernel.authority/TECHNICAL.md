# kernel.authority technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `kernel.authority`

**Owner:** `security-authority`

**Deputy:** `kernel-contracts`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.7B-B0-VERIFIED-USE`

This stable document is the implementation guide for `kernel.authority`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Issue, verify, expire and revoke capabilities without performing the effects they authorize.

The primary owner `security-authority` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `kernel-contracts` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `kernel`, kind `authority`, state model `stateful` and architecture role `immutable_kernel` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-contracts`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-contracts`

Non-authoritative implementation evidence roots:

- `codex-rs/hepta-contracts`
- `codex-rs/ext/hepta-governance`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-contracts/src/final_use.rs](../../../codex-rs/hepta-contracts/src/final_use.rs); the general lease owner is [authority_lease.rs](../../../codex-rs/hepta-contracts/src/authority_lease.rs), and external trust interfaces are in [authority_trust.rs](../../../codex-rs/hepta-contracts/src/authority_trust.rs). This is source navigation, not proof that every target port or production consumer exists. The canonical target → native API → product caller → test → qualification status is [TRACEABILITY.md](TRACEABILITY.md), with the complete declared target-port matrix in [PORT_MATRIX.md](PORT_MATRIX.md). The V1 general-lease trust model is frozen by [ADR-0001](ADR-0001-LEASE-TRUST-MODEL.md), and final-use ordering is normative in [LINEARIZATION.md](LINEARIZATION.md).

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`

Authoritative write domains:

- `authority_lease`
- `capability_revocation`

Explicitly denied capabilities:

- `physical_effect`
- `self_issued_acceptance`
- `learned_hard_constraint`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `lease registry`
- `revocation index`
- `verified-use validator`
- `decision and audit projection`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced target contracts (registration does not imply current product composition; see the traceability and target-port tables):

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `ModulePort::kernel.authority::auth.authbus`
- `ModulePort::kernel.authority::browser.servo`
- `ModulePort::kernel.authority::channel.matrix`
- `ModulePort::kernel.authority::inference.control`
- `ModulePort::kernel.authority::inference.worker`
- `ModulePort::kernel.authority::memory.federation`
- `ModulePort::kernel.authority::runtime.codex`
- `ModulePort::kernel.authority::runtime.fleet`
- `ModulePort::kernel.authority::runtime.supervisor`
- `ModulePort::kernel.authority::secrets.heptabao`
- `VerifiedUseTokenWitnessV1`

Consumed contracts:

- `ModulePort::platform.types::kernel.authority`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

`AuthorityClock::now_with_uncertainty` adds a centre/radius sample. Its default zero-radius implementation preserves compatibility point-time semantics; it is not production attestation. Production constructors bind their qualified nonzero uncertainty and retained custody through the internal runtime-clock adapter. Both FinalUse and ordinary leases require the complete possible time interval to lie within the signed or stored half-open validity window. General-lease pruning requires definite expiry at the interval's earliest time. Invalid arithmetic, excessive uncertainty and unavailable trust fail closed; these source checks do not establish independently attested production time.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `authority_lease`
- `capability_revocation`

Read-only data dependencies:

None.

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

The current general authority-lease store starts at canonical store schema V2 because retired lease-ID revision lineage participates in the authoritative frontier. No schema-V1 general lease store was activated or released; V1 images are rejected rather than silently reinterpreted. Any future durable predecessor requires an explicit migration and frontier transition. FinalUse writes the separately documented V4 snapshot with an explicit trust-family tag and durable optional pending revocation head. Its legacy V1–V3 layouts migrate within the original trust family while preserving nonce history. The FinalUse frontier V2 digest binds the committed head, pending head and complete claimed-nonce set; no history reset is introduced by the time or async-host changes.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](CURRENT_IMPLEMENTATION.md) identifies the actual state owners and lock/transaction boundaries. General V1 leases are registry-authoritative online references, with non-cloneable admin authority and a cloneable read/verify attenuation. An identical lease mutation is idempotent only with the original expected predecessor revision. Every final lease use acquires the owner lock before taking one coherent centre/radius sample from its bound clock, so possible expiry while waiting for the lock is rejected. Compatibility clocks retain their explicit zero-radius policy; production adapters retain the qualified uncertainty. FinalUse supports consumer-entry and bounded local-dispatch linearization as specified in [LINEARIZATION.md](LINEARIZATION.md). Product composition must follow [TRACEABILITY.md](TRACEABILITY.md); target contract registration alone is not runtime composition.

For guarded FinalUse effects, a revocation update that encounters an active effect first persists the exact monotonic head as pending and advances the external frontier, then returns `DispatchInProgress`. While pending, new claims and all new entry paths fail closed with `RevocationPending`. After the active effect drains, the exact head or a strictly stronger monotonic head must be retried. Pending state is durable V4 authority state, not a process-local bit. Recovery cannot replace it with an unauthenticated feed reread or weaken the external frontier.

The Agentd host owns a bounded task set on its existing Tokio runtime. It does not create a new OS thread and runtime for every provider dispatch. Dropping a response receiver cancels waiting, not the admitted task or its durable attempt. Completed task handles are joined before the task table admits additional work. Explicit normal Agentd shutdown/drain integration remains a separate qualification/source task; task-table ownership alone does not prove graceful shutdown.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/kernel.authority.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.authority.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler. The named Agentd automation path durably records the effect attempt and canonical dispatch-entry witness before provider contact; provider response loss, crash or timeout preserves one indeterminate identity for lookup/reconciliation and never blindly redispatches the same attempt.

The async Agentd migration retains the existing `ProviderEffectKey::for_operation(provider_scope, run_id, step_id)` external key profile for both dispatch and lookup. It does not reinterpret a prior effect using a newly derived provider namespace. A missing provider observation, `NotFound` or `Unknown` remains indeterminate. A cancelled caller cannot discard the admitted task. Local terminal reads retain exact intent/payload/command/evidence matching and do not consume a fresh grant, feed or capacity reserve.

Same-process owner drop/reopen, two fresh normal product processes, and target-host crash/backup drills are distinct scopes in `PORT_MATRIX.md`. The existing unit-test reopen is not a two-product-process cold-start receipt.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `capability_self_mint`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

Production-constructor runtime clocks retain the pinned live custody identity and reject observed key-set, generation, revocation-floor, role, domain or exportability drift. A detected drift fences that wrapper; reporting an old generation later does not un-fence it. Temporary custody unavailability supplies no admission time. These checks are a source contract for a bounded real provider, not evidence that KMS/HSM custody was deployed.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.authority.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-contracts/src/final_use.rs](../../../codex-rs/hepta-contracts/src/final_use.rs) and the linked implementation components.

Agentd host V2 configuration accepts bounded `max_inflight_effects` (default 64, maximum 1,024) and `claim_reserve` (default 256). New dispatch admission conservatively accounts for the configured maximum in-flight tasks before consuming nonce headroom. Reconciliation and terminal reads do not use this gate. A reserve rejection requests an independently signed epoch transition; it never advances the epoch itself or evicts nonce history. Operator alert delivery and a full rollover ceremony still require target-host evidence.

The 40-byte local claim journal does not eliminate complete-nonce-set frontier hashing. Ordinary leases still clone and replace their state image. The local Agentd clock floor still incurs durable writes as time advances. No incremental digest/checkpoint optimization or production speedup is asserted. The existing four-operation benchmark is not the required 55-row production matrix in [CAPACITY_QUALIFICATION.md](CAPACITY_QUALIFICATION.md).

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Embed authority owners behind a trusted host boundary. Production-oriented construction binds an `AuthorityClock` plus an externally durable CAS `AuthorityFrontierStore`; the owner-only local directory remains the crash-durable state store and must not be treated as the rollback oracle. A restored local snapshot behind the external frontier fails closed. Compatibility constructors without external trust are not production qualification.

`AgentdAutomationEffectHost` is a named repository-controlled source composition. Host schema V2 requires a bounded issuer key ring, a separately pinned signed revocation-feed key ring and feed file, exact provider configuration and an absolute trust root outside Agent home. `AgentdFinalUseTrustStore` supplies a single-writer persistent clock floor and exact FinalUse CAS frontier. Normal construction uses `recover_state_dir_with_issuer_keys` after authenticating the recovery head; it does not fall back to `open_state_dir`. The canonical `FinalUseFeedClock` additionally requires a current authenticated feed at each authority time sample. A head change invalidates the feed window before authority mutation and publishes a replacement window only after success. Provider entry checks the clock/feed and grant window again after witness persistence.

This current Agentd composition remains a local trust profile, not the complete independently attested production bundle. Normal Agentd/Fleet bootstrap still requires a selected real production provider integration before production qualification can be claimed. Directory separation alone is not proof of independent volume/backup/boot rollback domains.

The exact-frontier asynchronous `VerifiedUseToken::enter` requires the claim-time durable head to remain current and samples the protected owner time interval. A new head invalidates an unentered asynchronous token; an already entered effect remains subject to terminal observation and reconciliation, not automatic retry.

Current operating and state-format references:

- [codex-rs/hepta-contracts/FINAL_USE.md](../../../codex-rs/hepta-contracts/FINAL_USE.md).
- [codex-rs/hepta-contracts/README.md](../../../codex-rs/hepta-contracts/README.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [final_use_tests.rs](../../../codex-rs/hepta-contracts/src/final_use_tests.rs): `signed_claim_is_single_use_and_delivers_under_same_owner`.
- [agent_id_tests.rs](../../../codex-rs/hepta-contracts/src/agent_id_tests.rs): `canonical_id_is_stable_across_display_parse_and_serde`.
- [final_use_time_tests.rs](../../../codex-rs/hepta-contracts/src/final_use_time_tests.rs): entire possible time interval, overflow and final-entry rejection without nonce refund.
- [authority_runtime_clock.rs](../../../codex-rs/hepta-contracts/src/authority_runtime_clock.rs): runtime custody drift and unavailability fixtures.
- [authority_lease_interval_tests.rs](../../../codex-rs/hepta-contracts/src/authority_lease_interval_tests.rs): ordinary-lease interval admission, final-boundary and mutex-wait rechecks, definite-expiry pruning, arithmetic rejection, and mutation versus exact-receipt behavior.
- [automation_effect_host_tests.rs](../../../codex-rs/hepta-agentd/src/automation_effect_host_tests.rs), `authority_feed_clock.rs` and `authority_effect_tasks.rs`: preserved provider identity, feed expiry and task-ownership regressions.

The previously listed dedicated kernel-authority traceability test is not present in the original source tree. Target-port coverage cannot be inferred from unrelated tests. The target-port projection now checks the closed list of contracts declared in this guide and keeps execution/acceptance flags false without corresponding evidence.

In `codex-rs`, run `just test -p codex-hepta-contracts --retries 0 --no-tests=fail`. The current source-composed path additionally requires full affected automation, Agentd, Fleet, Bao and prompt-registry package checks. `qualification/kernel-authority/run_native_checks.py` captures the exact command plan, all-target check, package tests, strict Clippy, formatting, B4 and document-state checks under one immutable identity, including failure/timeout logs. It never repairs the source it qualifies.

`runtime_qualification.py` validates actual expected test identities and result counts in captured libtest output. A successful command with zero matching tests, ignored/renamed/duplicate cases or contradictory counts cannot yield a pilot execution claim. Benchmark raw outputs must be newly produced, not leftovers in a reused output directory. These parser unit tests do not themselves establish native execution.

The dedicated workflow covers core authority sources, affected host/consumer paths, Cargo configuration and B4 inventories. Development candidates require exact-head and deterministic synthetic-merge subjects; an applicable `main` push receives a distinct exact-main check. The presence of this workflow does not assert branch-protection settings or a successful run.

Production evidence admission uses schema `hepta.kernel-authority-production-evidence.v2`. It numerically checks revocation delivery/ack latency and complete node counts, requires all 55 point/operation capacity rows with at least 100 samples each, enforces percentile and budget consistency, and admits only structured crash outcomes that preserve indeterminate state without reset. Caller-supplied `withinSla` or `latencyBudgetPass` booleans are not accepted.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.7B-B0-VERIFIED-USE`
- `P0.7B-B2-TOOL-NET-FS`
- `P0.7B-B3-BOUNDARIES`
- `P0.7B-B4-CALLSITE-PROOF`
- `P0.8A-AST-RATCHET`

The bootstrap package is `P0.7B-B0-VERIFIED-USE`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. External production trust evidence is admitted through `qualification/kernel-authority/verify.py`; that admission is exact-candidate/content-addressed but does not itself activate or release a deployment. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `kernel.authority`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `P0.7B-B0-VERIFIED-USE`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `security-authority` / `kernel-contracts`.
- Allowed write paths:
- `codex-rs/hepta-contracts/**`
- Development predecessors:
- `P0.7A-RUNTIME-BOOTSTRAP`
- Activation predecessors:
- `P0.7A-RUNTIME-BOOTSTRAP`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `P0.7B-B2-TOOL-NET-FS`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `security-authority` / `kernel-contracts`.
- Allowed write paths:
- `codex-rs/hepta-contracts/**`
- `codex-rs/hepta-operations/**`
- Development predecessors:
- `P0.7B-B0-VERIFIED-USE`
- Activation predecessors:
- `P0.7B-B0-VERIFIED-USE`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `P0.7B-B3-BOUNDARIES`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `security-authority` / `kernel-contracts`.
- Allowed write paths:
- `codex-rs/hepta-contracts/**`
- Development predecessors:
- `P0.7B-B0-VERIFIED-USE`
- `P0.7B-B2-TOOL-NET-FS`
- Activation predecessors:
- `P0.7B-B0-VERIFIED-USE`
- `P0.7B-B2-TOOL-NET-FS`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `P0.7B-B4-CALLSITE-PROOF`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `security-authority` / `kernel-contracts`.
- Allowed write paths:
- `scripts/verify_hepta_callers.py`
- `CALLERS.toml`
- `qa/b4-no-bypass/**`
- Development predecessors:
- `P0.7B-B1A-PROVIDER-BOUNDARY`
- `P0.7B-B1B-MODEL-BOUNDARY`
- `P0.7B-B2-TOOL-NET-FS`
- `P0.7B-B3-BOUNDARIES`
- Activation predecessors:
- `P0.7B-B1A-PROVIDER-BOUNDARY`
- `P0.7B-B1B-MODEL-BOUNDARY`
- `P0.7B-B2-TOOL-NET-FS`
- `P0.7B-B3-BOUNDARIES`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `P0.8A-AST-RATCHET`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `security-authority` / `kernel-contracts`.
- Allowed write paths:
- `scripts/verify_hepta_callers.py`
- `CALLERS.toml`
- `qa/b4-no-bypass/**`
- Development predecessors:
- `P0.7E-DEPENDENCY-INVERSION`
- `P0.7B-B4-CALLSITE-PROOF`
- Activation predecessors:
- `P0.7E-DEPENDENCY-INVERSION`
- `P0.7B-B4-CALLSITE-PROOF`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `kernel.authority` to primary lane `LANE-A-FOUNDATION`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-OBJ`](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)

Owned readiness protocols:

- `CapabilityBoundaryV1`
- `EmergencyStopReceiptV1`

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-2-DEBIAN-BRIDGE-SANDBOX`
- `ASM-4-FEDERATED-ORGAN-ENROLLMENT`
- `EMB-2-REFLEX-MOTOR-ACTUATION`

## 17. Source implementation receipt

This receipt records repository source bindings for the current documentation candidate. It is navigation evidence only; it does not claim product execution, deployment, or external effect authority.

| Operation | Native symbol | Source path | Tests |
|---|---|---|---|
| `finaluseauthority` | `FinalUseAuthority`, `VerifiedUseToken`, `dispatch_final_use` | `codex-rs/hepta-contracts/src/final_use.rs` | `final_use_tests.rs`, `final_use_time_tests.rs`, `tests/final_use_linearization.rs` |
| `store` | `Store` | `codex-rs/hepta-contracts/src/final_use_store.rs` | `final_use_store_tests.rs`, `tests/final_use_pending_recovery.rs` |
| `authority_lease` / `capability_revocation` | `AuthorityLeaseRegistry`, `AuthorityLeaseVerifier` | `codex-rs/hepta-contracts/src/authority_lease.rs` | inline unit tests |
| trusted time / anti-rollback interface | `AuthorityClock`, `AuthorityFrontierStore` | `codex-rs/hepta-contracts/src/authority_trust.rs` | `authority_trust_tests.rs`, `authority_runtime_clock.rs` |
| independent approval / revocation feed | `FinalUseApprovalVerifier`, `FinalUseRevocationFeedVerifier`, `FinalUseTrustKey` | `codex-rs/hepta-contracts/src/final_use_control.rs` | inline unit tests |
| owned Agentd effects | `AgentdAutomationEffectHost::execute` | `codex-rs/hepta-agentd/src/automation_effect_host.rs` | `automation_effect_host_tests.rs`, `authority_feed_clock.rs`, `authority_effect_tasks.rs` |

- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json` and generated with the other projections from one manifest.
- Unmapped target consumers remain explicit in `PORT_MATRIX.md`; independent protocols are not relabelled as completed ports.
- Production implementation, product execution, independent acceptance, activation, and release remain false until their separate evidence gates pass.
- Current repository-controlled and external gaps are enumerated separately in `CURRENT_IMPLEMENTATION.md` and [REMEDIATION_20260928.md](REMEDIATION_20260928.md).
