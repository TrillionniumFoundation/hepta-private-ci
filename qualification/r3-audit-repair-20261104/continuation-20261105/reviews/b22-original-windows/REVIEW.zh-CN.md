# B22 原 Windows TUI 范围闭合建议

建议将 **B22 原 Windows TUI 指定范围闭合**。本结论依据当前 `5b6331250ff459033bd44d1a95daec70131277cc` 的原 CI 正文与实际负向场景，不继承旧目标汇总的绿色。整体 B15、当前其他 Windows 失败和 Intel 平台资格独立保留。

原退出条件逐字为：“定位真实turn/interrupt与关闭顺序，保留原断言和时间预算，以固定修复源的原用例/有效负控及原WindowsCI验收。”

## 当前实际 Windows 证据

原 blocking CI `41999114842`、attempt `1`、job `127339255966` 的实际 checkout 是合成提交 `9063c52a063b6f26c48e9418f6d8dbd14e9e06ff`，树 `b26598d0d97d8d51e723bb5582137315f2174d35` 等于产品 5b。目标 `//codex-rs/tui:tui-unit-tests` 为非缓存标记的 `PASSED in 30.2s`，日志有实际八分片执行进度，工件源记录和 clean-worktree 检查一致。

工件 `13430142275` 为 5,227,725 字节，SHA256 `b2edb0892c80cc978215ab5a57b0a1e6f324f98709256c72a352c219f00bda81`。完整 20 成员 CRC 和逐成员 hash 均通过。八份 TUI 日志中，冻结的 **13 个所选名称均恰有一次 `ok`**，包含真实 shell 退出例与失败启动拒绝控制。完整 TUI 日志核得 3,775 个成功、6 个原 ignored；另外 Queue 为 36 个成功。九份 XML 仅是九个 Bazel wrapper 用例，个别案例结论来自原 libtest 日志，未把 XML 汇总冒充逐例 JUnit。

## 原合同与有效负控

当前 `background_exit_tests.rs` 的完整 blob 为 `d7d9ed4435b3fb7cb7d8303e94cbb223b5ced438`，与历史已验证的固定 `7c4370335115a1eb098c5b88981d9dff24371cf4` 源完全相同；TUI `lib.rs` 也完全同 blob。就绪仍需同一 thread、turn 和 UserShell item，真实输出 marker 出现，原 5 秒等待、30 秒 shell 持有、canonical cwd 全部保留。

生产 `event_dispatch.rs` 在实际 `turn_interrupt(...).await` 成功后才排入 `Exit(ShutdownFirst)`；当前原用例实际到达原 Continue、无多余 Op 和 ShutdownFirst 断言。失败启动控制使用真实不存在的 cwd，要求收到同线程 CommandExecution 的 Failed 状态和 exit code -1，且目录仍不存在。本次 Windows 上该控制实际通过，因此没有把仅 TurnStarted 误当真实进程已就绪。

历史冻结 `second-batch-qualification.json` 另保存旧 predicate 的有效负控：原单例在指定 expect_err 断言失败，随后固定 12 例通过，原 retries 0；历史 tree 和 JUnit SHA 完整保留。本次未重新取得该旧 XML，未把旧运行称为当前 5b 运行。当前 Windows 负向场景与固定源则已直接读取。

## 重试、忽略与限域

原 `defs.bzl` 对有分片的目标设置 `flaky=True`，其既有默认三次策略没有变化；本次不是人为指定 retries 0 的调用。完整工件没有 `test_attempts` 成员，原 TUI console 没有失败或 FLAKY 标记，每个所选名称只出现一次。这里只报告可观察原件，不凭文件缺失虚构全局重试配置为零。

原 Windows skip filter 不匹配这 13 项；六个其他 ignored 名称仍按 ignored 保留。成功日志收集器自身的来源限域也保留：收集时记录 checkout，不能仅凭 mtime 建立调用绑定；本审结合原 checkout、执行进度、目标结果和逐例正文，不声称解析了保存的 execution.zst。后续不同源须重新取得自己的原 CI 资格。

B13 的八个 Queue 原名在同包通过；第九个 Agentd qualification 目标没有被报告，因此本包不关闭 B13。完整 13 名称、成员路径、原行、源身份、历史负控与逐项退出条件见同目录 `closure-review.json`。
