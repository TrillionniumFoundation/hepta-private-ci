本页从冻结 README 派生，仅将包内相对链接改为恢复路径文字；原字节 README 完整保存在无损包中。

# B15：holdout 文件锁生命周期候选与因果边界

## 结论

当前结论为 **STATIC_CANDIDATE_READY_FOR_INDEPENDENT_REVIEW**。可以确认一个具体的生命周期缺口：锁由 `File::try_lock` 成功取得后，原实现只保存 `File`，在 store 销毁或构造失败时依赖关闭该句柄；如果同一打开文件仍有重复或继承的句柄，单次关闭不能保证立即释放锁。候选使用私有 `FileLock(File)`，在成功取得锁后立即建立所有权，在其 `Drop` 中调用 `File::unlock`，使正常销毁和所有后续构造错误都尝试主动释放锁。

**原 Mac ARM 失败的具体持锁者、句柄来源和调度时间线仍未知。** 本地受控实验验证了重复句柄机制，未重现原 Mac 运行，不能据此宣称原失败已经归因或 B15 已闭合。候选尚未编译、执行项目测试或经过 rustfmt；当前执行环境没有 `rustc`、`cargo`、`just`、`rustfmt`。没有修改 ref、PR 或触发 CI。

## 固定源与候选身份

基线 source 为 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`，完整 tree 为 `3982ba56dc5a3f1da0c1de7ea57992f88125c359`，共 10,582 个 leaf。候选仅改变两个现有 leaf，完整 tree `7c18622c5c1b69826f7103dd2b2fec5bf572ae3a` 已实际 create 并 GET 根的全部 53 项，根 Git 对象重算与完整 Merkle 投影相等，其他 10,580 个 leaf 完整保持。

| 路径 | 原 blob | 候选实际 blob | 候选字节 |
| --- | --- | --- | ---: |
| `codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs` | `d496f6865d39e98d7b92ed62ebf130945cd8266c` | `603d36b01f6f8fe7472c72588e793f8ef169a08b` | 16,163 |
| `codex-rs/hepta-intelligence-eval/src/fenced_holdout_file_tests.rs` | `e6cb964c82d7aea02acae338c739ac1e5158dd3a` | `2c451a3c110288ca06eb43724329c48c39bb8f1e` | 13,010 |

两个 postimage 已通过 `create_tree(content)` 物化，并按预期 blob SHA 全量 GET，与候选 UTF-8 字节完全相等。三个原源码（含 owner）也完成直接 full GET 对照。无引用的两文件物化 tree 为 `4f67a90fa4a9526910dfc1761df61cd28847c135`；它只包含这两个文件，**并非**完整仓库候选 tree。实际登记原件（恢复包内 `authority/source-and-candidate.actual.json`）记录了这一差别。

`fenced_holdout.rs` 原 owner blob `b46cb572492afa8646b92e5213ce9c47a4feaf7d` 完整保持。私有守卫具有 `Drop`，外层 `FencedFinalHoldoutOwnerV1` 和 `LockedFileFinalHoldoutCasStoreV1` 都没有新增 `Drop`；原 `into_store(self) -> S { self.store }` 继续移动整个 store，不从带 Drop 的守卫移出内部 File。

## 原失败原件

复用已封存的 main 原完整 Bazel 上下文，不重新下载或执行：run `42123581385`，job `127679861749`，平台 `macos-15` / `aarch64-apple-darwin`。原日志记录 macOS 15.8.2、build 24H232、image `macos-15-arm64`。实际 checkout 为 PR merge `b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae`，tree 与 main67 完全相同。完整 decoded job log 为 983,417 B，SHA256 `b5f1fd02ed8a83328f500126cced6f23c196f3f69d48b0df5749ab039ddca884`。

原 artifact `13474454125` 的 ZIP 为 9,513,207 B、69 成员，SHA256 `15f4d85a07e2b135c8ebd6bd05fe32e63ed615e7e5073f9bcd85270af10848f1`。本包直接从已保留 ZIP 比较并复制其 manifest，以及 `failed-test-logs/invocation-fw7e1rzb/targets/0000/{test.log,test.xml}`。`0000` 是完整 `//codex-rs/hepta-intelligence-eval:hepta-intelligence-eval-unit-tests`，`0001` 是另一个 HTTP client 目标，未混计。原 ZIP 的全部其他成员与 compact 仍由原 main92 包保存；本包只保留本次必要原件及明确标注的 compact 投影。

该目标实际 **114 passed / 1 failed / 0 ignored**，0.59 秒；失败是 `longer_divergent_history_cannot_skip_the_retained_minimum_prefix` 的最终原断言，实际 `Some(Busy)`，预期 `Some(Rollback)`。测试输出中另有两次过滤后的 child `1 passed`，它们属于原父用例的子进程控制，不能加入 115 个父用例分母。

原 compact 投影的 TestRunner sequence 32540：`darwin-sandbox`、`cache_hit=false`、exit 101、`timeout_millis=300000`。sequence 32594 是独立 XML generator，`darwin-sandbox`、非缓存、exit 0，其输出 digest 与完整原 XML 的 11,957 B/SHA256 `d1e9df2ad7030acef328ea4d9b983fbd84b88d847d276b84864310d3081978e0` 对应。XML 是 Bazel wrapper 的一个错误 testcase；115 个 Rust 父用例与 114P1F 来自原 test.log，不能把 XML wrapper 计数说成每个 Rust testcase 的结构化结果。

原件来源及 ZIP 成员比对（恢复包内 `evidence/provenance.json`）、原失败完整 test.log（恢复包内 `evidence/original/artifacts/artifact-13474454125/failed-test-logs/invocation-fw7e1rzb/targets/0000/test.log`）、选定 compact 动作（恢复包内 `evidence/holdout-compact-actions.selected.json`）保留了各自的证据范围。

## 官方源码与机制

1. 固定 Rust 1.95.0 的 [File API 源码](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/fs.rs)中，`try_lock` 文档明确区分“所有重复/继承句柄关闭”与显式 `unlock`。本包完整保留正文及原 GET，见 `primary/rust-1.95.0-fs.rs`。
2. 同版本 [Unix fs 实现](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/sys/fs/unix.rs)在 `target_vendor="apple"` 使用 `flock(LOCK_EX | LOCK_NB)`；`unlock` 使用 `flock(LOCK_UN)`。文件打开包含 `O_CLOEXEC`。这不表示在 fork 后、exec 前该句柄已关闭。
3. [Apple 官方 flock 手册](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/flock.2.html)说明 dup/fork 对同一锁增加引用；通过一个引用显式解锁会影响共享该锁的其他引用。该手册是官方归档文档，不冒称对应当前 runner 的精确内核版本。
4. 固定 Rust 1.95.0 的 [Unix Command 实现](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/sys/process/unix/unix.rs)首先尝试 `posix_spawn`。原 crate 的三个 `Command` 调用未设置 uid/gid、pre_exec 等 fallback 条件，不能笼统说它们必然使用用户态 fork。
5. 补充读取 Apple OSS `xnu-11417.140.69`，实际 tag 指向 commit `43a90889846e00bfb5cf1d255cdc0a701a1e05a4`。其中 [kern_descrip.c](https://github.com/apple-oss-distributions/xnu/blob/43a90889846e00bfb5cf1d255cdc0a701a1e05a4/bsd/kern/kern_descrip.c)以 fileglob 为 flock 身份，`fg_drop` 最后引用才调用 close；`fdt_exec` 处理 CLOEXEC；[kern_exec.c](https://github.com/apple-oss-distributions/xnu/blob/43a90889846e00bfb5cf1d255cdc0a701a1e05a4/bsd/kern/kern_exec.c)与 [kern_fork.c](https://github.com/apple-oss-distributions/xnu/blob/43a90889846e00bfb5cf1d255cdc0a701a1e05a4/bsd/kern/kern_fork.c)展示 spawn/fork 的进程及文件表复制阶段。这是固定官方实现的机制支持，未证明原 15.8.2 runner 采用完全相同内核源码，更未提供原失败时的 FD 跟踪。

## 实际执行的受控实验

`mechanism/duplicate_fork_probe.py` 仅使用本地新建私有文件和自己 fork 的子进程。每个子进程有明确握手、释放管道和有限的自清理等待；没有发现、查询或操作其他 native 会话。实验在 Linux x86_64 / kernel 6.18.57 执行，4 个用例全部满足预期，exit 0、stderr 0。

| 保留引用 | 父持有者动作 | 引用仍存活时的独立 try_lock | 最后引用关闭后 |
| --- | --- | --- | --- |
| `dup` | 只 close | WouldBlock | Acquired |
| `dup` | unlock 后 close | Acquired | Acquired |
| fork 后、exec 前的 child | 只 close | WouldBlock | Acquired |
| fork 后、exec 前的 child | unlock 后 close | Acquired | Acquired |

fork 两例均实际确认 parent/child 的 FD_CLOEXEC 为 true。它们刻意延长了 pre-exec 窗口，证明该机制可以发生；没有模拟原 `posix_spawn` 内核时序，也没有执行项目 Rust 测试。完整输出见 probe.stdout.json（恢复包内 `mechanism/probe.stdout.json`），执行记录见 execution.json（恢复包内 `mechanism/execution.json`）。

## 变更边界与回归

生产变更只建立 File 的锁所有权：`acquire` 先保留原 binding、regular-file 和 `try_lock` 检查；只有成功取得锁才返回 `FileLock`，两构造函数立即持有它。此后没有用裸 File 穿过守卫空档。构造错误的原错误类型、文件格式、header/checksum、最小 anchor、fence、CAS、append/fsync、容量限制和 poison 逻辑全部保留。静态逆变换能够逐字节还原原生产文件，完整 patch 正反应用也逐字节相等。

守卫不实现 Clone，没有增加文件句柄或共享 owner。锁仍为原非阻塞 `try_lock`；没有新增等待、sleep、retry 或放宽 Busy。Drop 不能返回错误，因此显式 unlock 的 OS 错误与原 File close 一样不能成为新的成功回执；随后仍关闭 File。若 OS 拒绝 unlock，仍可能 Busy，候选不承诺所有平台或异常情况下释放永不失败。

原 `fenced_holdout_file_tests.rs` 的全部 10,243 B 为新文件完整前缀，原三个用例及全部 Busy/Rollback/child 控制没有改变。追加三例：

- store 经 owner 的 `into_store` 移出后仍维持 Busy，drop 后即使 duplicate 存活也可以按原 anchor recover；新持有者仍维持互斥。
- `create` 在已经有内容的文件上仍返回 AlreadyInitialized，同时不让 retained duplicate 延长该失败调用的锁。
- `recover` 在空文件上仍返回 MissingHeader，同时允许新的正常 create，并保持新持有者的 Busy 控制。

三个新增 Rust 回归尚未执行，仍需要原平台、原完整目标和正常项目门验证。所有原 test budget、目标、feature/dependency、并发配置保持；没有为了收绿色删除或重跑单一原用例。

## 完整调用检查与复核方式

从实际 B21 source archive 扫描全部 4,832 个 Rust 文件，按四个固定类型/控制变量字面量得到 112 个匹配行、11 个路径；完整结果在 callsite-search.json（恢复包内 `authority/callsite-search.json`）。49 个保留的源文件全部与 main67 的固定 Git leaf 一致。具体 File store 的实际构造调用在原独立测试文件，另一个外部 API contract 只引用其函数项；generic product owner 不因此被声称已经部署了该适配器。原 File store 不实现 Clone，File 字段私有；其他 `.clone()` 的内存 CAS fixtures 不属于该锁句柄。

在恢复目录运行 `python verify_candidate.py` 可离线复算完整 Merkle、49 源身份、8 份 primary GET、3 原源与 2 候选实际 GET、全部 ownership 逆变换、两个路径正反 patch、原件和机制记录。它不会执行项目测试或 OS 机制实验。需要重放完整调用搜索时，额外传 `--source-archive /path/to/source-head.tar.gz`；已执行的作者验证包含该完整扫描。最终执行记录与 stdout 保存在 `static-final.*`；较早的 `static-01.*` 与其原 verifier 另保留为历史。

下一步需要独立源码审阅、根审和正常 PR 自动门。即便未来单次原平台通过，也只证明该候选在该上下文的结果；原 Mac 失败若要精确归因，还需要实际竞争句柄或可对应的时间线，不能由本包的机制实验倒推。
