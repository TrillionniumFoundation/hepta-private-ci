# platform.types Specification V2

Status: normative entry point  
Scope: branch-independent platform type and wire contracts  
Specification version: `platform.types/v2`

This file is the single current entry point for the normative `platform.types` contract. It intentionally contains no branch name, source commit, workflow result, approval, or activation claim. Runtime and repository status belong in [`IMPLEMENTATION_STATUS.md`](./IMPLEMENTATION_STATUS.md); migration state belongs in [`MIGRATION_V1_TO_V2.md`](./MIGRATION_V1_TO_V2.md).

Detailed source material remains in the repository for review and provenance. Where older documents differ from this entry point, this entry point and the generated protocol/catalog artifacts named below control. Historical closure reports never establish current qualification.

## 1. Architectural boundary

`platform.types` defines data, validation, canonical encoding, stable identities, registries, and protocol descriptors. A valid value is not an authorization token and does not grant network, execution, persistence, publication, or provider access. Final-use authority remains with the owning runtime boundary.

All public constructors and decoders are fail-closed: values that exceed a declared bound, violate a profile, contain an unknown field, use an unsupported protocol item, or fail canonical reconstruction are rejected before use.

## 2. Type invariants

The implementation must preserve these invariants:

- stable identifiers are validated under an explicit identity profile;
- digest values are exactly 32 bytes and expose byte identity without mutable aliasing;
- bounded bytes, text, collections, registries, and nested values reject oversize input;
- generations and versions use checked, monotone representations where monotonicity is required;
- numeric profiles bind scale, rounding, range, shape, unit, normalization, and registry identity;
- constructors do not silently normalize an invalid value into a different valid value;
- public types do not carry ambient authority.

The detailed Rust API description remains in [`TECHNICAL.md`](./TECHNICAL.md). The machine-readable public surface is generated as [`PUBLIC_API_INVENTORY_V1.json`](./PUBLIC_API_INVENTORY_V1.json).

## 3. Canonical bytes

Canonical bytes are deterministic across supported hosts and languages. Encoders must:

1. emit one representation for each semantic value;
2. sort map/object members by the specified canonical key order;
3. use length-delimited, domain-specific encodings;
4. reject duplicate members, trailing bytes, unsupported numeric forms, and excess nesting;
5. enforce bounds before unbounded allocation;
6. decode and canonically re-encode to bytes identical to the accepted canonical input.

A decoder accepting a non-canonical representation is a contract failure even when the representation has the same apparent semantic value.

The detailed canonical model and protocol vocabulary are maintained in [`NORMATIVE_PROTOCOL_SOURCE_V2.md`](./NORMATIVE_PROTOCOL_SOURCE_V2.md).

## 4. Digest domains

Every digest is domain-separated. A digest input must bind, as applicable:

- specification/schema version;
- message or value kind;
- identity profile;
- owner/module identity;
- registry generation and registry digest;
- all semantically relevant fields and collection members;
- canonical payload bytes.

Digests with different meanings must not share an untagged byte domain. Digest equality is semantic only for values governed by the same domain definition.

## 5. Wire schema

Wire decoders must reject:

- unknown fields unless a schema explicitly reserves them;
- duplicate fields;
- trailing bytes or trailing JSON values;
- invalid UTF-8 or invalid stable identifiers;
- arrays, objects, strings, byte strings, or nesting beyond their limits;
- messages absent from the active protocol catalog;
- schema/profile versions outside the declared compatibility window.

Validation happens both before expensive allocation where possible and after decoding before a typed value crosses an owner boundary. Wire decoding does not confer final-use authority.

## 6. Bounds

Every externally influenced allocation or traversal has a named limit. Limits cover at least:

- raw input bytes;
- canonical encoded bytes;
- text and byte-string length;
- collection element count;
- object/member count;
- registry entries and aggregate registry bytes;
- nesting depth;
- related-module/candidate cardinality;
- generated binding and test-vector size.

A limit increase is a specification change and requires compatibility review and new boundary tests. Implementations must stop reading once an input is known to exceed a limit.

## 7. Protocol catalog

The protocol catalog is the allowlist for message kinds, schema profiles, owner assignments, identity profiles, and compatibility rules. Unknown catalog entries fail closed. Catalog generation is deterministic and its generated output must be clean relative to the checked-in source.

The catalog must bind:

- message kind and version;
- field names, cardinality, nullability, and bounds;
- accepted identity profile per identity-bearing field;
- owner/module assignment;
- compatibility posture;
- canonical encoding and digest domain identifiers.

Generated bindings and vectors are derived artifacts; they do not supersede this specification or independently prove qualification.

## 8. Compatibility rules

Compatibility is explicit, not inferred from successful parsing.

- additive changes are compatible only when the active schema reserves or explicitly permits them;
- removing, renaming, retyping, or changing the meaning or bound of a field is breaking;
- changing canonical bytes or a digest domain is breaking unless introduced under a new version/domain;
- legacy APIs may exist only as documented, time-bounded shims;
- owners must not silently downgrade a V2 value, receipt, snapshot, or protocol exchange to V1;
- compatibility claims must be represented in the generated compatibility matrix and tested in positive and negative fixtures.

The migration policy and consumer ledger are in [`MIGRATION_V1_TO_V2.md`](./MIGRATION_V1_TO_V2.md). The generated matrix is [`COMPATIBILITY_MATRIX_V1.json`](./COMPATIBILITY_MATRIX_V1.json).

## 9. Error contract

Callers receive stable, matchable error categories. Internal evidence may add field paths, byte offsets, message kinds, expected profiles, observed bounds, registry generations, and source schema versions, but must not leak secrets or unbounded payloads.

At minimum, errors distinguish:

- invalid identity/profile;
- bound exceeded;
- malformed or non-canonical encoding;
- unknown or incompatible protocol item;
- registry/snapshot mismatch;
- digest/integrity mismatch;
- unsupported version;
- authority required or final-use denied at the owner boundary.

Error classification must not depend on unstable human-readable strings from a third-party parser when a structured decoder path can provide the distinction.

## 10. Generated and supporting artifacts

These artifacts are derived from source and CI and must remain reproducible:

- [`PUBLIC_API_INVENTORY_V1.json`](./PUBLIC_API_INVENTORY_V1.json)
- [`COMPATIBILITY_MATRIX_V1.json`](./COMPATIBILITY_MATRIX_V1.json)
- [`IMPLEMENTATION_MAP.json`](./IMPLEMENTATION_MAP.json)
- protocol/catalog generated bindings and test vectors
- Lane-A truth matrices, attestations, and qualification evidence

CI must regenerate applicable artifacts and fail when the worktree changes. Qualification is determined only by the exact-source evidence chain described in [`IMPLEMENTATION_STATUS.md`](./IMPLEMENTATION_STATUS.md), never by the presence of a closure document.
