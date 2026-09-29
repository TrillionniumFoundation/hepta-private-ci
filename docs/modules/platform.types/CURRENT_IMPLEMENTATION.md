# `platform.types` current implementation

This file is the stable module-level entrypoint for the current executable
state. The detailed source map and integration guide remains
`docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md`; this file
makes the normative precedence, completion vocabulary, identity semantics and
qualification boundary explicit in the module documentation tree.

## 1. Normative precedence

When sources disagree, interpret the module in this order:

1. native Rust contracts in `codex-rs/hepta-types/src/` and the typed protocol
   catalog in `protocol_catalog_v2.rs`;
2. strict product codecs in `codex-rs/hepta-wire`, executable schemas and
   cross-language conformance vectors;
3. exact-candidate provenance, rustdoc/API, test, lint, Miri, fuzz and document
   evidence produced by the qualification workflows;
4. this current-state entrypoint and
   `TECHNICAL_CURRENT_AMENDMENT_V2.md`;
5. historical architecture and generated registry projections.

Historical prose is retained for compatibility and design context. It cannot
override current native constructors, exact schema bytes or candidate-bound
execution evidence.

## 2. Completion vocabulary

`platform.types` does not compress all completion states into one Boolean.
The following claims are independent:

| State | Current source claim |
| --- | --- |
| specification defined | yes |
| native source implemented | yes |
| strict product codecs implemented | yes |
| named owner callsites composed in source | yes |
| exact source-head qualification | derived per final candidate; no failure diagnostic substitutes for a receipt |
| deterministic synthetic-merge qualification | derived separately per final candidate |
| eligible independent approval | separate governance gate |
| authenticated registry publication | not owned by this module |
| deployed activation, promotion and release | not claimed |

A candidate is not complete merely because its source exists or an artifact was
uploaded. The exact source head and its deterministic synthetic merge must each
produce their own retained successful receipt. Independent review and product
release remain separate.

## 3. Registry identity and freshness

`ContractRegistryV1` content identity is the versioned canonical
`Digest32` commitment over the sorted definition and numeric-profile digests.
It is not an FNV checksum and is not a signature. The immutable registry
computes that commitment once after validation and reuses it. Exact
kind/identifier/version and numeric-profile lookups reuse canonical sort order
through binary search. Digest lookup uses a bounded immutable projection built
once from the already-validated entries and sorted by `(kind, digest, canonical
entry index)`, avoiding a repeated linear scan without introducing mutable or
authoritative state. The index has at most `MAX_REGISTRY_ENTRIES_V1` entries,
and its construction and lookup costs remain covered by the same-candidate
registry benchmark.

These optimizations reuse immutable structural work only. They do not cache any
of the following:

- whether a registry generation is still current;
- whether a caller is authorized;
- whether a receipt is acceptable at final use;
- whether deployment or promotion has been approved.

`RegisteredNumericConversionReceiptV2::verify` proves self-contained receipt
integrity. A generation-sensitive product owner independently pins
`RegistrySnapshotIdentityV1` and calls `verify_for_snapshot`; authentication,
publication and advancement of that pinned snapshot remain external owner
responsibilities.

## 4. Product composition boundary

The current source composition follows existing owners rather than a parallel
demonstration path:

| Product owner | Native boundary | Final-use responsibility |
| --- | --- | --- |
| Codex/Agentd and Learning Ledger | frozen Prompt V1 compatibility path | durable consumer policy and execution authority |
| Runtime Supervisor | validated topology candidate | topology admission and effect-boundary authority |
| NDU numeric owner | registered numeric V2 receipt | independently pinned current registry snapshot |
| NDU random-stream owner | random-stream manifest | exact seed, namespace, generator, episode, decision and counter window |
| Runtime Supervisor external-system owner | external-system manifest | host identity and authorization witness |
| Runtime Supervisor sensor owner | sensor-calibration manifest | hardware/adapter, generation, clock domain and failure policy |

All source-level admission receipts remain
`NonAuthorizingPosture::DENY_ALL`. Source composition proves that the existing
product path performs the checks; it does not grant deployment, external
execution, write, promotion or release authority.

## 5. Qualification contract

The deep workflow resolves a requested source ref once, records the resolved
source and base identities, and checks out those frozen identities in both
lanes. Manual `candidate_ref` resolution is fail-closed; it is not silently
replaced by the default branch. Acceptance uses an explicitly pinned Rust/MSRV
toolchain, while compatibility with later stable toolchains is a separate
signal. Environment evidence records the compiler, Cargo, runner image,
architecture and workflow identity.

Qualification keeps these outcomes separate:

- schema/catalog parity;
- source truth and generated-projection drift;
- exact Git provenance;
- complete rustdoc public-API compatibility;
- declared-MSRV checks;
- native tests and strict Clippy;
- pinned Miri;
- bounded coverage-guided fuzzing;
- source-head and synthetic-merge document bundles.

A failed step produces diagnostics only. A qualification receipt is emitted
only when every required outcome succeeds for the same exact candidate.
Uploaded logs, historical green runs and a successful artifact-upload step are
not receipts.

The Rama dependency guard models one coherent reviewed prerelease graph. Every
Rama product and support crate selected by `codex-network-proxy`, including
`rama-error`, `rama-macros` and `rama-utils`, is fixed to exact
`0.3.0-alpha.4`. This explicit support-crate pin is necessary because Cargo's
ordinary prerelease range may otherwise advance those dependencies to stable
`0.3.0`, whose API is not source-compatible with `rama-core 0.3.0-alpha.4`.
Mixed releases, unreviewed Rama packages and version drift fail closed.

## 6. Public API evidence

The committed exact-`pub use` inventory is a narrow ownership projection. Full
compatibility is derived from rustdoc JSON. Rustdoc numeric item identifiers,
including `Visibility::Restricted.parent` and tuple-variant payload IDs, are
normalized to stable structural references before comparison. This prevents
unrelated additive items from renumbering an unchanged private/restricted child
and creating a false breaking change. Actual public removals, kind changes,
field/variant changes, signature changes, payload changes or changes to the
referenced restricted parent still fail closed.

## 7. Current non-claims

The following remain outside the module's source claim:

- authenticated publication and rotation of registry snapshots;
- migration of every historical Prompt producer and durable consumer to V2;
- deployed random execution, host inventory collection or physical sensor
  drivers;
- target-host soak, operator canary acceptance, promotion and release;
- an eligible independent approval for any future exact head merely because an
  approval existed for an older head.

Exact current candidate status belongs to GitHub checks and retained receipts,
not to self-referential commit identifiers embedded in prose.
