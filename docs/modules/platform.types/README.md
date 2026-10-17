# platform.types

`platform.types` is the bounded, canonical, versioned type foundation for platform identities, digests, registries, numeric profiles, protocol descriptors, and strict wire exchange. Types represent validated data; they do not grant authority.

## Current authoritative entry points

There are exactly three current human-readable entry points:

1. [`SPEC_V2.md`](./SPEC_V2.md) — branch-independent normative contract: types, canonical bytes, digest domains, wire schema, bounds, protocol catalog, compatibility, and errors.
2. [`IMPLEMENTATION_STATUS.md`](./IMPLEMENTATION_STATUS.md) — fail-closed implementation, qualification, approval, merge, and activation state model.
3. [`MIGRATION_V1_TO_V2.md`](./MIGRATION_V1_TO_V2.md) — API mapping, shim policy, mandatory consumer ledger, and wire migration scope.

No amendment, closure report, generated JSON file, workflow log, or archived evidence bundle is a fourth current authority. When supporting prose conflicts with these entry points, treat the claim as unresolved and fail closed until source and generated evidence agree.

## Generated contract artifacts

These machine-readable derivatives are read-only review surfaces. They do not independently establish qualification:

- [`PUBLIC_API_INVENTORY_V1.json`](./PUBLIC_API_INVENTORY_V1.json)
- [`COMPATIBILITY_MATRIX_V1.json`](./COMPATIBILITY_MATRIX_V1.json)
- [`IMPLEMENTATION_MAP.json`](./IMPLEMENTATION_MAP.json)
- [`TRUTH_MATRIX_V2.json`](./TRUTH_MATRIX_V2.json)

`TRUTH_MATRIX_V2.json` is generated from the public API inventory, compatibility matrix, implementation map, fail-closed status source, and archive manifest. Candidate SHA, workflow success, reviewer approval, and activation are deliberately excluded from committed generated truth; they belong only in exact-SHA runtime evidence.

Run the complete read-only drift check with:

```bash
python3 scripts/check_platform_types_generated_artifacts.py
```

The individual write command for the current truth projection is:

```bash
python3 scripts/platform_types_truth_matrix.py --write
```

A generated file is accepted only when CI regenerates or verifies its source facts, proves the worktree remained unchanged, and binds runtime evidence to the exact checked-out source SHA.

## Supporting normative detail

The following files retain detailed design material referenced by `SPEC_V2.md`:

- [`TECHNICAL.md`](./TECHNICAL.md)
- [`NORMATIVE_PROTOCOL_SOURCE_V2.md`](./NORMATIVE_PROTOCOL_SOURCE_V2.md)
- [`PROTOCOL_AND_QUALIFICATION_V1.md`](./PROTOCOL_AND_QUALIFICATION_V1.md)

They remain reviewable source material, but current interpretation starts from `SPEC_V2.md`.

## Historical and qualification records

The following files are retained for provenance and audit continuity. They are non-authoritative for current status and must not be quoted alone as proof that the current head is qualified or activated:

- [`CURRENT_IMPLEMENTATION.md`](./CURRENT_IMPLEMENTATION.md)
- [`TECHNICAL_CURRENT_AMENDMENT_V2.md`](./TECHNICAL_CURRENT_AMENDMENT_V2.md)
- [`DEEP_QUALIFICATION_V1.md`](./DEEP_QUALIFICATION_V1.md)
- [`QUALIFICATION_HARDENING_20260928.md`](./QUALIFICATION_HARDENING_20260928.md)
- [`QUALIFICATION_INTEGRITY_20260929.md`](./QUALIFICATION_INTEGRITY_20260929.md)
- [`NDU_SNAPSHOT_INTEGRATION_20260929.md`](./NDU_SNAPSHOT_INTEGRATION_20260929.md)
- [`REMAINING_GAPS_CLOSURE_20260929.md`](./REMAINING_GAPS_CLOSURE_20260929.md)
- [`OPTIMIZATION_CLOSURE_20260929.md`](./OPTIMIZATION_CLOSURE_20260929.md)

Their effective metadata is machine-enforced by [`archive/MANIFEST.json`](./archive/MANIFEST.json). Every retained record is marked `superseded`, names its `supersededBy` authority, records an immutable `sourceSha` and `sourceGitBlob`, and remains valid only until `path-bound-evidence-retirement`.

The historical files remain at their existing paths because exact-source evidence and qualification tooling still address those paths. CI verifies that their bytes still match the recorded Git blobs. A later mechanical move into `archive/` is permitted only after all path-bound consumers resolve records through the manifest.

## Qualification rule

The module is qualified only when one immutable source SHA has a complete green exact-source record, a fixed synthetic-merge record, self-contained evidence, mandatory consumer closure, and independent same-head approval; the reviewed candidate must then be merged, verified post-merge, and explicitly activated. Missing or mixed-SHA evidence is failure, not “unknown success.”

CI enforces the three-entry documentation contract, immutable archive metadata, removed-API scan, compatibility/source binding, generated truth projection, and clean-worktree proof.
