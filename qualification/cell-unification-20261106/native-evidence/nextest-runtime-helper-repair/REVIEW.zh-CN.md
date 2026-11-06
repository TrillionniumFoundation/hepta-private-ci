# Nextest 跨包测试程序的显式供应

## 已证实的问题

Core 原门源码树为 `6d88ca9c8964669a408d8549efaeff7b94d68674`。原失败日志 SHA256 为 `d5838182b45478741d7af4c65dc3ed826b27c0f14d825897c21f0062a292e687`。其中 108 个唯一 FAIL 有明确的 binary metadata 缺失：`test_stdio_server` 97、`codex` 9、`codex-code-mode-host` 2。另外一个 CodeModeOnly 用例记录实际默认 host 路径的 ENOENT。这些是原门的观察，不是候选修复后的通过声明。

97 个 stdio 失败中，89 个直接返回缺失错误，8 个 plugin 用例先输出“skipping test”，随后因为事先挂载的 wiremock 未收到预期请求而 panic。原 `plugins.rs` 先挂载 SSE mock，再查 stdio 程序；`mount_sse_sequence` 明确断言请求数量。因此不能删掉 wiremock 断言或把内部打印当成成功跳过。

`test_stdio_server` 的真实 owner 是 `codex-rmcp-client`，由 `src/bin/test_stdio_server.rs` 自动发现。`codex-core` 对该包的普通 library 依赖不提供其 binary。Nextest 0.9.103 的 `test_list.rs` 按当前测试的 package ID 选择 non-test binaries；`test_command.rs` 只导出这一集合。增加 `-p codex-rmcp-client` 或构建全部 workspace，仍不等于向 Core 提供跨包环境变量。仓库原 `utils/cargo-bin/README.md` 已明确该限制。

本轮 native 元数据来自真实 `cargo metadata --no-deps --locked --offline`，包含 193 个实际 workspace member、31 个有 binary target 的包。完整调用图记录 101 个调用或 Bazel 声明文件的身份。`test_stdio_server` 等隐式 target 也由这份元数据确认，没有依名字猜 owner。

## 候选的边界

候选只修改 `scripts/run-nextest.py`，新增 `scripts/test_run_nextest_helpers.py`。原 `scripts/test_run_nextest.py` 字节保持不变。Rust 生产代码、Cargo binary resolver、plugin 逻辑、现有测试断言及旧的全仓 archive workflow 均未改动。

在原 runner 即将调用 nextest 时，候选为已选中的明确 consumer 包准备其声明过的跨包 binary。Core、app-server、rmcp-client、tui、CLI、exec-server 的映射来自实际调用链和原 Bazel 声明。按 consumer 求并集，共八个可能 target；没有无条件构建所有 workspace binary。

Core 的映射包括 `codex`、`codex-code-mode-host`、`codex-linux-sandbox`、两个 rmcp 测试程序、`codex-execve-wrapper` 及两个 Windows sandbox 程序。平台专属 binary 保留原 Rust cfg/stub；Cargo 按原调用的 target、配置和环境编译。Linux 上可能额外编译两个 Windows stub，这不代表执行或验证 Windows 测试。选择这一做法是为了不在 Python 中复制 Cargo 的隐式 target/config 解析。

`bwrap` 的 Cargo 候选函数受 `BAZEL_PACKAGE` 与 runfiles 双门约束，未把这一 Bazel 特定路径加入本桥。`wine-windows-exec-server` 是原 foreign-platform fixture，`codex-rs` 只出现在默认 ignored 的真实网络用例中；没有为它们创造别名或替代程序。`codex-exec` 的同包集成测试仍由 nextest 自身供应 metadata。

## 构建和身份约束

准备层执行实际 `cargo build`，只消费成功构建产生的 JSON `compiler-artifact`。每个结果必须匹配 freshly resolved package ID、target name、`kind=["bin"]`、原 `src_path`，并且是非 test-harness 产物。执行文件须为已有绝对普通文件；Unix 还须有执行权限。缺失、多个不同路径、错误 owner/target、错误源路径、无成功结束回执都会终止准备，不猜 `target/debug` 或 profile 目录。

原 nextest argv 完整保留。默认 helper 构建显式使用 Cargo `test` profile；`--cargo-profile` 映射到 Cargo `--profile`，`--release` 保持原含义。Nextest `--profile` 仅选择测试配置，`-j`/`-j1` 仅选择测试线程，二者不会混作 Cargo 构建参数。`--target`、`--target-dir`、锁定/离线标志、Cargo config 及构建环境保持来源。

增加 helper owner 后，裸 feature 和 `--all-features` 只展开原已选中包的已声明 feature，防止无意向新增 owner 开启额外 feature。明确的包限定 feature 必须属于原 scope；不能安全重现的 dependency-qualified feature 输入会给出明确错误。原 nextest 的 feature 参数本身不重写。

已有显式 metadata 遵守原 resolver 的优先级：精确 `CARGO_BIN_EXE_*`、其 underscore 形式、再到 `NEXTEST_BIN_EXE_*`。有效的显式值原样保留；更高优先级的无效值不会被新路径掩盖。构建获得的真实路径只传给子进程环境，不修改测试进程或调用者的全局环境。

Cargo rendered 编译诊断及非 JSON 错误文本会输出到 stderr；准备失败不会吞掉原错误，也不会启动后续 nextest。Cargo 本身的非零退出码会保留。

## 保留原 runner 的范围语义

精确 workspace 包选择、默认成员、`--workspace`、成员 manifest 和精确 exclude 可自动准备 helper。无 helper 需求的 scope 不构建它们。排除 helper owner 自己的测试不会删除 consumer 必需的运行时依赖。

原 graph-free metadata 优化与 fallback 主体保留。archive/reused metadata、opaque/glob/external package 选择和组合 scope 保持原 pass-through：不自动构建、不重映射、不修改 nextest argv，由原 metadata/env 负责。该边界明确保留兼容性，不声称这些调用已获得新桥接覆盖。确实需要准备 helper、但无法保证构建含义的未知 source-build 参数会明确报错；如果所有显式 helper 已齐全，则继续交给原 nextest。

本轮 `hepta-cell-framework-native.yml` 的 scoped Core 和完整 workspace 门都调用 `just test`，因而覆盖上述新 source-build 路径。既有 `.github/workflows/rust-ci-full-nextest-platform.yml` 直接构建/重放 archive，绕过该脚本；它只显式桥接了原 sandbox 程序，本次仅审计记录，没有扩改该工作流，也没有宣称 archive 模式已解决跨包 stdio 注入。

## 验证要求与当前状态

新增纯 Python 回归覆盖错误包/target/source/harness、缺失/歧义 artifact、Unix 权限、显式 env 优先级、参数/feature 范围、失败诊断、pass-through 与后续 test 退出码。另有一个依赖为空的真实两包 Cargo fixture：先让未供应 metadata 的原 nextest 确实失败，再验证 scoped/workspace 均能启动真实 helper，并保留 feature 导致的负例失败。

本地缺少 Cargo/nextest：完整 discovery 为 31 项，23 项通过，8 项因工具缺失跳过；其中原文件有 10 项（3 个纯 Python、7 个真实 Cargo），新增文件有 21 项（20 个纯 Python、1 个真实跨包 fixture）。这些结果不能替代 native 的完整 31 项执行。候选等待 native 在独立临时目录和 target 上运行原与新增全套、保留日志/退出码/每个测试名，再进入原 Core 与完整 workspace 门。

## 来源

- 源库基线：`bef6fa7645df9df12b69fda499e97eed25de6c75`；六个关键支持文件已由 native 比对 Core 原门树逐字不变。详见 `native-validation-results/core-fixture-metadata-audit/source-manifest.json` 与 `native-core-r8c-fixture-support-pins.json`。
- Nextest 0.9.103：[按包选 binary](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/nextest-runner/src/list/test_list.rs)、[注入运行环境](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/nextest-runner/src/test_command.rs)。
- 原 resolver 与其边界：[lib.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bef6fa7645df9df12b69fda499e97eed25de6c75/codex-rs/utils/cargo-bin/src/lib.rs)、[README](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bef6fa7645df9df12b69fda499e97eed25de6c75/codex-rs/utils/cargo-bin/README.md)。
- Core 显式依赖：[BUILD.bazel](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bef6fa7645df9df12b69fda499e97eed25de6c75/codex-rs/core/BUILD.bazel)。
- 闭合日志与逐例分类：`native-validation-results/checkpoint-through-r8d/core-r8c-failure-classification.json`（SHA256 `4eea16522f3673f2fd64c618e07adfcda99157a426b696b63ba2add552ad8bde`）。
