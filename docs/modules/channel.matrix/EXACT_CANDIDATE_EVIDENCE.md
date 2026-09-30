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
regular source files and binds exact Git blobs, file hashes, workspace, checkout
commit/tree, runner image, target triple, workflow run and attempt.

For each input, the provenance receipt records the exact absolute and
repo-relative path, successful `git ls-files --error-unmatch` command and exit
status, stdout/stderr digests, byte size, Git blob, SHA-256, first introducing
commit, first observed qualification stage and closed source classification.
Whole-workspace clean-state snapshots and both path/content inventory hashes are
bound before paired acceptance. A paired receipt fails if a transitive owner
root, exact path, source inventory or provenance identity is absent or altered.

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
closure and the focused JUnit artifact. It carries the full provenance receipt
digests plus each lane's complete and content-only source inventory digests.

A single fail-closed readiness manifest then binds:

```text
candidate_key
source_head_sha
source_tree_hash
frozen_source_sha
frozen_source_tree_hash
base_sha
deterministic_merge_sha
deterministic_merge_tree_hash
github_merge_sha
github_merge_tree_hash
workflow_sha
final_merge_sha
final_merge_tree_hash
workflow_run_id
attempt_id
runner_image
target_triple
Cargo.lock_hash
migration_hash
test_set_hash
qualification_profile_hash
production_qualification_profile_hash
process_fault_profile_hash
transport_tcb_hash
implementation_map_hash
module_status_hash
document_sources_hash
review_slices_hash
documentation_hash
artifact_hashes
required_lanes
lane_status
```

The test-set hash covers the scenario registry, nextest policy, native Matrix
tests, Matrix repository regressions, focused/evidence/pairing scripts and the
real Synapse runner. The qualification contract hash covers the production
profile, process-fault profile, Q01-Q29 registry and transport TCB.

`candidate_key` is a domain-separated SHA-256 over the complete closed identity.
It changes for another candidate, base, merge tree, run, attempt, runner, target,
source inventory, machine registry, command/test set or artifact set. Missing or
mixed lane evidence makes the key absent and keeps `repositoryQualified`,
`mergeReady` and `productionQualified` false.

Repository readiness requires source-head, source-head provenance,
deterministic merge, deterministic-merge provenance, GitHub merge-tree match,
paired repository receipt and same-run/same-attempt proof. Protected-main merge
readiness additionally requires the exact real final merge SHA and tree.
Repository CI never sets production qualification true.

## External qualification boundary

Real homeserver execution, encrypted device/session rotation, protected restore,
ENOSPC and corruption drills, sustained capacity/network pressure, target-host
binding and distinct external security/operations signatures remain governed
external gates. The process-fault contract additionally requires exact
Matrixd/Agentd/test binary, configuration, process-identity ledger, runner,
target triple and homeserver image identities for every PF01-PF18 scenario.

These external receipts cannot be synthesized from repository CI. A repository
readiness key is necessary to prevent evidence mixing, but it is not deployment,
activation, promotion, release or Matrix-send authority.
