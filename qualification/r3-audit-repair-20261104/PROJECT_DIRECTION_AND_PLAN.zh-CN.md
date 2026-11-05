# 项目方向与分阶段执行计划

本计划建议把当前主线收敛为：**可复现的跨平台运行基线 → 一个真实的正常业务入口 → 共享计算与可靠数据 → 有因果对照的只读学习闭环 → 真实未来窗口的长期学习**。具身系统、结构可塑性和外部系统吸收沿既有依赖推进。这里的阶段是对 V8 已有路线图的执行排序，不另立全局架构，也不按代码量、PR 数或测试目标数估算完成百分比。

固定依据是 `ff72d462d74f9eb856aa9edbc368caad9c466708` 上的 [canonical DEVELOPMENT.md](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md)、[40 模块注册表](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/modules/MODULES.json)、[91 工作包注册表](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/delivery/WORK_PACKAGES.json)以及 [READINESS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/READINESS.json) / [GAPS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/GAPS.json)。五份规范源码已重新取回并计算blob/bytes/SHA；当前cabc完整tree中的五个blob均与该固定依据相同。后续全量分支清点和实际工程执行另见本计划第3节，不把规范注册表状态当作运行通过。

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

**先完成当前工程修复、更新现有Draft PR，再以新提交的原始跨平台CI验收。** 当前原23项账本为8项范围内闭合、14项开放、1项科学HOLD。既有局部结果与原失败均保留；工程发布候选与后续Memory大改分阶段执行，避免等待尚未编译的方案阻塞已完成修复。

最新完整清点覆盖2026-11-05 03:16–03:24 UTC：1103个open PR，其中1079 Draft、24非Draft；5193 branches，155 main-base/948 nonmain-base，最长依赖链211；0个open非PR issue/0个release。逐页到空页并核终锚，不把多时点查询称为原子快照。旧22:27的1088 PR/5163分支及下文18:57历史增量分别保留。当前候选仍是PR #4797，目标base为integration/ui-objective-20261103-product，main观察为732e934。没有合入main或改变目标base。[本轮完整进展](CURRENT_AUDIT_PROGRESS.zh-CN.md) / [新完整库存](fourth-repository-inventory-20261105.json)

此前f825组合源已执行原25项权限回归25/25通过；原七包选中5416项，其中5408 JUnit PASS、8 FAIL；原全工作区19503项为19485 JUnit PASS、17 FAIL、1 TIMEOUT。24项requires-remote早退已逐名绑定原始输出；后续另核1项原capability早退，已知25项省略行为，均不当作对应行为执行。完整raw/JUnit/catalog/程序身份已独立重建与核验。[完整原始证据](fourth-f825-full-owning-complete-root-review.json)

此后三项修复已按各自固定源验收：Skills修正Table.insert后取得有效marker完整roots负控，恢复后原9例PASS；Migration负控到达原子进程588行的[]与官方名断言，恢复后原166例PASS，正例原日志1613–1627行保留两层同名成功；V8原6例及runtime68＋两个原integration共76例PASS。这三项修复的终态源树为7d703610ae4f778ad305ebc139860d276f416e8c，原Bazel update/check实际exit0，耗时111.734/0.493秒，双锁身份不变。前三组原测试均零重试，第一次Skills准备panic仍单列为无效负控，未借局部通过关闭新账本ID。[三项修复与锁门根审](fourth-three-repairs-v3-root-review.json)

App父存活V2已取得3项有效因果反例；八项正例中原App断连、3项原reaper及3项新控制实际通过，1项原capability因宿主前置缺失早退，原wrapper failure保留。完整157件原件已经独立重建。Windows窄ACL与四格DELETE/父DELETE_CHILD源码已整合，但Linux不提供Windows原生资格。Python原57项实际通过，普通index内容语义已只读核准。fb9原完整工作区现已执行，19,506项中19,490 JUnit PASS、16 FAIL，并保留25项早退；新增线程恢复与代理响应失败的原因保持OPEN并单独继续定位；最终fix/fmt和差异检查已完成，按现有Draft提交这批源码及证据，以固定新提交运行原Windows/macOS Intel/Linux等CI。原始断言、5秒/2秒等预算及零重试保持各自范围。[App完整根审](fourth-app-parent-liveness-v2-complete-root-review.json) / [新full逐项根审](fourth-full-fb9-nonpass-root-review.json)

原helper目录意外缺失的诊断已保留，原因未知；epoch2以f825在全新目录重建并绑定自己的程序身份，原1例FAIL/5.491秒，外层bwrap已消失而inner helper及Python仍存活。之后临时观测树1e936再次执行同一原例，FAIL/5.575秒；PR_GET在inner_entry与inner_after_restrictions均rc0/signal0，原killpg为Ok(())。50件原件及精确恢复f825已经独立核验；观测未定位清除信号的具体步骤，新的父存活候选首个native反事实在5.005秒因libtest banner与marker同一行而停于因果阶段前，未到kill/reparent/arm；该无效负控已精确恢复d8a5e94，新增一行println!后V2已完成3项有效因果反例及8 JUnit PASS，其中仅7项行为实际执行，原capability早退与严格controller1保持开放。两次失败和首次前置停止各自保留，不把诊断算修复通过。[epoch2原终态](fourth-app-epoch2-terminal-diagnostic.json) / [新观测50件与恢复根审](fourth-app-parent-probe-complete-root-review.json) / [首反事实无效与恢复](fourth-app-parent-liveness-invalid-negative-root-review.json)

原平台仍有73个ledger名字缺至少一个平台的充分逐例证据，已收敛为10个查询组、7个原目标和33个target/platform配对；最终必须绑定实际发布head与执行merge tree。现有Windows private-state和13-case resume的已满足范围继续闭合，其余strict token、Intel PTY、TUI与正常UI接受分别验收。现有ARM Mac或Linux Intel环境不能代替所需平台。

退出标准是固定新head、目标base和实际merge tree的适用必需CI终态成功，原失败有同源修复回执，完整原输出能逐例说明通过、忽略、早退与未知。当前尚未满足此退出标准。[原23项账本](current-blockers.json)

## 4. P1：一个真实正常入口及其恢复链

当前 registry 的 `currentPackage` 是 `P0.8D-VERTICAL-SLICE`。以它和 `INT-2-AGENTD-CODEX-COMPOSITION` 为主线，组合 UI/API ingress、Objective、bounded Memory/Context、Agentd、现有 Codex execution spine 与可观察终态。包 owner 是 agent-runtime，runtime-control 为 deputy；涉及 UI、Memory、Objective 的修改由原模块 owner 共同审查。[P0.8D 合同](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/delivery/WORK_PACKAGES.json)

这一步使用 B16 正常入口/joint-cohort 接受清单中的真实 producer、授权输入和 caller，不能把内部测试消息或临时 socket 路径当正常产品接线。验证必须覆盖 request/turn/result 关联、approval 阻塞后的恢复、cancel、lost acknowledgement、process restart、revocation、重复提交和 rollback。Queue ACK、工具 ACK 与 terminal external effect 分别记录；未知效果继续通过当前 fence reconciliation 求证。

role sockets、approval-blocked cold recovery 等 PR 可以提供组件。采纳前要对当前精确 base/head 的净 diff、caller、owner 和与本产品树的冲突重新核对；通过同树运行再提高对应声明。不能要求所有 40 模块和研究方向都完成后才交付第一个 bounded 产品路径，也不能让一个路径成功覆盖其他模块的义务。

本次#4812普通PQ/FinalUse和后继#4821本地operation事务是可评估组件donor，不能盲合：#4812对cabc ahead771/behind470，当前头没有Actions，原native结果属于更早源且HOLD；#4821仍明确拒绝未具备Cell lifecycle admission的public调用。先核Current/claim/frontier/issuer与当前sender/普通peer gate，再与已准备native token、两个pool caller和private checkpoint的实际resource owner接线逐项组合；这些依赖的真实执行和正常接受仍开放。[固定donor与资格](FOURTH_DONOR_PROGRESS_20261105.zh-CN.md)

## 5. P2：共享计算与可靠数据基础

沿 `INFER-V4-T1…T5`、Fleet allocation、Memory store/read/retrieval、Objective、确定性 NDU、Prompt registry、episode ledger 和 artifact registry 工作。共有类型先稳定，依赖它的 runtime、Memory 和 Objective 源码可以并行准备；activation 顺序仍遵循各自 DAG。

具体交付是一个经实际 caller 使用的共享 Encoder/Cell/worker 实现，有限队列与 sparse microbatch，以及一致的 snapshot/source/forget frontier。测试真实 **64 / 256 / 1024 / 4096 logical Cells**，同时记录 active concurrency；给出质量、CPU/RSS、p50/p95/p99、队列 age、token 和总成本，避免把配置规模当实际容量。Memory Cell 应是可重建的 source projection，correction/forget 需要跨 reader、KG/index、compact/federation 和 artifact 消费者验证。[P2 与性能合同](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md)

#4817的Memory V15可供协议/负控参考：实际53例属于同hostPython与历史设备收据离线核验，33路径没有Rust/native集成。不能用它替代本产品writer custody、Current或新的语言质量/完整成本证明。

退出标准是：一个 authoritative writer 对应一个 durable domain；跨 owner intent/outbox/dedupe/ack/reconciliation 可恢复；资源基线可复现。这样后续模型与学习实验才有可比账本。

## 6. P3–P4：先 shadow 比较，再完成首个只读因果闭环

P3 固定候选总体、输入、预算和 deterministic / strong-retrieval baselines，比较真实 local model、Neuron、Intuition、Prompt 与 Bellman/NDU shadow 候选。proposer、scorer、selector 分开；unavailable、负例、OOD 和 abstention 保留在原总体。分别报告 answer generation、Reader capacity、retrieval utility、citation entailment 与 parameter-learning benefit。

P4 执行 `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`：从 request 和 Objective receipt 出发，经 bounded retrieval、NDU/Prompt portfolio/timing、Context receipt、报告、outcome/correction 和 attribution，产生下一快照的 shadow candidate。对 no prompt、单 factor、pairs、full portfolio、fixed timing、learned timing 做预声明消融。原 C1 的 zero Memory/KG/tool/provider-effect 合同保持；主要指标为任务与检索收益、引用准确、陈旧/冲突拒绝、abstention、成本/延迟及 calibration/OOD。[P3–P4 与 C1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md)

#4823已从正文观察推进到独立原件复核：452件文件逐件核验，5个既有拟合检查点的有限Bellman J−C在IID/OOD均超过预定0.005收益下界；15个直接/门控/半径权重编辑候选均被VAL拒绝并恢复C。这个有限规划收益值得作为下一步可复现基线，不能替代原D−B采用条件。下一科学门应明确额外规划计算的总成本、重新冻结未暴露的分布与未来窗口，并区分新拟合重复和同拟合下的多个世界。当前CPU台账有缺口，Qwen仅保存CPU F32小窗口比较、native仍未取得生产/独立holdout资格。原#4798源77b244及B18的采用门/HOLD不变。[完整科学独审](scientific-pr4823/INDEPENDENT_REVIEW.zh-CN.md) / [根审重算](fourth-pr4823-root-review.json)

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

18:57 UTC 的 root 增量观察另存为 live delta：#4800 更新为 `1b390853e50aa2fdae2e6c68793f94742d2d667c`、10 files；#4803 新增 `83ad164ff05cb34d444d51e23ee286fa0241c783`、3 files、独立旧 base `14e2`。两者均未混入当前候选；该历史增量不是全库快照；先前完整1081 PR/5146 branches及1088 PR/5163 branches快照保留，当前全量以03:16–03:24的新盘点为准。新 head 的 source/执行资格需要重新核对，旧 head 的审查和独立仓库结果不自动继承。

## 固定源与附录

| 来源 | Git blob |
|---|---|
| DEVELOPMENT.md | `9ff53000ff301289d87c364eb45a938755a0f11e` |
| MODULES.json | `2571766d45a0a6b0db0ec83e675c70609d3bc39d` |
| WORK_PACKAGES.json | `77568a3965c4c68357b2e16f6af10309209b35dd` |
| READINESS.json | `2b56ff94aad7e6a0e19b0c2a600a2c3cd3616729` |
| GAPS.json | `aa01454cf24a60b8f0c61a8440d5177dced8d7a0` |

机器可读附录包含全部 40 模块、91 工作包及三组依赖、7 条实现线、9 个阶段的 actions/exit conditions、9 个外部门槛和本次 evidence refs。它是审计工作产物，未修改 canonical 注册表、Git refs、生产宿主或共享 native 工作树。

## 最终代码与下一道门禁

第四批共22个连续源提交，终点为 `20fd174ded4e5ce01bda34e4f6d1d74803301f49`，最终原生代码树为 `4a3374e22e16ce5c764288ad018cd9affadf94ea`。原 `just fix` 实际exit0（220.947秒），只删除当前Linux64范围两处同类型转换；原 `just fmt` 实际exit0（42.684秒），17文件的完整改动已经双重审查。随后两项原/完整候选差异检查均exit0（0.287/0.294秒），完整54路径映射重算得到同一个Git树。两次自动改动后的controller3是保留的审查停点，最终controller为0；这些成功不覆盖完整测试的16FAIL与25项早退，也不提供Windows或Intel原生资格。[最终收口根审](fourth-final-A-complete-hygiene-root-review.json) / [完整索引原件复核](fourth-windows-index-complete-root-review.json)。

下一步按现有Draft提交本批源码及证据，绑定新head、base、真实merge tree和原工作流。Core新增失败的裸线程缺失错误更符合rollout flush传播路径，但尚未定位哪一次flush；Proxy存在原2秒DNS与原2秒读取预算的静态竞争可能，原日志尚不能证明实际进入DNS。两项继续OPEN，观测候选尚未执行。[Core诊断](diagnostics/core-cold-root-fb9/CORE_COLD_ROOT_DIAGNOSIS.zh-CN.md) / [Proxy诊断](diagnostics/proxy-connect-fb9/STATIC_DIAGNOSIS_ZH.md)。

B16最后实测剩余空间为23,893,377,024字节，旧40,122,997,968字节foundation预算不满足。仅foundation复用既有构建产物路径的条件方案正在独立复核，执行前仍须重新量取容量并满足完整资源门；本批没有执行B或关闭其正常入口/真实接受门。容量变化未归因于本任务或其他具体进程。
