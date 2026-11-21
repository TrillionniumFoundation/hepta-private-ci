# 最终只读 CI 归档快照

采集时间：**2026-11-21 16:37:13 UTC**。固定研究源码 `a0b38d3d12c45a4fd254ca27fe1d4266b4c75c53`；prospective merge `b38c3cb721d930fd153839bfe6d43cf9fe575173`；两者 tree `e1952190914918e84449df90b110dba305cb05f8` 相同。

本次只读采集状态，不再等待长任务终态，不分析新增失败根因，不 dispatch/重跑/取消，也不改冻结源码。

**Blocking run 44922509419 仍 in_progress：45 jobs，26 success、8 failure、6 scope skip、5 in_progress。全仓 CI 未闭合。** 8 个失败 job 含两项依赖汇总，不代表8个独立根因。

与16:33:35快照相比：GNU whole job136902076692已SUCCESS；learning.operator deterministic merge136902075763、Windows shard2/4（136902076243、136902076555）及两项依赖汇总现已FAILURE。Windows Clippy136902078343仍在保存cache，但其Clippy步骤已FAILURE；不可继续称该步骤尚无失败。新增失败原因此轮未深挖，也未从旧source推定。

此前47/47数学fixtures、两feature各8/8 HCSN测试、TaskFlow两target各18/18等成功原件不变；它们不覆盖整仓失败。

## Workflow

| Run | Workflow | Status | Conclusion |
|---:|---|---|---|
| 44922509337 | HCSN source mathematical fixtures | completed | success |
| 44922509392 | Hepta MEM full trajectory native campaign | completed | success |
| 44922509328 | v8-canary | completed | success |
| 44922509289 | Hepta VERIFY-1 engineering validation | completed | success |
| 44922509303 | Hepta architecture convergence | in_progress | pending |
| 44922509327 | Learning artifacts qualification | in_progress | pending |
| 44922509419 | blocking-ci | in_progress | pending |

## Blocking jobs

| Job | Name | Status | Conclusion / 已观察失败步骤 |
|---:|---|---|---|
| 136901399167 | Select blocking CI scope | completed | success |
| 136901399432 | Current TaskFlow v1 migration source-head replay | completed | success |
| 136901399486 | Current TaskFlow v1 migration prospective-merge replay | completed | success |
| 136901399543 | Codespell / Check for spelling errors | completed | success |
| 136901399590 | Blob size policy / Blob size policy | completed | success |
| 136901400425 | LedgerWriter Bazel ${{ matrix.lane }} replay | completed | skipped |
| 136901400545 | Historical TaskFlow v1 migration ${{ matrix.lane }} replay | completed | skipped |
| 136902074996 | rust-ci / Detect changed areas | completed | success |
| 136902075047 | cargo-deny / cargo-deny | completed | success |
| 136902075109 | Hepta contract gate / Validate canonical branch and contract metadata | completed | success |
| 136902075118 | sdk / sdks | completed | success |
| 136902075153 | repo-checks / build-test | in_progress | pending |
| 136902075175 | sdk / python-sdk | completed | success |
| 136902075201 | repo-checks / Native Hepta paths on ubuntu-24.04 | completed | success |
| 136902075209 | repo-checks / Native Hepta paths on macos-15 | completed | success |
| 136902075239 | repo-checks / Native Hepta paths on windows-latest | completed | success |
| 136902075763 | learning.operator qualification / learning.operator deterministic merge | completed | failure；Compile and test deterministic merge candidate |
| 136902076024 | learning.operator qualification / learning.operator exact source | completed | failure；Exact-source compile, final-use, shadow, revocation and rollback tests |
| 136902076111 | NDU v6 neural rollout smoke / Python, native NDU, and real rollout | in_progress | pending |
| 136902076162 | NDU v6 neural rollout smoke / Unified profile and executed-policy regressions / Objective, continuation, and selected-policy invariants | completed | success |
| 136902076243 | Bazel / Bazel test on windows-latest for x86_64-pc-windows-msvc shard 2/4 | completed | failure；bazel test shard |
| 136902076541 | Bazel / Bazel test on windows-latest for x86_64-pc-windows-msvc shard 1/4 | completed | failure；bazel test shard |
| 136902076546 | Bazel / Bazel test on macos-15-intel for x86_64-apple-darwin | in_progress | pending |
| 136902076555 | Bazel / Bazel test on windows-latest for x86_64-pc-windows-msvc shard 4/4 | completed | failure；bazel test shard |
| 136902076591 | Bazel / Bazel test on windows-latest for x86_64-pc-windows-msvc (native main) | completed | skipped |
| 136902076692 | Bazel / Bazel test on ubuntu-24.04 for x86_64-unknown-linux-gnu | completed | success |
| 136902076697 | Hepta scoped native checks / shard ${{ matrix.shard }} | completed | skipped |
| 136902076765 | Bazel / Bazel test on ubuntu-24.04 for x86_64-unknown-linux-musl | completed | failure；bazel test //... |
| 136902076774 | Bazel / Bazel test on macos-15 for aarch64-apple-darwin | in_progress | pending |
| 136902076782 | Bazel / Bazel clippy on ubuntu-24.04 for x86_64-unknown-linux-gnu | completed | success |
| 136902076895 | Bazel / Bazel test on windows-latest for x86_64-pc-windows-msvc shard 3/4 | completed | success |
| 136902076907 | Lightweight prose and derived checks | completed | skipped |
| 136902078090 | Bazel / Bazel clippy on macos-15 for aarch64-apple-darwin | completed | success |
| 136902078320 | Bazel / Verify release build on ubuntu-24.04 for x86_64-unknown-linux-gnu | completed | success |
| 136902078343 | Bazel / Bazel clippy on windows-latest for x86_64-pc-windows-msvc | in_progress | pending；bazel build --config=clippy lint targets |
| 136902078384 | Bazel / Verify release build on macos-15 for aarch64-apple-darwin | completed | success |
| 136902078474 | Bazel / Verify release build on windows-latest for x86_64-pc-windows-msvc | completed | success |
| 136902502475 | rust-ci / Rust format | completed | success |
| 136902502490 | rust-ci / Cargo manifest preflight | completed | success |
| 136902502500 | rust-ci / cargo shear | completed | success |
| 136902504223 | rust-ci / Argument comment lint package | completed | skipped |
| 136902850643 | rust-ci / Rust benchmark smoke | completed | success |
| 136903647842 | rust-ci / CI results (required) | completed | success |
| 136909875327 | learning.operator qualification / learning.operator qualification required | completed | failure；Reject failed, cancelled or skipped qualification lanes |
| 136910415677 | Bazel / Bazel test on windows-latest for x86_64-pc-windows-msvc | completed | failure；Confirm Windows Bazel test shards passed |

## Learning artifacts

| Job | Name | Status | Conclusion |
|---:|---|---|---|
| 136901518426 | learning.artifacts (source) | in_progress | pending |
| 136901518645 | source-inventory | completed | success |
| 136901518741 | learning.artifacts (merge) | in_progress | pending |

原始API响应保存在同名JSON。此快照不改变N256 RED/未合格、C2原始训练链未闭合与E HOLD、HPCA HOLD/NoUpdate。既有原日志保留在同目录；未将pending猜测为成功或失败。

