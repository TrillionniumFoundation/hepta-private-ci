# Integrated v7 independent review

Decision: **ready to commit the frozen integrated-mode changes, with the existing CI gates still required**. No blocking defect was found in this scoped review.

The review bound all 13 tooling files to `INTEGRATED_MODE_PUBLISH_MANIFEST.json` (SHA256 `aeb8a6054b19de07d9cbc16a63b522ccea9d837cab4c66f3846c17b1c77e6bec`). All 35 real payload files match the proposed integration manifest bytes and Git executable modes; all three original policy files and the recipe match their frozen hashes. The shared HEAD still precedes integration, so the payload, manifest and tooling must be committed together before an integrated result can be generated.

## Binding and qualification checks

The integrated guard compares actual payload and manifest bytes with `git ls-tree HEAD` blob identities, checks executable modes, rejects any cached-index delta, and binds the complete `HEAD^{tree}`. A transport receipt must contain an exactly empty `candidate.patch`, no changed paths, and the exact committed integration manifest. A declared integrated result cannot silently fall back to historical patch behavior.

The historical patched path still executes Git patch checks and application. The same-run and same-attempt producer hash, source identity, original dependency policies, vendor inventories and dependency graph constraints remain in place. Synapse preserves its independent tree replay, exact helper import, extra-input guards and separate native qualification. Post-qualification still separates unchanged-source Clippy results from fixes that require fresh behavioral qualification.

The production generation path calls the pinned toolchain check, Cargo metadata with `--locked`, and `just bazel-lock-update` plus `just bazel-lock-check`; it rejects graph, lock, source or index drift before marking the candidate generated. These real external resolver calls were inspected, not executed in this review.

## Evidence

The three existing behavior logs were read and matched to their recorded SHA256 values: 47 port cases, 15 post-qualification cases and 19 Linux source/qualification cases. Those are controlled behavior tests recorded before scoped formatting; they are not Rust or Bazel qualification.

Seven additional probes ran against the final frozen code in tiny disposable real Git repositories:

1. Exact committed integrated source restores without applying a patch or changing the tree.
2. An index-only executable-mode change on a policy file outside the payload is rejected.
3. A worktree restored to approved bytes cannot hide a different committed payload blob.
4. A worktree restored to approved bytes cannot hide a different committed manifest blob.
5. A resealed new HEAD cannot reuse an old complete source-tree identity.
6. The legacy generator actually rejects the already applied historical patch with Git exit 1, before compiler dispatch.
7. A different workflow run ID cannot consume the integrated artifact.

All seven passed. The 13 frozen source hashes were unchanged before and after execution. The structured report retains actual rejection reasons, Git commands, log identities and scope. The reviewed production Git index, refs and the frozen ten-file Windows crate changes were not modified.

## Limits

This review supports submission of the source-mode tooling. It does not establish a fresh compiler, policy scan, full-workspace, Windows or native ARM64 Synapse pass. Historical artifact provenance is not fresh qualification, and no NDU capability-gain conclusion follows from these CI guards. Actual zero-drift resolver execution and all consumer/native gates remain required on the final committed source.

The earlier exec-server review and the 16 original-video hash metadata have also been copied into this directory with their original bytes and SHA256 values preserved.
