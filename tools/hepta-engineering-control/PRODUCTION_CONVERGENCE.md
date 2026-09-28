# control.engineering production convergence

The canonical human-readable source status is [`STATUS.json`](STATUS.json). Exact
commit/tree, command, host and artifact facts are emitted by CI through
`control_engineering_v2.status`; they are not written into the tracked source file
because doing so would create a cryptographic self-reference.

Repository qualification requires all of the following for one immutable source:

1. pull-request source-head and deterministic base-merge product receipts;
2. the final protected-`main` exact-SHA product, strong-sandbox and host-profile receipts;
3. signed reports for tests, line/branch coverage, type checking, lint, public API
   compatibility, a real mutation campaign and bounded durability soak;
4. a non-author independent-review acceptance receipt bound to the exact source;
5. real external distributed fencing, immutable audit anchoring, role-separated
   HSM/KMS custody, independent completion and integration-terminal observations;
6. observed target deployment, backup/restore and rollback rehearsal, followed by
   separately signed operator acceptance.

Missing evidence is a blocker, never an implicit pass. The source package and every
status/qualification decision retain zero runtime, merge, deployment, promotion and
release authority.

## Merge strategy

Changes that modify an `exact_blob` implementation map must preserve the reviewed
source observation as commit ancestry. Use a merge commit for the pull request; do
not squash or rebase such a change. A final protected-branch run is still mandatory
because pull-request evidence does not identify the eventual `main` commit.
