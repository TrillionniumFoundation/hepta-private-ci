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

## Closed source inventory

The source snapshot covers the Matrix protocol, durable store, SDK, daemon,
Supervisor lifecycle caller, final-use contracts, repository SQLite policy
owners, state owner, module documentation, evidence tooling, workflow bytes,
lockfiles and the real Synapse runner. A paired receipt fails if any of these
transitive owner roots or exact paths is absent.

The canonical target runner is:

```text
codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh
```

`tests/fixtures/run-hermetic-synapse.sh` is a compatibility navigation entry
point that delegates without changing arguments to the canonical runner. The
canonical runner and the real `real_synapse_e2e` test remain the evidence-bound
objects.

## Command receipts

Both source-head and deterministic-merge lanes execute and retain distinct
command receipts for:

1. locked all-target compilation;
2. public API compile-fail doctests;
3. the locked Matrix native test set and nextest JUnit report;
4. strict Clippy;
5. rustfmt.

Each receipt binds exact arguments, working directory, candidate SHA, source
snapshot digest, exit status, bounded log digest and a post-command clean-source
snapshot. The API compile-fail command is not a loose log: it is a required
canonical command receipt in both lanes.

## Paired acceptance

The paired verifier revalidates both artifact manifests, all Q01-Q29 native
scenario rows, the transitive source closure and the API compile-fail receipt.
It then emits one versioned paired receipt. Missing, failed, skipped, stale,
tampered or mixed-candidate evidence fails closed.

Real homeserver execution, encrypted device/session rotation, protected restore,
ENOSPC and corruption drills, sustained capacity/network pressure, target-host
binding and distinct external security/operations signatures remain governed
external gates. They cannot be synthesized from repository CI.
