# Workflow Strategy

The default branch keeps **durable product CI**, not historical one-shot controllers that try to fix, qualify, materialize, or re-qualify other CI runs.

## Pull Requests

`blocking-ci.yml` is the single merge-blocking entrypoint. It aggregates checks that directly evaluate the candidate source:

- Bazel build/test/clippy coverage;
- blob-size policy;
- dependency/license policy (`cargo-deny`);
- spelling and repository checks;
- focused Cargo/Rust checks;
- SDK checks.

Required checks run against GitHub's merge candidate where the reusable workflow supports it. The purpose is source correctness and merge compatibility, not to create a second admission protocol around CI metadata.

A normal PR must **not** be blocked solely because another workflow did not manufacture an exact-head receipt, review index, evidence packet, closure ledger, materializer output, or synthetic-merge attestation. Those objects have no independent authority merely because repository-controlled CI produced them.

## Governance and evidence

Governance/evidence workflows may exist when they validate an actual governance surface or an explicitly requested promotion. They should be manually/scopingly invoked and must not become transitive prerequisites for unrelated source PRs.

Historical PR-specific controllers, rerun/fixer workflows, materializers, and exact-head closure loops must be deleted after their bounded incident/PR is over instead of accumulating on `main`.

## Post-Merge On `main`

- `bazel.yml` re-verifies the merged Bazel path and keeps build caches warm.
- `rust-ci-full.yml` provides heavyweight Cargo-native coverage after merge, including full clippy/nextest matrices, release-profile builds, cross-platform linting and platform-specific tests.

Heavy post-merge verification is allowed to be broader than PR blocking because it does not turn every source change into a qualification campaign.

## Promotion and release

Release, signing, installed-target, device, destructive-recovery, external-evidence and independent-authorization gates remain hard requirements **when a promotion/release path claims those properties**. Moving them out of the ordinary PR gate does not make them optional for release.

## Rule of thumb

1. If a check answers “is this source correct and merge-compatible?”, it belongs in `blocking-ci.yml` or one of its reusable children.
2. If it answers “is this artifact/evidence/release qualified?”, it belongs on a promotion or release path.
3. If it answers “did another CI workflow run and emit the expected receipt?”, it is normally diagnostic and should not be a merge gate.
4. One-shot controller/fixer/materializer workflows should never become permanent default-branch infrastructure.
