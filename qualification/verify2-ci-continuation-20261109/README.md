# VERIFY exact-source platform qualification and CI repair

The five original PR heads remain unchanged. Source `3966ff1a8bc95042e1fe4bdf8d6f11ca4b6cb718`
completed VERIFY engineering run `42744802690` successfully on all three platforms:

| Platform | Original job | Full package tests | Dispatch |
| --- | --- | --- | --- |
| macOS 15 | 129594484681 | 158 passed | 9 scenarios / 17 subprocesses |
| Windows 2025 | 129594485195 | 158 passed | 9 scenarios / 17 subprocesses |
| Ubuntu 24.04 | 129594485282 | 158 passed | 9 scenarios / 17 subprocesses |

These three jobs also passed the original SQLite effect step. They qualify this
engineering source only; they do not establish independent real-task benefit.

Full blocking run `42744803289` failed. Job `129602996156` identified exactly five
Python scripts requiring formatting. This change applies the lockfile's Ruff
0.15.13 to those five files. FORMAT.json records unchanged parsed ASTs including
type comments and exact before/after SHA256 values. The scoped formatter check
passes. No redundant behavior tests or Rust changes were introduced. The sparse
checkout cannot run the complete workspace `just fmt`; remote full CI is required.

The original cargo-deny job `129602996075` remains failed. Its log reader again
returned Transport closed; generic fetch rejected the logs endpoint. Neither
failure establishes an advisory cause, and no policy suppression was added.

The full CI also has Bazel test failures across platforms. In the retrieved Linux
job `129602996544`, eleven operator-acceptance tests report missing OpenSSH
ssh-keygen in the test environment. Other targets also fail; this is not claimed
as their common cause. Required checks remain OPEN. Source-head Architecture is
still running; its base-merge pass is not substituted for source execution.

original-ci-records.zip preserves four complete decoded logs and the original
PR/head, job and error snapshots. MEMBERS.json binds their byte sizes and SHA256.
No historical evidence is rewritten. Final source CI must qualify its own head.
Independent labels on real tasks, complete costs and matched prospective utility
remain HOLD, with production authority NONE.
