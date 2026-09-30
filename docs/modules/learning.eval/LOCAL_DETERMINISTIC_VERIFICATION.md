# learning.eval local deterministic verification

This document defines the repository-controlled, offline verification path for the
`learning.eval` control plane. It does not authenticate a target host, validate a
real provider or publication owner, establish future-calendar observations, issue
independent acceptance, or authorize activation, promotion, or release.

## Canonical command

Run from a clean checkout at the exact candidate commit:

```bash
commit="$(git rev-parse HEAD)"
python3 scripts/hepta-learning-eval-local-verify.py \
  --source-commit "$commit" \
  --output ".hepta-evidence/learning-eval/local-deterministic-$commit"
```

The output directory must not already exist. Tracked source must remain clean for
the entire run. Python bytecode and generated fixture evidence are redirected
under the output directory rather than written into the source tree.

## Deterministic scope

The local verifier executes and records:

1. Python syntax compilation for all `learning.eval` evidence, reporting, status,
   documentation, discovery, and regression scripts.
2. Exact-recorder, nextest-discovery, exact-entry, compatibility-fixture,
   evidence-summary, documentation-contract, trusted-reporter, and local-verifier
   regression suites.
3. Generated source-status verification.
4. The fail-closed documentation/source contract.
5. Compatibility-fixture inventory checks without enabling product authority.
6. The target-host verifier self-test, which validates only verifier behavior and
   does not qualify an actual host.

The trusted-reporter aggregate suite contains 60 deterministic regressions: the original 15 producer/run,
workflow-identity, Git-object, exact-matrix, stale-head, symlink, and marker
tests plus 43 hardened entrypoint and local-evidence regressions for:

- duplicate JSON keys at any object depth;
- non-finite JSON constants;
- a strict allowlist for source/exact artifact files, source-status companion
  consistency, extra payloads, symlinked directories, excessive depth, and
  excessive entry count;
- normalization of GitHub terminal conclusions to the four-state
  `needs.<job>.result` vocabulary;
- duplicate, incomplete, wrong-attempt, and unknown producer job inventories;
- duplicate, half, reversed, and mixed legacy/current PR markers;
- exact preservation of text outside the machine-owned marker;
- Draft/NO_GO preservation;
- base-repository substitution;
- base or synthetic-merge changes between producer validation and final PATCH;
- complete producer job inventory, including the skipped attestation job;
- byte identity for the qualification control plane (test discovery, exact
  recorder/entry, API-surface, fault, compatibility, status/documentation,
  Cargo/nextest configuration, and their regression harnesses);
- revalidation of the GitHub PATCH response.

## Evidence contract

`local-deterministic-summary.json` uses schema
`hepta.learning-eval.local-deterministic.v1`. It binds the exact commit and tree,
all command lines, terminal status, exit code, log byte count and SHA-256, and a
canonical summary SHA-256.

A successful run may set only:

```text
localDeterministicVerifiedByThisRun = true
```

It always retains:

```text
authority = DENY_ALL
releasePosture = NO_GO
exactHeadExecuted = false
orderedParentSyntheticMergeExecuted = false
targetHostQualified = false
independentAcceptanceIssued = false
activationAuthorized = false
releaseAuthorized = false
```

Exact-head, ordered-parent synthetic-merge, Rust compilation, process-fault,
coverage, selected-host, statistical, operator, activation, and release facts
remain separate evidence domains.

## Trusted reporter boundary

The default-branch `workflow_run` reporter invokes
`scripts/hepta-learning-eval-trusted-entry.py`. Before any PR body update, that
entrypoint requires:

- an exact bounded allowlist of regular JSON artifact files: source evidence
  carries `qualification-summary.json` plus its consistent
  `CURRENT_STATUS.run.json` projection, while exact evidence carries only
  `exact-summary.json`;
- strict JSON parsing with duplicate-key and non-finite-value rejection;
- producer run, complete latest-attempt job inventory, workflow byte identity,
  qualification-control-plane byte identity, commit/tree, current PR head/base,
  and synthetic-merge reconciliation;
- one well-formed marker of each kind at most, with duplicate/half/mixed markers
  rejected before any replacement;
- a second current-PR scope check immediately before PATCH;
- an open Draft PR owned by the same repository;
- exact validation of the PATCH response.

The reporter remains unable to mint target-host, acceptance, activation,
promotion, or release authority.
