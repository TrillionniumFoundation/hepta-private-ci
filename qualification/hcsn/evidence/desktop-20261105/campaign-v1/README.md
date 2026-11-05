# CUDA campaign v1：启动后等待运行时的证据快照

本批证据记录了候选源码发布、部署包验证和 durable controller 的实际启动。
在独立读取的 **2026-11-05 17:10:56 UTC** progress 中，controller 状态为
`waiting_for_pinned_runtime`，`stages=[]`，完整 CUDA 训练完成数仍是 **0/170**。
本批是过程快照，不是最终资格结果。完整机器可读状态见 [STATUS.json](STATUS.json)。

## 已发生的变化

| 项目 | 本批记录 |
| --- | --- |
| 候选源码 | 已发布 `fe1def4a8a6655a361726f3ca275d9f5688dd394`，原 baseline 是 `28a61d14ea7d4c3b3c515ab57b29c98de22e5673`；本 packet 不修改 source 分支。 |
| 独立 evidence 分支 | 本快照基于 `716b7d6354bead8517527a25d66871e9ddaf4056`，追加到独立分支 `research/hcsn-desktop-evidence-20261105`；source 分支保持原提交。 |
| 部署包 | ZIP 已上传；第二次 staging 已核验 39 个包内文件、10 个任务依赖、23 个 baseline Python 文件及26个 candidate Python 文件。 |
| 第一次 staging | 因读取 manifest 时误判 ZIP 一级目录前缀而退出1；发生在 target 目录创建前，没有模型计算。 |
| 第二次 staging | 只修正对已核验 `campaign-bundle-v1/` 前缀的处理，原 ZIP 字节不变；任务退出0，输出完整且 durable。 |
| Controller | 实际 job `1a1acb0a367-fc05-5667` 已启动；进程记录为 running，已读 progress 为等待固定运行时。 |
| 环境 | 已实际读取新任务根目录的 raw NUMERIC_READY receipt，numeric 环境 ready；17:22:06 UTC整理的安全状态摘录仍记录 Torch/Mamba 下载进行中。numeric ready 与下载进度不代表安装完成或 Torch/CUDA ready。 |
| GitHub CI | 旧 run `42043926869` 已 cancelled；新源码 run `42066954076` 的 job `127383593260` 在17:08:22 UTC的记录中仍 queued，无 runner、无 steps、无通过结论。 |

实际来源分别见 [源码发布 receipt](candidate-source-publication.json)、
[staging receipt](campaign-runtime-staging.json)、
[launch 与两次 staging 历史](campaign-runtime-launch.json)、
[独立读取的 progress](campaign-runtime-progress-initial.json)、
[归属 claim](campaign-runtime-claim.json)、
[CI source transition](ci-source-transition.json) 和
[本地最新 CI 观察](ci-candidate-latest.json)。这些文件保留原字节；未来状态应另存观察。

新增的 [raw numeric READY receipt](numeric-runtime-ready.json) 记录完成时间为
16:57:14 UTC、numeric 包版本和 `model_computation_performed=false`，原始字节 SHA 为
`74bd91aa38786f49beb3f4fc5be7ca9cf278f79d13d1246e02174d696ca9052f`。
[运行时依赖进度观察](runtime-dependency-progress.json) 于17:22:06 UTC整理，两项
状态均为 `download_verified_ranges`；Torch和Mamba的最后payload时间分别为
17:20:36和17:20:33 UTC。该文件只摘录两份独立读取的完整atomic status中的安全字段，
保留原完整文件的SHA和长度，排除process-owner路径、cache清单与command metadata，
不发布原raw status。已核验下载范围与字节进度不是安装、数值、CUDA或训练结果，也不提供ETA。
这份依赖观察与17:10:56的controller快照分别标注时间，不把较晚的下载观察冒充新的模型stage。

## 预算与执行门禁

固定实验仍为 **17模型 × 5种子 × 2任务 = 170 runs**，其中 B 完整预算审计分母为
**20**。每个完成项需400次更新、batch64、length64、hidden64、25,600训练样本和
1,638,400 tokens。数据划分、种子、验证集选择、优化器和原预算保持不变。

Policy 0 仅在原 B 完整形状 CUDA probe 成功后使用。Policy 1 仅在原 B 实际图内存
OOM、固定16项 CPU parity、固定16项 CUDA parity及两个 B 候选完整形状 probe 全部
满足门禁后使用。策略统一应用于全部20个 B 身份，不依据任务质量选择。
当前尚未观察到任何该 campaign 的模型 stage、strict CPU、CUDA probe 或 parity 通过。

Controller 仅持有本任务的独占 campaign lock，并在实验期间持有安装环境共享 lock。
固定运行时最长等待24小时；stage 顺序和原始预算固定，失败不会自动重训或缩减预算。
源码、环境、checkpoint、已执行的部分预算和缺失能耗均需保留。

## 包、审计与本地控制证据

[部署 ZIP](../../../../../tools/hcsn/gated-campaign-v1/hcsn-campaign-bundle-v1.zip) 的 SHA-256 为
`3219e48fb0e8b28a77e1e245ad967f3be5d37948eddac24a64b05dcf17dce2a2`；
manifest 为 `90b3c9f6c6dc206362ee21f3617bd487c5484ca00ad61189195aa832382d3e40`。
ZIP 的39项内容已逐字节核验，固定时间戳和0644权限；两次编码结果相同。
[完整 archive inventory](archive-inventory.json) 记录了路径、长度和各项 SHA。
实际执行应使用完整 ZIP 展开目录；`tools/hcsn/gated-campaign-v1/` 中的单独源码副本用于
审阅，完整 candidate 文件集保留在 ZIP 中。

外部 full-B CUDA 审计固定覆盖全部20身份、全部1,024测试输入和联合网格factor1/2/4。
Factor1沿用batch64并要求实际 GPU trace/预测和原GPU MSE精确重放；factor2/4固定推理
batch8，再按原64样本块累计 MSE。它保留 hidden RMS、最终prediction RMS、相邻网格差、
mass/escape、实际耗时、显存与物理计数器可用性，不增设后验收敛门槛，也不计入170训练。
详见 [完整协议说明](full-b-audit-protocol.md) 和
[原准备 manifest](full-b-audit-package.json)。后者列出的逐子负例 receipt 的 hashes
仍保留在原始准备目录，本批只发布合并控制结果。

[Controller v3 控制](controller-synthetic-controls-v3.json) 为9/9，
[外部审计控制](audit-synthetic-controls-v1.json) 为21/21。
这些是来源、配置、覆盖率、归属和本地锁控制；它们没有执行 Torch 数值计算或 CUDA。
[独立 bundle 审阅](bundle-independent-review-v1.json) 与
[独立 audit 审阅](audit-independent-review-v2.json) 的结论限于各自固定字节的静态与本地验证。
冻结准备文件中描述的“prepared-only”是其生成时的范围，不改写为后来的训练成功。

## 尚未闭合的研究与物理测量

实际 NVML 查询中，直接功率、累计能耗及字段186/185/83/191均返回
**NOT_SUPPORTED**，不是零值。见 [原始 field-value receipt](nvml-field-values.json)。
没有测得任务物理能耗，不用 TDP、推算值或其他计数器代替缺失的 GPU 能耗。

原 smoke B 的不利结果完整保留：训练网格最大质量误差约 `3.5763e-7`，全部加密网格中
最大约 `6.5566e-7`，观测逃逸为0；但 hidden/output RMS变化仍为 **0.1660–0.1977**。
训练网格平均测试 MSE **0.3702743**，高于常数预测器的 **0.36800548**。
这些历史结果支持质量守恒与重放正确，尚不支持分辨率独立或任务优势，也不是完整预算
CUDA结果。原证据地址和指标记录在 STATUS 中。

下一批应追加真实 READY、strict tests、CUDA probes、parity、完整矩阵及 B audit 的
receipt，并保留失败与部分成本。等待或排队状态不能改写为测试通过；CI、完整170-run、
20项完整预算B审计、物理能耗及研究资格仍分别开放。
