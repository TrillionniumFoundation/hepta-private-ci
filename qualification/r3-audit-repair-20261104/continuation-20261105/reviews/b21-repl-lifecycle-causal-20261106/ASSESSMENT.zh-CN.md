# B21：REPL、stdin EOF 与 PTY 生命周期只读因果复核

## 结论

**B21 保持 OPEN；现有证据不足以选定新的产品修复。** 固定源码没有显示本次大输入测试存在“关闭队列后提前发 EOF”的顺序违约，也没有显示 Python 3.14.7 的常规 PyREPL 启动必然清空早到输入。原测试已经校验实际执行标记，并在看到提示符后允许一次补发，不能把“输入回显即就绪”的旧缺陷重新当作本次原因。

8075 的原 Intel 工作流新增了一个重要反证边界：原 PTY 目标仍为 **27 passed / 4 failed**，没有取得完整通过；该次 dropped-receiver 截止快照为零读取，和 84cc 原件中持续读出、丢弃 2,050,048 字节的失败阶段不同。优化消除了源码可证明的冗余分配/失败发送，但原超时根因仍未确定。所有原断言、31 个测试、两个 backend、2 秒/5 秒预算保持原样；本次没有运行产品、原生测试或 CI，没有更改 ref/PR。

## 1. 固定来源与两个观测切点

| 项目 | 84cc 原诊断 | 8075 原正常 PR 工作流 |
|---|---|---|
| source head | 84cc73453eb926d6f2c5b0372c0287b0ab86ed53 | 8075eb367b6e97546af206b27bbf4a3a867497c8 |
| 本次绑定树 | 45858bc96c0edbc366ec77991646b15971129975 | c1249a173ac346d0f1230fe56451b97d4e13c601 |
| checkout 身份 | 原诊断 source-head archive；产品叶等于 67cc | 原 job 的 git log 完整返回 b88f625afe17975db80b152283ef2e19cc50e41f |
| PTY 目标 | 28 passed / 3 failed，31 cases | 27 passed / 4 failed，31 cases |
| 大输入 EOF | ready 后 5.509082585 秒，后续输出 0，未观测到退出 | ready 后 5.001346858 秒，后续输出 0，未观测到退出 |
| preserved-FD bare REPL | 5.002924503 秒未就绪；回显及 Python 3.14.7 banner，没有提示符/执行标记 | PASS；原强制清空输入的 readiness 控制也 PASS |
| dropped receiver | portable；读取/丢弃 2,050,048 字节、4,002 次 read，截止 2.13193564 秒 | portable；spawn 651.527851ms，等待 2.004870616 秒；read_calls/read_bytes/discarded_bytes 全为 0 |
| 全 job | 见已登记原 v3 终态包；不由本评估扩大资格 | CANCELLED；末尾只有 operation canceled，取消原因 UNKNOWN |

84cc 的十份 PTY 源文件已从原 source-head.tar.gz 提取，并逐叶核对原 67cc 完整树。具体身份见 source-map.json。关键原测试正文 Git blob 为 **25836a08f9ff9a90b14204059d2544749a0f5461**；原 unix_io.rs 为 **67168dab510c9fd400a1cbcf4b4a6bb905b73c59**。

8075 的实际完整源码为 **c7ad412d04fd3f5505259a4afdcec0d4d8562a88**，只在该文件插入 406 字节；移除插入即可还原完整 67cc 文件。此次复算 67cc 的 10,582 叶及单叶替换结果，得到实际树 c1249a；其余 10,581 叶不变。source-ancestry-proof.json 保留全部受影响目录的直接条目和未变兄弟节点，可独立重放改变路径的 Merkle 根。8075 commit 的 parent 为 67cc；实际 merge 的父序为 [67cc,8075] 且同树。原 publication 工具回执与此次 job checkout 相互绑定，不把 source head 冒充 PR merge checkout。

完整 8075 job 日志 Git blob 为 **45ebf709bb26caf683357ac980e79686c5939d82**，UTF-8 字节数 1,093,592；本目录只保存原第 1821–1894 行的完整 PTY 段，Git blob **c957810fa501ffad04108331bab503ee0eec493a**，6,241 字节。完整原件由 donor 终态包另行保全，本评估不重复打包大日志或 ZIP。

## 2. close_stdin → 队列耗尽 → SendEof 的真实顺序

原 tests.rs 的大输入例先在子进程清除 ECHO、输出 ready 后等待 ready；随后把 37 字节一行重复 32,768 次，即 **1,212,416 字节**，作为一个消息排队。Rust 侧显式丢弃外部 writer clone，再调用 session.close_stdin，释放会话内部 sender。此例传空 inherited_fds，进入 portable backend，选择 SendEof。

process.rs 的 close_stdin 释放 sender，不会中断正在写入的消息。unix_io.rs 的 writer task 对每个 recv 得到的消息先完成 write_all；write_all 会推进部分写入并继续等待可写。只有 recv 不再返回消息，才进入 SendEof。这里必须区分 **消息成功入队** 与 **所有字节已写入内核**：测试开始 5 秒收集计时前只完成了入队，原日志没有后者的完成时间。

SendEof 仅在 tcgetattr 成功且当前 VEOF 非零时，尝试一次写入“一个换行加一个当前 VEOF 字符”。没有发送两个 EOT，也没有在本次 FIFO 数据写完之前发送。原 Python 断言要求读取结果在原 payload 后恰好多一个换行；多发控制字符、改 buffer 或改变断言不是这里获准的修复。

子脚本只改 ECHO，没有清除 ICANON，也没有修改 VEOF。两个 openpty 路径都没有传入显式 termios 初值；原 trace 未记录实际 ICANON、VEOF、tcgetattr 返回值或 EOF 写入结果。因此可以证明代码顺序，**不能证明这次运行确实执行并完成了 VEOF 写入，也不能仅凭输出 0 推断 EOT 次数错误**。

已有明确的可观测性缺口：

- payload 写入错误会使 writer task 直接返回，不进入 SendEof；
- tcgetattr 失败、VEOF 为零和最终 EOF 写入失败都没有进入现有失败快照；
- 该 Python 脚本在 read 完成前不会打印逐段进度，所以输出 0 不表示子进程读取了 0 字节；
- has_exited/exit_code 是 waiter 维护的会话状态，false/None 表示尚未收到退出观测，不能单独证明当时 OS 子进程仍处于哪一种状态。

preserved-fds backend 选择 NoEof，是另一个明确源码事实；**本次大输入例走 portable/SendEof，失败的 REPL 又尚未调用 close_stdin**，因此不能用这个差异解释上述两次失败。

固定 [portable-pty 0.9.0 原源码](https://docs.rs/crate/portable-pty/0.9.0/source/src/unix.rs) 中的 Unix writer drop 也采用换行加当前 VEOF。本项目保持该既有策略，并不等于已经证明实际 Darwin 终端状态符合某个假定值。

## 3. REPL 握手与 Python 3.14.7

原 helper 在 5 秒 deadline 内先发一次拆开的 print 表达式，只有实际输出完整 readiness marker 才成功。回显不包含完整 marker；发现字面提示符后最多再发一次。它没有定时循环重发。原库还已有一个严格回归：先看到回显但不能就绪，子进程经 gate 释放后明确清空终端输入再 exec bare Python，最后必须由实际执行标记就绪。该回归在这两个原目标记录中均 PASS。

本次取得官方 v3.14.7 annotated tag，固定到 **823f0323ee6ec1402088b73bce1a38473cac36dc**，全文核对十份 CPython/Bazel primary 文件。原 banner 版本与该 tag 对应；这不是 runner Python 二进制的构建来源认证。

在该固定 CPython 源码中：

- [Unix console](https://github.com/python/cpython/blob/823f0323ee6ec1402088b73bce1a38473cac36dc/Lib/_pyrepl/unix_console.py) 的常规 prepare 通过 TCSADRAIN 改终端模式，不使用 TCSAFLUSH。
- [Reader](https://github.com/python/cpython/blob/823f0323ee6ec1402088b73bce1a38473cac36dc/Lib/_pyrepl/reader.py) 的 readline 先 prepare、再刷新提示符、再处理输入；清空的是自身编辑 buffer，不能等同于清空内核输入。
- [HistoricalReader](https://github.com/python/cpython/blob/823f0323ee6ec1402088b73bce1a38473cac36dc/Lib/_pyrepl/historical_reader.py) 中找到的 forgetinput 调用属于结束增量历史搜索的命令，不是通常启动步骤；CompletingReader 没有另一个 prepare/forgetinput 覆盖。
- 原颜色处理在完整提示符字符串外包裹颜色控制码，没有把字面提示符的空格拆开。此次失败原 trace 本来就没有任何提示符，不能仅以颜色假设选择修复。
- [main.c](https://github.com/python/cpython/blob/823f0323ee6ec1402088b73bce1a38473cac36dc/Modules/main.c) 中 readline 导入在 banner 之前，startup/interactive hook/PyREPL 启动仍有 banner 后阶段。看到 banner 不能定位后续停在哪一层，也不能证明一定进入了 PyREPL 而非 fallback。

保留下来的原 Bazel action env 没有列出 TERM/PYTHON_BASIC_REPL 等键；固定 [Bazel 9.3.0 test-setup](https://github.com/bazelbuild/bazel/blob/e89755babf3e941bc1e9d8120b1cd48854ab9dfa/tools/test/test-setup.sh) 也未显式设置它们。这是 action 和 wrapper 的事实，尚不是 Python child 的直接环境快照。原 find_python 返回可执行名称，未保存最终解析路径；本评估不猜测哪个安装或交互配置承担了失败。

因此，“启动早到输入被新 PyREPL 必然丢弃”“默认提示符颜色令已有补发永不触发”“后台 FD 持有本身造成此 readiness 超时”均未获本次原件证实。保留假设可以，但不足以发布产品修复或关闭 B21。

## 4. 8075 后继原观察的边界

本次重算确认 8075 只让 reader 在接收端关闭时提前跳过分配和失败 send；writer、终端配置、测试正文、预算与握手均未改变。

其 dropped-receiver 快照是 waiting_for_read、读取计数为零、队列为零，child progress 仅到 python_started。这个 phase 文件写在构造/写入 4MiB stdout payload 之前，不能证明 payload 的 OS write 已开始。现有观测没有包含一次正长度读取后的优化行为。诊断字段使用独立 relaxed 原子，源码也明确不是整体原子协议快照，不能据此推导全部线程在同一瞬间的精确位置。

另外两个失败是 portable 和 preserved-fds 的 drop-detached-child 例，错误文本同为等待 PTY 输出超时。固定 helper 在显式 Drop 前有两个等待点：detached PID marker 和 input-ready marker；现有错误没有阶段标识，不能区分两者。可以定位到 **显式 Drop/运行时关闭断言之前**，不能称作“已经证明 Drop 或 runtime shutdown 挂死”。

该 job 的取消发生在上述 31-case 失败输出之后；日志没有说明取消执行者或具体触发条件。120 分钟上下的时间差不构成“已证超时取消”的依据。其他平台成功、后续某一个 REPL 用例成功、或优化的静态接受均不补足这个 Intel 完整目标失败。

## 5. 最小剩余观测与后续决定门

在保留原完整上下文、用例/断言/预算的前提下，下一阶段若由 root 授权一个观测候选，最小范围是：

| 要区分的假设 | 最少新增观测 | 仍不能冒充的结论 |
|---|---|---|
| 大输入仍在排队/部分写入，还是 writer 已错误返回 | writer 已取消息数、请求/完成字节、等待可写/错误码/结束状态；不记录输入正文 | 无数据不能选“再发 EOT”或扩大预算 |
| 已写完 payload 后，EOF 是否真正尝试/完成 | tcgetattr 结果、ICANON/VEOF、EOF attempt/result；原单个换行加 VEOF 不变 | 不能用零输出替代该协议阶段 |
| REPL 在启动、模式切换、提示符或读执行阶段停住 | 实际 Python 路径/版本及白名单环境存在性；初始 probe 入队/实际写入、reader 状态；必要时仅针对该 owned child 的阶段/栈观测 | 标签 Python 3.14.7 本身不是根因 |
| 两个 drop 例在何处超时 | 给现有两个等待点加固定阶段标签，不改变等待内容/时限 | 未到显式 Drop 不应归责 Drop 实现 |
| dropped-receiver 在 payload 分配/写调用前延迟，还是读取调度问题 | 在原 side channel 中区分 payload 已备好/写调用开始/返回，连同原 reader 快照 | phase=python_started 不能证明已进入内核 stdout write |

这些是可审阅的后续观测义务，不是本次已实施或已运行的补丁。若只补现有 PTY 诊断，优先考虑原 unix_io_diagnostics.rs、unix_io.rs 的 cfg(test) 观测和 tests.rs 失败阶段输出；不改变产品 stdin/EOF/任务清理策略，不引入新的 receiver、强 FD 所有权或隐式 wait。是否需要对子进程增加阶段观测，应由能解释上述缺口的最小设计决定，不复制大环境或敏感输入。

本次最终决策：**CAUSAL_UNKNOWN / NO_NEW_PRODUCT_POSTIMAGE / B21_OPEN / NO_LEDGER_TRANSITION**。

