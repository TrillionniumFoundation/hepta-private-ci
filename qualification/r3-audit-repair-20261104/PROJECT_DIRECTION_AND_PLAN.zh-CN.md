# 项目方向与分阶段执行计划

本计划建议把当前主线收敛为：**可复现的跨平台运行基线 → 一个真实的正常业务入口 → 共享计算与可靠数据 → 有因果对照的只读学习闭环 → 真实未来窗口的长期学习**。具身系统、结构可塑性和外部系统吸收沿既有依赖推进。这里的阶段是对 V8 已有路线图的执行排序，不另立全局架构，也不按代码量、PR 数或测试目标数估算完成百分比。

固定依据是 `ff72d462d74f9eb856aa9edbc368caad9c466708` 上的 [canonical DEVELOPMENT.md](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md)、[40 模块注册表](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/modules/MODULES.json)、[91 工作包注册表](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/delivery/WORK_PACKAGES.json)以及 [READINESS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/READINESS.json) / [GAPS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/GAPS.json)。五份源码已重新取回并计算 blob/bytes/SHA；没有重扫所有分支，也没有重跑模块构建。

## 1. 项目的实际发展方向

Hepta 的目标是本地优先、可恢复的多 Agent 系统。其工程核心是稳定的执行与权威内核、单一事实所有权、共享经验和隔离工作空间；其智能层再组合 Objective、NDU、DecisionCell/Neuron/Intuition、Prompt 因子、Bellman/operator learning 和学习账本。执行链与学习链有各自边界：Codex App Server 继续拥有 session/thread/turn/model/tool 执行主干，Agentd 只承担组合和生命周期；优化器生成选择或候选，不直接发执行权限。以上职责在 [DEVELOPMENT §§1、4、5、12、17](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md) 已明确。

当前最有价值的工作是让同一产品树中的正常 caller 真正走通，并在取消、重启、丢失确认、撤销和回滚下保持一致行为。源码、单包测试、协议模拟、真实模型使用、学习收益、外部接受和发布是分别可验证的事实。这样的顺序能让后续模型/学习实验使用稳定、可比较的底座。

注册表的 91 包状态为：

| 静态 registry state | 包数 | 应如何使用 |
|---|---:|---|
| `source_implemented` | 25 | 有相应源码层声明；继续读其实际执行与接受证据 |
| `source_implemented_execution_pending` | 20 | 把剩余执行义务排到对应固定候选与原平台 |
| `source_implemented_semantic_review_pending` | 2 | 先完成其独立语义审查，不能由文档检查代替 |
| `planned` | 43 | 按 Development DAG、模块 owner 与实现图安排工作 |
| `blocked_external` | 1 | 对应 `P0.9-EXTERNAL-GATES`，列具体外部输入与出口 |

40 个模块在注册表中均为 `existing_bound`、`source_root_present=true`；同一注册表的 `production_implementation` 声明均为 false。这表示文档刻意没有自证生产完成，不能解读为“没有实现代码”，也不能解读为“40 个模块已经投产”。READINESS 的闭合是规范/协议/入口语义闭合，其九类外部证据门槛仍单独存在。[注册表与完成语义](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/GAPS.json)

## 2. 七条实现线覆盖全部 40 模块和 91 包

| 现有实现线 | 模块 / 工作包 | 主要职责与先后关系 |
|---|---:|---|
| A Foundation | 7 / 14 | types、wire、authority、operations、evidence、AuthBus、HeptaBao；先稳定共享合同和故障分类 |
| B Runtime | 11 / 19 | supervisor、fleet、agentd、Codex、inference control/worker、automation、Matrix、browser、两类 UI；依 A 组合真实 caller |
| C Memory | 9 / 13 | cognitive types/store/read、retrieval/federation、KG、compact、prompt registry、context compiler；依 A 形成一致快照与单写者 |
| D Objective / Value | 3 / 7 | Objective、NDU、runtime control；依 A/C 形成确定性目标与效用基线 |
| E Learning | 4 / 14 | ledger、operator、eval、artifacts；依 A/C/D 获得不可变 episode 与独立评估 |
| F Adaptive Policy | 5 / 12 | neuron、intuition、prompt optimizer、plasticity、intelligence facade；依 B/C/D/E 进入 bounded shadow |
| G Engineering | 1 / 12 | engineering control；依 A 组织受限源码候选、集成与独立决策接口 |

这个划分直接来自 READINESS，JSON 附件保留了每个模块、owner/deputy、源码绑定、每个工作包及其三组依赖，覆盖 40 / 91 各一次。可以并行准备源码与审查；实际 activation 和 evidence 使用各包自己的前驱，不由 `source_implemented` 一次性推过所有门槛。[实现线与依赖](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/READINESS.json)

## 3. 当前批次：P0 可复现集成基线

**首要交付是一个可审、可执行、证据完整的新候选。** 收齐已经启动的唯一 native lane，各阶段结果绑定固定 source tree，再核 final fmt/fix 与组合 source map。把文档历史引用修复、完整 failed-target shard/attempt 日志采集、UI 两条必要历史 fetch 与子步骤计时纳入所属 PR，随后在实际最新 main 上形成真实 merge candidate。

原 48 ledger 已保留 35 个历史 native PASS，同时将 ff72 现状分为 8 个可见失败名、13 个部分 scope exact PASS 名、11 个仅非缓存目标通过名和 16 个正文未知名；原全矩阵闭合仍是 0。原 48 之外目前可见下界为 18 个新失败名，其中 10 个只属于 retry-stage。这个分层必须随新 CI 的完整 artifacts 更新，不能只盯已经可见的失败。Windows strict 三例、CodeMode capped unknown、Wine suspension、Intel PTY 与两个 macOS skills 原例各自保持原断言和预算。

下一候选的退出标准是：适用 required checks 对真实 head/merge 取得可接受终态，缺失日志补齐，原失败与后续失败有同源证据，无需靠忽略、放宽阈值或概率重试解释绿色。B12 private-state 和 B14 原 13-case 双 Windows lane 的已满足范围保持闭合；distinct server helper、权限边界及其他工作流仍分别判断。完整表见原 48 disposition，而不是从文档状态反推通过。

UI 修复已经有一个新的局部结果：`a69b20c4` 上原 Python discover **13/13 PASS、0 retry、47.297 秒**，完整 raw/status 与 9 文件 hash 已独验。六个 unchanged Gateway 检查仍按原代码查询 `HEAD907d4f5` 的 graph，故该结果只证明本次 13-case native phase；真实 GitHub source/merge UI 任务和原 60 分钟预算仍待执行。独审回执 blob：`88cd502578a06d68b3c6ec1f44de08b8e8f6b7df`。

## 4. P1：一个真实正常入口及其恢复链

当前 registry 的 `currentPackage` 是 `P0.8D-VERTICAL-SLICE`。以它和 `INT-2-AGENTD-CODEX-COMPOSITION` 为主线，组合 UI/API ingress、Objective、bounded Memory/Context、Agentd、现有 Codex execution spine 与可观察终态。包 owner 是 agent-runtime，runtime-control 为 deputy；涉及 UI、Memory、Objective 的修改由原模块 owner 共同审查。[P0.8D 合同](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/delivery/WORK_PACKAGES.json)

这一步使用 B16 正常入口/joint-cohort 接受清单中的真实 producer、授权输入和 caller，不能把内部测试消息或临时 socket 路径当正常产品接线。验证必须覆盖 request/turn/result 关联、approval 阻塞后的恢复、cancel、lost acknowledgement、process restart、revocation、重复提交和 rollback。Queue ACK、工具 ACK 与 terminal external effect 分别记录；未知效果继续通过当前 fence reconciliation 求证。

role sockets、approval-blocked cold recovery 等 PR 可以提供组件。采纳前要对当前精确 base/head 的净 diff、caller、owner 和与本产品树的冲突重新核对；通过同树运行再提高对应声明。不能要求所有 40 模块和研究方向都完成后才交付第一个 bounded 产品路径，也不能让一个路径成功覆盖其他模块的义务。

## 5. P2：共享计算与可靠数据基础

沿 `INFER-V4-T1…T5`、Fleet allocation、Memory store/read/retrieval、Objective、确定性 NDU、Prompt registry、episode ledger 和 artifact registry 工作。共有类型先稳定，依赖它的 runtime、Memory 和 Objective 源码可以并行准备；activation 顺序仍遵循各自 DAG。

具体交付是一个经实际 caller 使用的共享 Encoder/Cell/worker 实现，有限队列与 sparse microbatch，以及一致的 snapshot/source/forget frontier。测试真实 **64 / 256 / 1024 / 4096 logical Cells**，同时记录 active concurrency；给出质量、CPU/RSS、p50/p95/p99、队列 age、token 和总成本，避免把配置规模当实际容量。Memory Cell 应是可重建的 source projection，correction/forget 需要跨 reader、KG/index、compact/federation 和 artifact 消费者验证。[P2 与性能合同](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md)

退出标准是：一个 authoritative writer 对应一个 durable domain；跨 owner intent/outbox/dedupe/ack/reconciliation 可恢复；资源基线可复现。这样后续模型与学习实验才有可比账本。

## 6. P3–P4：先 shadow 比较，再完成首个只读因果闭环

P3 固定候选总体、输入、预算和 deterministic / strong-retrieval baselines，比较真实 local model、Neuron、Intuition、Prompt 与 Bellman/NDU shadow 候选。proposer、scorer、selector 分开；unavailable、负例、OOD 和 abstention 保留在原总体。分别报告 answer generation、Reader capacity、retrieval utility、citation entailment 与 parameter-learning benefit。

P4 执行 `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`：从 request 和 Objective receipt 出发，经 bounded retrieval、NDU/Prompt portfolio/timing、Context receipt、报告、outcome/correction 和 attribution，产生下一快照的 shadow candidate。对 no prompt、单 factor、pairs、full portfolio、fixed timing、learned timing 做预声明消融。原 C1 的 zero Memory/KG/tool/provider-effect 合同保持；主要指标为任务与检索收益、引用准确、陈旧/冲突拒绝、abstention、成本/延迟及 calibration/OOD。[P3–P4 与 C1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md)

这里的退出是“因果收益与代价在固定总体和预算下可复核”，并不是把离线 loss 或一次生成成功升级为长期有效学习。current-run objectives/artifacts 保持不可变。

## 7. P5：真实未来窗口、回滚与不可复活

沿 `ART-2`、`LONG-1…3` 和 causal evaluation 进行 next-snapshot reload、predecessor rollback、未来日历 holdout、retention/forgetting 与 unlearning non-resurrection。保留签名输入、模型/规则/状态版本以及 delayed outcome 的时间来源。

这一步的外部等待要明确记录窗口、owner、输入和下一次采集动作。未来窗口尚未发生时保持待证状态；离线重放不能替代它。只有实际消费者验证删除/撤销传播到 Memory、KG/index、Prompt、compact、federation、缓存与 signed artifacts，并完成独立跨窗口评估，才能按 canonical claim ladder 提高学习声明。[长期学习与完成阶梯](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md)

## 8. P6–P8：把高级能力放在实际依赖之后

- **P6 可塑性与自迭代候选：** eligibility/homeostasis、replay、world-model、PromptFactor evolution、参数可塑性和工程源码候选逐项推进。结构 Cell Split、topology canary 与 source evolution 在先前证据和独立决策之后；候选生成、selection、promotion、release 分别记录。
- **P7 具身：** 从共享 sensor/body/reflex/actuation 类型、确定性本地控制和终态 reconciliation 开始，先 simulator/HIL，再验证真实 target-host 时序、emergency stop、恢复和 safety evidence。实际物理动作沿既有 activation 门槛。
- **P8 外部系统吸收：** 对 owner 授权的 non-privileged Debian/POSIX fixture，从 read-only discovery、manifest/contract 到 credential-free sandbox、可回滚迁移，最后显式 host enrollment。每个外部作用和宿主加入都有当前 owner consent 与真实 consumer 证明；不从独立仓库成功推断已纳入本产品树。

B16/B18/B19 的具体 caller、凭据/证书/数据输入、policy HOLD 与 operator acceptance 由独立外部门禁计划列清。工程团队应完成可自主解决的源码、控制和可执行接受包；真正依赖外部 owner、未来时间或目标硬件的部分使用有明确出口的 `BLOCKED_EXTERNAL`，不伪造“全部闭合”。[外部 capability gates](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/GAPS.json)

## 9. 每个工作包的完成记录

每项工作只保留足以审查的实际信息：exact source/tree/parents、owner 与变更语义、必需的原例/负控/平台结果、剩余输入与执行动作、rollback 或 reconciliation 处理。普通源码变更继续正常 PR 和适用检查；真实运行、外部作用、独立评价或 release 才消费对应门禁。

Development、Activation、Evidence 三组前驱分别核对。源码准备和只读审查可并行，当前共享 native lane 保持单一 mutator；报告注明 case、target、cache、retry、unknown 的层级。一个 package 保留一个可审主集成候选，吸收 donor 时逐项比较净变化并保留有用历史。

18:57 UTC 的 root 增量观察另存为 live delta：#4800 更新为 `1b390853e50aa2fdae2e6c68793f94742d2d667c`、10 files；#4803 新增 `83ad164ff05cb34d444d51e23ee286fa0241c783`、3 files、独立旧 base `14e2`。两者均未混入当前候选；本计划没有重复全量抓取或把这些增量当新的分支总数，先前完整 1081 PR / 5146 branches 快照保留。新 head 的 source/执行资格需要重新核对，旧 head 的审查和独立仓库结果不自动继承。

## 固定源与附录

| 来源 | Git blob |
|---|---|
| DEVELOPMENT.md | `9ff53000ff301289d87c364eb45a938755a0f11e` |
| MODULES.json | `2571766d45a0a6b0db0ec83e675c70609d3bc39d` |
| WORK_PACKAGES.json | `77568a3965c4c68357b2e16f6af10309209b35dd` |
| READINESS.json | `2b56ff94aad7e6a0e19b0c2a600a2c3cd3616729` |
| GAPS.json | `aa01454cf24a60b8f0c61a8440d5177dced8d7a0` |

机器可读附录包含全部 40 模块、91 工作包及三组依赖、7 条实现线、9 个阶段的 actions/exit conditions、9 个外部门槛和本次 evidence refs。它是审计工作产物，未修改 canonical 注册表、Git refs、生产宿主或共享 native 工作树。
