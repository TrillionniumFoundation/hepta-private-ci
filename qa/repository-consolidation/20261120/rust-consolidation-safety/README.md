# Rust consolidation protection and Bazel library roots

Base: `0cee57ca617e0324e2df8e9447a2c075a6c76952`.
This candidate contributes two focused repairs to PR #6293.

## Branch protection

The previous default retirement policy omitted 80 ordinary-named branches that the published HIA protection audit already retained. The concrete branch `audit/toolchain-recovery-20261103` descends from historical HIA pin `c4a1bbed3a39beba43a6abf1a18b6f75c5725c21`, while diverging from all three roots used by the previous classifier.

The updated policy retains all 483 observed protected names and 504 historical/current pins. The classifier propagates protection through a complete Git parent graph, rejects incomplete or altered history, and carries forward observed names and prior SHA values. A retained plan directory has one application attempt; its exclusive journal records the latest observed policy before any deletion request. Existing main ancestry, backup, lease, atomic-push and readback checks remain.

The original 18 regression tests passed. Four new semantic regressions fail against the original implementation. All 31 candidate tests pass normally and with Python optimization enabled. The original logs are retained beside `verification.json`. These tests use temporary local Git repositories.

## Cargo and Bazel entry points

A census of 194 workspace manifests found three crates whose Cargo library root is `src/root.rs` while the Bazel macro inferred `src/lib.rs`: extension-api, hepta-context-compiler and hepta-prompt. The explicit wrapper root exports modules needed by their consumers. The macro now accepts an optional root at the end of its existing parameter list and forwards it to both product and test-library rules. The three BUILD files select their existing Cargo root. Existing callers retain default inference.

No Rust source, Cargo dependency or lock file changes are included.

## Validation still required

Native Bazel validation and final `just fmt` are pending. The original baseline-query dispatch returned a runtime connector timeout, so its result remains unknown and the original request is being reconciled. No duplicate query or successful build is claimed. The full live-ancestor recomputation also awaits its original read-only preflight.

This candidate does not qualify the complete source union or close the required checks of PR #6293. Main remains governed by `CI required` and `Architecture required`. No real branch deletion, HIA ref update or main update was performed by this review.
