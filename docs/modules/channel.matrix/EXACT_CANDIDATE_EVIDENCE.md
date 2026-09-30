# channel.matrix exact-candidate evidence closure

Status: repository-controlled evidence contract. This document grants no target
qualification, independent acceptance, activation, promotion or release.

## One immutable candidate

The authoritative local qualification is the pull-request head SHA, followed by
one deterministic merge commit whose parents are the recorded base SHA and that
same source SHA. After integration, the read-only workflow runs again on the
real `main` merge SHA. PR-head evidence is never reused as merged-source proof.

The workflow uses `contents: read`, checks out the exact SHA without persistent
credentials, and writes every receipt outside the checkout. No qualification
job edits, commits or pushes source.

## Closed source and execution inventory

The source snapshot covers the Matrix protocol, durable store, SDK, daemon,
Supervisor lifecycle caller, final-use contracts, repository SQLite policy
owners, state owner, module documentation, evidence tooling, workflow bytes,
lockfiles and the real Synapse runner. Per-lane provenance accepts only tracked
regular source files and binds exact Git blobs, file hashes, workspace, runner
image, target triple, workflow run and attempt. A paired receipt fails if a
transitive owner root, exact path or provenance identity is absent.

Inventory alone is not execution. The exact command policy directly includes:

```text
codex-hepta-contracts
codex-state
codex-hepta-operations
codex-hepta-matrix-protocol
codex-hepta-matrix-store
codex-hepta-matrix-sdk
codex-hepta-matrixd
```

The canonical target runner is:

```text
codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh
```

`tests/fixtures/run-hermetic-synapse.sh` is a compatibility navigation entry
point that delegates without changing arguments to the canonical runner. The
canonical runner and the real `real_synapse_e2e` test remain evidence-bound
objects.

## Command receipts

Both source-head and deterministic-merge lanes execute and retain distinct
command receipts for:

1. locked all-target compilation of every candidate-bound Rust owner;
2. public API compile-fail doctests;
3. locked native tests for every candidate-bound Rust owner plus all
   `test_channel_matrix*.py` repository regressions and a nextest JUnit report;
4. strict Clippy for every candidate-bound Rust owner;
5. rustfmt for every candidate-bound Rust owner.

The receipt producer, status renderer, scenario ledger, paired verifier and
readiness derivation import one command policy. Running them in separate
processes cannot silently compare a wrapper receipt against an older argv.

Each receipt binds exact arguments, working directory, candidate SHA, source
snapshot digest, exit status, bounded log digest and a post-command clean-source
snapshot. `source-after.json` must equal `source.json`; the status view exposes a
separate `clean_tree` state; and the paired verifier independently revalidates
`sourceUnchanged` for every command. The API compile-fail command is not a loose
side log.

## Paired acceptance and readiness

The paired verifier requires both lanes to come from the same workflow run and
attempt. It revalidates both artifact manifests, every canonical command receipt,
all Q01-Q29 native scenario rows, tracked-source provenance, transitive source
closure and the focused JUnit artifact.

A single fail-closed readiness manifest then binds the source head, frozen
ordinary source, base, deterministic merge, GitHub synthetic merge, workflow
blob and—after protected integration—the real final merge SHA. It also binds
runner image, target triple, `Cargo.lock`, migration, test-set, qualification
profile, implementation-map, documentation and artifact hashes. Missing or
mixed lane evidence makes `repositoryQualified`, `mergeReady` and
`productionQualified` false.

Real homeserver execution, encrypted device/session rotation, protected restore,
ENOSPC and corruption drills, sustained capacity/network pressure, target-host
binding and distinct external security/operations signatures remain governed
external gates. They cannot be synthesized from repository CI.
