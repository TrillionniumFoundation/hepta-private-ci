# R9 任务价值、普通对照与边界功能：执行报告

本轮完成了实际代码修复、15 个新头训练、76,800 个配对策略比较、独立重放和真实边界干预。**结果不支持把 P0/P1 标为闭合，也不支持解析脉冲架构的独特性。** 新 continuation 头相对最新 R8 校准头改善了若干任务指标；first_passage 未通过预注册的全部 gate，普通 direct 通过本轮四项 gate，而且 R9 在新组合上的净效用仍低于历史 R7。固定公共 oracle 动作后的边界实验进一步显示，当前任务奖励提高边界、减少发放所省的手续费，没有质量或实际调用数收益。

## 1. 固定来源与交付边界

- 本轮训练依赖固定于 `333fb9b036b80cf5d892aed222a1aac7aad80e53`；26 个源码/checkpoint/FREEZE 文件逐字计算 Git blob SHA 并对照远端。15 个 R8 头按固定 FREEZE 的 SHA256 验证。来源记录为 `SOURCE_BASELINE.json`。
- R8 的15个头、R7核心/编码器、任务定义、成本、动作预算与期限均未修改。新训练/协议/证据在本目录，未对生产执行入口授权或激活。
- 新版 native owner 是另一条工作线。这里没有把 Python 的30维 R7 value 输入误称为 native FullHX 的内容输入或5维 causal_input，也没有声称已经完成联合边界训练。

## 2. 实际改动及其作用

`head.py::CostFactoredHead` 把已知当前动作成本从学习问题中移出。令 `g(x)=abs(2*posterior-1)`，`c_a` 为动作成本加延迟成本，`κ=.0005` 为每次决策的计算收费：

```text
Q_STOP(x,z) = g(x) - c_STOP(x) - κ
Q_a(x,z)    = g(x) + fθ,a(x,content,z) - c_a(x) - κ
fθ,a        ≈ E[V_after_action] - g(x),  a ∈ {READ, WAIT, REPAIR}
```

训练标签仍来自冻结 finite joint-state DP；后续价值包含后续动作、期限、预算、复位/不应期和发放手续费。当前事件已经发生在动作之前，其手续费由 `finite.targets` 的状态价值结算，而不是重复加入动作差。实际推理只计算训练权重，不调用 oracle、Q表或未来世界。

`PreservedNominalHead` 是预先登记的组合策略：原来673个18维公开输入的精确成员继续执行未改的 R8 头，其他输入执行新 R9 头。它不拒绝任务、不把拒绝当收益。原名义效用因此逐字保持；同时记录完全不路由的新头 `new_unrouted`，避免把路由保护误认成新头在名义域也更强。加载路径为 `deployment.cost.load_deployment`，支持集合在 `deployment/SUPPORT.json`；序列化沿用 R8 数值权重容器，必须使用 R9 的 `CostFactoredHead` decoder。

训练使用8个原名义 contract 加8个扩展 contract，共1362个公共状态。first_passage、clocked、direct 各5个原核心种子，均32隐藏单元、1091参数、2400次 L-BFGS 迭代 cap、同一损失与同一标签访问。所有fit都达到cap，不能说数值优化已经收敛到全局最优。direct 的17个潜态行与目标完全相同，因此只消除严格重复行，保持同一个加权目标，节省实际训练成本。

8个新参数组合在训练前列明，只作为本轮 primary blind。旧 nominal/drift/missing/cost_shift 是历史回归资料，不能重新当作未知发现。扩域与成本拆分一同改变，本轮不能单独识别两者的因果贡献。

## 3. 冻结、失败与修正

- 原注册 SHA256：`80c525b0804bf60cb97512d929394ad953f4232369e01046049e8266805ef0f8`。
- 15 heads 冻结 SHA256：`a15b381b3072c0c7e1b2b2f134f1b5b1ccb3dfd62c1cf21ac411f3019359f004`。
- 生效 amendment SHA256：`1ce613f50192aaa8342617830058f0c96b01765e22ada65ab9371b3c41e9caff`。
- 第一次确认的独立概率流审计发现评估器错误：drift覆盖参数后两个contract拥有同一个起点；NumPy赋值覆盖了重复起点，漏掉1/8初始概率。改为累加初始概率，并增加重复contract回归测试。训练DP、15权重、训练配方、seed、128个episode预算和门槛完全未改。
- 首次失败完整保存于 `evidence/confirmation_attempt01`；只完成first_passage11的历史名义1024个配对，随后在历史drift的R7核对失败，blind尚未评价。
- 旧START在归档后也留在原路径；第二次调用被single-use guard挡住，未进行数据计算。该拒绝及前一amendment保存在 `confirmation_start_guard_attempt02`。随后增加显式 `--output`，在全新 `evidence/confirmation02` 完成确认。没有删除完成记录或放宽检查。
- 4项机制测试通过，包括成本解码、STOP、完整路由、任务实际执行的到期限制和重复contract概率质量。记录在 `evidence/MECHANISMS.log`。

## 4. 新组合主验收：四项 gate 不能择优报告

以下区间采用预先登记的5个配对fit均值、Student-t、三family Bonferroni 98.333333%。效用与质量来自实际128 episode/contract执行；动作regret使用完整有限状态集合相对精确Q*的动作差。质量非劣界为−.02，计算价格为1效用单位/CPU秒，训练按10,000次部署摊销。负regret差表示改善。

| Family | 实际净效用 Δ及区间 | 全状态动作regret Δ及区间 | 正确率区间下界 | CPU计价效用区间下界 | 全部gate |
| --- | --- | --- | ---: | ---: | --- |
| first_passage | +0.059821 [+0.019145, +0.100496] | -0.013596 [-0.029281, +0.002088] | +0.013507 | +0.012360 | 未通过 |
| clocked | +0.027605 [-0.072009, +0.127219] | -0.011094 [-0.026954, +0.004767] | -0.040660 | -0.077416 | 未通过 |
| direct | +0.060949 [+0.026123, +0.095774] | -0.013253 [-0.022328, -0.004178] | -0.007123 | +0.025974 | 通过 |

first_passage 的5个fit在全状态平均regret上均改善，但预注册区间仍跨0，不能改成只看均值或更换统计门槛。其实际访问状态regret区间全为负，也不替换预先指定的全状态gate。clocked 的部分fit净效用退化。direct 的通过是普通对照在同一新协议下的结果，不是解析状态不可替代性的证据。

## 5. 三代基线必须一起看

下表为已知有限模型中独立概率流精确计算的期望净效用，按每个contract等权及5个fit平均，包含真实任务成本、每次调用费与事件费。它与上表的有限实际episode均值有正常抽样差异。

| Family / regime | 历史R7 | 最新R8校准头 | R9组合策略 | R9−R8 | R9−R7 |
| --- | ---: | ---: | ---: | ---: | ---: |
| first_passage / nominal | 0.629975 | 0.651265 | 0.651265 | +0.000000 | +0.021290 |
| first_passage / drift | 0.378789 | 0.352644 | 0.370101 | +0.017457 | -0.008688 |
| first_passage / missing | 0.521538 | 0.442277 | 0.557532 | +0.115255 | +0.035995 |
| first_passage / cost_shift | 0.546968 | 0.491410 | 0.544284 | +0.052874 | -0.002684 |
| first_passage / blind | 0.447259 | 0.370084 | 0.428130 | +0.058046 | -0.019129 |
| clocked / nominal | 0.633042 | 0.651220 | 0.651220 | +0.000000 | +0.018179 |
| clocked / drift | 0.379561 | 0.348888 | 0.371593 | +0.022705 | -0.007968 |
| clocked / missing | 0.522983 | 0.435519 | 0.555273 | +0.119754 | +0.032290 |
| clocked / cost_shift | 0.550057 | 0.521207 | 0.543516 | +0.022309 | -0.006541 |
| clocked / blind | 0.442708 | 0.360415 | 0.396090 | +0.035674 | -0.046618 |
| direct / nominal | 0.633481 | 0.652400 | 0.652400 | +0.000000 | +0.018919 |
| direct / drift | 0.379856 | 0.338619 | 0.368878 | +0.030259 | -0.010978 |
| direct / missing | 0.537662 | 0.512705 | 0.549564 | +0.036859 | +0.011902 |
| direct / cost_shift | 0.549681 | 0.509267 | 0.538362 | +0.029094 | -0.011320 |
| direct / blind | 0.449913 | 0.368285 | 0.428368 | +0.060083 | -0.021545 |

**恢复相对退化R8的损失，不等于超过最佳既有策略。** first_passage 的新组合R9=.428130仍低于原R7=.447259；direct也是如此。first_passage只有missing回归明显超过R7，drift与cost_shift仍低于R7。若把R7列省去，会误判研发价值。

名义域未路由新头的期望效用分别为 first_passage .648844、clocked .648323、direct .650055，低于各自R8；组合策略保持原名义性能的作用应与新头学习能力分开。完整Q误差、访问状态regret、quality、events、调用数与每个seed结果均在主 `RESULTS.json`，没有筛除失败fit。

## 6. 边界的真实任务功能：一个已执行的退化反例

在同一个公共状态oracle最优动作下，分别改变冻结first_passage的raw_boundary，保持任务输入、动作、预算和所有其他参数。五个fit各128×8个episode，比较原边界、提高raw_boundary 1和普通无cell对照，共5120组、15,360次实际执行。另对6个边界偏移做完整概率流计算。

| 边界干预 | 平均物理边界 | 期望事件次数 | 净效用 | 正确率 | 实际决策次数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| raw偏移 -2 | 0.504796 | 1.242136 | 0.653518760 | 0.8442125 | 3.003875 |
| raw偏移 +0 | 1.063067 | 0.817941 | 0.653603599 | 0.8442125 | 3.003875 |
| raw偏移 +1 | 1.460929 | 0.593397 | 0.653648508 | 0.8442125 | 3.003875 |
| raw偏移 +5 | 1.985388 | 0.345640 | 0.653698060 | 0.8442125 | 3.003875 |
| 普通公共策略、无cell | — | 0.000000 | 0.653767187 | 0.8442125 | 3.003875 |

所有边界条件与普通对照的task_return、正确与否、调用数在实际配对中完全一致；完整概率流中的quality、任务cost与调用数也一致。所有净效用变化严格满足：

```text
Δutility = -0.0002 × Δexpected_event_count
d utility / d raw_boundary = -0.0002 × d expected_event_count / d raw_boundary
```

原边界处五个净效用梯度均为正，范围3.3210e−5至7.9555e−5。使用实际17态upwind生成元的 `expm_frechet` 求导，并用.02、.01、.005三档中心差分核对；最细一档的净效用梯度最大绝对差8.05e−10。这是有限CTMC梯度核对，不是连续扩散或自由边界QVI的收敛证明。

这个结果支持一个具体判断：在该任务与固定公共最优动作下，边界提高净效用的唯一渠道是少付事件手续费。普通无cell对照达到更高净效用，同样完成任务；发放不改变观测获取、实际调用、任务质量或后续控制权限。因此本任务并未提供把边界训练成非平凡价值控制器所需的奖励结构。此结论不推广为任何物理/未知模型任务都不需要事件状态。

## 7. 成本与同信息普通对照

| Family | 五个head训练/标定/导出CPU合计 | 同一优化cap |
| --- | ---: | ---: |
| first_passage | 299.335316s | 每个2400 |
| clocked | 301.886431s | 每个2400 |
| direct | 10.935192s | 每个2400 |

完整训练campaign为612.206914 CPU秒；主确认106.332146秒；raw核对与重放3.177680秒；边界诊断14.587494秒。旧R7/R8训练是本次增量比较的共有沉没成本，不冒充重新计量。失败首次确认的进程CPU未在abort前持久化，保留其post-START单线程wall上界3.927214秒，不能把它写成实测CPU。

标量策略计时包住编码、cell转移、support tuple/hash查找、实际old或new head、task.step与记录。独立的10次平衡加载测量也包含双checkpoint读取/解析/数组和support集合构造：R8平均fit中位加载3.143ms；R9为6.785ms。673项support离线构造26.485ms。R9留存数值数组30,232B，support的Python容器/tuple/float约447,552B；这不是完整RSS，未把allocator或解释器内存伪装成零。模型import和统一provenance检查不在加载计时里，完整Hepta应用及durable owner成本属于其他实验。

`evidence/COST_LEDGER.json`给出全部已测计时、未测部分和补充startup收费情景。把support准备与增量加载也摊销后，三family的CPU计价gate方向均不改变；原注册结果未被替换。没有能耗读数，CPU秒不是能耗证明。

blind中R9 first_passage相对R9 direct的精确净效用差均值−.000238、区间[−.018064,+.017589]；推理每session多0.513ms，区间[0.458,0.568]ms。计入本轮训练摊销后效用差均值−.006519。两个模型的质量差区间很宽，不能把不显著差异当作已经证明等价；但本轮没有解析优势证据。固定公共oracle动作的无cell构造进一步说明，该任务本身没有给脉冲带来额外信息。

## 8. 审计覆盖与样本数量

- 76,800是三family策略配对比较数量，对应25,600组基础episode键；每对实际执行R8和R9，因此153,600次策略执行。不是把同一world在不同模型下重复运行当作独立效力样本。
- 对所有76,800对紧凑raw重算返回记账和fit聚合：记账最大差1.75e−16，聚合最大差4.00e−15。
- 对每个family/seed/regime/contract固定重放offset 0、63、127，共3600次策略执行；回报、正确与否、调用数和events完全一致，未出现guard fallback。重放是核验，不增加效力样本。
- 完整状态价值同时由后向DP与使用独立task.step世界枚举的前向质量流核对，严格1e−11上限。所有指标保留，不通过gate也不隐藏。

## 9. 下一步必须接通的具体接口

1. `experiments/analytic_event_neuron/round7/task.py::step`目前每个动作推进一个整数tick；`tools/hcsn/round8_20261031/value_calibration/finite.py::targets`每个决策都收COMPUTE，并在cell转移后选择动作。需要把观测到达、任务deadline、剩余预算和实际head调用时刻放入同一个执行转移，只有真实发生的调用才收费。
2. `tools/hcsn/round9_20261031/native/src/schedule.rs::Owner::interval`与`owner.rs::Owner::step/commit`目前先decode内容，再用外部`request.driver`推进cell。内容输出未成为当前R7任务posterior/预算/动作的受控转移；事件还没有决定是否调用任务策略。
3. `native/src/content.rs::State`当前保存model_digest、completed_reads、last(logits/packet摘要)。需要与`owner.rs::Pair`原子绑定TaskParameters/模型身份、任务posterior、remaining_budget、deadline、已支付cost、待到达观测以及策略/decoder身份；恢复后不能只恢复神经概率而丢失业务状态。
4. 当前R7头输入是18维公共输入+8维content+4维cell basis；native FullHX输出/5维causal_input不是这一接口。必须定义显式适配和逐状态前后值一致性，不能仅重命名向量。
5. 完成接线后，新的边界动作才可在等待、读取、修复、提交及事件触发实际调用之间改变可观察结果。随后对同输入、同预算的普通direct/门控进行新的冻结比较，并与R7等最强已知策略同时比较。当前blind已被查看，不能回调本轮头再称其为新盲测。

## 10. 执行命令与关键文件

以下是本轮实际执行命令记录。输出已冻结；复现实验应使用新隔离工作副本及新输出位置，保留本轮原件。

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.round9_20261031.value.run register
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.round9_20261031.value.run train
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.round9_20261031.value.run confirm --output tools/hcsn/round9_20261031/value/evidence/confirmation02
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.round9_20261031.value.deployment.cost
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.round9_20261031.value.audit.readback
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.round9_20261031.value.diagnostics.boundary
```

主结果：`evidence/confirmation02/RESULTS.json`；完整配对raw：同目录`PAIRED.jsonl.gz`；15个新头：`evidence/heads/`；冻结链：`REGISTERED.json`、`HEADS_FROZEN.json`、`AMENDMENT.json`；独立核对：`audit/RESULTS.json`；边界反例：`diagnostics/RESULTS.json`和`PAIRED.jsonl.gz`；部署support和加载成本：`deployment/`；成本口径：`evidence/COST_LEDGER.json`。

所有结论限于这套明确的已知有限任务、冻结核心和CPU执行器。实际收益是改善一个失配critic并暴露了边界目标的退化；这不是“全新脉冲网络已训练成功、五项验收全过”的证据。
