# learning.eval 对抗审计与优化报告 — 2026-09-30

本报告记录 2026-09-30 UTC（北京时间 2026-10-01）的仓库审计和修复。审计入口基线为 `db5e9da4d4c7340eb6370964a68a76a35226a610`；唯一有效模块交付路线为 PR #1011。PR #1051 保留为历史比较材料，不作为并行合并路线。本轮修复候选将在该基线上形成草稿堆叠 PR；最终提交身份和执行证据由交付记录绑定。

**结论：详细技术开发文档已经存在，独立评估、持久化恢复和消费者链条也已具有具体源码实现。本次对抗审计发现并修复了信任时效、统计置信边界、持久状态一致性、checkpoint 前缀、holdout 泄漏及资格控制面等实质问题。源码修复和已通过的本地检查不能代替最终 SHA 的完整资格，也不能签发真实宿主、长期学习收益或发布资格。** 本报告及全部评估、恢复和资格回执均保持 `DENY_ALL`，发布姿态保持 `NO_GO`。

## 1. 审计范围和判定方法

审计覆盖模块专属根 `codex-rs/hepta-intelligence-eval`、Agentd 评估消费者、相关技术文档、资格脚本和源码状态投影。重点检查可利用的边界，而非仅统计文件或测试数量：

- 在证据签名仍有效但 root-issued trust distribution 已过期时尝试继续使用资格；
- 在 write-ahead I/O 期间推进宿主时钟，检查实际 sink 调用前是否再次验证；
- 构造未选中稀有动作、未知历史和 Q32 舍入边界，检查置信范围及权重上限；
- 为 CAS 输入提供元数据 digest 正确但语义 journal 非规范的状态；
- 保留有效 checkpoint，却替换其概括的等长原始 journal 前缀；
- 跨 fold 复用 final-holdout decision 作为训练标签，或将超预算数据放在晚到的 fold；
- 比较文档、源码投影、公开 API、测试 discovery 和 trusted reporter 的实际边界。

本报告区分源码存在、局部执行、最终候选资格、部署调用和独立外部证据。每项修复都须保持现有 compatibility、失败语义和一用 holdout，不以删减测试、放宽 lint 或扩大权限换取通过。

## 2. 技术开发文档是否详细

答案是**存在，且已形成开发、运行、验证和外部资格的分层入口**。建议按以下顺序阅读：

| 文档 | 实际用途 |
|---|---|
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | 模块使命、权限、产品调用、七阶段状态机、恢复、统计合约、失败分类和部署拓扑 |
| [TECHNICAL.md](TECHNICAL.md) | 完整技术开发指南、registry 投影、工作包、数据归属、容量、验证及设计沿革 |
| [PRODUCTION_CONTRACT.md](../../../codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md) | 默认公开 API、archive、holdout、生命周期、publication 和资格要求的规范合约 |
| [RECOVERY_CONTRACT.md](../../../codex-rs/hepta-intelligence-eval/RECOVERY_CONTRACT.md) | 独立 anchor、完整历史、checkpoint/tail、typed archive、cursor 和 publication 对账 |
| [RECOVERY_TRUST_CAPACITY_CONTRACT.md](../../../codex-rs/hepta-intelligence-eval/RECOVERY_TRUST_CAPACITY_CONTRACT.md) | root activation、每次使用的当前 trust、完整生命周期预留和已知未写/未知提交区别 |
| [NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md) | 算法、持久化、恢复、消费者的具体 Rust 符号及源码映射 |
| [EVIDENCE_ADMISSION.md](../../../codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md) | 签名身份、metric roles、temporal claim、durable holdout 和 V3 时间证据 |
| [learning.eval execution dossier](../../../qualification/module-execution-dossiers/detail/learning.eval.md) | 模块实施、stage-specific bounds、验收案例及剩余证据 |
| [LOCAL_DETERMINISTIC_VERIFICATION.md](LOCAL_DETERMINISTIC_VERIFICATION.md) | 离线控制面检查、严格 summary/marker 和 authority-free 证据边界 |
| [TARGET_HOST_QUALIFICATION.md](TARGET_HOST_QUALIFICATION.md) | 实际宿主、anchor、provider、publication、存储和未来窗的外部证据要求 |
| [CURRENT_STATUS.json](CURRENT_STATUS.json)、[IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json)、[QUALIFICATION_MATRIX.json](QUALIFICATION_MATRIX.json) | 保守机读状态、源码观察和部署能力绑定；它们不能替代执行回执 |

审计前存在“文档齐全但旧文字覆盖新实现”的问题：raw runner 被描述为默认入口、六阶段旧历史残留、multi-outcome recovery 被继续列为源码缺口、4,096 个 attempt 的事件数仍写为 24,576。此次已将手写指南、dossier、生成投影及公开规范同步至 recorded archived ingress 和七阶段语义；七个成功事件对应 28,672 个事件。

规范状态机要求 `ComparisonSealed -> QualificationArtifactsPersisted -> QualificationDecided`。开发指南原先允许直接跳到 decision 的箭头已移除。可读取历史兼容记录不赋予新的产品入口跳过 archive 的权限。

## 3. 模块在项目中的位置

`learning.eval` 位于 **qualification plane**，owner 为 `learning-platform`，deputy 为 `qualification-plane`。它依赖 `learning.ledger` 的 immutable decisions/outcomes 和 trust distribution、`learning.artifacts` 的候选与 lineage，以及 `kernel.evidence` 的证据边界。它负责冻结分析、估计、一次性使用 holdout、独立签名验证和可恢复资格证据，不拥有生产模型写入、独立接受或发布权限。

模块实现阶段专属的 point IPS/SNIPS/DR、cluster intervals、finite-horizon PDIS/DR、temporal fitting/cross-fit 和多测量 channel 比较。统计输出、资格判断和下一层 selection 是不同边界。所有结果继续为 `DENY_ALL`；`EligibleForIndependentSelection` 仅允许后续独立消费者审查。

实际消费者约束如下：

| 消费者 | 必须绑定的事实 |
|---|---|
| [AgentdEvaluationSessionV1::evaluate](../../../codex-rs/hepta-agentd/src/intelligence_evaluation.rs) | owner/run、objective、snapshot、context、candidate set、选择的候选、当前 root-issued trust 和签名证据 |
| [Agentd measured-outcome consumer](../../../codex-rs/hepta-agentd/src/intelligence_outcome_evaluation.rs) | sealed outcome qualification、当前 owner 状态、evaluation/execution/publication 身份和 signed exact-use payload；当前 distribution 的时效仍须通过 |
| [run_evaluated_shadow_v1](../../../codex-rs/hepta-intelligence/src/evaluated_shadow.rs) | sealed product qualification receipt、当前 trust/dataset/candidate/evaluator；不重新运行低级签名判定 |
| [governed plasticity](../../../codex-rs/hepta-intelligence/src/plasticity_product.rs) | proposal/candidate、artifact 与 evidence frontier、dataset 和 generator context；资格不等于生产写入权限 |

默认产品入口为 `RecordedProductEvaluationRunnerV1`，要求 independently anchored durable attempt journal。公开 qualification 必须持久化 canonical typed archive；raw `ProductEvaluationRunnerV1` 为兼容面，低级 V2/V3 decision primitives 和 unarchived qualification helper 为 crate-internal。生产依赖不得通过 transitive feature unification 启用 `trusted-inprocess-eval`。

## 4. 本轮已修复的 P1 问题

P1 表示可能破坏资格、统计或耐久性合约的缺陷；优先级并不表示已发生生产事故。

| 问题 | 可利用的原始行为与影响 | 修复及验证方向 |
|---|---|---|
| trust distribution 在消费者使用时过期 | evaluator/use 签名仍在有效期内，不能保证 root-issued distribution 仍有效；缓存 activation 可能被继续使用 | Agentd 两类消费者检查 `ActivatedLearningTrustV1` 的有效期。新增 distribution 已过期而签名仍有效的对抗回归 |
| sink 使用时间晚于入口验证时间 | archive/journal write-ahead I/O 后时钟推进，入口处有效的 trust 或签名可能在首次 publication 调用时过期 | [selected_host_final_use.rs](../../../codex-rs/hepta-intelligence-eval/src/selected_host_final_use.rs) 在底层 sink 首次调用前重读 archive、重新采样同一绑定的宿主时钟、检查单调性和当前 activation，并重验 exact decision。失败保留 Pending 对账状态，不能使未知写变得可重试 |
| sequential confidence contribution envelope 不足 | 仅看样本中的已选动作或已观察估计不能包住合法但未选中的稀有动作、未见历史、全局 Q 和单独 terminal reward；置信区间可能缺乏所声明的保守范围 | [sequential_confidence.rs](../../../codex-rs/hepta-intelligence-eval/src/sequential_confidence.rs) 按冻结 horizon、累计权重上限、全局 Q 范围、reward/terminal 和舍入误差推导 contribution envelope。小于必要范围返回 typed evidence gap |
| 累计 propensity 上限受 Q32 最近舍入弱化 | 多步最近舍入可能让实际比例已超过 ceiling 的路径仍显示在 ceiling 内 | [sequential.rs](../../../codex-rs/hepta-intelligence-eval/src/sequential.rs) 同时维护原始 propensity 比例和数值累计比例的向外上界，在舍入后的 point estimate 之外独立执行 admission 上限 |
| locked-file CAS 接受非规范语义状态 | 外层 digest 可以绑定错误的 journal head、sequence、predecessor、record 或 use digest；内存看到的状态与持久 payload 重开后可能分歧 | [fenced_holdout_replay.rs](../../../codex-rs/hepta-intelligence-eval/src/fenced_holdout_replay.rs) 将 live CAS admission 和 replay 统一到同一 canonical transition。非规范初始状态及 append 在文件写入前拒绝，原状态/长度保持不变 |
| checkpoint 掩盖原始 journal 的等长分叉前缀 | checkpoint 本身真实，不能证明当前源 journal 前缀就是 checkpoint 所概括的原始 bytes | [attempt_checkpoint_prefix.rs](../../../codex-rs/hepta-intelligence-eval/src/attempt_checkpoint_prefix.rs) 对 checkpoint frontier 之前的 framed bytes 做有界流式校验，验证 event count 与 rolling state digest，再恢复 reducer 并 replay tail |
| 恢复可见 tail 后未先建立耐久性 | outcome-unknown sync 后完整 tail 可能可读；仅可读不等于新 anchor 可以确认其已经耐久 | ordinary/checkpoint journal recovery 在确认恢复 frontier 前执行 `sync_all`，失败返回 `Indeterminate`，保留 reopen/reconciliation 要求 |
| final-holdout decision 跨 fold 进入训练 | 单 fold lineage/model digest 合法仍可能将真正 final-holdout decision 作为另一 fold 的训练标签；重算模型 digest 不能洗掉泄漏 | [temporal_cross_fit.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_cross_fit.rs) 全局收集 final-holdout decision identities 并禁止其进入任一 fold training；普通 cross-fit 训练共享及合法早期非最终 holdout 仍保留 |

这些修复没有证明 exchangeability、cluster independence、无隐藏混杂或真实 observation provenance。此类条件仍须由 preregistered assumptions 和独立外部证据支持；fixed-analysis clustered intervals 也不成为 anytime-valid 或 adaptive-stopping guarantee。

## 5. 本轮已修复的 P2 问题

| 问题 | 修复与作用 |
|---|---|
| cross-fit 全局资源预算检查过晚 | 在构造 global identity sets 或 fitting 任一 fold 前预检整个 input 的 row/action-cell 预算。晚到的超预算 fold 不能先触发早期训练工作 |
| CAS replay 重复重建语义前缀 | replay 保留同一个 canonical semantic journal，逐 transition 更新；减少每个前缀重复 reconstruction，同时保留 fence、anchor 和完整 use history |
| 存储 profile 的 holdout 历史不足 | profile 现在每个 generation 消费不同 frozen plan，包含非空 holdout records、fence takeover、source reopen、copy-compaction 和 successor reopen，并核对完整 authoritative state |
| source projection 与人读文档漂移 | generator 按 CURRENT_STATUS 的 single/multi typed recovery source fact 和七相事件数输出；源码存在和 deployed host qualification 明确分开 |
| Lane E API 追踪与 readiness metric-role 范围未同步 | matrix 保留原 closed-world source operations，但明确 raw runner 的 default private/compatibility 分类和 signed primitives 的 crate-internal 边界，并在既有 `productCallsites` 结构列出 recorded archived public 入口。readiness §5 改为 preregistered V2 superiority/non-inferiority/absolute roles，保留所有保护阈值与独立接受边界 |
| trusted reporter 文档/检查器使用旧入口假设 | AUDIT_INDEX 补齐 `workflow_run` 与 untrusted data 边界；控制面检查识别 trusted entrypoint/report 路径及其 delegation，并保留 fail-closed 约束和回归覆盖 |
| 初始缺失 import 和陈旧测试假设 | 补齐所需 test import；修正本轮变化涉及的真实 clock/trust、seven-phase archive 和持久状态 fixture，使回归验证当前合约，保留原来的故障断言 |

全局资源预算、default-public API 和独立 anchor 的保护均保持。没有通过减少 bounds、关闭故障测试或改变 `DENY_ALL` 来完成修复。

另有 P3 格式化检查器问题：source-status 检查曾依赖原始字符串/固定格式匹配，Rust 合法空白、注释、literal 或参数顺序会造成错误判断。本轮按实际 Rust token 边界修正匹配，增加八项针对空白、注释、literal 和参数顺序的回归，并将本地控制面 script inventory 同步为规范列表。它验证源码/控制面一致性，不能证明真实宿主或执行资格。

## 6. 有代表性的对抗回归

具体源码和 tests 仍由 [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json) 与 [NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md) 映射；本报告编写阶段不改写 source observation 身份。代表性回归包括：

- `signed_candidate_rejects_expired_distribution_with_live_signatures`；
- `multi_outcome_consumer_rejects_expired_distribution_with_live_use_signature`；
- `unchosen_rare_actions_cannot_hide_an_invalid_confidence_envelope`；
- `unseen_histories_and_separate_terminal_rewards_enter_the_safe_envelope`；
- `original_propensity_ratios_enforce_the_cumulative_ceiling_before_rounding`；
- `malformed_initial_snapshot_is_rejected_before_any_file_write`；
- `append_rejects_every_noncanonical_record_field_without_consuming_the_plan`；
- `same_length_divergent_journal_prefix_cannot_hide_behind_an_authentic_checkpoint`；
- `checkpoint_recovery_and_continued_append_remain_equivalent_to_ordinary_replay`；
- `final_holdout_decisions_cannot_supply_another_folds_training_labels`；
- `complete_input_budgets_reject_before_any_fold_fitting`。

普通合法 cross-fit 及 continued append 的正例与拒绝例一同保留。编译负例必须因所声明的 public API/type boundary 失败；无关 compiler error 不能作为边界成立的证据。

## 7. 完成度评估

完成度按证据层分开判断，不给没有分母和验收定义的百分比。

| 层次 | 当前判断 | 尚需的证据 |
|---|---|---|
| 文档与设计 | 详细 developer path、规范合约、dossier、源码映射和外部宿主协议存在；本轮已修正重要漂移 | 最终候选的完整文档/registry/source projection 检查及 commit binding |
| 核心源码 | point/cluster/sequential/temporal、多 outcome、signed V2/V3、fenced holdout、durable seven-phase journal、typed cold recovery、checkpoint 与 cursor 均有具体实现 | 最终 SHA 的编译、owner/consumer/API/fault/lint/coverage 资格 |
| 仓库消费者 composition | Agentd、evaluated shadow、governed plasticity 有明确 source bindings；本轮加强 distribution 当前性与实际 sink 时效 | named host 上的真实 provider/publication/supervisor 调用与部署测量 |
| 本地执行 | 下面列出的 owner、consumer、Python、API 和生产 library lint 已通过 | 它们属于本轮本地执行，不能冒充最终 exact-head、merge 或完整 workspace 证据 |
| 完整源码资格 | 尚未闭合 | 三包严格 lint 的共享依赖阻断、覆盖率至少 85%、exact head 和 ordered-parent synthetic merge 的 retained commit-addressed artifacts |
| target-host qualification | 未闭合 | authenticated host、独立管理员 anchor、实际 lock/CAS/fsync/目录/断电语义、provider/publication/cursor topology 和 recovery SLO |
| 真实长期学习与独立接受 | 未闭合 | real future-calendar windows、独立 snapshots/measurement、power、shift、retention、subgroup/privacy、unlearning、backup non-resurrection 和独立 semantic/operator acceptance |
| selection/activation/release | 未授权 | 各自独立的 gate 与 authority；当前继续 `NO_GO` |

## 8. 本地验证结果与明确限制

以下是报告编写时主审已确认的本地结果。最后一次源码修改、最终 commit 和其 synthetic merge 仍须由交付证据重绑定。

| 验证范围 | 编写时结果 |
|---|---|
| `learning.eval` 全部默认测试 | **223 项全部通过，零跳过**，包括四项缓存/严格回放等价与篡改回归 |
| Agentd 本轮 scoped filters | **6 项通过**；这是评估相关 scoped consumer 验证，不是整个 Agentd/workspace 全量验收 |
| Python 资格/控制面回归 | **182 项通过** |
| default/compatibility API boundary | **通过**，含针对具体边界的 compiler-negative fixtures |
| production library 严格 Clippy | **通过** |
| 文档文件/heading-anchor 检查 | **通过（15 documents）**，含本报告及索引链接 |
| `learning.eval` strict all-target Clippy | **通过，零警告**；129 处 fixture `expect` 按 Result/Option 分别替换为保留失败上下文的显式 panic，全部断言保留，没有放宽 lint |
| evaluator/intelligence/Agentd 三包 Rust formatting | **通过**；既有格式整理为独立机械提交，随后按 CI 原范围执行 `cargo fmt -- --check` |
| evaluator/intelligence/Agentd 三包 strict all-target Clippy | **未通过**：共享依赖 `hepta-operations` 两处绕过 `codex-state` SQLite shim 的连接构造及一处 `collapsible_if` 阻断。未绕过 deny list；现有 shim 的五连接策略与该 store 的四连接合约不同，正确迁移需要依赖/锁文件和该模块的容量策略审查 |
| 完整 workspace 测试 | 未作为本次 scoped 结果宣称通过 |
| default-production measured coverage >=85% | 待最终候选的覆盖率证据 |
| exact head / ordered-parent synthetic merge | 待最终候选的 commit-addressed CI artifacts |
| 实际宿主/独立接受/发布 | 无可由本地运行替代的证据；相关 claims 保持 false |

完整源码资格须将 source commit/tree、ordered parents、commands、exit codes、logs/output digests、toolchain 和 coverage report 绑定到同一个最终候选。queued、pending、cancelled、skipped 或 infrastructure-invalid 不能记作通过。

## 9. 非空 holdout 存储 profile 与性能优化

此次补强的 profile 在 **512 个 holdout records 与对应 fence 历史**下执行写入、源恢复、copy-compaction 和 compacted successor 恢复，校验保留 state、anchor 和 use history。它避免把仅有空 journal/fence 切换的 profile 当成非空 holdout 恢复证据。

进一步性能优化前，本机这轮观测为：

| 阶段 | 优化前 | 优化后 |
|---|---:|---:|
| holdout 写入/消耗与 fence takeover | 234.095 秒 | 5.083 秒 |
| 源 CAS 文件 recovery | 1.412 秒 | 1.676 秒 |
| copy-compaction | 2.866 秒 | 3.365 秒 |
| compacted successor recovery | 1.350 秒 | 1.567 秒 |

这些值来自同一配置在本机的各一次 scoped profile，不是部署 SLO、跨宿主线性一致性证明或长期吞吐验收。写入观测约快 46 倍；恢复/compaction 没有改善，且会受并行构建和宿主负载影响。两次 profile 均保留相同 234,756 字节源文件、185,808 字节 successor、512 条 plan 历史，并通过 `retryPreserved`、`anchorPreserved`。优化后 profile digest 为 `8abb7280dbbe35fc6e4a9fab7c67057c56644d6911cddb86df44f33969e096a5`。

根因是每次 fence takeover 都重新按完整 registry prefix 重建 journal。locked-file adapter 现在可返回已逐帧验证的 native journal；owner 仍先校验当前 CAS record，再逐字段比较完整 snapshot，并恢复 owner 原本的容量策略。缓存不匹配时拒绝；没有缓存的 generic store 继续严格重建。缓存复制/比较每次为 `O(N)`，不是整份文件恢复的复杂度。v2 registry 的逐前缀摘要仍要求整集合哈希，完整 recovery 仍可能为 `O(N²)`；重复 generic recovery 仍可能累计为立方成本。更改这项 wire 合约须单独设计版本迁移，不能省略 prefix 验证来伪造线性性能。

独立复审新增了容量策略和 genuine sealed receipt 跨 prefix 拼接攻击；四项回归覆盖相同/新 fence 的 strict 等价、容量策略规范化、元摘要漏检的 record 篡改，以及合法 seal 但错误 registry prefix 的拒绝。未更改原有 wire 版本或 digest。

优化只能减少重复 replay/snapshot/encoding 工作，不得削弱 sync、anchor acknowledgement、canonical transition、one-use holdout 或完整历史检查。优化后须保持同一非空 profile 的 state/anchor 对等检查，并记录新的 write/source recovery/compaction/successor recovery 结果。

## 10. 剩余可执行工作和终止标准

本轮存储性能优化和对应独立复审已收敛，确认的模块缺陷均已落实修复。交付仍需将 map/status 绑定至不可变源码观察，并保留完整源码资格、共享依赖 lint 和外部证据的未闭合状态。新的 docs 或 lexical facts 不能直接设置 `sourceQualifiedByThisRun`。

项目级规范仍有一项未闭合的跨 registry 关系：[MODULES.json](../MODULES.json) 的 `learning.eval.writes=[]`，而 [DATA_AUTHORITY.json](../../data/DATA_AUTHORITY.json) 将 `ndu_well_posedness_certificate_v1`、`operator_applicability_certificate_v1`、`regularity_profile_v1`、`support_audit_receipt_v1`、`candidate_evaluation_receipt_v1`、`conformance_receipt_v1`、`algorithm_fault_receipt_v1` 的 schema owner 和 authoritative writer 指定为 `learning.eval`。两者未机读说明空 bootstrap 列表与 qualification 目标域的关系，现有全局验证器也未比较两侧 writer 集合。本轮不改变任何 registry authority；后续须由项目规范协调明确该关系和一致性验证。这些目标域声明不证明已部署实现，更不授予生产写入权限。

额外执行的全局检查也未闭合：`hepta-docs.py verify` 因当前 checkout 缺少历史 Git 对象 `b621768b70a09d56626bb8a2c331e3dc424e6a4d` 而阻断，这是历史对象/环境可用性问题，不是此次文档修改引入的源码回归；`hepta-lane-e-closure.py verify` 返回 11 项 findings，包括 operator operation 闭世界集合漂移、traceability case 集合/OP-03 旧函数映射及八项 Agentd legacy learning-writer 边界。此次 `learning.eval` matrix 的既有 operation/status 集合与五个新增 public recorded source entries 已通过 scoped 验证；全局 findings 保留为跨模块规范/调用链协调义务，未扩大修改 operator 或 Agentd legacy runtime writer，也未宣称全局文档/Lane E gate 通过。

本轮更新了源码/资格控制面 inventory 与验证器；trusted CI 资格仍要求将对应 bootstrap control-plane 变更独立重堆叠、审阅并与 trusted base 的字节身份对齐。仅在模块候选中出现修复不能宣称已经通过可信控制面的最终资格。

共享依赖的三包 lint 阻断定位于 [destination_dedupe.rs](../../../codex-rs/hepta-operations/src/destination_dedupe.rs) 和 [durable_store.rs](../../../codex-rs/hepta-operations/src/durable_store.rs)。后续应由该 store 的连接/容量合约审查决定如何迁入集中 SQLite shim，同时更新依赖和 Bazel/Cargo 锁文件；仅改写调用名或添加 lint exception 无法修复规约。

源码资格须分别满足 default product API、隔离 compatibility、owner/consumer/process faults、typed cold recovery、capacity/checkpoint、严格 lint/format、measured coverage 和 source/ordered-parent merge。若新修复改变相应路径，复跑相应 scoped 检查；不要把旧 working-tree 的成功嫁接到新 commit。

外部剩余工作由独立拥有者提供：真实 host/anchor/provider/publication/cursor 的身份与拓扑、存储断电和恢复测量、至少两个真实未来窗口和三个独立 snapshot、retention/change-point/power/subgroup/privacy/unlearning/backup 非复活，以及 semantic/operator acceptance 和后续独立 selection/canary/promotion/release。`UNBOUND_EXTERNAL` 能力不得因 trait、fixture 或 repository CI 存在而变成已认证实例。

本轮终止标准是：本次范围内确认的缺陷已落实修复并有对应验证；尚未建立的证据被明确保留；最终候选可交给独立 reviewer 和资格执行。该标准不声称未来不可能发现新问题，也不把持续优化请求解释为虚构外部时间、真实收益或发布权限。
