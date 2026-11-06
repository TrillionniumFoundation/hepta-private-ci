# 两条旧修复支线的终态原件与 ac18 待执行增量

本包保存 2026-11-06 08:40:52 UTC 之前一次取得的两个既有 blocking run 完整 jobs 列表、两份完整 job 日志、holdout 官方 ZIP 的全部三成员，以及新 ac18 的后续待执行切点。没有启动、重跑或取消 CI，没有查询私有容量，没有改产品源码、断言、预算、ref 或 PR；不新增 blocker 闭合。

## 1. 旧 PTY 8075：原 31 例仍有四例失败，整个 job 取消

run `42167168039` 共 37 个唯一 job，全部 attempt 1：26 success、6 failure、1 cancelled、4 skipped。目标 Intel job `127729084043` 05:23:01–07:23:29，API 结论 cancelled。完整原日志为 `job-127729084043.original.log`（1,093,592 B，SHA256 `04a0203600c464102794b28e0ec0ab1479ef601026f896ad5390ea29ceaf5433`），完整 MCP 返回另存；工具原字符串的 UTF-8 SHA256 在 code-mode 独立计算，再与本地 Python 完整文件核对相等。

实际 checkout 的 `git log -1 --format=%H` 返回 `b88f625afe17975db80b152283ef2e19cc50e41f`。复用既有 root 发布原件，验证该 merge 的有序 parents 为 `[67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed, 8075eb367b6e97546af206b27bbf4a3a867497c8]`，source head 与 merge 均为 tree `c1249a173ac346d0f1230fe56451b97d4e13c601`。未重复查询发布信息。

原日志第 1817–1894 行包含完整 `//codex-rs/utils/pty:pty-unit-tests` 输出：31 个唯一用例，27 passed、4 failed、0 ignored，11.12s。四个失败为：

- `pty_drop_allows_runtime_shutdown_with_detached_child`
- `pty_dropped_output_receiver_keeps_draining_child`
- `pty_preserving_fds_drop_allows_runtime_shutdown_with_detached_child`
- `pty_close_stdin_preserves_large_input_and_delivers_eof`

原段逐字派生到 `pty-observed-31-case-segment.derived.log`，完整 job 仍无损保存，包括所有其它目标的失败、超时、进度和清理输出。末尾只明确记录 `The operation was canceled.`；本包没有取消原因证据，不能只按接近两小时的时长宣称 job timeout，也不归因于该单点 PTY 修改。

该 job 的 Bazel execution-log 上传步骤为 skipped。本包未取得它的独立 XML/BEP/compact，也没有完整 Bazel 最终汇总。因此只接受上述实际出现的 31 例输出，不声称覆盖每个 produced attempt、不声称 uncached、不从最后进度行推算整套 605 targets 的最终通过率。B21 仍需其原完整资格。

## 2. 旧 holdout 4a：六个文件锁用例通过，完整 scoped gate 失败

run `42176273058` 共 12 个唯一 job：4 success、2 failure、6 skipped。Linux job `127755476318` 06:44:07–07:36:43，结论 failure。它直接 checkout source HEAD `4a1410f332e4a34564feafbc4dcb2e808c7f6c5f`，不是 merge。原 guard 的 before/after 完全相同：tree `605720504e547296dca1c78914fee5ed6d29844d`、parent 67cc、dirty=false。

完整 job 日志 4,329,523 B，SHA256 `7bc3b24b56b1a3a4b9afa33217ee524cb2efc08ea16e627d7addd8c5c8c9f389`。官方 artifact `13486100626` 为 379,045 B，SHA256 `e7d981ea110d109c40b5e290ba23e6f5c9262c01debacd5b728d94c5d4a45813`；与完整 job 上传摘要及 run-artifact API digest 三者相等。ZIP 的全部三个成员均通过 CRC，并与展开文件逐字节相等：原 dependency plan、原 source/exit guard report、完整命令日志。命令日志 2,284,485 B / SHA256 `11c564a3fe25e105ad4ac775eed9b6b189278615d00eb2e67c0c9ff974c9c0af`，与 report 绑定相等。

原命令为 `python3 scripts/hepta_ci_dependencies.py --base 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed --tested 4a1410f332e4a34564feafbc4dcb2e808c7f6c5f --output /home/runner/work/_temp/cargo-impact.json --run`。完整 plan 保留全部 changed_packages 与 packages；这是受影响 owner/reverse-consumer 集合，不能把整套数量写成只测 holdout。

原 nextest 最终摘要：17,800 tests run，17,796 passed（6 slow、2 flaky），3 failed、1 timed out、49 skipped。原外层命令返回 100，wrapper 本身 timed_out=false；一个内部测试超时与外层总命令超时不是同一状态。

三个最终失败均为 codex-arg0 的 preflight 用例，每项首尝试与第二尝试都报告找不到 `test_arg0_preflight`，包括缺少 `CARGO_BIN_EXE_test_arg0_preflight` 对应值与 `target/debug/test_arg0_preflight` 文件。原完整错误、六个 failed attempt、两个原 flaky 控制全部保留。本包不将这个错误解释为 holdout 锁语义失败，也不先声称它已由其它 donor 修复。

内部超时为 `codex-hepta-supervisor::paired_process_product` 的 `five_real_pairs_adopt_all_ten_children_and_isolate_one_matrix_crash`，两个 attempt 分别 60.005s / 60.008s。日志有 warm_pair_complete、ten_children_ready，未见该用例完成 ten_children_adopted。本包只保留实际观测，不在缺少进一步内部定位时归因于 holdout、调度或任何特定调用。

六个 `fenced_holdout_file::tests`（原三个与新增三个 duplicate-handle 控制）均实际显示 PASS，名单和时长在 verification 输出中逐项列出。此范围限于旧 4a、Linux 的真实执行；不能改称整个 scoped gate 通过，不能赋予 Mac ARM 或当前 ac18 原生资格，不能据此闭合 B15。

## 3. 当前 ac18 与收件边界

新 head `ac18b623c7a6cb953b4660979e9b620fe7176bb2` 的 blocking run `42186354218` 在 08:35:03、08:40:18、08:47:04 三次完整 jobs 切均为 total_count=0。08:40:18 的完整单 run API 为 pending、conclusion=null、attempt1。时间为调用完成后取得的上界；没有把多个查询伪称同时发生。旧两支线结果不转授 ac18。前一个 08:29 包 registry `c425db96529df31d905b72da9c42bf64cbabb90e` 保持不变。

单项 artifact API 曾返回不支持端点的 HTTP 400，原错误完整保存；随后使用正常 run-artifact 集合取得唯一 artifact 的官方 metadata，下载一次完成。临时下载凭据不归档，保留的是 ZIP 原始字节、可重算身份及安全收件回执；其它标为 original 的 MCP 返回为完整对象 JSON 序列化，不是 HTTP wire capture。

离线验证入口：`python3 verify_terminal_evidence.py --root <解包目录>`。它完整核对 cloud UTF-8 hashes、两个 MCP/log 等价、全部 API 分母/唯一 ID/head/attempt、PTY 实际 merge、31 例原段、官方 ZIP 与全部成员/CRC、source before/after、完整 plan/report、各失败 attempt、六个文件锁 PASS，以及三次新 head 待执行切。首次重放 exit0、stderr0，输出 35,322 B。该 Python 验证器不会联网或运行产品代码。
