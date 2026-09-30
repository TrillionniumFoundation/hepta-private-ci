# platform.types

`platform.types` is the bounded, canonical, versioned type foundation for platform identities, digests, registries, numeric profiles, protocol descriptors, and strict wire exchange. Types represent validated data; they do not grant authority.

## Current authoritative entry points

There are exactly three current human-readable entry points:

1. [`SPEC_V2.md`](./SPEC_V2.md) — branch-independent normative contract: types, canonical bytes, digest domains, wire schema, bounds, protocol catalog, compatibility, and errors.
2. [`IMPLEMENTATION_STATUS.md`](./IMPLEMENTATION_STATUS.md) — fail-closed implementation, qualification, approval, merge, and activation state model.
3. [`MIGRATION_V1_TO_V2.md`](./MIGRATION_V1_TO_V2.md) — API mapping, shim policy, mandatory consumer ledger, and wire migration scope.

No amendment, closure report, generated JSON file, workflow log, or archived evidence bundle is a fourth current authority. When supporting prose conflicts with these entry points, treat the claim as unresolved and fail closed until the source and generated evidence agree.

## Generated contract artifacts

These files are machine-readable derivatives and must be regenerated or validated in CI:

- [`PUBLIC_API_INVENTORY_V1.json`](./PUBLIC_API_INVENTORY_V1.json)
- [`COMPATIBILITY_MATRIX_V1.json`](./COMPATIBILITY_MATRIX_V1.json)
- [`IMPLEMENTATION_MAP.json`](./IMPLEMENTATION_MAP.json)

A generated file does not independently establish qualification. Its source SHA and clean-worktree proof must be present in the exact-source evidence bundle.

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

Their effective metadata is:

```yaml
status: superseded-or-supporting
superseded_by:
  - SPEC_V2.md
  - IMPLEMENTATION_STATUS.md
  - MIGRATION_V1_TO_V2.md
source_sha: recorded-inside-each-artifact-or-associated-evidence
valid_until: superseded-on-adoption-of-three-entry-contract
```

The files are intentionally not moved yet because existing evidence links and qualification tooling may address their current paths. A later mechanical archive move is safe only after all path consumers are generated from the documentation manifest.

## Qualification rule

The module is qualified only when one immutable source SHA has a complete green exact-source record, a fixed synthetic-merge record, self-contained evidence, mandatory consumer closure, and independent same-head approval; the reviewed candidate must then be merged, verified post-merge, and explicitly activated. Missing or mixed-SHA evidence is failure, not “unknown success.”

CI enforces the three-entry documentation contract and removed-API scan through `scripts/check_platform_types_documentation_contract.py` and `scripts/check_platform_types_legacy_api_usage.py`.
