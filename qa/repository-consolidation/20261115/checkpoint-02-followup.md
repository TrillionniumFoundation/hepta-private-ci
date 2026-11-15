# Second publication follow-up

This checkpoint remains partial. The frozen branch inventory is for review; it is not authorization to delete stale branch tips. HIA exclusions and required checks are unchanged.

## Reviewed changes added after checkpoint-02

- Preserve all parent histories from sixteen reviewed small legacy merges. Each incoming source or workflow was inspected; detailed limits and checks are in `legacy-small/`.
- Correct Windows fixtures that explicitly expect legacy/disabled refusal to select that same sandbox route. Retain all assertions and the elevated delete-permission matrix. A narrowly reviewed elevated-token candidate now removes ambient Logon/Everyone alternatives while preserving the dedicated user, selected capabilities, network marker and all original delete-matrix assertions. This candidate still requires the actual Windows matrix; the deletion boundary and two communication-log failures are not reported as fixed.
- The original three evidence archives pass the unmodified blob-policy CLI after lossless partitioning (record held by the inventory audit worker).
- A dependency-equipped native host ran the legacy Python source archive: 655 tests, 651 passed, 4 explicitly skipped for absent native binaries. See `legacy-python-native-environment.json` for exact source and log hashes, package versions, skip names, and scope. No full-repository test pass is claimed.
- Root native source v1 passed the repository formatter with an empty diff. The helper-build job then exited 1 before the planned neuron suite; the helper manifest is incomplete and is not a successful native receipt.

## Still outstanding

Remaining Rust histories and conflicts, the Learning and HCSN production changes, full-workspace Cargo/Bazel lock validation, affected native suites, real encoder range failure, Windows deletion isolation, and the protected CI/Architecture gates still require completion. Main and all excluded HIA refs remain unchanged; no branch was deleted in this pass.
