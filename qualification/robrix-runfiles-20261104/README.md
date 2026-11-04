# Robrix original corpus runfiles on the maintained CLI union

The original two-case integration target reads the complete tracked Robrix v2 artifact directory. Its compile-time `CARGO_MANIFEST_DIR` resolves to a remote build path in Bazel, so both original cases fail before their existing corpus and byte-for-byte writer assertions can run. The adjacent gzip preserves a contiguous original negative target output, and `evidence.json` binds it to the full decoded job digest and exact target source files.

This candidate has parent `9b3521c42d4a81dd814a364d02e77d89be2e0a7d` (CLI #4741 on the maintained dependency union). It copies only the three existing source repairs from #4718: declare the whole fixture directory as Bazel test data, depend on the workspace runfiles utility, and resolve the tracked manifest through `find_resource!` before reading its parent directory. The complete fixture set and all original assertions are unchanged. Cargo.lock retains the current union and adds one existing workspace dependency edge.

## Original acceptance

The three native jobs run the existing unsharded `hepta-supervisor-robrix_control_projection-test` target with the original authenticated Bazel wrapper and fresh test execution. Each must execute both original named cases exactly once: 2 passed, 0 failed, 0 ignored, 0 measured, 0 filtered. The same existing plain test target must also pass original Clippy. No nonexistent `-bin` helper is substituted.

The lock job first checks the committed MODULE lock, then runs the actual repository `just bazel-lock-update`, then the original post-check. An initial failure is retained and keeps the job failed even if generation succeeds; generation continues only to obtain the real follow-up bytes. A changed generated lock is retained in the artifact and framed in bounded base64 log chunks for readback. All three commands and equality to the committed lock must pass on the final candidate. The entry lock must equal `git show HEAD:MODULE.bazel.lock`, and both initial and final `git diff --exit-code HEAD --` checks must pass; an already modified checkout cannot qualify.

The formatter job runs the original repository formatter against the exact parent and rejects a source diff. Every native attempt retains the complete stdout/stderr, native log/XML, source hashes before and after, and receipt. Qualification remains pending until actual hosted results and immutable source bytes are checked.

## Current boundary

No local execution environment is available, so no local Rust, Python, formatter, Clippy, or lock-generator success is claimed. Prior #4718 local results do not transfer to this candidate. The original 30-minute native and generator budgets are unchanged. This isolated Draft does not merge main, deploy, activate a product, clear other blockers, or authorize deleting Library originals.

Posture: **Draft / HOLD_NO_GO / DENY_ALL**.
