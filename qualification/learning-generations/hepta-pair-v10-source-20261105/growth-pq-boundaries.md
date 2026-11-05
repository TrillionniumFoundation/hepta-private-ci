# Growth／PQ 融合边界：固定源码上的实现证据审阅

**结论：以下六处边界在本次固定源码上仍然存在；Growth 与 PQ 尚未在一个配置中融合。** 本文只记录已经读到的实现与已经执行的测试，不提出新的并行路线图，也不构成独立安全审计或发布资格。

- Chain：`04be5f02c84cf5cb626a53f34bc03a5bd6ff5137`，tree `d4f4a85c439982d8decec9265c1993408f3577cf`。
- Runtime：`d7c32f38ae1c3890e73ff48ef8ee725ba4e80c58`，tree `b79a4a4677b672a89cce53c9abe6f6c71810ee88`；其 [V10 源码选择器][runtime-source] 固定上述 Chain。Runtime 源码控件的通过不替代融合业务测试。

下列源码链接全部固定到该 commit；移动分支头及后续证据投递 tip 的区别见 [README.md](README.md) 和 [branch-readback.json](branch-readback.json)。

## 六处现存融合边界

| 边界 | 实际实现与其含义 | 固定源码 |
| --- | --- | --- |
| **1. 交易编码与大小** | `GrowthPacket::encode/decode` 都要求每笔交易为 159–2,048 字节，并调用经典 `pon_wire::Envelope::decode`；`requested` 也从该 Envelope 取得账户。已通过的 PQ ApplicationV6 真实交易测试明确断言交易大于 2,048 字节，使用配置绑定的 PQ packet 路径。当前 Growth packet 不能承载该交易或取得其 PQ 授权语义。 | [GrowthPacket][packet]；[Growth 请求／执行][growth-execution]；[实际 PQ 交易测试][pq-native-test] |
| **2. 区块时间未接入 PQ 准备路径** | `execute_observed_with_workers` 构造 `BlockExecution` 时写入 `timestamp: None`。M06 的 PQ 准备分支要求 `Some(timestamp)`，否则返回 `PQ2_HEADER_TIMESTAMP_REQUIRED`；该时间进一步用于签名的有效期检查。这是实参契约缺口。 | [Growth 执行][growth-execution]；[PQ 时间要求][pq-time]；`pq_accounts_v2::prepare_signature_metered` [实现][pq-signature] |
| **3. 配置与 genesis 绑定** | Growth builder 重写 `state_profile`、growth 参数、network、parameters 和 genesis。PQ `Profile` 保存 `ChainContext` 与配置摘要；`policy` 校验 network／parameters／完整配置，`context` 返回其已绑定 genesis。对现有 PQ 配置直接改这些输入会触发 `PQ2_CONFIG_CHANGED` 等拒绝，当前组合没有一个共同构造出的完整上下文。 | [Growth builder][growth-profile]；`pq_accounts_v2::Profile/config_digest/policy/context` [实现][pq-policy] |
| **4. 完整 PQ 授权历史与 Growth 部分账户视图** | Growth 从完整 working 分区加当前已验证 multiproof 中的账户构造 `view`，并通过 `AccountPointAccess` 限定账户读取。PQ `validate_state` 则从账户逐一验证授权 generation、nonce、SPKI 与各代 status，并要求每个 `pq-*` 行均属于该账户验证得到的集合。若 working 中保留了未被本包账户证明包含的已授权账户历史，其 `pq-*` 行不会进入该集合，直接使用现有验证器会触发 `PQ2_ORPHAN_AUTHORITY`；当前接口没有对应的 Growth 部分授权证明契约。 | [Growth view／账户访问][growth-execution]；`pq_accounts_v2::validate_state` [实现][pq-state] |
| **5. owner backend 与恢复 schema 分离** | `Node::open_selected` 要求 Growth profile 对应 `PermanentAccountGrowthV2`；PQ 账户 profile 又要求选择 `PqNetworkV2`／`PqContinuousV3`／`PqWitnessV4`，否则拒绝 `PQ_ACCOUNT_REQUIRES_PQ_NETWORK_OWNER`。Growth opener 传入的 `pq_network`、`pq_witness` 均为 `None`。现有 backend 与 schema 选择没有允许这两套 owner 同时成立。 | [StateBackend/schema][backend-schema]；[open_selected][backend]；[Growth opener][growth-opener] |
| **6. 服务身份与公开操作 profile 分离** | `PublicServer::with_native_growth` 明确要求 `!self.identity.is_pq()`。`ClientProfile::NativeGrowthV1` 允许操作 6–8；`PqHistoryV4` 允许操作 2／3，PQ 身份分支选择后者。因此当前普通 Growth listener 不能通过同一个配置成为 PQ 身份的 Growth 服务。 | [ClientProfile 与 with_native_growth][pq-service] |

第三项需要精确区分：Growth builder 的入口条件 `task_profile == continuity_v1::PROFILE` **本身不是“排除所有 PQ”检查**；[PQ ApplicationV6 配置][pq-task-profile] 同样使用 continuity profile。真正可见的阻塞包括上述密封配置／链上下文、backend 与服务身份约束，不能把入口条件解释成一个不存在的额外拒绝规则。

## 已修复的运行中 epoch 竞态

[`growth_activate_with_progress`][activation] 新增的两个操作是：先观察 `BeforeContext` 取消，再在取得 `BEGIN IMMEDIATE` 写锁后重查 `growth_guard`。这覆盖同 tip／较低 work 的 no-op 分支，避免它在未经重新验证的外部写入 epoch 上返回成功。[`growth_guard`][guard] 比较已审计的 `PRAGMA data_version` 与 schema；[冷审计收尾][epoch-audit] 为新 owner 建立相应的内存 epoch。

[新增原生测试][activation-tests] 使用真实 SQLite authorizer 在 BEGIN 准备阶段打开第二连接，两次实际提交恢复相同逻辑行但改变连接可见的数据版本；另一个测试检查已取消请求在任何 SQL 准备前退出，并保留原始错误对象。它们还检查事务回滚、精确行集合以及后续真实交易与冷重开。

**这项修复的边界是当前运行 owner 的取消和外部 SQLite writer 竞态。** 本轮未执行“整库恢复为更早合法快照后，外部单调授权仍禁止重新消费”的完整协议测试，也没有在这 6 行修改中接入外部 frontier／rollback witness。冷重开分项通过不能作为整库回滚后已消耗权利永不复活的证明。

## 真实 RED／GREEN 与可计入的测试范围

| 执行 | 源码／范围 | 实际结果 |
| --- | --- | --- |
| RED | 原生产 `47b4a62463d8e1371a175c74196d52d99c5fccb8`，仅增加两项测试 | **0 通过／2 失败**：`cancelled activation returned success`；`activation returned from a changed storage epoch`。 |
| GREEN | 冻结 Chain `04be5f02…`，同两项测试 | **2 通过／0 失败**。 |
| 最终 retained | 同一最终 ELF：44 项 Growth（含两项新 activation）＋2 项 public Growth＋5 项 PQ | **51 个不同测试通过／0 失败，另有 2 项原有 ignored**。两项 activation 不重复计数。 |

RED／GREEN 都固定 Rust 1.95.0、OpenSSL 3.5.9、locked graph、all features、jobs=1；Node 为 `opt-level=3, debug=0` 的**诊断构建**。原 test profile 的 baseline 编译被 SIGKILL，测试未运行，失败收据单独保留。最终 ELF SHA256 为 `f869a33141d4b1602979bbaf583d96764e6c89cdd22bc1c2569ec153425e2f5c`。

51 个测试使用同一最终二进制，但 Growth 与 PQ 仍是各自配置；它们没有满足“PQ 账户、服务身份、Growth 状态、真实交易和恢复在同一配置成立”。这里的 51 是不同执行测试数，另一个 V10 的 51 是 manifest 文件数。两项 ignored 分别是跨 65,536 账户的原生门禁与固定 owner 的账户／历史规模观测；它们未被计为通过。原硬件 4 秒／16 攻击者／depth 6 门禁也未由本轮获得资格。

收据：[范围与摘要](growth/growth-pq-validation-summary.json)、[RED](growth/red-nodebug-observation.json)、[GREEN](growth/green-nodebug-command-result.json)、[retained](growth/retained-command-result.json)、[原 profile 编译失败](growth/red-command-result.json)。这些实现与测试证据不证明最便宜合法 W1 成本下界、Growth／PQ 融合或整链 PQ 安全声明；相关系统门禁继续 HOLD。

[runtime-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d7c32f38ae1c3890e73ff48ef8ee725ba4e80c58/scripts/hepta_smollm_execution_source_v1.py#L67
[packet]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth/packet.rs#L31
[growth-execution]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth.rs#L646
[pq-native-test]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/ingress/public_v3/pq_identity_tests.rs#L312
[pq-time]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-mvcc-fee/src/pon_executor.rs#L1481
[pq-signature]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/pq_accounts_v2.rs#L803
[growth-profile]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth/profile.rs#L13
[pq-policy]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/pq_accounts_v2.rs#L34
[pq-state]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/pq_accounts_v2.rs#L423
[backend-schema]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store.rs#L808
[backend]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store.rs#L1257
[growth-opener]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth.rs#L288
[pq-service]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/ingress/public_v3/growth.rs#L25
[pq-task-profile]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/pq_accounts_v2/application_v6.rs#L65
[activation]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth/recovery.rs#L376
[guard]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth.rs#L307
[epoch-audit]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth/recovery.rs#L769
[activation-tests]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth/tests.rs#L1260
