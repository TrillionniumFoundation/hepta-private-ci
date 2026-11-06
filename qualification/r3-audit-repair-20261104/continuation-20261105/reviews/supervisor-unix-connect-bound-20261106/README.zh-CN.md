# Supervisor Unix 控制连接：独立连接阶段上限候选

本候选修复三个同步 Unix 控制连接在 connect 阶段没有调用者期限的问题。它不认定旧 `five_real_pairs_adopt_all_ten_children_and_isolate_one_matrix_crash` 的两次 60 秒 timeout 已找到根因；原失败的具体阻塞位置仍为 UNKNOWN。

## 唯一基线与三路径差异

固定基线为 source `ac18b623c7a6cb953b4660979e9b620fe7176bb2`、tree `c3e9ddc1799f470ac7c80e117ee953a7232847e0`，10,802 原叶。之后根已另行发布 aaf 后继；本候选保留 ac18 原基线，不默默更新 ancestry。未来组合时须由根重新核对父树与路径冲突。

| 路径 | 变更 | actual postimage |
|---|---|---|
| `codex-rs/hepta-supervisor/src/unix.rs` | 新增私有模块声明，只替换三处 connect；其他原字节由逆变换核实 | `84e4d339172fd49e527ae0317b9c127a09f8ad1d` |
| `codex-rs/hepta-supervisor/src/unix_connect.rs` | 201 行私有同步连接实现 | `9fbca2e7048c6d7af0a2ebad9eeacd1808862c95` |
| `codex-rs/hepta-supervisor/src/unix_connect_tests.rs` | 161 行、6 个新回归测试源码 | `b4a71f89805fa28226d74ef399ca65653759e0f5` |

预期并已实际物化的无引用 tree 是 `44e8f7176037a5455476c068ad6ad8d692868769`，10,804 叶，10,801 原叶不变。没有创建 commit、改 ref/PR 或触发 CI。三份 postimage 全文 GET 均与作者原字符串逐字相等；实际返回在 `authority/`，简明回执在 `candidate-postimages.actual.json`。

## 行为与兼容边界

三个入口分别为 agent health、Matrix health 和 agent drain。新连接阶段复用原 `HEALTH_PROBE_IO_TIMEOUT` 的值 200ms。原 read/write timeout 各 200ms、三次 adoption、失败间隔 50ms、所有 exact identity 校验逐字保持。200ms 是**新增连接阶段上限**，原代码没有共同的 200ms handshake 截止；本补丁也没有建立整个 handshake 或 recover 的总期限。

每次连接先计算单调 deadline、验证 pathname，然后创建自己的 AF_UNIX/SOCK_STREAM。创建成功立即交给 OwnedFd；之后任何错误均沿现有 I/O 错误路径返回，所有者关闭 descriptor。支持原 std 原子 CLOEXEC 的平台仍在 socket 创建时设置该标记；其他平台保留 fcntl 回退。Apple、DragonFly、FreeBSD、NetBSD 保留 std 使用的 SO_NOSIGPIPE。没有 fd clone、后台连接线程或逃逸 raw fd。

pathname 按固定 Rust 1.95.0 std 的编码构造：拒绝任意 NUL（包括开头 NUL），拒绝长度大于等于 sun_path 容量，使用平台真实 sun_path offset 与显式 socklen。空 pathname 保持 std 原编码。结构先全部清零；BSD/Darwin 的长度字段处理沿用所固定的 std sockaddr_un 实现，不混用 TUI 的另一套编码。没有新增 Linux abstract socket 支持。

连接 fd 先设为 nonblocking。EINPROGRESS/EALREADY/EINTR 才进入 poll 分支；poll 被 EINTR 打断时从同一个 deadline 计算剩余时间，毫秒舍入后短 poll 也不会重置期限。处理 POLLNVAL、SO_ERROR，并要求 peer_addr 表明已经连接。成功后恢复 blocking，再交回原 caller 设置 read/write timeout。操作系统调度或系统调用不可抢占部分仍不构成实时系统的绝对 wall-clock 保证。

Linux/Android AF_UNIX 的 EAGAIN 发生在监听队列满且连接尚未入队时；它原样返回，沿原 adoption 重试或后台 health polling 处理，不增加内部重试或睡眠。不能以 POLLOUT/SO_ERROR=0 虚构连接成功。原 drain 的 WouldBlock/TimedOut 分支仍表示未确认，不是 ACK；adoption 身份未证明仍 Rejected，不授予 signal 权限。

新 helper 返回 std::io::Error；原 health 路径的 ProcessDriverError::from(io::Error) 字符串化、adoption 布尔 proof 以及 drain 错误分类均保持。这里没有声称将原错误链改成新的结构化 API。

## 测试源码与本地验证范围

新增 6 个测试覆盖：自己创建的 listener 成功连接及 blocking/CLOEXEC、关闭 listener 的 ConnectionRefused、Linux 自有监听队列满时的真实 EAGAIN、已耗尽 deadline 不产生连接、pathname/长度/NUL 与 std 校验一致，以及自有 socket 持续不可写时 poll 使用原 deadline。测试不改环境变量，不操纵其他进程或 listener，不启动产品子进程。Linux backlog 场景有明确平台 cfg；poll 场景使用有限填充循环和原 200ms 值。

原 `unix_tests.rs`、`unix_drain_tests.rs` 和完整 `paired_process_product.rs` 未修改。原 paired 测试 blob 仍为 `c03bdba974ea48281cd839b9161eb0ccdc38b892`；保留两组 product 测试的全部 PID、generation、故障隔离、健康、关闭和时间预算断言。Bazel 的原 src/**/*.rs glob 已覆盖新文件，Cargo/BUILD/锁文件不变。

`verify_candidate.py` 是可移植 Python 静态 verifier，重算完整 base/candidate Merkle 树、全部固定来源和 primary 全文 GET 身份，重放 forward/reverse patch，核三处替换与原断言/参数的字节保全。运行：`python verify_candidate.py <候选根目录>`。`prepare_candidate.py` 仅保留作者生成记录，冻结后不需要运行它或覆盖冻结产物。

本地没有执行 Rust 编译、Rust tests、rustfmt、clippy、真实 socket 或 CI；不能把 Python 的源身份/patch 检查称为这些门已通过。正式接受还需要独立源码审阅与根负责的原适用门。新增参数注释遵照原 AGENTS，但实际 lint/格式资格尚未取得。

## 原证据与 primary

`historical-review/` 原字节复制先前只读短报告、FREEZE 和 86 叶适用性表；该历史 FREEZE 描述原独立目录的 104 个成员，本候选不声称这三份历史副本独自包含全部 104 个文件。完整原 native 包由 registry `23e67ce20a439e2968eb63ae4e9a74a214ccd081` 保全，不重复复制大 ZIP。旧 Ubuntu job `127755476318` 实际 checkout 是 4a，而非其 PR merge。

`source/` 保存本候选判断所需的当前固定源码，包括原 driver、三组原测试、相关恢复依赖及完整当前 Cargo/defs。`primary/` 保存 Rust 1.95.0 的 UnixStream/addr/socket 实现、Cargo 固定的 libc 0.2.191 Unix/Linux/Apple 声明、Linux v6.8 AF_UNIX 实现以及各原 GET 返回。Linux v6.8 用于固定机制依据，不冒充原运行机 kernel 版本。TUI 的私有 bounded helper 仅作为历史参考，没有引入 TUI 依赖或复制其 peer-owner 策略。

本候选限定为 `INDEPENDENT_CONNECT_STAGE_BOUND_FIX_CANDIDATE`，原 60 秒因果仍 UNKNOWN，没有 blocker 台账转换。
