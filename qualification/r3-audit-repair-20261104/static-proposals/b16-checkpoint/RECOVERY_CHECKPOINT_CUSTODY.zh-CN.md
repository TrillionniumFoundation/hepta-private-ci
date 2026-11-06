# B16：恢复 checkpoint 的真实连接生命周期缺口

**结论：已确认一个实际生产调用仍未携带资源 owner。** 已冻结的两个 pool 绑定包不覆盖这个独立单连接。此次分别准备了 2 文件生产候选和 3 文件测试候选；只有静态源码、差异与重建证据，没有编译、原生运行、依赖采用、锁生成或分支修改。

## 现有实际调用和取消风险

固定 `AgentdProductionWriterHost::open_with_recovery`（`production_writer_host.rs`，blob `f881d7c4d20a189d781977da09237f8c82dc4012`）实际调用 `CognitiveStore::open_with_recovery`。在 B 串行基础后的 Memory 源 `54e917f45520f6b0e31fcd6a2f57ac3a00d8ae6c` 中，恢复先核验外部 authority 和 current-cut 输入，再取得原 `CognitiveStoreOpenGuard` 的排他锁、从保留描述符形成私有副本、用 guarded pool 验证 schema、内容和 integrity。

验证 pool 关闭后，实际调用 `SqliteConfig::checkpoint_private_recovery_database`。该方法在 state 源 `27b123f6862ca4355da74ed4d1b21c7047b3b2df` 中另建普通 `SqliteConnectOptions`，连接之后执行原 `PRAGMA wal_checkpoint(TRUNCATE)` 和 `PRAGMA journal_mode=DELETE`，最后显式 close。它没有携带新 SQLx native lifetime token。

SQLx 原 worker 在 `ConnectionWorker::establish` 先创建独立线程，再由该线程执行 native open；在 Rust future 被丢弃时，线程可以仍在 SQLite 内。已有连接的命令同样由该线程执行。恢复 future 取消会释放它的原 guard、gate 和已关闭 pool 等 Rust 拥有者；取消不等于 SQLite 已经停止使用候选数据库。这个单连接没有 native owner，因此仅靠 caller 的词法 guard 不能覆盖该时间窗口。这里是固定源码所支持的生命周期缺口，**尚未有本候选物理负控结果**。

GitHub code 索引对 checkpoint 名称返回定义与 Memory caller 两个文件；对 `CognitiveStore::open_with_recovery` 返回 Agentd caller、原恢复测试及两份文档。索引实际对应 main `732e934ba496d90fbe042b8d41d479ef901643e5`；随后已把真实源码对应到固定 cabc 文件和 B postimages。这个索引不是 cabc/B 完整全树扫描，不能据它宣称没有任何索引外调用。

## 生产候选：强制传原 owner

`production-custody.patch` 仅有 2 文件、15 行新增和 3 行删除：

| 位置 | 改动 | 保留的合同 |
|---|---|---|
| state checkpoint 方法 | 新增必填 `Arc<dyn Send + Sync + 'static>`，在 `connect` 前传给 `connection_lifetime_token` | 原 options 的其他参数、5 秒 busy timeout、全部 SQL、busy 拒绝、journal-mode 精确判断、close 与错误优先级 |
| Memory 实际 caller | 传 `exclusive_guard.custody.clone()` | 原 File 和 Windows 目录 File 的同一个 owner；不重开路径、不造替代 owner |

不保留已知未绑定的兼容旁路。公共方法签名因此收紧；完整编译门必须发现任何索引外 caller，并逐个传真实 owner，不能用 `()` 或空 token 凑接口。普通非 Memory pool、只读冷镜像和其他未选择该 API 的路径没有因此获得 native custody。

本补丁不改变恢复 authority、current-cut 等式、提交判据、原 ACK、active pointer 发布顺序或 Current 构造权限。两处已冻结的 pool native 绑定完整保留。

## 独立控制：真实 Memory 恢复取消

`memory-physical-control.patch` 只注册一个新测试子模块、增加现有 workspace `libsqlite3-sys` 的 dev 依赖、添加一个选中父用例及其显式调用的 ignored 子进程支持。原恢复测试文件除模块声明外逐字不变。

父测试使用真实普通 libtest 子进程。子进程通过既有测试 authority 建立实际 `CognitiveStore`，捕获真实 anchor、关闭原 store，然后调用实际 `CognitiveStore::open_with_recovery`。测试 authority 只属于既有单元测试合同，不代表真实 Root/Session 或外部生产授权接受。

控制不依赖“第几次 open”或估计延时。SQLite 原生 `SQLITE_TRACE_STMT` 只有观察到精确的 `PRAGMA wal_checkpoint(TRUNCATE)` 才武装该连接的 progress callback；callback 实际进入后，丢弃恢复 future。Tokio runtime 和它的 worker 此时仍存活。父进程独立打开原 fence 文件并执行真实 `try_lock`，必须得到 `WouldBlock`；物理探针之后还要读到 `gate_status=0`，防止 callback 已超时或释放却被误认作缺失绑定的因果证据。

随后释放 native callback。测试分别观察该连接的 `SQLITE_TRACE_CLOSE` 和原 fence 真正可获取。`TRACE_CLOSE` 只标记 close 事件，**不当作 native close 已返回**；物理锁释放是另一项独立条件。所有新阶段的边界为 5 秒；没有增加原测试时限或更改任何原重试、skip、断言。子进程和读线程都有 owner，失败由父进程 kill/wait 后清理；没有孙进程。

对应负控只移除 checkpoint 的 native token attachment，并将相同 incoming owner 保留在普通 future local，直到该 future 正常完成或取消。实际 Memory caller、两个 pool 的 binding、依赖 API、原恢复校验以及全部测试均保留。负控必须实际达到准确 checkpoint callback、丢弃恢复 future、探测到原锁错误地可用，并在探针之后仍观察到 `gate_status=0`，才算因果失败。编译失败、setup 失败、没选中用例、不同阶段失败、callback 超时、其他文件锁错误都不算。

## 尚待执行的门

先采用经独审的 SQLx native-lifetime API，并按仓库原生成器生成真实依赖锁；此控制新添 dev-edge，因此本包没有伪造 Cargo/MODULE 锁。然后在同一精确源上执行负控、精确恢复、一个新父用例及原 Memory owning 范围。ignored support 不计为第二个通过用例。

原恢复模块有 10 个定义，其中 2 个受 Unix cfg 限制；其冷只读子模块另有 4 个 Unix 用例。源码上 Linux 应选中这些 14 个原用例和 1 个新父用例，必须以真实新 roster 确认，不能由静态计数宣布通过。还需保留原 sender/read-ACK、checkpoint interlock、state 和 Memory 全部 owning 门及平台资格。

新底层 callback ABI 已对照 `rusqlite/rusqlite` 的 `v0.39.0` 固定 commit `2a1790a69107cd03dae85d501dcbdb11c5b32ef3`（其 `libsqlite3-sys` 为 0.37.0），bindings blob `c892eefa6d15577af6379e39872420b9829903b7`。这只核 API；实际采用依赖的编译与运行仍未发生。SQLite 官方 [trace 事件](https://www.sqlite.org/c3ref/c_trace.html) 与 [progress handler](https://www.sqlite.org/c3ref/progress_handler.html) 说明这些回调的含义；没有以文档代替物理结果。
