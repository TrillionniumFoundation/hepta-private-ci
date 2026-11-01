# HCSN R13：联合分布、任务价值与实际执行的统一验证

日期：2026-11-01 UTC（2026-10-31 America/New_York）。

**本轮完成了可训练、可执行、可复核的研究实现，但没有通过“加入解析动力学带来能力增益”的主要验收。IID 的 D−B 显著为负；OOD 未证明改善，也未通过质量非劣门槛。** 因此不批准生产替换，不宣称保质量省算。

这是一条从 R12 冻结协议出发的独立 R13 研究实现。目录保留 `unified_cell_r12_20261031` 以对应协议和原始证据；实际扩展由 [IMPLEMENTATION.json](IMPLEMENTATION.json) 明确登记。审阅入口为 [PR #4542](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4542)。

## 一、工作定义如何落到代码

本轮采用以下定义：

> Hepta Continuous Spiking Network 保留内容与不确定性，由任务价值决定干预边界，以连续首达、存活和再生算子推进状态，并通过连续内容和事件流连接后续计算。

实际状态是 20 维联合概率，而非一个均值或一个 margin：

\[
p_t(j,h)=\Pr(\text{phase}=j,\text{content bit}=h\mid\text{已提供的因果历史}).
\]

其中有 8 个活动位置格、2 个恢复阶段、2 个内容类别。位置与内容的相关性保存在联合分布中。缺失观察和恢复中的 unavailable token 分别编码；actor 不接收 latent phase、未读符号、未来标签、teacher posterior 或执行中的隐藏状态费用。

| 用户要求 | 已完成 | 当前范围 |
|---|---|---|
| 标量 QVI 作为可验证起点 | 独立求根、旧例回归、value matching、smooth fit、QVI 与隐式导数检查 | 仍是旧的标量无限时域基准；不冒称新任务有同一条全局最优边界 |
| 准确传播进入实际训练 | 训练、规划与执行复用同一有限生成元构造、恢复及内容规则；完整概率状态参与训练 | 每个 fit 的规划共享 fitted Q，真实环境保持冻结的 true Q；精确性针对声明的有限 CTMC |
| 双通道有可区分工作 | 继续与复位的任务价值，独立改变不确定性、期限和恢复状态；保留普通双头及斜率匹配参考 | 当前任务没有产生到访的最优主动 RESET 区域 |
| 同一控制下检验 D−B | 八个配对 fit、强 GRU/SSM 对照、真实执行、完整统计与成本账本 | 主要能力与保质量成本门槛均未通过 |

实现主要位于 [cell.py](cell.py)、[estimators.py](estimators.py)、[recurrent.py](recurrent.py)、[task_value.py](task_value.py) 和 [data.py](data.py)。

### 1. 联合传播与再生

每个有限区间使用

\[
T_\Delta=\exp(Q_\theta\Delta),\qquad p_{t+\Delta}=p_tT_\Delta.
\]

下界吸收进入恢复阶段，保留当前 bit；恢复完成时，以 0.75 概率保留 bit，否则重新抽取公平 bit，因此最终同 bit 概率为 0.875。恢复期间的剩余时间继续推进，恢复完成后还能在同一区间内发生后续事件。累计事件数使用增广生成元，不把它限制为首次事件概率。

活动区间是 log-distance `[0, 0.8]`，上界反射；下界采用半格距离的吸收零密度面。恢复是均值 0.35 的 Erlang-2 过程。这个恢复分布、有限上界和网格都是模型选择，不能与确定性不应期或无界扩散混同。

完整 HX 财务核提供 boundary、equity、F、G 和 debt；三项可学习物理参数为 sigma、liquidity、maturity，另有 12 个 emission logits。其余六项财务参数固定。导数经过原有 Dual 算术链，再经过矩阵指数 Fréchet 导数。训练没有使用有限差分梯度或 spike surrogate；有限差分只用于独立核查。

“连续”也有具体边界：概率传播关于时间连续；reset 位置的线性网格插值分段可微，动作价值的 max 和最终行动选择仍有分段边界。代码在精确插值结点拒绝不唯一的普通导数，不能据此宣称整个网络处处光滑。

### 2. 任务价值决定干预区域

行动包括 STOP0、STOP1、WAIT、READ、RESET。READ 在区间末观察并支付实际 endpoint 费用；RESET 先把状态映射到恢复起点，再推进整个实际区间，固定费用为 0.04。所有继续动作均收取 `0.01 × dt` 时间费用。RESET 不会在内容保留规则上重复扣减。

两条任务价值通道定义为

\[
Q_{\rm continue}=\max(Q_{\rm WAIT},Q_{\rm READ}),\qquad
Q_{\rm regenerate}=Q_{\rm RESET}.
\]

STOP 单独比较。只有 RESET 同时优于继续与 STOP，才属于实际再生区域。有限时域任务的边界是 belief、剩余时间、预算和价格共同决定的区域，不一般等价于一个全局标量 `V_b`。财务核的边界参数与任务的最优干预区域在代码和解释中分别保留。

目标使用实际内容答对收益，加 `0.05 × equity/(principal+equity)` 的声明式 bonus；READ 费用由 debt 与 principal/maturity 决定，恢复态费用为 0.06。这是明示的合成任务，不是从金融论文直接推出的神经元最优性定理。

主训练损失仍是联合 posterior CE 加 `0.25 × 当前 bit 标签 CE`。任务费用、期限和复位后果已进入共同规划目标，但本轮没有直接端到端优化任务 utility 或 Qπ。

## 二、独立数值与机制验证

本轮最终 **47 项测试通过**，其中有 **69 个完整序列参数梯度差分检查**：HX 全部 15 个名义参数，GRU 与 SSM 每个参数块的抽样位置。序列包含 READ、WAIT、RESET 和恢复 token，检查了跨时间 BPTT、初始分布导数、Bayes 分母和完整传播链。

| 检查 | 结果 |
|---|---:|
| 旧标量 QVI 四例边界最大差 | 4.44e-16 |
| 标量六项隐式导数最大缩放差 | 3.91e-10 |
| 不规则时间 semigroup 最大差 | 4.16e-16 |
| 同均值、同内容后验、不同位置分布的首达概率差 | 0.257912 |
| 相同 phase/bit 边际、不同相关性后的 bit1 概率 | 0.552592 / 0.447408 |
| 正确 RESET→推进与错误推进→RESET 的状态 L1 差 | 1.895802 |
| 24 个固定切片中主动 RESET 严格最优 | 0 |

这些检查表明均值闭合确实会遗漏可影响后继的状态信息，也验证了复位顺序和剩余时间的必要性。它们本身不证明任务增益。

### 原生数值与网格误差分开报告

独立 C uniformization 覆盖 56 个 case，另有 6 个 case 使用 60 位 Decimal 参考：

| 路径 | 最大状态绝对差 | 最大质量误差 |
|---|---:|---:|
| C FP64 | 2.75e-15 | 1.15e-14 |
| C 真 FP32 | 3.38e-7 | 2.99e-6 |

FP32 误差没有被重新归一化掩盖。这项测试只覆盖导出有限生成元的传播，未给予完整财务核纯 FP32 或生产 Rust 准入。

另用独立稀疏实现对 512 格有限参考进行精化比较：

| 活动格数 | 四个固定期限上的最大首达概率差 |
|---:|---:|
| 8 | 0.00764658 |
| 16 | 0.00128632 |
| 32 | 0.00055236 |
| 64 | 0.00013794 |
| 256 | 0.00000659 |

512 格仍是数值参考；上界截断和恢复分布的模型误差没有因此消失。完整记录在 [grid_refinement_result.json](grid_refinement_result.json) 及 qualification 证据中。

### 双通道参考没有被省略

72 个公开 development 格点按固定 seed 分为 48 个训练、24 个留出点。普通独立线性双头只训练固定 20 次更新；margin-only 参考在锚点匹配两个值及局部斜率。二者不是主八-fit 比较的替代品。

| 通道参考 | A 留出 MSE | B 留出 MSE | 动作区域不一致率 |
|---|---:|---:|---:|
| 普通独立双头 | 0.00088910 | 0.00298440 | 4.17% |
| margin-only 匹配斜率 | 0.00701538 | 0.01879594 | 8.33% |

固定 margin、改变不确定性/期限/恢复状态时，精确继续与再生价值分别变化 0.142826、0.094119；margin-only 参考均不变。普通双头也能拟合相当部分结构，因此不能将这项表达能力归为 HX 独有。

## 三、冻结后的主四格确认

| 动力学/状态估计 | 固定 READ 控制 | 同一任务价值控制 |
|---|---|---|
| validation 选择的 GRU 或连续 SSM | A | B |
| HX 联合分布 | C | D |

每个 seed 的四臂共享完全相同的 fitted Q、emission、payoff、read cost、reset map 和 controller identity。初始 prior 相同，actor 只接收相同类型的 10 维原始信息。随机 tape 采用固定索引，以保证不同动作不会改变随机数消耗顺序。

八个 seed、三种核心各训练 20 CPU 秒，总计 24 次拟合；每个 fit 使用 384 条训练序列和 96 条验证序列，长度为 12。八个 seed 的 validation 选择均为连续 SSM，GRU 的模型和结果仍完整保留。HX/GRU/SSM 的名义参数数为 15/1636/1052；相同 CPU 与原始输入不等于相同参数数或归纳先验。合成世界也属于 HX 参数族，结论限于这个设定。

训练及共同数据准备的完整子进程 CPU 为 **494.924698 秒**，墙钟 **251.667710 秒**。训练超额均记录，最大约 0.0154 CPU 秒。所有原始历史、selected/final checkpoints、失败状态及选择依据已保存在 archive。

源码、模型、选择、数据 hash 在生成确认观察前冻结：

- 协议基线：`2f9104e5f0fc2802b093d04aeb42ea4bece21de7`。
- 冻结 manifest 的 source pointer：`5f1575cc280b26322daf084da27c6f7d38cbdaa6`。
- 远端候选与训练证据提交：`8b7cea658c70024012a36574b1e9e315d0105158`。
- FREEZE SHA256：`0d9c882950ff0c6c06970cf5004a6e537a78eb9c2c8bf9187cf2007a9a1a8fa9`。

每个 seed/domain 有 192 条确认序列和 128 个 paired episodes。合计 2048 个 episode tapes、8192 次四臂 rollout；统计独立单位始终是 **8 个 fit**，没有把 episode 当成额外独立重复。确认执行 CPU 为 9.180065 秒。

### 1. 实际平均效用

| Arm | IID | 不规则时间 OOD |
|---|---:|---:|
| A：SSM + 固定读取 | 0.725699 | 0.689352 |
| B：SSM + 任务价值 | **0.764713** | **0.731592** |
| C：HX + 固定读取 | 0.717887 | 0.694235 |
| D：HX + 任务价值 | 0.747679 | 0.729610 |

### 2. 全部预定 contrasts

以下区间为 paired-fit 的描述性 95% t 区间；主假设检验仅为 IID/OOD 的 D−B，采用 256 个符号向量的精确双侧 sign-flip，再进行两域 Holm 校正。

| Contrast | IID 均值 [95% CI] | OOD 均值 [95% CI] |
|---|---|---|
| B−A | +0.039014 [0.012258, 0.065769] | +0.042240 [0.012754, 0.071727] |
| D−C | +0.029792 [−0.000078, 0.059662] | +0.035375 [0.005011, 0.065739] |
| C−A | −0.007813 [−0.033938, 0.018313] | +0.004883 [−0.013570, 0.023336] |
| **D−B** | **−0.017034 [−0.027141, −0.006927]** | **−0.001982 [−0.014152, 0.010187]** |
| (D−C)−(B−A) | −0.009222 [−0.036907, 0.018464] | −0.006865 [−0.032235, 0.018505] |

IID D−B 的 raw p=0.015625，Holm p=0.03125，方向为负。OOD 的 raw/Holm p=0.703125。预登记的正向均值至少 0.01 且校正 p<0.05 的改善判据，两域均未通过。

### 3. 分布更准，没有转化成更高任务效用

| Domain/core | 联合 posterior KL | Bit accuracy | Brier |
|---|---:|---:|---:|
| IID HX | 0.00005076 | 81.68945% | 0.124165 |
| IID SSM | 0.00692171 | 81.84136% | 0.124520 |
| OOD HX | 0.00004989 | 81.19032% | 0.129013 |
| OOD SSM | 0.03991469 | 80.43620% | 0.135004 |

HX 的联合分布估计明显更接近同模型 teacher，尤其是不规则时间 OOD；但 IID 的 bit accuracy 和主任务 utility 均没有优势。这正是保留 D−B 的意义：不能用传播误差或 posterior KL 代替任务能力验收。

相同 fitted Q/E 的普通 HMM 与 HX posterior 最大差仅为 IID 2.22e-16、OOD 3.33e-16。两者是相同有限 Bayesian filtering 算子的两种实现，不能主张 HX 独有推断能力。

原始 hard accuracy 对 0.5 附近舍入敏感。确认后的固定数据重放核对了所有数据 hash，查到 IID/OOD 分别 34/50 个 HX/HMM 硬分类分歧，均距离 0.5 不超过 1.67e-16。原始准确率和主要结果没有修改；更稳定的 KL/Brier 以及分布数值等价仍保留。

### 4. 动作与实际费用

| Domain | B READ 总数 | D READ 总数 | B/D 主动 RESET |
|---|---:|---:|---:|
| IID，1024 paired episodes | 1255 | **1300** | 0 / 0 |
| OOD，1024 paired episodes | 1202 | **1231** | 0 / 0 |

本轮 D 实际读取更多。两种策略的完整动作路径分别在 13.67%/12.70% 的 episode 上不同。

实际效用差可精确拆为：

| D−B 分量 | IID | OOD |
|---|---:|---:|
| 答对率变化 | −0.01562500 | −0.00097656 |
| Equity bonus 变化 | +0.00015685 | −0.00013284 |
| 实际任务费用增加 | +0.00156593 | +0.00087309 |
| 最终 utility | **−0.01703408** | **−0.00198249** |

这里的任务费用是 READ/RESET/时间费用，与 CPU 成本不同。记录支持“动作边界发生变化、D 的答案及费用表现更差”，但不能单独证明哪一个训练或模型因素导致负差；简单统一减少读取也不是已经验证的修复。

## 四、成本验收没有被负向质量结果绕过

| D/B CPU ratio | IID | OOD |
|---|---:|---:|
| 仅在线执行：估计器、规划器、owner、设置 | 0.855537 | **1.181277** |
| 单个选中核心训练与共同准备摊销，加在线执行 | 0.988440 | 1.010211 |
| 登记的完整拟合/选择成本摊销，加在线执行 | 0.353478 | 0.357871 |

完整拟合/选择口径按 1000 episodes 摊销：A/B 包含共同 HX 模型校准以及 GRU、SSM 两个候选拟合；C/D 复用一次 HX 拟合，不重复计算。这个口径让选择与共同模型的成本可见，但其约 65% 的差距主要由这些训练项形成，不能解释为单次推理节省 65%。它也不是整个研究项目的累计成本或硬件能耗。

成本接受还要求同时质量非劣：对两域采用 Bonferroni 的 97.5% 单侧 t 下界，必须高于 −0.01。IID/OOD 下界分别为 **−0.027141、−0.014152**，均失败。因此两域的“保质量省算”接受值都为 false。

资格检查另记录 parent/child CPU 约 0.8265 秒，网格精化原始 CPU 9.6016 秒；这些离线共同诊断与主拟合/在线账本分开保留。所有计时都是实际 CPU 时间，不是焦耳测量。

## 五、对正在推进的 Hepta neuron 有什么帮助

本轮最直接的产物是可核查的状态与执行语义：联合状态保留什么、READ 何时可见、恢复何时结束、RESET 后如何继续、重复事件如何计数、规划器依据哪些因果信息作决定。这些规则现在有可执行检查，并进入了实际训练和 rollout。

对 neuron 实现，建议把本轮核心作为三类参考使用：

1. **状态传播参考。** 用分布、恢复阶段和内容相关性检查已有均值近似，尤其是不规则时间切分和多次事件。
2. **任务调度参考。** 将真实读取费用、期限和 reset 后果放进共同控制器，以实际收益验证停止/读取/复位决策；本轮 B−A 的描述性收益说明这项工作不必依赖 HX 专属动力学。
3. **证据合同。** 保留 model identity、原始符号边界、全部候选成本、固定对照与确认前冻结；不同实现只能在相同控制与信息条件下比较。

当前实现还没有替换 `codex-rs/hepta-neuron` 的生产状态机、定点表示或调度器。C reference 也不是生产 owner 集成。内容仅为一个动态 bit，不是长期语义向量或大模型能力；本轮没有完成多层语义网络的任务证明。

还有两项需要后续独立研究，而不能在本轮确认集上调到正结果：

- **任务目标对齐。** 主训练优化 posterior/label loss，实际验收是任务 utility。下一轮应预登记如何加入真实费用和实际 Qπ 的学习目标，同时给普通核心同样目标与预算。
- **可辨识性。** 本轮 flow 的 Q/prior 主要通过 sigma 和 HX boundary 两个组合变化。确认后的固定参数审计中，三项物理导数的第三个奇异值约为 1e-15；liquidity/maturity 没有被内容流损失分别识别。参数可求导不等于参数可独立识别，需要额外有效观测或明确减少自由参数。

这些是下一轮的假设与工程目标，不削弱本轮 IID 负向结论。主动 RESET 在固定切片和实际确认 episode 中均未成为执行动作，因此目前也不能声称再生通道提高了内容或行动能力。

## 六、复核入口与完整证据

- [FREEZE.json](runs/task_flow_r13/FREEZE.json)：源码、模型、选择和数据 hash。
- [SUMMARY.json](runs/task_flow_r13/SUMMARY.json)：所有 per-seed contrasts、检验、区间和成本。
- [TRAINING_SUMMARY.json](runs/task_flow_r13/TRAINING_SUMMARY.json)：24 fits 和完整子进程计时。
- [QUALIFICATION.json](runs/task_flow_r13/QUALIFICATION.json)：六类独立资格证据，含每个 native case 的向量。
- [POST_CONFIRMATION_DIAGNOSTICS.json](runs/task_flow_r13/POST_CONFIRMATION_DIAGNOSTICS.json)：明确标记的事后描述性动作分解、可辨识性和浮点 tie 审计。
- [训练证据 archive](runs/task_flow_r13/training_evidence.tar.gz) 与 [确认执行 archive](runs/task_flow_r13/confirmation_evidence.tar.gz)：完整 histories、selected/final checkpoints、逐 episode 动作/效用记录、模型身份和费用。

在仓库根目录复原并核对已有结果：

```bash
python -m pip install -r tools/hcsn/unified_cell_r12_20261031/requirements-numpy.txt
RUN_DIR=tools/hcsn/unified_cell_r12_20261031/runs/task_flow_r13
tar -xzf "$RUN_DIR/training_evidence.tar.gz" -C "$RUN_DIR"
tar -xzf "$RUN_DIR/confirmation_evidence.tar.gz" -C "$RUN_DIR"
python -m tools.hcsn.unified_cell_r12_20261031.campaign restore-data --output "$RUN_DIR"
python -m tools.hcsn.unified_cell_r12_20261031.campaign verify --output "$RUN_DIR"
python -m unittest discover -s tools/hcsn/unified_cell_r12_20261031 -t . -v
```

全部八组 NPZ 已通过独立复原检查，既验证数组 hash，也验证与冻结记录完全相同的 NPZ 字节 hash。已有确认目录有 STARTED guard，拒绝覆盖或重新冻结；新训练应使用新的输出目录。固定数据的复核重放不构成新的独立确认。

### 来源和集成记录

执行环境提供 NumPy/SciPy；PyTorch 与 Rust/just 当时不可用。因此实现采用独立核查的显式微分与 BPTT，并保留原 R12 requirements 与本轮 requirements-numpy 的区别。`just fmt` 实际尝试后因命令不存在未运行；没有修改 Rust 源码。专用 GitHub Actions `HCSN task flow R13` 已通过数值测试与 C audit。

本轮进行期间，原 R12 branch 并行产生另一套实现，且 IMPLEMENTATION、data、statistics 三个文件语义不同。PR 已改以固定协议分支 `research/hcsn-protocol-anchor-2f9104e` 为 base，保留双方各自的源码与证据；没有覆盖并行实现，也没有把两套结果混合。后续生产或合并集成需要单独变更与验证。

另有一项机械来源对账：[SOURCE_RECONCILIATION.json](runs/task_flow_r13/SOURCE_RECONCILIATION.json) 记录了上游 kernel 复制到本地时多出的一个末尾换行。准确的已执行 SHA256 在确认前已写入并提交 FREEZE；之后把远端文件字节补齐到该已冻结版本。没有修改执行源码、模型、输入或结果，历史 source pointer 和原始 FREEZE 均保留。

**最终状态：研究实现完成；主要能力验收失败；质量非劣成本验收失败；生产启用为 false。**
