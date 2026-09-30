# channel.matrix source purity and candidate freeze

Status: repository-controlled source and evidence contract. This document grants no
deployment, activation, promotion, release, Matrix-send, or external-effect
authority. The executable regressions are
`scripts/tests/test_channel_matrix_closure_workflow.py`,
`scripts/tests/test_channel_matrix_source_provenance.py` and
`scripts/tests/test_channel_matrix_readiness.py`.

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

- GitHub permissions are `contents: read`;
- `actions/checkout` uses `persist-credentials: false`;
- deterministic merge construction may use `git merge-tree` and
  `git commit-tree` only to create an in-run test object;
- receipts and logs are written outside the checkout;
- the tracked tree and the complete workspace status are checked clean before
  and after every source-provenance scan;
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

## 4. Ordinary source and tracked provenance closure

All reviewed implementation, tests, documentation, registries, migrations, and
qualification logic live at their ordinary tracked paths. The repository must
not contain Matrix-specific encoded patch bundles, numbered patch fragments,
temporary staging directories, repair scripts, or preservation patches that can
reconstruct a different source tree during CI.

The default source inventory command is exactly:

```text
git ls-files -z
```

The closure-specific invocation narrows that tracked inventory only by the
closed Matrix pathspec set. Generated directories, caches and downloaded
artifacts are never silently included as source. When a separately governed
execution needs generated output, that output remains in its own artifact
provenance and cannot satisfy tracked-source closure.

For every closure input, `source-provenance.json` binds:

```text
workspace_root
checkout_sha
checkout_tree
absolute_path
repo_relative_path
git_blob
sha256
bytes
git_ls_files_error_unmatch_command
git_ls_files_error_unmatch_exit_status
git_ls_files_stdout_sha256
git_ls_files_stderr_sha256
introduced_at_commit
first_observed_stage
source_class
fixture/workflow/documentation classification
```

The introduction commit is derived from the exact repository history with a
single ordered add-history scan. Both complete workspace `git status
--porcelain=v2 -z --untracked-files=all` snapshots, tracked path inventories,
closure path inventories, complete provenance rows and content-only inventories
are hashed. Paired acceptance and readiness independently revalidate those
hashes instead of trusting a Boolean written by the provenance producer.

The executable guard also checks both the historical forbidden paths and the
complete tracked-file inventory. A newly named patch bundle therefore fails
even when it is not listed in the historical inventory.

## 5. Frozen candidate identity

A candidate freeze records:

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

The source-head commit/tree are immutable. The base and every merge identity are
explicit and cannot be inferred later from a branch name. No green result may be
assembled from another commit, workflow run, attempt, runner context, source
inventory, command policy, profile, documentation set or artifact set.

`candidate_key` is a domain-separated SHA-256 of the complete closed identity
above. It changes when an attempt, artifact, source inventory, profile or merge
identity changes. It is an anti-mixing identity only: it grants no deployment,
activation, promotion, release or Matrix-send authority.

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
slices, and clean-tree checks in one workflow run and attempt. The GitHub
synthetic merge must resolve to the exact deterministic merge tree. Protected
`main` readiness additionally requires the real final merge SHA and tree to be
the exact tested source.

The readiness generator must fail closed for a missing, queued, canceled,
skipped, superseded, partial, flaky, failed, stale, mixed-candidate,
mixed-attempt, duplicate, path-inconsistent or tampered input. If any required
repository lane fails, `candidate_key` is absent and both `repositoryQualified`
and `mergeReady` are false. A workflow definition, local authoring run, status
label, or PR comment is never execution evidence.

Repository CI always keeps `productionQualified = false`. Target qualification
and independent security/operator acceptance are separate required lanes whose
receipts cannot be authored or joined by the repository candidate itself.

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
identity, runner, target triple, homeserver identity and the same candidate key,
all production, independent-acceptance, activation, promotion, and release
claims remain false.

## 9. Reviewer checklist

A reviewer should be able to establish all of the following from ordinary Git
objects and retained receipts:

1. No workflow can reconstruct or push a different Matrix source tree.
2. Every Matrix qualification workflow is read-only regardless of filename.
3. The repository write-capable workflow inventory is closed and Matrix-disjoint.
4. Every scanned source path is tracked, regular, byte-identical to its Git blob,
   bound to its first introducing commit and independently hash-verifiable.
5. The candidate commit/tree, base, deterministic merge, GitHub merge, workflow,
   run, attempt, toolchain, target, source inventories, machine registries and
   artifacts are explicit under one non-mixable candidate key.
6. Both exact lanes ran the same canonical command set and Q01-Q29 ledger.
7. No result was borrowed from a superseded candidate or another attempt.
8. The real merge SHA is scheduled for a fresh post-integration execution.
9. External production and independent-acceptance gates remain false unless
   their protected receipts are present and valid.
