# 固定 Chain 04be5f02 的 W1 与原 Host 证据边界

**内部源码复核，未进行外部独立安全审计。** 本文记录已读取的实际实现、现有成本 reader 的资格限制，以及本轮原 Host 缺证。没有新增测试、成本测量或确认活性执行；没有修改源码、workload、期限、攻击预算或安全声明。最便宜合法 W1、原确认活性及整链 PQ 门禁均保持 **HOLD**。

## 精确来源

| 项目 | 固定值 |
| --- | --- |
| 仓库 | `TrillionniumFoundation/Trillionnium-Chain` |
| Commit | `04be5f02c84cf5cb626a53f34bc03a5bd6ff5137` |
| Tree | `d4f4a85c439982d8decec9265c1993408f3577cf` |
| `trillionnium/Cargo.lock` SHA-256 | `00f3573879f3da7d5a702a8bc13245196bbfd53b86b0b6eb19c51f14887cef61` |

下文源码链接全部固定到上述 commit。结论不覆盖后续移动分支头，也不把已有 reader 单测、分项原生测试或相同文件字节自动升格为新的端到端资格。

## 1. 实际 W1 接纳、fork choice 与 DAA

| 关系 | 精确源码路径与符号 | 已核对的行为 |
| --- | --- | --- |
| 区块挑战 | [`trillionnium/crates/trnm-protocol/src/pon_wire.rs`][wire]：`Header::encode`、`Header::challenge` | 挑战是完整规范 header 的域分离哈希；编码含 network、parameters、parent、height、timestamp、target、miner、transactions/state/receipts roots、work_task、nonce。 |
| Header 预检及完整工作证明 | [`trillionnium/crates/trnm-pon-node/src/store.rs`][store]：`Node::check_admission_header_context`、`WorkCheckedPacket::verify_with_progress`；[`trillionnium/crates/trnm-crypto-primitives/src/pon_work.rs`][work]：`precheck_proof_statement`、`verify_with_progress`、`verify_with_kernel` | 预检先核对 parent/height、由该 parent 历史得到的 target、时间及事务 root，并作便宜的 proof statement 检查。该检查通过仍不是 `VerifiedWork`。完整入口绑定实际 `h.challenge()`、`h.work_task`、`h.target`、proof；默认完整 verifier 选择 `FullLimb`，重放 transcript、核对 trace，再核对 product，成功后才产生 `VerifiedWork`。 |
| 实际累计工作与 fork choice | [`store.rs`][store]：`Node::persist_admission_execution`、`Node::recover`；[`consensus.rs`][consensus]：`required_work` | 接纳后加入的工作是 `parent.work + required_work(h.target)`。`required_work(T) = floor(2^256 / (T + 1))`，并拒绝零 target。恢复选 tip 使用 `ORDER BY chainwork DESC,height,id LIMIT 1`。这里没有按实测 CPU、矩阵秩、模型质量、实现或硬件成本给区块加权。 |
| 实际 DAA 和时间约束 | [`trillionnium/crates/trnm-pon-node/src/consensus.rs`][consensus]：`BranchTargetHeight::after`、`BranchTargetHeight::window`、`retarget`、`check_time` | 使用该 parent 的已验证、parent-first 历史；非调整高度沿用 parent target。调整窗口的 `desired=(interval-1)*spacing`，`observed=max(last-first,1)` 被夹在 `ceil(desired/4)` 与 `4*desired` 之间，再按比例调整 parent target，并限制在 1 与 pow limit 之间。时间必须严格超过最近最多 11 个祖先的中位数，且不超过当前观察时间加 future skew。 |
| Growth 的接纳与恢复 | [`trillionnium/crates/trnm-pon-node/src/store/growth/recovery.rs`][growth]：`check_growth_header_with_progress`、`admit_growth_with_progress`、`growth_recover` | 同样从当前 parent 取得 target／时间窗口，并累计 `required_work(h.target)`；恢复使用相同 chainwork 排序。另有明确 `CONTINUITY_MAINTENANCE` 检查，要求 `h.work_task == continuity_v1::maintenance_task()`。 |

固定的 [`config/pon/devnet-v1.json`][devnet] 给出 retarget interval 16、target spacing 10 秒、median width 11、factor 4、future skew 120 秒、初始 target／pow limit `7fff…ffff`。因此需要解释的是实际目标权重、合法时间安排和接纳关系下的生产成本；某个矩阵乘法实现跑得较慢，不能推出同等 chainwork 必须支付该成本。

## 2. 合法材料与诊断材料不能混用

普通 legacy 入口的 [`trnm-pon-node/src/lib.rs`][node] 中，`Settings::development` 选择 `LEGACY_TASK_PROFILE`；`maintenance()` 生成：

- `A[i] = i mod 31`；
- `B[i] = (7*i) mod 37`。

它与连续任务／Growth 的 [`trnm-mvcc-fee/src/continuity_v1.rs`][continuity]：`maintenance_matrices`、`maintenance_material`、`maintenance_task` 不同。后者生成：

- `A[i] = (13*i + 17) mod 257`；
- `B[i] = (29*i + 31) mod 263`。

原确认压力测试实际调用 `Settings::development(Some(1_750_000_000))` 和 `maintenance()`，使用前一组 31／37 材料。Growth header 则明确绑定后一组 257／263 maintenance task。不能把一个 profile 的材料、预计算成本或测试结果当成另一个 profile 的最低成本证明。[原测试源码][host-test]

[`pon_work/maintenance_periodic.rs`][periodic] 的 `MaintenancePeriodicPreparedTask::new` 已实现针对精确 257／263 材料的合法专用构造；它先核对每个输入值，再建立列计划、行前缀及实际乘积。这说明特殊材料和合法复用是实际实现需要计入的成本组成。此构造本身既不是所有策略的最优性证明，也不能把 full-rank generic 计时转成固定 maintenance 材料的成本下界。

zero、one-zero／rank-one 等诊断类需要另行区分“数学 W1 关系可构造”与“该实际配置中 task 获准接纳”。特别是 Growth 上述 task 检查禁止把任意诊断任务直接替换为合法 Growth maintenance task。本文不把这几类一概宣称为各业务配置均可自由选用。

## 3. 现有 reader 的构造上界与缺失的最低成本下界

[`scripts/pon_w1_legal_strategy_reader_v3.py`][reader] 的 `analyze_shard`／`analyze` 检查一个有限、固定网格：5 类材料、2 个 target、复用 horizon 1／8／64、每格 8 个样本，以及 eager/lazy × transposed/full-limb 四种已实现策略。五类是 full-rank-field、zero、continuity-maintenance-v1、one-zero-left-rank-one、one-zero-right-rank-one；其中没有原 Host 的 31／37 legacy maintenance 类。

reader 的主要作用是重建记录字节、核对完整尝试与分母、保留所报告的 native verdict。它在源码和输出中明确保留：

| 字段／状态 | 值与含义 |
| --- | --- |
| `w1_transcript_replayed` | `false`；reader 自己不重放完整 W1。 |
| `native_execution_authenticated` | `false`；记录一致不等于原生执行与时钟来源已经认证。 |
| `fastest_adversary_lower_bound` | `false`；没有最便宜攻击者的成本下界。 |
| `native_chainwork_observed` | `false`；work-equivalent 是记录中的有效 target hit × required target weight，不是实际账本产生的 chainwork。 |
| `confidence_bound` | `null`；没有把有限样本提升为统计置信界。 |
| `qualification_status` | `HOLD`；hardness、work profile、resource fairness、独立硬件、生产启用等资格字段仍为 false。 |

在同一具体任务、硬件和成本记账范围内，一个已认证的可执行合法策略可以给出实现该样本工作的**构造性成本上界**：最便宜策略的成本不会大于这个已知策略的成本。它不能反向证明“所有合法策略至少需要这么多成本”。reader 的记录一致性通过，单独也不能认证该构造的实际计时。若将最小成本记为 `C_min`、某个已实现策略的同范围成本记为 `C_s`，可支持的方向至多是具体条件下的 `C_min <= C_s`，不是安全论证需要的 `C_min >= L`。

有限网格不能排除更长复用 horizon、跨 nonce／区块摊销固定材料准备、其它周期／低秩算法、GPU／ASIC 或未观察硬件。[`scripts/ci/check_cross_arch_cost.py`][cross-arch] 的 `implemented_strategy_envelope` 对提供的当前架构／有限 cohort 取已观察最小值，也明确输出 `global_cheapest_producer_qualified=false`、`independent_hardware_qualified=false`、`work_hardness_accepted=false`。本轮 reader／quantum 控件通过的计数不能填补该下界。

此外，legal-strategy reader 的 `challenge()` 使用 `pon-w1-legal-strategy-challenge-v3` 的合成域及 task、target、sample、search、nonce。它不同于真实 `Header::challenge` 对完整 header 的绑定。因此这些记录不能自行作为真实挖块、竞争分支或实际 fork choice／DAA 执行证据。[reader][reader] [真实 header][wire]

## 4. 量子场景仍是条件代理

[`scripts/ci/pq_quantum_daa_scenarios.py`][quantum] 的 `target_search_proxies` 计算 `ceil(2^256/(T+1))` 的经典尝试数代理及其平方根索引；源码明确说明 `sqrt(N)` 不是量子 oracle 门数。

`simulate` 导入参考 `retarget`／`timestamp_state`／`work`，在假定 `seconds_per_header` 和假定外部时钟下推演高度 16、32…的 target 调整。它没有执行真实 Rust W1 producer、完整关系的可逆 oracle、uncomputation、真实量子设备、真实网络或竞争链。实际电路规模、容错／错误预算以及公平的同时间挖矿成本，不能从该索引得到。

其结果明确是 `UNQUALIFIED_HYPOTHETICAL`；`compare_scenarios` 为 `HOLD_RESEARCH_ONLY` 且 `same_wall_clock_or_mining_budget=false`。时间序列满足参考规则不证明按这些时间可以产出合法区块；模拟 chainwork 也不等于实际 fork choice 已被验证，更不构成量子安全或攻击成本下界。

## 5. 原 Host 确认活性与本轮优化适用范围

原确认测试是 [`public_v3_from_zero.rs`][host-test] 中的 `from_zero_signed_business_reports_confirmation_in_original_pressure_window_against_same_packet_baseline`。原 reader [`run_from_zero_native.py`][host-reader] 的 `validate_confirmation_phases` 要求：原 4 秒窗口、压力阶段 16 个 worker、原 7 块诚实链中的 1 笔交易、独立客户端 depth 6 确认、完整状态一致、真实攻击重叠、确认在窗口截止前完成。`run_from_zero_native.py::TESTS` 仍列出原五个 case；诊断或新 workload 不是原 case 的替代。

固定 Host 的 [`config/systemd/trnmponpublic.slice`][slice] 与 [`public_host_ci_observation.py`][host-observation] 规定 CPU `25000 100000`（25% quota）、2 GiB memory、swap 0、tasks 256，并检查固定 parent／unit 身份。当前 [`run_from_zero_host.py`][host-wrapper] 管理该 parent 下自己的唯一 child，保留原 native runner 与原 case，未赋予本轮本机运行原硬件资格。

本轮 [M06 原始汇总](m06/summary.json) 记录：原 `trnmponpublic.slice`／原硬件不可用，观察到的容器 `cpu.max` 为 `800000 100000`；没有在这里执行原 4 秒／16 worker／depth 6 确认接受试验。因此不得称原活性失败关闭，或用本机组件测试的运行时间替代原 Host 接受结果。

本轮 namespace 优化的实际范围如下：

| 改动 | 入口与有效范围 | 不成立的推论 |
| --- | --- | --- |
| Capacity 精确范围扫描 | [`continuity_v1.rs`][continuity] 的 `capacity_with_sources`／`liability_rows` 只遍历 contribution、quota、release、reward、task 命名空间；[`pon_executor/growth.rs`][growth-executor] 的 `check_capacity` 调用 `capacity_with_account_access`。相关普通 continuity／Growth 路径使用这项优化。 | 原确认 case 的 legacy-task 路径不使用 continuity capacity 关系，不能将该优化直接计为原确认耗时下降。 |
| 公开取消检查 | `continuity_v1::capacity_with_progress` 保留完整状态扫描，`CAPACITY_PROGRESS_INTERVAL=256`，并在发布结果前再次检查；与范围路径共享相同容量计算。 | 256 是行数检查间隔，不是加载状态、构造 root 或确认的墙钟上界。 |
| Funds 精确范围扫描 | [`pon_executor.rs`][executor] 的 `funds` 按原全局词序遍历 account、quota、release、reward、task，保留原溢出、类型和首错误语义。它进入普通 legacy completed-block 的资金守恒检查。 | 尚无原 Host 的 speedup／确认通过观察；它也不是 W1 producer 成本下界或 fork-choice 成本证明。 |

最终 Chain 原 profile 的 M06 证据为 lib 133 PASS／0 FAIL／8 ignored、既有 `capacity_progress` integration 7 PASS／0 FAIL，以及 strict Clippy exit 0。8 个 ignored 是显式可选成本观测，本轮没有执行；第一次非法配置 fixture 的 exit 101 原样保留。上述结果证明所跑范围内的组件回归和 lint 状态，不证明原 Host 活性、最低合法 W1 成本或整个协议的端到端资格。[M06 原始汇总](m06/summary.json)

[wire]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-protocol/src/pon_wire.rs
[store]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store.rs
[work]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-crypto-primitives/src/pon_work.rs
[consensus]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/consensus.rs
[growth]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store/growth/recovery.rs
[devnet]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/config/pon/devnet-v1.json
[node]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/lib.rs
[continuity]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-mvcc-fee/src/continuity_v1.rs
[periodic]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-crypto-primitives/src/pon_work/maintenance_periodic.rs
[reader]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/scripts/pon_w1_legal_strategy_reader_v3.py
[cross-arch]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/scripts/ci/check_cross_arch_cost.py
[quantum]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/scripts/ci/pq_quantum_daa_scenarios.py
[host-test]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/tests/public_v3_from_zero.rs
[host-reader]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/scripts/ci/run_from_zero_native.py
[slice]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/config/systemd/trnmponpublic.slice
[host-observation]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/scripts/ci/public_host_ci_observation.py
[host-wrapper]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/scripts/ci/run_from_zero_host.py
[growth-executor]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/growth.rs
[executor]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-mvcc-fee/src/pon_executor.rs
