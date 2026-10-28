# Exact Python formatting repair

Original hosted job 122598462803 at f50ea5dd failed its frozen Ruff 0.15.13 formatting check on exactly two existing files. The original failure is retained in the audit logs. This patch applies that same pinned formatter only to those files, and the complete Python AST of both files remains identical when source locations are excluded. No guard logic, test body semantics, authority, parser, dependency or CI threshold was changed.

The exact frozen/offline full check of scripts and .github passed: 188 files already formatted. The first attempted fresh offline cache lacked the locked wheel and exited 1; the existing task cache supplied the unchanged pinned wheel, without network. The preview returned 1 because it reported the two expected formatting diffs; it is not counted as a successful check.

Only Python/static tooling was run. No local Hepta Rust/Cargo/Bazel build or native test was executed. This formatting result does not close cargo-deny, model, paired service, PQ, or WAN gates.
