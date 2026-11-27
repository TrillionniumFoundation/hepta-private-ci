# Matrix store cipher code generation candidate

The complete original Windows shard 2 log remains in
qualification/common-current-ci-d0f3-20261127/original-windows-shard-2-failure-job.log.gz.
Both original storage upgrade cases reached the original five-second startup
deadline while all four cipher workers were already running. No worker had returned.

This candidate optimizes only the fixed matrix-sdk-store-encryption dependency,
which instantiates PBKDF2-HMAC-SHA256. Cargo dev/test profiles and the Bazel crate
annotation agree on opt-level 3. No dependency version, source code, key-derivation
round count, original fixture, password check, original test, or deadline changes.

The original just fmt, just bazel-lock-update, and just bazel-lock-check
finished successfully. Both dependency lockfiles remain byte-identical.
These results do not establish that the original Windows failure is fixed.
The branch-specific workflow runs the complete original SDK unit and storage
upgrade targets, with real uncached test execution and no retry/FLAKY acceptance.
The original full-package Mac just test -p codex-hepta-matrix-sdk is separately
running with two build jobs and an owned target directory. Its result and the
Windows result will be retained after natural completion.

This is a code-generation candidate, not a complete matrix qualification.
