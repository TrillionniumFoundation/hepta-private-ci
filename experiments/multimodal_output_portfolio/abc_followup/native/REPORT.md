# ABC follow-up：真实未来预测、连续原生状态与同 head 提案链

## 结论与证据范围

本轮完成了一个真正**在未来生成前提交预测**的 478→64→33 head，并在新冻结的 1,432 个来源对上验证。未来状态预测 MSE 从 persistence 的 **0.207088 降到 0.119969**；按来源对聚类、两动作合并的改进为 **0.087119，名义 95% 区间 [0.082265, 0.091874]**。ID-only 改进也为正，但仅 **0.004985 [0.003592, 0.006508]**；总体效果主要来自完整模态缺失情形，不能把混合平均数读成一般 ID 任务的大幅改善。[VERIFICATION_RESULTS.json](VERIFICATION_RESULTS.json)

原来的“最大实际状态残差→confidence”契约仍然失败：验证 ID ECE 为 **0.262781**，超过原上限 0.03。Rust 对 2,864 个预测逐值核对后真实调用原 `NeuronRuntime::bootstrap`，返回 **`InvalidCalibration`，0 个 tick**。这个失败没有通过残差缩放、调阈值或覆盖旧结果来消除。[RESIDUAL_NATIVE_RESULTS.json](RESIDUAL_NATIVE_RESULTS.json)

在验证来源打开前单独登记的“未来语义正确率概率”契约通过了预定 point-ECE、FAR、非空洞接纳率及 OOD 来源对上界四个 gate。其真实 future head 随后完成 **1,600 个 tick、13 个 journal 段、12 次 rollover、同一个 context 的三次恢复**；在 **sequence 802** 的实际 admitted ID anchor 上完成该 head 自己的 **36 次 owner resolution、两个 typed parameter proposal、pending registry/witness 持久化与恢复**，再从同 anchor 继续到 1,600。完整链使用同一份未来 head 权重，没有拼接旧 head 的提案。[PROSPECTIVE_VERIFICATION_RESULTS.json](PROSPECTIVE_VERIFICATION_RESULTS.json)、[FUTURE_NATIVE_RESULTS.json](FUTURE_NATIVE_RESULTS.json)、[FUTURE_PROPOSAL_RESULTS.json](FUTURE_PROPOSAL_RESULTS.json)

这闭合了研究切片中的“未来 predictor→原生 admitted tick→连续 acknowledged journal→同 head pending proposal/recovery”机制。**没有获得生产更新权限、没有应用模型更新，也没有证明提案带来独立收益。** 两个旧 head 预冻结提案在本次独立来源上的 raw-Brier 改善均略负且区间跨零；新 head 的两个提案只做了已观察历史来源上的功能评价。真正产品 admission 的第一实际 owner 拒绝仍是 **`OwnerEvidence(Unavailable)`**。[OLD_CANDIDATE_VERIFICATION_RESULTS.json](OLD_CANDIDATE_VERIFICATION_RESULTS.json)、[FUTURE_CANDIDATE_DEVELOPMENT_RESULTS.json](FUTURE_CANDIDATE_DEVELOPMENT_RESULTS.json)

本报告只报告 native 这一条实验线，不把上述预测误差、correctness head 参数变化称为多模态生成效用改善、Merton 问题解、全局 NDU 最优或无条件稳定性证明。

## 1. 前瞻冻结、来源与实际预测对象

主 predictor/protocol 在 commit [`9f885429cab68f1150a5155ef78b0eb9a68dd7e3`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/9f885429cab68f1150a5155ef78b0eb9a68dd7e3) 发布后才读取 calibration。calibrator、补充契约、动力学配置、live hook、旧候选比较及其全部源码又在验证前发布；完整最后冻结点为 [`1166eccb6e72ced755bcf1712349200a5a0f1a9c`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/1166eccb6e72ced755bcf1712349200a5a0f1a9c)，tree `fc8e8d5ef3cac2ee08135ad200c57ec839f40ab4`。43 个文件的逐项 SHA 见 [FREEZE_READY_MANIFEST.json](FREEZE_READY_MANIFEST.json)。验证后未修改其中任何文件。

| 材料 | 固定身份 / 使用范围 |
| --- | --- |
| 原生 core | `9595221c21f1fe0775295a9c8756a1ba4d69ea49`，428 个原源文件校验，22-crate 隔离研究 build |
| 主协议 | `b94df6feac7cace3beb8f1f9f95b7a299f60dbb9b86c4fe414df5925c8c5416b` |
| predictor weights | `95d6fade17c609457cb6b978d6580a37fb3bdd02aafa125d964c60c48dd4cc0c` |
| predictor freeze | `23475f242980f006329e4d6a200e8f0e553b3ddefd40a1221095a5264de96f2a` |
| calibrator freeze | `42e90963a5d5f7ccccb78606572011ac238abffabd40ebc78a698b0364a0b454` |
| future-correctness supplement | `e0b6687bf9e4f79c1085605591911a722745915f25047a128d034519d1283b1b` |
| verification arrays | `e71599c687be4a1129aee1afe0fdb6023bc50f026b676ffbabee573731704c96` |
| frozen continuous binary | `b30b813104776c6af619f3004cc8475e9d4f4916650fae2e1afcfed8b79480b6` |

来源分配与其他实验线共同登记在 [SOURCE_ALLOCATION.json](../control/SOURCE_ALLOCATION.json)，SHA `85ba9a409a31a6ff6c6b4df5f6f06867d14be9442d3434c0c143e0cdb9a4e76d`。元数据审计检查了全部 16 个历史大型 metadata 中的个体 MNIST ID，预留 test 尾部与已执行历史交集为零；不同分配区间的个体 source ID 和 pixel SHA 也不相交。

| Phase | 来源对 | 实际未来分支 | 角色 |
| --- | ---: | ---: | --- |
| 历史 fit | 4,000 | 8,000 | train；3,000 ID、1,000 complete absence |
| 历史 selection | 2,000 | 4,000 | train；1,000 ID、1,000 complete absence |
| 新 calibration | 800 | 1,600 | test pairs [768,1568)，400 ID、400 absence |
| 新 verification | 1,432 | 2,864 | test pairs [1568,3000)，632 ID、800 absence |

每个来源对含两张不同的原始图像；每对执行 `refine_text` 和 `couple` 两个未来动作。统计聚类单元始终是来源对，两个动作、native 重放、不同 proposal 均没有增加独立 N。其他线使用的 test [512,768) 未进入本 native 训练、校准或验证。

每次实际 prefix 先完成初始化中的两个 shared 更新，再执行真实 `refine_image`。输入 478 维只取这个 prefix 的公开状态、Encoder 条件、实际草稿图文及下一动作 flag，不含 target、后验质量观察、未来 RNG 或未来输出。目标 32 维为真实未来媒体的 16 个视觉编码坐标及 16 个有界 token-embedding 坐标；第 33 个输出 logit 预测未来联合语义正确率。

预测器是 478→64 tanh→33。状态预测为当前实际输出状态加有界残差；依据已有动作语义，`refine_text` 的视觉残差固定为零。历史 fit 上执行 2,000 个 Adam step；每 100 step 用 historical selection 的 MSE+0.05BCE 选择，实际选中 step 1,700。8-bin calibration 的切点仅由历史 selection 冻结，概率只用新 calibration 计算；验证后没有 refit、重选或重新校准。

采集器先把**两个动作的输入、状态预测及 raw probability 均 fsync**，然后才执行任一真实未来 transition。独立事后审计逐一重开了全部 90 个 commit 文件、2,864 个 PNG/UTF-8 输出：输入/过去状态/预测/概率与冻结模型逐值相同，caption 与实际 tokens 相同，媒体 hash 相同，从 PNG/text 重编码的全部未来状态坐标 Q24 精确相同。每个来源的两个 commitment 均早于第一未来 transition；最小记录时间差约 3.062 ms。这个审计支持本地冻结代码的执行顺序，不冒称外部签署的可信时间服务。[FUTURE_EVIDENCE_AUDIT.json](FUTURE_EVIDENCE_AUDIT.json)、[evidence_audit.py](evidence_audit.py)

## 2. 新来源上的未来状态预测

| 来源 / 动作 | Forecast MSE | Persistence MSE | 改进 | 来源对聚类 95% 区间 |
| --- | ---: | ---: | ---: | --- |
| 全部，预注册主指标 | 0.119969 | 0.207088 | 0.087119 | [0.082265, 0.091874] |
| ID | 0.027139 | 0.032124 | 0.004985 | [0.003592, 0.006508] |
| 完整缺失 | 0.193304 | 0.345309 | 0.152005 | [0.146916, 0.157259] |
| `refine_text` | 0.090164 | 0.158706 | 0.068541 | [0.063615, 0.073628] |
| `couple` | 0.149774 | 0.255470 | 0.105697 | [0.099561, 0.111811] |

只有第一行是预注册主比较，其余是描述性分解，均来自相同 1,432 个来源对，没有当作新的独立验证。主结果相对 MSE 下降约 42.07%；ID 相对下降约 15.52%，绝对差更小。`refine_text` 的视觉误差双方都是零，来自该动作保持实际图像的契约，不是新学到的视觉预测能力。

混合来源上的视觉 MSE 为 0.056840 vs 0.091925，文本状态 MSE 为 0.183098 vs 0.322251。ID-only 的文本 MSE 为 0.023161 vs 0.025587。它们是冻结 latent 描述的误差，不能直接等同于原始文本准确率、图像保真度或用户任务收益。

calibration 预定的“每个来源、两个动作、全部坐标的最大绝对误差”90% radius，在新 ID 上覆盖 **571/632=90.35%**，完整缺失上覆盖 **717/800=89.63%**。对应 radius 为 1.07009、1.43546，ID 最大误差的 P50/P95/P99 为 0.56587/1.29194/1.61929，absence 为 1.20081/1.48601/1.59232。来源 MSE 的经验 CVaR90 分别为 0.108779、0.265996。这些结果描述已冻结混合来源的实测覆盖与尾部；不提供任意新任务、任意条件或非交换分布的普遍 conformal 保证。

## 3. 两个 native confidence 契约，两个不同结论

原 residual 契约使用 `drive=[1, actual_future_state]`、`prediction=[p, committed_forecast]`，保持原始 Q24 残差量纲。原 kernel 最大残差给出 confidence，等价于概率和状态误差共同约束的分数。这个分数不是天然校准的语义正确率概率：calibration ID ECE 0.251799，verification ID ECE 0.262781；即使未来状态 MSE 显著改善，原 `.03` ECE gate 仍失败。

supplement 在看过 calibration、尚未打开 verification 时明确注册另一种契约：`drive=[1, observed_state32]`，`prediction=[frozen_future_p, observed_state32]`。后 32 个坐标严格相消，只承担原接口的 confidence carrier，**复制的 observed 坐标没有未来预测含义**。真正的 32 维未来预测仍是前一节独立预提交并验证的预测器；native 使用的真实未来信息是提前预测的语义正确率 `p`。这个 adapter 没有改变权重、bin、真实状态误差或旧契约失败。

| 量 | Calibration | Verification | 原登记验收 |
| --- | ---: | ---: | --- |
| future correctness native ECE，ID | 0.002421 | 0.026089 | 两角色最大 point ECE ≤0.03，通过 |
| ECE，全部 | 0.001834 | 0.011862 | 同上 |
| ID 概率 gate 接纳率 | 526/800=65.75% | 826/1,264=65.35% | 两角色均 ≥25%，通过 |
| OOD 被接纳来源对 | 0/400 | 0/800 | point FAR≤0.004999，通过 |
| OOD FAR 单侧名义 95% 上界 | 0.007461 | 0.003738 | 预先只要求 verification 上界≤0.004999，通过 |
| 冻结概率 Brier，全部 | 0.068369 | 0.056494 | 描述性结果 |

verification 的 ID ECE 来源 bootstrap 区间为 **[0.011978, 0.049021]**，上端高于 0.03。因此这里只能称为预注册 **point-ECE qualification**；不能称为“以 95% 置信度 ECE≤0.03”。OOD 上界按每个来源的任一动作误接纳计数，使用 800 个来源对的名义二项上界，不把 1,600 个分支当独立样本；它只覆盖本轮构造的 complete-absence OOD。

## 4. 持续流失败的成因与单独登记的动力学配置

原来分离的 singleton context 隐藏了长期阈值漂移。本轮先保留全部真实失败，再定位机制：第一次 continuous driver 漏掉原测量器每 tick 的 `start_window`，把旧高水位带入后续 tick，测得 5,012,756 B 并全部弃权。恢复原测量生命周期后，瞬态分配降到 5,845 B，但原 ±Q 阈值配置仍仅 **40/800 ID tick admitted**。

对原 kernel 的逐步重放与真实记录的全部 1,600 个 eligibility digest/activity 精确吻合。第 **65** tick 首次出现 `projection_count>8`；第 **66** 个 ID tick 的 8 次 threshold clamp 加 1 次 eligibility L1 projection 构成真实拒绝。最后有 15 个 threshold clamp；全程 1,527 个 tick 超过 projection gate。没有删除计数、抬高 gate、周期 reset 或用短前缀代替完整流。[DYNAMICS_RESULTS.json](DYNAMICS_RESULTS.json)

原 dynamics 的 `h_t=0.5 h_(t-1)+drive_t`，homeostasis 按原 eta=Q/8 调整阈值。旧 head 由无噪声有界 Encoder 条件和两个 0.25tanh shared 更新得到解析 drive 界 **B=1.5Q**；新 emitted-state head 为 **B=Q**。故 recurrent state 有界于 2B。旧 ±Q 阈值不足以为这些驱动保留竞争余量；新 width33 若仍用 target=Q/8，期望总活动 4.125 还超过 top-k=4。

单独登记的新 profile 保持所有 confidence/ECE/FAR/resource/projection 验收 gate、eta 和长期连续执行不变，只把 dynamics 参数设为：

| Profile | 解析 drive 界 | 阈值范围 | target activity |
| --- | --- | --- | --- |
| 旧 width32 current head | B=1.5Q | ±(2B+Q)=±4Q | floor(4Q/32) |
| 新 width33 future head | B=Q | ±(2B+Q)=±3Q | floor(4Q/33) |

运行时逐值检查声明 drive 界，不能以观测到的 max 替代解析来源。最大 score 上界分别是 7Q 和 5Q，低于原 activation 硬界 8Q。这个推导只证明驱动范围与竞争余量、活动预算可行，**不能证明耦合竞争及 rate EMA 在任意输入的无限时域永不 clamp**。

历史真实 1,600-tick 重放下，新配置 800/800 ID admitted、0/800 OOD，且无 projection gate 超限。另预定 2 个宽度×4 类极端输入×16,384 step，共 131,072 step，始终固定真实契约要求的 drive[0]=Q；所有 case 的 projection count 最大 0 或 1。但负常值和交替输入出现暂时沉默，最多连续 13 个 step，原 activity gate 会正确拒绝。最初过强的“每一步均有活动”测试失败已保留；随后测试只验证实际支持的有限期 projection 事实，未放宽 kernel 接纳条件。

## 5. 新 future head 的完整实际链

原生重放顺序在打开验证前冻结：全部 800 个 absence 来源取 `couple`，与前 400 个 ID 来源的两个动作交替，共 1,600 tick。实际调用的是同一个原 `NeuronRuntime` subject/objective；journal 每段容量 128，无按来源 reset。预定 sequence800、1600 恢复；live proposal 再增加一次同 anchor 恢复。[LIVE_PROPOSAL_PROTOCOL.json](LIVE_PROPOSAL_PROTOCOL.json)

| 检查 | 实际结果 |
| --- | --- |
| Rust/Python Q24 prediction parity | 1,600/1,600 完全一致 |
| Runtime bootstrap | accepted，full supplement `study_qualified=true` 已显式核对 |
| 完整 tick / journal | 1,600 / 13 段；12 次 rollover |
| ID admitted | 486/800=60.75% |
| OOD admitted | 0/800 |
| 额外 dynamics/resource 拒绝 | 0；概率 gate 合格数恰为 486，与实际 admitted 完全相同 |
| 活动 / saturation | 每 tick 4/33；最大 saturation/projection count=1 |
| 恢复 | sequence800、proposal 后 sequence802、sequence1600，三次 |
| 链连续性 | 1,599 个 successor predecessor-anchor 全部吻合 |
| 最终 tick | sequence1600、pair1967，真实 abstain；没有挑一个更好最终点 |

全 verification 中 65.35% 的概率接纳率和 native 子流中的 60.75% 使用不同的预定来源组成，不应被误读为 runtime 丢失了合格信号。逐 tick 审计确认概率合格却被 runtime 拒绝的数量为零，也没有概率不合格却 admitted 的 tick。[FUTURE_TICK_AUDIT.json](FUTURE_TICK_AUDIT.json)

注册的 hook 是“首个 sequence≥800 且实际 admitted 的 ID tick”。sequence800 的 confidence 662879 不合格；801 是 OOD；实际首个是 **sequence802，pair1768，confidence935898**。其 anchor 为 `e5e24dce4b89626b281def5f6c2af89a5df7e05c7d2c732b2a6bd1f98e5a46c4`。driver 先保留真实 context/checkpoint/NDU backup 并释放 runtime owner，才调用 proposal；随后通过原完整段链恢复同一 anchor 和 eligibility 并继续执行。

这个 head 的 typed map 是 `w2[32][0..32]` 的 33 个显式 diagonal eligibility 映射，norm 分母绑定 correctness row 的全部 64 个权重及 bias。它是局部确定性研究规则，不声称梯度、最优学习或整个候选宇宙的完整性。两次 proposal subprocess 从同一个 context 产生字节相同的候选 JSON；36 次 owner resolution、所有 weights digest、实际 neuron anchor 均与本 future head 相同。最终 pending proposal digest 为 `6f3db64070433d860216288870bc66d272b3c6d43853706c50d94e6581440b23`，registry/witness 已恢复，状态仍是 `RequiresIndependentAcceptance`。

原核心 `propose_v2` 持久化只是候选生命周期证据；生产 host admission 拒绝与这一研究 API 的 pending 状态同时真实保留。这里没有把 product admission 失败改成成功，更没有 install/activation。它也不是一条持续 1,600 步的单任务视频/语音生成：是同一 research subject 依次处理预先观察到的任务输出。预测在原 Python 生成前已提交，native 本轮仍是结果重放，不是在线调度尚未生成的动作。

## 6. 真正的提案收益检验与原样保留的不利结果

旧 508→32 当前输出正确率 head 的两个参数提案在未来验证打开前已固定，基于真实旧长链 context 产生。历史 48 来源的 feature 重构预检逐项 Q24 精确一致后，使用新验证每个来源的实际 `refine_text` 输出检验；共 1,432 对、一个未来输出/来源。固定 baseline+两个 candidate，4,000 次配对来源 bootstrap，共享抽样，两个比较各用 97.5% 区间，名义 family 95% Bonferroni。

| 旧 head 候选 | Raw Brier | 相对 baseline 的改善 | Family-adjusted 区间 | 校准 confidence 变化 |
| --- | ---: | ---: | --- | ---: |
| Baseline | 0.05716541420 | — | — | — |
| update `5c44073c…` | 0.05716542779 | −1.3589e−8 | [−9.1346e−8, 5.9761e−8] | 0 行 |
| update `b400ac99…` | 0.05716544138 | −2.7183e−8 | [−1.8270e−7, 1.1952e−7] | 0 行 |

两者均没有正下界，均值方向还略差。没有重选尺度、重新训练或把概率微小变化称为有用收益。这个结果已经关闭“是否已有独立证据支持这两个旧候选有效”的问题：**本轮不支持**；它没有关闭“如何构造有用的 native update”这一算法问题。

新 future head 在 sequence802 产生的两个候选只在**已观察的 historical selection 2,000 来源对 / 4,000 行**上运行功能评价。实际分别修改 26/23 个 correctness 参数，最大 raw probability 变化约 4.77e−5/2.39e−5；Brier 在旧数据上下降约 5.51e−8/2.75e−8，但 frozen calibration bin 零变化、32维状态预测逐值不变。由于来源已用于 predictor 选择，这不是独立收益检验；所有材料明确 `eligible_for_independent_acceptance=false`。没有把它与旧 head 的新来源比较拼接为成功。

## 7. 学习账本与生产 authority 的实际第一边界

空研究账本时，真实 `resolve_agentd_plasticity_admission_v1` 首先返回 `ArtifactBinding`。随后曾实际尝试不完整 singleton 记录，原 append 拒绝 `Semantic(IncompleteCandidateSet)`；改为完整 singleton 又拒绝 `Semantic(MissingAbstainCandidate)`。两次失败均保留，最终记录对象明确改为**已完成 tick 的实际二元信号发布 gate** `{admit_neuron_signal, abstain}`，选择直接来自保留的 `tick.abstain`，给定完整 context 的确定性 propensity=1。

这两个无签名 V1 记录是原 `append_qualification` 的真实追加与恢复，不是任意填写的 nonzero frontier；future hook 的实际 head 为 `503c7bd3bdb2b363172a50a30cf70111e321a3051e1f6a4db4ce8ec2d73e8683`。它们绑定 actual context/anchor/weights/observation，但并不覆盖 head 选择、生成动作或 plasticity 候选空间，也不提供上游 utility 对本次 head 调用的因果 credit。

有了这个真实 research head，产品 API 的实际第一后续结果是 **Dataset 查询的 `OwnerEvidence(Unavailable)`**。未到达的签名、独立 evaluator、部署及应用检查不能报告为“都已失败”。当前研究材料没有既有部署的 root trust、Generator/Observer/Evaluator 签署证据和正式 Dataset owner bundle；用户对研究执行的授权不是这种密码学资格。

[AUTHENTIC_HANDOFF.md](AUTHENTIC_HANDOFF.md) 给出真实 `activate_learning_trust→LedgerWriter::from_durable→append_decision→append_outcome→freeze_dataset` 入口、正式 receipt 类型，以及较新固定仓库 `f8c9419…` 的 Agentd descriptor/CLI。只读审计还发现该固定 loader 显式只展示单 journal 恢复，不能仅凭一个外部 bundle 宣称可导入本轮 13 段真实链；并且它在该处检查 Dataset receipt 自洽和 head，一致性检查本身不能替代正式生产来源。上述产品接口范围必须与本研究链的成功分别处理。

针对单 journal 接口不足，本轮另外交付了 [production_handoff 的 exact-base patch](../production_handoff/README.md)，保留旧 descriptor 并增加显式 `segment_chain`，通过原 journal API 恢复完整链、核对最终独立 anchor，并把所有段纳入原 owner 路径分离。新增 helper/probe 已在本轮真实 future head 的 13 段副本上恢复到 sequence1,600，最终 anchor/33维eligibility 精确一致；旧单文件和19项拒绝检查也通过，共21项。原13个文件SHA不变，无新增tick或统计N。[CHAIN_RECOVERY_VALIDATION.json](../production_handoff/CHAIN_RECOVERY_VALIDATION.json)

这个交付关闭了“只有静态指出缺少完整链接口”的实现缺口。实际编译验证的是 helper/probe 与原 `9595221…` journal rlib，**不是较新整个 Agentd crate**；完整目标集成、合入和部署尚未执行。它也没有获得 Dataset owner、角色签名或独立候选接受，不能把恢复测试成功写成生产 qualification。

## 8. 实际资源、总工作成本与检查范围

下面全是原 Linux shared host 上的实际测量，没有用模型估算替代时钟。exact-PID wrapper 在启动前登记 entrypoint/wrapper SHA，直接 `wait4(child.pid)`，日志 fsync；完整 receipt 和不利执行在 [PROCESS_COSTS.json](PROCESS_COSTS.json)。

| 阶段 | Child wall 秒 | Child CPU 秒 | Peak RSS bytes |
| --- | ---: | ---: | ---: |
| 历史未来数据完整采集 | 31.129619 | 30.839198 | 441,593,856 |
| Predictor fit、选择、落盘 | 5.244436 | 5.229594 | 434,118,656 |
| 新 calibration 采集 | 6.488074 | 6.434088 | 372,744,192 |
| Calibration 与冻结 | 1.808940 | 1.798330 | 251,412,480 |
| 新 verification 采集 | 9.617508 | 9.518880 | 372,498,432 |
| 主验证分析 | 3.439559 | 3.424663 | 273,219,584 |
| Supplement 验证分析 | 4.107185 | 4.082775 | 310,235,136 |
| 旧提案独立来源检验 | 2.600492 | 2.595981 | 299,438,080 |
| Residual packet 准备 | 3.931709 | 3.903956 | 360,534,016 |
| Future packet 准备 | 3.616760 | 3.587902 | 345,055,232 |
| Residual 原生实际拒绝 | 0.236164 | 0.233576 | 42,397,696 |
| Future 全流含 live hook | 7.523864 | 4.078486 | 336,805,888 |
| 全部 commit/media 复核 | 3.507629 | 3.502865 | 287,043,584 |

这些主实验阶段 wall 相加为 83.251939 秒，是各阶段工作时间之和；有些分析并行，因此不是一次端到端请求的 elapsed latency。加上保留 receipt 的历史诊断/失败/old-live smoke，所列阶段总和为 108.338313 秒。它们不含此前复用的 generator/observer 训练、Rust 工具安装、编译和未单独计时的调试；这些成本不能被当成零或宣称已包含在“训练总成本”。

随后新增的 product chain helper 编译及真实副本 probe 另实测 2.588157 秒，固定单 CPU affinity，单独保存在其 [validation receipt](../production_handoff/CHAIN_RECOVERY_VALIDATION.json)。这项单独编译计时没有补足此前未测的全部构建/调试成本。

Future 原生全流的逐 tick native execution P50/P95/P99 为 **318/569/2,041 μs**，outer tick 为 **589/1,061/2,697 μs**。native 最大 3,249 μs；outer 最大 77,215 μs。最大模型瞬态分配 **5,831 B**、checkpoint **1,568 B**，实测 resident heap **285,598 B**。原 profile 的真正门槛是 p95≤3,000μs、p99≤8,000μs、transient≤512KiB、checkpoint≤1MiB；没有单独 resident 256KiB ceiling。原资源验收通过，但这里只是在当前 shared host 的有限 pilot。

Live proposal/evaluation/recovery hook 额外暂停 **2.391017 秒**，已包含在 native 整段 wall；它不在逐 tick latency 分位数内。完整 batch 7.523864 秒包括 parity、journal、全部 tick、hook 子进程和持久化，不能仅用 318μs 宣称完整在线控制成本。嵌套 evaluator receipt 保留在 cost index，但没有再加到父流程 wall 上。

Focused `just test` 的最终回执是 6/6 通过，范围是新 head parity、配置/有限 stress 与 driver 所需模块；没有跑 CI 或全仓测试。原 profile 的长期拒绝、两个错误 ledger 记录尝试、首次 allocator lifecycle 错误、过强活动断言失败和缺失 `/usr/bin/time` 的启动失败均原样保留。最终格式化由协调 agent 单独处理，执行身份以预先发布的 source/binary SHA 为准，不把格式化后文本冒称原执行字节。

## 9. 下一步应该解决什么

原始 residual-confidence 契约尚未合格；future-state MSE 的改善不能自动把最大 latent 残差变为任务成功概率。一个可检验的后续是保持原状态误差独立审计，在新来源上学习和校准条件任务价值/失败风险，再验证它是否改变真实生成动作选择并覆盖全部控制成本。当前 supplement 已证明真实未来概率可被接入，但没有证明其动作选择价值。

局部 eligibility×utility 的两个固定参数候选在独立来源上没有收益证据。应改进具有任务含义、受实际 parameter geometry 约束的候选更新规则，并在**新的**冻结来源上检验；不能继续使用已打开的本轮 verification 来重选或宣传独立进步。

持续 journal 和同 head pending proposal 已在研究切片真实贯通，完整段链 helper/目标补丁也已交付并通过真实链恢复验证。正式产品接入仍需要目标完整 Agentd 集成与部署验证、实际 Dataset owner/角色签署来源、独立 candidate acceptance 和真实 applied-update 后的评估。详细可调用路径与当前实际第一拒绝已写明；这些事实约束不能通过更改文字、放宽 gate、填入任意 digest 或自签测试身份“闭合”。
