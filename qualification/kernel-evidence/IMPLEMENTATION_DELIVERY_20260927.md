# kernel.evidence implementation delivery, 2026-09-27

## Candidate and scope

The sole candidate advanced in this delivery is PR #1092 on
`fix/kernel-evidence-production-closure`. The fixed integration base is
`a126987b84737dbc2ee2592442a314117bddb4a2`. No main merge, force push, independent
approval, deployment, canary or release was performed. Other module and evidence
branches were not modified.

The source examined at the start had already advanced from the earlier audit to
`d266a8d8ad7f2d51fc8c767b7112aab37fe31fac`, tree
`21368c768e2322f021bf19228dad168dc08eb875`. That predecessor supplied the actual
bounded independent-identity solver, named verification profiles, sealed
store/role-bound issuer inputs, same-transaction claim verification and the
full stored-admission commitment helper. These are inherited changes, not new
work attributed to this delivery. They still need native qualification.

This delivery advances implementation. **Stages A through D are NOT jointly
complete.** An implementation note or commit does not qualify a candidate.

## Actual pushed implementation

### 88d31c216f1a058d285cce9b6baf728fb9065485

`recovery_frontier.rs` now delegates to `recovery_snapshot.rs`. Migration,
qualification and replay frontiers are read through the same SQLite transaction
and connection. An independent writer cannot make the collector combine an old
qualification prefix with a new replay state.

The historical `recovery_snapshot()` API preserves V1 envelope-only digest
semantics. `authenticated_recovery_snapshot()` produces wire snapshot version 2:
it requires an explicitly enrolled store identity and commits every stored
admission field through `authenticated_row_sha256`, rather than just the public
envelope hash. The Rust struct retains its historical name for source
compatibility; its serialized schema version distinguishes the digest semantics.
Never relabel an existing signed V1 snapshot as V2.

Qualification bodies are read in 32-row keyset pages after an SQL byte-length
preflight. The configured scan limits are one million rows, 512 MiB of aggregate
canonical envelope bytes, 256 KiB per envelope, 16,384 replay rows and 1,024
migration rows. These are enforced limits, not measured production capacity.
They do not establish a hard bound on all other store-open scans or on elapsed
recovery time.

Three native source regressions cover one held WAL read epoch, enrollment and
store identity, and separate mutation of seven authentication metadata fields.
The latter deliberately simulates offline tampering; it is not a runtime SQL
escape or an API for mutating evidence.

### 142bf6cf853e4bee3345ffbbe8c95668707bc53b

Agentd production admission and read-only preflight consume the authenticated
snapshot. The frontier decoder retains historical V1 readability, but the
production verifier requires snapshot version 2 and recomputes the local value.
Production enrollment must therefore precede startup. Startup cannot silently
create an unbound recovery identity or promote an old snapshot.

The production verifier returns the exact issuer-registry digest admitted by the
signed frontier. `EvidenceHost` retains it in a private production trust mode
and supplies it to every owner-registry load. A registry replacement is checked
again before publishing the host. Development-mode reload behavior remains
separate. This closes silent registry substitution within an admitted process
generation; it is NOT the complete live monotonic rotation protocol.

Existing receipt, signature, build, path and backup checks remain. Their private
implementation was extracted to `evidence_production_checks.rs`, included in
the same module. The non-Unix implementation still fails closed. Source files
are included by the Agentd Bazel source glob; no dependencies were added.

### 88dfa09120ecd856611d106dec485df3aa153e55

Five new integration tests compile against the ordinary evidence library, not
unit-test-only raw trust adapters. They cover an old registry against the
admitted digest, a registry changed after verification, cross-store/role reuse,
revoked issuer construction and agent identity substitution.

The read-only `kernel-evidence-core-regression.yml` workflow runs the actual
`identity_assignment.rs` with `rustc --test`, including its Cartesian-product
oracle, separately on the exact source and a deterministic ordered-parent merge.
It also runs an independent SQLite protocol probe and retains diagnostics. This
small diagnostic lane does not replace evidence-package, Agentd, architecture,
formatting, Clippy or full qualification workflows. It has no write permission
and never modifies source or claims independent authority.

## Execution evidence actually obtained

The independent Python/SQLite probe ran locally: **8 tests passed** with Python
3.13.5 and SQLite 3.46.1. This executes SQLite/WAL protocol experiments; it does
not execute the Rust implementation, SQLx integration or real Agentd.

- Probe path: `qualification/kernel-evidence/probes/test_recovery_protocol.py`.
- Exact source Git blob: `5cdb4055f29fec5de043e4d3eb851a4a9b0695a8`.
- Source SHA-256: `4aea83fd1b45102c792b83aaf2b05977dcb3cdd47049da097b793ef164e199ed`.
- Execution log SHA-256: `fe6aaa2c4dea0401fea3d97ded489387a616d252e709c161a6f8f4f3bcab3303`.

The source blob was independently read back from GitHub and matched the locally
executed bytes. The log and scoped result are retained alongside this note.
No local Rust compiler, rustfmt, Clippy or complete checkout/build environment
was available. Native compilation, package execution and formatting are **not
claimed**. At observation, the core run `36305085174` was queued, convergence
`36305085320` was pending and `blocking-ci` `36305085173` was pending on source
`88dfa09120ecd856611d106dec485df3aa153e55`. These are historical observations,
not successful qualification or evidence for a later documentation head.

## Remaining source blockers, in required order

### A: trusted decision correctness

Run the actual native solver oracle and product integration tests. Verify every
consumer's required profile is bound to its intended claim; a named profile
alone is not proof that a consumer chose the right minimum policy. Compile-fail
and integration tests must establish that downstream crates cannot supply raw
registrations or arbitrary verification bindings. The source changes are present;
final native execution is outstanding.

### B: durable recovery and publication

The snapshot now represents one database epoch, but there remains a gap between
snapshot verification and the separate local frontier-acceptance transaction.
Close it with a durable owner/generation fence. Persist pending publication in
the same transaction as the operation that requires it; recover claim, backup,
signing, CAS dispatch and acknowledgement boundaries without replacing an
unknown outcome with a new operation identity.

Keep local commit and external anchoring distinct. Current Agentd appends still
commit locally; they do not drive external CAS. The locked-file backend remains
a real adapter, not a composed continuous publisher. A restart after unpublished
writes can still require recovery. No zero-data-loss or continuous external
rollback protection is asserted by this change.

New admission rows still need persisted original signature material and
trust-generation provenance. Historical V1 rows did not retain signatures; a
new hash cannot reconstruct them. The V2 commitment detects later changes when
compared with its signed external anchor, but is not itself a signature.

Production trust is pinned for one process generation. An independently rooted,
monotonic trust transition and revocation lifecycle remains required. Do not
introduce a self-signed registry whose own untrusted contents supply its roots.

### C: product and long-term operation

Wire stable cursor paging and bounded verification summaries into the Agentd
protocol. The existing V1 query still invokes the unpaged method. Replace
path-derived mode selection in public composition with explicit typed modes.

The backup receipt currently binds a snapshot description, not the bytes of a
located durable backup object. Add immutable object identity/version, length,
content digest, storage acknowledgement and witnessed restoration. Likewise,
binding a binary hash and source hash separately does not establish governed
build provenance. Neither issue was claimed solved here.

Add bounded journal segmentation and archival verification, an authenticated
latest index, observability, pressure behavior, target-host RPO/RTO and capacity
measurements. Do not clear history to regain capacity or treat synthetic
fixtures as production measurements.

### D: final candidate and documentation qualification

The implementation map now records production incompleteness, corrects the
moved error-binding path, maps the new authenticated snapshot and stops claiming
that library paging/CAS/history are product-composed. Its source anchor is the
real implementation commit, not a self-referential documentation SHA.

`STATUS_SOURCE.json` and its five generated projections still carry the older
`2d8505b...` source anchor. They must be regenerated together after final source
closure; their old false gates are not current-head pass receipts. This delivery
does not mask that drift or claim the documentation checks pass. Preserve the
existing technical material while reconciling its current-versus-target claims.

Run exact source and fixed-main merge qualification after formatting and fixes,
retain real logs and artifact digests, and obtain independent authority receipts
for target-host activation and acceptance. A subsequent source change invalidates
older exact-candidate execution evidence.

## Claim boundary

`productionImplementation`, `productExecutionProved`, `independentAcceptance`,
`activation` and `release` remain false in the implementation map. The existing
canonical qualification/deployment gates remain false. This file is an
implementation and execution log, not a second canonical status source and not
an authority receipt.
