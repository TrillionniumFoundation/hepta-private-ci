# V9：训练期实体定位监督与两步关系组合的因子实验

本协议在 V9 初始化、编码、训练和新面板评分前冻结。V8 的关系资格与联合资格全败；
其旧题排序已好于固定阈值成绩，内部关系排序仍近机会水平，不能将问题归结为阈值。
现有记录没有端点定位轨迹，不能判定先坏在定位还是组合。本轮显式记录二者，
使用训练期 span／实体对齐监督与图状态传递的 2×2 因子对照，禁止推理期 oracle。

## 1. 共同架构、起点与四臂

种子固定 41、47、53，各自使用实际 V6 Bridge warmup 的冻结权重与来源。
旧 42,562 个参数完整复制，继续训练；不以 V8 最优末权重或失败 continuation 换起点。
新增模块统一为 2,322 参数，总计 44,884，四臂全部张量初值逐字节相同。
末输出层 weight 与 bias 全零；初始化概率须与共同旧核心一致，摘要与实测均保存。

| 臂 | 训练 span／实体对齐 loss | 新图状态 | 身份 |
| --- | --- | --- | --- |
| latent_chain | 权重 0 | 两 hop 连续传递 | 无定位监督对照 |
| grounded_chain | span 1、alignment .1 | 两 hop 连续传递 | 事前主臂 |
| grounded_reset | span 1、alignment .1 | 每 hop 从问题地址重置 | 组合对照 |
| latent_reset | 权重 0 | 每 hop 从问题地址重置 | 完整因子对照 |

所有臂保留旧 BridgeReader 三 hop；这里 reset 只干预新增图状态，不重置旧 Reader。
没有用破坏 payload 或改变参数量替代状态因子，也不在失败后更换主臂。

新模块七个参数张量为两个 `32×32` 矩阵 feature／metric、`4×32` queries，
以及 `6→16→2` GELU Head 的两个 weight、两个 bias；`2048+128+112+34=2322`。
原始公共 token 经旧 `project(LayerNorm_384(raw))`，再经新 feature、GELU、无仿射 LayerNorm。
四个 query 分别产生事实 source／destination 与 question／candidate 的 masked token 注意池。
地址经同一个 entity metric 后 L2 normalize，图状态初值为问题地址，隐藏维度 32。
每步 `A_i=masked_softmax(sqrt(32)*state dot source_i)`，
下一状态为 `normalize(sum_i A_i*destination_i)`；chain 传递下一状态，reset 每步改用问题初值。
图固定两 hop；新 Head 使用六个既定读出：新状态对候选／问题的 cosine、
前后状态 cosine、事实注意最大值、归一化熵、事实／问题／候选有效性，
仅最终新图 logits 残差加到旧三 hop logits。精确空 mask／数值边界随架构源码冻结。

模型 forward 仍只有六个公共特征张量，不读取实体字符串、role、span、支持句、标签或 gold 路径。
fact 轴是最多 62 个 content token 的 chunk；受控短句各一 chunk，自然长句可多 chunk。
这些是可学习的潜在角色和地址，不能直接称为完整实体解析器或长文本推理能力。

## 2. 数据、辅助监督与固定预算

保持实际 V7 diverse 训练成员与三条计划顺序不变：natural→augmentation→old。
自然训练 64 段／722 问／3,909 候选；旧受控 32 组／128 候选／64 配对；
新课程为同一 V7 augmentation 256 组／1,024 候选／512 配对，不按成绩追加新样本。
旧内部关系 16 组／64 候选／32 配对已暴露；自然内部 827 候选／194 问仅描述。
各种子四臂的样本、顺序、batch16、Adam `.001`、`foreach=False`、旧 depth3 与图 depth2 一致。
每模型固定 500 cycle、1,500 次优化更新、24,000 曝光；每流 8,000。
十二模型共 18,000 更新、288,000 曝光；各臂独立重置优化器，不承接 warmup 动量。
natural 使用最终二类 CE；两个受控流使用 CE 加 `.5×paired_margin`，margin=1。
不加教师蒸馏或旧输出锚定，不增加 Encoder、模态、长链或 NDU 控制。

辅助监督只用于两个受控训练流，来自公开语法中每个 mention 的 source／destination、
question object 与 candidate color 字符区间，不依赖候选正误或选中的证明支持句。
fast tokenizer 的完整无 special IDs 必须逐项等于冻结缓存 IDs；offset 与 chunk 必须对齐，
否则在神经执行前失败。多 subword span 使用预先冻结的归一化目标，不能按原始 BPE ID 判实体相等。
span loss 为目标 span 上的注意 CE；alignment 为共享 metric 上跨上下文同型 canonical entity 对齐，
温度 `.1`，权重 `.1`。相同上下文复制不能作为唯一 positive；无跨上下文 positive 的 query 跳过并计数。
canonical 类型／名称、位置、上下文去重规则与损失归约必须随训练 utility 和 sidecar 冻结。
自然案例无这项语法监督；latent 两臂可同算辅助诊断，但监督权重严格为 0，实际成本实测。
这是额外训练监督，不是仅靠答案标签自发获得定位；推理时不生成或传入这些目标。

冻结步数、顺序、资源上限与模型运行顺序。中途诊断不能早停、选步、选臂或调阈值。
即使主臂某种子失败，仍执行全部十二个预定预算；资源耗尽则保存部分成本与失败状态，不暗中续跑。
每模型训练完成先冻结固定末权重，所有十二模型均完成、完整记录后才作全局判断和新面板评分。

## 3. 两个新冻结面板

使用 `grounding_protocol.py`，数据种子固定 2901；每个面板 32 完整双世界组／128 候选／64 配对。

| 新面板 | 词表与解释 |
| --- | --- |
| fresh_combinations | 旧受控 train 词表中的新完整世界／问题／候选组合 |
| fresh_vocabulary | 受控训练未用的人名／物品词表，新完整世界；颜色仍共享 |

生成排除 V4 train/tune/final、V5 全角色（含 verifier_fit 和原 reserved fresh）、V7 augmentation，
按句序无关完整事实来源及 `sorted(facts)+question+candidate` 语义键排除，并排除彼此重叠。
语法独立重建标签与支持，随机句序；完整成员、角色、案例顺序、源／代码 SHA 在编码前冻结。
new-vocabulary 沿用 V5 reserved 的未训练词表，但世界／任务与它们不重叠；不是重新评分原 V5 域。
“新组合”只表示完整世界的语义／来源不重叠，不保证原子边或 object-person-color 三元组未见。
不声称词汇从未出现在自然训练或 Encoder 预训练中，不把重复种子视为新增独立案例。
两个新面板仍为两跳所有权→存储；更长链明确递延，原 V5 两个 fresh 域始终不用。
不读取官方 validation，不根据新面板的任何预测、定位或得分重新训练或选择。

全部十二模型末权重与数据／阈值／代码冻结后，才编码并一次性评分全部四臂与两个新面板。
旧 legacy joint 失败也不取消本轮事前指定的新面板诊断；新面板成绩从不反向影响训练。
先完成并保存全部十二模型×两面板的原始概率，再构造 `frozen_diagnostic` span 目标并独立评分；
目标不进入模型、不 teacher-force 图状态。之后24个面板各以 batch16 再执行8批完整辅助观测，
共3,072次额外候选观测，预测必须与原始同批概率逐项完全相等；这是重复测量，费用和次数另记。

## 4. 门槛与机制检验

旧 legacy joint 沿 V7 原条件独立报告：旧128候选与64配对均≥.95、降幅≤.05；
已暴露内部64候选≥.75、32配对≥.50；自然完整训练 F1m≥最佳常数+.05，
F1a≥同种子真实起点+.05，EM≥.05，概率 CE≤训练先验 CE×.95。
自然起点绑定同种子实际 V7 所存 V6 warmup 完整观测；历史复用不计新神经调用。
新面板资格不覆盖或改写这些旧门槛，不能以新关系成绩掩盖遗忘或自然学习失败。

主臂各种子在两个新面板都须 candidate accuracy≥.85、paired accuracy≥.75，
即至少 109/128 候选与 48/64 配对；三种子、两面板全部满足才记新面板资格通过。
固定保存概率 `p>.5`，相等判负，不调阈值；CE 使用保存概率并与 logits 训练 CE 分开报告。
各臂原始计数、全部失败原因、legacy/new-panel 两类资格分别保存，不能用均值抵消失败种子。

逐面板报告事实 source/destination、Q/c 的定位 top1、目标 span 概率、跨上下文实体 retrieval，
以及预测第一／第二次事实选择、完整两步路径与最终答案；gold 索引只用于评分，不作推理输入。
定位正确不能单独证明实体地址正确；retrieval、路径和答案是不同指标，不相互替代。
报告同种子 grounded_chain−latent_chain、grounded_chain−grounded_reset 及完整 2×2 interaction，
包括候选、配对、定位／路径指标与实际成本；所有三种子逐项保留，只作描述性机制证据。
若未在这些直接对照上稳定优于对照，不宣称已建立辅助监督或连续两步组合的收益。

三个主臂末模型在两个新面板各执行以下五种预定诊断，其他臂不追加此诊断：
图 depth1；图 depth2 每步 `graph_reset=True`；fact行连同mask反序；
沿 V8 SupportDeletedBank 删除两个独立语法核验支持句对应的整行；
沿 V8 public_value_permutation 对有效 fact 载荷按公共特征 hash 循环错配。
旧 Bridge 始终原三 hop、最终权重不重训，Q/c与原标签不改。
图步数／reset、fact反序和payload错配是公共输入／状态变换；支持句删除使用独立核验的 gold support，
仅为冻结后的诊断构造，不能称为标签盲干预，支持标注不进入原始预测 forward。
错配可能带回自身 payload，缺证据可能不可答；graph1/reset可能等价，须如实记录，
不能当两次独立复制。fact反序检查的是一致性，也不单独证明组合推理。
共30个新诊断面板／3,840次候选观测；不按成绩挑诊断、病例或额外步数，也不用于调参。

## 5. 审计范围与真实延迟

所有分类／配对更新保存原始 logits，独立重算；每个受控更新保存 span 概率／归约项，
以及 contrastive numerator／denominator logsumexp 等充分统计，以核验辅助 loss 的归约。
固定 old 前16候选与 augmentation 前16候选（各4完整组），在 diagnose0/100/200/300/400/500
保存全原始辅助向量与注意，供独立 dot-product／retrieval 复算；十二模型相同，不按结果挑 anchor。
全向量复算只覆盖该固定网格；不能称为所有训练更新的独立神经重放、梯度认证或完全可解释证明。

全部十二模型冻结后，对旧128的前1例和前2例分别测 batch1／batch2 的缓存 Head 推理延迟。
前2例为同一公共事实与问题的两个候选；固定 CPU FP32、thread1、eval/no_grad、旧depth3／图2与各臂模式。
每模型每种 batch 为3次 warmup加20次 timed forward；保存每次 CPU／wall ns 数组、median、p95。
p95 使用 `statistics.quantiles(n=20,method="inclusive")[18]`，
即20次排序后 `.95×第19项+.05×第20项`；median 为中间两项平均。
frontend batch 构造成本与 forward 分开；记录图支路实际分组数（前2候选2→1）及 batch 对独立执行的
最大概率差。batch2/2 是摊销吞吐指标，不是单例请求延迟；warmup与额外一致性执行全计入评估子进程。
这是已缓存特征的 CPU Head 延迟，不是包含编码的端到端延迟，也不是 GPU 或 NDU 收益。

完整子进程 CPU/wall/RSS、Encoder/cache/load、辅助计算、训练、面板与延迟成本分层报告，
函数内与物理 batch 是外层成本拆解，不再叠加；复用的 warmup、缓存、起点历史费用单列，不称免费。
未知 FLOPs 保持未知。新面板实测不自动授权 feedback、生产 Cell 分裂或改写既有阴性结果。
本轮不声称推理涌现、一般新任务学习加速、更长链、多模态或 NDU 净收益已经成立。
