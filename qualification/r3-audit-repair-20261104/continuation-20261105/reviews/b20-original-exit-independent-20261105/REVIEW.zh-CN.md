# B20 原始握手、真实 AppServer 关闭与断连证据复核

## 结论与范围

本包提出 `ORIGINAL_B20_EXIT_EVIDENCE_SATISFIED_PENDING_ROOT_REVIEW`。原验收句保持不变：**确定性旧源同握手错误、新源对照及原真实 AppServer 关闭/断连断言全部通过。** 本复核不修改工作账，不代替根审，也不把旧测试记录改称当前候选的全量通过。

这次补齐的是此前缺失的完整原始因果记录。旧 GNU 源 `0ec7ee504e4450a6a959a437a54363d8634100a9` 实际运行两项控制，连接夹具稳定报出 `WebSocket protocol error: No "Connection: upgrade" header`，普通 HTTP 非升级控制通过，结果为 **1 PASS / 1 FAIL，exit 100**。修复源 `98e7be301dec58f14d51738221e4445e3a06d900` 实际运行全部 19 项原 remote-control 测试，结果为 **19 PASS / 0 FAIL，exit 0**。日志里的 1,016 / 1,000 skipped 是选择表达式排除的其他测试；所选两项与十九项的 JUnit 均没有 ignored/skipped 节点。

上述两次原始命令都保留 `just test --locked --offline -p codex-app-server --test all`、`--no-tests fail --retries 0 --test-threads 4`。总耗时含编译，分别为 263.108 秒与 84.783 秒；JUnit 测试阶段分别为 0.110 秒与 4.592 秒。这些时间不能混为单项测试耗时。成功命令没有 `--success-output immediate`，因此本包不虚构成功测试的完整捕获 stdout；完整 PASS 行、JUnit、测试函数和可达真实断言一起构成证据。

## 因果源码与原断言

从实际取得的 e729 完整基树 9,499 个叶子出发，分别应用两份原始 manifest 的 47 项记录，重算出的完整 Git 树精确等于负例与修复源树。两棵源树只在 `codex-rs/app-server/tests/suite/v2/remote_control.rs` 一叶不同。固定文件 Git blob 为 `10a523727b458839c4c2899596f01338e871248e`。

负例 blob 的直接 GitHub GET 返回了 404，原响应保留。负例源码通过实际 e729 基文件和原始 119,086 字节 patch 中该文件的完整 6,306 字节片段重建：正向和反向 Git apply 检查通过，51,810 字节结果的 SHA256/Git blob 与旧原 manifest 精确一致。它的身份是**精确重建的旧源**，不是一次成功的旧 blob GET。

负例的 18 个测试函数正文在修复源中全部逐字节不变；仅新增 `http_fixture_rejects_eof_before_request_headers_complete`。原 `stdio_eof_exits_with_remote_control_connection` 从 e729 到负例、固定源正文也完全不变。原 10 秒与启动 30 秒预算保留，没有选择性 ignore、skip 宏或测试体提前 `return Ok`。

旧错误通过先完整发送普通 `/v1/models?` 请求、再建立 WebSocket 的顺序稳定复现。修复后的 HTTP 读取器先完成模型 HTTP 响应，再把真实握手头部、正文与 BufReader 内预读数据按原顺序交回 `accept_async`；它没有把普通 HTTP 伪装为成功握手，也没有删除缺失升级头的拒绝控制。新 EOF 控制验证空输入和未完成请求头均返回 `UnexpectedEof`。

真实关闭控制仍通过 `TestAppServer::builder()` 启动真实 `codex-app-server` 可执行文件，完成 initialize 和 remote-control enroll/initialize 往返，然后 `shutdown_gracefully()` 关闭真实子进程 stdin 并等待进程退出，断言退出成功，再等待实际 backend 连接读循环结束。`TestAppServer`、HTTP 夹具依赖、transport 和 remote-control processor 的源码身份都已核对。

## 当前候选桥接与 B23 边界

完整源码树重算覆盖 5b、e78、eed，以及当前主候选 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / tree `3982ba56dc5a3f1da0c1de7ea57992f88125c359`。67cc 的证据是根审已绑定实际 Git 根的完整预期叶树，本包再次重算；它不被描述为一次递归 Git GET。固定 remote-control 源码与整个 AppServer 子树在这四个当前源中相同。AppServer transport、AppServer protocol、state、cargo-bin 和 tests/common 的完整子树在旧基源到这些当前源也相同。

旧 GNU 与当前 `app-server/src/lib.rs` 存在 B23 的 signal subscription 改动，**不宣称整份 lib 或二进制逐字节相同**。原 stdio 的 `TransportEvent::ConnectionClosed` 分支逐字节相同；原 `install_shutdown_signal_handler && !single_client_mode` 条件使 signal 分支在 stdio 情况下禁用。listen-off 的 signal 分支不在本包的“旧 GNU 字节等价”结论内。最终 Unix signal CI 仍属于 B23 的独立开放门。

## 独立 Windows 原始补证

现存 5b Windows job `127339255880`、artifact `13431285250` 的真实 checkout 是 merge `9063c52a063b6f26c48e9418f6d8dbd14e9e06ff`。4,967,167 字节 ZIP 的 54 个成员全部 CRC 与完整 SHA256 检查通过；该目标有 16 个原始 shard，19 个 remote-control 名字各出现一次 `ok`，原 job 对 AppServer 目标的汇总是 `PASSED in 57.2s`。整个 job 的其他目标仍有失败，本包不把 job 改成全绿。

完整 Bazel compact 日志解码消耗 **29,681,851 字节、87,246 个原始 entry**。目标的 16 个真实 `TestRunner` 均为 local、非缓存、exit 0，保持原 900,000 ms action 预算；另外 16 个动作只是 XML 生成器。实际测试环境中没有 `CODEX_SANDBOX_NETWORK_DISABLED`。完整选中 frame 及偏移、全部目标 raw/XML 都保留。

15 对 raw/XML 的全文内容字节相同；shard 8 的 XML writer 将原日志中 XML 不允许的 ESC 字节变成 `?`。本包保留两份完整原件，记录每个替换偏移，只允许这一精确转换，未删减日志。此前历史档里的 “19+3 attempts / FLAKY” 不是这个 5b ZIP 的结果，不能移植到这里。

完整 Windows ZIP 已保存在发布过的 V7 main-Windows 85 段归档中；本包带有其既存 transport/member manifest、原 ZIP 身份及选中完整原件，不重复存储整个 ZIP。验证器可用 `--windows-zip` 重开原 ZIP 并再次解码完整 compact 流。

## 复核入口

运行 `verify_b20_original_exit_v1.py --root <解包根目录> --windows-zip <已有13431285250.zip>`。它只验证保留字节与隔离临时目录中的 Git apply，不启动产品测试、native 进程，不改 source ref 或工作账。输出保存在 `derived/independent-verification.json`。三次证据解析器初始观察单独保留：XML 嵌套路径、ESC 转换、GitHub fetch_blob 只返回 content；这些是本次云端证据处理器的修正，不是产品测试失败，也没有改变原始输入或既定验收值。

**保留边界：**原 48 条记录的 GNU/musl 平台标签、当前候选全量门、B23 最终 Unix 信号门和其他 blockers 不由本包改写。全部 blocker 已闭合及候选全量合格均保持 false，最终是否将 B20 记为 scoped closure 交由根审按原验收句决定。
