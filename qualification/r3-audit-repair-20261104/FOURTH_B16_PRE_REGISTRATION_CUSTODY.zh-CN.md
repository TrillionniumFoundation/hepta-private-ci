# B16：SQLx 注册前取消与 custody 边界

**结论：在固定 SQLx 0.9.0 的现有连接、连接池公共接口上，不能完成要求的原生连接全生命周期持锁；该缺口保持 OPEN。** 本轮没有依赖 fork、生产补丁、原生执行或 ref 变更。

这份结论限定于当前私有连接池及受审接口，不宣称另写 VFS、驱动或进程系统在理论上不可能。后者需要独立设计与资格，不能算成现有接口已经提供的能力。

**范围澄清：** “不 fork 依赖”来自 parent `/root` 对上一阶段公共 API 研究的明确任务约束，不是用户永久禁令，也不是自动审批拒绝。Root 现已另行授权准备最小 native lifetime-token 静态补丁和真实因果控制；仍不授权修改 native/ref 或发外部 PR，依赖取得和真实锁生成仍由单一 CI 执行者后续处理。

机器报告：Git blob `da59ec79283bd997502cd57590ce416ca4e4851c`，38399 字节，SHA256 `8196dd779711c25cfdf125cd04bb1cdb60d825f7874e411fc55b1dfe35b42fd1`。

## 1. 固定身份

- 当前项目锁定 `sqlx/sqlx-core/sqlx-sqlite 0.9.0`、`libsqlite3-sys 0.37.0`；锁对象为 `71fc8fa78b5afa076835b29790a5e6b0bd772558`。工作区启用 `sqlite-bundled`。
- 本轮直接解析了上游 `v0.9.0` 标签，确指向 [75bc0487eb661da811bb7a3c5d158f1bd463fef4](https://github.com/transact-rs/sqlx/tree/75bc0487eb661da811bb7a3c5d158f1bd463fef4)。
- 12 份固定主源均按完整 UTF-8 字节重新核对 Git blob 和 SHA256。没有把主机 Python 或系统 SQLite 版本当成实际 SQLx 运行时版本；没有在此轮拆取 registry crate 或原生缓存。

## 2. 缺口发生在哪里

| 阶段 | 已核实现 | custody 所处位置 |
|---|---|---|
| 生成参数 | `EstablishParams::from_options` 只复制普通参数；线程命名回调立即求值成字符串 | 捕获的应用对象未进入 worker |
| 启动线程 | `ConnectionWorker::establish` 把参数移动到实际标准线程，然后调用原生 open | 没有应用 guard |
| 原生打开 | `ConnectionHandle::open` 调用 `sqlite3_open_v2` | 无公共入口交接 guard |
| 初始化 | `ConnectOptions::connect` 先等待建立，再执行初始 PRAGMA | 仍早于可用注册点 |
| options collation | PRAGMA 成功后才注册 | 对前面阶段太晚 |
| pool after_connect | 完整 driver connect 成功后才调用 | R2e3 的注册后持锁从这里开始 |

对应原源是 [options/connect.rs](https://github.com/transact-rs/sqlx/blob/75bc0487eb661da811bb7a3c5d158f1bd463fef4/sqlx-sqlite/src/options/connect.rs)、[connection/establish.rs](https://github.com/transact-rs/sqlx/blob/75bc0487eb661da811bb7a3c5d158f1bd463fef4/sqlx-sqlite/src/connection/establish.rs) 和 [connection/worker.rs](https://github.com/transact-rs/sqlx/blob/75bc0487eb661da811bb7a3c5d158f1bd463fef4/sqlx-sqlite/src/connection/worker.rs)。机器报告保存逐项行段、对象和推论。

另一个必须处理的来源是 **连接池自己的 acquire deadline**：[pool/inner.rs](https://github.com/transact-rs/sqlx/blob/75bc0487eb661da811bb7a3c5d158f1bd463fef4/sqlx-core/src/pool/inner.rs) 会对 driver connect 加 timeout。因此只让外层任务继续存活、屏蔽调用者取消，仍不能证明没有内部 connect 取消。SQLite 的 `close_hard` 也只是丢弃 wrapper 后返回，没有等待真实 worker 关闭确认。

## 3. 现有接口为什么不够

`thread_name` 只把计算后的字符串传入线程；把 guard 藏在命名闭包中不会交给 worker。`collation` 和 `after_connect` 都太晚。`lock_handle` 只能用于已经拿到的连接。`connect_lazy_with` 只是推迟调用同一打开路径。

给 `SqlitePool` 套自定义 `ConnectOptions` 也不能透明解决：`SqliteConnection` 的关联 Options 类型已经固定。自建 VFS 或全局扩展不是现成的每连接 ownership hook；它们还引入未开成功、未调用回调、注册表清理和共享 SQLite 状态的完整新责任。本轮不走这些未经验证的路径。

## 4. 可继续的最小实现方向

需要依赖层明确支持一种**可选的、仅表达对象生命周期的 token**，从 options 在启动线程之前送入 EstablishParams，再由真实 ConnectionHandle 从 open 前开始持有。默认值为空，既有调用行为不变；它不表达 Current、授权、租约或写许可。

最小受审闭包是：

1. SQLx options 增加明确的可选 ownership token。
2. EstablishParams 在创建线程前接收它，并交到实际原生 open。
3. ConnectionHandle 在成功的 `sqlite3_close` 之后才释放它；若原生 close 返回错误，必须保持持锁并保留错误，不能在 panic/unwind 时释放唯一 token 而留下活连接。
4. 依赖自己的原生因果控制证明这些分支。
5. 依赖能力经正式接受并固定版本、真实生成 Cargo/Bazel 锁后，才在 Hepta 两个显式 guarded/coordinated 构造器中接入现有真实 OpenGuard。默认构造器、提交否决钩子、目录保护和错误传播不改。

本报告完成的是可审设计；没有创建本地 `[patch]`、vendored fork，也没有向外部仓库提交或发送请求。后续最小依赖层静态补丁已经得到 Root 单独授权，将作为新的可审批次准备；当前 API 本身并未因此具备该能力。

## 5. 必须实际运行的四类控制

- **原生 open 中取消：** 在依赖自己的真实打开路径建立确定性门，取消调用者后，由独立自有进程竞争原锁。真实 worker 仍活着时必须拿不到锁；实际关闭结束后才成功。
- **初始 PRAGMA 中取消或内部 timeout：** 使用真实 SQLite 操作与可核对的阶段同步，不能用取消 future 返回作为关闭证据。
- **增长与替换连接：** 覆盖初次成功后新开连接、借出连接、关闭取消及最后一个原生 owner 的销毁。
- **错误和 busy close：** 保留原错误；未确认关闭时必须继续持锁。忙关闭分支在自有隔离进程中验证并完整回收，不能留下未归属子进程。

以上都尚未实现、尚未运行。不能用 Arc 计数、一个析构回调或日志标记单独替代实际文件锁竞争与原生关闭证据。

## 6. 与 R2e3 的关系

R2e3 manifest `6985c5154f8f6c7ae42f94fd4d569dc6a1dab3b2` 和 patch `5b5a2dee4b33b5946ec21825ed7fc916487a0bf9` 仍只覆盖成功注册之后的连接 custody。它已经写明初始化缺口；本报告没有扩大其资格。Current 认证、精确 checkpoint、每次最终使用、独立 shared-open 和正常 Root/Agentd/Desktop 联合入口仍分别开放。

## 修订记录

上一版 JSON `b3b65a1bdbc9caa78adad0319063a49aa2cbb179` 和 Markdown `3625ce3995e03a632ef272cc55a10b4c077c26ef` 保留。此版只澄清研究阶段约束的来源及后续授权，不改变固定源码事实或资格状态。
