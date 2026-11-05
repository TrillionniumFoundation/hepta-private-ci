# 下一阶段：真实双模态局部适配与动态控制的可判别小实验

状态：实施方案，不是实验结果。已实现的文本 adapter 接口与即将运行的单源真实更新，只证明执行、梯度、冻结和重载接线。不得把它们写成四组收益、自然任务泛化或完整训练范式验证。

## 1. 先决门槛与立即可执行工作

当前 run_real.py 的两条流程来自同一公开 bee 图片与 seed 17，属于一个来源的两次处理。已报告的 19.22/30.04 秒可用于估算 CPU 排期，不能提供有效样本量或效应估计。九次 VLM 输出相同、图像未体现 bee 的现象使语义输入链尚未通过；先完成正在排队的图像/指令干预诊断。诊断至少区分：输入文件是否改变、processor 像素/文本张量是否改变、冻结视觉特征/输出 logits 是否响应、语义任务是否正确。数值变化只是接线证据；训练/验证集上的独立正负控制仍需证明相关事实能被识别。

可以在该门槛未通过时运行单源 adapter 工程检查，但必须标注 visual_conditioning_verified=false。一次训练损失下降或记忆一个目标，不能使输入链门槛自动通过。不得用评估源来挑选“模型刚好会做”的题目。

立即可执行接口是 train_adapter.py：真实 VLM 每步图像前向，rank-4 FP32 输出头残差，原视觉/语言主干和 tied embeddings 冻结；processor 验证 assistant prefix 与完整序列的 token 对齐后，才对回答 token 做监督 CE。保存 safetensors、基座逐参数前后哈希、实际变化数量，以及同一训练输入在原 hook/重载 hook 下的 logits 等价检查。哈希、失败、保存、重载与两次检查前向均计费。图像 conv_out adapter 是独立接口：真实冻结 UNet 前向与监督去噪训练，性质另列。

## 2. 四组中的“生成器学习”必须限定到实际更新的参数

| 编号 | 控制器 | 生成器局部参数 | 能识别的处理 |
|---|---|---|---|
| 00 | 验证集选定的固定分配 | 文本/图像 adapter 均保持初始化值 | 共同基线 |
| 10 | 学习的 Hepta 控制策略 | 与 00 相同，保持冻结 | 控制训练程序收益 |
| 01 | 与 00 相同的固定分配 | 已声明的局部 adapter 学习 | 局部生成适配收益 |
| 11 | 学习的 Hepta 控制策略 | 同一声明的局部 adapter 学习 | 两种处理同时存在及其交互 |

若只通过文本真实更新，G 因子必须写成“文本输出 adapter 学习”，tiny-SD 始终冻结。只有图像更新也通过，才可把 G 定义成“文本输出头 + 图像输出层的局部适配包”。无论哪种，原视觉编码器、语言主干和扩散主干均未训练，不能简称整个基础模型共同学习。

每个 seed 的四组只从同一个训练前基座、初始 adapter 和初始 actor 分叉；优化器、经验、已训练 checkpoint、缓存与产物不在四个主组之间共享。参数值相同不等于可以复用一次物理训练事件当作四次独立训练。共同的、训练前的模型下载或数据准备可单列 setup，并在完整成本中只记一次。

如果 G 用监督 CE/去噪损失训练、C 另行学习，则 11 是模块训练程序的组合，不能称为共同净回报的联合训练。四组 interaction 为正也不能单独证明训练范式；非线性评分和组件兼容性本身就能产生交互。

## 3. 数据、单位与评分

建议初始完整小面板为 48 个事前登记的原始来源：24 train、8 validation、16 development evaluation；训练 seeds 为 17/29/43，每个 source×seed×arm 一次评估生成。三次训练种子只是小规模稳定性检查，16 个评估来源的区间也只能探索性解释。即使实际执行 192 个主组 episode，有效来源数仍是 16，不是 192。

当前只有一张 bee 图片，不具备此面板。可先建立具有独立原始来源与已复核关系标签的真实图片清单；若没有足够标注资源，允许预先生成 48 个独立 scene-seed 的受控几何图任务，保留真实 VLM 与真实扩散生成，但必须把输入分布写为“合成受控任务”，不得替代自然图片证据。渲染器只生成训练输入与评估参考，不得生成或修复被评分的模型输出。

原图、同视频帧、裁剪、重编码、增强和多个问题必须归属于同一个 source_group。先按 group 划分 train/validation/development，再产生变体。不同抽样种子、epochs 和生成重复都不是新来源。相同字节哈希可以拦住明显重复，但不能证明原始来源独立。

参考事实、关系与最终评分仅由训练/独立评估通道访问；actor、critic 的线上 view 不得包含 source 的正确答案、未来候选、评估分数或私有 descriptor。对受控任务，预先固定文本关系解析、图像对象/颜色/关系评分和联合一致性函数，并用正确参考与错误颜色、数量、位置、文本矛盾的负控制校准。不能由同一 VLM 的自评直接充当独立质量真值。不能在看到主组结果之后移动评分阈值。

保留失败、取消、超时、弃答、不完整产物的事前效用约定。失败不可删除。评估时每个已登记 source×seed×arm 都必须形成行；训练失败导致不可用 checkpoint，也需留下对应未完成评估单元和已支付训练成本。

## 4. 固定分配及三类强对照

主四组使用一个固定 F*，由共同训练前基座在 validation 上从登记的候选表选出，此后同时用于 00/01。候选必须包含不额外感知的 text→draft→stop、perceive→text→draft→stop、加 verify、draft 后 refine、以及 verify 后 revise→text→refine→verify→stop；选择依据是预先固定的同预算目标。这个主 F* 保证生成因子比较中的固定分配没有改变。

此外，对每个最终生成器条件重新用 validation 选择最强固定表 F*_G，作为主矩阵外的强对照，并计入选择费用。这样可以检查学习控制器是否仅胜过一个未随生成器适配重新调好的旧分配。重新调优不能使用 development 的真实候选结果。

先在 validation 检查 critic 与转移模型对实际后缀回报、失败概率和成本分布的校准，数据按原始 source 分组；拟合条件指数矩时应对应 log E[exp(−2R)|public state]，不能回归 E[−2R|state] 冒充同一目标。校准不足时保留误差与不确定性，不把 critic 当质量真值。

One-step completion VOI：在训练数据上拟合同一公开状态下的联合观察/成本规律；每个合法动作之后只接固定完成策略 F。风险目标使用 Qγ(s,a)=−log E[exp(−γ R(a→F))|s,a]/γ，其中 R 包含本动作、后续完成、核查与停止的全部随机费用及终局质量；不能平均条件 CE。若使用均值 VOI，则明确另列均值目标。比较同一目标的 STOP，执行一次实际动作后重新规划。不能把 actor logits argmax 改名为 VOI。不能为预测下一步先生成真正的未选候选而把费用隐藏；若实际生成了候选，必须收费且信息条件改变需单列。

轻量策略：对同一公开特征使用小型 logistic/线性分类器或预定阈值类，训练/阈值只由 train/validation 确定。特征可含已有计划/文本/图像是否存在、已到达 critique、历史和剩余预算，不得含最终真值。它的训练、提特征和推理均计费。

有限规划：使用与 VOI 完全相同的训练得到的联合转移/质量/成本模型，按同一指数矩目标搜索 2 层未来动作并接同一固定完成策略；只用预测分支，不查真实 evaluation 反事实表。搜索、critic、成本预测全部记入 planner/critic events。精确 DP 小模型不能静默替代这个不完美世界模型，更不能向规划器提供测试源所有未来生成结果。

## 5. 同信息、同预算与时间估算

所有方法共用同一公开 request、同一冻结输入处理、相同合法动作、同一输出版本失效规则、相同初始 STOP、相同 horizon 与预算上限。建议从 horizon=9、最多 2 次图像操作、最多 6 次 VLM 操作、相同 token 与扩散步数上限起步；这些是相同 API 工作配额，不等同于相同 CPU 秒。实际费用仍按执行记录计算。每个 episode 新建 backend，按 source×seed 块随机化组别/对照顺序，记录 cold/warm load 与运行平台；不让前一组的常驻状态免费帮助下一组。

训练主口径是同一“可用总预算”，例如每个 arm×seed 3600 CPU 秒的事前上限，以及相同训练源访问上限和 validation 查询上限；记录真实用量，不能强迫无学习组烧空转成本来凑等额。联合组的两组件不得各自额外领一份总预算。另一个“每组件相同更新剂量”口径可以单列，但其总训练成本可能更高。预算上限必须包含所有尝试、数据/模型校验、采样、失败、critic、规划、优化、checkpoint 与重载，而不只是 optimizer.step。

当前 synchronous 接口仅在操作边界检查 CPU/wall，不能称为抢占式物理硬上限。越界运行不能带着 completed/qualified checkpoint 进入同预算结果；必须作为该口径的失败/未完成项保留。最终计量回执自身与外层进程开销需由 runner 的完整包络封口，不能当作零，也不能与内层 exclusive intervals 重复相加。

主矩阵为 4×3×16=192 个评估 episode。若在两种生成条件下各加四类对照（重新调优 fixed、VOI、轻量、2层规划），再加 384 个；joint-vs-composed 诊断再加 48 个，总计 624 个评估 episode，另加训练、validation 和失败工作。按当前单源 canary 约 20–30 秒粗估，单机串行评估约 3.5–5.2 小时；实际新控制流可能不同，不能视为运行保证。按 seed/arm 在独立 CPU jobs 分片可以缩短墙钟，但不能隐藏总 CPU 成本或主机差异。先用 train/validation 预跑校准开销，再锁定完整 development roster；若资源不足，应保留未完成状态，不能缩短样本集后沿用原完整面板标签。

质量单位与 CPU 秒之间不存在自动换算。若需要净回报 CE，先固定服务目标所支持的 tariff/权重与成本单位；没有这个规范性选择时只报告同配额下质量和原始 CPU/wall Pareto，不能凭空制造 NDU 净收益。不得在 development 上挑选最有利的成本系数。

## 6. 旧 V3 可以复用什么，不能直接复用什么

可以复用旧 learning.py 的 actor_score_loss、critic_log_moment_loss、actual_suffix_returns 和 population_metrics：它们分别实现未自归一化的 gamma=2 矩目标 score loss、条件指数矩 critic、真实后缀净回报和 CE/mean 汇总。可复用 training.py 的参数分组、冻结审计、独立 seed、真实产物回读与预算记录模式，也可复用小 HeptaCore 作为 controller。旧 JointGenerator 的 16×16 四媒体合成模型及 utility 不能冒充现在的真实预训练双生成器。

要做严格的局部 joint-return 子实验，先只更新 actor 与真实文本 adapter，让扩散器保持冻结。将当前 deterministic describe 改为明确的采样文本法则，并对所有受 adapter 影响的 token 保留精确 log-prob；可以用保存的生成 token 在冻结主干上 teacher-force 重算这些分数。每次真实 episode 的控制动作 score 与文本 token score各算一次，使用实际输出评分减完整费用作为 detached return，再调用 actor_score_loss。adapter 不参与的感知/核查可以继续冻结。若任何受训练参数影响的生成分支仍贪心而没有合法梯度处理，便不能声称完整 score-law 联合估计。

图像输出层监督去噪是实际神经训练，但 tiny-SD inference_mode 的最终 PNG 不自带对 adapter 参数可用的 score。要让图像 adapter 也受同一终局净回报训练，必须另外声明可微外部目标/路径导数，或可计算且与实际采样完全一致的扩散随机转移密度。不能把旧 V3 的 Gaussian emission log-prob 直接粘到真实扩散输出上，不能把去噪 MSE 暗称为最终 CE 梯度。

保留一个明确的额外组成对照：独立训练的 controller-only checkpoint 与 generator-only checkpoint 只在“composed”诊断组组合，不回流污染四个主组。只有同信息、同预算下共同回报训练的 U11_joint 进一步超过这种分别训练的组合，才增加对联合训练程序的证据；仍只是所声明局部参数与数据分布的证据。

## 7. 结果归因与不能识别的结论

按原 source_group 和 training seed 成对保留四组，报告 mean 与 gamma=2 的各组 CE 后再作差：控制 U10−U00、生成 U01−U00、联合 U11−U00、interaction=(U11−U10)−(U01−U00)。不得改用 CE(U11−U10)，不得把不同 width/core 或不同成本定义的 CE 随意混合。source 与 seed crossed bootstrap 维持所有组配对；只有三个 seed 的不确定性须保留明显限制，不给确认性显著性叙事。

即使实验成功，也最多支持局部生成参数适配、给定分布上的动态控制、或严格限定的局部联合训练；不能证明完整基础模型训练范式、四模态统一优势、音画同步、跨帧实体一致性、长记忆或不可撤回流式交付。监督训练与 actor 的组合、同源重复、提示词搜索、训练损失下降、参数哈希改变、成功重载都不能单独补上这些证据。

## 8. 当前落地顺序

1. 完成输入链干预诊断；不通过则先修/更换合格输入链并保存旧失败证据。
2. 发布并运行文本、图像 adapter 的真实小步工程检查，保存冻结审计、梯度、重载、所有费用与失败；仍不做收益结论。
3. 冻结多来源数据、独立评分、训练/validation/development 分组、预算/成本口径与全部强对照；建立四组 runner 的完整 expected episode/event roster。
4. 先闭合模块适配四组；另登记 joint-return 子实验和 composed 对照，不能事后改名。
5. 全量执行预登记矩阵，失败项照留，以现有 factorial 分析器做已封口记录的归因。输入链、独立评分、成本封口或完整矩阵任何一项缺失，都保持对应结论未建立。

本方案依据当前 decision_audit/run_real.py、local_models.py、dual_runtime.py、factorial.py 与新增训练接口；旧训练损失和模型参照固定提交 c6773fcc3fe0520f58e0d5234713d60ecf246f31 下的 joint_hepta_20261029/learning.py、model.py、mechanism_data.py、media.py 和 joint_hepta_20261029/v3/training.py。方案没有生成新的实验收益数值。
