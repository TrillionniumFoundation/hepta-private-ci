# channel.matrix source purity and candidate freeze

Status: repository-controlled source and evidence contract. This document grants no
deployment, activation, promotion, release, Matrix-send, or external-effect
authority. The executable regression is
`scripts/tests/test_channel_matrix_closure_workflow.py`.

## 1. Purpose

`channel.matrix` qualification must test ordinary, reviewable Git source. A
workflow may compile, test, inspect, package evidence, and construct a
deterministic synthetic merge, but it may not decode a hidden patch, edit the
checkout, commit generated source, or push a replacement candidate. Source
authoring happens through normal reviewed commits before qualification begins.

The exact candidate is the immutable commit and tree recorded by the evidence
receipts. The mutable pull-request branch is transport for review, not candidate
identity. An immutable branch alias is navigation only; it is not an additional
source of truth and cannot substitute for the exact commit/tree pair.

## 2. Filename-independent classification

The purity rule is deliberately independent of workflow filenames. Renaming an
apply, repair, materialize, export, bootstrap, or finalizer workflow must not
evade the boundary.

A workflow is treated as Matrix qualification when its filename or content
references the Matrix qualification identity, candidate branch family,
qualification scripts, or exact-candidate verifier. A workflow is treated as
touching Matrix source when its content names Matrix owner roots, the Supervisor
Matrix caller, the module documentation tree, or Matrix qualification scripts.

The executable guard scans every tracked `.github/workflows/*.yml` and
`.github/workflows/*.yaml` file. Matrix qualification workflows must declare
top-level `contents: read`, and any checkout they perform must set
`persist-credentials: false`. Qualification and Matrix-source-touching workflows
are rejected if they contain source-authoring machinery.

The repository also maintains a closed writable-workflow allowlist. Only the
existing CLA, Rust release, and isolated single-main integration workflows may
hold `contents: write`. A new or renamed write-capable workflow fails by default
until an ordinary reviewed commit adds it to that closed inventory. Every
allowlisted workflow remains disjoint from Matrix candidate branches, Matrix
source roots, Matrix qualification scripts, and Matrix staging or patch payloads.

## 3. Read-only qualification invariant

The allowed repository qualification path is read-only:

- GitHub permissions are `contents: read`.
- `actions/checkout` uses `persist-credentials: false`.
- deterministic merge construction may use `git merge-tree` and
  `git commit-tree` only to create an in-run test object;
- receipts and logs are written outside the checkout;
- the tracked tree is checked clean before and after every command;
- source-head and deterministic-merge lanes use the same closed command policy;
- the paired result must come from one workflow run and one attempt.

The following are forbidden in Matrix qualification or any workflow that
directly touches Matrix source:

- `contents: write`;
- `git commit` of ordinary source or `git push`;
- `cargo clippy --fix` or another in-place source repair;
- base64/gzip decoding used to materialize a source patch;
- `.matrix-staging`, repair scripts, split patch parts, or encoded full-patch
  payloads;
- credentials persisted by checkout for a later source write.

`git commit-tree` is not source authoring when it is used solely to materialize
the deterministic merge candidate that is immediately tested and never pushed.

## 4. Ordinary source and tracked payload closure

All reviewed implementation, tests, documentation, registries, migrations, and
qualification logic live at their ordinary tracked paths. The repository must
not contain Matrix-specific encoded patch bundles, numbered patch fragments,
temporary staging directories, repair scripts, or preservation patches that can
reconstruct a different source tree during CI.

The executable guard checks both the historical forbidden paths and the complete
tracked-file inventory. A newly named patch bundle therefore fails even when it
is not listed in the historical inventory.

## 5. Frozen candidate identity

A candidate freeze records:

```text
source_head_sha
source_head_tree
base_sha
deterministic_merge_sha
deterministic_merge_tree
github_merge_sha
workflow_sha
workflow_run_id
attempt_id
runner_image
target_triple
Cargo.lock_hash
migration_hash
test_set_hash
qualification_profile_hash
implementation_map_hash
documentation_hash
source_tree_hash
artifact_hashes
```

The source-head commit/tree are immutable. The base and both merge identities
are explicit and cannot be inferred later from a branch name. No green result
may be assembled from another commit, workflow run, attempt, runner context, or
artifact set.

`IMPLEMENTATION_MAP.json` owns frozen inspected-source mapping and provenance.
The external candidate/readiness receipts own the metadata candidate and
execution identities. `MODULE_STATUS.json` owns current claim state. Generated
Markdown is navigation only.

Any later commit creates a new candidate. Its old receipts become historical and
must not be relabeled. A branch alias is navigation only and does not freeze a
moving pull-request branch.

## 6. Receipt invalidation and readiness

Repository readiness is true only when source-head and deterministic-merge lanes
both complete the canonical locked commands, public API compile-fail proof,
Q01-Q29 JUnit ledger, strict lint, formatting, tracked-source provenance, review
slices, and clean-tree checks in one workflow run and attempt.

The readiness generator must fail closed for a missing, queued, canceled,
skipped, superseded, partial, flaky, failed, stale, mixed-attempt, duplicate, or
tampered input. A workflow definition, local authoring run, status label, or PR
comment is never execution evidence.

## 7. Post-integration rule

Pull-request evidence is not reusable after integration. The actual real merge
SHA must execute the complete repository qualification again against the exact
preceding `main` SHA and retain a new readiness manifest. A GitHub synthetic
merge, deterministic pre-merge object, or PR-head pass cannot stand in for that
real merge SHA.

The post-integration receipt remains a repository qualification result. It does
not itself authorize a canary, deployment, activation, promotion, release, or
external Matrix effect.

## 8. Runtime and production boundary

Repository qualification proves source composition and the declared native
fixtures only. Real encrypted-room/device rotation, protected backup restore,
storage faults, clock discipline, sustained capacity, rate limiting, reconnect,
slow homeserver behavior, long unknown effects, and independent operator and
security acceptance require target-bound, separately governed evidence.

Consequently, production qualification remains external. Until those receipts
exist and verify against the exact target binary, configuration, process
identity, runner, target triple, and homeserver identity, all production,
independent-acceptance, activation, promotion, and release claims remain false.

## 9. Reviewer checklist

A reviewer should be able to establish all of the following from ordinary Git
objects and retained receipts:

1. No workflow can reconstruct or push a different Matrix source tree.
2. Every Matrix qualification workflow is read-only regardless of filename.
3. The repository write-capable workflow inventory is closed and Matrix-disjoint.
4. The candidate commit/tree, base, deterministic merge, GitHub merge, workflow,
   run, attempt, toolchain, target, source inventory, and artifacts are explicit.
5. Both exact lanes ran the same canonical command set and Q01-Q29 ledger.
6. No result was borrowed from a superseded candidate or another attempt.
7. The real merge SHA is scheduled for a fresh post-integration execution.
8. External production and independent-acceptance gates remain false unless
   their protected receipts are present and valid.
