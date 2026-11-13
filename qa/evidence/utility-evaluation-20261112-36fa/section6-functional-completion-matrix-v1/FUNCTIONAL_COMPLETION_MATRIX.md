# 第六节功能完成矩阵与下一可实施边界

## 当前结论

当前已经有原 owner、签名、冻结契约、真实读回、同一 operation 和同一 Cell 的具体机制；**普通产品入口、真实独立任务链、daemon 与 Root 的完整进程冷恢复仍未闭合**。支持真实授权 A→T→独立 B→Adopt 或完整 NoUpdate→新 C→双进程冷恢复的成功次数仍为 **0 / Unknown**。这不是仅剩归档或运行的问题：正常启动与跨进程 task custody 还有具体接口工程。[H1][H2][R1][R2]

本文按用户“第六节”的四个小节及末尾目标整理。范围是 5 份既有固定审查和 20 个精确匹配最终源码库存的窄源码读审；不是再次全仓扫描，也不声称未抽核的某机制不存在。精确源码为 `b6084394a4a38ab495c16eaba09e879f04a96f8e`，树 `8ebb37e523ad3932a58cf016af0a9f4e0eeb6638`。本文没有执行项目代码、QA、Rust、H 或资格入口。

## 要求、已有实现和实际差距

| 用户要求 | 已有具体实现与证据 | 当前仍未完成的部分 |
|---|---|---|
| **1. 外部 NDU 目标与奖励契约分离**：用户目标、后果预测、策略、critic、独立结果各有固定身份，不能改目标或权限来证明进步。 | Objective 模型区分不可补偿约束、软偏好、外部终态谓词与中间信号；RunStart 保留原签名、目标语义字节和独立的协议函数字节，并核各自摘要。原 learning request 在 D/T 前冻结评价 profile。OPE 将行为概率、评估概率、预测值和后续 finalized outcome 分开；缺失 outcome 不变成零。[S1][S2][S3][S4] | 把这些已有类型接到**同一次真实 A**的已授权 ObjectiveStart、原 Source/Decision/Outcome 和冻结公开奖励契约；逐项证明实际任务中目标、观察定义、critic 和权限未被事后换掉。OPE 是纯估计器，NDU 证书也是无授权证据，均不能自行证明上述真实来源或效用。当前抽核没有外部奖励契约在完整部署链中实际兑现的证据。 |
| **2. 比较完整可部署系统、最强对照、退化与全部成本**。 | Cell/bundle 和 candidate material 接口有原模型材料读回；B 输入由实际 opaque D/T/Candidate 推出双方 manifest，未先跑辅助 E/Model。MetricRole 将主指标优越、非劣界限、绝对约束分别冻结；每个主指标与安全界限分别判定。CellTaskCost 保留训练、规划、critic、通信、评价等 12 阶段；失败/取消/拒绝仍计入；未知不补零；inclusive envelope 不重复加账。[S3][S5][S6][S7] | 真实可获取且合法使用的 base、adapter/Cell、router/selector、配置/工具与任务分布尚未组成可部署比较。没有完成“最强可部署对照”的外部选择与同口径实测。现有成本类型**不证明计量覆盖**；实际训练失败、取消、搜索、评价、下载和服务仍需接原 owner 的真实事件，冻结计量/分摊规则并保留未知。旧/稀有/安全任务、隐私与授权必须逐项有实际通过证据，不能由平均收益抵销。 |
| **3. 检查任务来源、训练谱系、模型和运营控制；动作影响结果时保留决策前数据并冻结或 crossfit critic**。 | SignedEvidence 原验证同时核 principal、credential chain、key、scope、时效/撤回及 controller collision。CrossFoldPlan 核 training/holdout 的 principal、episode、window 不交叠，固定模型/预测与 final holdout 的单一使用。OPE 核完整候选、propensity 支持、ESS/权重、独立最终结果与证据；不默默裁剪权重或填补结果。[S4][S8][S9] | 原 host-owned trust 仍须来自真实授权者；自报不同 key、字段或 fixture seed 不证明独立。实际 B 的任务来源、训练数据谱系、评估模型、运营控制、决策前状态/策略/propensity 和 critic 冻结时点必须能读回并认证。谱系集合和本地 seal 只约束所供材料，不认证真实观测时点；识别条件不足继续 Unknown。 |
| **4. Adopt、完整 NoUpdate/Ineligible、InsufficientEvidence/Unknown、确定性 ObjectiveFraud 必须不同**。 | 独立评价有 EligibleForIndependentSelection、Ineligible、InsufficientEvidence 三分；完整性优先，已知坏指标不能覆盖其他缺证据。三个原负例针对这一边界。训练 QuantizedWeightsUnchanged 只是 TrainingNoUpdate；学习协议还保留 Selection/NextUse，只有原新任务 committed readback 才可成为 UsedByNextTask。[S3][S9][T1] | 还需把上述原结果贯通正常产品出口和真实 C。Eligible 不是 Adopt，训练未变化不是完整 NoUpdate，未知 ACK/Unavailable/超时不是已拒绝或未执行。**本次窄证据未认证一个已贯通的 ObjectiveFraud 确定性生产判定**，这不是全仓“不存在”的结论；后续须定位原确定性判定或补最窄可复核分支，不能把 SourceChanged、门禁失败或 Unknown 改称 fraud。 |
| **末尾目标：真实 A→T→独立 B→Adopt 或完整 NoUpdate→新 C→daemon+Root 真冷恢复**。 | 已实现 purpose 固定的 Root candidate handoff/service、原十角色流、pidfd/peer/截止与只读限制；有 Fresh Material/T/B 和 publication 分阶段机制准备。非 Clone initial Root custody 消耗原 Prepared/Ready，保存具体 Current/Artifact/FinalUse；factory 保留原 PublishedTask 与同 Cell/Source；cold entry 走原 existing Current/journal recovery。9 个新 ignored Root 用例覆盖同 operation、原 task/drain、错误后 readback、已有 store reopen/撤回。[H1][H2][S7][R1][R2][T2] | **12 个新公开 custody 方法目前无非测试调用者**，普通 main/Root host 未装配。新 cold tests 明示是丢旧 custody 后同进程重开 existing store，未证明 Root/daemon 进程冷启动。真实独立 B、新 C 实际采用、可持续模型读取和合法材料授权未完成。已有三 UID harness/测试 FileCas 不等于部署拓扑或生产 Root CURRENT。 |

表中的“实现”是实际源码能力，测试是已编写并登记的机制用例；本文不把它们写成已执行成功。

## 能继续做的工程单元

以下按依赖顺序列出具体产物。现有用户“全量冲”的工程授权允许继续准备这些代码；各单元仍须正常源码审阅与原执行审批，不能通过新 owner 身份、宽化 UID 或伪造 grant 来省略原前置条件。

| 顺序 | 可实施代码工作 | 必须保持的边界与验收 |
|---|---|---|
| **E1：普通 Root typed 装配** | 在真实 Root host 中接原 protected root/lease/issuer 工厂，并**消费显式传入的原 Artifact、selected generation、FinalUse consumer、目标 journal/witness**，调用原 prepare/recover 和现有 custody。 | `open_original_issuer_custody` 只给 root/clock/lease/issuer，不能冒充 generation authorities。初始 grant 和 retained same-model grant 的 purpose 不可互换；不开放任意 callback、owner getter、通用 RPC 或新签发者。[H1][H2] |
| **E2：Root task 服务与非 Root daemon 接口** | 为一个固定 task/operation/purpose 建立具体 Root-owned 执行/读回/retirement 服务，保有真实 PublishedTask、factory 创建的 Cell/Source 与 live Current。给原 daemon 安装封闭的 invocation/readback client；窄拆现 `into_q24_task` 同时消费 AgentdConfig 的接缝。 | 当前 launcher 在 runtime 前 `drop_to_owner`，而 custody install/drain 要真实 UID0；不能把新方法直接插到降权后的 receive/run。唯一 AgentdConfig/writer 继续留原进程；同 Arc task/Cell/drain 留真正拥有者。不能靠 Current-only RPC、平行 Cell、复制目录或提高 daemon 权限解决。[H1][H2][H3] |
| **E3：连接正常 learning/handoff 路径** | 从现有 Registration 与 Root 授权装配真实十角色 channels、trusted Material/protocol/loaded baseline/verifier，调用现有 candidate service；在正常 daemon 启动中完成真实 stage owners 的消费。保留 Pending→原 CAS/Experience→Dataset→Training 的原顺序。 | checkpoint/JSON/摘要不能自授予权限；未装配必须继续拒绝。T/E readonly 共享必须同原 Arc、单 channel/nonce/128 与原绝对截止；四连接上限、pidfd、原 UID/boot/start、一次消费均不变。新框架空 provider 不算此项完成。[H1][R3] |
| **E4：真实消费者与进程冷恢复** | 正常新 C 必须经实际 runtime/control ObjectiveStart 和原 Source/Cell 读回，消费可获取的原模型材料。为 E1–E3 增加真实进程退出/重启后的 existing Root CURRENT、Artifact/FinalUse、generation journal、Source/Cell 重建与同 operation readback。 | warm `recover_original` 和同进程 reopen 不能代表进程冷恢复；冷入口只走原 recover，不 reprepare、补 grant、重置 nonce 或 Create fallback。install/drain 错误可能已发生 durable effect；未知 ACK 保 Unknown。现机制 `finish` 的 5 秒超时不证明任务已经 join，必须明确记录；如要增强终态证明，另作持有 handle 的受界 abort/join 设计，不能只延时。[R1][R2][T2] |
| **E5：真实评价、成本与结果出口** | 沿原注册/冻结计划接真实 B 的证据与全成本事件；把全系统 manifest、对照、任务分布、约束及四类结果连到正常输出。对 ObjectiveFraud 先核原确定性判定接口再决定最窄实现。 | 不重写目标/评价规则，不用 prepared 负例代替真实 Ineligible，不用模型根代替材料可读/授权。量表、margin、隐私/授权检查和 meter 覆盖必须来自冻结契约与原可读事实。[S1–S9][T1] |

**E1–E4 是明确可继续实现的产品工程，不能统一归为“等待外部授权”。** 但 E1 接收的真实 owner 对象以及 E5 的独立观察不是代码可以创造的事实；缺少时应具体报告缺哪个原输入、哪个阶段仍 Unknown。

当前 source/native 资格入口须先沿原 14 phases 和精确 48 Root parents 完成；这只验证工程候选。即使原 gates 全过，也不会自动提供真实 A/B/C、持续模型可用性或外部授权。[Q1]

## 需要真实提供的输入，不由 fixture 或摘要替代

- **A 与公共目标契约**：原用户/任务授权的完整 ObjectiveStart、原 Source/RunStart、决策前状态及随后完整 Decision/Outcome 签名；既有完整 snapshot codec 仅传输与重放，不能签发 A。
- **Root 与 generation custody**：原 protected Current/operation、真实 Artifact trust/lease/head/withdrawal、实际 selected payload/registry、同 binding 的 FinalUse grant/consumer frontier、原 target journal/witness。Root 私有 store 和 UID60001 fixture store 不可互换。[H3]
- **T、材料与新 C**：真实原训练 owner、原 custody 文件/witness/Generator、可访问且合法的模型/adapter/bundle 材料、原认证通道；C 的实际运行与 committed readback。内容根只承诺内容身份。
- **独立 B 与 causal 输入**：任务来源和 lineage、评估模型与运营控制、真实 observer 签名、冻结 critic/crossfit 与 propensity/延迟结果。当前 B 四 objective 字段解耦已是 test-only 代码，仍先核实际 opaque D/T/Candidate；它不授予 Source 或独立性。[S7][S8][S9]
- **比较与成本**：最强可部署对照的实际全系统包、冻结任务分布/非劣与绝对约束、隐私/授权证据、所有成功/失败/取消/下载/服务的实际计量。未测项保 Unknown，不用预算上限当实际支出。[S5][S6]

## 证据与状态截止

已实际完成的工程运行是独立维护 41e 的 fix=0/fmt=0、50f 的四非 Rust 更新与最终 fmt=0（formatter 无新变化），以及 5a9 canonical alignment 正常 0；它们不是真实学习链或本轮原 source/native 门禁结果。原先另一合同的 fix101 失败记录不被覆盖。此矩阵截止，source/native 最终资格结果仍未收到；READY 配置和 source bootstrap 同行仅是可执行准备。[Q1]

冻结登记为 633 boundaries、442 protected、45 paths/288 scopes、ordinary 34 scopes/17 literals、64 QA/607 methods、48 Root parents。该组数字是登记与计划范围，不能由此推出测试运行或效用。完整 evidence refs 见 INPUTS.full_get.json 与 PURE_SOURCE_BINDING_REVIEW.json。下列是阅读入口：

| 引用 | 精确原件 |
|---|---|
| H1 | 正常 host 接线审查 `301ac7b630d378729010ddef119a29c5b8865e1c` |
| H2 | 同进程可表达性与非 Root 部署接口边界 `e0fc0094fc489637e0b83c32c9ccdcf8053b293c` |
| H3 | 原 CURRENT/跨 UID/B 输入工厂审查 `50a182e905aca1e388bafe4dffe28277a7c568d9` |
| R1 / R2 | 当前 `neuron_generation_initial_root_custody.rs` `ae30e3bddeec100da2f609df60fc1571ef9a78be`；`neuron_generation_initial_root_cold.rs` `c38f1b85029ecba6f9cdc9a73cf2bf719f7ec6c0` |
| R3 | 原 Source/first-admission API 审计 `2dfea484b9cb17751771d53fcc9f2ad7fcf1ffa2`（既有冻结审计引用；本轮没有重新全仓审） |
| S1 / S2 | `hepta-objective/src/model.rs` `9a32e109815e0f53b61349bae1834d1eb183e6f1`；`hepta-learning-ledger/src/run_start.rs` `cb387137df02044221c2b2caa0bc8db0ccde3fd7` |
| S3 / S4 | `learning_iteration_types.rs` `827d05abc541498920013465880e6fd4211088b9`；`ope.rs` `52fb8b882012f2561c65a95639a63da8e2c12ff4` |
| S5 / S6 | `metric_roles.rs` `8916bbdb97f79a8a77da7b1e637b8f51f1296ec2`；`cell_task_cost.rs` `c73cb763cbf2bd753ae44ce74e33da0a3f951772` |
| S7 | 当前 B 输入支持 `circuit_original_evaluation_fresh_training_support_tests.rs` `9d31107258d2987112cdff7edc8baf247d6e467e`；这是机制 fixture |
| S8 / S9 | `signed_evidence.rs` `214cae5c9fc4e60598a572faeca5d92c87b0be7f`；`closure.rs` `97d6c9cbc151cb5373ca900a7915f8f38ff941aa` |
| T1 | `closure_incomplete_evidence_tests.rs` `af1c2da4aa90588a69f6d9024eeebc7c2b48a7d8`：三项完整性负例，未在本审查运行 |
| T2 | custody 五项 `438767164b3f231f6f3c39003f7f1f44dbcb69f9`；cold 四项 `795fa0a9639a9dd4156dd3de91e78456cd8955ee`，全部 direct ignored Root 机制测试 |
| Q1 | 41e RESULT `b87aed7647ac34e3db0e381110bf685438aee0ee`；50f RESULT `800869ed57256984964dd3c8b9f29e09c496438a`；5a9 RESULT `5aa9590a7b68504bd58ad0d0b889605c7e8ad71d`；READY 变体同行 `04aa27bbad0d49bdb787116d9bc3911d90e28845` |

本报告不改变任何源码、协议、限额、权限、候选或许可字段。当前最小产品收口方向是 E1 的真实 typed 装配与 E2 的实际同 owner task 服务；实现后再沿 E3–E5 证明完整任务链，不能把机制具备写成部署完成。
