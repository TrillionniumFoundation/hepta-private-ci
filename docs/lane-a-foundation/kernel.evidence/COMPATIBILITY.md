# kernel.evidence compatibility

## Stable identities

Contract identifiers, canonical fields, digest domains, evidence identity and
authority meaning do not change in place. Additive fields require an explicitly
registered version and unknown critical fields fail closed. Canonical JSON and
Rust types must preserve identical semantics and deterministic ordering.

## Storage and migrations

Migrations are ordered, checksum-bound and verified on open. Runtime production
opens never create or migrate a store. An upgrade must retain historical record
interpretability, append-only constraints, accepted frontier history and exact
replay/provenance commitments. Rollback across a schema boundary requires a
binary-compatible backup and the independently retained monotonic frontier; an
older but internally valid database is not accepted as current.

## Frontier versions

V1 remains readable for historical/local recovery compatibility. Its legacy
`signature` field is an integrity token and is not an authentication claim. V2
is the production frontier and binds authenticated snapshot, ledger root,
issuer/signer registries, backend, executable, qualification receipts, backup,
source, signer-policy generation and Ed25519 signatures.

A V2 successor is automatic only under the state-machine rules in
[ARCHITECTURE.md](ARCHITECTURE.md). Store/backend/source/build/qualification,
migration or issuer-authority changes require an explicitly governed transition.
Same-generation different identities never become compatible through a
lexical/timestamp tie-break.

## API retirement

Compatibility adapters are temporary and non-production unless explicitly
admitted. Retirement requires all named callers migrated, no old-path use,
reopen and rollback rehearsal, retained historical decoding and current exact-
source plus deterministic-merge qualification. Removal must not erase lineage or
make old receipts uninterpretable.

## Evidence compatibility

Execution evidence is object-specific. A receipt for a source head cannot be
reused for a deterministic merge, GitHub synthetic merge or final real merge.
Changing Cargo.lock, tests, migrations, implementation map, documentation,
workflow or retained artifact inventory changes readiness-manifest hashes and
requires requalification.
