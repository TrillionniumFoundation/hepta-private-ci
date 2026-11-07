# Cell 统一集成：当前源码、验证与采用边界

**当前状态：DRAFT；科学结论 HOLD；权限 DENY_ALL。** 当前登记源码是 source49，commit `50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a`，tree `be34ab1afe622ad3b8f030c8c5018f4f54fbc304`。其 client 项目门已通过；默认工作区门 r23 **真实失败**：20,228 个唯一执行结果中，20,220 PASS、7 FAIL、1 TIMEOUT，另报 130 skipped。八项不通过的后续候选正在独立准备；source50 commit 尚未创建。当前 native 授权限于候选应用与原 Bazel lock 更新，尚无新源码的 Rust 门结果。最终 fix/fmt、发布源码对应的 CI、分支与 Draft PR 均未完成。[当前状态][status]／[源码身份][identity]／[r23 完整闭合证据][r23]

本目录是工程证据与成熟度索引，不是生产采用批准。GitData 创建的 commit/tree 用于精确绑定源码身份；原生执行以回执记录的 staged tree 为准，不能据此声称当时 checkout 了后来创建的 commit。

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

固定输入为 #4887 `bef6fa7` 的 Cell framework 与 #4890 `caf06e0` 的职责／分化定义。新增输入桥和注册表沿用已有 owner 执行与恢复接口。[源码来源与 49 个创建记录][identity]

| 实现 | 当前行为 | 资格边界 |
| --- | --- | --- |
| `CellGlobalFeatureProjectionV1` | 严格导入既有 `hepta.feature-global-q24-conversion.v1`；校验独立取得的 conversion、bundle、来源行、encoder、scope 和当前 frontier pins，再验证 receipt 封条 | 导入全局 Q24 向量；没有导入完整张量、token、模态 mask 或时空视图 |
| `CellBackendRegistryV1` | 绑定 backend ID、家族、capability、expert 与 Cell definition；核对参数／状态／输入／输出 schema | 是不可变登记快照，不授予动态模型发布、采用或生产权限 |
| `RegisteredCellBackendV1::enter/recover` | 登记 digest 进入原操作与语义身份；变更角色、家族或 expert 不能把旧操作解释成新决定；执行前核当前 owner definition/source frontier | 使用已有 prepare/infer/decide/commit 与原请求恢复路径；未知结果保持 pending，不自动重新派发 |
| 原生输出 | 继续产生 `CellDecisionReceiptV1` 提案，保留成本、迟到／弃权等原有语义 | 输出不是自然语言／媒体 schema，也不是独立语义质量证书；权限保持 DENY_ALL |

[输入桥源码][projection-source]和[注册表源码][registry-source]固定在 source49。14 项新增机制回归使用控制夹具；较早的两包基线为 200/200，加入桥与注册后为 214/214。它们分别绑定各自原始源码树，不能与后续门累计，也不证明真实模型效能。[基线回执][baseline]／[注册机制回执][registry]

### FeatureBundle 与 Q24 的精确范围

原 Python FeatureBundle 保存原始张量、dtype、shape 和完整身份；本轮 Rust 桥读取的是它**已经定义的全局 Q24 conversion receipt**，没有另造 tensor 协议。该窄 profile 为 signed Q24、ties-to-even，row 0..511、width **1..512**；receipt 必须保留 `authority=DENY_ALL` 和 `legacy_head_parity_qualified=false`。[原始格式与边界][maturity]

**EG2 的 768 维输出当前必须拒绝。** 不能静默截断、改 basis 或补造 pooling、token 对齐、视频时间与联合 AV 语义。独立 caller 仍需保管、验证原 bundle、完整身份和最终使用时的当前来源；自洽 SHA 本身不提供独立来源认证。已审历史资产中没有定位到可用于本桥真实端到端资格的留存 Encoder `q24_global` receipt，因此当前兼容性回归仍明确属于 fixture。

### 组合过程中修复的其他工程问题

为了让原项目门和默认工作区门实际执行，已登记源码还包含按 owner 分开的修复：Rust 大载荷装箱和相邻参数命名组、实际消费者同步、Matrix 持久预算恢复、终止请求与实际退出确认、隐藏 hook 的受控绑定、跨包测试 helper 的真实 artifact 接线及对应 fixture 修正。Rust 调用方可能需要适配；不能把“原 wire／digest 语义保留”误读成 Rust 源码 API 完全不变。[历史完整记录][history]

source48 的 Linux 生命周期修复持续观察原 PTY owner 的 pidfd，保留新 session、PID namespace 与权限边界，payload 分支显式关闭该句柄。r20 原项目门中的原五秒断连用例和新增四项 owner／FD 回归均通过。source49 仅在两个 client 测试请求中补既有可选字段 `trace: None`，并把 client owner 加入既有 CI lane；r22 验证了该项目范围。[r20][r20]／[r22][r22]

## 3. 实际门状态：分别绑定源码，禁止相加

当前登记源码有 **188 个变更路径：175 个 Rust、13 个其他文件**，对应 **23 个 Rust owner 包**。既有 CI matrix 有 **24 个包选择项**，额外保留 control-plane。证据附件另计。范围来自实际 source49 清单、原 Cargo metadata 与已登记 workflow；这不是最终 fix/fmt 已执行的声明。[源码身份与范围][identity]

| 原始门 | 绑定源码 | 实际终态 |
| --- | --- | --- |
| r20：app-server＋linux-sandbox | source48 / `e65356f` | strict 与 tests 均退出 0；**1,495 PASS、0 FAIL、0 TIMEOUT，2 reported skipped**。其中 app-server 1,345、Linux sandbox 150；原七项失败和新增四项回归全通过。[闭合入口][r20] |
| r21：默认 193 成员 workspace | source48 / `e65356f` | **编译退出 101**，两个测试初始化缺少 `trace`；nextest 未启动，执行与结果计数均为 `null`。不是“执行零项而通过”。[闭合入口][r21] |
| r22：app-server-client | source49 / `be34ab1` | strict 与 tests 均退出 0；**30 PASS、0 FAIL、0 TIMEOUT、0 skip**。修复后的原 fixture PASS 0.017 秒；原 tests 命令含构建 270.655592 秒，nextest 执行 45.604 秒。[闭合入口][r22] |
| r23：默认 193 成员 workspace | source49 / `be34ab1` | **自然失败，退出 100**；**20,228 unique＝20,220 PASS＋7 FAIL＋1 TIMEOUT，130 reported skipped**。原命令含构建 2,128.745449 秒，nextest 执行 1,671.481 秒。[完整结果读回][r23] |

r23 原命令是 `just test --locked --retries 0`，没有新增测试筛选；原 source／lock 守卫通过。上述 skip 数保留各原日志口径，不凭总数补造逐项跳过身份。默认 193 成员范围不等于所有 feature、跨平台或真实外部服务均已验证。准备、归档或 Python 读回成功也不等于 Rust gate 成功。

### 当前八项不通过与隔离候选

完整 test ID、结果和时长列在 [STATUS.json][status] 与 [r23 原始读回][r23]。以下四组候选均基于 source49，**尚未取得新的 Rust 资格**。[source50 原始候选准备快照][source50-preparation] 已封存九路径输入、四份独立审查和真实 Git 克隆探针；应用／锁更新的闭合结果尚未纳入，其暂定范围不能替换当前 source49 的已登记范围。

| 组别 | 原失败与已核范围 | 候选方向及保留条件 |
| --- | --- | --- |
| CLI telemetry，1 FAIL | `process/start` 拒绝未协商退出观察能力的请求 | 测试初始化显式协商已有 `processExitObservation`；保留指标断言、30 秒等待和原有子进程负载 |
| exec-server sandbox fixture，2 FAIL | 原 wrapper 声称支持 `--as-pid-1`，实际只直接 exec，两个错误进入真实 PID 1 guard | wrapper 转发到仓库真实 bwrap，保留原 argv／FD、调用记录、fail-once 与断言；通过既有 runner 声明准确 helper artifact。依赖适用范围调整还需原 Bazel lock 门 |
| network-proxy policy fixture，4 FAIL | 三项原日志显示前置 allowlist 拒绝；一项仅记录 `response.is_none` 断言失败。源码说明四项均经过 DNS／本地地址防护，但没有逐次实际 DNS 答案或延迟证据 | 四个直接调用内存 policy 的 fixture 使用既有 `allow_local_binding` 配置入口，保持 host／path／method、全部原断言与生产默认拒绝／DNS 防护 |
| 官方 marketplace 导入，1 TIMEOUT | 原 60.005 秒块没有内部 stderr；源码确实从空配置推断官方来源并执行真实公共 Git clone | 同一测试子进程使用真实本地 Git 仓库；仅配置官方 URL rewrite 和子进程 local-file transport allow。原推断、add、clone、清单校验和错误断言保留；本地纯 Git 探针通过，仍不是 Rust 门通过 |

这些候选不能抵消 r23 的失败，不能提前记作 source50，也不能据源码推断补造旧运行的 syscall 轨迹。后续须登记精确候选树，再执行受影响 owner 的原严格／完整项目门及默认工作区门。

## 4. 冻结分化研究：执行完成，两个场景均 HOLD

#4890 原 Python 研究保持源码、种子、数据划分、128 步训练、六个对照和门槛不变。normal 与 `python -O` 测试各 24/24 通过；一次完整研究完成 **10 trials、60 arms、11,520 个测试预测**，没有失败 arm。冲突与冗余场景均为 **HOLD**。[完整执行与结果][study]

冲突场景确实生成子分支并改善不兼容任务，但没有在每个种子上比每个对照至少降低 0.0005 MSE；对 fixed experts 的平均增益只有约 **0.00006279064223624**。冗余场景保留原 parent、输出相同，额外诊断增加成本。因此没有科学采用批准。

独立读回检查 **30,720 条预测记录**，最大绝对差 **1.4432899320127035e-15**；按共有工作每 trial 只计一次，核对 **655 个成本事件、49,090,740 estimated FP operations、37,120 routing decisions**。这些是不同单位，不能与秒数或 RSS 相加；也不能再次累计每个 arm 中重复展示的共有预训练成本。[研究读回与成本说明][study]

六臂总计算预算不完全相等，不能声称等总预算优势。此次参数序列化是进程内读回，不是跨主机续训或 live owner handoff；保持旧任务 parent 完全相同，也不能替代真实后端的独立长期保留验收。历史六组模型研究没有在本轮重训，其资格不转移到当前注册表。

## 5. 剩余采用与发布门槛

1. 处理 r23 八项实际不通过，取得精确新源码的 owner 项目门和完整默认工作区结果；失败原件继续保留。
2. 完成约定的最终 scoped fix/fmt、精确最终差异和源码导出，再由最终发布 SHA 的 CI 验证。当前两个步骤均 **NOT_EXECUTED**。
3. 把真实后端、真实 Encoder receipt 与产品 owner 接到共同合约；补齐完整状态、unknown 恢复、当前来源／scope／撤销和最终消费校验。
4. 按具体任务完成独立保留、校准、强检索／精确 KV／固定策略对照与完整生命周期成本验收。历史训练、fixture 回归和测试数量均不能代替这些结果。
5. 形成可分层审阅的 Draft PR；当前分支未创建、PR 未发送，最终 CI 与生产采用均未获资格。

## 6. 证据恢复与阅读方式

本页、[STATUS.json][status] 和 [SOURCE_IDENTITY.json][identity] 是工作区恢复后**重新编写的当前报告**，不是失去的 source49 旧报告原字节。此前已登记到 Git `b14c3288c736ab1c54d2852c797e2646751662ce` 的三份完整 source47／r19 报告，按原 bytes 保存在 [history 快照及清单][history]；其中旧 current 字段只描述当时状态。

r20、r21、r22 的原 archive、日志、raw rc、receipt、资源与源码原件已精确恢复；三个 `*-recovered-checkpoint` 入口记录的是**恢复后新做的读回**。两个独立读者分别重查完整原日志／唯一 ID 和全部源码／离线 Git tree，没有重跑 Rust，也没有伪造丢失的旧审计文件。[r20][r20]／[r21][r21]／[r22][r22]

[r23 完整正式附件][r23] 已封存原 archive、16 份 evidence、6 份 input 和全部独立读回；[独立审计][r23-independent] 重新核对了 188 份源码、离线 Git tree、20,228 个唯一执行结果及八个原失败块。导出与读回成功不改变 Rust 门的失败。较早 root 读回中的历史 pending 字段保持原样，由新闭合记录补充，不覆盖旧回执。

较早的 1,052 个证据路径已在上述不可变 Git 报告树中保留，将复用原 blobs；当前本地目录不要求全部重新下载。链接核验使用“当前本地文件＋既有不可变路径”并集。历史相对链接仍以原报告根为基准。源码、日志、科学数据、归档导出和文档状态各自绑定，不互相授予资格。

[status]: STATUS.json
[identity]: SOURCE_IDENTITY.json
[maturity]: MATURITY.zh-CN.md
[assets]: HISTORICAL_ASSETS.json
[study]: study-evidence/README.md
[history]: history/published-r19-b14c3288/MANIFEST.json
[r20]: native-evidence/r20-recovered-checkpoint/RECOVERY-CLOSURE.json
[r21]: native-evidence/r21-recovered-checkpoint/RECOVERY-CLOSURE.json
[r22]: native-evidence/r22-recovered-checkpoint/RECOVERY-CLOSURE.json
[r23]: native-evidence/r23-workspace-checkpoint/CLOSURE.json
[baseline]: native-evidence/baseline/native-first-receipt.json
[registry]: native-evidence/registry-a/native-registry-a-receipt.json
[projection-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a/codex-rs/hepta-neuron/src/cell_feature_projection.rs
[registry-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a/codex-rs/hepta-neuron/src/cell_registry.rs
[source50-preparation]: native-evidence/source50-provisional-repair/READBACK.json
[r23-independent]: native-evidence/r23-workspace-checkpoint/independent-readback/INDEPENDENT-READBACK.json
