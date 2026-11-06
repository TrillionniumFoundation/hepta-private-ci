# Linux arg0 normal-main 夹具的两入口构建候选

## 当前状态

这是基于实际 `ac18b623c7a6cb953b4660979e9b620fe7176bb2` / 树 `c3e9ddc1799f470ac7c80e117ee953a7232847e0` 的三路径候选。三个源文件已实际写成 Git 不可变对象并完整 GET 逐字比较；实际候选树是 `66552bda88637403f4f1d72a5be8592e07a8a308`。没有创建提交、移动 ref、修改 PR、启动 CI 或执行 Cargo/Rust/nextest。原生验收仍待正常 PR 的适用检查；本包不关闭任何 blocker。

| 路径 | 原 blob | 候选实际 blob | 字节 |
| --- | --- | --- | ---: |
| `.github/workflows/rust-ci-full-nextest-platform.yml` | `0ea9d5dcd5ffd622c2d25f3d808ab5738142a851` | `ac975501df7c4515142d03621ba1dcf761ac9a90` | 18,226 |
| `scripts/hepta_ci_dependencies.py` | `2403d7a16f14e919952db597dad3ffdc0825cc31` | `bdd45c82c259238cdecf26c7bfa7acdbb9dfe9f2` | 30,388 |
| `scripts/tests/test_hepta_ci_dependencies.py` | `8e547a867e7c31d694b90f759be60af5c92da2a4` | `f2b2e2c35f4713e63ddd9a0bff83f3ef797a3ea0` | 23,658 |

完整 10,802 叶的 Git 索引正反补丁核验与独立 Merkle 计算相等；另 10,799 叶及全部既有模式保持。`candidate-postimages.actual.json` 保留实际 create、三个源 GET 与完整根树 GET，未用计算哈希冒充已注册对象。

## 已观察到的缺口与源适用性

旧 holdout 作业 `42176273058 / 127755476318` 在实际源 `4a1410f332e4a34564feafbc4dcb2e808c7f6c5f`、树 `605720504e547296dca1c78914fee5ed6d29844d` 上运行。原 nextest 汇总为 17,800 executed：17,796 passed（其中 2 flaky）、3 failed、1 timed out，另外 49 skipped。计划选择 127 包，20 个 changed_packages 包含保守 opaque 消费者；这不是 holdout 单包结果。

三个 arg0 preflight 例的首次和重试均在 `cargo_bin("test_arg0_preflight")` 解析处失败：运行环境没有对应 `CARGO_BIN_EXE`，Cargo fallback 的 `target/debug/test_arg0_preflight` 也不存在。它们尚未执行正常 main 或后续行为断言。旧与 ac18 的 Cargo manifest、resolver、依赖执行器和 just/nextest 入口均为相同 blob；arg0 的两处 Clippy donor 不改变 lookup 到 spawn 的前缀，不能修复缺少 normal-main binary 的问题。

`source/codex-rs/arg0/src/lib.rs`（`bf4181d1...`）明确使用 `#[cfg(all(test, target_os = "linux"))]` 引入原三例。该 bin 的 `test=false`、`bench=false` 是正常 main 夹具的既有声明，保持不变。Bazel 原 `unit_test_extra_binaries` 已声明它，本补丁不修改 Bazel 或 resolver。

同一旧作业的六个 fenced_holdout_file 例在 Linux/4a 全部 PASS；Supervisor 的 60 秒 timeout 是另一个尚待定位的故障，不能合并成 arg0 或 holdout 的因果。本包保持这些原始边界。

历史只读适用性报告保持原字节：实际 REVIEW `2672ec5db4d307062ed618b381f0c6b11e782105`、verifier `0d24ec05a326fc9a6f791561a298c37bef9a4358`、完整 stdout `be39a3f98df97b86934e0881170d6d95fd966d29`。旧完整官方日志/ZIP由 Windows owner 的实际 registry `23e67ce20a439e2968eb63ae4e9a74a214ccd081`（37 路径）保留；此候选包引用其身份，不重复这些大原件，也不声称它们是新候选的运行。

## 修复范围

### 1. 依赖计划执行入口

仅当实际 Python host 是 Linux、action 为 test（包括原 `--run` 别名），且原计划的 `packages` 真正包含 `codex-arg0` 时，在原 suite 前执行：

```text
cargo build --locked -p codex-arg0 --bin test_arg0_preflight
```

条件使用原完整计划的 packages，而非 changed_packages；因此覆盖该工具的原 `--full` 和 full fallback。原计划发现、选择算法、所有 `-p`、`--workspace`、`just test --locked` 命令保持。非 test、未选中 arg0、空选择、macOS 和 Windows 不新增此构建。

构建返回非零或 signal 时不执行 suite，保留原非零码及原 `128 - returncode` signal 映射。成功构建后还须通过原 tracked-source diff 检查；dirty 或无法查询 source 都停止 suite。若构建已经失败且 source 也 dirty，保留构建失败码，同时记录 source_unchanged=false。

每次准备阶段向 stdout 追加独立 running 和最终 JSON，明确 kind 为 `arg0_preflight_fixture_build`，记录实际构建命令、tested SHA、cwd、返回码和 source 检查结果。当前 blocking scoped 的外层 `hepta_ci_exec` 会把这两行及构建输出一起保存在原完整日志中；没有新增不在 upload 路径内却声称已上传的文件。

显式 `--record-output` 模式另复用原 `hepta_ci_exec.py`，在解析后的 suite 目标文件名后追加 `.arg0-preflight-build.json`，使用原 exclusive creation 和独立 log。正式 suite 保留原输出路径；准备失败时没有 suite 通过回执。合法 dangling symlink 的目标先 resolve，再用 resolved basename 派生准备文件，避免两个阶段同路径。旧碰撞草稿与独立反例保留，不改写为曾经通过。

现有外层 3,600 秒 deadline仍覆盖整个依赖命令，未增加。显式记录模式沿用原 recorder 的每命令默认限制；没有更改项目测试 timeout/retry。普通不带 recorder 的本地调用仍沿用原调用者的执行边界，没有借此新增平台资格。

### 2. 全量 nextest archive 的 Linux helper 路径

在原 `Build runtime test helpers` 步骤的 Linux 分支中，以原 `CODEX_CI_TARGET` 和 `CODEX_CI_PROFILE` 构建同一 normal binary，再放进现有 helper 目录。原 `*` artifact 上传和既有下载步骤自然携带该文件。Linux shard 把它复制到原 target/profile 目录并恢复 executable bit，传入既有 resolver 支持的 `CARGO_BIN_EXE_test_arg0_preflight`。

只新增三段 Linux helper 内容。Mac/Windows 分支、archive 命令、nextest 全 argv、四个 shard、线程选项、runner、权限、artifact策略、60分钟作业时限、原测试配置均逐字或完整结构保持。构建失败仍由原 `set -euo pipefail` 停止 archive job；shard 原 `needs: archive` 不变。

入口界限：blocking-ci 的 full_repo 当前调用 fast `rust-ci.yml`，该 reusable 并没有全量 Cargo `just test`；repo-checks 的直接 just 仅测试 codex-hepta-paths。另一路 postmerge/opt-in `rust-ci-full` 才进入本次修复的 archive workflow。本次没有把两入口修复说成任意手工 `just test` 调用都会自动准备此 fixture；直接开发调用仍须按原夹具说明先构建 normal binary。

## 已完成的离线验证

- 36 个 Python unit regressions，包括原全部 29 个与新增 7 个行为测试方法。新增方法以子场景覆盖成功、`--run`/`--full`、未选中、非 test、非 Linux、错误码、signal、dirty、source-query error 和独立 record 路径；不编译任何 Rust。
- 11 个原 `hepta_ci_exec` 配合假 Cargo/just 的控制：独立两阶段记录、构建失败、真实假进程 signal、dirty 成功/失败、suite 失败、两个已有回执拒绝覆盖、dangling symlink、原外层 retained stdout 成功/失败链。
- 3 个直接执行候选原 Bash 段的假 Cargo 控制：原 Linux helper 目录传输成功、构建失败阻断、原 suite 非零透传。使用含空格 producer/consumer/target 路径，核原 target/profile/nextest argv 和 helper env。
- 原 source/完整 tree、Python AST/旧函数与旧测试保留、YAML 结构、Bash parse、完整索引正反 apply 均通过。

最终作者 verifier 实际 exit 0、空 stderr，stdout 4,565 B，Git `5c14f2b2dd225a7f73287ef052dff7c03e4c27e4`。36/11/3 是不同离线验证分母，不能合为产品用例数量。真实 Cargo build、nextest、Rust fmt/fix 和平台 native 均未运行；本地缺少 cargo/just，固定 Ruff 的离线 cache 也不可用，保留其原失败结果，不冒称完整 formatter gate 已通过。

## 可移植复验

从候选包恢复本目录后，使用已有 Python 3.11+、PyYAML、Git 和 Bash，选择一个不存在的新输出目录：

```text
python3 verify_candidate.py --source /absolute/restored/candidate-packet --output /absolute/new/replay
```

脚本只在新目录创建合成 Git/Python/Bash 控制环境；Cargo/just 均由固定嵌入的假程序替代。它重算 full.patch/source-map/intended-full-tree，执行有界离线控制，写入原 stdout/stderr及独立回执，并输出可逐字比较的稳定 VERIFICATION JSON。不访问网络，不查询 CI，不调用原生工具链。

历史适用性报告的独立复验需同时恢复上文 registry23e67 的旧终态原件：`verify_applicability.py <恢复的 applicability 根> <恢复的 old-donor-terminal 原件根>`。该历史脚本只读，不执行项目工具链。
