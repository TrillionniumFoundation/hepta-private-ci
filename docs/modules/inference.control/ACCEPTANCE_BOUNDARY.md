# inference.control artifact acceptance boundary

## Source and execution are separate trust domains

The existing `hepta-inference-readonly-matrix.yml` executes the candidate on disposable runners. Its source-head and base-merge lanes retain source archives, command records, logs and toolchain metadata. It is not the independent acceptance authority.

`hepta-inference-independent-acceptance.yml` is now an artifact consumer. It has read-only GitHub permissions and no candidate checkout, Cargo invocation, shared cache or repository write. It resolves the current PR source, current main, the GitHub merge tree, and a completed successful run of the exact read-only matrix. Queued, skipped, failed, stale-source and ambiguous artifacts are rejected.

The verifier is downloaded only from the frozen trusted main commit. It is run with Python isolated mode and without the GitHub token. Candidate archives are parsed as data: no archive path is extracted, imported or executed. A missing trusted verifier is a blocker; there is no candidate-code fallback. Initial installation therefore requires separate review on the trusted base. This candidate cannot certify its own verifier by first executing it.

## What the verifier checks

The ZIP digest must match the GitHub artifact API observation. File and entry limits, duplicate names, unsafe paths, encrypted ZIP entries, symlinks in the outer ZIP, unsupported tar nodes and duplicate JSON keys fail closed. The Git tree is recomputed from archived file bytes, executable modes and symlink targets, without materializing those targets. The source archive's commit comment must match the tested commit.

Every one of the eleven required command records must be present. Commands must match the reviewed argument vectors, not an echo or comment. Source, base, tested commit, tree, lane, run and attempt identities must agree. Exit codes must be integer zero, statuses must be passed, test commands must record a positive test count, and timeout/output-limit flags must be false. Before/after snapshots must be clean and identical, and synthetic-merge parents must be ordered base then source. Log sizes and SHA-256 values are recomputed.

The synthetic merge identity is independently derived from the GitHub merge tree, ordered parents, fixed author/committer identity and timestamp, and the existing matrix's exact message. This derivation is tested against Git; a different merge or source archive is not accepted by relabeling it.

## What this does not prove

Artifact integrity is not independent execution proof. A candidate test sharing the command recorder's operating-system identity can fabricate its own records. Artifact hashing authenticates bytes, not honest execution. A separately controlled recorder/output channel, independently reviewed execution policy and owner acceptance are still required. Accordingly reports retain `independentExecutionProved`, `independentAcceptance`, `activation` and `release` as false.

The parser's thirteen adversarial tests use explicitly synthetic fixtures. They also compare a real temporary Git archive against Git's tree identity, including executable files and symlinks. These are parser and integrity tests, not real provider, GPU, HIL, durable-lifecycle soak or vault-deletion evidence.

## Operator sequence

Review and install the trusted verifier on main without importing candidate code. Finish the exact source/current-main read-only matrix. Then re-run the artifact consumer for that source and immutable execution run; manual dispatch is permitted only from main. Preserve both lanes' integrity reports and GitHub API observations. Do not update production status, close review findings, remove Draft, merge or activate merely because artifact parsing passed.
