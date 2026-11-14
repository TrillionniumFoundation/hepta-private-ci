# Matrix SQLite 0.19.1 compatibility candidate

This document retains the original import and dependency-patch record. The current
checkout also includes the repository formatting follow-up described below.


The official archive and upstream license are bound by HEPTA-PATCH-PROVENANCE.json. Only the two rusqlite constraints change from 0.40.2 to exactly 0.39.0, retaining upstream limits, fallible_uint and cache features. This preserves the existing libsqlite3-sys 0.37 link shared with SQLx 0.9. All Rust implementation and SQL migration files remain byte-identical to the official crate.

This SDK upgrade performs real storage migrations: crypto state reaches version 19, state reaches version 16, and event cache reaches version 18 with upstream cache resets. Hepta retains the matrix-sdk-0.18 directory as its existing data identity, its human passphrase API, its own authoritative sync cursor/inbox/outbox, and its production five-second startup bound. Old SDK binaries must not reopen stores after migration; this change does not provide reverse migration or claim lossless binary rollback. Recovery requires an independently retained, consistent pre-upgrade store backup.

Native qualification must create encrypted stores and old Olm/Megolm ciphertext with the original 0.18 graph, then reopen through the candidate production API and decrypt with the existing persisted sessions. Same-version restart, matching public keys, a compilation pass, and old branch evidence are insufficient. This is a candidate until those exact-source tests and the unchanged dependency audit pass.

## Repository formatting follow-up (2026-11-14)

The normal repository formatter changed 8 Rust files.
HEPTA-FORMATTING-PROVENANCE.json binds every affected path to its exact Git
object, mode, size and SHA256 before and after formatting. The comparison uses
c2130629037b342e6e48154867b65acc8fc82434 as the input identity.

Import targets, aliases, visibility and attached attributes are retained.
Comments and non-import literals are retained; the other reviewed changes are
layout, trailing punctuation, single-expression block layout and same-order
derive grouping. Existing minimal dependency patches, upstream README files
and license bytes are retained. This record does not claim a new runtime test
result or a successful full-repository formatting check.

The original =0.39.0 description above applies to the initial compatibility
patch. Merge 9967f09c8f4b1f731fd2337356e6217583469f1e already changed both
Cargo manifests to rusqlite =0.41.1; the current manifests are preserved by
this formatting change. The original SQLite patch remains an exact historical
record, and the JSON records both that stage and the current manifest hashes.
