# learning.operator 对抗审计与完成度报告

审计日期：2026-09-30（执行环境日期）；文件与分支的 `20261001` 命名保留。
范围：`learning.operator`、关联开发文档、Agentd 只读消费边界及资格证据链。
本报告供独立 reviewer 评估已核实的源码行为、执行证据、修复和真实剩余工作。
代码来源整合 `audit/learning-operator-20261001` 与 `codex/learning-operator-authoritative-convergence-20260930`。
保留离线算法修复与 owner-bound 能力，未以删除功能、清空真实 blocker 或降低验收条件来取得闭合。
源码导航 commit：`986eae8438285bf6d9a97e5f12ab6a3b1240afea`（tree `6352a2bdf4785ba1e18ffc9be1124b10b4f871e7`）。该远端源码树与本地审计候选 `a318fec911d96af3ca755fd7c5b7fac8eb03a4fa` 完全一致；原本地提交历史见 [LOCAL_AUDIT_HISTORY.md](learning-operator-audit-20261001/LOCAL_AUDIT_HISTORY.md)。导航身份不构成当前候选执行 receipt。

## 1. 技术开发文档确实存在

本模块有详细开发资料，覆盖身份、算法、默认 API、数据/工件、信任、容量、恢复、测试及资格边界。

| 文档 | 作用与本轮核验 |
|---|---|
| `docs/modules/learning.operator/TECHNICAL.md` | 模块定位、实现结构、原生/协议差异、事务及剩余集成义务。 |
| `ADMISSION_CONTRACT.md` | canonical profile、单次 final-use capability、selection window 与 host currentness。 |
| `DEVELOPER_GUIDE.md` | 默认 capability 调用顺序、兼容路径及 `just test` 本地检查。 |
| `COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md` | V1/V2/V3 边界、资源模型、回归性能与 shadow 限制。 |
| `OPERATIONS_RUNBOOK.md` | 准备、撤销、停止、恢复身份、精确前驱回滚及资格操作。 |
| `STATUS.json` / `STATUS.schema.json` | 单一机器状态及 schema；默认完整循环接线保持 false。 |
| `SCHEMA_COMPATIBILITY.json` / `IMPLEMENTATION_MAP.json` | 版本迁移、操作/测试路径、源码观察与真实 gap。 |
| `codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md` | 原生符号、数值行为、载荷、兼容及 host 义务。 |
| `qualification/module-execution-dossiers/detail/learning.operator.md` | 可执行实现设计与案例；额外场景未冒充 OP 注册表 ID。 |
| `docs/learning/HOLDER_BELLMAN_SPEC.md` | 连续算子目标、适用假设、误差预算、科学与工程扩展边界。 |
| `docs/readiness/LEARNING_EVALUATION_EXECUTION.md` | 因果/纵向评估、独立观察、未来窗口与 unlearning 要求。 |

文档已纠正直接 V3 调用指南、持久化先于评估的顺序、V1 pin 隐藏说法和三样本 tail 性能口径。
`existing_bound` 只表示源码根存在；文档、函数和工作流存在都不是当前执行通过或产品激活证明。
检查了本模块文档链接、JSON 结构、状态投影 hash、冲突标记及 source/test 实际位置。

## 2. 模块在项目架构中的位置

模块属于 qualification plane 的 `stateful_shadow` / `slow_learner`，在慢路径生成有界候选。
`learning.ledger` 保有决策、独立结果、冻结源集合、修正/撤销及其 durable owner 身份。
`learning.operator` 验证已冻结输入并构造目标、有限表格算子或 action-conditioned 世界模型。
`learning.eval` 负责独立评估；选择、registry、create-only 工件字节和当前性由各自 owner 提供。
Agentd 的 evaluated `PinnedCognitiveRanker` 是实际只读消费者，对每次 read 刷新配置的 owner witnesses。
通用 `coordinate_learning_operator_shadow_v1` 只编排端口，不拥有 ledger、evaluator、store 或发布权限。
目前它只有 fixture-port 状态机测试，尚无真实 owner-port 实现与默认 runtime caller 的完整接线。
因此 `shadowCoordinatorImplemented=true`，`defaultLoopWired=false` / `defaultProductLoopWired=false`。
`productionImplementation`、`productExecutionProved`、独立接受、activation 和 release 均保持 false。

## 3. 已修复的具体问题

### 3.1 有限 sensor geometry 与摘要身份

修复 fill distance、separation 与 mesh 的舍入方向：fill/mesh 向上，separation 向下，避免低估。
Qualified reduced 模式对完整原始候选集合重测覆盖，不让 working-set reduction 隐藏离群点。
摘要绑定完整 canonical candidate design，包括未被选中的点；不同几何不能仅凭相同 design label 共用身份。
统一 exact V2 与兼容 V1 的几何字段和 V2 commitment，保留 nearest/ties-to-even 的边界回归。
`hull_digest` 明确为点集合 commitment，有限候选 fill 不再被描述为连续域覆盖或几何 hull 判定。

### 3.2 Tabular 统计、证据与载荷

完整 sensor×action support、正 sample count、unique evidence 和所有 identity digests 必须成立。
Raw、indexed、persisted 预测共享 bounded artifact 校验，拒绝不可达到的 mean/min/max/count 组合。
训练摘要绑定 `minimum_samples_per_cell`，避免不同准入门槛得到相同训练身份。
原始行 evidence 的全局唯一性与冻结 source-record 集合严格匹配，不能重标同一观察来增加支持度。
旧训练 digest 依独立 payload pin 保留，不声称能由载荷剩余 sufficient statistics 重新推导原始训练行。

### 3.3 World model 数值、完整性与资源

V2 方差改用精确中心矩 `C=n·Σx_raw²−(Σx_raw)²`，再按固定点规则量化，常量观察严格为零方差。
Confidence radius 从未舍入中心矩计算，避免 variance 已显示零时把小尺度不确定性错误抹除。
Public fitted Arc 被替换、`Arc::make_mut` 复制、calibration/lineage/work metadata 篡改会被私有 seal 拒绝。
Branch storage 仍共享，预测保留 indexed 查找；未为完整性反复复制整份 branch 数据。
Memory preflight 覆盖 ID 堆文本、input Vec capacity、group/tree、临时行、摘要和 Arc 转换重叠。
操作预算覆盖 sorting/group/branch 与完整输入摘要，state/action 超限早拒，摘要后复查 deadline。

### 3.4 全流程资源与默认 API

Sensor fingerprints、tree、reduced clones 和完整候选副本在 expensive work 前纳入 shape/operations/bytes 预检。
Tabular preflight 不再固定按 128 bytes/sample 低估长 ID；覆盖排序 scratch、分组与 evidence 数组。
共享 fit context 保持累计 operations、同时驻留 reservation、同一 elapsed deadline 和 cancellation token。
默认 crate root 为 `authoritative_lib.rs` 的显式 allowlist；raw fit/predict 与 direct V3 仅在兼容 feature 导出。
默认测试使用 formatter-stable 的 crate-private aliases，未恢复默认公开 raw API，也未用整 crate warning suppression 掩盖问题。
Bazel 配置显式对齐 authoritative crate root；实际 Bazel 执行是否通过仍需完整 build 证据。

### 3.5 Final-use、selection 与信任

Opaque capability 非 Clone 且单次消费，绑定 durable owner、dataset/generation、authority/stop epoch 与绝对 deadline。
Issuance/use/handoff 的 deadline 是 exclusive；clock regression、真实 elapsed 到界及最后 cancellation 都拒绝。
同一个 monotonic fit context 从 issuance 延续到最终返回，静止的 caller witness 不能掩盖真实耗时。
Tabular 候选保留训练 trust digest，selection 不可重新贴一个无关 trust 身份；world request 必须绑定实际 owner trust。
Opaque tabular load 返回 `SelectedTabularOperatorV1`，load 与每次 predict 都检查 selection window。
Selected world-model prediction 同样检查 selection window，不仅依赖 model retention expiry。
静态 wrapper 不能自行发现后来撤销、registry/stop 变化；host 每次最终使用仍须刷新实际 owner witnesses。
最终复审又发现同步 fit 可跨过签名证据 expiry，而传入 witness 仍停在旧时间。
补丁以 `max(witness_time, issue_time + monotonic_elapsed)` 检查 owner/row 签名 TTL，候选保留实际 publication 时刻。
时间推进不伪造刷新 identity/epoch witness；新增三项回归及默认/兼容完整模块测试均通过。

### 3.6 Shadow coordinator 与恢复

所有阶段前后取得 trusted host clock，检查 monotonic time、deadline、依赖 receipt expiry 和未来时间伪造。
Evaluation freeze 严格晚于实际 fit 完成，不能仅凭两个不同 dataset digest 假装 future window。
Persistence 失联或返回不匹配 receipt 时产生 `PersistenceOutcomeUnknown`，保留 run/candidate/selection 恢复身份。
不加载、不盲目回滚不可信 reported object，不把未知写入结果当可安全重新执行。
Verified persistence 之后即使 deadline、load、shadow、currentness 失败，也要求精确前驱 cleanup。
Cleanup 失联或错误前驱产生 `RollbackFailed` 并保留 verified storage identity，不返回成功 terminal outcome。
Terminal audit 绑定 selection reason、storage、rollback 及相关 evidence，并绑定 producer 与前驱/候选 generation。
即使 opaque receipt digests 相同，改变 producer/generation 仍产生不同 audit；实现拆成入口/types/validation/rollback/tests。

### 3.7 资格证据一致性

修复 gate command 与 retained stage command 的绑定，区分 command 和说明性 purpose。
Stage/gate 绑定 source/tree/run/attempt，readiness 使用同一 stage directory，禁止跨 run 拼接。
Qualification/readiness 交叉验证 base、merge、workflow、target 和输入 hashes。
重新构建 deterministic merge tree 及固定 metadata SHA，拒绝只有合法 parents 的任意 tree。
Gate target 与 compiler target 必须一致，相关拒绝回归已纳入证据测试。
最后补齐 `load_stages` 的 execution identity 参数，并增加旧 run `exact_source_receipt` 拒绝回归。
这些检查提高证据内部一致性，不能把自生成 hash 升格为独立科学或产品接受。

## 4. 当前验证证据及限制

执行结果按各自范围记录；focused/harness 成功不能替代未完成的产品链和工作流资格。
原始记录及源码字节承诺见 [validation.json](learning-operator-audit-20261001/validation.json)。两个常规测试 skip 分别为显式性能矩阵和 owner 全流程 profile，均已单独执行通过。
部分 Cargo/nextest 日志在实际编译成功前含 rustc 动态库诊断；保留原文，结果依据实际退出状态与测试汇总。

| 验证 | 结果 | 能证明什么及限制 |
|---|---|---|
| 默认/兼容 operator 常规测试 | 每个配置 107 passed，2 skipped | 有界源码行为；两个 skip 未计入通过。 |
| 默认/兼容 check、strict Clippy | 通过 | 本模块相应配置编译与 lint；不替代整个 Agentd build。 |
| Coordinator 源码 harness | 12 passed，0 skipped | 直接加载当前 coordinator 源码及真实 `codex-hepta-types`；不等于 Agentd/app-server/V8 产品 build。 |
| 真实 Git 证据回归 | 13 passed | 合成 Git 场景下 receipt/readiness 拒绝行为，非独立外部接受。 |
| 源码变异 | 9/9 killed，8 个未修改目标基线通过 | 只接受目标断言失败；工具错误、编译失败、超时和崩溃不能计作 killed。 |
| API 消费者检查 | 14/14 passed（2 positive、12 compile-fail） | 验证默认隔离、必填当前时间和私有 selected loader；负例必须命中特定 Rust 诊断。 |
| 本机 debug 性能矩阵 | 通过，210.66 秒，7 项规模 | 回归观测；每项 2 warm-ups、7 observations，无 shipping capacity claim。 |
| Whole Agentd / Bazel | 磁盘容量受限，未完成 | focused tests 或源码 harness 不替代全依赖链 build/test。 |
| 完整 protected/authoritative workflow | 未取得统一成功 receipts | exact-source、deterministic merge 及真实 main merge SHA 必须各自有完整记录。 |

默认 nextest 60 秒限制曾中断性能矩阵；显式 `learning-operator-performance` opt-in profile 允许 10 分钟后完成。
测量为本机 debug 回归结果，sensor 1K/4K/8K/16K 与 tabular 100K/500K/1M 共七项；已知 medians 如下。

| 规模 | Median |
|---|---:|
| Sensor 1K | 38.680 ms |
| Sensor 16K | 258.483 ms |
| Tabular 100K | 1.140782 s |
| Tabular 500K | 6.200454 s |
| Tabular 1M | 13.071725 s |

这些数值没有 accepted host/device 身份、充分 tail 样本或独立容量接受，不证明 p95/p99 或 shipping bounds。
当前未取得独立科学接受、真实 future-calendar efficacy、target-host 容量或 operator 部署接受。

## 5. 完成状态与兼容风险

### 跨 owner 资格入口仍是实际 blocker

`codex-rs/hepta-intelligence/src/plasticity_product.rs:488` 通过公开 signed V2 从 raw bundle 得到 Eligible，并写 durable proposal。
`codex-rs/hepta-agentd/src/intelligence_evaluation.rs:124` 同样得到资格 digest，进入 evaluation-consumption / EvaluationAdmitted Continue。
这两条路径具有有效独立签名、expiry/controller/host trust 检查，但输入 metrics 与局部 holdout registry 仍可由调用方提交。
调用方未被强制经 sealed `ProductEvaluationRunnerV1`、fenced CAS holdout 消费和 durable qualification sink/publication。
公开 `prepare_self_evolution_selection_v1` 还通过内部 signed V3 从同类 raw bundle 生成 prepared selection，存在相同资格边界缺口。
`DENY_ALL` 仍保留，因此它们不授部署权限；但签名真实性不能代替真实测量、holdout 消费或耐久资格发布。
该迁移需要 sealed product receipts、最终使用时重新认证及真实 runner/fsync sink fixtures，并封闭公开 raw decision 路径。
本轮没有扩大为无法完整验证的 learning.eval 迁移；Lane E 资格仍 failed，不将该 blocker 改成文档问题或外部科学验收。

文档已详细且本轮真值收敛；bounded reference、tabular/world model、owner-bound 能力与只读 ranker 有实现。
完整模块交付尚未闭合：真实默认训练循环接线、canonical wire adapters 和全部候选资格证据仍缺。
Native V1 名称不等于 canonical JSON 协议；未知字段、wire lifecycle 与 round-trip 证明不能由 native payload 测试代替。
V2 digest domain/完整输入承诺改变新建候选身份；旧 pin 按原字节保留，重建必须重新独立评估/选择。
Private fit-owned seals 使外部 struct literal 构造结果不再可用；兼容调用应经明确 feature 和受审 API 迁移。
`OpaquePinnedTabularArtifactV1::load(now)` 及 selected `predict(..., now)` 需要调用方提供可信当前时间。
Estimated bytes/operations 是保守工程模型，未替代 allocator/RSS/cgroup 或实际目标机测量。

## 6. 具体下一步与停止边界

1. 排除磁盘限制后执行全 Agentd/Bazel 与统一候选 authoritative CI；保留全量工作流、synthetic merge 与实际 main merge 的独立记录。
2. 以 sealed receipts/use-time reauthentication 迁移真实评估消费者，加入真实 runner/fsync fixtures 与 raw API compile-fail、缺失/篡改/过期/replay 拒绝覆盖。
3. 实现 coordinator 的真实 owner ports 和 runtime caller；一次跑通 freeze→fit→evaluate→select→persist→fresh-process→rollback。
4. 加入 durable run dedup、崩溃恢复/reconciliation 与当前撤销 witness；未知持久化不能靠重复启动解决。
5. 为 registered applicability/sensor/regularity/Bellman 协议实现 canonical wire adapters，验证版本、bounds、round-trip 与迁移。
6. 用 accepted host、warm-up、充分样本及真实内存观测完成 performance/resource qualification，给出 measured shipping bounds。
7. 由独立 owner 提供适用假设、科学校准、因果/未来窗口收益、retention/unlearning 与部署接受 receipts。

本报告不自封 100% 完成，也不保证未来不会出现新问题；结论限定于已审范围与已记录证据。
完整接线、wire parity 或外部接受未闭合时，保持对应状态 false，继续明确的剩余工作。
