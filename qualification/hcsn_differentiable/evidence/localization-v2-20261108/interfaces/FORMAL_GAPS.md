# 从真实接口进入可判别实验：实现缺口、数值门槛与成本

本文件是对已冻结源码和实际回执的只读分析，不是新的训练启动令，也不表示下面的候选构造已实现。当前 `formal_protocol.json` 状态仍是 `specified_not_admitted_not_started`。已有用户授权；缺的是实现、数值适用范围、训练充分性和可执行预算的闭合。

## 1. 已完成与仍未完成的边界

18/18 接口、72 个更新和独立种子张量检查已经完成，不需要再用同样的四步训练反复证明模型能运行。原片段只有 train 的 2 类和 dev 的 1 类，不能承担效果对照。当前物理 profile 对固定物理、固定 grid 和指定窗口的资格，也没有覆盖任意已训练观察似然产生的过滤状态。

下一轮最值得实现的是：真正的物理读数删减、同容量普通双门控、完整多类数据索引和可恢复训练器。CfC/SNN/S4D/attention 等六家接口无需再重复一次无效 smoke；它们随后应进入有容量与优化充分性约束的正式比较。

## 2. 明确到代码的缺口

| 位置 | 当前行为 | 正式执行所需实现 |
|---|---|---|
| `data.py::prepare` | 固定 A01 128 / D01 64；frontend 只拟合该 A01 片段 | 新 subject/sequence/row/tick manifest；ABC 训练、D 开发；完整序列分段、末尾短段、类别支持、标签权重；所有窗口先按无监督规则固定，再验收类别分布 |
| `models.py::build_model` | 每家宽度写死 | 类型化 model config、标签无关容量枚举器、实际实例化计数、配置/实现/依赖 SHA；强循环结构与 SNN/S4 的合理搜索空间 |
| `run_interface.py::worker` | Adam .001，固定四步，raw `torch.save` | epoch/validation/early-stop、配置选择、模型重拟合、校准、可恢复 dataloader 游标、重试成本和全研究上限 |
| `checkpoint.py::validate_adam_state` | `type(optimizer) is torch.optim.Adam`；拒绝 AdamW | formal JSON 指定 AdamW，必须增设真实 AdamW/group schema 与恢复验证，不能只换名称；保存 optimizer、scheduler、随机状态、窗口排列和语义配置 |
| `ContentLayer` / `ContinuousSpikingNetwork` | 五个物理读数进入多个神经路径 | 结构性 channel selector；每个模型的真实维度、state 和 checkpoint schema；不能靠置零列保留无用参数 |
| S4 优化 | 当前四步是统一 Adam | 读取并保留官方参数上的 `_optim` 分组信息，明确每组 LR/weight decay；不能让统一 AdamW 默认值覆盖官方零 decay 或特殊 LR |
| `benchmark_admission.py` | v1 schema，硬编码 `gru_d`、`mamba` 等 17 个臂，正式至少 5 种子 | 新协议/实现 registry 与准入版本必须显式对齐 S4D 身份；不能把 S4D 填成 Mamba，也不能把三种子 pilot 当作 v1 正式准入 |

训练器必须尊重 `_validate_state` 对全部参数的 snapshot：优化器更新只能发生在结束的 episode 之间。不能把旧 hidden state 保留到下一次参数更新后继续运行。所有模型使用相同的观察范围；不让循环模型保留跨段历史而 attention 每段清空。

完整 ABC 有 **89,216** 事件、D 有 **31,952**、E 有 **43,692**。按 256 长度逐序列分段并保留末尾短段，ABC 是 **356 个 episode/epoch**。JSON 中的“全量事件”不能被实现成丢弃尾段。当前 batch=1 可直接使用变长短段；以后 padding 必须统一 valid mask、`dt=0` 与 loss mask。损失按事件还是按 episode 加权、尾段是否按长度缩放，必须先确定，评价不能把不同长度段简单等权平均。

E 已做过完整性/时钟/global-gap 元数据审计；所谓封存只能指未做模型训练、调参和计分。ABC 自身最大 gap `.162175` 已独立核实，但不能据此重写 `.2` 的实际选择历史。

## 3. 容量匹配可以具体实现，但尚未通过实例验收

保留当前一层、FP64、25 输入、11 输出以及冻结物理 HCSN 的 **9,804** 个可训练参数作为示例参考。根据目前 adapter 的结构，以下是标签无关的静态计数候选；它们不是已训练或已准入模型。

| 家族候选 | 静态参数数 | 相对 9,804 |
|---|---:|---:|
| 单层 GRU，hidden=44 | 9,867 | +0.643% |
| CfC，units=12、backbone=112 | 9,823 | +0.194% |
| recurrent PLIF，width=82、共享可学习 tau | 9,770 | −0.347% |
| S4D-Lin，width=54、state=16 | 9,785 | −0.194% |
| causal Transformer，width=24、heads=2、FF=128 | 9,691 | −1.153% |

计数分别来自当前单层结构的 `3h²+92h+11`、`26b+5bh+15h+11`、`h²+37h+12`、`2h²+2hN+41h+11`、`4h²+2hf+46h+f+11`。必须用实际官方模型实例验证这些公式及全部参数是否参与有效计算；S4 的复数表示按实标量计数，冻结物理、dead padding 和只用于凑数的参数不能算作训练容量。其他合法深度/state-size 组合可在相同容量带内按预先固定规则选择；“最接近参数数”本身不能保证该家族已得到合理配置。

相同参数数不等于相同记忆状态或计算量。普通双门控需要同样的 bank slot 数和 content width；六个不同家族的持续状态和成本仍要分别实测。

## 4. 全部所需消融的真实实现

当前五个读数是 `interval_value`、`risk`、`margin`、`expected_events` 和 `active`；`risk` 与 `expected_events` 在当前单步域重复。它们通过 likelihood、write gate、proposal、层间 message 和最终 readout 进入预测。

| 消融 | 最低实现要求 / 当前阻点 |
|---|---|
| Frozen vs trainable physics | 现在只允许固定默认值；四个可训练 raw 参数的合法取值范围不是数值资格范围。需要新的可训练域、梯度与轨迹误差门 |
| Call-only / Risk-only / Dual | 真正将所有相关 Linear 的输入与层间输出缩为 1/1/2 个读数，并删除 margin、active 和重复 expected_events 旁路；当前 call 仍是单区间工程值，不是 U |
| 同容量普通双门控 | 需要实际神经记忆 bank 更新、真实双门控和隐藏状态反馈，无 physical operator；不能给 HCSN 改名或仅加两个 scalar |
| All physical readouts removed | 将五个直接读数从所有路径删除；保留 `p,m` 的物理内容输运时，只隔离读数贡献，不能称为“全部物理已删除” |
| 有 / 无 reset | 可复用 `reset_enabled=False` 的 killed absorbing control，但必须固定吸收相位、事件/价值和内容写入语义并重新资格；不是随便跳过一次 reset |
| 分布 vs 仅平均状态 | 必须写明保留哪些平均量和 closure。均值不足以决定首达概率与边界流；不能用 `p.mean()` 充当物理平均状态 |
| 同生成元 vs 独立通道 | 真正保存两套独立 law/物理参数/时钟，定义内容属于哪套 law、如何融合，并记录额外状态与计算；当前单 law 的两个读数不等于独立通道 |
| 维护 / rollover on-off | 目前没有相关动力学。须先定义政策、维护年龄、成本、生成元变化和 reset/rollover 耦合，随后实现和资格；不能用一个无作用布尔量满足表格 |

建议用实际数据依赖检查证明剪除：在保持 transport 的 `p,m` 不变时，任意替换被删除的物理读数，预测应逐位不变。普通门控控制则应在 physical operator 被设为不可调用时仍能运行。这些验证检验了研究问题本身，不只是镜像一次实现。

### 下一最小对照的具体结构候选

在 K=145、content width=4、物理冻结时，一层 HCSN 的真实剪除计数是：五读数 9,804；单读数 8,584；双读数 **8,889**；零直接读数 **8,279**。最后两者相差约 6.86%，已超 ±5%，所以简单的三个臂会留下容量混杂。

建议下一次只做以下 **四个核心臂**，暂不重复六家 smoke：

1. HCSN Dual：仅 interval-value 与 risk，8,889 参数。
2. 普通双门控：145×4 的神经 bank，令 `z=[x_25, pooled_state_4]`；`Linear(29,24)→Tanh→Linear(24,290)` 生成两个 145 维 sigmoid 门；`Linear(29,4)` 加 145×4 slot embedding 后经 Tanh 得到 proposal；`h'=forget*h+write*proposal`。采用 144 个自由 pooling logits 加一个固定锚、4→11 head。静态计数 **8,869**，距 Dual −0.225%；没有物理传播，是真实带状态反馈的普通门控。
3. Content-only exact deletion：8,279 参数，保留内容物理输运，但删除全部五个直接物理读数。此臂明确是自然删减消融，不能称容量匹配。
4. Content-only matched：在第 3 臂加入实际参与预测的 `Linear(4,67)→Tanh→Linear(67,4)` residual MLP（607 参数），合计 **8,886**。它检验相同神经容量下内容路径能否解释收益；与第 3 臂分开，不能把“删除+容量重分配”说成单一纯删减。

以上仅是待实现的函数与静态参数设计，不是新执行结果。门控、residual、pooling 的定义、初始化、实际梯度、配置和 checkpoint 类型必须先锁定。四臂的比较会区分“两个物理读数”“物理内容输运”与“普通神经门控”；不能只比较 Full HCSN 与一个小得多的门控。

## 5. 数值准入的前置条件

新固定 `.2` profile 的 common-prior U、refinement 与未条件化 schedule 通过，并没有证明已训练过滤网络的误差有界。新 64/256 长度、不同 ABC/D 窗口或 trainable physics 均不能直接继承旧资格。

一个具体困难是：`ContentLayer.likelihood`、`write_gate` 的输出维度是 K，`state_embedding` 是 K×D。直接把 grid 从 K=145 加密，会同时改变已训练神经函数和容量；比较两次重训后的质量不是同一函数的物理离散误差。因此必须先实现以下之一：共同连续神经场，或明确的 coarse-to-fine lift，把同一组 likelihood/gate/proposal/embedding 作为同一个分段场映射到加密 grid。尾部和相位也须有相同语义的 lift。然后才能在相同数据、参数和观测条件下比较 transport、通道、内容和 logits。

必须先冻结误差限、实际 gap 集、初始 law、选定 episode、代表性与边界/尾部状态、source/profile SHA，以及观察更新后的检查方式。正概率、总质量接近 1 和 loss finite 只是接口必要条件，不能替代物理/任务读数的 refinement 误差。对已训练 checkpoint 的验证若失败，该运行保持不合格并保留成本，不得靠重新选窗口、减小 dt、clip 概率或放宽阈值改成通过。

可训练物理域还需覆盖 mu、sigma、boundary、reset 的联合变化及梯度。可选择先限制到一个新预声明的小域并资格，而不是声称四维全部开放范围已覆盖。当前折现、refractory 等固定项也不能在保留 episode 中暗改；维护耦合需要新的显式控制语义。

## 6. SNN 的充分训练与正式协议歧义

PLIF 当前 12 窗口中 8 窗口无脉冲，虽然 tau 和 surrogate 梯度可更新。这既不是现代 SNN 充分训练的证据，也不证明 SNN 做不好本任务。width=82 的等容量候选只修正了规模，尚未修正优化充分性。

正式前必须有：训练侧多类小集的 memorization 检查；逐层/逐窗口 firing fraction、膜电位和 tau 诊断；有限且可用的梯度；完整 train/dev 学习曲线；至少达到规定训练量并满足预声明收敛判据。持续静默、只剩 head bias 学习、未学会非平凡训练样本或预算耗尽，均应标记优化不足。不能强行用不合格 SNN 的分数为 HCSN 背书，也不能用任意强制非零 firing 阈值替代任务学习证据。

当前 12 候选只覆盖 LR×weight-decay×clip；相同数值网格不自动意味着各家得到合理训练。需要在固定总 trial 数和完整成本内预声明各家适用的搜索空间，包括 PLIF 的 tau/threshold/surrogate 或输入尺度选择，以及 S4 的参数组。不能在看到谁输以后仅追加某家的隐形调参。

D 同时承担配置选择、early stopping 和 temperature 拟合，必须把再利用写清。可以先按完整 D 序列固定 selection/calibration 分区，或使用明确的序列级交叉拟合；不能把在 D 上选出的最好配置再报成独立确认结果。最终 E 只计分一次，但其元数据审计历史仍公开。规范必须补齐 macro-F1 的固定 11 类与 zero-division、balanced accuracy 支持、Brier 归一化、温度拟合目标/界限和 NaN/缺类处理。当前指标脚本明确 Brier 平方和及除以 2 的版本，可作为定义来源。

五个确认种子只提供五个独立训练单位；数千 episode 不增加这个数量。一名 E 受试者和五条相关序列也不能支持广泛人群结论。模型之间可以共享 seed 对应的数据排列，但应报告配对差异及其有限样本不确定性，不把不同结构相同 seed 误当相同随机参数。

## 7. 为什么完整正式预算尚不能直接冻结

持久事件日志给出的 HCSN 128 个训练 events / 四次更新阶段为 **21.499、22.035、21.789 秒**，均值 **21.774312618 秒**。这里从 `fit_started` 计至第 4 次 `optimizer_step_completed`，含构表、前后向及部分 checkpoint I/O，排除了主要导入和 64-event 开发前向，但不是稳定吞吐测量。整个 HCSN worker 为 34.315–35.081 秒，启动约 2.9 秒。

仅将这个工作流按训练事件数线性外推，得到如下**量级情景，不能当成实测预算或性能预测**：

| 情景 | HCSN 单臂训练阶段量级 |
|---|---:|
| ABC 89,216 events，一个 epoch | 约 4.216 单线程 CPU 小时 |
| 一次训练，至少 30 epoch | 约 126.47 CPU 小时 |
| 12 配置×3 调参 seed + 5 确认 seed = 41 次训练，各 30 epoch | 约 **216 CPU 天** |
| 同样 41 次训练，各达到 100 epoch 上限 | 约 **720 CPU 天** |

原始算式与数据见 [cost-scaling-scenario.json](cost-scaling-scenario.json)。30-epoch 情景仅该臂就是 109,735,680 个训练事件；100-epoch 是 365,785,600。六家基础路线至少 246 次独立训练，核心消融还会增加。不能把六家都按 HCSN 成本乘算，也不能把其他五家当作免费。

这些数字尚未包括 D 的每轮评价、确认校准/E 计分、失败调参、消融、数值资格、数据/依赖与传输。32→256 的 BPTT 长度、尾段、等容量后各家实际速度和内存、学习物理的构表/AD 成本都未测；也没有假定能继承旧缓存、GPU 或其他 study 预算。S4 FFT 的 episode 成本与循环模型也不应简单按同一比例放大。

因此，用户授权已存在也不意味着当前 JSON 是一个合理的固定资源计划。必须先落实精确 arm registry、实现、context 和优化规则，再用已资格实现进行有限的无新增训练成本校准/静态计数，冻结每次 fit、每个 arm 的全部失败/调参，以及整研究的 wall/RAM/计量上限。达上限即保存并停止，不能把未收敛标成完成。

## 8. 下一最小可判别多类 pilot：先锁选择，再看标签，未启动

建议新建独立研究 ID，只运行第 4 节的四臂。一个具体、标签无关的候选选择是：ABC 各完整序列按 tick/原行排序，在长度 N 的序列中取起点 `floor(j*(N-64)/3)`、j=0,1,2,3 的四个 64-event 窗口；D 同规则；E 不作模型输入。这会固定 **3,840 个训练事件、1,280 个开发事件**，不会再只看最前面的 walking 片段。选定 row/tick manifest 必须在计算所选标签分布、训练或查看效果前写入哈希。归一化只拟合所选 ABC 训练事件；人工边界首 gap 原样保留，各臂都重置 episode。

随后只做一次覆盖验收：每条所选 ABC/D 序列合计至少 2 类，train 和 D 各至少 3 类，D 的所选类别须在 train 中出现；完整报告 11 类的缺失与计数。这是最小多类 pilot，不是全量 11 类确认实验。若任一条件失败，记录 `blocked_label_coverage` 并停止，不能换另一段或按照标签微调 offset。是否采取新的研究设计须另立版本，不能覆盖这次选择。

预先固定两个主要差异：Dual vs 普通同容量双门控；Dual vs 同容量 content-only。exact-deletion 作为容量变化已明确的机制消融。建议以 D 的原始 NLL 为主要 pilot 指标，同时给出固定 11 类的 macro-F1、ACC、Brier、ECE 和类别支持；不根据结果临时改主指标或忽略未覆盖类别。三种子可作机制与训练可行性 pilot，但不能升级为至少五种子的正式确认或统计等效性结论。

此候选也不是几分钟研究：沿现有 21.774 秒/128-event 情景，3,840 events×30 epoch 每个物理臂/seed 的训练阶段约 **5.44 CPU 小时**；Dual、两个 content 臂共 9 个物理 fit，训练阶段已约 **49 CPU 小时**，另加 D、普通门控、数值验证和失败。三个物理臂都保留真实传播，不能在成本上把 content-only 当成普通 MLP。新实现和数值门通过后才可能冻结现实上限；当前未将该情景当作资源预留或开启任务。

### 准入顺序与停止条件

| 顺序 | 应先产生的具体证据 | 不能满足时 |
|---|---|---|
| 1. 协议与源身份 | 新 study、四臂定义、数据 selection manifest、解释过的 E 历史、source/依赖/配置 SHA | 不开始 fit；不复用旧 smoke 完成数 |
| 2. 实现与容量 | 真删减、真实普通双门控、有效参数计数、路径独立性、AdamW/恢复与 episode 边界语义 | 保持 implementation HOLD；不加 dummy 参数 |
| 3. 数据覆盖 | 先冻结索引，后验证多类、无 subject/sequence/hash 泄漏、共同 frontend 与实际 dt | 覆盖不够即停，不换窗口、不改时钟 |
| 4. 数值适用范围 | 固定神经场的 refinement、选定实际窗口/观察更新、space/phase/tail/time/quad 与梯度检查 | 数值 HOLD；不 clip、不放宽容差、不借粗网格资格 |
| 5. 可执行预算 | 全部 trial/seed/失败的硬上限、恢复记录、完整成本字段和未知量 null | 预算合同未闭合则不启动；已有授权不需重问 |
| 6. 训练充分性 | 预声明训练量、训练侧多类学习、完整学习曲线与收敛、所有臂同一评价规则 | NaN/不变参数/无效学习/未收敛或到时保存失败，不判 HCSN 胜 |
| 7. 判别与后续 | 分析预声明两差异，公开所有种子和反例；物理读数收益须超出同容量普通门控与内容路径 | 无可靠实用收益则不进入 GPU/混合精度/语言预训练；有迹象也先做正式六家与完整消融确认 |

可并行推进的现在是四臂实现、统一完整数据索引、容量计数、训练/恢复/指标工具以及数值 lift 设计。真正训练要等待这些门按顺序闭合。本轮没有启动任何这些新 fits，也没有修改已冻结 source。
