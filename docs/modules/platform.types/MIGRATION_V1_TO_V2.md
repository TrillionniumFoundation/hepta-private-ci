# platform.types Migration: V1 to V2

Status: current migration authority  
Specification: [`SPEC_V2.md`](./SPEC_V2.md)  
Qualification status: [`IMPLEMENTATION_STATUS.md`](./IMPLEMENTATION_STATUS.md)

This document is the single current ledger for public API, owner, consumer, registry, and wire migration from V1 to V2. Migration is not complete merely because the core crate compiles.

## API mapping

| V1 or legacy surface | V2/current surface | Policy |
|---|---|---|
| `Digest32::as_bytes()` | `Digest32::as_array()` for a borrowed `[u8; 32]`; `Digest32::into_array()` for owned bytes | Internal consumers must migrate atomically. Do not reintroduce an unbounded compatibility alias unless an external compatibility obligation is documented. |
| unprofiled identity strings | `StableId` plus an explicit identity profile at the protocol field | Fail closed on invalid or unsupported profiles. |
| unbounded `Vec<u8>`/`String` at trust boundaries | bounded byte/text constructors and bounded readers | Preflight before allocation where possible. |
| ad-hoc JSON decoding | strict schema decoding with unknown/duplicate/trailing-value rejection | No permissive product fallback. |
| registry use without snapshot identity | generation plus registry digest/snapshot receipt | V2 owners must bind and verify the exact snapshot. |
| implicit message discovery | generated protocol catalog allowlist | Unknown kinds fail closed. |
| V1 numeric admission | V2 admission/receipt bound to profile, registry, generation, schema, and signal | An explicit V2 owner cannot silently downgrade. |

## Compatibility shim policy

A shim is allowed only when all of the following are recorded:

- the external consumer that still requires it;
- exact behavior and security limits;
- tests proving it cannot bypass V2 validation or owner authority;
- the first release in which it exists;
- the earliest release in which it may be removed;
- an accountable owner and removal issue.

Shims are adapters, not alternate execution paths. New product code must use the current API. Internal workspace consumers should be migrated in the same commit as a breaking API change; a deprecated alias is a last resort, not the default fix.

## Mandatory consumer ledger

The exact list is generated from the workspace and implementation map. At minimum, qualification covers:

| Consumer/boundary | Required V2 posture | Current ledger posture |
|---|---|---|
| `codex-hepta-types` | current constructors, canonical bytes, digest domains, registries, profiles | implemented; exact-head qualification required |
| `codex-hepta-wire` | strict V2 schema/catalog decoding and bounded validation | implemented; cross-platform/exact-head qualification required |
| `codex-hepta-ndu` | numeric snapshot generation/digest binding and current `Digest32` API | migration repaired in the candidate; mandatory test must pass |
| generated protocol bindings | deterministic output from the active catalog | regeneration and clean-tree check required |
| legacy fixtures/consumers | self-contained positive and negative fixtures tied to exact source | closure evidence required |
| product owners listed in `IMPLEMENTATION_MAP.json` | no hidden V1 fallback at final use | generated ledger and owner tests required |

“Implemented” does not mean “qualified.” The generated exact-source status artifact is authoritative for pass/fail.

Candidate evidence is self-contained by construction. Qualification evidence paths must resolve to regular files inside the checked-out repository tree; absolute paths outside that tree, parent traversal, and symlink evidence are rejected before a receipt can be emitted. This prevents a runner-local path from becoming part of a supposedly portable positive fixture.

## Consumer migration procedure

For each public API or wire change:

1. update the specification/catalog source;
2. update the implementation and generated artifacts;
3. search the full tracked workspace for removed API and schema use;
4. migrate all mandatory consumers in the same candidate;
5. add a negative gate for the removed form where practical;
6. run exact-source and fixed synthetic-merge checks;
7. update this ledger only with evidence-backed status;
8. obtain independent approval after the final change.

A core-only green test run cannot close migration.

## Wire compatibility scope

V1 and V2 are wire-compatible only where the generated compatibility matrix explicitly says so. In particular:

- a decoder must not accept unknown fields merely to preserve forward compatibility;
- canonical byte or digest-domain changes require a new version/domain;
- V2 snapshot-bound receipts cannot be represented as V1 receipts without losing security meaning;
- identity-profile changes are breaking unless the field declares a compatible profile set;
- bounds are part of the contract; increasing or decreasing them requires compatibility review;
- an adapter must preserve exact semantic fields and must not manufacture authority.

The machine-readable matrix is [`COMPATIBILITY_MATRIX_V1.json`](./COMPATIBILITY_MATRIX_V1.json). CI must regenerate or validate it and fail on drift.

## Earliest shim removal

No general removal release is asserted in this checked-in document. Each actual shim must name its own earliest removal release in generated migration metadata. For the internal `Digest32::as_bytes()` call site, the preferred closure is direct migration to `as_array()`; no compatibility shim is required.

## Completion criteria

V1-to-V2 migration is complete only when:

- removed API usage is absent from tracked mandatory consumers;
- every owner and field uses the catalog-declared V2 profile;
- positive and negative legacy fixtures are self-contained and reproducible;
- generated API, compatibility, implementation, and truth artifacts are clean;
- all required checks pass on one immutable candidate SHA and its fixed synthetic merge;
- a non-author approves that same SHA;
- the merge SHA passes post-merge verification;
- activation names that merge SHA.
