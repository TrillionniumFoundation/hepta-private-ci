# prompt.registry: implementation design

Parent: `docs/modules/prompt.registry/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: payload-backed durable owner, guarded recovery checkpoint and Agentd send-currentness implementation present; production input composition, history maintenance and independent qualification remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-prompt-registry`.
Packages: `PIM-0-PROMPT-INTERVENTION-CONTRACTS`, `PIM-1-PROMPT-FACTOR-REGISTRY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`admit_factor(factor, reviewed_scope) -> FactorRevision`; `register_realization(factor_revision, model_profile, payload_digest) -> RealizationRevision`; `revoke_factor(id, reason, cutoff) -> LifecycleReceipt`; `read_compatible(snapshot, model_tuple, context_profile) -> FactorSet`. Factor semantics and model-specific realization text are separate identities. External content must undergo governed admission before becoming an instruction factor.

## 3. State records and transaction design

`prompt_factor_registry` stores semantic factor ID, supported task classes, provenance and revision. `prompt_realization_registry` binds model/version/tokenizer/template/tool schema, locale, role, payload digest, token cost and expiry. `prompt_factor_lifecycle` stores proposed/admitted/revoked/retired transitions and supersession. Registry append and lifecycle publication are atomic for one owner revision; optimizer access is read-only.

## 4. Deterministic algorithm and scheduling

Validate source trust and owner authorization; dedupe semantic factors without merging incompatible realizations; validate model/template compatibility and payload bounds; append immutable revisions; publish lifecycle. Readers freeze one registry generation and reject expired or revoked realizations at delivery revalidation. No registry insertion automatically selects a factor in a running request.

## 5. Capacity and performance profile

Pilot candidate read <=128 factors, realization payload <=64 KiB subject to model-context limits, support references <=64 per factor. Count tokenizer cost under the exact selected tokenizer rather than character length. Measure lookup, lifecycle propagation and model-version fanout.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- PREG-01: same factor with incompatible tokenizer/template is not delivered by implicit fallback.
- PREG-02: untrusted page text cannot self-register as system instruction.
- PREG-03: revocation between optimization and delivery invalidates the selected realization.
- PREG-04: duplicate revision semantics are idempotent; changed payload under the same identity conflicts.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

KG holds rebuildable factor interactions; learning.ledger owns causal exposure/outcome, not this registry. Rollback may choose a compatible non-revoked predecessor, but never restore an old lifecycle snapshot before a revocation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `open_state_dir` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `open_state_dir_with_recovery_checkpoint` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `register_factor` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `admit_factor_final_use` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `register_realization_payload_final_use_v2` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `retire_factor_final_use` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `revoke_factor_final_use` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `snapshot_v2` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `read_compatible_v2` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `dereference_realization_v2` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `registry` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `requires_reopen` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs).
- **State and recovery:** `DurablePromptRegistry` is the sole writable owner. Storage V3 selects immutable payload extents with atomic metadata; the deterministic `PromptRegistry` exposes read views, not an ambient production writer. Profile identity includes model ID and model version both during admission and reopen. The legacy digest-only `register_realization_v2` is test-only, not a production API.
- **Guarded restore:** `open_state_dir_with_recovery_checkpoint` binds an owner-specific, independently retained checkpoint outside the registry directory. Current/pending identities coordinate witness prepare, registry publication and witness promotion. Reopen must match one exact identity before metadata migration or payload-tail trimming. A checkpoint-required manifest cannot use unguarded reopen. Invalid checkpoint arguments are rejected before creating a new registry lock.
- **Commit uncertainty:** failures after possible witness or metadata publication fence all authoritative reads and writes until reopen. Proven pre-publication failures preserve the predecessor and abort the pending witness. Missing/corrupt witness data is not reconstructed from a potentially old backup.
- **Named host:** `AgentdState` opens `AgentdPromptPipelineOwner`; `app_server_runtime_options_for_agent` installs its guarded host in the existing App Server. A persisted lease binds selected factors, realization bindings, model tuple, generation digest, portfolio and expiry. Preparation checks current owner state; actual provider admission repeats the check under the registry lock and the existing Agentd/Fleet readiness fence. An old caller timestamp cannot defeat queue expiry. A previously recorded attempt is not permission to send again.
- **Limits and headroom:** 16,384 is the absolute record ceiling, not a guarantee that all maximum-size inputs fit. Metadata is bounded to 32 MiB and immutable payload extents separately to 32 MiB. New metadata preserves retirement/revocation headroom for accepted live factors. Runtime metadata reserves a maximum legal terminal observation for every unresolved dispatch, including a later resolution of an indeterminate result. Logical reserves do not guarantee free physical disk space.
- **Source tests:** [`durable_payloads_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs), [`durable_capacity.rs`](../../../codex-rs/hepta-prompt-registry/src/durable_capacity.rs), [`durable.rs`](../../../codex-rs/hepta-prompt-registry/src/durable.rs), [`v2_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/v2_tests.rs) and [`prompt_runtime_tests.rs`](../../../codex-rs/hepta-agentd/src/prompt_runtime_tests.rs). Test definitions are not exact-candidate pass receipts.

## 9. Required recovery and send fault cuts

| Cut | Required behavior and regression source |
| --- | --- |
| Distinct model ID/version, otherwise identical profile | Accepted records reopen; shared `same_profile` identity is used by admission and recovery. |
| Invalid initial capacity or guarded checkpoint arguments | No partial registry initialization; a corrected first configuration can retry. |
| Restore older manifest with newer extents | Reject against retained witness before trimming any newer bytes; reinstating the current manifest remains recoverable. |
| Restore old complete registry backup | Reject when it is neither the checkpoint's exact current image nor its exact pending successor. |
| Capacity/storage error before rename | Abort pending witness and keep predecessor readable; retry only after a proven precommit failure. |
| Metadata rename committed but directory acknowledgement lost | Fence owner; reopen reconciles the exact pending successor rather than overwriting it. |
| Independent witness corruption or write uncertainty | Fence reads and writes; no automatic witness regeneration. |
| Revocation after staging, including process reopen | Preparation and provider admission reject; no new dispatch record. |
| Expiry while queued, stale dispatch timestamp, retired Agent generation | Revalidate actual current time and live Agentd/Fleet fence after acquiring the owner lock and after durable claim publication. A late rejection is durably NotDispatched before returning an error to the physical policy hook. |
| Dispatch acknowledged but process exits before terminal | Keep the original unresolved attempt; reject blind retry, including duplicate use of that attempt identity. |
| New metadata approaches logical capacity | Reject ordinary growth before consuming reserved revocation or terminal capacity. |

## 10. Claim boundary and remaining implementation

This candidate does not create a second optimizer or executor. Registry registration, signed admission and payload publication exist, but the normal daemon still needs a fully authenticated production input/selection producer to invoke `compile_and_stage`. The signed-registry fixture constructs a portfolio to exercise the owner boundary; it is not independent Generator/Evaluator selection evidence or a real provider acceptance test. A mounted guarded host alone is not complete product execution.

History archives, safe reclamation and indexed exact historical lookup are not implemented here. The runtime still has 1,024 dispatch/terminal slots, and old registry payloads remain immutable and retained. Existing legacy snapshots created without capacity reservations are not retroactively guaranteed headroom. Do not remove historical claims or revoked payload facts simply to regain capacity.

The checkpoint protects registry-only backup restoration only while its owner identity/path and independently retained state remain trusted. It is checksum-bound host state, not a remote signed authority or hardware monotonic counter. Restoring registry and checkpoint together, initial enrollment from an unverified old backup, malicious writes by the same OS principal, and rollback of the separate runtime/provider journal require stronger host/authority recovery composition. They are not claimed solved by placing a file in a sibling directory.

Live provider model/configuration identity, external revocation distribution, normal daemon input production, archival, exact final-head/merge execution, target-host capacity qualification and independent acceptance remain explicit gates. No activation, promotion, merge or release is granted.
