# Qualification prerequisite repair: SQLite policies and ownership projections

## SQLite scope

Both real operation and destination-deduplication constructors now use the
central codex-state SQLite shim. Their effective policy remains four pooled
connections, WAL, FULL synchronous durability, foreign keys on and a five-second
busy timeout. The existing five-connection evidence constructor is unchanged.
Statement logging is disabled at the shared boundary.

The disk-full and migration-tamper fixtures use a separate dev-only
codex-state-test-support crate. It has only log/sqlx dependencies and compiles
only its own lib.rs; it neither depends on nor recompiles codex-state. Its Bazel
library is testonly=true, rather than enabling a feature globally on production
state. The storage-fault constructor clones the actual owner's options, rejects
other connection-count profiles and caps all new connections. Existing-history
inspection uses one connection and never creates a missing database.

No SQLx lint was relaxed at an owner. The test helper is itself the isolated
central test connection shim. Integration fixture helpers propagate setup errors
instead of suppressing expect-used lint. The outbox conditional simplification
preserves its mutation condition and transaction boundary.

## Validation

- Full operations library: 42 passed, zero skipped.
- Destination recovery integration: six passed, one helper entry skipped by
  nextest. The two parent crash tests invoke that ignored child entry in real
  subprocesses and check pre/post-commit recovery without repeating the effect.
- Selected operations/test-support all-target strict Clippy: passed.
- Central state library strict Clippy: passed. Scoped just fix also passed.
- Actual constructor regressions check each of four retained connections for
  WAL/FULL/foreign-key/busy settings and reject a fifth checkout. Existing
  disk-full transaction-atomicity and migration-lineage tests still pass.
- Cargo metadata traversal excludes the helper from all normal/build dependency
  paths rooted at state, operations and the native worker. Structural preflight
  reports 194 manifests and zero errors.
- Bazel lock refresh passed. Direct target query confirms testonly=true and only
  log/sqlx dependencies. A broader transitive graph query unexpectedly fetched
  uncached dependencies and exhausted disk; it failed and is not qualification.
  Newly fetched disposable cache entries were removed; all source/logs remain.
  No Bazel test execution or transitive Bazel graph acceptance is claimed.

## Ownership synchronizer

The inherited recursive marker transformer could reintroduce duplicate exclusive
worker ownership. It now handles only explicit known registry rows: worker
remains exclusively owned by inference.worker, while inference.control may
retain caller/evidence references. Third-owner source claims, duplicate owners
or roots, invalid binding modes, malformed rows, unknown schemas and conflicting
Cargo owners fail closed. The four canonical registry checks and seven focused
transformer tests pass. The final hosted-equivalent Python selection passes 737
tests. This repair does not overwrite unrelated module provenance or promote
product/qualification/acceptance gates.

The typed Agentd/inference bridge, atomic ingress generation fence, real Windows
retained store, unrelated source ancestry and complete product acceptance remain
separate open work. No merge, deployment or release is requested.

Independent final review found no concrete source blocker in the policy-preserving
shim or isolated helper structure and reran all seven ownership-transformer
tests successfully. That review did not independently execute Rust or Bazel tests.
Full repository formatting completed; unrelated inherited formatter churn was
restored without altering this stage's owned changes.
