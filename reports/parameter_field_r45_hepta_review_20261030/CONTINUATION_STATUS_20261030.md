# Execution04 续报：launcher 已启动，科学执行仍等待资源准入

**状态时点：2026-10-30 00:24:34 EDT（America/New_York；2026-10-30T04:24:34.447574+00:00）。** 本报依据同一次 STATUS 稳定字节快照；快照读取于 2026-10-30T04:24:40.434060+00:00。这是固定历史时点的执行报告，后续内存波动或进程进展不回写本报的观察事实。机器字段保留 UTC。

正式测量 launcher 已在 **2026-10-30 00:00:50 EDT** 启动原 supervisor。此后截至本报时点，supervisor 仍为 **initial_capacity_admission**，children 为空，科学任务完成 **0/14**、已核验阶段 ACK **0/17**。本 execution04 的科学训练工作仍为 **0**；**343,808 gradient microsteps 是原计划数，不是已经完成的工作**。[E01–E03]

## 1. 已闭合与待闭合

| 项目 | 截至本报时点的真实状态 | 含义与边界 |
| --- | --- | --- |
| 源码与原历史 bundle 发布 | 已完成，固定公开提交 51749cfc93452ba7c235543c1529568a75368f2d；实际读回凭据已关闭源码发布门 | 原 C1/C2/C3 身份由真实 bundle 恢复，远端 snapshot commit 与它们不同；源码发布不等于科学完成。[E10] |
| 论文 comments 与五优先级矩阵 | 已发布至 522b344da7635711e7cee617243061db44e212d5；6 文件、90,840 B 已实际 HTTP 字节读回 | 原理论正文与科学判定规则保持；本报追加操作状态。[E11] |
| 原模块真实 import closure | 2026-10-30T02:17:18.526531+00:00 的真实导入及 loaded-source closure 已通过 | 这是历史导入凭据，不替代当前资源准入或科学任务资格。[E09] |
| 授权缓存清理及对账 | 4,758 次 unlink 返回成功；随后缓存全量重现 | 操作已完成，持续空间回收未获证明。[E04] |
| 自有文件驻留页排查 | runtime/assets 大小文件的只读 mincore 测量已完成 | 仅建立限定文件与时点的容量证据，不归因共享内存。[E05–E07] |
| 原正式 launcher 启动 | 已真实启动，并记录测量父进程与原 supervisor 身份 | 外层启动不代表内部资源门已经通过。[E02–E03] |
| 当前资源窗口 | 未通过；连续合格样本数 0/3 | RAM 不达标；磁盘本次单点达标不等于整个联合窗口通过。[E01] |
| 原 14 jobs 与 17 次真实阶段 ACK | 0/14，0/17 | 尚无本轮科学结果可据此判定五个问题。[E01] |
| 全量分析、恢复与 postseal | 待 26 个 analysis 输入 seals、30 个 finalizer seals、literal restore 及已登记补充分析 | 这些是后续真实完成门，不能用准备文件替代。 |
| 最终成本与终端持久化 | 最终 outer wait4 和 root terminal closure 待真实结束 | 内层 science/driver/archive 成本不能与已包含它们的 inclusive CPU 再次相加。 |

**当前阻塞是资源准入，不能写成参数场或 Hepta 的阴性结果，也不能声称全部 blocker 已关闭。** 原历史额外工作和 CPU 上界未知仍保留；本报没有把旧 episode 的工作归零。

## 2. 当前资源读数与不变阈值

| 量 | 本次实际读数 | 原阈值 / 解释 |
| --- | ---: | --- |
| effective available RAM | 707,678,208 B | 至少 1,879,048,192 B；本次短缺 1,171,369,984 B |
| 输出盘 available bytes | 6,346,141,696 B | 至少 2,415,919,104 B；本次单点通过 |
| 连续资源合格样本 | 0 | 要求 3 次，间隔 10 秒 |
| 共享 OOM / OOM-kill 计数 | 4 / 4 | 共享计数，不归因某个进程 |

以上来自 E01 对应 STATUS.capacity 样本，RAM **1,879,048,192 B**、disk **2,415,919,104 B** 的门保持不变。仍由原 supervisor 检查；没有以降低阈值、缩减样本、改变 guard 或另起实验控制器来获得通过。

## 3. 清理发生了，但没有证明持续回收

授权的清理中，**4,758 个已列名文件成功 unlink，总逻辑字节 103,154,374 B**。主机侧在清理结束后 **42.38121895 秒** 的读回又看到相同完整人口：4,758 个文件、103,154,374 B；另一观察面在约 40 秒也看到完整人口。故“unlink 已执行”与“缓存持续不存在”必须分开记录。[E04]

103,154,374 B 是被操作文件的逻辑体积，不是已证明持续释放的 RAM 或磁盘净差。重现机制及写入者没有确定；不能据此虚构自动重编译、回滚或进程归因。已完成对账，没有重复删除循环，也没有扩大到源码、模型、数据或既有证据。

## 4. 已测自有文件页不足以解释 RAM 差额

两次只读测量覆盖 runtime 与 assets 的全部已盘点非空普通文件逻辑字节 **1,446,678,132 B**：大文件 **1,085,593,451 B**，小文件 **361,084,681 B**。大文件测量时点为 2026-10-30T04:09:01.735016+00:00，小文件为 2026-10-30T04:11:33.010163+00:00；合计观察到 **12,288 B（12 KiB）驻留文件页**。方法是 mmap(PROT_NONE, MAP_PRIVATE) + mincore，没有读取/解码模型或数据内容，没有 fadvise、全局 cache drop 或 cgroup 改动。[E05–E06]

同次范围盘点给出其余自有工作区文件的保守文件页上界 **57,715,232 B**，远小于本报 RAM 缺口 **1,171,369,984 B**。这说明已覆盖自有文件页不能解释这一数量级的准入差额；它没有识别共享全局缓存的所有者，也没有证明这些页均可回收。[E07]

mincore、文件盘点和当前 STATUS 是不同时间的元数据观察，不是一次原子的全局内存测量；驻留情况可以变化，后续新增文件也不受旧盘点的永久约束。不能把“文件逻辑体积较大”直接当作“删除就可释放同量 RAM”。

## 5. 已有 CI 不是已验证的本研究替代入口

已有 runner/CI 路径的只读评估没有核验到可以直接接收本次冻结配置、取得私有 pinned 资产并维持 17 次真实阶段 ACK 的 fullstudy 入口。历史 hosted CI 的成功证明曾有独立 CI 执行能力；已检查的具体接口分别固定执行 unittest、Rust 工程任务、另一套 NDU 协议，或 main-only 的 10 分钟只读 availability probe。[E08]

因此不把另一个协议的训练、历史 runner label 或探针当作本研究的完成证据。原 launcher 已启动后，继续维持其唯一执行权；没有启动替代科学控制器。该评估是限定范围的“尚无已验证现成入口”，不是证明任何其他机器都不可能运行。

## 6. 五优先级与核心 comments

| 优先级 | 要回答的问题 | 最有判别力的既定结果 | 当前结论 |
| --- | --- | --- | --- |
| P1 | 合法候选是否产生不同 guard 后状态 | 合法后继差、首次分歧、fallback、真实成本；完整 A inactive 谓词 | 待科学数据 |
| P2 | 价值标签是否与 baseline、clock、guard、budget 对齐 | 完整分支状态上的 advantage 与误差/可得增益比较 | 待科学数据 |
| P3 | field 遗漏何种决策信息 | 同动作空间的 field/full-state/history 比较及动作排序 witness | 待科学数据 |
| P4 | 参数场控制是否有独立净收益 | ordinary/fixed_taper 对照、独立任务、retention、总成本 | 待科学数据 |
| P5 | Hepta 是否有额外适配性 | 原 2×2 simple effects 与 interaction；再判断是否扩展 neuron 或 modality | 待科学数据 |

理论评论的核心判断保持为：**参数场理论为 Hepta 提供可检验的控制研究框架，尚不能据此证明具体神经元实现正确或优越。**

- **先定义完整状态与合法控制。** optimizer 辅助状态、clock、guard/rollback、预算及策略可观察历史决定比较的含义。候选动作不同不保证 guard 后合法后继不同；必须看实际状态差、首次分歧和 fallback。
- **压缩动力学、遗漏信息、动作限制和估计误差是不同问题。** field、完整 current-state 与同信息 history 必须在相同动作空间比较。12 维 field 的大小、拟合 R² 或单个 witness 都不能单独证明充分性或一般可达分布上的信息损失。
- **优势标签与误差必须匹配实际部署。** 以同 baseline tail、guard、clock、剩余预算与 paired tape 定义 advantage，再比较 gated 选择误差和可得增益。依赖 calibration parents 不能提升为独立样本或统一误差证书。
- **utility 与资源账分开。** 当前 terminal utility label 不自动包含训练 CPU 或论文干预 effort；独立任务、retention、强 ordinary、轻量 fixed_taper 和完整成本一起决定本实现是否有净收益。
- **Hepta 的额外适配性需要原 2×2 比较。** 同时报告 simple effects 和 interaction；正 interaction 可能仅是较少伤害。当前 ridge heads 不等同于已求解论文 Riccati/HJB/FBSDE，当前架构增量也不代表整个 Hepta neuron 家族或 LLM 尺度结论。

这些是已公开评论的条件和待检验问题。A 的完整 inactive 谓词、负效应、零效应、retention 不通过等都可以成为忠实的科学结果；当前资源阻塞尚不提供这些结果。

## 7. 已发布材料与证据身份

- [已公开理论评论及判定矩阵（固定 commit 522b344…）](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/522b344da7635711e7cee617243061db44e212d5/reports/parameter_field_r45_hepta_review_20261030)
- [已核验源码发布、真实 bundle 与恢复说明（固定 commit 51749cf…）](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/51749cfc93452ba7c235543c1529568a75368f2d/operational/parameter_field_recovery04/publication)
- [R45 论文固定来源](https://github.com/TrillionniumFoundation/ICLR-2027/tree/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45)：访问仍受论文仓库权限约束；本报没有复制 TeX 原文件。
- [同一状态的机器可读摘要](CONTINUATION_STATUS_20261030.json)

下表是本地实际凭据的精确描述符，供受控执行证据核对；仅发布身份不等于这些原始文件在该公开目录可下载。私有 SNAPSHOT 内容、模型/数据文件、远端存储对象身份及服务凭证不在本次公开清单中。

| ID | 工作区相对证据路径 | Bytes | SHA256 |
| --- | --- | ---: | --- |
| E01 | publication_bridge_20261030/CONTINUATION_STATUS_PUBLICATION/SNAPSHOT.json | 762 | 37cde87abba588458715f3a0cabbb95137f18efc2b5bc715caa35ba2fbe46c70 |
| E02 | fullstudy_execution04_ops/wait4_launcher/START.json | 989 | a05cc2e0fbf57534b23417d322899463b73e60229f7b87959d807e60856c368e |
| E03 | fullstudy_execution04_ops/detached_launcher/RELEASED.json | 1,147 | 540e65a913b3356f0efea7c1f166b12163acdd86ac374f2edd71c5dda788542c |
| E04 | continuation_recovery_20261030/current_readiness_0253/capacity_reconcile/FINAL_RECONCILIATION.json | 4,754 | add9f840199ce145ec9664221ae6a59b7ee9926039bfa963eb06bb396b88fd24 |
| E05 | continuation_recovery_20261030/current_readiness_0253/file_cache_residency_20261030T040749/RESIDENCY.json | 11,914 | 5cdcba58648e80e1c787b784662d56383bed8458ed7a206569b619f8dabe1d7a |
| E06 | continuation_recovery_20261030/current_readiness_0253/small_file_cache_residency_20261030T041129/RESIDENCY.json | 4,503 | e0e27962cf66570bce6de75602491620d241f00c9077fbfd73a52270b71e0d0c |
| E07 | continuation_recovery_20261030/current_readiness_0253/WORKSPACE_OWNED_CACHE_BOUND.json | 1,705 | 4b10507996e4a11b3a3f52d66b25b25a368d6eb09c6237262dc62fc0f474c690 |
| E08 | continuation_recovery_20261030/current_readiness_0253/ALT_CAPACITY_ASSESSMENT.json | 15,436 | 18e3187bd1d7695c30a3d18933f507830f25e858cdaf868e159311fe98671a69 |
| E09 | fullstudy_execution04_ops/prelaunch/import_gate/IMPORT_CLOSURE.json | 2,228 | 477b5719c790c05b5162199e76c2de2c1711852226ae7fdb2a68b2a5df63b00d |
| E10 | fullstudy_execution04_ops/prelaunch/SOURCE_PUBLICATION_VERIFIED.json | 1,937 | 5acf21093bf567a8c5dbddd0a48b0977ac8cf845dd6e6aff91b09700796bad57 |
| E11 | publication_bridge_20261030/report_remote_readback_522b344da763/REMOTE_BYTES_VERIFIED.json | 11,123 | 07f2c3295b39819dc1b42435081fe81e63d3531b9767dd23b9fe21f661610e56 |
| E12 | fullstudy_execution04_ops/registrations/initial/PIPELINE_CONFIG.json | 5,259 | c1a541cd8fca9e43c710cfd5ccf1cb76793a28712d66eed65a238f158de0e57e |
