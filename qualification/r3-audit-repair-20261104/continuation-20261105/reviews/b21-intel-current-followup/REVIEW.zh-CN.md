# B21：Intel 原因果复核与已发布观察点

本次固定源码为 `eed4d6bb61b789b19f60facc79f9e031765fa4c9` / tree `ca1c4671ef6b2773280d01b5d76c6166252f5856`。**B21 保持开放；没有足够证据据此编写新的生产排水修补。** 当前有一项可直接消除的证据缺口：成功的原 PTY 目标未列入日志留存名单。附带的一行 CI 候选只修这个缺口。

## 已有原件所支持的结论

| 原精确范围 | 实际 Intel 原件 | 可以证明的范围 |
|---|---|---|
| cabc 原 30 例 | 28 PASS / 2 FAIL | drain 在 portable 分支原 2 秒失败；close-stdin 得到 `(-1, "__complete__")` |
| 0e139 原 30 例及新增 collector 控制 | 30 PASS / 1 FAIL，即原 30 中 29 PASS / 1 FAIL | 原 close-stdin 和现有 collector 控制均实际通过；drain 仍失败 |
| 0e139 残余 drain | spawn 5.331807 ms，等待 2.023066511 s，`deadline_elapsed`、`has_exited=false`、`exit_code=None`、`python_started` | 未进入 preserved-FD 第二轮；没有实际 read 字节或 errno，不能定位阻塞系统调用 |
| 5b Intel main | 冻结 snapshot0078 中 job127339256123 为 cancelled / runner0 / steps[] | 没有取得这份源的 PTY 执行原件；不能把别的 Intel operator 或 V8 成功转借 |
| eed 新 main | 冻结 snapshot0005（16:46:22–24 UTC）run42063948117 / attempt1 pending，未展开 Intel main job | 后续状态由独立新 CI cut 承接，不能从这一旧快照断言当前仍未运行 |

原 30 名、31 行及每行原文都在 `original-exact-case-projection.json`。cabc 的原 XML 是一个 Bazel 目标错误包装；30 条真实单元结果来自完整 libtest 正文。0e 的失败块发生在整 job 后来取消之前。旧 forward 的 30.603 秒属于 ExecServer 写入超时，不是 PTY 的 2 秒 drain 预算。

## 已修部分与仍未确定的原因

旧输出收集器会不断选择已经关闭的广播接收分支。已发布夹具以 `output_open=false` 停用该分支，继续等待原 exit receiver 和原 deadline。既有新增控制实际把该收集器 poll 到 pending，再发送真实 exit37，并要求完整输出及退出值。后续 0e Intel 的原 close-stdin 例也实际 PASS。但旧 `-1` 曾混合 deadline、exit channel 关闭及 child.wait 错误，不能仅凭后一次通过倒推原失败的唯一原因。

残余 drain 直接等待 `exit_rx`，不经过该收集器。当前 Unix reader 在输出发送失败后仍继续读；每个会话只注册一次 AsyncFd，复用一个 8192 字节缓冲。已读的固定 Tokio 1.53.3 源码在真实 WouldBlock 时才清 readiness，并在每次 I/O 前经过 cooperative budget。没有发现足以静态证明 lost-wakeup 或“接收端关闭即停止 drain”的源码证据。

eed 已含原作者冻结的会话观察点：实际 read calls/bytes、丢弃 bytes、EOF/errno、reader/writer/waiter 完成状态、同一个 AsyncFd 的 F_GETFL 与非消费 FIONREAD。它在**原 timeout 已返回以后、原 terminate 以前**打印；不是 deadline 当时的原子快照。统计使用独立 relaxed atomics，可能扰动测试调度，但不驱动生产 I/O 或通过条件。

当前测试全文仅比 0e 多四行观察输出；删除这四行即可逐字恢复原文件。原 30 名、原 2 秒／5 秒、4 MiB 单次 Python 写入、child/FD/退出值与清理断言均保留。两项 macOS 专属 process-group 控制仍不能由 Linux 29 例替代。暂不再添加 sleep/yield、termios 调整、readiness 清除或 waiter 改写。

## 下一份必须取得的原 Intel 原件

- 原工作流 `.github/workflows/blocking-ci.yml` 调用 `.github/workflows/bazel.yml`。
- 原 job：`Bazel / Bazel test on macos-15-intel for x86_64-apple-darwin`。
- 原目标：`//codex-rs/utils/pty:pty-unit-tests`。沿用原 `run-bazel-ci.sh test //...`、标签筛选、缓存和重试设置；本次未要求新增测试命令。
- 原相对文件：`bazel-testlogs/codex-rs/utils/pty/pty-unit-tests/test.log`、`test.xml` 及可用 `test_attempts/`。
- 原 artifact 名：`bazel-execution-logs-test-x86_64-apple-darwin`。
- 核原 30 名及新增 collector 1 名逐行结果、所有实际 attempts、缓存、Python 前置与真实 source/merge/runner。如果再次 drain FAIL，先取 `io_snapshot` 和 `child_phase`，再按实际字节/errno决定最小修复。

若完整 4 MiB 已排出而 waiter 未返回，下一边界是 child post-write/退出与 wait。若 reader 提前 EOF/EIO，下一边界是 FD 生命周期。若 reader pending 且有 queued bytes，才进一步调查 readiness；单个快照仍不足以证明丢唤醒。通过且没有成功 stdout 诊断，也不能自动解释旧原因。

## 独立的一行证据留存候选

在现有 `RETAINED_TARGETS` 原 11 项之后追加原 PTY 目标；其余全文不变。

- preimage：`2142eeb382664d95f77d83ac7ae3da4459601abf`
- postimage：`18701f51e4df1ef6b0fd390d2990114bf971331d`
- patch：`e0f94bd68a555a7ca4af773a26c4957215284dcf`
- 变化：1 行新增、0 行删除；原 11 项顺序完全保留。
- 云端静态核验：两个 Python AST 可解析、反向删行恢复全文、独占临时目录真实 git apply/check/reverse 四命令通过。
- 原回归门仍为 `python3 -m unittest discover -s .github/scripts -p test_run_bazel*.py -v`，本次未执行任何项目测试。

该项会扩大 GNU、macOS、Windows 原 invocation 的**已有成功日志**归档范围，不增加执行、不禁用缓存、不调整筛选或预算。NOT_REPORTED／SKIPPED／AMBIGUOUS 仍不读取旧目录，缺日志显式保留。原 job 后来取消时 `!cancelled()` 上传条件仍可能阻止 ZIP；本候选不改变它。成功测试的 stdout 默认仍可能被 libtest 捕获，所以它保证可留存已有具名 ok 行，不保证成功诊断全部可见。

候选未应用、未建分支、未更新 ref；按 root 指示等下一次必要产品发布再考虑纳入。完整 source map、原件投影与机器审计结论均保留；账本退出条件和闭合数字未改。
