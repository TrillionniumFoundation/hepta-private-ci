# B21 原 macOS Intel PTY：自动运行终态与因果边界

## 结论

**原完整 PTY 目标已在真实 Darwin x86_64 / Intel 机器完成一次非缓存执行，libtest 原日志记录 31 PASS / 0 FAIL / 0 ignored / 0 filtered。B21 仍为 OPEN。** 这次结果补充原平台的运行记录；旧 2.023066511 秒 drain 失败的具体原因仍然未知，成功日志也没有展开每会话 reader counters。

同时保留一个证据边界：原测试已有 `find_python()` / `setsid_available()` 失败时返回成功的分支。本次 libtest 捕获了成功测试的输出，原件既没有 counters，也没有这些条件分支的执行明细。因此这里验证的是完整实际测试清单与每条 `ok` 结果，不能把没有 skip 字样当作额外证明，断言所有条件体都实际走完。原测试源码、断言与预算均未为取得本次结果而改写。

| 身份 | 已验证的精确值 |
|---|---|
| 自动 workflow run / attempt | `42138373221` / `1`，`pull_request`，completed / success |
| 原 job | `127632180031`，全部步骤 success |
| 实际 checkout source HEAD | `cc65856cc0b20d03db506c19495d53d61162102d` |
| source tree | `eaded1870d080eaa55efae6208354729140e784c` |
| 固定 parent / tree | `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / `3982ba56dc5a3f1da0c1de7ea57992f88125c359` |
| 实际 PR merge，仅作关联 | `f0355601e362e2ad4947b40d51215e5c4d075fc3`；不是本 job checkout |
| 原 artifact | `13466574706`，`b21-original-intel-pty-42138373221-1` |
| 原 ZIP | 1551105 字节，17 个成员，CRC 全部有效 |
| ZIP 官方 SHA256 | `26d153e60b60e8206261da3819a9f1a8ac235fd2e3b82d3a709de8bdb9373309`，下载原件全字节匹配 |
| 实际平台 | Darwin 24.6.0，macOS 15.7.9 / 24G830，Intel Core i7-8700B，x86_64 |
| 原 Bazel 退出 / console-copy 退出 | `0` / `0` |

原运行链接：[run 42138373221](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42138373221)；关联 [Draft PR #4902](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4902)。只进行一次 commit workflows 状态切点；该切点已终态。原 blocking-ci 同切点仍 queued，不能由此单目标诊断替代完整 required CI。

## 实际源码与运行边界

独立重算 parent 和 source 全部 1571 个目录的 Git Merkle hash。parent 10582 个原叶全部保持，只有工作流 `77387b7a3e8a15efe11cca02bf4185377ff0a86f` 新增；运行中记录的 10583 个 `git ls-tree -r` 叶子与完整 source tree 相等。实际 HEAD/parent/diff/platform guard 步骤成功，前后 tracked status 为空，最终原 clean-worktree action 成功。

原 argv 只有一次完整 `//codex-rs/utils/pty:pty-unit-tests`，保留原 wrapper、ci-macos 环境、`--nocache_test_results` 和 `--flaky_test_attempts=1`，没有 case filter、重复运行、skip 或 timeout override。source HEAD 与 PR merge 分开记录，不能把两者有相同 tree 当作实际 checkout 证据。

9 份 PTY 相关源码由本次独立 full GET 取得，每份完整字节均匹配运行 source-leaves。旧 0e139 `tests.rs` 的实际 `42fc028d6e710dab9f9390ad7ee1b711ba1927d6` 与本次 `25836a08f9ff9a90b14204059d2544749a0f5461` 只有一处四行 snapshot 打印插入。移除这处打印可逐字节恢复旧全文，原 2 秒 drain、4 MiB 单次输出、portable→preserved-fds 顺序、退出码断言、5 秒 close-stdin 和 FD 断言因此保持。

## 实际 31 例与原 30 例

完整 `test.log` 为 2455 字节、SHA256 `92a3ef68e813bb3567a47f91bebb7c8e9acc303ff4f49a71237c29800b95824f`，报告 3.65 秒。31 个唯一实际结果逐条列在 `VERIFIED-02.stdout.json`，其中完整包含旧原 30 例，另一个是此前已有的 `output_collector_waits_for_exit_after_output_closes` 控制；本工作流没有新增测试。

两个 Mac 专属用例均有实际 `ok` 行：

- `process_group::tests::denied_group_signal_rejects_unsafe_process_group_ids`
- `process_group::tests::denied_group_signal_terminates_owned_descendants_and_preserves_escalation`

这两个源文件由 `cfg(all(test, target_os = "macos"))` 精确绑定，正文和原 5 秒子进程检查保留。旧两次失败相关的 dropped-output / close-stdin 用例本次也各有 `ok` 行，前述成功输出捕获和条件早退可见性限制仍适用。

原 XML 2868 字节、SHA256 `42c43a730a06a7334f937c8e8fd85e8b7dccf39e8a03a56e7bdfa89badd77271`，包含的是 **一个 wrapper testcase**，其 system-out 嵌入完整 31 例日志。没有把 wrapper XML 的 tests=1 冒充 31 个独立 XML testcase。

## compact 与 collector 的交叉核对

原 compact 压缩成员是 1189064 字节 zstd。解压严格验证 EOF、无尾随或未消费字节，得到 8635511 字节、14846 条完整 protobuf entry；使用已固定的官方 Bazel 9.3.0 `spawn.proto`，其实际源码 blob `19f68f22a4d62c4fd1aa28fd1c7c0217aa6a7cb0` 和原 GET 回执均包含在包内。

该目标只有 **一条真正 test-setup.sh TestRunner**：`darwin-sandbox`、cache_hit=false、exit=0、原外层 300000 ms。第二条是独立 `generate-xml.sh`，不算第二次测试或 retry。实际参数和环境没有 case filter / RUST_TEST_THREADS / RUST_TEST_NOCAPTURE；原 invocation ID `21969864-0d2a-42f0-a2bc-7a5e541e7e2b` 与 console 一致。

除 manifest 的自身声明以外，解码到的 file entry 13256 将归档 `test.log` 的精确字节摘要绑定为同一 invocation 的 XML 生成输入；entry 13258 将精确 `test.xml` 绑定为该 action 输出。原两条 frame 的完整 protobuf 字节、偏移和摘要都保存，可重新核对。

collector 的原 `complete_for_selected_targets=true`、errors=[]、两份文件 byte/hash 全等。其 `complete_case_inventory=false` 与原 limitations 原样保留，没有替 collector 扩大结论。collector 自身记录的 13567 字节 console 摘要精确对应外层 13792 字节 tee 文件的 offset 67 连续切片；外层多出的 wrapper 提示和归档回执不被误判成日志缺失。

## 旧失败没有被抹去

通过已知旧 GitHub job `127089468985` 的原日志 API 重新取回 767416 字节，完整 SHA256 `dc3b6664bc61ef353c4fe2d231efc198182536671a6297f2c89b0dfa0e57c49a` 与历史记录相同。旧 Git blob `250f40c...` 直接 GET 返回404的原响应也保留；后续取得原 job 完整日志后，按原第1368–1415行恢复4201字节原 PTY block，SHA256仍为 `65b4c2f87c1884ae35fae23c446a63bfd1759c6d71587bc9281d3ad8dabf1d2d`，没有将404当作证据不存在。

旧 run `41975255726` 的该原块是31例30P1F，原30子集29P1F；portable backend 实际 wait_elapsed=2.023066511s、deadline_elapsed、has_exited=false、exit_code=None，child_phase只到python_started。旧完整 job 后续取消与此前已完成的 PTY 失败分开。本次 pass 无法补出旧 reader bytes/errno 或具体调度状态，不能据此推断负载、吞吐、丢唤醒、collector 或单一产品根因。

## 可移植复核与后续门

从 lossless archive 恢复后执行：

```bash
python verify_terminal.py --root <恢复目录>
```

脚本只读取保存的 JSON、源码、日志和 ZIP，使用 Python zstandard 解码；不联网、不写产品文件、不创建 native 进程、不查宿主资源、不修改 ref。最终输出应逐字节等于 `VERIFIED-02.stdout.json`，stderr 为空。`VERIFIED-01` 是增加 console 连续切片交叉核对前的成功历史结果，保留但不作为最终冻结证明。

完成条件仍包括实际 Intel drain 因果、原条件体的充分可见性与相关完整原 CI。下一步应保持原物理断言/2秒与5秒预算/完整 roster，先让现有按会话观测在成功时也可读，再按具体失败数据决定产品修复；不能靠增加等待、重新解释 expected 或把某次绿色结果当作原因分析完成。本代理没有 dispatch、rerun、cancel、native driver 调用、资源轮询或 ref 更新。
