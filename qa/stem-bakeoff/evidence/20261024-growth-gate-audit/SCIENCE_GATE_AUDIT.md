# Hepta 分裂、迁移与局部学习：六项科学门槛审计

审计快照：2026-10-24 06:55 UTC。此文审查已执行源码和已发布证据，并对已有逐例结果做离线算术重建。新增训练、Encoder 调用、模型调用、远端 worker 均为 **0**。没有重开任何封存测试，没有调整模型、路由阈值、目标或试验选择。本次解释是事后诊断，不是新的独立验收。

## 主要判断

目前确实存在可训练的私有参数、来源隔离的历史评估、实际分裂/合并/退役、完整状态恢复和有界的 NDU 正证据。它们足以支持继续研究这种架构。六项更强的科学门槛尚未全部闭合；现有结果尤其不支持把“复制 cell、连接节点、局部目标下降”直接解释成持续产生通用任务收益。

已有负结果涉及不同现象，必须分开：

1. **Smol 参数记忆 population 的分裂读出退化**：最初路由几乎拒绝全部支持的查询，掩盖了实际存在的专家答案；后来修路由可追回大量保留成绩，但未解决专家本身的迁移缺口。
2. **Real Cell Evolution V3 的历史 August 退化**：在固定两个槽位、匹配参数更新工作量的对照里，把 A/B 两个父体变成 A/A 两个子体，与分别继续训练 A/B 混合了不同初始化和保留知识。准确率三 seed 都下降，但降幅小、已发表区间都跨零，NLL 也不是三 seed 同向。
3. **p25 之后 PFT 的局部目标失配**：控制器把预定 J 降低，同时未来 NLL 变差。旧任务项是双侧平方跟踪，旧损失下降也受罚；这是已能从源码及保存结果直接定位的问题，不能把 J 的改善称为能力保留提升。

“迁移”还必须区分**知识迁移到新问题**和**checkpoint 在进程/节点间移动**。现有前者有负结果；后者在单机回环机制中反而有字节及输出一致的正证据。没有依据把语义迁移下降说成搬运 checkpoint 损坏。[E1][E2][E3][E4]

## 六项门槛：按用户原表

| 原门槛 | 已实际闭合的有限事实 | 反证、限制或未测项 | 当前结论与最小下一步 |
|---|---|---|---|
| **1. 单 cell 对未见任务收益** | 参数干预控制表明九个已写入合成事实的回忆确实依赖 adapter；p25 的 source-disjoint 小 Head 曲线确有随训练样本增加的有限提升；有限图文 pilot 的采样律内容收益通过原协议 | 已见任务族中的新来源、换措辞、后月份不等于未见任务族。p25 是一组 patch-shape 结构标签，PFT 是一个四类新闻任务；strong prototype、BM25/检索及先验有竞争力。本次 prefix/headtail 试验主 CI 跨零，不能充当本门槛成功 | **部分基础事实闭合，强门槛未闭合。** 下一轮先要求一个实际任务族的执行结果超过强检索/固定策略，并冻结 source/family 分割；新任务族泛化单列验证 |
| **2. 分裂对同等容量** | V3 确有两个私有子 Head、同槽位/活跃张量字节/参数×样本×步数/路由工作/选中 Head 次数的对照 | Smol 虽匹配总 adapter 字节和总 token，却不匹配活跃私有参数更新工作；额外梯度探测与路由成本另计。V3 更换父体来源、固定人工 partition，未证明自动分裂策略；August 反向 | **有执行与有界反例，收益未闭合。** 首先固定相同初始化池、相同两槽位，比较不分裂继续、随机分区、学习分区；强单体为单独成本前沿，不能把更多 token/活跃参数更新隐去 |
| **3. 相同 cells 下无边/固定/随机/学习边** | p25 的去重调度能保持预测并减少重复工作；pilot 在同内容、同 forward/critic 工作下胜 matched-random 动态路由 | query→expert 的选择器、32 个唯一状态的副本分发，都不等于学习 cell→cell 的信息边。未找到相同 cells、相同可用信息和预算下四种边条件的完整执行矩阵 | **完整门槛未测。** 先固定 cell bytes/状态与读预算，对四种边做一次冻结矩阵；单独区分“是否连接”与“连接是否学习”，且不能给无边基线更少输入 |
| **4. 局部更新对整体 NDU 及信用分配** | 57d2c7aa pilot 的内容训练、同内容随机路由对照有有限正区间；PFT 可保存/恢复 theta、Adam moments、时间/RNG/上下文且真实更新 | 原 v6 全 census 的 joint facts 全为0，32 CI 均跨0；新 FiLM competence probe 好转，但 fresh full census 未见发布终态。PFT 降 J 不保证未来 NLL；完整 optimizer state 与 credit assignment 是不同问题 | **有界正证据存在，整体信用分配未闭合。** 等候既有 owner 的新 census；未来将局部干预相对关闭/打乱信用信号的全系统任务效用、旧能力和完整成本作为同一验收，不把局部 surrogate 当全局 NDU |
| **5. 长期分裂+合并剪枝的旧能力/迁移/总成本** | V3 真正蒸馏合并、退役后0调用、回滚概率一致；typed lifecycle 有 correction/withdrawal/replay，并公开 correction 后一旧事实错误 | 只有短轨迹/一次结构循环；固定 decoder 的迁移 oracle 已有限，路由修复不足以克服。没有长期任务序列、多次成长/合并/剪枝后的净旧能力、迁移、累计加载/训练/废弃状态成本 | **机制部分闭合，长期科学门槛未测。** 先让单次更新有任务能力，再冻结有真实 drift 的顺序流与固定 checkpoints，统计长期遗忘、迁移、累计资源；不要先做大规模细胞增殖 |
| **6. 同一逻辑图单机vs多机，含通信加载恢复** | 单机两个独立 worker、认证 loopback、checkpoint 迁移/重启/旧 owner 拒绝有实际记录；PFT 12 次冷进程训练续接逐位一致 | 这些实验都不是两台物理机器的同图 A/B。物理多机排队/传输/冷加载/失败恢复与 full process-tree 成本未匹配；有主机资源不等于已有科学证据 | **单机工程子项闭合，所要求的跨机对照未测。** 固定同图同输入同模型 bytes，先做1机/2机无故障对照，再在相同 effect/request 身份与相同故障点做恢复；unknown/indeterminate 不算任务成功 |

表内“未闭合”不是“机制不存在”；“有界反例”也不意味着所有 cell 架构必然失败。证据范围见 [E1]–[E9]。

## 一、Smol population：拒绝路由、专家上限与不完全成本匹配

实际训练源码 `07df4a9cc385375cddded5b5e3b99632ce0652ec`，发布证据 `ac27a821bbfeb123bc55daca0b7432159ca3c9de`。三个 seed 使用同一 pinned SmolLM2-135M。rank-4 父体先训练512步；单体函数保持扩到rank-8后训练1024步；两个rank-4孩子分别从同一父体复制后各训练512步。每个来源访问16次，总训练 token 相同，候选总 adapter 张量均1,843,200 B。学习分区用64次来源梯度探测及依赖组约束。[E1]

### 现象和最可信机制

- 原路由保留结果是2/64、0/64、0/64；相应单体45/64、43/64、40/64。支持集覆盖率只有3.12%、0%、0%，这是**已观察的拒绝行为**，不是推测所有分裂后的参数都忘了。
- 同一组专家的 eligible oracle 却有61/64、47/64、45/64。说明一部分可用答案被路由丢弃。oracle 是使用真实结果的不可部署上界，不是可实现算法成绩。
- 后续固定 decoder 的 full-cross 路由诊断恢复到60/64、41/64、39/64，共140/192，高于单体128/192的合计。但两个 seed 仍低于单体，不能只报 pooled 正值。
- 对新问题形式/插值外推，full-cross 为15/96，单体20/96；lexical 为14/96。eligible-oracle event interpolation只有5/16、6/16、5/16，procedural extrapolation3/16、3/16、0/16。因此**冻结专家下没有答案时，路由优化不能产生答案**。
- full-cross 同时改变措辞覆盖、观测数量以及有效 reject-target 分布；balanced 控制减轻样本数混淆，却没有唯一定位“就是某一个措辞或类别先验”的原因。该诊断用的是暴露过的44-root合成 cohort，新生成不同wording不是新的未来验收。[E2]

### 哪些预算相同、哪些不相同

单体更新全部 rank-8 参数1024次；两个 rank-4 专家分别更新512次。用张量字节×被更新步数作透明代理：

- 单体：`1,843,200 × 1,024 = 1,887,436,800 byte-steps`。
- 两孩子合计：`2 × 921,600 × 512 = 943,718,400 byte-steps`。

因此单体的**活跃私有参数更新代理是2倍**。这不是硬件 FLOPs 测量：二者总 input tokens 和共享base前向主工作仍相同，而且 split 额外支付64个梯度探测及路由训练。现有对照不应被概括成“完整计算预算完全相同”。源码明确把router开销排除在adapter字节匹配之外。[E1 source]

两种控制不能混淆：在固定专家上做 uniform expected routing，不是重新训练 random partition 的 split。后来的3个自然CI incident小试验有随机/学习分裂，但只有三个已知来源的新措辞，exact-source retrieval也全对，不能承担稳定新任务迁移的结论。[E5]

### 加载与存储

跨目录新进程的一问回放保存了15项非耗时字段一致，generation约0.242s，整个fresh process约8.136s；这个差额包括导入/加载/启动等，不能直接全部命名为checkpoint加载。压缩checkpoint会解回FP32，不代表驻留内存等比例下降。把源文本、shared base、私有参数、索引/路由、optimizer、历史版本、加载及重试成本分开记账后，才可能判断是否真的更轻。[E1]

## 二、Real Cell Evolution V3：固定两槽位替换，不是净增长实验

实际执行关键三文件与提交 `a0a92fcbd2a688b948fca96cea16f6f41d6a2bd6` 的字节逐一匹配：

| 文件 | 执行 plan 内 SHA256 |
|---|---|
| `real_evolution_probe.py` | `b458dc3f4ba9d7640a11f3676787435d51d64808d08de0402190c80759c60deb` |
| `cell_evolution_training.py` | `b7720888b1218b3b37a3d9efec0a99f826df43c886a1c9a3202486ad96e1692e` |
| `cell_evolution_snapshot.py` | `5723614018bf8c4719cbcb87ceea51777ceadc13af3dcbe70da4076c5e114b2d` |

这里使用真实Granite97M共享Encoder，私有gated Heads和fresh learned Router。source-disjoint历史新闻中，March父体、May replay、June calibration，July/August/publisher-OOD最终评估；这仍是一个分类任务族。[E3]

### 真正被改变的变量

`split_snapshot(parent, "head_a", ...)` 从 Head A 初始化两个孩子，并**替换整个两个槽位 roster**；`continue_snapshot` 则A沿A、B沿B继续训练。两个分支都使用相同replay分区及router数据，100步head SGD、200步router训练、86,368 B活跃张量、175,379,200 parameter-example-updates、21,248训练/校准/内部报告Head/example calls，推理每行只调用一个Head。

所以“容量/更新不匹配”不能笼统用来否定V3，它确实比旧population更严格。但**A/B→A/A 的祖先初始化和知识多样性改变**与 split label绑定，无法单独归因于分裂本身。退役B可能减少知识覆盖是合理假说，还不是因果定论。人工固定hash分区也没有验证学习何时该分裂。[E3 source]

### 本次从原始逐例概率重算

原始 ledger 的69批中，33批是reload/mechanism/recovery，不能当新评估样本；只保留36批普通evaluation。ledger原始SHA `f92dced0699e7869a06010119e3a52ca1f803f880df0c223e38598ae30bda927`、report原始SHA `261a6cdf38f7dca84d8c9d561f67cf3d6d656da6ebeceb23560fa26c89a862f6`，均对上published inventory。全部重算accuracy/NLL与report相差<1e-12。

| 历史来源 | 来源数 | split−static准确率，3固定seed均值 | NLL差值，负为好 | split独有正确/ static独有正确的source-seed对 |
|---|---:|---:|---:|---:|
| July普通 | 128 | +1.8229 pp | −0.00528336 | 12 / 5 |
| August普通 | 96 | −2.0833 pp | +0.00943100 | 6 / 12 |
| July publisher holdout | 48 | +3.4722 pp | −0.05479535 | 8 / 3 |

August每seed准确率差分别−2.0833、−3.1250、−1.0417 pp；原发表各自95%描述区间分别[-7.2917,+3.1250]、[-7.2917,+1.0417]、[-6.25,+4.1667] pp，均跨零。NLL差为+.019099、+.021421、−.012227，只有前两个seed变坏。这是**保留负方向和不确定性**，不是宣判总体统计显著退化。

三seed没有同一个August故事都成为split独有错误。slotassignment分别改变15/19/19个，ledger只保留被调用Head的真实输出，没有未选专家counterfactual输出；因此不能仅用此ledger把退化分解成“路由错了多少、专家遗忘多少”。重复调用模型补齐矩阵属于新实验，本轮没有做。

按类别的事后切分还表明：August class0准确率差−5.56pp但NLL略改善；class3准确率差−2.78pp且NLL变坏。这进一步说明校准/决策边界/迁移不是同一个指标。这些切片只用于解释已暴露结果，不选择后续题目或超参。

### 已修复但不能误报成能力修复

V3修复了training wrapper在冻结module上留下gradient buffers的问题：adoption重新加载已保存NPZ，inference拒绝残留梯度。55个NPZ及完整prediction ledger与V2逐字节相同，证明资源生命周期修正保持行为；**它没有改善August成绩**。新merge是真正调用两个teacher再训练student，retire后0Head/Router调用，rollback恢复旧概率，说明机制有效，但仅一段短结构轨迹，不是长期自组织收益。[E3]

## 三、p25 与其后 PFT：成本和目标的真正进展

### p25 的可用进展及边界

p25报告发布在`4b3081c...`，实际执行源是p24 `9b1f52cd...`。1,728个实际训练Head、有来源分组隔离、不同budget、fresh-process reload，是对“参数有没有真的学”的有意义进展。Gated8→128的历史balanced accuracy曲线有正增益；但128预算下Gated相对Linear很小且CI跨零，prototype还具有竞争力。这个事实应与“完全没学习”区分。8→128同时增加每步使用的样本数；源码每步对全部训练行求梯度，`example_updates=steps×training_rows`，因此该曲线不是固定总训练成本下的免费提升。[E6]

1024 physical cells 的dispatch优化实际对应**32种不同learned state的副本**。按完整state去重后预测逐位一致，避免重复计算，是真实工程优化；不是1024种新能力自发出现。physical top-k 还出现replica crowding；按state分组会缓解，默认all-unique scatter保全覆盖。它证明冗余和路由实现能损害效率，未证明新连边创造任务收益。[E6]

p25长issue在192-token窗口下大量截断，确实是输入诊断线索；但我们后续严格matched prefix/headtail试验的主准确率差约+.945pp，CI[-1.535,+3.579]pp，未建立收益。不能看到截断就断言“只要修输入便能修分裂”。该试验的一次checkpoint prefix加载失败被strict guard在forward前拦住，后续132个F32 body tensor逐bit校验解决的是加载正确性，不是任务能力或cell分裂收益。[E9]

### p25之后已经完成的新PFT栈

最新PFT #3655–3661不是设计草稿：执行源`87641f069a7830b46fdeaaf34d417635c5f5d463`，证据提交`ff5baef731f36420370c5bcc049c50a567cda06a`，60/60条件完成、0失败；6个warm-start模型，不能写成60个独立任务。它冻结Granite97M并把384维特征预先无标签投影到8维，控制36/52参数的Head。结论限定在此小Head，全批次确定训练Q=0。[E4]

完整状态保存theta、Adam一二阶矩、step、RNG、sampler及上下文身份；12次冷进程完整/中途重放的状态和动作逐位一致。这个修复使“局部训练状态”可验证，比仅复制weights更完整。但这不是全图信用分配的验证。

最重要的目标问题可直接代数化：旧项原为`[L_old(x)-L_old(reference)] - [L_old(initial)-L_old(reference)]`，相消后就是`L_old(x)-L_old(initial)`；平方同时惩罚变好与变坏。`zero`基线仍执行普通Adam，不能叫“不更新”。

本次对published per-run审计记录再聚合（不是二次逐NPZ独立审计）得到：

| all/loss2−zero | Linear | Gated |
|---|---:|---:|
| current probe NLL | −.0210164 | −.0157327 |
| old probe NLL | +.1060929 | +.0557740 |
| J | −.0285727 | −.0146787 |
| tracking降幅来自旧项的份额 | 98.937% | 98.302% |

`loss2`比myopic的J在12/12配对更低，但all/Linear未来May NLL差+.008947，CI[+.004752,+.013815]；June+.006273，CI[+.001174,+.011765]。GatedMay+.002000，CI[+.000124,+.003916]；June区间跨零。正确表述是**本目标控制改善不等于外部任务改善**。探针规模、8维投影和月份分布等仍未单独消融，不能宣称全部外部退化已被一个机制因果解释。

`extended`在12/12配对J更差，也不构成“更多信息一定有害”：各自投影后求出的Riccati策略不是嵌套最优策略类。`full`只对同动作、同目标、同切线数组最优，不是原非线性训练或global NDU最优。[E4]

### 修复状态不能与新收益验证混写

| 已发生的修复/变化 | 已有验证 | 尚缺的验证 |
|---|---|---|
| Smol crossed-wording router | 固定decoder的完整专家矩阵，保留成绩追回；另有19,379项独立算术比对 | 新来源、新任务、同完整成本的迁移收益；原专家能力上限仍在 |
| V3丢弃残留gradient buffers | 55个NPZ及完整ledger与V2字节一致，实际inference拒绝梯度 | 该修复没有新的质量收益；长期内存/allocator/full RSS仍未匹配 |
| p25唯一state去重及replica-aware路由 | 有实际服务计时与输出一致性；默认全unique保覆盖 | 不是新能力；未在一般异构大图/通信故障下确认这些倍率 |
| p25 prior/temperature校准 | 已冻结模型的既有输出上重算，NLL下降 | balanced accuracy接近先验；不算新的表征或新任务能力；温度上限命中不能冒充独立确认 |
| PFT保存完整Adam状态 | 12条实际冷进程训练重放逐位一致 | 本轮Q=0；随机流、多机/长期续训、局部到全图信用分配未测 |
| NDU FiLM+LayerNorm条件绑定 | validation-only 6项competence gate、legacy兼容与输出重现 | 新conditioned full census尚未发布终态，不能提前报future收益 |
| 本次LFM native checkpoint prefix严格加载 | 132个F32 body tensor逐位一致，匹配输入预算的实际试验完成 | 任务主CI跨零；没有分裂或agent任务收益验证 |

## 四、NDU #3622：最新终态核查

截至上述快照，PR仍是`b98961ceb71414490e1c6ae397cf635bca3093f4`，GitHub更新时间2026-10-24 06:14:18Z。正文明确新的conditioned 7,560-row census **running**；同SHA的`v6/results`只有旧`full-001`、`replay-001`、`competence-001`、`command-film-001`等，**没有新的conditioned full终态**。这表示未见发布完成证据，不推断owner机器是否已经运行结束。[E7]

- 原完整运行`cf3bc202...`：所有arm的joint fact correctness为0，32个contrast CI都跨0。
- `befeb286...`exact replay保持7560轨迹及15120媒体完全一致，改了执行成本，没有新增质量样本。动态risk-aware complete-row约454.334→62.250ms，fixed约22.935ms，动态仍约2.714倍。
- validation-only FiLM+LayerNorm修复到52/64 supervised、54/64 NDU，6个competence gates通过；这是新full实验的前置资格，不应先行当fresh future验收。
- 不应由上述负结果抹掉2026-10-23 pilot：执行源`57d2c7aa...`的finite sampling law中，NDU−supervised效用+.020926、CI[+.011638,+.032925]；同内容、matched-random动态对照+.043656、CI[+.021470,+.070240]。它是真正的有界正证据；不涵盖greedy准确率、自然图像、同硬件时延、长期交互或一般NDU/FBSDE。[E8]

## 五、下一步：先从已有证据获得能回答的问题

### 本轮已完成且不需要新模型

1. 逐例重建V3所有普通evaluation accuracy/NLL、配对wins/losses、已发表CI、路由slot分布及类别切片；已排除重复批次。
2. 将实际执行源码三文件与plan哈希及immutable commit逐字节绑定；原始/压缩ledger与report双层哈希核验。
3. 重新聚合PFT每条运行的objective分项，明确old项的贡献与外部未来结果分离。
4. 从Smol训练调用明确区分总token、总adapter字节、活跃私有参数更新代理与路由/探测的额外工作。

对应可重复脚本`reanalyze_published_evidence.py`与`offline-diagnostic.json`只读保存数据。没有执行项目模型代码。

### 能继续离线做、但不能声称当前已做的诊断

- 对population已保存的per-expert完整矩阵重新区分：共同来源资格下的专家互补、router regret、reject/unsupported tradeoff。应按原source dependency groups计数，不把wording当独立未来。
- 对PFT保存的raw states计算单侧遗忘等新指标只能是**事后objective诊断**；不能在已暴露May/June上重选控制器，不能用新指标替换冻结验收。
- 账本按common sunk setup、每个candidate训练与选择、每次load/调用、通信/恢复、历史版本存储拆分。墙钟重叠段不能相加；零调用有实证才记0；缺失energy/RSS不能填0。

### 最小下一轮严格对照：在新数据上冻结后才执行

第一步是**可用任务能力**，不是立即扩大meta network。选真实来源组和实际可执行任务结果，固定单cell强retrieval/固定策略、未更新cell及学习cell；先验证学习后真实收益且旧能力守住预定界限。以已暴露样本调好的任何选择都必须在新source/family组确认。

若这个门槛通过，再做两槽位的最小析因：所有分支从同一祖先/同一初始化池开始，同一回放源和窗口；固定partition continuation、随机balanced partition、learned partition；另加A/B保留与A/A复制的初始化控制，避免把丢失B误叫split effect。强single同总容量单列，并预先声明token匹配与active-parameter-work匹配是不同预算层；实际共享base、router/probe、load及wall成本全部记录。**不要在数学上无法同时相同的量上宣称完全相等。**

对edges，冻结同一批cell及状态，只有边策略变化；给四条件相同外部观测与总消息/调用预算，分别报零边、固定边、固定随机边、训练边。对于知识流作用，应保存全部实际消息和至少预定诊断样本的候选输出，而不是仅保存最终所选专家。诊断额外forward计费且不进入线上预算优势。

局部信用分配与PFT修复需要先冻结**不奖励撤回改善**的保留约束（例如非劣界或单侧遗忘惩罚），任务NDU由外部结果和完整成本计算。新目标应在未开的source组评价；旧May/June保持原结果。控制器内部J、实际任务效用、旧能力分别报告，不能合并成一个“学习成功”标签。

最后才延长为有多次split/merge/prune的顺序流，以及同一逻辑图的物理1机/2机实验。固定request/effect身份、故障点和恢复语义，记录完整进程树、冷/热load、通信、失败浪费和尾时延。主机数增加或节点连接成功本身不作为通用智能证据。

## 固定证据链接

- **[E1] Smol population**：[发布证据](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/ac27a821bbfeb123bc55daca0b7432159ca3c9de/qa/stem-bakeoff/evidence/20261023-memory-population)；[source：实际training调用](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07df4a9cc385375cddded5b5e3b99632ce0652ec/scripts/memory_cell_population/population_training.py)。
- **[E2] 固定decoder路由诊断**：[完整README](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/evidence/20261023-routing-diagnosis/README.md)；[独立逐记录复核](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/evidence/20261023-memory-independent-review/README.md)。运行repo `d61a36e...` 加五个冻结driver模块，不是拿后续格式提交冒充执行源。
- **[E3] Real Evolution V3**：[证据目录](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/evidence/20261022-real-cell-evolution)；[source：split/continue](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0a92fcbd2a688b948fca96cea16f6f41d6a2bd6/qa/stem-bakeoff/cell_evolution_training.py#L258-L338)；[source：实验调用与匹配](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0a92fcbd2a688b948fca96cea16f6f41d6a2bd6/qa/stem-bakeoff/real_evolution_probe.py#L340-L390)。
- **[E4] 新PFT执行**：[完整报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff5baef731f36420370c5bcc049c50a567cda06a/qa/stem-bakeoff/evidence/20261024-cell-parameter-field/README.md)；[raw/audit/结果](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/ff5baef731f36420370c5bcc049c50a567cda06a/qa/stem-bakeoff/evidence/20261024-cell-parameter-field)；[执行源目标构造](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/87641f069a7830b46fdeaaf34d417635c5f5d463/qa/stem-bakeoff/cell_field_run.py#L239-L247)；[执行源cost](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/87641f069a7830b46fdeaaf34d417635c5f5d463/qa/stem-bakeoff/cell_field_control.py#L27-L35)。
- **[E5] 小型自然CI来源和typed生命周期**：[domain报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/evidence/20261023-memory-domain-development/README.md)；[typed生命周期、保留失败与单机网络](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/evidence/20261023-typed-cell-lifecycle/README.md)。
- **[E6] p25报告，执行源p24**：[stage25](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/evidence/20261023-cell-next-stage/README.md)。
- **[E7] NDU v6快照**：[固定结果目录](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/b98961ceb71414490e1c6ae397cf635bca3093f4/experiments/multimodal_output_portfolio/v6/results)；[PR3622动态页面，仅截至本文读取时间](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3622)。
- **[E8] 有界正pilot**：[执行报告，源57d2c7aa，后续证据发布](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/99001f4ac6598914b26f66de977e190341c51dbc/qualification/joint-generation/runs/codex-cloud-20261023-r1/REPORT.md)。
- **[E9] 本次input coverage试验**：[PR3663](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3663)，审计已知head `59a725f78a3bf627dac2d17c1075e5d1ef4faaf7`，执行源`c3eb451a8b2bb18d2f2011989d346223ef08ca6e`；仅四个结构标签的历史来源对照，非分裂、agent任务或AGI收益实验。
