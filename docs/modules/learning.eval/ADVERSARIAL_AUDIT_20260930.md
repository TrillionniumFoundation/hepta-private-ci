# learning.eval 对抗审计与优化报告 — 2026-09-30

本报告记录 2026-09-30 至 2026-10-01 UTC 的两轮仓库审计和修复。首轮入口为 `db5e9da4d4c7340eb6370964a68a76a35226a610`，规范模块交付基线为 PR #1011；PR #1051 保留为历史比较材料。第二轮以 PR #1307 当时的 `3714b7e1c2513e0e79ad8560a80fda480aca9471` 为复审基线，继续修复其后的候选。最终 source commit/tree、审查 head 和执行证据分别由交付记录绑定，历史 head 的成功不能移用于新 head。

**结论：详细技术开发文档已经存在，独立评估、持久化恢复和消费者链条具有具体源码实现。两轮对抗审计修复了信任时效、完整决定封印、最终归档身份、统计边界、持久状态一致性、checkpoint、holdout 泄漏、兼容特性隔离及资格控制面等实质问题。最后修改后七包 882 项与 Agentd 六项消费者合计 888 项测试通过；完整资格仍单独记录。源码与局部通过结果不能签发真实宿主、长期学习收益或发布资格。** 本报告及全部评估、恢复和资格回执均保持 `DENY_ALL`，发布姿态保持 `NO_GO`。

## 1. 审计范围和判定方法

审计覆盖模块专属根 `codex-rs/hepta-intelligence-eval`、Agentd 评估消费者、相关技术文档、资格脚本和源码状态投影。重点检查可利用的边界，而非仅统计文件或测试数量：

- 在证据签名仍有效但 root-issued trust distribution 已过期时尝试继续使用资格；
- 在 write-ahead I/O 期间推进宿主时钟，检查实际 sink 调用前是否再次验证；
- 构造未选中稀有动作、未知历史和 Q32 舍入边界，检查置信范围及权重上限；
- 为 CAS 输入提供元数据 digest 正确但语义 journal 非规范的状态；
- 保留有效 checkpoint，却替换其概括的等长原始 journal 前缀；
- 跨 fold 复用 final-holdout decision 作为训练标签，或将超预算数据放在晚到的 fold；
- 比较文档、源码投影、公开 API、测试 discovery 和 trusted reporter 的实际边界。

第二轮进一步修改公开 receipt 的决定字段、替换 Pending 后的完整 archive/外层 holdout digest、跨 fold 给同一 decision 配置不同 episode/action、构造最近舍入权重相同而真实 ESS 不同的数据、令 checkpoint 在读取期间增长，并在真实恢复子进程的 `fsync` 注入内核 `EIO`。同时检查执行 hook、Python import layout 和完整 owned source root 的身份闭包。共享 SQLite、NDU 和 Memory 的改动用于闭合实际依赖或 fixture 阻断；这些 scoped 审查不表示整个项目已完成对抗审计。

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

第二轮将详细规范同步至 receipt evidence domain v4、完整 archived bytes 与原 holdout digest 的最终使用绑定、有限 Q32 ESS 认证及其数值缺口。真实顺序为先构造并验证 canonical archive，再持久化并确认 phase 4；selected-host 在 Pending 后、writer 前再次验证完整归档、当前 clock/trust 和 exact decision。旧 v3 内存 receipt 需要重验重出，依赖其 evidence digest 的 candidate/use 签名也须重签；archive/journal/publication wire 未改，已发布历史不能因此重写或再提交。

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

因此，本模块的完成度必须围绕三个相邻边界判断：上游 ledger/provider 是否提供当前、独立、真实的观察与 trust；模块内部是否将冻结分析、一次性 holdout、签名决定和耐久历史绑定；下游消费者是否在当前 owner 状态下绑定精确使用，并由另一权限层决定 selection/activation。加强模块内部封印或通过 repository CI，只能关闭相应源码缺口，不能证明另外两侧的真实部署与组织独立性。

## 4. 首轮已修复的 P1 问题

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
| Shadow fixture 将 raw 兼容特性带入 workspace 默认构建 | Shadow 的 dev-dependency 开启 `trusted-inprocess-eval`，经 Cargo feature unification 扩大正常产品构建的公开 API；最终 inventory 检查发现违反隔离合约 | 移除该 feature，迁移数值/因果链和 API-link fixture 至默认 `RecordedProductEvaluationRunnerV1`。真实 locked journal、分开保留的文件 anchor 和 typed archive 覆盖七阶段及关闭重开；保留原数值和 `DENY_ALL` 断言，不增加 allowlist |
| final-holdout decision 跨 fold 进入训练 | 单 fold lineage/model digest 合法仍可能将真正 final-holdout decision 作为另一 fold 的训练标签；重算模型 digest 不能洗掉泄漏 | [temporal_cross_fit.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_cross_fit.rs) 全局收集 final-holdout decision identities 并禁止其进入任一 fold training；普通 cross-fit 训练共享及合法早期非最终 holdout 仍保留 |

这些修复没有证明 exchangeability、cluster independence、无隐藏混杂或真实 observation provenance。此类条件仍须由 preregistered assumptions 和独立外部证据支持；fixed-analysis clustered intervals 也不成为 anytime-valid 或 adaptive-stopping guarantee。

## 5. 首轮已修复的 P2 问题

| 问题 | 修复与作用 |
|---|---|
| cross-fit 全局资源预算检查过晚 | 在构造 global identity sets 或 fitting 任一 fold 前预检整个 input 的 row/action-cell 预算。晚到的超预算 fold 不能先触发早期训练工作 |
| CAS replay 重复重建语义前缀 | replay 保留同一个 canonical semantic journal，逐 transition 更新；减少每个前缀重复 reconstruction，同时保留 fence、anchor 和完整 use history |
| 存储 profile 的 holdout 历史不足 | profile 现在每个 generation 消费不同 frozen plan，包含非空 holdout records、fence takeover、source reopen、copy-compaction 和 successor reopen，并核对完整 authoritative state |
| source projection 与人读文档漂移 | generator 按 CURRENT_STATUS 的 single/multi typed recovery source fact 和七相事件数输出；主模型补齐已提交投影中已有的三项 root-activated final-use/API source facts，恢复单一模型与投影一致性。源码存在和 deployed host qualification 明确分开，全部外部 claims 仍为 false |
| Lane E API 追踪与 readiness metric-role 范围未同步 | matrix 保留原 closed-world source operations，但明确 raw runner 的 default private/compatibility 分类和 signed primitives 的 crate-internal 边界，并在既有 `productCallsites` 结构列出 recorded archived public 入口。readiness §5 改为 preregistered V2 superiority/non-inferiority/absolute roles，保留所有保护阈值与独立接受边界 |
| trusted reporter 文档/检查器使用旧入口假设 | AUDIT_INDEX 补齐 `workflow_run` 与 untrusted data 边界；控制面检查识别 trusted entrypoint/report 路径及其 delegation，并保留 fail-closed 约束和回归覆盖 |
| 初始缺失 import 和陈旧测试假设 | 补齐所需 test import；修正本轮变化涉及的真实 clock/trust、seven-phase archive 和持久状态 fixture，使回归验证当前合约，保留原来的故障断言 |

全局资源预算、default-public API 和独立 anchor 的保护均保持。没有通过减少 bounds、关闭故障测试或改变 `DENY_ALL` 来完成修复。

另有 P3 格式化检查器问题：source-status 检查曾依赖原始字符串/固定格式匹配，Rust 合法空白、注释、literal 或参数顺序会造成错误判断。本轮按实际 Rust token 边界修正匹配，增加八项针对空白、注释、literal 和参数顺序的回归，并将本地控制面 script inventory 同步为规范列表。它验证源码/控制面一致性，不能证明真实宿主或执行资格。

## 6. 第二轮新增发现与修复

以下问题来自 `3714b7e..HEAD` 的持续审计。表中的拒绝语义均有保留正例的回归；源码存在与最终候选执行分别报告。

| 优先级 / 问题 | 原始失效路径 | 修复与实际边界 |
|---|---|---|
| P1：single-outcome receipt 未封印全部决定语义 | 修改公开 disposition、evaluation/candidate/baseline IDs 或 failed-metric 内容/顺序，可能保留旧 evidence digest 与 private seal | [product_qualification_receipt.rs](../../../codex-rs/hepta-intelligence-eval/src/product_qualification_receipt.rs) 将全部决定字段及 trust/authentication/context 绑定至 `product-qualification.v4`；外层 receipt-seal domain 仍为 v1。旧 domain-v3 内存 receipt 和依赖签名须从真实证据重验重出，持久 wire 和 Published 历史保持原义 |
| P1：final-use 仅验证内层签名不够 | Pending 后只替换 archive 外层 holdout digest，内层签名仍然合法；冷恢复若以新磁盘 bytes 计算期望 digest，会接受替代来源 | [prepared_qualification_archive.rs](../../../codex-rs/hepta-intelligence-eval/src/prepared_qualification_archive.rs) 让初始 phase 4 与 guard 共用同一 canonical bytes；[qualification_archive.rs](../../../codex-rs/hepta-intelligence-eval/src/qualification_archive.rs) 比对全部 bytes digest 和原 holdout digest。冷期望取自 validated anchored phase-4/ComparisonSealed history。三类签名路径分别测试初始与冷恢复替换：零 publication，保留 Pending/Unresolved，不能变成重试 |
| P1：LedgerWriter/Shadow 缓存 activation 超过分发有效期 | subject signature 仍有效，不能赋予已过期 root distribution 新写入或调用资格 | [production_active_trust.rs](../../../codex-rs/hepta-learning-ledger/src/production_active_trust.rs) 统一约束五个签名入口；Shadow 在任何 port 调用前检查 owner trust。expiry=50 的分发在 50 允许、51 拒绝，角色签名仍有效至 90；拒绝时 ledger/witness/frontier 不变，Shadow port 调用为零 |
| P1：同一 decision 跨 fold 更换因果身份 | 不同 fold 可对同一 decision 提供不同 episode/action，局部 lineage/digest 检查不足以保证同一事件 | [temporal_cross_fit.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_cross_fit.rs) 先全局绑定不可变 episode/action 身份；合法 outcome correction 和正常 cross-fit 训练共享继续允许 |
| P2：有效 confidence radius 被中间乘积溢出拒绝 | 最终 Q32 半径可表示，宽 range 的直接中间乘法却超出 `u128` | [sequential_confidence.rs](../../../codex-rs/hepta-intelligence-eval/src/sequential_confidence.rs) 用精确商余数递推保持向外 rounding，保留原范围/alpha/cluster 合约；宽声明 envelope 与 horizon 128 的有效正例不再因中间值溢出失败 |
| P1：nearest ESS 被误作真实 propensity 支持证明 | 最近舍入权重相同，不能证明原始 ratio 权重相同或真实 ESS 达到严格 floor | [ope_support.rs](../../../codex-rs/hepta-intelligence-eval/src/ope_support.rs) 以原始 e/b 及 sequential prefix 的有限 Q32 外向 bounds 认证。LB 达标或同正真实权重 equality 证明 ESS=n 才支持；有限 UB 可证明低支持，非uniform 未决返回 `NumericalSupportGap`。nearest/ties-even receipt ESS 只保留为点诊断 |
| P2：checkpoint 读取在并发增长时不受捕获长度约束 | format 上限与第一次 metadata 合法，不能让随后增长的文件触发无界 `read_to_end` 或缓冲扩容 | [attempt_checkpoint_read.rs](../../../codex-rs/hepta-intelligence-eval/src/attempt_checkpoint_read.rs) 精确分配捕获长度，只读该长度加一个 EOF probe；增长、截短或读后长度变化返回 `Corrupt`，真实 I/O 错误保留类型 |
| P1 验证补强：缺少真实恢复 fsync 故障证据 | 正常恢复通过和 mock anchor 拒绝都不能验证恢复 `sync_all` 失败时不会确认 frontier | [recovery_sync_eio_tests.rs](../../../codex-rs/hepta-intelligence-eval/tests/selected_host_recovery_support/recovery_sync_eio_tests.rs) 在 Linux x86_64 子进程跨 exec 使用 seccomp 注入真实内核 `fsync EIO`，ordinary/checkpoint 均要求 `Indeterminate`、anchor CAS=0、四份持久文件不变；正常重试要求 CAS=1 和完整 history/anchor 等价。该故障实验不证明生产断电或其他平台语义 |
| P1：实际 `just` shell hook 不在可信字节清单 | `justfile` 通过 `runpy` 执行 `scripts/just-shell.py`，只固定 justfile 仍可替换真正的测试执行器 | trusted 与 auxiliary inventory 均绑定 hook bytes；doc-contract 也要求 entry/report/hook 在身份清单。hook 改动必须 fail closed，不改变 workflow 权限 |
| P1：新增 Python module 劫持控制面 import | 添加 candidate `scripts/subprocess.py` 可在保护脚本 bytes 不变时伪造 `Popen.wait()==0`，把不存在命令记为 passed | [control-plane-identity.py](../../../scripts/hepta-learning-eval-control-plane-identity.py) 比较 trusted committed Git 与 exact candidate commit/tree 的 Python import layout，覆盖当前 scripts 与 root/codex-rs import 链的 module/package/bytecode/extension 路径。新增/删除/替换、opaque import roots、错误 SHA、truncated tree、重复 keys/path、异常模式和超限响应拒绝；不冻结无关脚本正文、不执行 candidate code |
| P2：convergence profile 检查缺少非空计划与 retry 条件 | 发现 JSON artifact 不等于检查了真实计划历史或重试保持；旧内嵌 checker 可接受缺字段/空 plans/retry=false | workflow 加入 `planRecords == 512` 与 `retryPreserved is True`；回归直接抽取并执行实际内嵌 checker，对缺失、零 plans 和错误 retry 拒绝。未将 artifact 发现升级为 qualification passed |
| P2：source observation 仅覆盖映射清单 | unmapped source/build input、新文件或非忽略 untracked 文件改变，旧 map 仍可能被当作完整 owned source 观察 | [status.py](../../../scripts/hepta-learning-eval-status.py) 在所有 mapped/caller paths 外固定校验完整 eval 根，并要求 canonical archived public ingress 入 map。status 仍只产生 lexical source inventory，外部 claims 全 false；新源码须重新绑定 commit/tree |
| P2：Bazel 未声明 Operations 迁移编译输入 | 两处 `sqlx::migrate!` 读取 SQL，但原 BUILD 的 `compile_data=[]`，Cargo 成功不能证明 Bazel 输入完整 | [Operations BUILD.bazel](../../../codex-rs/hepta-operations/BUILD.bazel) 明确包含 `migrations/**` 和 `destination_migrations/**`；仅编译时嵌入，无需 runtime data。独立输入/依赖复核通过，不作为 Bazel test 通过 |
| P2：共享 SQLite 连接工厂与 4/5 容量合约冲突 | 简单替换本地构造器会将 operations 原四连接预算变为 state 默认五连接；绕开 factory 继续触发 lint | [sqlite_evidence.rs](../../../codex-rs/state/src/sqlite_evidence.rs) 提供命名的 FourConnections/Default 策略，保留 WAL、FULL sync、foreign keys、5 秒 busy timeout 和 authoritative corruption 失败语义；operations 接入中央 factory，迁移仍由 store owner 执行 |
| P2：NDU 兼容 re-export 和最大 residual fixture 阻断 | deprecated re-export 让正常依赖 lint 失败；solver maximum residual 包含未发出的 initial 值，与 iteration receipt 合约不符 | 保留 public deprecated wrapper 和原 API；内部实现不触发自用 deprecation。maximum 取 emitted post-update receipts，零 iteration 保留 initial residual。增加正负方向和零 iteration 真实边界，未删除失败断言或扩大 allowance |
| P3：共享依赖 fixture 与当前合约不一致 | Memory V2 migration 断言未包含已有第十五个 migration；operations fixture 使用未武装的生产 writer；私有 runner import 检查受 formatter 改写影响 | 保留 migration 重开/schema 断言，使用真实 LedgerWriter/factory 武装 fixture，并按 token 识别合法私有 imports；compiler-negative 仍必须因指定 API boundary 失败 |

ESS 数值认证不是无限精度有理数 ESS 求解器。`S=2^32`，单步使用 `L=floor(e*S/b)`、`U=ceil(e*S/b)`，prefix 逐步向外更新；真实 ESS 位于 `(ΣL)²/ΣU²` 与 `(ΣU)²/ΣL²` 之间。最大 floor=n 的 Cauchy equality 用原始 ratio 证明；不同编码的同一正比例仍能恰达标。Sequential horizon≤128 的等号证明使用两份固定 129-limb arrays，`2^8192` endpoint 需要 8,193 bits，不能少一 limb。其 fallback 在当前 total-step cap 下有界，不向普通 ESS 计算引入无界大整数。

真实 API 回归中，400 个 2/3 权重的不同编码仍满足 ESS=400；改变一行原始 propensity 后，nearest weights 相同，真实 ESS 与 400 的差仅约 `2.4e-20`。这是严格门槛的算术一致性案例，不能宣传为有意义的实践误差或统计 power 改善。floor=400 必须拒绝，靠近它的一 raw-Q32 floor 可返回明确数值缺口，充足 margin 的 floor=399 仍保留有效正例。

最后实际消费者构建发现 Operations 的四连接 `SQLITE_FULL` fixture 将动态 `String` 直接传给 SQLx 0.9 `query`，不满足 `SqlSafeStr`。fixture 现使用固定 PRAGMA 前缀和仅含正 `i64` 数据库 page count 的 `QueryBuilder`，不使用任意输入字符串或 `AssertSqlSafe`；每连接持有、设置、读回及全部原子性故障断言保留。修正后 Operations 44 项实际通过。

源码扫描器另修复了每次尝试 raw-string prefix 都复制剩余源串的重复工作：仅调整四行，以 offset 匹配原字符串，保持语法与 identifier/code-token 结果不变。主审对 8,824 份、约 333 万字符的同一 corpus 校验结果完全等价；新完整扫描单次为 28.382 秒，旧观测至少 197 秒。这个本机比较不宣称跨机器吞吐或所有输入的统一加速，也未删除全仓调用清单检查。

本节修复已拆成可审查的连续提交，格式化与行为修改分开。详细开发文档已同步迁移及边界；需要最终 source observation、执行记录和可信 control-plane bootstrap/restack 来完成后续资格。独立 scoped 复审没有发现本节范围内未处理的可复现模块缺陷，但这不代表没有未知缺陷。

最终远端 head 的首次规范离线检查中，13 项通过，source-status 实际发现归档写入的旧映射仍为 `qualification_archive.rs::Archive::persist`。实现已经迁移至 `prepared_qualification_archive.rs::PreparedArchive::persist`；本轮同步修正实现映射、手写 native mapping 和必需符号清单，并重新绑定最终候选执行记录。该失败没有被记作通过，也没有放宽源码检查。

## 7. 有代表性的对抗回归

具体源码和 tests 由 [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json) 与 [NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md) 映射；最终 map-only 提交将 source observation 固定到其不可变源码父提交及 tree。代表性回归包括：

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
- `complete_input_budgets_reject_before_any_fold_fitting`；
- Shadow `lane_e_causal_candidate_chain_is_digest_bound_and_deny_all`，包含 recorded 七阶段、archive bytes digest 和完整 history/anchor 重开等价；
- `lane_e_public_operation_surface_is_linkable`，默认入口不要求启用 raw compatibility feature。

普通合法 cross-fit 及 continued append 的正例与拒绝例一同保留。编译负例必须因所声明的 public API/type boundary 失败；无关 compiler error 不能作为边界成立的证据。

第二轮代表性回归还包括：

- `recorded_archived_ineligible_receipt_seals_every_signed_decision_field`；
- `selected_host_initial_and_cold_final_use_require_exact_anchored_archive`；
- `signed_decision_requires_current_distribution_without_writes_after_expiry`；
- `original_propensities_determine_ess_even_when_rounded_weights_match`；
- `full_horizon_cross_products_fit_the_fixed_limb_budget`；
- `radius_division_retains_outward_rounding_and_full_plan_bounds`；
- `recovery_sync_eio_blocks_anchor_ack_and_successful_retry_retains_the_tail`；
- checkpoint concurrent-growth/truncation/invalid-length/I/O-error 回归；
- Python hook drift、import module/package/extension/bytecode additions/deletions 和 truncated/wrong-SHA/duplicate tree metadata 回归。

## 8. 完成度评估

完成度按证据层分开判断，不给没有分母和验收定义的百分比。

| 层次 | 当前判断 | 尚需的证据 |
|---|---|---|
| 文档与设计 | 详细 developer path、规范合约、dossier、源码映射和外部宿主协议存在；本轮已修正重要漂移 | 最终候选的完整文档/registry/source projection 检查及 commit binding |
| 核心源码 | point/cluster/sequential/temporal、多 outcome、signed V2/V3、fenced holdout、durable seven-phase journal、typed cold recovery、checkpoint 与 cursor 均有具体实现 | 最终 SHA 的编译、owner/consumer/API/fault/lint/coverage 资格 |
| 仓库消费者 composition | Agentd、evaluated shadow、governed plasticity 有明确 source bindings；本轮加强 distribution 当前性与实际 sink 时效 | named host 上的真实 provider/publication/supervisor 调用与部署测量 |
| 本地执行 | 七包最终 882 项加 Agentd 六项，共 888 项通过；先前 State 216 项保留历史身份 | 它们不能冒充最终 exact-head、merge、覆盖率或完整 workspace 证据 |
| 完整源码资格 | 尚未闭合 | 本次 Core 首个依赖 lint 阻断、前次 ContextCompiler 两处未证明关闭及下游既有 warnings、覆盖率至少 85%、exact head 和 ordered-parent synthetic merge 的 retained artifacts |
| target-host qualification | 未闭合 | authenticated host、独立管理员 anchor、实际 lock/CAS/fsync/目录/断电语义、provider/publication/cursor topology 和 recovery SLO |
| 真实长期学习与独立接受 | 未闭合 | real future-calendar windows、独立 snapshots/measurement、power、shift、retention、subgroup/privacy、unlearning、backup non-resurrection 和独立 semantic/operator acceptance |
| selection/activation/release | 未授权 | 各自独立的 gate 与 authority；当前继续 `NO_GO` |

## 9. 本地验证结果与明确限制

### 第二轮已取得的局部执行证据

本表只记录主审已确认的实际运行。模块冷恢复实现最后修改为 `cc052a777`；后续含两处指南澄清、Operations Bazel 输入声明及 SQLx 故障 fixture 类型适配 `6fa79c5eb`。源码观察的交付身份由 map-only 提交绑定；局部执行不能替代完整 exact-head/merge 资格。

| 验证范围 | 实际结果与适用范围 |
|---|---|
| Eval / Intelligence / Ledger / NDU / Shadow 五包 | **最终复跑 566 passed，2 既有 ignored**：Eval 246（224 lib+22 integration）、Intelligence 84、Ledger 120、NDU 78、Shadow 38。包含最后三个 owned cold-replay 等价/分叉/回滚回归及真实内核 fsync EIO 父进程实验。Ledger 的 host-growth worker 和 Shadow 的 parent-only process worker 各 1 项 ignored；Shadow 父进程实际执行其子进程覆盖。日志：`eval-round2-final-five-tests-retry.log`，exit 0。先前 563 项运行不再替代这次最终五包结果 |
| 七包及消费者依赖编译 | **882 passed，exit 0**：Eval 246、Intelligence 84、Ledger 120、NDU 78、Shadow 38、Memory 272、Operations 44。与上述五包结果重叠，不累加为 1,448。全新 target、Rust 1.95、debug=0、jobs=1、Core codegen-units=512，日志 `eval-round2-final-isolated-target-tests-retry.log`。Summary 444 skipped 包含过滤排除和既有 ignored；此次 Agentd/State 已编译但不计为已运行。初次因 SQLx fixture 类型错误失败，修复后重跑通过 |
| State 先前 scoped run | **216 passed**，保留先前源码/执行身份；不是此次七包运行。同次旧 NDU fixture 曾失败，随后 NDU 78 最终通过，不能把失败那次整体记作成功 |
| Eval / Shadow strict all-target Clippy | **最终通过，exit 0，`-D warnings`**：`eval-round2-final-strict-eval-shadow.log`。default 所有 targets 均实际检查；它不是完整三包消费者依赖链严格通过 |
| Eval / Intelligence / Agentd strict all-target Clippy | **最终重检失败，exit 101**：本次首先阻断于 Core `src/client.rs:3100` 的 8/7 参数，日志 `eval-round2-final-strict-three-packages-retry.log`。此前 `eval-round2-strict-three-packages-post-memory.log` 还观察到 ContextCompiler `src/v2.rs:99` 的 doc-comment 空行及 `:1995` 的 8/7 参数，未证明完整关闭。首次 final 检查因执行环境中断未完成，不记作通过。未加 lint exception；本次早期失败不证明下游没有其他 warnings |
| 文档契约与新增详细规范 | doc-contract CLI、18 项回归和 15 份 local Markdown/heading-anchor 检查通过；最后 clean head 的规范控制面入口包含对应文档检查，执行身份随 PR 交付 |
| 原始 runner caller 全仓扫描 | 等价扫描完整通过；8,824 份同一 corpus 比较结果不变，新单次 28.382 秒。该结果仍只是 source/API 控制面检查 |
| 首轮 remote head `3714b7e` | bootstrap/sustained workflow 曾成功；仅在其 manifest/source binding 与该 head 一致时使用，不能作为当前新 head 的资格 |

### 最后修改后的补跑结果和资格缺口

| 最终补跑 | 状态 |
|---|---|
| default product API / 具体 compiler-negative 边界 | **通过**：`eval-round2-final-api-surface.log`，exit 0。default 正向 Recorded/recovery API 编译成功，raw runner、低级 V2/V3、unarchived helpers、volatile journal 和未验证 publication 路径的具体错误码负例均拒绝；explicit compatibility raw 正例编译成功 |
| 隔离 compatibility fixture | **实际 1 passed，0 skipped**：`eval-round2-final-compat-fixture.log`，exit 0。原 OP-03 fixture 按原 materializer 复制至独立 `[workspace]`，保留全部三项断言，以 Linux 上的 seeded/pruned locked dependency graph 执行；不是仅检查 197 份 manifests，也不是完整跨平台兼容资格 |
| Agentd 相关 consumer filters | **6 passed，exit 0**：两类消费者的当前 distribution、owner/context/run/candidate、evaluator key/epoch/metrics 及 exact-use signature substitution。独立 Agentd 默认依赖图、`--lib`、六个具体测试名，166 项未运行；日志 `eval-round2-final-agentd-six-tests.log`。与七包合计 888，未宣称全 Agentd/workspace 通过 |
| Memory 全包及 migration 断言 | **272 passed**，包含 V2 fixture 的 migrations 1..15、历史数据/citations/revoke 及 shared-use 空集断言；已计入 882 |
| Operations 当前生产 writer/factory fixtures | **44 passed**，包括四连接逐一 `max_page_count` 读回和 `SQLITE_FULL` 原子性故障；已计入 882 |
| 最终 formatting / scoped fix | **`just fmt` 和九包 `just fix` 均 exit 0**。自动修复仅将 NDU CLI 100 次 bounded profile 的 50/95/99 percentile 写为 `div_ceil`，独立复核等价；其后再执行 `just fmt`。scoped fix 非 strict，不能记作零警告；Eval/Shadow strict 与三包阻断分别见上表 |
| Python/source-status/local deterministic summary | **197 项组合 Python 回归通过**：`eval-round2-python-final.log`。新源码观察及最终 head 的 14 项规范离线控制面命令、exit/log digests 和 summary 身份由 [草稿 PR #1307](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1307) 交付记录绑定；该入口只能产生局部控制面通过，不能设置完整 source/host/acceptance/release 资格 |
| measured coverage ≥85%、exact head、ordered-parent synthetic merge | **PENDING：无可替代的当前 commit-addressed 完整 CI artifacts** |

九包普通 fix 的完整日志打印 **237 个 warning diagnostics**；各 target summary 合计 247，其中 10 个是重复诊断，不能重复累加或当作 strict 通过。独立按 `3714b7e` 核对：Intelligence canonical 大枚举、28 项 lib-test `expect` 和 15 项 intuition-fixture `unwrap` 均是未变源码；Agentd 整个目录相对该基线未变，警告涉及 dead code、大枚举、参数数目和既有测试 panic 风格。Memory、NDU、Operations 的对应警告也来自原有代码或保留同一调用的行号位移。Eval/Shadow/State 未出现 warning blocks。更广泛消费者基线须单独整理；本次不将它们冒充新修复或已关闭的完整资格。

### 首轮历史本机结果

以下保留首轮截至第二轮入口的验证记录，便于复核修复沿革。它们不是当前候选新执行；其中 SQLite/deprecation 阻断已由第二轮源码处理，不能继续作为当前三包阻断原因。

| 验证范围 | 编写时结果 |
|---|---|
| `learning.eval` 全部默认测试 | **223 项全部通过，零跳过**，包括四项缓存/严格回放等价与篡改回归 |
| Agentd 本轮 scoped filters | **6 项通过**；这是评估相关 scoped consumer 验证，不是整个 Agentd/workspace 全量验收 |
| Shadow qualification 全包测试 | **38 项通过，1 项显式 ignored parent-only worker**；父进程跨进程测试通过，未新增 skip。新文件 anchor fixture 仅在本次 Linux 宿主执行，不证明跨平台或独立管理员生产存储资格 |
| Python 资格/控制面回归 | **182 项通过** |
| default/compatibility API boundary | **通过**，含针对具体边界的 compiler-negative fixtures |
| compatibility manifest isolation | **197 份 product manifests 检查通过**，`fixtureIsolated=true`；inventory 本身不等于 compatibility regression 已执行 |
| Bazel dependency lock update | **`just bazel-lock-update` 通过**，Cargo/Bazel 锁文件无需变化；补齐 Shadow Bazel test 已有 `ed25519-dalek` direct dependency。该结果不是 Bazel test 通过 |
| production library 严格 Clippy | **通过** |
| 文档文件/heading-anchor 检查 | **首轮通过（15 documents）**，含本报告及索引链接 |
| `learning.eval` strict all-target Clippy | **通过，零警告**；129 处 fixture `expect` 按 Result/Option 分别替换为保留失败上下文的显式 panic，全部断言保留，没有放宽 lint |
| evaluator/intelligence/Agentd 三包 Rust formatting | **通过**；既有格式整理为独立机械提交，随后按 CI 原范围执行 `cargo fmt -- --check` |
| evaluator/intelligence/Agentd 三包 strict all-target Clippy | **首轮未通过**：operations SQLite 构造和 collapsible-if；第二轮已引入保留四/五连接政策的中央 factory。本次首先阻断于上表 Core 一处，前次 ContextCompiler 两处未证明关闭；下游更多 warnings 另行记录 |
| Shadow strict all-target Clippy | **首轮未通过**：NDU deprecated re-export；第二轮保留兼容 wrapper 并修正内部调用边界，未放宽 warning gate |
| 完整 workspace 测试 | 未作为本次 scoped 结果宣称通过 |
| default-production measured coverage >=85% | 待最终候选的覆盖率证据 |
| exact head / ordered-parent synthetic merge | 待最终候选的 commit-addressed CI artifacts |
| 实际宿主/独立接受/发布 | 无可由本地运行替代的证据；相关 claims 保持 false |

完整源码资格须将 source commit/tree、ordered parents、commands、exit codes、logs/output digests、toolchain 和 coverage report 绑定到同一个最终候选。queued、pending、cancelled、skipped 或 infrastructure-invalid 不能记作通过。

## 10. 首轮非空 holdout 存储 profile 与性能优化

首轮补强的 profile 在 **512 个 holdout records 与对应 fence 历史**下执行写入、源恢复、copy-compaction 和 compacted successor 恢复，校验保留 state、anchor 和 use history。它避免把仅有空 journal/fence 切换的 profile 当成非空 holdout 恢复证据。下表保留首轮历史对照，不能移用于当前候选；第二轮在 `cc052a777` 的独立新 profile 于本节后文单列。

进一步性能优化前，本机这轮观测为：

| 阶段 | 优化前 | 优化后 |
|---|---:|---:|
| holdout 写入/消耗与 fence takeover | 234.095 秒 | 5.083 秒 |
| 源 CAS 文件 recovery | 1.412 秒 | 1.676 秒 |
| copy-compaction | 2.866 秒 | 3.365 秒 |
| compacted successor recovery | 1.350 秒 | 1.567 秒 |

这些值来自同一配置在本机的各一次 scoped profile，不是部署 SLO、跨宿主线性一致性证明或长期吞吐验收。写入观测约快 46 倍；恢复/compaction 没有改善，且会受并行构建和宿主负载影响。两次 profile 均保留相同 234,756 字节源文件、185,808 字节 successor、512 条 plan 历史，并通过 `retryPreserved`、`anchorPreserved`。优化后 profile digest 为 `8abb7280dbbe35fc6e4a9fab7c67057c56644d6911cddb86df44f33969e096a5`。

首轮写入优化的根因是每次 fence takeover 都重新按完整 registry prefix 重建 journal。locked-file adapter 现在可返回已逐帧验证的 native journal；owner 仍先校验当前 CAS record，再逐字段比较完整 snapshot，并恢复 owner 原本的容量策略。缓存不匹配时拒绝；没有缓存的 generic store 继续严格重建。缓存复制/比较每次为 `O(N)`，不是整份文件恢复的复杂度。v2 registry 的逐前缀摘要仍要求整集合哈希，完整 recovery 仍可能为 `O(N²)`；重复 generic recovery 仍可能累计为立方成本。更改这项 wire 合约须单独设计版本迁移，不能省略 prefix 验证来伪造线性性能。

第二轮继续消除了冷恢复的逐帧完整快照复制：同一个 canonical validator 为 live CAS 保留候选隔离，为 cold replay 移动已验证的快照；plan 仅追加 native journal 刚产生的一个记录，fence 保持非空 Vec 的原分配。反序 plan IDs、逐前缀严格恢复等价、重复帧、重算 checksum 的等长分叉、旧备份回滚拒绝和失败后恢复原历史的回归均保留完整状态检查。冷恢复成本由 `O(B + N² + F(N + 1))` 降至 `O(B + N² + F)`，现有 sorted-table wire 摘要仍保留二次项。该变化不省略任何 checksum、canonical transition、最小 anchor、sync 或完整历史检查，也没有修改 wire。三个新增回归已包含在最终五包的 566 项通过中。

第二轮同配置 `1,024 attempts / 512 plans / 512 fences` 的前后各一次本机 profile 均 exit 0：

| 阶段 | owned replay 优化前 | 优化后 |
|---|---:|---:|
| holdout 写入/消耗与 fence takeover | 4.211 秒 | 3.898 秒 |
| 源 CAS 文件 recovery | 1.474 秒 | 1.233 秒 |
| copy-compaction | 3.106 秒 | 3.001 秒 |
| compacted successor recovery | 1.359 秒 | 1.224 秒 |

attempt journal 均为 7,168 events / 1,103,342 bytes；holdout 源/successor 仍为 234,756 / 185,808 bytes，`retryPreserved`、`anchorPreserved` 及完整状态等价检查均通过。优化后 attempt write/recovery 为 0.422 / 0.341 秒，优化前为 0.332 / 0.308 秒，因此不能宣称所有路径都更快。保留的原始 JSON 为 [storage-profile-before.json](audit-evidence/20261001/storage-profile-before.json) 与 [storage-profile-after.json](audit-evidence/20261001/storage-profile-after.json)，内嵌 `profileDigest` 分别为 `f7b4c3a23a8968daf43c0b9dc521f788c275fe913429db41420a3e1af603fc6b` 与 `c6c367ad3e1adf61cbbfc9094045ecfc6a06a432199309c67ea449afaa86fae1`；原始文件 SHA256 分别为 `752e45214d6617265b5483c44f1e816b1f60c81084bf31a7c59e67fea93ad19c` 与 `a8b541683085e3aee76d9974622e8c57b0df22cf1c51fd6afb8dd86f176a63c0`。单次本地数值不能分离宿主负载影响，不是统计性能保证或 target-host SLO。

独立复审新增了容量策略和 genuine sealed receipt 跨 prefix 拼接攻击；四项回归覆盖相同/新 fence 的 strict 等价、容量策略规范化、元摘要漏检的 record 篡改，以及合法 seal 但错误 registry prefix 的拒绝。未更改原有 wire 版本或 digest。

优化只能减少重复 replay/snapshot/encoding 工作，不得削弱 sync、anchor acknowledgement、canonical transition、one-use holdout 或完整历史检查。优化后须保持同一非空 profile 的 state/anchor 对等检查，并记录新的 write/source recovery/compaction/successor recovery 结果。

## 11. 剩余可执行工作和终止标准

两轮 scoped 复审已将确认的模块缺陷落实为源码与回归，第二轮又针对 seal、原始 propensity、最终 archive、内核 fsync 故障、控制面执行闭包和 Cargo/Bazel 输入独立检查；最后的恢复复制优化及 SQLx fixture 适配也经独立审核。最后实际局部测试共 888 项通过。报告分别保留依赖 lint 和外部证据缺口。最终 map-only 提交将 map/status 绑定至不可变源码观察；最后 clean head 的规范离线回执由草稿 PR 交付记录列出。完整源码资格仍须将完整 matrix 的 commands、exit/log digests、toolchain 和 measured coverage 绑定至同一候选。新的 docs、lexical facts 或局部回执不能直接设置 `sourceQualifiedByThisRun`。

项目级规范仍有一项未闭合的跨 registry 关系：[MODULES.json](../MODULES.json) 的 `learning.eval.writes=[]`，而 [DATA_AUTHORITY.json](../../data/DATA_AUTHORITY.json) 将 `ndu_well_posedness_certificate_v1`、`operator_applicability_certificate_v1`、`regularity_profile_v1`、`support_audit_receipt_v1`、`candidate_evaluation_receipt_v1`、`conformance_receipt_v1`、`algorithm_fault_receipt_v1` 的 schema owner 和 authoritative writer 指定为 `learning.eval`。两者未机读说明空 bootstrap 列表与 qualification 目标域的关系，现有全局验证器也未比较两侧 writer 集合。本轮不改变任何 registry authority；后续须由项目规范协调明确该关系和一致性验证。这些目标域声明不证明已部署实现，更不授予生产写入权限。

全局检查仍未闭合。第一次浅历史下的“缺少对象”诊断已由完整 fetch/deepen 复查修正：对象 `b621768b70a09d56626bb8a2c331e3dc424e6a4d` 已可解析，当前 `hepta-docs.py verify` 实际失败为 **`cleanup base is not ancestor`**。这是当前 cleanup contract 与交付 ancestry 的真实不满足，不能继续归因于缺对象，也不能把下载成功当作 gate 通过；须由规范拥有者协调正确 baseline/lineage。

`hepta-lane-e-closure.py verify` 当前返回 **10 项 findings**：1 项 learning.operator operation 闭世界集合漂移、1 项 traceability case 闭世界集合漂移及 8 项 Agentd legacy learning-writer bypass。旧 OP-03 函数映射问题不再计入当前结果。canonical archived qualification API 的 source/map/trace 已补齐，但整体 Lane E 仍失败；没有为通过而删减 case、放宽 operator 闭世界规则或修改跨模块 writer authority。

本轮更新了源码/资格控制面 inventory 与验证器；trusted CI 资格仍要求将对应 bootstrap control-plane 变更独立重堆叠、审阅并与 trusted base 的字节身份对齐。仅在模块候选中出现修复不能宣称已经通过可信控制面的最终资格。

首轮的 NDU deprecated re-export 和 operations SQLite factory 阻断已在第二轮处理：兼容 public API 保留，四/五连接政策显式注册，durability/corruption 语义保持，Cargo/Bazel 依赖检查按原 gate 执行。最终三包 strict 本次首先阻断于 [Core client](../../../codex-rs/core/src/client.rs) 一处现有 lint；此前还观察到 [ContextCompiler v2](../../../codex-rs/hepta-context-compiler/src/v2.rs) 两处，未证明完整关闭；九包普通 fix 又显示更广泛的既有消费者 warnings。它们均保留为完整源码资格缺口，不能把 Eval/Shadow 严格通过写成整个链条通过。

源码资格须分别满足 default product API、隔离 compatibility、owner/consumer/process faults、typed cold recovery、capacity/checkpoint、严格 lint/format、measured coverage 和 source/ordered-parent merge。若新修复改变相应路径，复跑相应 scoped 检查；不要把旧 working-tree 的成功嫁接到新 commit。

外部剩余工作由独立拥有者提供：真实 host/anchor/provider/publication/cursor 的身份与拓扑、存储断电和恢复测量、至少两个真实未来窗口和三个独立 snapshot、retention/change-point/power/subgroup/privacy/unlearning/backup 非复活，以及 semantic/operator acceptance 和后续独立 selection/canary/promotion/release。`UNBOUND_EXTERNAL` 能力不得因 trait、fixture 或 repository CI 存在而变成已认证实例。

本轮终止标准是：本次范围内确认的缺陷已落实修复并有对应验证；尚未建立的证据被明确保留；最终候选可交给独立 reviewer 和资格执行。该标准不声称未来不可能发现新问题，也不把持续优化请求解释为虚构外部时间、真实收益或发布权限。

## 12. 2026-10-01 CI 终态复审与第三轮优化

本节是首两轮后的 root 复审，没有新增独立审核者。最新 main 为 `997e7beef8151160065df36b024bc8da5c989e93`；相对此前 main 的已接受变化主要属于全局 CI/文档 gate，模块源码、专属文档及 status 脚本没有变化。下面的 CI 失败属于草稿 PR 的历史候选 `5ca584996a43b9c9545d73aa14351aa7622958f0`，不能归因于更新后的 main，也不能移用于本轮新候选。

| 历史候选检查 | 实际终态及含义 |
|---|---|
| convergence 36805266722 | identity、default/compatibility compile、fault recovery、consumer tests 通过；coverage 和 format-lint 失败，完整资格失败 |
| exact trees 36805266695 | head 的前 15 个命令通过，停在 default coverage；后续 compatibility coverage、strict lint、format/diff 未执行；merge job 也失败，未核定其具体故障日志 |
| sustained profile 36805266525 | 成功，只代表该历史候选的 profile |
| trusted bootstrap 36805266707 | 成功，不能证明本轮新增控制面字节已获 trusted base 接受 |
| development docs 36805266485 | source/cleanup commit 不是祖先；这不是缺对象，也不是已更新 main 的 editorial gate 结论 |
| Lane E 36805266796 | 仍有 10 项 findings：operation 闭世界 1、traceability case 1、Agentd legacy writer bypass 8 |

### 12.1 确认的问题与修复

历史候选 default coverage 在相同 11,621 行范围内覆盖 9,780 行，即 **84.16%**，真实低于 85% 门槛。非空 durable storage profile 的 271 行全部未覆盖，是实际验证缺口。新增两个 native binary 回归执行真实七阶段写入和重新打开、完整 pending 检查、文件长度与报告计数对应、profile digest，以及已有 journal 的拒绝和原字节保留。覆盖率不是仅靠文档或 profile 成功推断。

两次并行 libtest coverage 分别在不同 CAS recovery 回归返回 `Busy`；进程创建和文件锁别名生命周期是调查方向，尚未证明生产缺陷的根因。没有更改生产锁释放或恢复语义。CAS fixture 改为独占预留的私有临时目录，避免共享平面路径和旧文件碰撞。默认 coverage 改用 native nextest 进程隔离、4 个线程、**零重试**；仍为 all targets、no default features、85% 门槛，没有排除文件、弱化断言或混入 compatibility 覆盖。compatibility qualification 仍独立执行。

另有两个 Python 仓库检查只识别 `.git` 目录，误跳过合法 worktree 的 `.git` 文件；初次 197 次执行有 4 次跳过（导入复用导致同一检查重复出现）。修复检测后 **197 次执行全部通过、零跳过**，不把执行次数称为唯一测试数量。

### 12.2 本轮实际验证与完成度

| scoped 检查 | 本轮实际结果 |
|---|---|
| `just test`，零重试 | 248 通过，0 跳过 |
| default native-nextest measured coverage | 10,001 / 11,621 行，**86.06%**；248 通过，0 跳过；profile 207 / 271 行 |
| owner all-targets strict Clippy | exit 0，`-D warnings` |
| owner scoped `just fix` / mandatory `just fmt` | 均 exit 0；格式后执行过的 Rust token 身份相同，没有仅因格式重复 Rust 测试 |
| learning.eval Python regression suite | 197 次执行通过，0 跳过 |

详细命令、工具版本、实际日志摘要、失败的 libtest 运行及历史 CI artifact 身份保存在 [ci-followup.json](audit-evidence/20261001/ci-followup.json)。本地 nextest 0.9.146 / just 1.58.0 与 CI 的 0.9.103 / 1.51.0 不同；Rust 1.95.0 和 cargo-llvm-cov 0.9.1 相同。实际执行输入和格式后源码 token 对应保留，最终源码观察由后续 map-only rebind 与 PR 交付记录绑定；这些本地结果不能写成新不可变 head/merge CI 已通过。

模块详细开发文档、核心实现和 scoped 回归已经形成可审查的实现闭包；本轮关闭了默认覆盖门槛和 worktree 检查缺口。历史 format-lint 此次实际先失败在 ContextCompiler v2 的两个 lint（doc-comment 空行、8/7 参数），而非此前本地首先观察的 Core lint；owner strict 通过不代表整个消费者链 strict 通过。全量同一候选 matrix、新控制面的独立 trusted bootstrap/restack、项目 registry/lineage 协调及真实 target-host/未来窗/独立验收仍未闭合，不能用百分比估计发布完成度。

本轮范围内最后复查没有新增已确认功能缺陷；这表示当前可执行修复收敛，不表示未来不可能发现优化。继续保持 `DENY_ALL / NO_GO`；source full qualification、外部认证、activation、promotion 和 release 均未授权。
