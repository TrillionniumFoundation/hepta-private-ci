# Memory 真实租约到期测试修复候选 V2

状态：源码与合同静态核验完成；未编译、未运行 Rust 或原生测试。候选只改原测试文件的一处用例，生产租约实现、依赖、BUILD、工作流与外层执行预算均未改。

## 实际故障与合同

固定产品源为 `5b6331250ff459033bd44d1a95daec70131277cc`。Windows 原 job `127339256007` 中，`local_development_owner::tests::explicit_owner_expires_bound_lease_and_fences_old_witness` 在首次 `append_intent(...).await.expect("intent")` 报 `Lease(StaleFence("local lease has expired"))`。所属原第一分组为 79 PASS、1 FAIL、20 filtered；后面的 20 项是另一原分组，日志尾部重印不是重试。原错误之后的到期回滚、幂等回放、旧 witness 拒绝和新 generation 断言均未执行。

原测试在完整 `CognitiveStore::open` 之后才采集实际 `SystemTime`，因此主 store 的目录准备、migration 和初始完整性校验并没有占用这一秒租期。采时之后仍有租约写事务、bound executor 的写事务与读事务、首次 intent 的写事务。生产代码在 intent 事务中重新核对真实到期时间；观察到的拒绝符合该生产检查。原记录没有这些事务的分段时间或初始时钟小数部分，不能进一步指定宿主负载、某次 I/O 或某个事务为唯一原因。

`LocalLeaseBinding::new` 接受调用者提供的非零 Unix 秒到期时间；`expire_local_lease` 要求正确 store、显式绑定和真实到期，再委托原单事务 `expire_lease`。其合同没有要求一秒租期。这个用例的业务检查是先成功写入 intent，再真实到期，并拒绝旧 executor/lease witness。原 `+1` 与 `120 × 25 ms` 是该测试自行选择的准备窗口和轮询方式。已读模块设计文档和原 B16 退出合同也不把它们设为产品时延指标；本修复仍不授予真正 Current、Root 或生产调用接受资格。

## 精确改变

| 项目 | 原测试 | 候选 |
|---|---|---|
| 采时与调用顺序 | store 完整打开后采真实时钟，再获取租约、打开 executor、写 intent | 顺序和全部生产调用原样 |
| 首次租约期限 | `floor(now_seconds) + 1`，无时钟跳变时剩余 `(0, 1]` 秒 | `floor(now_seconds) + 10`，剩余 `(9, 10]` 秒 |
| 到期等待 | 最多 120 次、每次 25 ms 的真实时钟轮询 | 同一 25 ms 轮询，包在 12 秒 Tokio timeout 内 |
| 到期判断 | 实际 `SystemTime >= expires_at` | 同一个判断，原最终断言逐字保留 |
| 后续行为 | 正确 store 回滚、相同终态回放、旧 executor/lease 拒绝、新 generation 2 | 所有调用及 10 个原断言逐字、同序保留 |
| 项目执行范围 | 原 Windows Bazel owning target / 原分组 | 不改目标、原测试名字、过滤、重试或外层预算 |

10 秒是有限的 fixture 初始化余量，不是新增产品 TTL，也不是已测得的 Windows 最坏执行时延。它消除“必须在下一个整数秒边界前完成多次真实事务”的隐含测试要求；若实际事务仍停顿超过这个窗口，原生产检查会继续拒绝并使测试失败。

12 秒只约束新增的到期等待 future。轮询继续读真实 `SystemTime`，Tokio timer 没有暂停或推进，未使用 `expire_lease_at_unix_seconds` 等覆盖时钟入口。若时钟回拨或始终没有观察到到期，timeout 会使测试失败；已有最终真实时钟断言继续执行。该时限受运行时被调度的条件约束，不是整个测试或宿主停顿的物理硬时限。正常无时钟跳变时，从采样到租约到期最多约 10 秒，已经消耗在真实事务及第二 store 准备中的时间不会再次睡满 10 秒。

## 静态证据与下一道真实门

候选包含一条路径、17 行新增和 11 行删除。云端隔离 Git 目录中，完整正向和反向 `git apply` 检查、应用均成功。恢复两个修改区域后，整个文件与固定原像逐字相等；用例之外的全部字节、文件中的五个原测试名字、该用例的 10 个断言均精确保留。Tokio `time` feature 已是该包现有依赖，无需改 Cargo/BUILD 或生成锁。

必要验证仍是当前候选在原 Windows MSVC owning target `//codex-rs/ext/hepta-memory:hepta-memory-unit-tests` 的真实完整运行，保留原 wrapper、原目标分组与错误退出。需看到这个原同名用例到达全部既有断言并 PASS、整个 owning target 正常终态、无所选跳过或额外重试。Linux 或单独编译通过不能替代这道 Windows 门。原失败完整日志永久保留，修复候选不会将旧失败改标为通过。

此前 V1 诊断候选仅为历史，没有被应用、编译或运行；本 V2 直接基于原 5b 文件，没有纳入那些诊断输出。先前将一秒视为不可调整的约束已在本次合同审查中更正。
