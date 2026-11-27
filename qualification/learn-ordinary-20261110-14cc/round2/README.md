# LEARN 第二轮：普通 Q24 任务、原 CURRENT 与冷读取

## 结论

本轮补齐了具体的普通 Q24 任务生产 factory、原始 source 的持久输入/结果、受真实 CURRENT 约束的 Feature/control 和私有 Cell、只读 Observer，以及不保留内存 completion token 的前序历史恢复。原生测试实际执行了签名任务 A、原训练器产生的候选权重、不同输入/新会话 C，以及原文件重新打开。

**工程验证通过；用户要求的完整 LEARN 链保持 `HOLD_ORDINARY_CHAIN_NOT_ESTABLISHED`。** 普通入口测试使用明确标注的 issuer、Dataset target 和 artifact-selection 夹具。独立 B/旧能力保留面板、适配冻结 SGD 的原 Proposal 协议、完整生产 stage-owner 实现和实际 daemon/Root 双进程冷重启尚未建立。真实训练损失下降和候选被 C 读取，不能推出独立质量评价及原 Selector 已批准采用。

- 完整普通链：**0**。
- 完整正向采用实例：**0**。
- 完整普通 NoUpdate/回退实例：**0**。实际 trainer NoUpdate 与父模型保留消费分别有通过的工程用例，但不能拼接成同一次原始注册的整链实例。
- 多时间窗口持续收益研究：**未启动**。

本目录保留本轮完整结果，不覆盖上一轮证据。上一轮固定源、维护与测试记录仍在父目录；其结果没有转移成新源码的通过结论。

## 固定来源与验证

行为测试源码为 `bbab98d805f5c44c1a70a91f0dfd98821adddecc`，树为 `e11487778d16d8eb30900e2c5dcc62e39372cf41`。原生执行和源码变异检查均核对了前后干净的同一 HEAD/tree。

| 验证范围 | 结果 | 明确排除项 |
| --- | --- | --- |
| 六包 native 组件切片 | **510/510**，0 failure / error / retries | 终端摘要另有 1,068 个未选入用例；不是六包全量测试。 |
| 实际 EUID 0 Root 组件 | **6/6**，0 failure / error / retries | 902 个未选入用例；不是 daemon/Root 整链冷重启。 |
| 两组 native 唯一用例 | **516**，交集为 0 | 子进程输出未重复计数。 |
| 源码闭集/变异检查 | **63/63** | 结果绑定同一固定源码。 |
| 全仓调用闭集 | **211 边界、215 保护条目、171 个独立保护文件、6,223 Rust 文件** | 证明本身不授予任何 authority。 |

六包实际分布为 agentd 211、automation 55、intelligence-eval 2、learning-artifacts 22、learning-ledger 6、neuron 214。

原生门禁使用 ai395 的实际 Rust 执行，六包运行 `just test`，0 retries；helper 在同一源码构建并在末尾再次核验。Root 切片单独验证实际 UID/EUID 0，仅运行六个明确的父测试。测试筛选之外的用例数量保留在原始终端摘要中；通过数不包含这些筛选排除项，也不把子进程日志重复计入父测试。

维护遵守仓库的“先测试，再 fix/fmt，之后不重跑测试”顺序。四包 `just fix` 成功；第一次 scoped fmt 因隔离 Git 对象库缺少原基线 tree 而退出 2，原失败日志保留。补入原基线的 19 个缺失 tree 对象后只重试 fmt，未重跑 fix。fmt 与其后的 `cargo check --tests --bins` 均退出 0。44 个原生 postimage 的长度、SHA-256 和 Git blob 与本地逐一相符，保存在 `13880c9fca1a3ce89df0a2720f385137c7abe867`。独立只读审阅未发现生产行为变化；唯一非格式变动是测试中删除一次最后使用时的多余只读句柄 clone。随后 `fde7c2ae0e7874b101563fea6bad394bbf899f03` 仅对齐 81 个 CALLERS 和 15 个 QA 字符串标记，静态读回保持全部权限、caller 集合、禁止项、校验顺序和 Rust postimage。维护后未运行行为/变异测试或全仓 caller 扫描；516 个 native 用例与 63 个源码检查的行为结论仍明确绑定维护前的固定 `bbab`。

## 同一候选中的实际改动

### 普通任务 source 与真正 native 执行

[circuit_q24_task_profile.rs](../../../codex-rs/hepta-agentd/src/circuit_q24_task_profile.rs) 和 [config_q24_circuit_task.rs](../../../codex-rs/hepta-agentd/src/config_q24_circuit_task.rs) 把原 host 提供的已发布任务、文件/witness、模型、Circuit routes 和控制 owner 装配进正常签名 ObjectiveStart/Circuit 路径。它们不预制 operation ID、不从公开方法直接提交原始任务，也不生产 Root grant 或选择签名。

[circuit_task_source.rs](../../../codex-rs/hepta-agentd/src/circuit_task_source.rs) 保留完整原 RunStart、dispatch 产生的 operation ID、真实 Cell 输入及 sealed Circuit completion。claim 与 completion 分别经过原 journal 和独立 witness；Pending 不被重新发明为一项新工作。已完成 publication 可读回原 record、输入、结果、模型 bundle 和 checkpoint，并继续检查当前撤回状态。

[cell_composed_q24_feature.rs](../../../codex-rs/hepta-agentd/src/cell_composed_q24_feature.rs) 实际执行已加载 Q24 模型的同一 hidden/head 算法，检查模型、权重、组件、encoder/head、数值和状态 schema 的完整绑定。实际 Cell admission 才能绑定 [feature_control.rs](../../../codex-rs/hepta-neuron/src/feature_control.rs) 的 durable control。未知 dispatch 保留 Pending；过期/撤回与不确定提交保持失败，不重新推断补齐。

Feature 当前是明确的 reset-only profile；非空 checkpoint 输入被拒绝。其实际 wall interval、queue 与已分配容量统计不构成全流程 CPU、RSS、energy 或独立任务质量证据。

### 原 CURRENT 与私有状态

[circuit_feature_current.rs](../../../codex-rs/hepta-agentd/src/circuit_feature_current.rs) 只能由原 Ready initial/update publication 构造，保留实际 Generation journal、`LiveGenerationCurrent`、原选择与 FinalUse 检查。普通 Feature profile 必须提前进入原 target.task_digest，不能将任意已有任务 grant 改释成新的 profile。

私有 Cell 使用独立的 guarded journal header，绑定原 scope、frontier、writer epoch 和 CURRENT。读、admission、commit、fsync/witness 之后都重查原 CURRENT；撤回导致已写入结果不确定时不宣称提交成功。旧 unguarded open 不能重开 guarded 文件。

真实 writer 只交给普通 Q24 factory。公开的 `PublishedCircuitCellOwnerV1` 和 `CircuitTaskSourceReadbackV1` 只读；版本 drain 留在原 `PublishedCircuitFeatureTaskV1`，并要求同一 owner、真实 Cell 完成、source 前后读回及原 drain ACK。Observer 无法获得 Cell commit、source withdrawal 或版本 drain 写能力。

### 原评价签名与阶段责任

[neuron_cell_evaluation_owner.rs](../../../codex-rs/hepta-agentd/src/neuron_cell_evaluation_owner.rs) 消费 host 已授权的原 Evaluator key、完整 signer/controller/trust 和冻结计划，仅为 native runner 的 sealed execution request 持久签名。它在签名前落盘 claim，完成后落盘准确 payload/签名并取得独立 ACK；恢复读取原始字节和原始有效期。Pending 不重新签名。新增 enrollment 查询只校验原已注册身份，不通过试签名制造 authority。

该 owner 不提供 B/retention 数据，不替代原 qualification 签名或发布 sink。它保存的是准确签名 payload 与证据；若 native runner 的原执行 body 仍 Pending，不能仅靠签名 journal 重构 body 或清除未知效果。

| 责任 | 本轮实际保持的边界 |
| --- | --- |
| Training | 原冻结规则和实际 durable optimizer；候选或明确 QuantizedWeightsUnchanged；不决定质量和采用。 |
| Evaluator | 原 sealed 执行请求、注册身份、签名 journal 和有效期；真实 B/retention 材料仍由独立原 owner 提供。 |
| Selector | 现有原 signed selection 与当前 trust 校验保持；测试选择签名明确标注夹具，不能计作真实采用决定。 |
| Observer | 从实际 source、私有 Cell 和 CURRENT 读回 Selection/NextUse 的无签名观察；没有训练、提交、撤回或 drain 权限。 |
| 版本 owner | 原 artifact/CURRENT/FinalUse 的 prepare、publish、drain、recover；模型 manifest、前序完成和新任务 scope 均需匹配。 |

### 无内存 token 的历史恢复

[circuit_feature_current_recovery.rs](../../../codex-rs/hepta-agentd/src/circuit_feature_current_recovery.rs) 根据已恢复的真实 successor publication，只读其签名 previous 对应的 source/Cell 历史并重建 sealed completion。`HistoricalRead` 只传入无 writer 的 `CellOwnerJournalReadbackV1`。

历史读取要求非空、完整记录、实际 head 与原 witness 完全相等，且没有多余尾字节。完整未 ACK 尾、torn tail、缺失原历史与 Pending 都保持失败；这个读取路径不修复、不 fsync、不追加，也不补 witness。它恢复历史事实，不能恢复旧任务执行权。

## 三项普通入口用例实际证明了什么

| 原生用例 | 实际通过的行为 | 结论边界 |
| --- | --- | --- |
| `q24_ordinary_signed_tasks_consume_real_current_model_and_fresh_input_after_drain` | 通过正常签名入口执行 A；原任务 drain 后发布同模型的新任务；新会话/不同输入 C 实际执行；签名重放不修改 source/Cell/control，篡改请求被拒绝。 | 原签名和版本选择由夹具提供；不是完整学习 NoUpdate 链。 |
| `q24_ordinary_fresh_task_consumes_original_trainer_changed_head_after_version_publication` | 使用 A 的实际输入；原 durable trainer 运行 2 步冻结 SGD，真实 heads 改变；重开 trainer 返回原完成字节；原版本机制发布实际候选，新 C 输出准确反映候选权重，父文件及其他行保留。 | target、Dataset/stage metadata 和 selection credential 是夹具；没有独立 B、retention 或原 Proposal/Selector 的质量采用结论。 |
| `q24_ordinary_cold_recovery_rebuilds_completed_predecessor_without_retained_token_or_repairs` | 释放 A/C 的实际 task guard、source、Cell/control 和 completion token，重开原文件，重建前序凭证，再重放原签名 C；source/Cell/control/CURRENT bytes 和 nonce 数保持；旧 Cell 未 ACK 尾被拒绝。 | 保留的是无 capability 的已验证配置，测试未伪造 Fleet Starting 转换；不是实际 daemon 与 Root 两个 OS 进程冷重启。 |

上述用例之外，门禁也实际执行 trainer 的量化权重未变 NoUpdate、Current 撤回、丢失 ACK、原评价签名恢复与原 source 撤回等用例。精确用例名以保留的 JUnit 为准。

## 整链仍需关闭的接口和原始材料

详见 [OWNER_ASSEMBLY_GAPS.md](OWNER_ASSEMBLY_GAPS.md)。这次审查发现的核心结构问题是：当前 `LearningIterationProposalPayloadV1` 只有 Parameter/Topology；原 Parameter V3 从真实 NDU/Sparse journals 重算 eligibility/modulator 并重生完整候选集。冻结 Q24 单行 SGD 的 Model/heads 不是该生成器的输出，不能事后填入几个摘要或冒用 candidate ID 来通过。

若保持冻结 SGD，需要明确的新 Model Proposal owner/profile，由原 owner 登记并持久提交；若复用原 Parameter V3，则须取得真实 V3 源材料并在训练前重新冻结模型/参数映射。两种路径都必须保留独立质量评价与原 Selector 的采用责任。

真实 B/retention 还需原冻结材料、holdout CAS、qualification sink、两臂真实训练历史及完整成本。现 Cell comparison contract 要求匹配预算与真实 Wall/CPU；普通 Feature 的局部统计和 CURRENT 所用的 Generation journal 不能代填这些记录，未知 CPU 也不能写成零。

此外，同一个生产 `LearningIterationStageOwnerPortsV1` 实现和 CLI 原始 profile producer 尚未装配完成。原 launcher 继续在 Root learning stages 未装配时拒绝启动。检查 main/ai395 的限定服务、绑定及原 task-registry 路径后，没有验证出可恢复的原 LEARN custody；这是检查范围内的结论，不是全磁盘不存在性证明。未启动、停止或改配原服务，未输出私钥/token。观察记录及 SHA 在 custody evidence 中保留。

## 证据与失败保留

[RESULT.json](RESULT.json) 给出机器可读状态；[ARTIFACTS.json](ARTIFACTS.json) 给出所有交付文件和档案的 SHA-256；[MAINTENANCE.json](MAINTENANCE.json) 记录行为源与维护后源码的关系。

- [final-bbab-v1-evidence.tar.gz](final-bbab-v1-evidence.tar.gz)：固定源码的完整 native 日志、原执行 driver、helper、JUnit 和源码前后身份。
- [source-checks-bbab.tar.gz](source-checks-bbab.tar.gz)：63 项源码检查、全仓 caller 证明、精确 driver 以及 inventory 缺项失败。
- [maintenance-bbab-complete-v1.tar.xz](maintenance-bbab-complete-v1.tar.xz)：初次维护失败、fmt-only 重试、两次 compile-only、工具链、原基线 object pack 和 44 个完整 postimage。
- [marker-format-maintenance.tar.gz](marker-format-maintenance.tar.gz)：保护标记的精确维护差异、只读审阅和静态读回；没有后维护行为测试。
- [custody-evidence.tar.gz](custody-evidence.tar.gz)：限定服务、绑定与原路径的脱敏只读检查及其 driver。
- [ARCHIVE_INTEGRITY.json](ARCHIVE_INTEGRITY.json)：完整档案、内部文件清单、原日志和执行 driver 的本地独立字节核对。

| 中间尝试档案 | 原始结果 | 与最终结果的关系 |
| --- | --- | --- |
| [warm-46fc-v1-evidence.tar.gz](warm-46fc-v1-evidence.tar.gz) | helper 成功，测试编译退出 101，未执行用例。 | 保留失败；不计入最终通过。 |
| [warm-dfbed-v1-evidence.tar.gz](warm-dfbed-v1-evidence.tar.gz) | 四包切片 172 个用例：167 通过，5 失败。 | 保留真实失败；不是当前六包门禁。 |
| [warm-fe612-focused-v1-evidence.tar.gz](warm-fe612-focused-v1-evidence.tar.gz) | 修复后的定向 8/8 通过。 | 仅中间定向验证；不计入 bbab 的 516。 |
| [warm-13f3-assembly-v1-evidence.tar.gz](warm-13f3-assembly-v1-evidence.tar.gz) | helper 外层退出 1；内部 E0433；未启动 ordinary 测试。 | 编译失败。 |
| [warm-718b-assembly-v1-evidence.tar.gz](warm-718b-assembly-v1-evidence.tar.gz) | helper 成功；测试编译 19 处 E0659，退出 101。 | 未执行行为测试。 |
| [warm-852c-assembly-v1-evidence.tar.gz](warm-852c-assembly-v1-evidence.tar.gz) | helper 成功；测试 helper 的 String 错误转换 E0277，退出 101。 | 未执行行为测试。 |

保留的失败包括原 completion 摘要公式错误、测试模型输出宽度不符合原生产边界、测试断言宏/错误转换编译失败、错误 production dependency 路径，以及新调用闭集 inventory 缺项。修复没有降低原模型边界、撤回/当前性检查、Fleet 生命周期或原权限要求。失败尝试的源身份、实际结果和最终门禁分别记录，未用后来的成功覆盖早先失败。

在原始 owner 测试环境复现本轮组件门禁的主要命令为：

```bash
just test --locked --offline \
  -p codex-hepta-agentd -p codex-hepta-automation \
  -p codex-hepta-learning-artifacts -p codex-hepta-intelligence-eval \
  -p codex-hepta-neuron -p codex-hepta-learning-ledger \
  --lib \
  -E 'package(codex-hepta-neuron) | test(cell) | test(circuit) | test(q24) | test(learning) | test(signed_evidence) | test(ordinary_source_) | test(feature_control) | test(original_evaluator_) | test(original_owner_enrollment)' \
  --test-threads 2 --retries 0 --success-output final --failure-output final
```

实际执行 driver 另外保留了同源码 helper 构建/核验、SOURCE_SHA/TESTED_SHA、实际 Root 六项过滤器、环境、工具链、完整日志及 JUnit 收集。Root 组件需要原授权的实际 Root 测试环境；普通用户执行结果不能替代它。
