# Cell 统一集成：当前源码、验证与采用边界

**当前状态：DRAFT；科学结论 HOLD；权限 DENY_ALL。** source53 的 GitData commit `f74be175de66a4b351cd239d39d98cd34fe9cc1b`、tree `440d4a8e09af4009e4d9ea067388826308da8803` 已登记，并已由纠正输入位置后的独立 apply-only 任务应用到原生 staged tree。原三条 Git 命令与该外层任务均自然退出 0；197 个变更路径、HEAD 和双锁守卫通过。原生 HEAD 仍是 framework 基线；对象登记和 staged tree 应用不等于 checkout、分支发布或 PR 创建。[当前状态][status]／[源码身份][identity]／[source53 诊断与应用原件][apply53]

**source53 只增加诊断日志，尚未证明修复 Bedrock 根因。** 唯一原生 R30 app-server 项目门已实际启动，最后闭合的控制快照为 running／strict-start；strict、tests、outer 的终态与计数仍为 `null`。计划中的完整 1,345 个原项目 ID 只在完整门后核对，不作为筛选；之后的 R31 默认工作区仍未执行。[R30 启动快照][r30-start]

最近完整工作区 **R29 绑定 source52，已自然失败 100**：20,228 个唯一结果＝**20,227 PASS、1 FAIL、0 TIMEOUT**，另报 **130 skipped**。唯一 FAIL 是 `suite::v2::bedrock_setup::setup_bedrock_profile_and_environment`，原完整块显示首次 Profile setup 等待响应达到既有 deadline；这是 FAIL，不是 nextest TIMEOUT。该记录没有定位具体内部等待阶段，不能把新增阶段日志称为行为修复。[R29 完整失败原件][r29]

source52 的 R28 原四包门仍保持 **Python 32/32、0 skip；strict 0；1,564 PASS、0 FAIL、0 TIMEOUT、3 reported skipped；tests／outer 0**。该有限项目通过不替代 R29 工作区失败或 source53 新门。此前 source51/R26 与 source50/R24 的失败记录和逐例转换继续保留；旧 R25、R27 没有执行。最终 fix/fmt、最终 SHA CI、分支与 Draft PR 均未完成。[R28][r28]／[R26][r26]

本目录是工程证据与成熟度索引，不是生产采用批准。每个门绑定其原始 staged tree；静态审查、应用成功、历史 PASS 和工具准备成功分别记录，不转授给其他源码、完整工作区或真实模型采用。

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

固定输入为 #4887 `bef6fa7` 的 Cell framework 与 #4890 `caf06e0` 的职责／分化定义。新增输入桥和注册表沿用已有 owner 执行与恢复接口。[源码来源与 53 个登记记录][identity]

| 实现 | 当前行为 | 资格边界 |
| --- | --- | --- |
| `CellGlobalFeatureProjectionV1` | 严格导入既有 `hepta.feature-global-q24-conversion.v1`；校验独立取得的 conversion、bundle、来源行、encoder、scope 和当前 frontier pins，再验证 receipt 封条 | 导入全局 Q24 向量；没有导入完整张量、token、模态 mask 或时空视图 |
| `CellBackendRegistryV1` | 绑定 backend ID、家族、capability、expert 与 Cell definition；核对参数／状态／输入／输出 schema | 是不可变登记快照，不授予动态模型发布、采用或生产权限 |
| `RegisteredCellBackendV1::enter/recover` | 登记 digest 进入原操作与语义身份；变更角色、家族或 expert 不能把旧操作解释成新决定；执行前核当前 owner definition/source frontier | 使用已有 prepare/infer/decide/commit 与原请求恢复路径；未知结果保持 pending，不自动重新派发 |
| 原生输出 | 继续产生 `CellDecisionReceiptV1` 提案，保留成本、迟到／弃权等原有语义 | 输出不是自然语言／媒体 schema，也不是独立语义质量证书；权限保持 DENY_ALL |

[输入桥源码][projection-source]和[注册表源码][registry-source]固定在 source52。14 项新增机制回归使用控制夹具；较早的两包基线为 200/200，加入桥与注册后为 214/214。它们分别绑定各自原始源码树，不能与后续门累计，也不证明真实模型效能。[基线回执][baseline]／[注册机制回执][registry]

### FeatureBundle 与 Q24 的精确范围

原 Python FeatureBundle 保存原始张量、dtype、shape 和完整身份；本轮 Rust 桥读取的是它**已经定义的全局 Q24 conversion receipt**，没有另造 tensor 协议。该窄 profile 为 signed Q24、ties-to-even，row 0..511、width **1..512**；receipt 必须保留 `authority=DENY_ALL` 和 `legacy_head_parity_qualified=false`。[原始格式与边界][maturity]

**EG2 的 768 维输出当前必须拒绝。** 不能静默截断、改 basis 或补造 pooling、token 对齐、视频时间与联合 AV 语义。独立 caller 仍需保管、验证原 bundle、完整身份和最终使用时的当前来源；自洽 SHA 本身不提供独立来源认证。已审历史资产中没有定位到可用于本桥真实端到端资格的留存 Encoder `q24_global` receipt，因此当前兼容性回归仍明确属于 fixture。

### 组合过程中修复的其他工程问题

为了让原项目门和默认工作区门实际执行，已登记源码还包含按 owner 分开的修复：Rust 大载荷装箱和相邻参数命名组、实际消费者同步、Matrix 持久预算恢复、终止请求与实际退出确认、隐藏 hook 的受控绑定、跨包测试 helper 的真实 artifact 接线及对应 fixture 修正。Rust 调用方可能需要适配；不能把“原 wire／digest 语义保留”误读成 Rust 源码 API 完全不变。[历史完整记录][history]

source48 的 Linux 生命周期修复持续观察原 PTY owner 的 pidfd，保留新 session、PID namespace 与权限边界，payload 分支显式关闭该句柄。r20 原项目门中的原五秒断连用例和新增四项 owner／FD 回归均通过。source49 仅在两个 client 测试请求中补既有可选字段 `trace: None`，并把 client owner 加入既有 CI lane；r22 验证了该项目范围。[r20][r20]／[r22][r22]

source50 又闭合了 CLI 能力协商、真实 bwrap helper 接线、直接 policy fixture 与官方 marketplace 本地 Git 测试前置，并将新 owner 纳入原 CI。因测试依赖适用范围变化，原 `just bazel-lock-update` 已实际退出 0，Cargo 与 Bazel 两份锁的前后原字节完全相同；准备工具的三个失败尝试、Bazel 警告和首次导出失败均按原事实保留。此锁结果不覆盖 r24 的测试失败。[实际锁更新][lock50]／[控制原件补充][lock-control]

## 3. 实际门状态：分别绑定源码，禁止相加

当前 source53 清单有 **197 个变更路径：183 个 Rust、14 个其他文件**，仍对应 **26 个 Rust owner 包和 27 个 CI 包选择项**。source52 的原 195 行清单值和逐行 JSON 原字节保持；新增两项都是原已存在的 app-server Rust 文件。单一 parent、18 个前后目录 Git tree 的完整对象哈希及唯一两叶 delta 已独立重算。依赖、双锁、CI 输入均未改变；source50 原锁更新成功仅按未变依赖输入继承，source53 没有重新执行锁更新。[source53 原件][apply53]

新的 183-Rust＋2-Python 默认 formatter 选择目前只作准备边界。原 source52/R29 fresh metadata 的 193 个成员和包归属证据保留为历史输入；未来 source53/R31 仍须重新执行原 metadata 并核同源完整工作区，不能把旧 metadata 写成新的执行。报告编辑器没有运行 Cargo、Rust 或 formatter。

| 原始门 | 绑定源码 | 实际结果及范围 |
| --- | --- | --- |
| r20：app-server＋linux-sandbox | source48 / `e65356f` | strict 与 tests 均退出 0；**1,495 PASS、0 FAIL、0 TIMEOUT，2 reported skipped**；原七项失败和新增四项 owner／FD 回归全通过。[入口][r20] |
| r21：默认 193 成员 workspace | source48 / `e65356f` | **编译退出 101**；nextest 未启动，执行与结果计数为 `null`。[入口][r21] |
| r22：app-server-client | source49 / `be34ab1` | strict 与 tests 均退出 0；**30 PASS、0 FAIL、0 TIMEOUT、0 skip**。[入口][r22] |
| r23：默认 193 成员 workspace | source49 / `be34ab1` | **自然失败，退出 100**；**20,228 unique＝20,220 PASS＋7 FAIL＋1 TIMEOUT，130 reported skipped**。[入口][r23] |
| 原 Bazel lock 更新 | source50 / `ea48acf` | 原命令与外层均退出 0；两锁完整前后原字节相同。它是锁更新门，不是 Rust 资格。[原件][lock50] |
| r24：四包项目门 | source50 / `ea48acf` | Python **32/32**；strict **0**；完整测试 **1,561 PASS、3 FAIL、0 TIMEOUT，3 reported skipped**；tests／outer **100**。[入口][r24] |
| source51 apply-only | source51 / `763c8d2` | 原三条 Git 命令与外层均 **0**；194 路径、两处 delta 与双锁守卫通过；该任务未运行 Rust、锁更新或 fix/fmt。[原件][apply51] |
| r26：四包项目门 | source51 / `763c8d2` | Python **32/32、0 skip、0**；strict **0**；完整测试 **1,562 PASS、2 FAIL、0 TIMEOUT，3 reported skipped**；tests／outer **100**。原 r24 三个失败用例均 PASS。[入口][r26] |
| source52 apply-only | source52 / `211f15b` | 原三条 Git 命令与外层均 **0**；195 路径、唯一 runtime.rs delta、HEAD 与双锁守卫通过。没有新锁更新或 Rust 执行。[原件][apply52] |
| r28：四包项目门 | source52 / `211f15b` | Python **32/32、0 skip、0**；strict **0**；完整 **1,564 PASS、0 FAIL、0 TIMEOUT，3 reported skipped**；tests／outer **0**，源码守卫通过。[入口][r28] |
| r29：默认 193 成员 workspace | source52 / `211f15b` | **自然失败 100**；**20,228 unique＝20,227 PASS＋1 FAIL＋0 TIMEOUT，130 reported skipped**。原源码／HEAD／双锁后置守卫通过。[完整原件][r29] |
| source53 apply-only，首次尝试 | 原生仍 source52 / `211f15b` | 输入包位置错误，读取 task-root 文件时自然退出 **1**；完整 FNF 发生在 Git 与应用证据目录创建前。独立只读任务退出 0，确认原 195 项、HEAD、双锁和两份 before 未改。这不是 Rust 测试失败。[原件][apply53] |
| source53 apply-only，明确授权的纠正尝试 | source53 / `440d4a8` | 同脚本、同输入字节，只纠正输入位置并用新的唯一任务 key；三条 Git 命令和外层均 **0**，197 项和双锁守卫通过。没有 Rust、锁更新或 fix/fmt。[原件][apply53] |
| r30：app-server 完整项目门 | source53 / `440d4a8` | 唯一任务实际启动，最后闭合快照为 running／strict-start；strict、tests、outer 与结果计数均 `null`，不记为 PASS。[启动快照][r30-start] |
| r31：默认工作区 | source53 / `440d4a8` | 惰性准备，**未执行**；需同源 R30 完整闭合后才允许绑定并运行原 no-p 门。 |
| 旧 r25、r27 | 各自旧源码 | 惰性历史准备，均未执行；不累计为工作区结果。 |

默认工作区原命令保持 `just test --locked --retries 0`，不新增测试筛选。各门 skip 数保持原日志口径，不凭总数补造跳过身份；不同阶段和源码的执行数量不相加。193 默认成员范围也不等于所有 feature、平台或外部服务均已验证。

### R29 唯一失败与 source53 诊断边界

R29 的 Bedrock 用例 **10.643 秒 FAIL**，原 tests 总命令耗时 **2,768.967783928 秒**，nextest 自报执行 **1,646.985 秒**；这些不同口径分别保留。原初始化有 60 秒预算，普通请求沿原 10 秒等待；本次没有提高任何时限、增加重试或改变断言。

source53 在原 handler 的四个 await 边界周围增加九条固定阶段事件，并仅为原失败用例的第一个 app-server child 设置窄 `RUST_LOG`。日志只含固定阶段标签，不记录 profile、region、凭据或请求参数；既有 INFO request span 与 DEBUG queue span用于区分分派和排队。全部 22 个原断言、请求、await、60 秒／10 秒预算和第二个 child 保持。[两源精确候选和独立审查][apply53]

现有源码链尚不能证明此次延迟来自网络、配置、认证、队列或具体系统调用。后续 source53 项目门若真实通过，可以记录该版本工程项目范围 PASS；它仍不证明偶发原故障已修复，更不能替代完整工作区或科学资格。

### r26 两项实际失败与 source52 四处测试配置

r26 的两个实际失败均在 network-proxy 的 wildcard policy 测试中。source52 在四个直接配置 policy 的测试内显式设置已有 `allow_local_binding=true`，让这些测试的 allowlist／denylist oracle 不依赖其不打算验证的主机解析前置。另两个用例在 r26 本来就是 PASS，保留其历史状态，不把它们列为新增失败。

| 原测试 | r26 原结果 | r28 原结果 |
| --- | --- | --- |
| `host_blocked_subdomain_wildcards_exclude_apex` | FAIL | PASS |
| `host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist` | FAIL | PASS |
| `host_blocked_requires_allowlist_match` | PASS | PASS |
| `add_allowed_domain_removes_matching_deny_entry` | PASS | PASS |

四个测试的原断言、命令、时限与 oracle 全部保留；生产代码、默认配置、专门的 DNS／private／localhost 防护测试与注入解析测试均未修改。原失败块不包含实际 DNS 答案或解析耗时，不能仅凭约五秒的用例耗时推断 DNS 超时、私有地址或特定系统调用原因。[source52 修复与原件][apply52]／[r26 原结果][r26-readback]／[r28 完整结果][r28]

source51 的两处修复也有明确边界：bwrap 测试 helper 先使用既有生产 PATH system-bwrap 查找入口，缺失时保留仓库 binary fallback；DetectTls policy 测试只增加局部 `allow_local_binding=true`。同主机、同受控参数的诊断中 system bwrap 退出 0、repo bwrap 退出 1；这不证明全部后端可用，也没有测出具体内核或 LSM 根因。对应两个 exec-server 用例与 DetectTls 用例在 r26、r28 均实际通过，原权限／计数／FD／PID 1 防护没有放宽。[source51 有限诊断与修复][registration51]／[原转换][r26-readback]

r28 三条原命令的实际耗时分别为：Python **4.025784969 秒**、strict **89.192417145 秒**、完整 tests **347.584490299 秒**。Python unittest 自报 **3.921 秒**；nextest 自报执行 **52.852 秒**。包含构建／fixture 准备的命令总时长与测试框架内部时长分别保留，不能互换。[闭合原回执][r28]

## 4. 冻结分化研究：执行完成，两个场景均 HOLD

#4890 原 Python 研究保持源码、种子、数据划分、128 步训练、六个对照和门槛不变。normal 与 `python -O` 测试各 24/24 通过；一次完整研究完成 **10 trials、60 arms、11,520 个测试预测**，没有失败 arm。冲突与冗余场景均为 **HOLD**。[完整执行与结果][study]

冲突场景确实生成子分支并改善不兼容任务，但没有在每个种子上比每个对照至少降低 0.0005 MSE；对 fixed experts 的平均增益只有约 **0.00006279064223624**。冗余场景保留原 parent、输出相同，额外诊断增加成本。因此没有科学采用批准。

独立读回检查 **30,720 条预测记录**，最大绝对差 **1.4432899320127035e-15**；按共有工作每 trial 只计一次，核对 **655 个成本事件、49,090,740 estimated FP operations、37,120 routing decisions**。这些是不同单位，不能与秒数或 RSS 相加；也不能再次累计每个 arm 中重复展示的共有预训练成本。[研究读回与成本说明][study]

六臂总计算预算不完全相等，不能声称等总预算优势。此次参数序列化是进程内读回，不是跨主机续训或 live owner handoff；保持旧任务 parent 完全相同，也不能替代真实后端的独立长期保留验收。历史六组模型研究没有在本轮重训，其资格不转移到当前注册表。

## 5. 剩余采用与发布门槛

1. 保留 source52/R29 完整失败，按原 app-server 严格与完整项目门取得 source53/R30 实际结果；仅其完整通过后运行同源、无新增筛选的默认 193 成员工作区 R31。阶段日志用于定位等待，不能把诊断运行结果直接解释为根因修复。
2. 只有全部工程门满足后，才执行约定的 scoped fix/fmt、精确最终差异与源码导出，再由最终 SHA CI 验证。执行器必须绑定实际 native HEAD／tree、双锁、真实工具及非空默认选择：**183 个 Rust 文件＋2 个 Python 文件、26 个 owner**。不沿用旧 source52 的执行绑定，不改成 `--all`；当前 fix/fmt 均 **NOT_EXECUTED**，R29 失败不能满足其工作区通过前置。
3. 把真实后端、真实 Encoder receipt 与产品 owner 接到共同合约；补齐完整状态、unknown 恢复、当前来源／scope／撤销和最终消费校验。
4. 按具体任务完成独立保留、校准、强检索／精确 KV／固定策略对照与完整生命周期成本验收。历史训练、fixture 回归和测试数量均不能代替这些结果。
5. 形成可分层审阅的 Draft PR；当前分支未创建、PR 未发送，最终 CI 与生产采用均未获资格。

## 6. 历史快照、恢复与证据阅读

这三份报告候选登记当前 source53 的实际应用和 R30 初始快照。上一版 source52 三报告与 native INDEX 原字节已保存到 `history/source52-checkpoint6/`，并与不可变 artifact checkpoint `9896f63f1352906a6afec53b94d4d123143ba35e` 的实际叶 map逐项核对。该 checkpoint 的代码和报告属于 source52，固定当时 R28 PASS 与 R29 启动／fresh193快照，不包含后来 R29 的失败终态。[前版精确保全][prior53]

本次源码登记列表逐项取自固定 [source53 ledger 历史快照][ledger53]：**53 个源码对象、208 个二进制路径、6 个 artifact checkpoint**。这是该次观察的固定数字；后续 R29 上传登记等操作不回写此快照，也不被误称新的测试或 artifact checkpoint。原 source51／source49／更早报告和失败证据继续保留。[source49 历史][history49]／[更早历史][history]

source53 正式组分别保存首次准备路径失败和明确授权的纠正应用成功；全部原始回执、错误与输入字节保持。R29 工作区失败另有完整封组；R30 初始只读快照没有活动日志或终态推断。文档、静态审查、GitData保存和应用成功均不替代工程完整门或科学采用资格。[source53][apply53]／[R29][r29]／[R30 启动][r30-start]

[status]: STATUS.json
[identity]: SOURCE_IDENTITY.json
[maturity]: MATURITY.zh-CN.md
[assets]: HISTORICAL_ASSETS.json
[study]: study-evidence/README.md
[history]: history/published-r19-b14c3288/MANIFEST.json
[history49]: history/source49-r23-checkpoint/MANIFEST.json
[prior52]: history/source52-report-update/PRIOR-REPORTS.json
[ledger52]: history/source52-ledger-snapshot/MANIFEST.json
[r20]: native-evidence/r20-recovered-checkpoint/RECOVERY-CLOSURE.json
[r21]: native-evidence/r21-recovered-checkpoint/RECOVERY-CLOSURE.json
[r22]: native-evidence/r22-recovered-checkpoint/RECOVERY-CLOSURE.json
[r23]: native-evidence/r23-workspace-checkpoint/CLOSURE.json
[r24]: native-evidence/r24-project-checkpoint/CLOSURE.json
[r24-readback]: native-evidence/r24-project-checkpoint/INDEPENDENT-READBACK.json
[transitions]: native-evidence/r24-project-checkpoint/readback/R23-FAILURE-TRANSITIONS.json
[r26]: native-evidence/r26-project-checkpoint/CLOSURE.json
[r26-readback]: native-evidence/r26-project-checkpoint/INDEPENDENT-READBACK.json
[r28]: native-evidence/r28-project-checkpoint/CLOSURE.json
[r28-facts]: native-evidence/r28-project-checkpoint/INDEPENDENT-READBACK.json
[r29-start]: history/source52-r29-start-checkpoint/MANIFEST.json
[fresh-scope]: history/source52-scope-preparation/fresh/READ-ONLY-AUDIT.json
[baseline]: native-evidence/baseline/native-first-receipt.json
[registry]: native-evidence/registry-a/native-registry-a-receipt.json
[projection-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e0910becc37383e6d17ecf861ea844fd07d8862/codex-rs/hepta-neuron/src/cell_feature_projection.rs
[registry-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e0910becc37383e6d17ecf861ea844fd07d8862/codex-rs/hepta-neuron/src/cell_registry.rs
[lock50]: native-evidence/source50-lock-update-checkpoint/INDEPENDENT-READBACK.json
[lock-control]: native-evidence/source50-lock-control-recovery-addendum/INDEPENDENT-READBACK.json
[registration51]: history/source51-registration/MANIFEST.json
[apply51]: history/source51-apply-checkpoint/MANIFEST.json
[apply52]: native-evidence/source52-repair-apply-checkpoint/CLOSURE.json
[scope52]: history/source52-scope-preparation/SCOPE.json
[apply53]: native-evidence/source53-diagnostic-apply-checkpoint/CLOSURE.json
[r29]: native-evidence/r29-workspace-checkpoint/CLOSURE.json
[r30-start]: history/source53-r30-start-checkpoint/MANIFEST.json
[prior53]: history/source52-checkpoint6/MANIFEST.json
[ledger53]: history/source53-ledger-snapshot/MANIFEST.json
