# Fresh cloud build dependencies: two original failed attempts

Both attempts used the unchanged clean source
`2420fb01d7d26d7c851f48dd24ad2f9385272259`, tree
`24c507b1536b4dd7d92a87525f1adf13fa455b54`, on cloud executor
`74d784910ce8` as UID 1000. Remote commit
`d8b03c34ecdf324e5f0ff5345789e510571763c1` has the same tree.

Each attempted to build the actual same-source
`codex-hepta-infer-worker-host` helper before running the complete Agentd,
Agent Protocol and Learning Ledger library tests. Both stopped at that
prerequisite. **Zero native tests ran; there is no JUnit or UID0 result.**

| Attempt | Actual observed failure |
| --- | --- |
| `integration-2420fb01-cloud` | Helper build ran 54.20 seconds. `aws-lc-sys` reported `Missing dependency: cmake`; Cargo failed and the helper collector returned 1. |
| `integration-2420fb01-cloud-cmake2` | After installing verified official CMake 4.4.5 in the task directory, the same source failed after 3.79 seconds in bindgen: the existing Debian libclang 19.1.7 could not find `stddef.h`. |

These are observed development-environment prerequisite failures, not
application assertion failures or passed test runs. No source, business
assertion, timeout or guard was changed between them.

The official CMake release archive and checksum file were both checked
against the release metadata digests. Installation was local to this task.
For the next separately recorded attempt, `gcc -print-file-name=include`
identified the existing GCC 14 include directory. The actual `stddef.h`
and `stdarg.h` were read and hashed, and that directory was supplied to
bindgen as an ordinary `-isystem` include. No bindgen validation or build
script was disabled. This setup record does not claim the following build
or tests succeeded.

`original-records.tar.gz` retains every regular record produced by both
failed attempts, including full Cargo JSONL, stderr, helper manifests and
environment receipts, commands, final driver records and exceptions. It
also retains both exact orchestration scripts and the CMake/header setup
metadata. `inventory.json` binds each member and the archive to its byte
count and SHA256; all archive members were extracted and compared with the
original bytes before committing this checkpoint.

The separate nine-case Neuron component result uses a different source
snapshot and does not qualify these three libraries. Complete ordinary
positive, NoUpdate and daemon-plus-Root cold-restart counts remain
**0 / 0 / 0**.
