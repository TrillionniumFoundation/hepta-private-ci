# prompt.registry: implementation design

Parent: `docs/modules/prompt.registry/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: durable factor lifecycle, final-use mutations, canonical V1 codecs and payload-backed exact-model V2 delivery are implemented in source. A named Agentd owner opens the store and attaches its runtime host; authenticated product write ingress and invocation of portfolio compilation/staging remain uncomposed. Section 8 separates those facts from target-host and independent acceptance. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

Use all eighteen dossier receipt fields when the corresponding qualification or runtime boundary consumes a dossier. Ordinary authorized source development instead runs affected package tests, applicable review checks and development-profile ownership/schema/path/reference validation; Git and CI supply the candidate identity. A development-profile pass does not renew historical qualification evidence or prove product execution. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `DurablePromptRegistry` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `register_factor` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `admit_factor_final_use` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `register_realization_payload_final_use_v2` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `retire_factor_final_use` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `revoke_factor_final_use` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `snapshot_v2` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `read_compatible_v2` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `dereference_realization_v2` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `PromptFactorV1` in [codex-rs/hepta-prompt-registry/src/protocol.rs](../../../codex-rs/hepta-prompt-registry/src/protocol.rs); `PromptRealizationV1` in [codex-rs/hepta-prompt-registry/src/protocol.rs](../../../codex-rs/hepta-prompt-registry/src/protocol.rs); `factor_graph_source_v1` in [codex-rs/hepta-prompt-registry/src/lib.rs](../../../codex-rs/hepta-prompt-registry/src/lib.rs).

### 8.1 Public mutation and read boundaries

`DurablePromptRegistry::open_state_dir(directory, maximum_records)` is the public owner constructor. `PromptRegistry::new` and direct lifecycle writers are crate-private; digest-only `register_realization_v2` is test-only. Product mutation must use the durable final-use APIs rather than those fixture helpers.

[durable_recovery.rs](../../../codex-rs/hepta-prompt-registry/src/durable_recovery.rs)
adds `PromptRegistryRecoveryAnchor`, `recovery_anchor()` and
`open_state_dir_with_recovery_anchor(directory, maximum_records, expected)`.
The anchored constructor is for an existing owner at an independently retained
exact semantic cut; it never silently bootstraps missing selected state.

| Native operation | Implemented behavior | Composition scope |
|---|---|---|
| `register_factor` | Inserts bounded draft metadata; identical content is idempotent and changed content under an existing ID conflicts. | No instruction admission and no external product caller. |
| `admit_factor_final_use` | Binds factor content, reviewer, reviewed scope and evidence to a claimed final-use grant, then commits under final-use verification. | Native authenticated writer exists; no product ingress or deployed trust profile. |
| `register_realization_payload_final_use_v2` | Binds exact model tuple, payload digest, actor, scope and optional predecessor; validates payload bytes and publishes a revision. | Native writer exists; no external product caller. |
| `retire_factor_final_use`, `revoke_factor_final_use` | Govern lifecycle changes; revocation binds actor, reason and cutoff and cascades to realizations. | Native writer exists; no external product caller or live product revocation feed. |
| `snapshot_v2`, `read_compatible_v2`, `dereference_realization_v2` | Bind the exact current snapshot and model/version/tokenizer/template/tool schema/context profile/locale; reject stale snapshots, inactive or revoked factors, expiry and payload drift. Dereference returns the actual bounded bytes with a deny-all receipt. | Consumed by `hepta-intelligence` compilation and materialization source. |
| `PromptFactorV1`, `PromptRealizationV1` | Canonical bounded JSON encoding and decoding with semantic validation and critical-field rejection. | Native interchange codecs; no deployed ingestion route implied. |
| `factor_graph_source_v1` | Exports a validated rebuildable factor/interaction source from the in-memory image. | Read-only projection source; durable relation schema/write ingress remains absent. |

### 8.2 Physical state, concurrency and recovery

The durable owner locks its Unix directory descriptor before creating `registry.lock` and retains both locks with an in-process `PromptRegistry` image. Directory and relative file opens reject symlinks, foreign owners, shared permissions and linked files; special-file opens do not block on a FIFO, and non-Unix durable opening fails closed. A newly created owner directory synchronizes its parent entry. Zero capacity fails before creating state. A proven pre-rename failure on first initialization removes only that opener's fresh marker and synchronizes the owner directory so a retry can initialize it; existing/migration markers and indeterminate post-rename outcomes retain their markers. Missing selected metadata behind an existing marker is corrupt. These rules do not claim automatic recovery from every possible bootstrap crash. Mutations validate a cloned successor, preserve immutable payload bytes through `Arc<[u8]>`, publish the durable state, and only then replace the current image. The Agentd facade additionally serializes owner access with a `Mutex`.

Storage V3 uses `registry.json` for the V2 semantic metadata image and bounded extent references, and `registry.payloads` for immutable payload bytes. Appended extents and the directory are synchronized before `registry.next` is synchronized and atomically renamed. A failure before publication retains the predecessor. Uncertain durability after rename returns `IndeterminateDurability`, poisons authoritative reads/writes, and requires reopening the owner. Reopen verifies committed extents, semantic digests, lifecycle lineage and the configured record policy before trimming only an unselected trailing write. Missing, truncated or altered committed bytes fail closed. V1/V2 migration preserves semantic identity and terminal lifecycle; an already valid V3 reopen does not rewrite metadata.

Typed storage decoding rejects repeated JSON members in every supported schema. Restore replays actor/evidence shape, historical source trust, reviewer separation, unique admission grants and native owner revisions; recomputed checksums cannot waive those invariants. Active realization profile identity includes model ID and version as well as profile digests. Factor relations have an in-memory graph-source API, but no durable records or governed relation mutation port. Durable publication rejects a relation-bearing image before selecting new bytes rather than publish an unreopenable graph digest.

Current native bounds are 16,384 logical records, 128 compatible results, 64 KiB per realization, 32 MiB metadata and a separate 32 MiB raw extent budget. Token cost is a validated nonzero declared bound; the registry does not independently execute the selected tokenizer. Metadata serialization, semantic hashing and the complete in-memory image remain size-dependent. Lifecycle history and revoked payloads are retained; bounded retention/compaction is not implemented. A quiesced backup must capture both selected files. Internal integrity checks do not establish that a backup is the independently current head, so restoring an older internally valid snapshot needs an external revocation/current-head fence.

`recovery_anchor()` exports exact revision, lifecycle/revocation frontiers and
semantic registry digest only while the committed owner is available. Anchored
open validates anchor shape and capacity before filesystem access, then fully
validates the existing selected image under its owner lock. `InvalidRecoveryAnchor`,
`RecoveryStateMissing` and `RecoveryAnchorMismatch` reject invalid shape, missing
state and any different cut respectively. A mismatch cannot migrate metadata or
trim a payload tail. A match permits normal V1/V2 migration or V3 tail cleanup.
Missing owner directories or selected metadata never create an owner directory
or marker. An existing legacy image can create its missing lock marker before
cut comparison; metadata and payload bytes remain unchanged on cut rejection.
Parent-directory synchronization repeats on open even if a failed initial sync
left the owner directory present, so a successful retry cannot skip that fence.
The synchronized parent is opened relative to the verified owner directory
descriptor, not derived from the input path's lexical parent; alias paths such
as `owner/child/..` still fence the actual parent inode.
The witness is an exact cut, not a minimum acceptable prefix; the registry cannot
prove that a later image extends all prior complete mutation semantics. Every
newly acknowledged mutation therefore needs a refreshed cut retained in an
independent rollback domain. Public anchor serialization grants no authentication,
freshness or mutation authority; trusting an anchor from the backup itself is
circular. Agentd bootstrap still uses the ordinary unanchored constructor.

Factor semantic purpose is bounded to 4,096 bytes, authority class to 64 bytes and
canonical eligible-dimension JSON to 8,192 bytes; complete protocol input is
bounded to 262,144 bytes. Dimension-size validation uses checked exact encoding
cost before serialization and checks strict canonical ordering without cloning
the input collection. Identifier validation uses the 128-byte ASCII stable-ID
profile on borrowed protocol and admission inputs before creating owned IDs.
These checks preserve public APIs, wire versions and existing shape errors.

Public final-use request binding helpers apply those borrowed factor bounds
before request allocation/hash and preserve the existing error priority and
valid request digests. Invalid factor shape returns `AdmissionError::InvalidGrant`.
Native registration additionally reserves the unresolved migration purpose
`legacy imported factor; semantic purpose unavailable` and combined model tuple
`model:legacy-imported` / `legacy-imported`; their native factor/realization errors
are `InvalidFactorMetadata` / `InvalidTransition`. The realization binding helper
rejects the tuple with `InvalidGrant` before authority claim. Legacy restore,
terminal lifecycle operations and its explicit missing-lineage export rejection
remain unchanged; either model component paired with a different value is allowed.

V1 migration checks the combined factor/realization count and rejects excess
bindings before record decoding, index construction or synthetic imported events.
The storage-file byte ceiling still applies before the typed image exists.
Final-use payload registration rejects empty or over-65,536-byte input before
factor cloning, hashing or grant claim. It preserves the registry/selected files
and original grant claimability on this shape failure; it does not refund a nonce
after entering a final-use effect.

Both ordinary and anchored V3 reopen pass the configured record limit into
`PayloadState::hydrate`. Its shared `validate_stored_metadata_bounds` checks
header/revision, resource configuration and collection counts before sorting
references or opening, reading or hashing payload bytes. Reference count is
bounded by realization count and reference IDs are borrowed-validated before
indexing clones. These failures preserve `ConfigurationMismatch`,
`CapacityExceeded` or `Corrupt` and leave selected metadata and payload/tail bytes
unchanged. The bounded typed-JSON decode still occurs first; full semantic restore
and anchor comparison remain mandatory before migration or tail cleanup.

### 8.3 Named composition and remaining product path

[Agentd state bootstrap](../../../codex-rs/hepta-agentd/src/state.rs) calls [AgentdPromptPipelineOwner::open_state_dirs](../../../codex-rs/hepta-agentd/src/prompt_runtime.rs) with the agent home `prompt-registry` directory and run `prompt-runtime` directory. [The embedded App Server options](../../../codex-rs/hepta-agentd/src/app_runtime.rs) receive that owner's runtime host. `AgentdPromptPipelineOwner::enumerate_candidates` reads this exact store, and `compile_and_stage` calls [compile_prompt_registry_v2](../../../codex-rs/hepta-intelligence/src/prompt_delivery.rs) before staging the selected actual bytes. These methods exist, but no external product callsite invokes enumeration or compilation/staging. Host attachment is therefore a partial named composition, not execution of the complete intervention path.

The registry compiler seals its verified delivery-set digest inside the compiled bundle; caller-created or rehashed replacement payloads cannot mint this source provenance. Compilation checks selected realization membership, exact stored bytes and the complete model/context profile. Agentd staging requires the exact same model identifier and bounds its deadline by the requested deadline, portfolio validity and every selected realization expiry. A compatible model alias requires an explicit validated adapter. These source checks still do not refresh revocation after staging.

The upstream canonical optimizer seals enumeration metadata as well as
`PricedPromptCandidatesV1` and
`SelectedPromptPortfolioV1` in process. The priced and selected values expose
public `validate()` methods that reject
tampering with otherwise rehashed public receipts. Pricing validates complete
candidate semantics and the verifier objective; selection validates the signed
pricing result and requires its original verifier objective and trust digest;
cross-objective or cross-trust-epoch selection fails with `PricingIntegrity`.
The enumeration's private seal binds snapshot and omitted count; callers cannot
rehash those public fields to invent a new source enumeration or hide omissions.
Only `enumerate_factors_v1` establishes that process provenance.
The optimizer's learning.ledger dependency exposes
[`VerifiedLearningEvidenceV1::valid_until_unix_ms`](../../../codex-rs/hepta-learning-ledger/src/signed_evidence.rs):
the exclusive endpoint is the minimum signed/principal expiry plus one
millisecond, capped by known revocation; saturation conservatively excludes the
unrepresentable successor to `u64::MAX`. Pricing seals both verification time
and the earliest completeness/pricing evidence endpoint. Selection rejects
backdated time (`InvalidTime`) and evidence expiry (`PortfolioExpired`), including
the no-pair path. Portfolio validity also includes pair-evidence endpoints, requested
validity and realization expiry. Privately sealed selection time makes exercise
before selection return `RejectStale`. Evidence trust remains ledger/host-owned;
these dependency checks do not create another registry authority.
`exercise_v1` applies the exclusive horizon and exact state/vector/model scope
checks before returning `NoIntervention` for an empty sealed portfolio. Empty
portfolios return `RejectStale` for backdated/expired time or scope drift, while
nonempty portfolios additionally revalidate the current registry/lifecycle cut.
Exercise and registry compilation validate the selected-portfolio
seal. `CandidateIntegrity`, `PricingIntegrity` and `PortfolioIntegrity` preserve
these failure distinctions. Callers use verified pricing/selection constructors;
private seals have no serde reconstruction path and grant no execution authority.
They retain construction provenance, not continuously current trust; producer
trust/revocation refresh at exercise or physical send remains a host requirement.

The optimizer's private `canonical_temporal.rs::graph_valid_until_unix_ms` caps
portfolio validity by the next relevant prompt-edge or endpoint-support transition
in the frozen KG projection, including supports not yet visible. Relevant edges
join candidate factors or require a missing target from a known candidate.
KG support starts are inclusive and ends exclusive in seconds, converted with
saturating multiplication to millisecond deadlines. Overlapping-support transitions
also expire the old support cut even if the relation remains visible. Unrelated
and non-prompt facts do not shorten the portfolio. This cap joins requested,
pricing/pair-evidence and realization deadlines; the compiler and staging host
consume the same sealed portfolio horizon. A later graph generation still needs
current host revalidation.

Registry compilation and compiled-output validation separately enforce a maximum
declared `token_cost` of 10,000 per selected fragment, reporting the typed
`PromptFragmentTokenLimit` error above that limit. This is an individual-item cap,
not only an aggregate context budget. It does not certify actual tokenizer cost.
Fragments declared above 1,000 tokens require the repository's P0 manual review;
the applicable review receipt and exact-tokenizer attestation remain pending
qualification evidence.

The public lower-level `compile_exercised_prompt_context_v1` and
`prepare_prompt_delivery_v1` validate the sealed portfolio and enforce the same
per-fragment bound before construction or delivery-receipt rebinding, using
`PromptPipelineErrorV1::PromptFragmentTokenLimit`. They share the
`MAX_PROMPT_FRAGMENT_TOKENS = 10_000` constant with the registry-backed V2 path.

`prepare_prompt_delivery_v1` rejects serialized payloads above the existing
16-MiB context-compiler ceiling before exercise, materialization, occurrence
scanning, hashing or serialization copies, after portfolio/receipt binding checks.
It preserves the existing `ContextCompiler(SerializedPayloadTooLarge)` error
classification rather than adding a wire error.

Serialization occurrence proof uses private
`prompt_serialization_search.rs::find_subslice`, a KMP first-occurrence search
with `O(H + N)` work per search. The explicit 64-KiB needle ceiling bounds its
prefix table to 512 KiB on a 64-bit target. First-match, cursor order and
missing-occurrence behavior remain unchanged. This is an algorithmic source
bound, not executed-candidate or runtime benchmark evidence.

Runtime journal dispatch must precede the staged deadline, and terminal observation
must not precede dispatch; equal dispatch/terminal timestamps are allowed. The
same checks apply at commit and reopen. Dispatch deadline replay needs the
corresponding staged record; terminal-versus-dispatch ordering is also checked
after stage cleanup. They do not replace a trusted live clock or current registry
revocation validation at physical send.

Remaining product work is authenticated draft/admission/realization/lifecycle ingress with independently provisioned trust and scope, a registered caller that performs selection and compilation/staging, and current registry/revocation revalidation at the physical provider boundary. Store restore now has an exact-cut native check, but still needs independently authenticated anchor custody, acknowledgement ordering and host integration before claiming non-resurrection across arbitrary backup replacement. PIM-3 discovery, split/merge evolution, causal ablation and next-snapshot governance remain separate target capabilities. Target-host measurements, current exact-candidate execution, independent semantic review, acceptance, canary, promotion and release remain external evidence gates. Actual byte materialization alone does not prove model delivery or causal uplift.

### 8.4 Verification references

[lib_tests.rs](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs) and [v2_tests.rs](../../../codex-rs/hepta-prompt-registry/src/v2_tests.rs) cover source trust, lifecycle and compatibility. [durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs) contains owner tests including `final_use_admission_is_scope_bound_single_use_and_revocation_aware`, `restart_preserves_revocation_payload_and_admission_lineage`, `concurrent_writer_is_rejected_by_owner_lock`, `post_rename_sync_failure_poison_writer_until_reopen`, `storage_full_before_rename_keeps_predecessor_live_and_reopenable`, and `reopen_rejects_resource_policy_drift`. [durable_payloads_tests.rs](../../../codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs) covers extent corruption, unselected tails, migration and metadata publication. [durable_restore_tests.rs](../../../codex-rs/hepta-prompt-registry/src/durable_restore_tests.rs) exercises recomputed-checksum lifecycle attacks, model-profile separation, duplicate members, special files, fresh-marker cleanup and concurrent bootstrap. Canonical codec fixtures live in [protocol.rs](../../../codex-rs/hepta-prompt-registry/src/protocol.rs); [Agentd prompt runtime tests](../../../codex-rs/hepta-agentd/src/prompt_runtime_tests.rs) cover the source composition seam. These are test identities, not execution receipts for this documentation revision.

Implementation and operating reference: [docs/modules/prompt.registry/TECHNICAL.md](../../../docs/modules/prompt.registry/TECHNICAL.md).

[durable_recovery_tests.rs](../../../codex-rs/hepta-prompt-registry/src/durable_recovery_tests.rs)
adds exact-cut fixtures for rejected old backups and equal-revision forks,
missing-state rejection without bootstrap, cut comparison before tail cleanup
and V1/V2 migration, poisoned-owner capture rejection and parent-sync retry.
[protocol_bounds_tests.rs](../../../codex-rs/hepta-prompt-registry/src/protocol_bounds_tests.rs)
adds exact encoded-byte boundaries and canonical-order round trips. Intelligence
delivery tests live in
[prompt_delivery_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery_tests.rs)
and [prompt_delivery_multirole_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery_multirole_tests.rs).
These references identify regression source; the audit separately records which
candidate executed each suite.

[canonical_integrity_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_integrity_tests.rs)
covers rehashed pricing and portfolio mutation, candidate receipt integrity and
selected factor/token/expiry semantics. Intelligence adds
`portfolio_expiry_and_utility_tampering_is_rejected_before_compilation`.
[prompt_runtime_integrity_tests.rs](../../../codex-rs/hepta-agentd/src/prompt_runtime_integrity_tests.rs)
covers the exclusive dispatch deadline, unchanged state on rejected dispatch,
pending-dispatch restore and terminal order both before and after stage cleanup.

The optimizer integrity fixtures also cover pricing evidence expiry and known
future revocation without pair evidence, pair-evidence horizon propagation and
exercise-time rollback. The ledger dependency's
[signed_evidence_horizon_tests.rs](../../../codex-rs/hepta-learning-ledger/src/signed_evidence_horizon_tests.rs)
checks inclusive-expiry to exclusive-deadline conversion and revocation caps;
it is dependency coverage, not a prompt.registry-owned API or global production
closure claim.

[canonical_signed_pricing_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_signed_pricing_tests.rs)
adds `actual_signed_pricing_preserves_expiry_and_known_revocation_through_selection`:
actual durable enumeration and independent generator/evaluator signatures feed
pricing and selection; inclusive expiry 200 becomes exclusive deadline 201,
known revocation 150 caps it at 150, the last valid time succeeds, the cutoff
fails and time 99 before verification fails. Enumeration seal coverage includes
`rehashed_enumeration_metadata_cannot_hide_omissions`; intelligence adds
`signed_prompt_fragment_declared_token_cost_obeys_individual_item_cap` using
the signed pricing/selection path at 10,000 and 10,001 declared tokens.

[durable_input_bounds_tests.rs](../../../codex-rs/hepta-prompt-registry/src/durable_input_bounds_tests.rs)
adds `legacy_record_capacity_precedes_decode_and_preserves_selected_bytes`,
`legacy_orphan_bindings_are_rejected_and_exact_capacity_remains_migratable` and
`payload_shape_rejection_preserves_registry_and_signed_grant_claimability`.
The payload fixture uses real Ed25519 final-use grants at zero, 65,537 and 65,536
bytes. These newly added source cases await execution for the repaired candidate;
the earlier CI results do not cover them.

Its fourth fixture,
`v3_metadata_bounds_precede_payload_access_and_preserve_recovery_inputs`,
uses a missing payload file to prove typed metadata/configuration/count/reference
rejection precedes I/O, then verifies an existing payload with an orphan tail and
the selected manifest remain unchanged under ordinary and anchored reopen.
Execution for the new candidate remains pending.

[canonical_temporal_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_temporal_tests.rs)
adds ten real durable-enumeration/signed-pricing/selection/exercise cases. They
cover future conflict and required-factor edges, expiring complements and
endpoints, future endpoint visibility, unrelated facts, exact exclusive
millisecond boundaries, negative/unrepresentable second bounds and a future
support in an already visible relation. Source presence is not an execution
receipt for later edits. All ten cases executed successfully on source candidate
`666b20e73926325b7b4bcf763f03a15c7c76ccf5`; the audit records its exact CI job.

`empty_portfolio_obeys_the_same_time_and_scope_currentness_checks` constructs
a genuinely signed zero-token-budget selection: current empty exercise succeeds
as `NoIntervention`, while time before selection, exclusive expiry and changed
nonzero state/vector/model fields produce `RejectStale`. That named candidate
executed this case; subsequent source changes require their own evidence.

[admission_binding_bounds_tests.rs](../../../codex-rs/hepta-prompt-registry/src/admission_binding_bounds_tests.rs)
checks all four public final-use helper bounds, exact-boundary request/payload
digest compatibility and existing rejection priority.
[protocol_reserved_values_tests.rs](../../../codex-rs/hepta-prompt-registry/src/protocol_reserved_values_tests.rs)
checks native migration-marker rejection, complete state/file and grant
preservation, valid protocol export/reopen, partial-marker model tuples and
V1/V2 legacy restore. These fourth-pass tests have separate validation records
in the audit; their source presence grants no execution or deployment claim.

[prompt_pipeline_fragment_bounds_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_pipeline_fragment_bounds_tests.rs)
adds `public_prompt_compiler_enforces_declared_fragment_bound_before_compilation`
and `public_prompt_delivery_checks_fragment_bound_before_receipt_rebinding`
through genuine admitted/signed-selection portfolios at 10,000 and 10,001
declared tokens. Execution for the new source candidate remains pending.

The same file adds
`public_prompt_delivery_rejects_oversized_payload_before_occurrence_scanning`:
an admitted and signed-selection preparation receives 16 MiB plus one byte
without the selected bytes, and must return size rejection before the otherwise
applicable missing-occurrence error. Execution remains pending.

Two further public-path fixtures,
`public_prompt_delivery_handles_maximum_repeated_prefix_missing_occurrence`
and `public_prompt_delivery_records_the_first_of_multiple_source_occurrences`,
cover a 64-KiB repeated-prefix source against an exactly 16-MiB serialization
and the first matching range at offsets 6–9 respectively. The five public-path
cases still await execution; their declared token costs do not attest actual
tokenizer cost.

[prompt_serialization_search_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_serialization_search_tests.rs)
adds `first_match_handles_prefix_fallback_and_overlapping_occurrences`,
`advancing_the_cursor_selects_the_next_non_overlapping_occurrence` and
`empty_or_absent_needles_preserve_missing_semantics`. These three small source
cases also await execution for the repaired candidate.
