# Hepta Continuous Spiking Network：独立群体研究实现与结果

> **结论：8–64群体网络已有可学习实现，解析算子独有优势和大模型优势仍未证。** 主72槽仅N8的七组过门；随后独立signed-only补充的9槽在三个宽度均达到沿用的数值门槛，但复用已公开test，仅作事后描述。45适配视图仍对应原qvi_full父模型。封存原件、独立指标重算、原超时和未知费用均保留。

## 1. 本轮完成了什么

本轮把局部再生扩散算子组成了可运行、可训练、可续算的小网络，并实现同一冻结表示上的梯度与解析 readout 对照。完成代码和数值测试，只能证明相应实现行为；有效学习、通用能力、规模优势仍须由各自实验门槛支持。

实现准确名称为 **QVI boundary-controlled population flow + value/risk operators**。当前 value/risk 是同一生成元的读出特征，未作为两项恢复/恐慌力直接反馈到 drift，不能把它称为原 Core Idea 的 Call/Put 双力方程已完整实现。

| 实现 | 实际行为 | 对应文件 |
| --- | --- | --- |
| 独立群体网络 | 每个神经元保留概率、signed mark、phase、边界与旧消息；两组有向连接 | `model.py` |
| 输入与评价合同 | 两次分离 cue、固定 source family、完整 prefix、pre-late 和停止费用 | `data.py` |
| 训练与封存 | 有界 Adam、开发选模、完整 checkpoint、依赖身份、失败与一次性测试 | `train.py`、`campaign.py`、`cost.py` |
| 五臂适配 | 公共parent/mask/评价；监督三臂同目标，STRICT_WSP禁标签拟合，保留KEEP/ABSTAIN | `adaptation_suite.py`、`editing.py` |
| 程序迁移控制 | 已知接口变换、角色内置换、完整状态变换与固定 delta 负控制 | `transfer_suite.py` |
| 数值与性能诊断 | 全参数/input VJP、真实新进程续算、长时 forward、独立固定 law 缓存 | `benchmark.py`、`fixed_law_benchmark.py` |
| 只读结果分析 | 固定门槛、同 seed 配对、失败分母、封存和预测哈希验证 | `analysis_results.py` |

研究工作接续上游 finite-volume/marked-renewal 实现，不重跑旧 PenDigits、169 配置、N256 或 HPCA 封存对象。本目录的 N 表示独立概率群体，不能与旧内容通道宽度混为同一规模变量。

## 2. 实验矩阵与公平性

训练实验预声明 N=8/32/64，每个 N 使用三个初始化和八个 arm，共72个槽位：`qvi_full`、`qvi_boundary`、`qvi_flow`、`fixed_full`、`learned_full`、`qvi_tanh`、`qvi_value_only`、`qvi_risk_only`。

每个 fit 最多512次 Adam 更新、180优化 CPU 秒，参数和 minibatch 设置共享。source family、初始 margin、训练/开发/测试划分和目标约定相同。正式设置使用原始特征 `feature_normalization=none`；归一化前测的阴性结果保留，不继续以前测选优。

| 比较域 | 合同与限制 |
| --- | --- |
| 神经元规模 | N 个独立状态，前半 sender、后半 receiver；receiver 不直接读原始输入 |
| 信息路径 | 耦合读取旧消息；原 `qvi_flow` 为无边界的 event+signed flow，mask `(0,1,1)`，不是 signed-only |
| 精度 | mixed 的可训练层/输出为 FP32，物理概率、网格和求解仍为 FP64 |
| 内核 | N8/32 使用 dense，N64 使用 uniformized；跨 N 时间差同时包含内核选择 |
| 功能消融 | 屏蔽 value/risk 的 arm 仍执行物理核，不计作省去求解的加速 |
| 参数 | `parameter_count` 含冻结的 raw_boundary；learned mode 多 N 个 trainable，消息 mask 改变有效连接，不能按总槽数宣称容量相等 |
| 预算 | 共同资源上限不等于相同更新数、FLOPs、达到同一最优点或充分收敛 |

冻结 manifest 绑定实际训练依赖闭包、协议与 Python/NumPy/Torch 环境。独立分析及缓存诊断不进入训练闭包，不能借此改变已冻结的 `model.py` 或正式训练选择。

同N、同QVI/full-message的value/risk/tanh组匹配名义参数槽与声明特征维度，但单通道消融把部分readout列置零；boundary-only还阻断sender mark通路。因此是同任务/物理状态/预算下的结构消融，不是严格等有效参数。qvi_tanh仍运行population流，只替换两个特征，不能当独立传统RNN基线。

**冻结身份：** `evidence/PROTOCOL_FROZEN.json` 的 canonical SHA256 为 `c259030b227f25bc72ccbab12402fbe62747df845c9dce965e795b85b1af176d`；14个训练依赖绑定 CPython3.12.3、NumPy2.5.4、Torch2.8.0+cpu、单线程。适配与迁移各有独立冻结协议；训练及全局适配 seal 位于源胶囊 `evidence/training/SEAL.json`、`evidence/adaptation/GLOBAL_ADAPTATION_SEAL.json`，下载清单保存文件SHA。

## 3. 数学对象与两处导数修复

局部 QVI 解的是冻结漂移、奖励与成本下的 Brownian 再生控制：触界后进入 Erlang 等待，再回到固定绝对 reset 位置。边界由标量根求解，并通过隐函数的一阶导数参与训练；当前不支持二阶自动微分保证。实际网络使用有限空间格、反射上界、输入控制和群体反馈，没有继承整个网络的最优控制定理；finite-volume、有限 Erlang phase 和采样点写入是近似或模型合同，重复采样并减小 dt 会改变总写入量。

value 是实际有限生成元的折现 continuation 解，risk 是区间内至少一次事件的概率；二者不能直接命名为原金融论文的 equity call 与 put 价格。risk 和重复事件期望数不同，初始 phase 释放后再触界也必须计入。

本轮修复了两处前向近似正确、导数却可能错误的问题：

1. 零边界位移时，多个独立 min/max/clamp 分支的 AD 可能不守恒。改用同一个 cell CDF 差分，使 lower、格间重叠和 upper 在值与导数上共同相消。
2. 三角沉积在精确格中心的默认 ReLU/abs 导数可能破坏“一阶矩等于输入位置”的导数恒等式。改用 symmetric clip，在精确 knot 明确采用左右斜率平均，并检查一阶矩导数。

这些修复支持有限网格上的**分段可微**实现，不使所有 kink 消失，也不是全局 smooth-pasting 定理。长时 forward 的守恒、续算和有限差分/VJP 检查，分别回答不同问题，不能互相替代。

## 4. 输入语义与预先保留的负面限制

标签由两次到达的独立连续 cue 的和决定。source 改变增益、噪声和 cue 时刻；所有 source 都是模拟参数族，不是独立真实人体或传感器队列。晚信息到达前仍有可利用的早期信息，不能把多数类表现当成充分利用早期 cue。

当前 B 是单拍脉冲，law 仅在偶数 tick 更新；`boundary-only` 可能漏掉奇数 tick 的 cue，而其他 arm 可通过 signed content 传递。该 alias 是当前采样和通信合同的限制，不证明边界通信本质不可行。

active mark 每拍按固定比例擦写；持续处于 active 且未获补充的早期内容会反复衰减。phase、回流和递归内容另有演化，不能把局部衰减率推广成全网络记忆定理。当前没有改成事件门控写入。

pre-late 评价使用各样本晚 cue 前一拍；t=0 的 receiver 尚未收到 sender 消息。停止策略为预声明置信度阈值加末拍强制决策，并收等待费用；没有将其称为分类任务的最优停止解。

## 5. 测试与执行限制

按不同测试方法去重计数：原有37项加固定 law 3项，共 **40项 Torch runtime 测试**；另有 **4项本地 stdlib 分析测试**，合计44项。runtime覆盖数学/状态、输入、编辑/迁移、封存、目标与缓存；分析测试以人工回执检查门槛、失败分母、费用和证据拒绝，不打开正式holdout。不能写成44项全在Torch运行，测试通过也不等于所有native32或长时诊断通过；signed-only新增测试另列。

**精度结论须按内核区分。** mixed 通过不能替代 native32 通过；已测 dense native32 长时失败，追加 uniformized native32 的四条轨迹则在原 `3e-5` 门槛下完成512步，未进行概率重归一化。正式训练仍保持已冻结的 mixed，不因此事后更改策略。

| 精度/内核 | N与law日程 | 长时forward结果 | 最大质量误差 |
| --- | --- | --- | --- |
| mixed / dense | N8，fixed与slow=2 | 两者512步完成 | 两者最大 `9.712e-13` |
| mixed / uniformized | N8，fixed与slow=2 | 两者512步完成 | 两者最大 `1.482e-13` |
| native32 / dense | N8，fixed | 第103步失败，完成102步 | 失败步 `3.016e-5` |
| native32 / dense | N8，slow=2 | 第356步失败，完成355步 | 失败步 `3.004e-5` |
| native32 / uniformized | N8，fixed | 512步完成 | `4.530e-6` |
| native32 / uniformized | N8，slow=2 | 512步完成 | `2.021e-5` |
| native32 / uniformized | N32，slow=2 | 512步完成 | `1.919e-5` |
| native32 / uniformized | N64，slow=2 | 512步完成 | `2.414e-5` |

表中为 batch 1、关闭梯度的单轨迹。追加 T=6、batch 4、N8/32/64 的 native32 uniformized 对 FP64 dense 检查中，无缺失或非有限梯度：拼接全部参数的单标量 loss VJP 相对 L2 最大 `7.5201e-7`，输入最大 `9.1118e-7`；逐参数张量最大相对 L2 为 `1.8650e-6`。拼接误差不是每个参数的上界，VJP 不是完整 Jacobian。这些结果不构成512步BPTT或正式FP32训练资格，也不增加单测计数。

依据为 `evidence/audit/benchmark_v04.json` 与 `evidence/audit/native32_uniformized.json`；追加诊断 worker CPU 至回执为20.939秒（含导入、不含退出），源码/model哈希和正常退出见相应 job/source 原件，冻结 model 未修改。

`just fmt` 已尝试，但独立 checkout clone 超时后缺少 `codex-rs` 工作目录，格式化命令未实际运行；状态为 unavailable，不是通过。本次没有修改 Rust。证据见 `evidence/audit/rust_formatter_unavailable_execution.json` 及两份 clone-timeout 回执。

**最终评测发生 operational timeout。** 原 finalizer job `1a20dbaee10-ffbe-398e` 达到1800秒上限，以124退出。九个适配最终评测与训练63/72槽已完成，余9槽；不能据此声称原十个工作单元一次全部成功，也不能将超时等同于模型数值或训练失败。依据为 `evidence/audit/final_stage_timeout.json`。

独立恢复仅补9个缺失测试槽位，完整封存预检先于数据构造，另建 `RESUME_CLAIM`。9个worker全部以0退出，原63个row/prediction对字节不变，最终72槽完整；本次partial清单为空，无需移文件。原 `FINAL_CLAIM`、阈值、权重与选择保持。`evidence/FINAL_STAGE_RECEIPT.json`、`evidence/training/RESUME_RECEIPT.json` 同时保留原124退出与续测成功，未抹去原超时和已耗资源。

## 6. 正式训练结果与学习门

逐 seed 须同时满足最终准确率≥.8、相对同seed初始提升≥.1、相对pre-late提升≥.1；每个N×arm至少2/3 seed通过，使用未舍入值。缺失/失败留在预定分母，均值只用已评测seed并报覆盖；selected step 0不能称学到任务。缺证组为UNVERIFIED，封存/预测身份不符则拒绝分析。

72/72训练与评测均完成，0个训练运行失败；封存/逐项回执/预测SHA全部核验。完整24组及72逐项结果见 [RESULTS_TRAINING.md](evidence/summary/RESULTS_TRAINING.md) 与 [SUMMARY.json 的无损分块清单](evidence/summary/SUMMARY.json.parts.json)。另由 `evidence/INDEPENDENT_METRICS_VERIFICATION.json` 对72份selected/initial完整prefix logits独立NumPy重算指标，最大标量差 `2.220446049250313e-16`；这是保存预测的指标一致性，不是重跑物理轨迹。

| N | qvi_full 最终准确率与 seed SD | 相对初始提升 | final−pre-late | 通过 seed/预定 seed | 证据与组门槛 |
| ---: | --- | --- | --- | --- | --- |
| 8 | 90.04±1.88% | +40.89±2.86个百分点 | +14.26±2.20个百分点 | 3/3 | 已核验，PASS |
| 32 | 60.87±14.43% | +11.72±16.10个百分点 | +0.59±1.01个百分点 | 0/3 | 已核验，FAIL |
| 64 | 52.54±0.00% | +1.69±2.93个百分点 | 0.00±0.00个百分点 | 0/3 | 已核验，FAIL |

其余七个 arm 的全部组结果和同 seed 配对差，从完整汇总直接引用，不只挑最好来源或最好 seed。seed 标准差不是置信区间。来源内先描述各 seed，再描述来源均值；不将多个层级混为独立样本，不输出未经设计支持的显著性结论。

24组中7组过门，全在N8：full/flow/fixed/learned/tanh/value-only均3/3 seed通过，risk-only为2/3；N8 boundary-only为52.54%、0/3。N8 learned/fixed/tanh观测均数分别92.84%/91.28%/91.41%，高于full的90.04%；没有测到QVI/full或value/risk双特征独有的优势，三个seed也不支持强显著性声明。N32/N64组均失败；N32 tanh仅单个seed过门，不满足组标准。

这是共同180优化CPU秒与512更新上限下的结果：N8全部512更新，N32为226–335，N64为178–253；宽度、backend和已完成更新量同时变化，不能归因纯宽度或证明较大网络没有表达能力。11/72尝试保留step0，均按原件报告；数值测试通过不替代学习门。

## 7. 五臂适配：监督对照与信息限制

适配仅使用九个 `qvi_full` selected parent 的冻结 final features，只允许改变 readout weight/bias。训练整网与适配 readout 是两个问题，不能用第二阶段优势宣称第一阶段 BP 已被取代。

BP/ANALYTIC/HYBRID共享标签、表示、参数域及signed one-hot的MSE+权重ridge目标，bias不惩罚；BP与解析正规方程尺度一致，工作求解采用FP64，转回parent dtype后才评价。KEEP不优化，STRICT_WSP proposal禁止标签拟合与梯度，外层仍统一评价并分摊费用。**五臂不是同信息竞赛**；WSP是不同可用信息的能力边界对照，成本/质量配对主要针对同监督域三臂。

| 方法 | 实际含义 |
| --- | --- |
| KEEP | 保留同一 parent |
| BP | 在同一 readout 参数域使用有界 L-BFGS，统计实际 closure、停止和候选数 |
| ANALYTIC | 对同一固定表示和目标求条件解析解，并支付矩阵构造、条件诊断及求解费用 |
| STRICT_WSP | 没有可识别的无标签能力构造时 ABSTAIN，保持完整参数 |
| HYBRID | 独立求 ridge，再从预声明的 parent-to-ridge blends 按 dev 选择；不是 edit-then-BP |

旧域 accuracy/Brier 保持门和新域选择只读 dev。保持门是聚合条件，不能声称每个来源均不退步；独立测试须同时报告旧域、新域、最差来源和未采用候选。

公共特征提取和 cache IO 的实际成本向五臂同等分摊；各臂另承担构造、开发选择、失败、写盘和重载。parent 训练成本单独继承披露，不把同一 parent 的训练费用重复相加为五次实际执行。

九个 parent×五臂共45个最终视图均已评测，最终身份回执与开发集 selected candidate 一致，未使用测试结果重选。每个旧/新域测试含八个模拟 source、512个样本；所有方法共享这些样本。下表为九个 parent 的等权均数，混合三个 N，不能当作九次同规模独立实验或45个独立数据集。

| 方法 | 采用/9 | 旧域准确率 | 新域准确率 | 新域Brier | 新域停止效用 |
| --- | ---: | ---: | ---: | ---: | ---: |
| KEEP | 0 | 67.8168% | 64.0625% | 0.386069 | 0.593321 |
| BP | 8 | 72.9167% | 70.4861% | 0.341633 | 0.647569 |
| ANALYTIC | 8 | 72.9167% | 70.3993% | 0.341345 | 0.639744 |
| STRICT_WSP | 0（9次ABSTAIN） | 67.8168% | 64.0625% | 0.386069 | 0.593321 |
| HYBRID | 9 | 72.9384% | 70.4427% | 0.338935 | 0.640945 |

按 N 分开看，新域准确率三 seed 均数为：

| 方法 | N8 | N32 | N64 |
| --- | ---: | ---: | ---: |
| KEEP / STRICT_WSP | 87.5651% | 57.3568% | 47.2656% |
| BP | 89.1927% | 75.0000% | 47.2656% |
| ANALYTIC | 89.1927% | 74.7396% | 47.2656% |
| HYBRID | 89.3229% | 74.7396% | 47.2656% |

五臂各自9/9 parent 的最终旧域聚合 accuracy/Brier 满足预声明保持容差；这是事后描述，不是新增接受或选模决策。BP/ANALYTIC 各有3/72、HYBRID有5/72个 parent-source 准确率下降，每次1/64；最差来源的最小值不降并不表示每个来源不降。三个监督方法均只有7/9 parent 的旧域 Brier 不增，另外两个仍在容差内。

ANALYTIC 相对 BP 的平均新域准确率略低0.0868个百分点、Brier略好、停止效用低约0.00783；没有支配或质量等价结论。N64 的准确率没有因 readout 适配改善，不能用其他 N 的改善宣称规模优势。

依据为 `evidence/ADAPTATION_FINAL_TEST_AUDIT.json`（SHA256 `5e9060574d22e7e4707df76c8949d97f169b18e84772f8a18a44c805881f2095`），其范围是报告文件及身份/SHA引用。后续 `evidence/INDEPENDENT_ADAPTATION_VERIFICATION.json` 已用独立NumPy从45/45份保存的logits重算旧/新域指标，最大标量差 `2.220446049250313e-16`；这增加了预测与指标一致性验证，不是重新执行45个checkpoint的动力学。

## 8. 独立固定 law 推理优化

`FixedLawHCSN` 只覆盖 `_flow`，要求 dense、关闭 autograd，以及序列期间保持 law。缓存 augmented matrix action、first-hit vector 与 continuation value，按完整配置及 generator/event/boundary/cost 的值、形状、dtype/device 校验；改变 law 必须显式清缓存。

概率、signed mark、phase、消息、输入写入和 readout 仍每拍推进。完整 forward 计时包含初始化、控制起点、生成元构造和cache-key检查。配置为CPU单线程、N8/32/64、FP64/mixed、64 ticks、batch 4、一个初始化、每项三次计时；执行顺序固定，warm中位数比只描述该次短基准。首次构造另列，action视图不重复计入plan bytes。

六个 FP64/mixed case 的 logits、features、五个状态张量与原实现的最大观测误差均为0。mixed 的完整 forward CPU 如下（秒；cold列包含一次计划构造，warm列为三次中位数）：

| N | 原实现 | cold缓存 | warm缓存 | 原实现/warm | plan CPU | plan tensor bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | 0.251235 | 0.148478 | 0.147031 | 1.7087× | 0.001818 | 70,784 |
| 32 | 0.411683 | 0.171915 | 0.167414 | 2.4591× | 0.003991 | 282,752 |
| 64 | 0.735954 | 0.204369 | 0.195494 | 3.7646× | 0.008937 | 565,376 |

plan bytes 只计持有tensor，action views不重复计数；不代表进程总内存或构造峰值。原件为 `evidence/audit/fixed_law_benchmark.json` 与 `evidence/audit/fixed_law_job.json`。

这项优化没有修改冻结 model，不支持缓存 BP 图，不证明动态 law 或正式 N64 uniformized 提速，也未验证原生 FP32/AMP。能耗仍未知。

## 9. WSP 与程序迁移到底证明什么

已知 affine 输入接口可直接构造对应输入权重变换；已知标签 schema 可置换 readout。角色内神经元置换须同时变换物理 buffer、连接、readout 和完整状态。readout sign view 使用显式坐标 wrapper，不代表概率神经元具有符号对称性。

这些控制验证**已知规则下的程序迁移与语义等价**：输入按新接口编码、输出按已知标签置换解释；不是同一个无任务标记head同时保持互相矛盾的旧/新标签。对换坐标后的 checkpoint 重跑程序，与复制一份固定 delta 必须分开评价；同 checkpoint 的多个 view 不能充当更多独立模型。

本轮 `STRICT_WSP` 子协议禁止标签拟合与梯度，不能把监督ridge或标签驱动候选搜索归入该臂。九次ABSTAIN只表示本实现没有可识别的新能力构造，不概括所有WSP方法不可行；规则发现成本未测，不能写作零。已知接口和线性readout构造也适用于其他冻结encoder，不是HCSN独有优势。

九个独立训练尝试的选中 parent，各五项正控制，共45/45通过；63次完整 forward、程序零标签访问，原始参数均未变。跨全部正控制的最大绝对误差：logits `1.3709e-6`、features `4.7684e-7`、完整state `4.4688e-7`。九份原件位于 `evidence/transfer/`，冻结规则见 `evidence/TRANSFER_PROTOCOL_FROZEN.json`。

复制固定 delta 的负控制9/9不满足 logits 等价，其中三个case的argmax未变，不能称九个case的分类都失败。程序构造、克隆、哈希、forward和检查的已测body共16.080 CPU秒；不含程序发现、进程启动或JSON写出尾部，不将它解释为训练全新能力的总费用。

## 10. 成本汇总的包含关系

| 账本 | 统计范围 | 不应混入的解释 |
| --- | --- | --- |
| training CPU | 实际优化步，包括失败尝试和越界 | 不是完整 fit 或从启动到退出的费用 |
| fit body | 设置、训练、开发选择及 checkpoint | 包含 training CPU，不能再相加 |
| worker CPU | 解释器/导入到回执时刻 | 包含 fit；退出另由外层核算 |
| child/shard | 子进程至退出 CPU、调度器与分片 wall | 并发 wall 的和不是 campaign makespan |
| final test/seal | 共同完整性预检、独立测试与写盘 | 与训练/适配选择费用分列 |
| memory | 单进程 RSS 峰值、动态 tensor bytes、plan bytes | 不等于同时驻留总内存或 BPTT tape |

所有失败、共享准备和条件求解成本保留。包级能耗计数不能归属单进程时，不叠加为模型能耗；不把 CPU 秒换算为焦耳。

适配部分已回收的实际 CPU：45臂自身 body 共12.997秒，九个 parent 的共同特征准备共153.593秒，九次最终测试 body 共988.529秒；三项合计1155.118秒。它不含每个 worker 的解释器/导入/退出完整费用，不能写成完整生命周期总耗时。继承的九个 parent 训练 body 另为1764.560秒，只计一次，不重复分摊后相加。

| 方法 | 自身适配body均值CPU秒 | 共同费用1/5分摊后适配+测试 | 共同费用全额计入 | 再计完整parent训练body |
| --- | ---: | ---: | ---: | ---: |
| KEEP | 0.0287 | 25.3464 | 40.4218 | 236.4840 |
| BP | 1.3123 | 26.7862 | 41.8615 | 237.9237 |
| ANALYTIC | 0.0336 | 25.3870 | 40.4623 | 236.5246 |
| STRICT_WSP | 0.0322 | 25.3976 | 40.4730 | 236.5352 |
| HYBRID | 0.0374 | 25.4294 | 40.5047 | 236.5669 |

后三列是同一实际工作量的不同归属口径，不相加。ANALYTIC 相对 BP 的观察 CPU 减少在三种口径下分别约5.22%、3.34%、0.59%；因质量不等价，这些不是同质量训练加速。共同费用全额口径仍未补测整套独立生命周期；程序发现和每 parent 导入/退出 CPU 仍未知。

72槽优化CPU共12119.362秒，fit-body共13791.103秒，worker至回执共13938.111秒；三分片children含退出共13995.982秒。这些账本包含前者，不相加。N8/32/64分片wall分别1027.599/1248.131/1280.117秒，不把并发分片wall之和写成campaign历时。单worker RSS峰值最大471,429,120字节，评测chunk五个动态tensor最大212,992字节；正式记录质量误差最大 `2.354e-14`，不将这些数值解释为全机训练内存。

72个最终测试pair body共1422.211 CPU秒；原63个占1127.591秒，续测9个占294.620秒。续测children含退出313.699 CPU秒、driver至回执5.228 CPU秒/106.970 wall秒；children包含续测9个body，不能再相加。原finalizer含等待wall1811.716秒，临时systemd账本已不可用，原总CPU及被中断worker的导入/预检/部分case耗时未知，保留该缺口，不从wall推算。

## 11. 本轮结论与扩展门槛

主试验支持N8群体网络通过BP学习；第13节的signed-only补充进一步支持同任务N8/32/64的可学习性，属于事后描述。uniformized原生FP32在已测诊断域可行，固定law推理能复用算子，冻结表示readout能条件解析求解；均未证明QVI/full优于简单替代、boundary-only有效，或STRICT_WSP可取代整网BP。

主72槽的N32/N64组没有过门，但signed-only补充在相同CPU上限下各3/3 seed过沿用的数值门槛；原阴性不能归因宽度本身。完成更新量和训练轨迹仍不同，不据此建立一般通道优劣定理。纯signed仍含QVI及value/risk，主full-message的fixed/learned/tanh消融不能外推到纯signed N32/64，也不能将其成功归功于QVI。下一轮应在同signed-only合同内匹配fixed/learned/QVI边界和tanh/value/risk特征，保持信息与资源可比，再用未见source family复验；本轮未追加这些实验，补充不作新holdout声明。

当前没有与Transformer或现代SNN同任务/数据/资源的主干比较，没有多模态预训练、GPU吞吐或可归属能耗证据。固定状态、局部解析算子和条件readout解不足以推出大模型训练优势；扩展仍需数值/梯度、输入信息到达、独立新来源学习、旧/新域保持及完整成本证据，不以理论类比或推理缓存速度替代。

## 12. 原件索引与复现

完整命令见 [README.md](README.md)。代码、协议、数据身份、封存和选择历史与预测原件对应；只读汇总不拟合、不改阈值或checkpoint。非冻结后处理helper为解释恢复成本修订，旧/新版及短暂路径替换/恢复均记录于 `evidence/POSTPROCESS_REVISION_RECEIPT.json`；14个训练模块未改，最终输出仅移动至发布路径，字节未变、未重算。

| 原件 | 用途 |
| --- | --- |
| `evidence/audit/formal_freeze_execution.json`、`kernel_normalized_and_benchmark.json`、`smoke_population_execution.json`（均在同目录） | 冻结/测试、内核诊断和选择前阴性smoke，不是正式指标 |
| `evidence/audit/fixed_law_benchmark.json`、`native32_uniformized.json`及各自`*_job.json`（同目录） | 缓存基准、原门槛FP32追加诊断与回执；不改正式精度 |
| `evidence/ADAPTATION_FINAL_TEST_AUDIT.json`、`evidence/summary/`、`evidence/INDEPENDENT_*VERIFICATION.json` | 主矩阵、45适配视图、费用及两类独立指标重算 |
| `evidence/audit/rust_formatter_unavailable_execution.json`、`evidence/FINAL_STAGE_RECEIPT.json`、`evidence/training/RESUME_RECEIPT.json` | 格式化未执行；原124退出、63保留/9续测、成本缺口 |
| [无损运输说明](../hcsn_evidence_transport_20261125/README.md) 与 `INDEX.json` | 11 个原对象按 44 个小块存储；重组后使用原文件 SHA 与历史索引，研究结果未重写 |
| `evidence/archives/ARCHIVE_INDEX.json`、`GIT_PUBLICATION_MANIFEST.json`（同目录）、`evidence/preflight-evidence.tar.gz` | 主82份原始档案的SHA/内部路径；历史smoke、失败、source snapshots |

## 13. Signed-only 事后补充对照

原 `qvi_flow` 同时传 unsigned event 与 signed flow，未精确满足只传signed的需求。补充在 `../hcsn_signed_control_20261124/` 独立执行；只增加固定unsigned mask，不改原72槽、14个冻结模块、数据、目标或选择规则，也不把原flow成绩改名归入补充。

N8/32/64×3 seeds 的9槽沿用原mixed、backend及180优化CPU秒/512更新。补充源码、主协议与主结果均绑定身份；全9终态、initial/selected/last mask预检并封存后才测试。它在主结果公开后登记，复用已公开test，仅作描述性比较，不是预注册或新holdout证明。新增3项runtime测试已通过，分别确认唯独mask改变、原Core重载等价，以及仅signed跨神经元扰动有效。

9次fit与9次test均成功退出，全部selected step>0；9/9保存预测的独立NumPy指标重算最大差 `2.22e-16`，不等于重跑物理轨迹。下表沿用原数值门槛，仅作事后描述；±为3 seed样本SD。原72表及失败保留，原45适配/迁移未改用signed-only父模型。

| N | signed-only准确率±SD | final−pre-late | final−initial | 实际更新数 | 沿用门槛 |
| ---: | --- | --- | --- | --- | --- |
| 8 | 91.276±0.923% | +15.430个百分点 | +42.122个百分点 | 512 | 3/3 |
| 32 | 90.625±1.924% | +14.844个百分点 | +41.471个百分点 | 255–265 | 3/3 |
| 64 | 91.732±1.440% | +15.820个百分点 | +40.885个百分点 | 194–197 | 3/3 |

signed-only减原event+signed flow的同seed准确率差，N8/32/64分别为−0.391±1.408、+23.438±13.016、+36.263±8.546个百分点；不作新holdout或显著性声明。补充fit/test children含退出CPU分别1771.546/222.886秒，campaign wall253.604秒、driver至回执CPU4.760秒；优化1535.043秒和worker1765.795秒均在fit账本内，两个stage driver值是累计快照，不相加。主/补pair-body计时起点不同，不作速度对比，能耗未知。完整[补充结果](../hcsn_signed_control_20261124/evidence/RESULTS_SIGNED_ONLY.md)、同目录SUMMARY/协议/验证/EXECUTION/POSTPROCESS_REVISION及[复现命令](../hcsn_signed_control_20261124/README.md)保留全部身份与费用。
