# f070 的后续 CI 观察：格式已被维护补丁覆盖，Windows 与依赖门仍保留原终局

这份追加记录只读取指定 CI 的既有结果，没有修改运行时代码、重跑测试、重跑 CI 或屏蔽门禁。原始失败保持失败；后续 dde 的静态补丁覆盖和本地 strict Clippy 通过不等于这些远端任务已经重跑通过。

## 源码身份

PR head 为 `f070113bb61cda492d2668b3afbbcda13e11fa52`。blocking run 的 build-test 与两个 Windows Bazel job 实际 checkout 是 GitHub 合成 merge `9498ada2adfa88f5562d9e91acab3dad480fcb3d`，父提交为 M6 与 f070。读取 Git commit 对象核实其 tree `068b6a7749e94d7335c826d6c43c19198e02cc24` 与 f070 完全一致。独立 Windows-private job 明确 checkout f070。

用于对照的原 M6 Windows 日志实际 checkout 为 `1fd5f73489497b16fd4a44b4bc0bd40173de7343`；其 tree `293ece7ffdffa2332ccfdec4fbbc4b7dcb3363cb` 也与 M6 `885dae0f3285267e9e9c49d8b43b0d009779f9e8` 一致。精确对象、父提交和选定失败位置的原/新文件 SHA 见 [SOURCE_IDENTITY.json](SOURCE_IDENTITY.json)。

## 指定失败的实际原因

| 观察 | 原始结果 | 分类与维护覆盖 |
| --- | --- | --- |
| [blocking build-test 129159652068](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372714/job/129159652068) | 第 19 步格式检查失败；6 个 Python 文件、11 个 Rust 文件 | 6 个 Python 路径正是 dde 的 6 个已格式化文件；72 个 Rust hunk 的 f070 前像和 dde 后像逐字复核成立。覆盖核验不构成远端重跑结果。 |
| [Windows-private 129153808326](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372441/job/129153808326) | 第 9 步 durable owner Rust 格式检查失败，尚未执行该 workflow 的 Windows native suite | 去除日志时间戳与 ANSI 后，与 build-test 相同的 72 个 Rust hunk、11 个文件；均由 dde 覆盖。 |
| [cargo-deny 129159652206](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372714/job/129159652206) | `Run cargo-deny` 已失败 | 原因尚未观察。GitHub 日志接口未取得正文，另一条 Mac gh GET 在 90 秒后超时；这些是取证失败，不能推断 CI 是因网络、依赖策略、V8 或其他原因失败。 |
| [Windows Bazel shard 3/4 129159652631](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372714/job/129159652631) | 实际运行测试，最终 hepta-agentd、hepta-neuron、tui 三个 target 失败 | Windows 文件锁 code 33、Circuit fixture `Invalid`/`PermissionDenied`、perception fixture 字节多出 CR=13、TUI 路径有无扩展前缀的断言。不是 V8 获取失败。27 个不同失败 case 中 25 个在原 M6 同一 shard 日志已失败；另外两个新 credit case 在未改的服务 fixture 构造时遇到同样 code 33，尚不能据此建立新运行时回归。 |
| [Windows Bazel shard 1/4 129159652726](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372714/job/129159652726) | 最终 exec-server test target 失败 | legacy Windows sandbox 因 ambient parent `FILE_DELETE_CHILD` 无法保证删除边界而拒绝，原 M6 日志已观察同一错误。另有 core resume-context cleanup 超时，但 Bazel 最终记作 FLAKY，不额外算作失败 target。 |

详细格式核验在 [FORMATTING_HUNK_REVIEW.json](FORMATTING_HUNK_REVIEW.json)：两处末尾虚拟 EOF 空白 context 显式处理，没有缺失格式修复。Windows 每个失败名、首次失败正文与 M6 对照在 [WINDOWS_COMPARISON.json](WINDOWS_COMPARISON.json)。最终 Bazel 统计分别是 shard 3：99 target pass / 3 fail / 45 skipped；shard 1：92 target pass / 1 fail / 51 skipped。它们是 Bazel target 计数，不是 Rust 测试用例总数；原始 `Executed 46 out of 147` 与 `Executed 40 out of 144` 也完整保留，不把 cache 与 skipped 混成新执行。

## Architecture 与证据边界

本次只读快照中，[Architecture run 42615372442](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372442) 的 source-head job `129153810392` 仍在 `Compiled service lifecycle and actual process restart`；base-merge job `129153810121` 已 success。没有新的完整 Architecture 终局，也没有宣称共同候选全 CI 通过。

4 份可取得的完整 job log 逐字保存为 gzip，解压字节 SHA 与压缩 SHA 均见 [RAW_LOGS.json](RAW_LOGS.json)。cargo-deny 的不可取得状态、原取证错误与 Mac bounded GET 回执单独保存于 [CARGO_DENY_RETRIEVAL.json](CARGO_DENY_RETRIEVAL.json)。三份 job 快照原件保留在 snapshots/；它们只表达各自观察时刻。

代码维护身份仍为 dde，维护证据见 [../maintenance/README.md](../maintenance/README.md)。f070 的本地 native、模型与 Root 结果没有转移给维护后的源码。完整普通 P0 和科学资格不由这份 CI 观察追加产生。
