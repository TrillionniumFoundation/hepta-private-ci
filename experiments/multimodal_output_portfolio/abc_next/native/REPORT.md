# ABC3 原生接入：真实 correctness head、admitted tick 与同上下文 proposal

## 1. 结果与适用范围

本轮实际完成了一个新的、明确命名的 **resident observed-output correctness head**：使用真实图文生成结果训练与校准，在预留独立来源上一次验证，随后调用原始 Rust `NeuronRuntime` 产生非 abstaining tick、持久化 witness、checkpoint、eligibility，并在相同 objective/subject 上调用原始 dynamic resolver、参数候选生成器与 proposal registry。没有修改原生校准门槛，也没有把评分器准确率直接填入 native calibration。

**完成的是研究 resident profile 的真实执行链。生产 admission 仍然拒绝。** 原始 Agentd product admission 已被实际调用，返回 `ArtifactBinding`；实际 learning ledger 为 0 条记录、head 为零。没有用本地自签 DatasetSnapshot、资格常数或伪造 frontier 绕过这个拒绝。落盘的研究 proposal 状态是 `RequiresIndependentAcceptance`，权限为 `DENY_ALL`，没有应用参数更新。

| 本轮项目 | 实际结果 | 可以支持的结论 |
| --- | --- | --- |
| 新 head 独立验证 | 800 ID + 800 不重叠 complete-absence OOD；ID ECE 0.024466055；OOD 接受 0/800 | 新观察输出正确率 head 的预声明点估计 gate 通过 |
| 实际原生 tick | 1,600 次；ID 非 abstaining 800/800；OOD 非 abstaining 0/800 | 实际 native port、sparse runtime 与校准执行，而非 digest stub |
| durable acknowledgement / recovery | 1,600/1,600 anchor 与 eligibility 恢复一致 | 新 profile 有真实非零 journal/witness 链 |
| 同上下文 dynamic resolver | 35 次原始 resolver 调用 | 原先缺 acknowledged checkpoint 的局部前置缺口得到解决 |
| 参数候选 | no-change + 2 个非零候选，各改 4 个真实 `w2` 参数 | 实际 eligibility/modulator 参数映射与生成器执行 |
| 候选效果 | 两个候选的 development raw Brier 均略差 | 没有学习改进或可应用更新证据 |
| 研究 proposal | 原始 `propose_v2`、registry append、witness 和 reopen 成功 | authority-free 提案持久化链完成 |
| product admission | `ArtifactBinding`，实际 ledger 为空 | 真实下一层 blocker 已定位，生产资格未获得 |

旧 v6 persistence predictor 的校准失败仍然成立。新 head 预测的是**已经观察到的输出是否正确**，其 residual 是显式 confidence 编码；本轮没有修复旧 latent-dynamics predictor，没有执行 Agentd/fleet daemon、intuition、生产主机认证、声音/视频 native backend 或生成器反向传播 owner。

主要结构化依据是 [RESULTS.json](RESULTS.json)，本地大证据的大小与 SHA 见 [EVIDENCE_INDEX.json](EVIDENCE_INDEX.json)。该索引不包含媒体、特征矩阵、模型参数、二进制或原始 journals 的正文。原始代码固定为仓库 ref `9595221c21f1fe0775295a9c8756a1ba4d69ea49`；428 个原文件的身份见 [UPSTREAM_SOURCE_PINS.json](UPSTREAM_SOURCE_PINS.json)。本次实际资格及执行代码已原字节发布到 GitHub commit [`9d48cb518fcd457f58eb23d068e6b1bf934b2dc2`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/9d48cb518fcd457f58eb23d068e6b1bf934b2dc2)，tree 为 `56f020dbb43bd745865603a69b47bb711a1918f1`，与本地执行源提交 tree 完全相同。九个文件的 SHA 见 [EXECUTED_SOURCE_PINS.json](EXECUTED_SOURCE_PINS.json)，格式化后的代码不能冒充这些原字节。

## 2. 先冻结、再校准、再独立验证

[PROTOCOL.json](PROTOCOL.json) 的 SHA-256 是 `1ccf9287e4246569678a1ff65b8d28dbb7d9307a0869cfc7b7a81421ad8626b3`。以下为实际记录的 UTC 时间；访问记录同时绑定前置 freeze 的 SHA，而不只记录 wall clock。

| 事件 | UTC，2026-10-25 | 绑定对象 |
| --- | --- | --- |
| 冻结协议 | 05:58:58.307044 | 来源角色、ID/OOD 构造、训练算法、校准算法、原生门槛 |
| 冻结 predictor | 06:00:12.288898 | 选定 weights、development cuts、选择历史与实现 |
| 首次打开 calibration | 06:00:45.523256 | predictor freeze `c4ef0339…a838233` |
| 冻结 calibrator | 06:01:06.762794 | 概率、计数、模型、原校准结果 |
| 首次打开 verification | 06:01:19.063095 | calibrator freeze `1740ed66…4985b` |

专用 `neuron_calibration` 与 `neuron_verification` 各 1,600 对、3,200 张原图。每个角色前 800 对按固定次序分成 clean/noise/occlusion/missing_trusted/conflict_untrusted 各 160 对，后 800 对独立用于 complete absence：两块视觉像素与 mask 均为零，两个数字 hint 均为 unknown，keep/swap 命令仍可见。没有把错误输出反向标成 OOD，也没有让同一对同时充当 ID 与 OOD。

独立复核重新核算了 6,400 个媒体文件 SHA、3,200 个特征行 SHA，并核对两个角色的原图来源交集为零。每对只产生一个生成结果与一个 correctness label。Native 重放的 1,600 行、候选 development 计算、bootstrap 和成本复现均增加 **0 个独立资格样本**。

源 manifest SHA 为 `60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058`。角色身份分别为：

- calibration：`ace53c420755d0b21267f0950380b61afd0b082b2ffa06e5c87171b5dc06aa67`；
- verification：`c5d9dfc65c222522beeb3ed77bef71586123f24e963c85f6e3603d6f25279de6`。

这是对单一冻结 generator/observer/来源构造的验证，不是多训练 seed 总体资格，也不是广义 OOD 认证。尤其 complete absence 可由公开 mask/hint 直接识别；其单独校准 bin 是预声明的公开缺失分组，不应宣传为从头学到的通用异常检测能力。

## 3. Predictor 的实际输入、标签与 native 映射

使用已有 seed-17 `output_ndu` generator，模型 SHA `2f766c9356333d86f7c78c1cb18e8c67e776019c1071ff7af4b112f294518549`；RewardA observer SHA `8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003`。它们在本轮开始前固定。训练标签来自实际保存并重新打开的 PNG 与 UTF-8 caption，由冻结 observer 与原始 target 离线判定联合正确性。target、RewardA 的输出、source ID、view 标签与未来 RNG 不进入 head 的 508 维特征。

| 公共特征 | 维度 | 实际来源 |
| --- | ---: | --- |
| 当前生成共享状态 `h` | 96 | 实际生成器状态 |
| Encoder context | 96 | 公开观测的条件编码 |
| 当前随机图像草稿再编码 | 96 | generator 自己的公开像素 encoder；不使用 RewardA 标签 |
| 当前 caption | 192 | 8 个实际 token，各 24 维 one-hot |
| 两块公开 mask 均值 | 2 | 观测存在程度 |
| 两个 hint | 22 | 各含 unknown 的 11 类 one-hot |
| hint reliability | 2 | 公开 flags |
| keep/swap 命令 | 2 | 公开 one-hot |

Head 为 `508 → affine(32) → tanh → affine(1) → sigmoid`。train 角色 0–3999 对用于 fitting，其中 3,000 ID、1,000 absence；4000–5999 对用于 development，其中 1,000 ID、1,000 absence。固定 Adam、lr=0.002、weight decay=0.0001、batch=128、2,000 step，每 100 step 计算 development BCE，最低者入选，同值选较早者。实际选中 step 400，BCE 0.1971922517。完整 20 个 checkpoint 的选择轨迹保留在 `RESULTS.json`，没有拿 calibration 或 verification 选择 head。

ID development raw prediction 的 1/3 与 2/3 分位固定为 `[0.8623580871721156, 0.9377036038021233]`。校准只估计三个 ID bin 和一个公开 complete-absence bin 的 `(successes + 0.5)/(n + 1)`。没有强制零概率、直接 abstain override 或放大 residual。Weights SHA 为 `a79979a3801c83cd4a789c6a87ff56f2efba63428da7c597f537fe5c6567b6f7`；calibration SHA 为 `93b5cd49fd317fa2281af45db194f676478a0fdeff2e158c5d95c0adc4d28d98`。

原始 [`NeuronModelPort`](../../../../codex-rs/hepta-neuron/src/runtime_types.rs) 接收绑定 config、encoder、head、weights 的 feature vector，由实现返回 drive、prediction 和实际执行 receipt。本轮没有改这个接口；[head.rs](head.rs) 真正执行冻结 MLP，并核对调用身份、特征宽度、模型结构、概率范围和输出 digest。研究进程中的 pin/custody 不等同生产调用主体认证；它没有接管现有 `GenerationDriver` 或独立 credential issuer。

| Native 字段 | 本轮真实语义与代码映射 |
| --- | --- |
| `feature_vector_q24` | 508 个公开特征，绑定固定 source/model/profile |
| `state_width=32` | 原始 sparse state，`top_k=4`；不是把 508 维语义完整预测成 32 维未来状态 |
| `drive_q24` | `[Q24(1), first31(public features)]` |
| `prediction_q24` | `[Q24(calibrated p(correct)), same first31 features]` |
| `prediction_error_q24` | 原 sparse kernel 的最大绝对差；本构造为 `1-p` |
| `zero_confidence_error_q24` | 原量纲 `1<<24`，没有扩大 scale |
| `maximum_in_domain_error_q24` | 同样 `1<<24`，没有扩大 scale |
| native confidence | 原 `calibrate()` 得到约 `p`，只有 Q24/ppm 取整 |
| native OOD score | 原 `calibrate()` 得到约 `1-p`；本 profile 只声明其对 complete absence 的实际 FAR |

**第一维的 1 是常量 success-reference。这是 confidence 编码适配，不是实测未来 latent dynamics。** 其可用性由独立正确性标签和实际 native 行为支持。它不能证明早期输入已包含未来输出，也不能替代条件价值函数、一般 NDU 递推或对未知 OOD 的认识不确定性预测。

## 4. 校准与独立验证的完整主要结果

ECE 使用 10 个固定等宽概率 bin、实际 runtime 量化后的 ppm。ID 与全 cohort 分别报告；写入 native profile 的实测 ECE 是 calibration/verification、ID/full 四者最大值的向上取整，为 **24,467 ppm**。原门槛仍为 ECE≤30,000 ppm、OOD FAR≤4,999 ppm、confidence≥750,000 ppm、OOD score≤500,000 ppm。

| 分组 | 校准 n / successes | 固定概率 | 独立验证 n / successes | 实际 native confidence |
| --- | ---: | ---: | ---: | ---: |
| ID 低 bin | 281 / 213 | 0.7570921986 | 270 / 196 | 757,093 ppm |
| ID 中 bin | 263 / 226 | 0.8579545455 | 254 / 217 | 857,955 ppm |
| ID 高 bin | 256 / 233 | 0.9085603113 | 276 / 261 | 908,561 ppm |
| Complete absence | 800 / 0 | 0.0006242197 | 800 / 0 | 625 ppm |

| 指标 | Calibration | Independent verification |
| --- | ---: | ---: |
| ID 联合正确率 | 672/800 = 0.84 | 674/800 = 0.8425 |
| ID 接受率 | 800/800 | 800/800 |
| ID ECE | 0.0012788575 | 0.0244660550 |
| Full ECE | 0.00095192875 | 0.01254552750 |
| Full Brier | 0.06517152512 | 0.06259948066 |
| OOD false acceptance | 0/800 | 0/800 |
| OOD FAR 单侧 95% 上界 | 0.003737662826 | 0.003737662826 |

FAR 上界用预声明的零计数精确公式 `1 - 0.05**(1/800)`，低于 0.004999。新 profile 还要求 ID 接受率至少 25%，实际为 100%，所以没有用全部 abstain 获得空洞通过。接受率 100% 同时伴随 126 个 ID 错误；它不等于全任务正确，更不等于增加了生成质量。

校准 cohort 的 ECE 是拟合后的数值，不能当成独立证据。独立 verification 的 ID 正确率 Wilson 95% 区间为 `[0.8156282195, 0.8660982503]`。对其 5 个固定 ID view 分层、按来源对重采样，4,000 次 bootstrap、seed 28191017，ID ECE 的描述性 95% percentile 区间为 **`[0.0119708164, 0.0506751291]`**。因此，原生**点估计门槛通过**成立；“人口 ECE 以 95% 置信度不超过 0.03”不成立。这个区间没有被用于修改或重新解释冻结 gate。

新 protocol 只有一次校准与一次独立验证，没有失败后重开 validation、重标 OOD 或换阈值。旧 v6 ECE 503,354/612,707 ppm、两个 cohort OOD 均 32/32 false acceptance 的失败记录保持原样，见既有 [native REVIEW](../../abc_recovery/results/native-review-001/REVIEW.md)。新 confidence head 不替旧 predictor 改写历史结论。

## 5. 真正执行的 native tick 与 durable 恢复

[main.rs](main.rs) 对已验证的 1,600 个输出做 native replay。每对创建自己的 subject/scope 和单 tick runtime，logical sequence=1，profile 有效序列为 1–2。这是 **1,600 个单 tick 上下文**，没有宣称一个连续运行 1,600 tick 的生产 daemon，也没有测量长期 calibration drift。

每个上下文都调用原 `NduProjectionStoreV1` append/select、备份与 reopen，然后原 `NeuronRuntime::bootstrap`、`tick`、`FileAnchorWitnessStore` 和 canonical checkpoint。返回的真实 anchor 与 eligibility 被记录；关掉 runtime 后重新打开 witness 和 journal，原 `NeuronRuntime::recover` 得到完全相同的 anchor 与 eligibility。1,600 个 confidence/OOD 输出全部逐行匹配冻结资格计算。

ID 有 800 个实际非 abstaining tick，OOD 为 0。**OOD abstaining tick 仍然产生正常 journal/witness 和恢复证据**；没有把 abstention 写成零提交，也没有把所有 1,600 次写成非 abstaining admission。Native 重放复用了已经观察的 verification 数据，其统计独立 N 不变。

这里的 NDU 值是该输出实际观察到的 terminal utility（`1 - 2 × weighted loss`）的 Q32 投影。observed result 的 digest 与相同 objective/subject 绑定。这个 terminal 信号没有作为 predictor 特征使用；它供观察结果后的局部 plasticity 链使用，不代表在线已知未来 outcome，也不是一般条件 NDU valuation owner。

### 5.1 资源口径

实际主机为共享 8 CPU quota、8 GiB 内存的 Linux container、local overlay filesystem。单线程 Rust head 使用已经 resident 的模型、features 与 packet。保留的主机明细和实际二进制 SHA 在证据索引中；这不是生产目标主机 attestation。

| 测量 | 实际值 | 原门槛 / 解释 |
| --- | ---: | --- |
| Native receipt P95 / P99 | 379 / 623 μs | ≤3,000 / 8,000 μs |
| 完整 `runtime.tick` 外侧，含 durable witness P95 / P99 | **676 / 1,425 μs** | 同一 3,000 / 8,000 μs envelope |
| 非 abstaining ID 单独外侧 P95 / P99 | 675 / 1,425 μs | 没有靠 OOD 行压低资格延迟 |
| Head transient peak live allocation delta | 5,848 B | 实际 allocator 计量 |
| 整个 tick 外侧 peak live allocation delta | **11,870 B** | ≤524,288 B |
| 模型加载后新增 resident heap | 132,477 B | 单独保留，不冒称 transient |
| 进程终点 / 峰值 RSS | 23,976 / 24,004 KiB | 包含已 resident 输入；不冒称 512 KiB 全进程内存 |
| 最大 canonical checkpoint | 1,528 B | ≤1,048,576 B |
| 每 tick journal / witness 新增字节 | 816 / 112 B | 两者合计 928 B |
| Native journal write amplification | 0.534032× | ≤4×；合并 witness 约 0.60733× |
| 完整 1,600-case Rust 进程 wall | 5.982949 s | 含上下文准备、恢复与输出，独立于每 tick 分位数 |

外侧时钟覆盖 `runtime.tick` 返回前的持久化 acknowledgement。NDU projection 的上下文准备、初始化、后续独立 checkpoint 文件导出与恢复在该时钟之外，包含在进程总 wall 中。这个 envelope 是 resident head 的边界；没有偷偷把 full generator 称作 sub-millisecond。

### 5.2 上游生成与训练成本保留

对已观察 development 中 128 对 clean 输入做单请求串行计时，仅作成本测量，不增加资格 N。实际 generator+公共 draft encoder 特征计算 P50/P95/P99 为 **6.6772 / 8.8469 / 13.3409 ms**；再含输入准备为 **7.0255 / 9.4972 / 13.7926 ms**。这些数值尚未包含 head、journal 和 raw media serialization。进程 startup/import/load 1.9799 s，峰值 RSS 369,061,888 B。

因此完整上游生成不能继承 resident head 的 3ms/8ms 资格。本轮没有解决旧 cold Python worker 或完整 multimodal generation tick 的相同 envelope。

最初 6,000 对 train 数据生成的已计时段 wall/CPU 为 12.2122/12.2025 s，校准 1,600 对为 4.0977/4.0934 s，验证 1,600 对为 3.7720/3.7695 s；这些计时在 Python/Torch import 后开始，不冒称完整冷进程成本。

另用两个新 Python 进程复现冻结 train-only 全流程：包括 imports、原数据检查/加载、6,000 次真实生成和媒体/标签、2,000 次训练更新、development 选择、写出与退出，总 wall **19.515262584 s**，child CPU **21.038287 s**，wrapper 所观测的 `RUSAGE_CHILDREN` RSS 高水位 **370,286,592 B**。Weights 和 cuts 的 SHA 与原预验证冻结产物逐字节相同。此为冻结算法的后置成本复现，未再打开 reserved role，未替换原选定模型，也不将耗时伪称原始那一次历史 wall。此前 generator/observer 训练、校准/验证、工具链安装成本均未包含在该 19.515 s 内。

该 wrapper 的 CPU 使用前后累计用量之差；RSS 使用结束后的累计 child 高水位，未保存运行前的 RSS 高水位。如果 wrapper 继承了更早 child 的资源历史，这个值可作为本轮 child 峰值的上界，不能证明为隔离测得的本轮两个 child 的精确峰值。原数值和原始回执保留，新增的范围说明见 `RESULTS.json.measurement_scope_notes`。此限定不影响 wall/CPU 差值、Rust 进程自己的 RSS/瞬时分配测量、校准数据或 tick/proposal 门槛。

## 6. 相同上下文的真实 resolver、候选与 proposal

固定使用预先按序的 case 0。它的 `joint_correct=0`、confidence=857955 ppm，不是挑选一个成功任务进行演示。上下文为：

| 身份 | 值 |
| --- | --- |
| Objective | `1ccf9287e4246569678a1ff65b8d28dbb7d9307a0869cfc7b7a81421ad8626b3` |
| Subject scope | `6d72083e6019829a797c0ae370749cc3e3896a011f6e3a3ccaca7e002dea5775` |
| Acknowledged neuron anchor | `4a4e7caf49a7113c98c270f68d5d3be78697112f7b7896dda17c64842be9d898` |
| NDU modulator | `84f7427b8ddfe0c596f2d7648a70bd62b4b5a1241aa7a1d067b07b5cf5a67986` |
| 实测 terminal utility Q32 | `1220686304` |

[proposal.rs](proposal.rs) 重开该实际 NDU store、acknowledged sparse journal 与 immutable artifact registry，以原始 `PlasticityDynamicOwnerEvidenceResolverV1` 进行 modulator、eligibility、broadcast 和 32 个参数信号的 35 次解析。32 维 eligibility 显式对应已训练 head 的 32 个 `w2` 参数；实际非零 eligibility 位于 11、13、22、23。Qualification query 中缺少的 frontier 真实保持零，没有填常数通过。

原 V3 parameter generator 在 learning rate=0.0001、scale=1/0.5 下生成 no-change 与两个非零候选。Full-scale 的 `delta_q32` 分别为：`w2.11=97267`、`w2.13=151997`、`w2.22=122628`、`w2.23=116381`；half-scale 分别为 48633、75998、61314、58190。Baseline output layer squared norm 为 `39266325987527787044` Q64。

这个更新是局部 utility × eligibility 的 three-factor perturbation；它不是 generator backpropagation，也不证明这些 eligibility 是该正确率 loss 的梯度。登记的本地类型化 allowlist 不冒充经过认证的 `control.engineering MutationGrammar`。

实际把候选参数代入已观察的 2,000 对 development：

| 候选 | Raw probability Brier | Calibrated ID ECE | 最大 raw probability 改变量 |
| --- | ---: | ---: | ---: |
| No change | 0.058366352931054 | 0.020729642 | 0 |
| Half scale | 0.058366371187071 | 0.020881110 | 0.000009244142 |
| Full scale | 0.058366389446792 | 0.020881110 | 0.000018488500 |

两个候选均略微恶化。Development 本身已被用于选择 head，结果明确标为 `eligible_for_independent_acceptance=false`。没有把数据换标签冒充独立验收；也没有因为 gate 描述性值仍过线就应用更新。

携带实际 evaluation digest `183e8ab41111f94ba5634f54507cf0d6fde541ccd87613ceb900c17c20895ec8`，原 `propose_v2` 生成 proposal，原 `DurableProposalRegistry` 与实际 Agentd anchor witness 代码完成追加、持久化、关闭和恢复。Proposal digest 为 `750094cead6778409c0400e4eb932fb9be162309df7a929285f5e94bf9a37f09`，proposal anchor 为 `d6e6595445de833b45987b141771a29710c4ff99178fe3d7eb750fc564aaf911`。

### 6.1 Product admission 的实际拒绝不可省略

原 `resolve_agentd_plasticity_admission_v1` 已真实调用并拒绝为 `ArtifactBinding`。实际 `learning.ledger` 为零条记录、零 head；原实现对这个零 frontier 在 owner-evidence 分派前就返回 `ArtifactBinding`。因此，本轮没有到达 DatasetSnapshot owner 或签名验收，更不能把推导的后续缺项说成已执行的独立错误码。合格的 DatasetSnapshotReceiptV3、当前 learning-ledger frontier、独立候选评估与真实独立 trust authority 仍然缺失。核心 proposal 的低层持久化 API 可以存储待独立验收研究提案，但不因此获得完整 product admission。该区分写入结构化结果。

旧 blocker 是“没有 acknowledged neuron checkpoint，resolver/parameter/proposal 链根本没构造”。新结果是“真实 checkpoint 后的同上下文 resolver、非零候选与 authority-free durable proposal 已执行；实际 product admission 阻塞于真实 artifact/frontier 资格”。这属于可验证的工程推进，不能写成所有生产 blocker 已关闭。

## 7. 原始 Rust 范围、测试与没有发生的事情

原代码通过固定 ref GitHub connector 读取，逐文件验证 SHA-256 与 Git blob SHA-1，并按匹配的 index 身份补入本地 Git object store。没有因 shell promisor 网络认证失败而将仓库宣称不可读，也没有更改 Git 配置或凭证。

构建只包含 20 个原 Hepta library crates，加 original-byte Agentd 三模块 bridge 和新 harness，共 22 个 local crates。Bridge 使用原 `plasticity_host.rs`、`plasticity_owner_evidence.rs`、`plasticity_anchor_journal.rs`，只增加根 re-export，未重实现 resolver/owner。原 Rust 源文件均未修改。隔离 workspace 的 Cargo manifests 删掉未运行依赖 crate 的 dev-dependencies，缩小 members，保留所需 features，最终依赖版本从原 `Cargo.lock` 恢复；没有声称与完整 production workspace 的 feature unification 完全等价，也没有修改生产 Cargo manifests/lock/Bazel。

正式验证通过仓库 `just test` 调用 nextest：

- `codex-hepta-neuron` 与 `codex-hepta-plasticity`：135 tests，0 failure/error/skipped；
- original-byte owner bridge：16 tests，0 failure/error/skipped，覆盖 owner/context/value 绑定、rollback、append/ack 恢复与 crash/restart 路径；
- 合计 151 个独立测试 case。第二组曾在临时 tempfile 3.26.0 下运行，发现与原 lock 不同后恢复为 3.27.0 并重跑；正式计数只采用后一次，不将重复运行累加为 167。

在形成实际结果之前，出现过缺少 compile-time AUTHBUS fixture、隔离 nextest 配置引用不存在 workspace package、未设置 local profile、harness 私有 API/字段名与 Rust 小数语法错误。依次补齐原 fixture/原 local 参数并修正新 harness 后继续；这些是构建/配置失败，不是被丢弃的 calibration cohort。所有新协议 calibration/verification 开启次数仍为一。未运行全仓 tests、远端 CI、daemon/fleet、生产资源 qualification 或 clippy全仓修复。测试回执 SHA、执行 binary SHA 和复现路径见 [REPRODUCE.md](REPRODUCE.md) 与证据索引。

## 8. 保留的 blocker 与下一次可执行验收

| 问题 | 本轮状态 | 下一次需要的真实证据 |
| --- | --- | --- |
| Resident correctness head 点估计校准 | 已通过新 profile | 如需人口 ECE 高置信保证，应预声明更大独立来源与其统计 gate；不能重用本 verification 作为新未见集 |
| 旧 latent-dynamics predictor | 原失败不变 | 真正未来状态/误差预测模型及独立校准 |
| Research tick/journal/recovery | 实际完成 | 生产匹配注册、长期多 tick、drift/expiry 与真实目标 host |
| 条件 NDU 在线控制 | 未建立 | current public history → learned conditional value/feedback → future generation 的 native 执行与完整成本 |
| Same-context 参数候选 | 已实际生成，但效果略差 | 有理由的 update rule、独立来源评估与 admissible parameter scope |
| Product proposal admission / 更新 | 实际 `ArtifactBinding`；未应用 | 真实 DatasetSnapshot、learning-ledger frontier、独立 candidate evaluation 与合法 trust authority |
| Agentd/fleet/intuition | 未运行 | 完整 host/lifecycle/configuration、对应 owner admission 与实际 daemon receipt |
| 完整 generation 3ms/8ms envelope | 未通过本 resident 结果解决 | 包含 upstream generation/feature/media 成本的适用资源 profile |
| 原生文字/语音/视频 | 本轮未接入 | 真实 modality backend、注册与时钟/同步/输出证据 |

研究协议中的实际可执行链已到达真实 product-artifact 边界。继续合理的步骤是由拥有合法数据与 trust authority 的部署环境建立真实 DatasetSnapshot/learning frontier，然后用新的独立候选验收验证参数更新；在此之前保持 `RequiresIndependentAcceptance`、`DENY_ALL` 与无已应用更新。不能为了把状态表全部写成绿色而制造资格。

## 9. 成果保存与资源释放

仅提交主要完整报告、紧凑结果、来源/证据身份表与实现源码。原始媒体、features、weights、packet、per-case journal/checkpoint、二进制留在本地 `abc3-native-runs`，未归档到 GitHub。

已保留实际执行的两个 binary 及 SHA；释放本人可重建的 Rust target 中间件 1,260,100,734 B 和已验证的安装包/解包副本 559,691,616 B，约 1.82 GB。未删除旧实验科学文件。复现用源镜像、Cargo cache、工具链安装、执行 receipts 与大证据继续保留。

并发工作中另一 agent 曾在原执行源码提交前运行全局 `just fmt`，更改了 4 个实验 Rust 文件。本 agent 立即与 retained execution source 的 SHA 核对，只从严格匹配副本恢复了原字节，九个执行源码的 pins 全部再次匹配。该事件见 [FORMAT_SOURCE_IDENTITY.json](FORMAT_SOURCE_IDENTITY.json)；没有重新读取 reserved 来源或重新拟合。随后，协调 agent 在原执行代码进入 Git 历史后，已从 `codex-rs` 实际运行 `just fmt --base ee824c94f55018927a937d16fa8a96ed2627fa0a`，退出码 0。前后源码 SHA 与执行路径见 [FINAL_FORMAT_RECEIPT.json](FINAL_FORMAT_RECEIPT.json)，格式化差异单独提交，没有在格式化后重跑测试或 qualification。本报告的实际执行身份以预格式化来源 SHA 为准。
