# 原生四包运行：临时目录与 JUnit 配置更正

## 核对范围

本审查针对固定测试源码 `58c81ccdd25002ae0f481d434af067a56fa7ddb8`，tree `57809be09ef01c02389ef37a817f1447d13d167b`。后续导航或证据元数据提交不能替代这个实际 Rust 测试身份。以下结论来自固定源码、实际 Run1 日志及 nextest 0.9.103 的原始实现；它们不替代对运行结果的审计。Run2 原始 XML、receipt、metadata 原件及报告配置的独立核对现已完成，详见[四包原生测试独立审计](native_audit/independent-native-run-audit.md)。

## Run1 的实际失败与证据缺口

原运行器记录的 run ID 为 `ec0d4c41-c964-433e-b3d1-f7c66a4ac083`。原日志汇总为 **697 tests run，696 passed（1 slow），1 failed，66 skipped**。唯一失败为：

`codex-hepta-infer-worker-host` / `native_app_server::tests::real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone`。

原 profile 的两次尝试都在 `probe existing agentd control socket` 阶段返回 `InvalidInput: path must be shorter than SUN_LEN`。该错误发生于 host 初始化，尚未到达该用例的新鲜记忆、final-use 删除及纠正断言。首轮结果仍然是失败；不能把原因属于环境解释成测试已通过。

Run1 没有生成原生 JUnit，也没有完成 59 项 XML 审计。早期“local profile 会继承 default.junit.path”的结论有误，已由固定版本实现推翻。原错误审查文件保留为历史记录；当前结论以 [nextest-0.9.103-junit-correction.json](nextest-0.9.103-junit-correction.json) 为准。没有将 stdout 转写为 XML。

## 临时目录修正为何适用

用例以 `std::env::temp_dir()` 为根，再添加 `hepta-cognitive-worker-e2e-<nonce>`。`CognitiveTestHost` 创建并 canonicalize 此目录，真实 fleet layout 将控制 socket 和 App Server socket 分别放在 `fleet/run/a<compact-id>.ctl` 与 `.app`。真实控制服务器先用 `UnixStream::connect` 检查现有 socket，再执行 bind；路径错误在这条正常路径上直接传播。[源码：测试用例](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58c81ccdd25002ae0f481d434af067a56fa7ddb8/codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs)、[host fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58c81ccdd25002ae0f481d434af067a56fa7ddb8/codex-rs/hepta-agentd/src/test_support.rs)、[fleet layout](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58c81ccdd25002ae0f481d434af067a56fa7ddb8/codex-rs/hepta-paths/src/fleet.rs)、[控制 socket](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58c81ccdd25002ae0f481d434af067a56fa7ddb8/codex-rs/hepta-agentd/src/control.rs)。

Linux 的 `sun_path` 数组为 108 字节，Rust pathname 地址构造要求路径字节数严格小于该数组长度。原实际控制路径为 **140 字节**。使用新建、owner 私有、权限 `0700` 的 `/tmp/a9f4ebc7` 后，同样格式的 `.ctl` 与 `.app` 路径均为 **102 字节**，前提是 canonicalization 后仍是该短目录。这一计算针对此次 Linux host。[Linux Unix socket 文档](https://man7.org/linux/man-pages/man7/unix.7.html)、[Rust Unix socket 地址实现](https://doc.rust-lang.org/src/std/os/unix/net/addr.rs.html)、[Rust temp_dir 文档](https://doc.rust-lang.org/std/env/fn.temp_dir.html)。

隔离子进程继承环境，只添加原 case/completion marker；精确测试名、进程组清理及完成标记断言均未改变。此次环境修正没有更改测试源码、授权输入规则、测试超时或重试预算。[隔离 helper](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58c81ccdd25002ae0f481d434af067a56fa7ddb8/codex-rs/hepta-infer-worker-host/src/native_test_process.rs)。

## nextest 0.9.103 的实际报告规则

仓库原配置将 `junit.xml` 设置在 `[profile.default.junit]`，原 `just test` 入口选择 `NEXTEST_PROFILE=local`。0.9.103 的 `JunitConfig::new` 对 `path` 使用以下选择方式：

```rust
custom_data
    .map(|custom| &custom.path)
    .unwrap_or(&default_data.path)
```

存在自定义 local profile 时，其 `path=None` 会保留下来，不会回退到 default 的路径，因此不会创建 JUnit writer。这是报告路径的特殊规则，不能从其他 profile 字段的默认继承规则推断。[固定版本实现，blob `abc86ad3e82f605a7365427ab79f7466c06a48c9`](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.103/nextest-runner/src/config/elements/junit.rs)。

已核对的 Run1 实际 `nextest.toml` 与原固定源码逐字相同，SHA-256 为 `351cdfe17480eae1124145e32a0de6de2889a38f01b14036187bc42e2553fdde`；实际 `run-nextest.py` 亦逐字相同，SHA-256 为 `45c4e35d1ff24840d9e1e05331af0b89475bfe1aec3231afc56fecb8cea66127`。包装器的临时目录仅保存 scoped metadata；它既没有重定位 workspace root，也没有删除 JUnit。

## Run2 的原生输出方案与选择等价性

继续使用原 `just test` 入口和原 local profile。源码树外的工具配置只包含：

```toml
[profile.local.junit]
path = "/absolute/evidence/fourpkg-run2.junit.xml"
```

0.9.103 原生支持 `--tool-config-file TOOL:ABS_PATH`。配置按 embedded、tool、原 repository 的次序合并，原 repository 配置优先；这两行只启用明确路径的原生报告输出。[CLI 定义，blob `17a38c772684d8a4c2c8b1a140b843c8695b6ee6`](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.103/cargo-nextest/src/dispatch.rs)、[配置合并，blob `98b92000c673b4baf061734b12d24c44279d72d8`](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.103/nextest-runner/src/config/core/imp.rs)。

原包装器会对 `--tool-config-file` 进入已有的透传分支。为继续使用 Run1 的 scoped metadata 语义，先在同一冻结源码的 `codex-rs` 工作目录、同一 Cargo 环境执行原 scoped 分支使用的命令：

```bash
cargo metadata --no-deps --format-version=1 --locked
```

保存其原始成功输出，再给原 `just test --locked` 和相同四包参数追加 `--tool-config-file` 与 `--cargo-metadata`，传入报告配置及这份 JSON 的绝对路径。两个附加参数和 metadata 的实际位置必须写入运行 receipt，不能称为命令字符串完全未变。

已直接检查实际包装器，并调用其只读参数解析函数：附加选项前后均选择 `codex-hepta-agent-protocol`、`codex-hepta-agentd`、`codex-hepta-infer-worker-host`、`codex-hepta-runtime`，`filtersets` 均为空；新增参数进入原透传分支。实际仓库配置没有 `deps`/`rdeps` 过滤。该方案没有修改 package、feature、测试过滤、profile 选择、timeout、retry、test threads 或断言。[原包装器](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58c81ccdd25002ae0f481d434af067a56fa7ddb8/scripts/run-nextest.py)。

补齐的 [metadata 压缩原件](../publication/native-evidence/run2-original-scoped-metadata.json.gz)已解压并与原始 JSON 逐字节核对，其 SHA-256 与 [metadata receipt](../publication/native-evidence/run2-original-scoped-metadata.json.receipt)及 Run2 内嵌记录一致。workspace 指向上述冻结源码，四包启用的 21 个测试目标与实际 JUnit suites 完全相等；[报告配置原件](../publication/native-evidence/report-only.nextest.toml)仅包含 `profile.local.junit.path`。完整检查记录见[独立审计 JSON](native_audit/independent-native-run-audit.json)。

## 实际结果审计边界

原始 49 项审查清单保持不变；追加版包含相同 49 行及 e65 的 10 个原回归用例，共 59 项。真实 XML 必须由 nextest 直接生成，并与冻结 C58、执行清单、原退出码及传输 hash 一起审计。此版本 JUnit 仅列已运行用例，**全套 66 skipped 仍须依据原运行器 Summary 保留**。697 个 XML testcase 的存在不能表述为整个套件没有跳过测试。
