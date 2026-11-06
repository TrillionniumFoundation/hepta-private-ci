# Cell 统一集成：当前源码、验证与采用边界

**当前状态：DRAFT；科学结论 HOLD；权限 DENY_ALL。** source51 的 GitData commit `e28b0f385ee882f842911044958b2810f62f6379`、tree `763c8d2b4089f6e9806c3bbb68fa247bc2f6af36` 已登记，并已由唯一原生 apply 任务应用到隔离 staged tree。该任务自然退出 0，只完成两个 fixture 的精确变更与源码／双锁守卫，没有运行 Rust 或新的锁更新。原生 HEAD 仍是 framework 基线，不能把 commit 对象登记写成 checkout、分支发布或 PR 已创建。[当前状态][status]／[源码身份][identity]／[source51 应用原件][apply51]

最后一个完整 Rust 项目门仍是 **source50 的 r24 失败**：Python 32/32、四包 strict 退出 0；完整测试 1,564 个唯一结果中 **1,561 PASS、3 FAIL、0 TIMEOUT，另报 3 skipped**，原 tests 与外层任务均自然退出 100。source51 的同一 r26 任务已观察为 running：原 Python 测试 **32/32、0 skip，raw／effective 退出 0**，194 路径与双锁守卫通过，strict 已开始。严格门、完整 Rust 测试和外层任务均尚无闭合终态。r27 完整工作区门仍是惰性准备，被 r24 阻止的旧 r25 未启动。最终 fix/fmt、最终源码 CI、分支与 Draft PR 均未完成。[r24 完整闭合证据][r24]／[r26 已闭合 Python 与进度快照][r26-python]

本目录是工程证据与成熟度索引，不是生产采用批准。每个门绑定其原始 staged tree；历史 PASS、静态审查、应用成功和工具准备成功分别记录，不转授给新源码。

## 1. 重新判断七类职责与历史资产

**撤回“七类都只是 enum”的判断。** 历史研究已有真实编码器、Head、Adapter、内部 LoRA、路由、有限状态模型、生成模型和续训资产。当前任务是把具体实现按共同 Cell 合约注册、组合、恢复和验收；历史资产存在、当前合约接入成立、科学收益通过分别需要证据。[成熟度报告][maturity]／[六组历史资产清单][assets]

`CellFunctionalRoleV1` 的七类是**功能职责**；HNMF `EngramPopulationV1` 的七类是**记忆组织分类**。职责不是 capability type、模型或进程，两套枚举不能按序号互换，也没有证据证明七是最优模型数量。

| 功能职责 | 已核查的历史资产 | 当前采用缺口 |
| --- | --- | --- |
| 感知编码 `PerceptionEncoding` | 共享 Encoder、多模态接口、私有 Head、真实特征与媒体输入 | 独立新来源视频与联合 AV；当前来源和完整 FeatureBundle 接入 |
| 记忆关联 `MemoryAssociation` | V13 MiniLM＋Residual Adapter、V14 内部 attention LoRA、V15 持久评价 | 稳定保留、校准、强检索／精确 KV 对照及完整成本净收益 |
| 预测仿真 `PredictionSimulation` | 有限状态、belief、readout、continuation-Q 与反馈实验 | 未见任务和动作条件泛化；固定物理 dynamics 的研究不能当作已学会整体动态模型 |
| 决策协调 `DecisionCoordination` | 真实路由、停止、actor／critic 与固定策略对照 | 跨任务、完整成本下稳定优于强固定策略 |
| 动作生成 `ActionGeneration` | 自由词表 LM＋可训练前缀、小型 Rust 内容解码器 | 自然质量、学得的流式跨模态一致性、统一产品 owner 接入 |
| 验证元认知 `VerificationMetacognition` | 独立数值差分、媒体读回、输入干预、严格类型评分 | 自然语义评分可靠性与独立 freshness；自 critic 不能签发最终质量结论 |
| 学习发育 `LearningDevelopment` | Head／Adapter 训练、结构候选、优化器恢复与多轮反馈 | 多代有效采用、保留、成本与学习策略自身改进 |

这张表概括已绑定的历史证据，不代表本轮重新运行了这些模型。V13 的完整续训契约不能转授给 V14 的内部 LoRA；V14 分类器不能作为生成模型证据；V15 已知的 authority 整体回滚反例继续保留。具体模型修订、权重、原始指标、反例和范围见固定清单。[历史边界][maturity]

共同 Cell 合约保留三个可替换家族：

1. **冻结表示＋私有 Head／Residual Adapter**，承接共享 Encoder 与轻量适配。
2. **生成模型＋私有 Adapter／解码状态**，承接参数、工具参数及多模态输出研究。
3. **可训练状态模型／World Model**，承接有限预测、控制和连续状态研究。

Granite 97M、EG2 与 V13 MiniLM＋Adapter 继续作为各自具体任务的候选。角色、capability、expert 版本和实例数量分别建模，不预设恰好七个模型。

## 2. 当前代码具体接通了什么

固定输入为 #4887 `bef6fa7` 的 Cell framework 与 #4890 `caf06e0` 的职责／分化定义。新增输入桥和注册表沿用已有 owner 执行与恢复接口。[源码来源与 51 个登记记录][identity]

| 实现 | 当前行为 | 资格边界 |
| --- | --- | --- |
| `CellGlobalFeatureProjectionV1` | 严格导入既有 `hepta.feature-global-q24-conversion.v1`；校验独立取得的 conversion、bundle、来源行、encoder、scope 和当前 frontier pins，再验证 receipt 封条 | 导入全局 Q24 向量；没有导入完整张量、token、模态 mask 或时空视图 |
| `CellBackendRegistryV1` | 绑定 backend ID、家族、capability、expert 与 Cell definition；核对参数／状态／输入／输出 schema | 是不可变登记快照，不授予动态模型发布、采用或生产权限 |
| `RegisteredCellBackendV1::enter/recover` | 登记 digest 进入原操作与语义身份；变更角色、家族或 expert 不能把旧操作解释成新决定；执行前核当前 owner definition/source frontier | 使用已有 prepare/infer/decide/commit 与原请求恢复路径；未知结果保持 pending，不自动重新派发 |
| 原生输出 | 继续产生 `CellDecisionReceiptV1` 提案，保留成本、迟到／弃权等原有语义 | 输出不是自然语言／媒体 schema，也不是独立语义质量证书；权限保持 DENY_ALL |

[输入桥源码][projection-source]和[注册表源码][registry-source]固定在 source51。14 项新增机制回归使用控制夹具；较早的两包基线为 200/200，加入桥与注册后为 214/214。它们分别绑定各自原始源码树，不能与后续门累计，也不证明真实模型效能。[基线回执][baseline]／[注册机制回执][registry]

### FeatureBundle 与 Q24 的精确范围

原 Python FeatureBundle 保存原始张量、dtype、shape 和完整身份；本轮 Rust 桥读取的是它**已经定义的全局 Q24 conversion receipt**，没有另造 tensor 协议。该窄 profile 为 signed Q24、ties-to-even，row 0..511、width **1..512**；receipt 必须保留 `authority=DENY_ALL` 和 `legacy_head_parity_qualified=false`。[原始格式与边界][maturity]

**EG2 的 768 维输出当前必须拒绝。** 不能静默截断、改 basis 或补造 pooling、token 对齐、视频时间与联合 AV 语义。独立 caller 仍需保管、验证原 bundle、完整身份和最终使用时的当前来源；自洽 SHA 本身不提供独立来源认证。已审历史资产中没有定位到可用于本桥真实端到端资格的留存 Encoder `q24_global` receipt，因此当前兼容性回归仍明确属于 fixture。

### 组合过程中修复的其他工程问题

为了让原项目门和默认工作区门实际执行，已登记源码还包含按 owner 分开的修复：Rust 大载荷装箱和相邻参数命名组、实际消费者同步、Matrix 持久预算恢复、终止请求与实际退出确认、隐藏 hook 的受控绑定、跨包测试 helper 的真实 artifact 接线及对应 fixture 修正。Rust 调用方可能需要适配；不能把“原 wire／digest 语义保留”误读成 Rust 源码 API 完全不变。[历史完整记录][history]

source48 的 Linux 生命周期修复持续观察原 PTY owner 的 pidfd，保留新 session、PID namespace 与权限边界，payload 分支显式关闭该句柄。r20 原项目门中的原五秒断连用例和新增四项 owner／FD 回归均通过。source49 仅在两个 client 测试请求中补既有可选字段 `trace: None`，并把 client owner 加入既有 CI lane；r22 验证了该项目范围。[r20][r20]／[r22][r22]

source50 又闭合了 CLI 能力协商、真实 bwrap helper 接线、直接 policy fixture 与官方 marketplace 本地 Git 测试前置，并将新 owner 纳入原 CI。因测试依赖适用范围变化，原 `just bazel-lock-update` 已实际退出 0，Cargo 与 Bazel 两份锁的前后原字节完全相同；准备工具的三个失败尝试、Bazel 警告和首次导出失败均按原事实保留。此锁结果不覆盖 r24 的测试失败。[实际锁更新][lock50]／[控制原件补充][lock-control]

## 3. 实际门状态：分别绑定源码，禁止相加

当前 source51 清单有 **194 个变更路径：180 个 Rust、14 个其他文件**，对应 **26 个 Rust owner 包**。既有五个 CI lane 保留 **27 个包选择项**，额外保留 control-plane；source50→51 的两处 Rust fixture 变更没有改变依赖、双锁或 CI 输入。证据附件另计，scoped fix/fmt 仍未执行。现有包身份与当前完整路径清单已重新对应；未来 r27 仍须取得新的 Cargo metadata，不能把旧 source49 metadata 写成新执行结果。[源码范围准备快照][scope51]

| 原始门 | 绑定源码 | 实际终态 |
| --- | --- | --- |
| r20：app-server＋linux-sandbox | source48 / `e65356f` | strict 与 tests 均退出 0；**1,495 PASS、0 FAIL、0 TIMEOUT，2 reported skipped**；原七项失败和新增四项 owner／FD 回归全通过。[闭合入口][r20] |
| r21：默认 193 成员 workspace | source48 / `e65356f` | **编译退出 101**；nextest 未启动，执行与结果计数为 `null`。[闭合入口][r21] |
| r22：app-server-client | source49 / `be34ab1` | strict 与 tests 均退出 0；**30 PASS、0 FAIL、0 TIMEOUT、0 skip**。[闭合入口][r22] |
| r23：默认 193 成员 workspace | source49 / `be34ab1` | **自然失败，退出 100**；**20,228 unique＝20,220 PASS＋7 FAIL＋1 TIMEOUT，130 reported skipped**。[闭合入口][r23] |
| 原 Bazel lock 更新 | source50 / `ea48acf` | 原命令与外层均退出 0；两锁完整前后原字节相同。它是锁更新门，不是 Rust 资格。[原件][lock50] |
| r24：CLI、exec-server、network-proxy、external-agent-migration | source50 / `ea48acf` | Python **32/32**；strict **0**；完整测试 **1,561 PASS、3 FAIL、0 TIMEOUT，3 reported skipped**；原 tests 与外层 **100**。[闭合入口][r24] |
| source51 apply-only | source51 / `763c8d2` | 原 apply-check／apply／精确 stage 及外层均 **0**；194 路径、精确两处 delta 与双锁守卫通过。未运行 Rust、锁更新或 fix/fmt。[原件][apply51] |
| r26 | source51 / `763c8d2` | Python **32/32、0 skip、退出 0**；strict-start 已观察。同一 job 最后观察为 running；strict／Rust tests／outer 均无终态，终态计数为 `null`。[闭合 Python 原件][r26-python] |
| r27 | source51 / `763c8d2` | 惰性准备，尚未执行；必须先取得同源 r26 真实通过。计数为 `null`。 |

默认工作区原命令保持 `just test --locked --retries 0`，不新增测试筛选。各门 skip 数保持原日志口径，不凭总数补造跳过身份；不同阶段和源码的执行数量不相加。193 默认成员范围也不等于所有 feature、平台或外部服务均已验证。

### r24 三项不通过与 source51 的两处修复

r23 原八项不通过中，r24 已实际通过六项，两个 exec-server fixture 仍失败；另一个 DetectTls policy fixture 出现新失败。完整 ID、原错误块和逐项转换保存在 [r24 读回][r24-readback]与[转换清单][transitions]；旧 source49 的全部失败和当时候选说明原字节保留在[历史快照][history49]。

| 原失败 | source51 的精确修复 | 保留的验证边界 |
| --- | --- | --- |
| `sandboxed_discovery_batches_roots_without_combining_different_permissions`；`sandboxed_file_system_helper_finds_bwrap_on_preserved_path` | helper 在建立测试 shim 之前使用已有生产 PATH system-bwrap 查找入口；无系统程序时仍使用既有仓库 Cargo binary fallback | wrapper 全部 argv、FD、PATH 记录、fail-once、权限／计数断言与 PID 1／owner guard 保持。同一主机、同一受控参数的诊断中 system bwrap 退出 0、repo bwrap 退出 1；这不证明全部后端可用，也未测出具体内核或 LSM 根因 |
| `http_proxy::tests::http_connect_accept_defers_brokered_host_mitm_until_protocol_detection` | 仅该直接内存 policy fixture 添加既有 `allow_local_binding=true` | 保留 host、虚拟 token、原断言、超时及生产默认／DNS 防护。原块证明 `403 blocked-by-allowlist`；没有实际 DNS 答案或耗时证据 |

这两处改动已经按精确源码应用，**原失败不能因此记为通过**。source51 必须完成原 r26 项目门及随后同源默认工作区门；原日志、失败与限界继续保留。[登记及审查快照][registration51]／[有限 launcher 对照][probe51]

r26 原 Python 命令含实际 fixture 构建等工作共 **71.149435997 秒**；unittest 自报执行 **59.132 秒**，两者分别保留。最初两次控制查询不可用的原件仍在 launch 历史中，不记为 Rust 失败或重跑。[launch 历史][r26-launch]

## 4. 冻结分化研究：执行完成，两个场景均 HOLD

#4890 原 Python 研究保持源码、种子、数据划分、128 步训练、六个对照和门槛不变。normal 与 `python -O` 测试各 24/24 通过；一次完整研究完成 **10 trials、60 arms、11,520 个测试预测**，没有失败 arm。冲突与冗余场景均为 **HOLD**。[完整执行与结果][study]

冲突场景确实生成子分支并改善不兼容任务，但没有在每个种子上比每个对照至少降低 0.0005 MSE；对 fixed experts 的平均增益只有约 **0.00006279064223624**。冗余场景保留原 parent、输出相同，额外诊断增加成本。因此没有科学采用批准。

独立读回检查 **30,720 条预测记录**，最大绝对差 **1.4432899320127035e-15**；按共有工作每 trial 只计一次，核对 **655 个成本事件、49,090,740 estimated FP operations、37,120 routing decisions**。这些是不同单位，不能与秒数或 RSS 相加；也不能再次累计每个 arm 中重复展示的共有预训练成本。[研究读回与成本说明][study]

六臂总计算预算不完全相等，不能声称等总预算优势。此次参数序列化是进程内读回，不是跨主机续训或 live owner handoff；保持旧任务 parent 完全相同，也不能替代真实后端的独立长期保留验收。历史六组模型研究没有在本轮重训，其资格不转移到当前注册表。

## 5. 剩余采用与发布门槛

1. 完成 source51 原 Python／四包严格／完整项目门，确认原三个失败用例均真实执行；随后取得同源、无新增筛选的完整默认工作区结果。r25 的旧惰性模板继续保持未执行。
2. 只有工程门满足后，才执行约定的 scoped fix/fmt、精确最终差异和源码导出，再由最终发布 SHA 的 CI 验证。最终执行器必须重绑实际 native HEAD／tree、双锁和非空显式 fmt 选择，不能沿用 source49 准备件或改成 `--all`。当前 fix 与 fmt 均 **NOT_EXECUTED**。
3. 把真实后端、真实 Encoder receipt 与产品 owner 接到共同合约；补齐完整状态、unknown 恢复、当前来源／scope／撤销和最终消费校验。
4. 按具体任务完成独立保留、校准、强检索／精确 KV／固定策略对照与完整生命周期成本验收。历史训练、fixture 回归和测试数量均不能代替这些结果。
5. 形成可分层审阅的 Draft PR；当前分支未创建、PR 未发送，最终 CI 与生产采用均未获资格。

## 6. 历史快照、恢复与证据阅读

本页、[STATUS.json][status] 和 [SOURCE_IDENTITY.json][identity] 是当前 source51 报告。修改之前，已将不可变 artifact checkpoint `464603f9b710d24b52dd5ba5f2dc34207352397d` 对应的 source49 三报告**原字节**保存在 [history/source49-r23-checkpoint][history49]。旧 current 字段只描述当时状态；更早 source47／r19 的完整历史也继续保留。[更早历史][history]

当前身份列表逐项复用固定 [source51 ledger 快照][ledger51]中的 **51 个源码对象登记记录**；快照当时有 176 个已登记二进制路径。附件随后增加不会改写这个历史数字，本报告不把它声明为永久的当前附件总数。ledger、源码、旧 formal 组均未被报告编辑器修改。

r20、r21、r22 的原 archive、日志、raw rc、receipt、资源与源码原件已精确恢复；三个 `*-recovered-checkpoint` 的读回是恢复后新审计，没有重跑 Rust，也没有伪造失去的旧审计字节。[r20][r20]／[r21][r21]／[r22][r22] r23 完整失败记录、source50 实际锁更新及 r24 完整项目失败记录分别封存，读回成功不改变对应 Rust 门结果。[r23][r23]／[lock][lock50]／[r24][r24]

此前不可变 artifact checkpoint 中的旧证据路径继续保留，无须全部重新下载；历史相对链接仍以原报告根为基准。新的 source51 登记、有限 probe、apply-only、r26 launch 与闭合 Python 快照均明确注明范围，不替代真实模型、科学研究或新 Rust 门证据。

[status]: STATUS.json
[identity]: SOURCE_IDENTITY.json
[maturity]: MATURITY.zh-CN.md
[assets]: HISTORICAL_ASSETS.json
[study]: study-evidence/README.md
[history]: history/published-r19-b14c3288/MANIFEST.json
[history49]: history/source49-r23-checkpoint/MANIFEST.json
[ledger51]: history/source51-ledger-snapshot/MANIFEST.json
[r20]: native-evidence/r20-recovered-checkpoint/RECOVERY-CLOSURE.json
[r21]: native-evidence/r21-recovered-checkpoint/RECOVERY-CLOSURE.json
[r22]: native-evidence/r22-recovered-checkpoint/RECOVERY-CLOSURE.json
[r23]: native-evidence/r23-workspace-checkpoint/CLOSURE.json
[r24]: native-evidence/r24-project-checkpoint/CLOSURE.json
[r24-readback]: native-evidence/r24-project-checkpoint/INDEPENDENT-READBACK.json
[transitions]: native-evidence/r24-project-checkpoint/readback/R23-FAILURE-TRANSITIONS.json
[baseline]: native-evidence/baseline/native-first-receipt.json
[registry]: native-evidence/registry-a/native-registry-a-receipt.json
[projection-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e28b0f385ee882f842911044958b2810f62f6379/codex-rs/hepta-neuron/src/cell_feature_projection.rs
[registry-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e28b0f385ee882f842911044958b2810f62f6379/codex-rs/hepta-neuron/src/cell_registry.rs
[lock50]: native-evidence/source50-lock-update-checkpoint/INDEPENDENT-READBACK.json
[lock-control]: native-evidence/source50-lock-control-recovery-addendum/INDEPENDENT-READBACK.json
[registration51]: history/source51-registration/MANIFEST.json
[apply51]: history/source51-apply-checkpoint/MANIFEST.json
[scope51]: history/source51-scope-preparation/SCOPE.json
[probe51]: history/source51-registration/launcher-comparison-readback.json
[r26-launch]: history/source51-r26-launch/MANIFEST.json

[r26-python]: history/source51-r26-python-checkpoint/MANIFEST.json
