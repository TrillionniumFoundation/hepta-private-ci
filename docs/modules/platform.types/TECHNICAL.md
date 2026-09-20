# platform.types technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `platform.types`

**Owner:** `kernel-contracts`

**Deputy:** `architecture`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `PLATFORM-0-TYPE-BOUNDARY`

This stable document is the implementation guide for `platform.types`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own the smallest shared semantic type vocabulary without acquiring runtime or persistence authority.

The primary owner `kernel-contracts` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `architecture` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `foundation`, kind `contract`, state model `stateless` and architecture role `contract` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-types`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-types`

Source implementation evidence roots:

- `codex-rs/hepta-types`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared target root now contains a bounded implementation and focused tests. It does not imply activation, operator acceptance, promotion or release. Source moves must update `MODULES.json`, `SOURCE_BINDINGS.json`, the Cargo/Bazel workspace and this guide in one exact candidate.

### Native source and scope

The registered source root is `codex-rs/hepta-types`. Current native entrypoints include `validate_id`, `canonical_digest_v1`, `ContractRegistryV1`, `rescale_signal`, and `rescale_signal_registered`; the canonical encoding and cross-language vectors are frozen in `CANONICAL_DIGEST_V1.md` and `CANONICAL_V1_CONFORMANCE.json`. This is source navigation evidence, not proof of product execution or external acceptance. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/platform.types.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.types.md).

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

None.

Authoritative write domains:

None.

Explicitly denied capabilities:

- `runtime_authority`

The module accepts bounded semantic values and immutable caller-supplied registry generations. It owns no mutation/effect path. Identifier/profile mismatch, malformed HPTC bytes, oversize/depth overflow, unresolved normalization/profile definitions and nonzero raw authority bits fail closed before publication.

Non-goals include becoming a state store, authority issuer, mutable registry service, transport, secret container, provider adapter or execution spine. Generated bindings describe only the frozen foundational binding spec; they do not turn arbitrary Rust domain structs into external schemas.

## 4. Internal architecture and component decomposition

The native components are:

- bounded values and profiled identifiers;
- monotonic identities and raw `Digest32`;
- HPTC V1 encode/digest/raw-byte validation;
- sealed non-authorizing posture and one-byte raw authority rejection;
- checked FixedQ32/ProbabilityQ32 with explicit arithmetic semantics;
- immutable schema/normalization and numeric-profile definitions/registry;
- checked numeric-signal conversion;
- canonical conformance vectors and deterministic generated bindings.

All components are pure or caller-owned immutable values. There is no local transaction, queue, filesystem, network, process-global mutable state or external terminal outcome. Changes to frozen HPTC framing, profile semantics or generated-binding source require a new version rather than reinterpretation in place.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::platform.types::cognitive.types`
- `ModulePort::platform.types::context.compiler`
- `ModulePort::platform.types::intuition.policy`
- `ModulePort::platform.types::kernel.authority`
- `ModulePort::platform.types::kernel.evidence`
- `ModulePort::platform.types::kernel.operations`
- `ModulePort::platform.types::learning.artifacts`
- `ModulePort::platform.types::learning.ledger`
- `ModulePort::platform.types::learning.operator`
- `ModulePort::platform.types::neuron.runtime`
- `ModulePort::platform.types::objective.compiler`
- `ModulePort::platform.types::platform.wire`
- `ModulePort::platform.types::prompt.optimizer`
- `ModulePort::platform.types::prompt.registry`
- `ModulePort::platform.types::utility.ndu`

Consumed contracts:

None.

Critical protocol schemas:

None.

Current executable compatibility is narrower than the registry inventory. Rust owns the semantic primitives; HPTC V1 owns structured canonical commitment bytes; `PLATFORM_TYPES_BINDINGS_V1.json` owns the generated Python/JavaScript/TypeScript foundational binding surface. No claim is made that arbitrary Rust structs and arbitrary JSON are identical external schemas.

HPTC V1 field/map order, type tags, integer widths, lengths, bounds and no-Unicode-normalization rule are frozen. Unknown/invalid tags, invalid bool bytes, noncanonical ordering, duplicate keys/fields, truncation and trailing bytes reject in `canonical_validate_v1`. Contract/profile meanings cannot change in place.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

None.

This module owns no authoritative mutable domain and therefore has no writer, store, migration, projection, retention or restore protocol. `ContractRegistryV1` is an immutable caller-owned value; authenticating/provisioning a registry generation belongs to the product owner.

The three canonically owned target protocols `RandomStreamManifestV1`, `ExternalSystemManifestV1` and `SensorCalibrationManifestV1` remain source-pending and are not implied by the existing primitive library.

## 7. Runtime, concurrency and transaction model

The current native implementation is stateless. There are no locks, owner transactions, retry loops or background workers. Every operation completes synchronously over supplied values and bounded allocations. Product owners may cache immutable registry generations, but that cache is outside `platform.types` and must bind the exact generation/digest it serves.

## 8. Failure semantics, recovery and rollback

Failure is input rejection: invalid bounds/IDs, malformed canonical bytes, arithmetic overflow, unresolved definition/profile or attempted authority widening. There is no partial durable commit and no recovery/reconciler. Rollback restores code plus the compatible frozen contract version; V1 bytes/profile identities must never be silently reinterpreted.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is zero authority, bounded input and deterministic commitments. Generic bounded values are not secret containers. Raw authority V1 input is untrusted; exactly one zero byte admits deny-all and every nonzero grant bit rejects before a trusted posture exists.

Negative tests cover profile substitution, malformed IDs, oversize/depth exhaustion, duplicate/noncanonical HPTC collections, invalid bool/tag bytes, arithmetic overflow, missing registry definitions/profiles and raw authority widening. Any future persistence/network/effect surface is outside this module and requires a separate owner boundary.

## 10. Performance, capacity and hot-path policy

Current source-enforced ceilings are: StableId 128 encoded bytes; HPTC V1 256 KiB; canonical container 4096 items and depth 16; registry 256 total ordinary/profile definitions; ordinary definition 4096 UTF-8 bytes and 256 KiB aggregate ordinary-definition bytes; numeric signals 4096 elements. Checked arithmetic rejects overflow rather than saturating.

These are semantic capacity limits, not target-host latency claims. Named product composition must measure host-level latency/allocation separately.

## 11. Observability and operations

Pure value library; no daemon, database, migration, log sink or shutdown sequence. Consumers pin exact ID/numeric profiles and an immutable registry generation. Invalid conversion or unresolved profile is rejection, never fallback to a looser arithmetic path.

Current format references:

- [codex-rs/hepta-types/CANONICAL_DIGEST_V1.md](../../../codex-rs/hepta-types/CANONICAL_DIGEST_V1.md)
- [codex-rs/hepta-types/NUMERIC_SIGNAL_CONVERSION.md](../../../codex-rs/hepta-types/NUMERIC_SIGNAL_CONVERSION.md)
- [docs/lane-a-foundation/platform.types/PRIMITIVES_V1.md](../../lane-a-foundation/platform.types/PRIMITIVES_V1.md)

## 12. Verification and qualification

Current focused evidence sources (references, not pass receipts):

- `bounded_tests.rs`: byte/allocation bounds;
- `identity_tests.rs`: exhaustive/profiled IDs, monotonic overflow, raw authority-bit rejection and sealed non-authorizing posture;
- `canonical_digest_tests.rs`: frozen bytes/digest, ordering, HPTC raw validation, invalid bool/tag, truncation/trailing bytes and NFC/NFD separation;
- `registry_tests.rs` + `numeric_profile_tests.rs`: registry bounds/namespace invariants and profile identity/version/scale/rounding binding;
- `numeric_conversion_tests.rs`: rounding/overflow and registry-admitted source/target profile + normalization;
- `CANONICAL_V1_CONFORMANCE.json`: five accepted + seven rejected vectors with Python/Node oracles;
- `bindings/generate_bindings.py --check` plus generated Python/JavaScript consumer gates.

Lane A CI executes all of the above plus native tests/strict lint on exact HEAD and deterministic synthetic merge. Workflow artifacts are the candidate receipts.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `P0.7E-DEPENDENCY-INVERSION`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `PLATFORM-0-TYPE-BOUNDARY`

The bootstrap package is `PLATFORM-0-TYPE-BOUNDARY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, current-truth/evidence maps and closed-world validation. `implementedOperationMappingComplete` covers only operations actually claimed by the candidate. `ownedTargetProtocolSourceComplete` covers every protocol canonically owned by the module and remains false while the three manifest protocols are source-pending. The legacy broad `nativeSourceMappingComplete` must not be used to collapse these meanings.

Composition requires a named authenticated product caller; qualification requires exact-head and synthetic-merge receipts. Acceptance, selection, promotion and release are separate externally governed states. This document grants no runtime/effect/deployment authority.

### Work-package execution envelopes

#### `LRN-0-CAUSAL-LEARNING-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `learning-platform` / `cognitive-platform`.
- Allowed write paths:
- `codex-rs/hepta-learning-ledger/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- Activation predecessors:
- `DOC-2-DEFAULT-BRANCH-SELECTION`
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

#### `NDU-0-PREFERENCE-UTILITY-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `intelligence-platform` / `learning-platform`.
- Allowed write paths:
- `codex-rs/hepta-ndu/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- Activation predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
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

#### `OBJ-0-OBJECTIVE-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `intelligence-platform` / `kernel-contracts`.
- Allowed write paths:
- `codex-rs/hepta-objective/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- Activation predecessors:
- `DOC-2-DEFAULT-BRANCH-SELECTION`
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

#### `P0.7E-DEPENDENCY-INVERSION`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `kernel-contracts` / `integration`.
- Allowed write paths:
- `codex-rs/hepta-wire/**`
- `codex-rs/hepta-types/**`
- `codex-rs/Cargo.toml`
- Development predecessors:
- `MEM-0-TYPES`
- `P0.7B-B4-CALLSITE-PROOF`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- Activation predecessors:
- `P0.7B-B4-CALLSITE-PROOF`
- `MEM-0-TYPES`
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

#### `PIM-0-PROMPT-INTERVENTION-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `intelligence-platform` / `cognitive-platform`.
- Allowed write paths:
- `codex-rs/hepta-prompt-registry/**`
- `codex-rs/hepta-prompt-optimizer/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- Activation predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
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

#### `BIO-0-NEURON-INTUITION-CONTRACTS`

- State: `planned`; priority: `2`; parallel class: `contract_first_parallel`.
- Owner/deputy: `learning-platform` / `inference-platform`.
- Allowed write paths:
- `codex-rs/hepta-neuron/**`
- `codex-rs/hepta-intuition/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- Activation predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
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

#### `HBO-0-BELLMAN-OPERATOR-CONTRACTS`

- State: `planned`; priority: `2`; parallel class: `contract_first_parallel`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-bellman-operator/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- Activation predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
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

#### `PLATFORM-0-TYPE-BOUNDARY`

- State: `source_implemented_execution_pending`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `kernel-contracts` / `architecture`.
- Allowed write paths:
- `codex-rs/hepta-types/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `P0.7E-DEPENDENCY-INVERSION`
- Activation predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `P0.7E-DEPENDENCY-INVERSION`
- Required deliverables:
- `exact_source_identity`
- `static_verification`
- `focused_tests`
- `clean_worktree`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `platform.types` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `ModulePort::platform.types::cognitive.types`
- `ModulePort::platform.types::context.compiler`
- `ModulePort::platform.types::intuition.policy`
- `ModulePort::platform.types::kernel.authority`
- `ModulePort::platform.types::kernel.evidence`
- `ModulePort::platform.types::kernel.operations`
- `ModulePort::platform.types::learning.artifacts`
- `ModulePort::platform.types::learning.ledger`
- `ModulePort::platform.types::learning.operator`
- `ModulePort::platform.types::neuron.runtime`
- `ModulePort::platform.types::objective.compiler`
- `ModulePort::platform.types::platform.wire`
- `ModulePort::platform.types::prompt.optimizer`
- `ModulePort::platform.types::prompt.registry`
- `ModulePort::platform.types::utility.ndu`
- `RandomStreamManifestV1`

**Consumed contracts:**
- None.

**Typed protocols:**
- `RandomStreamManifestV1`

**Owned data domains:**
- `random_stream_manifest_v1`

**Read data domains:**
- None.

**Work packages:**
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `P0.7E-DEPENDENCY-INVERSION`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `PLATFORM-0-TYPE-BOUNDARY`

**Owned threats:**
- None.

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `platform.types` to primary lane `LANE-A-FOUNDATION`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- `ExternalSystemManifestV1`
- `SensorCalibrationManifestV1`

Consumed readiness protocols:

- `ParallelLaneEnvelopeV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-0-EXTERNAL-SYSTEM-CONTRACTS`
- `EMB-0-EMBODIED-CONTRACTS`

## 17. Source implementation receipt

This receipt records repository source bindings for the current documentation
candidate. It is navigation evidence only; it does not claim product
composition, deployment or external effect authority.

| Operation | Native symbol / artifact | Source path | Primary verification |
|---|---|---|---|
| bounded values | `BoundedText` / `BoundedBytes` | `codex-rs/hepta-types/src/bounded.rs` | `bounded_tests.rs` |
| profiled identity | `validate_id` | `codex-rs/hepta-types/src/identity.rs` | `identity_tests.rs` |
| raw authority rejection | `AuthorityPosture::try_from_wire_bytes` | `codex-rs/hepta-types/src/identity.rs` | all eight grant bits reject |
| canonical commitment | `canonical_digest_v1` | `codex-rs/hepta-types/src/canonical_digest.rs` | accepted cross-language vectors |
| canonical raw validation | `canonical_validate_v1` | `codex-rs/hepta-types/src/canonical_digest.rs` | invalid bool/tag/order/truncation cases |
| FixedQ32 compatibility arithmetic | `FixedQ32` | `codex-rs/hepta-types/src/fixed.rs` | explicit toward-zero profile tests |
| immutable registry | `ContractRegistryV1` | `codex-rs/hepta-types/src/registry.rs` | namespace/profile/capacity tests |
| numeric profile admission | `NumericProfileDefinitionV1` | `codex-rs/hepta-types/src/numeric_profile.rs` | identity/version/scale/rounding tests |
| numeric conversion | `rescale_signal` | `codex-rs/hepta-types/src/numeric_conversion.rs` | rounding/overflow/digest tests |
| registry-admitted conversion | `rescale_signal_registered` | `codex-rs/hepta-types/src/numeric_conversion.rs` | normalization + both-profile admission |
| generated bindings | `generate_bindings.py` | `codex-rs/hepta-types/bindings/` | generator drift + Python/JavaScript consumer gates |

- Exact source binding is recorded in `IMPLEMENTATION_MAP.json` using
  `latest_declared_root_commit_v1`.
- `implementedOperationMappingComplete=true` means the rows above have native
  source and verification anchors.
- `ownedTargetProtocolSourceComplete=false` while
  `RandomStreamManifestV1`, `ExternalSystemManifestV1` and
  `SensorCalibrationManifestV1` remain source-pending.
- `productCallerState=not_composed`; generated bindings and qualification
  callers are not production callers.
- Production implementation, independent acceptance, activation and release
  remain false until their separate evidence gates pass.
