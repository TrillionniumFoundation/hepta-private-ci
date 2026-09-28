# auth.authbus remediation self-review and independent acceptance gate

Review date: 2026-09-28.

**Provenance: remediation-author self-review, NOT independent acceptance.**
The previous heading and reviewer-role assertion were unsupported: this file
contained no separately identified reviewer, signed approval or immutable review
artifact. This revision removes that assertion. Neither this document nor an
AI-generated referee persona satisfies the independent security review gate.

## Scope and source findings

This self-review covers the sealed issuer handles, persisted registry loaders,
crate-private authority writer, database/checkpoint owner fencing, bounded
maintenance worker, product caller migrations, public API inventory, exact-head
receipt checker and module operational contracts.

The source includes reload of the durable issuer at settlement, negative API
compile examples, owner-lifetime guards, bounded expiration reconciliation,
shutdown-aware maintenance and label-free snapshot exposition. Those statements
identify implemented code; they are not assertions that native tests passed.
The trusted-computing boundary still includes the authority process and its
service account. An opaque handle does not make an attacker-selected filesystem
bootstrap root trustworthy or isolate hostile code sharing that OS identity.

## Evidence disposition

Source materialization and scoped publication completed on c17e17ef2ec68aa2a4de8b9c0406305063bc84c1.
The terminal artifacts of run 36369533941 report incomplete qualification:
locked Cargo resolution and formatting failed before native tests could execute.
Dependency-edge, moved-value caller and formatting repairs were subsequently
materialized in da25b0a1d312c43602b62f2e81cbfe9cfa1546e3; that is not a substitute
for terminal native evidence on the next exact candidate. Successful Python
contract tests and SQLite syntax checks are explicitly not Rust qualification.

## Independent acceptance requirements

A separate reviewer must identify their role and independence from the author,
pin the reviewed source SHA/tree and dependency/schema digests, inspect the
source-head and fixed-base merge receipts, and record findings with disposition.
The review must include registry provenance/revocation, owner collision and
process death, crash/fault boundaries, quota conservation, unknown outcomes,
product execution, and the API visibility contract. Retain the review artifact,
its digest and the explicit approval decision; do not fill these with fabricated
identities or placeholder approvals.

Production acceptance additionally requires named deployed trusted-time and
settlement signing providers, actual KMS/HSM custody and endpoint policies,
independent state-volume provisioning, working exporter/alert routes and
recorded target-host ENOSPC/power-loss exercises. The deployment document is a
contract, not proof that these resources were provisioned.

## Decision

**INDEPENDENT_ACCEPTANCE: NOT_ESTABLISHED. PRODUCTION_ACTIVATION: BLOCKED.**
Continue native qualification and review; do not merge or activate merely because
source preparation, inventory generation, or a queued workflow exists. Skipped,
cancelled, deferred, zero-test and historical-SHA results cannot close this gate.
