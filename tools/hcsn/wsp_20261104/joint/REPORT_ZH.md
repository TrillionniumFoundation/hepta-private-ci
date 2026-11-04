# Hepta Neuron 最新实证审计与真实 Checkpoint 末层编辑实验

日期：2026-11-04。范围：`TrillionniumFoundation/hepta-private-ci`。GitHub API 已核实该仓库的 visibility 为 public，不能从名称推断它是私有仓库。这是子任务研究报告；未修改任何运行中模型、未提交 GitHub。主代理负责 HeptaRuntime Rust 集成与最终发布。

## 结论

已经从发布的原始模型归档取出五个 renewal 模型及其原 train/validation 数据，验证归档 SHA256 和每个模型 SHA256，对真实的三个 Continuation Q 末层完成闭式参数编辑。使用 320 个新生成的公共世界、独立有限环境解析器和原 TRAIN 拟合的译码混淆矩阵计算期望任务价值。闭式编辑、同一末层梯度下降、等范数随机编辑、无编辑、WAIT/READ/REPAIR 单通道消融均实际运行。

**结果不支持“已显著优于传统训练”或“已闭合 Hepta Neuron 的任务收益问题”。** 闭式编辑平均 IID 增量 +0.01418、OOD +0.02693，但以五个原始训练重复为独立单位的 95% 描述性区间都跨零。梯度末层基线接近；经相同验证选择的随机编辑在 IID 的均值反而更高。五个验证集都接受的编辑中，IID 与 OOD 仍各有两个 fit 出现退化。原始科学结论应保留为 OPEN。

可以独立验收的实际成果是：**真实已发布权重上的冻结特征凸子问题可通过闭式参数更新快速求解；它改善了共同留出状态集的 Q 拟合，并提供了 Rust 可复核的真实输入及期望参数；末层拟合质量、策略价值和全模型收益仍是三个不同验收项。**

## 1. 最新源代码与证据身份

| 研究线 | 固定源代码/结果版本 | 直接证据 |
| --- | --- | --- |
| 默认 main | `732e934ba496d90fbe042b8d41d479ef901643e5` | [main 固定提交](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/732e934ba496d90fbe042b8d41d479ef901643e5)，默认分支没有自动包含研究 Draft |
| Digital joint 最终审计 | `5b69a046d886cf4c2a73c50e58197360ea15d8f5` | [PR4650](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4650)，[STATUS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5b69a046d886cf4c2a73c50e58197360ea15d8f5/tools/hcsn/digital_joint_20261102/STATUS.md) |
| Digital joint 原训练源代码 | `36e9ddd099e09688593bccf2c32d1dfabc39ac99` | [归档分片清单](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5b69a046d886cf4c2a73c50e58197360ea15d8f5/tools/hcsn/digital_joint_20261102/evidence/JOINT_TRAINING_PARTS.json) |
| 原模型冻结发布 | `8977e83d89fc0b2e7e74c2ed6f025adb096f5dfc` | [MODEL_FREEZE](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5b69a046d886cf4c2a73c50e58197360ea15d8f5/tools/hcsn/digital_joint_20261102/evidence/JOINT_MODEL_FREEZE.json) |
| R22 综合研究 | `b35dc241271a111c27b1a5fea72ad0112b43cd1a` | [PR4618](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4618) |
| V13 joint-content 源代码 | `1a8f0b22e318bf919050f76b52a9c5feb5521ce9` | [PR4619](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4619) |
| V13 最终综合结果 | `3b9a136c56e9e743d7ecba852d621e1ecabf6bba` | [PR4658](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4658) |
| 更早 terminal/feedback 修复 | `5ed5d87123b2aa66d4939e111821922ebc7fa3f0` | [PR4591](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4591)，25 模型、10,000 episodes，0/14 校正门通过 |

最新按更新时间查询的 weight 相关 PR 还包括 #4708、#4679、#4681；这些明确是历史代码/文档归档，不是新的科学效力或权重编辑实验。未将归档日期当作更晚的模型成功。

归档总字节数 14,316,376；SHA256 `87173e7699117f9870393832f428b9f3e0046efe7f92035be7b37f5348ad9124`。模型冻结文件 SHA256 `982ccd42b472072aa860e6c0d203fab72a740bd8bef120bc6e01197b1befa29c`。实验在独立scratch副本运行。归档中五个 fit 是 11、23、37、53、71，每个包含四个家族，20 个模型都被完整下载；本轮仅编辑 renewal 家族。

## 2. 哪些问题能通过权重编辑解决

### 可执行的真实头

Digital joint 的完整状态表示是 31 个活动网格状态加上下边界 refractory 两状态，总共 33 维条件质量；公共输入 43 维，预测阈值 bank 9 维。因此真实输入是 85 维。

`head1: Linear(85,48)`，Tanh，`head2: Linear(48,4)`。前三个输出是 WAIT、READ、REPAIR 的 Continuation Q；最后一个是 belief logit。最终动作值固定组装为：

\[
p=\sigma(o_3),\qquad Q=[0,o_0,o_1,o_2,1-2p,2p-1].
\]

[模型定义](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5b69a046d886cf4c2a73c50e58197360ea15d8f5/tools/hcsn/digital_joint_20261102/joint_model.py)与[无 Torch 推理](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5b69a046d886cf4c2a73c50e58197360ea15d8f5/tools/hcsn/digital_joint_20261102/joint_deploy.py)直接支持这些身份。

| 目标 | 当前源码事实 | 合理编辑/审计边界 |
| --- | --- | --- |
| 状态表示 | renewal 保存完整条件质量和未来公开 schedule 驱动的 bank；GRU 分别学习 mass decoder 与 bank decoder | 可检查质量归一性、观测时序与输出校准。被冻结的末层不能恢复上游已经丢失的信息；表示本身错误需要重建特征或上游改动 |
| First-Passage/Reset | joint 是有限空间 CTMC，加上下边界 refractory 和 reset 分布；八个 renewal raw 物理参数在原联合训练中可学习 | 本轮未编辑物理参数。改 raw 后必须重新生成 generator/transition tables；只改 JSON raw 字段不改变当前 NumPy forward |
| Call/Put 或正负价值通道 | joint 的 terminal SUBMIT 值已经严格互补，bank 是三个 horizon × 三个阈值尾概率；没有可自由分别修补的两个 terminal 矩阵 | 不能把已存在的 `1-2p/2p-1` 再包装成新修复。更广 HX 金融通道需按真实实现逐项定位，不能把 joint digital bank 当作完整金融 Call/Put |
| Belief | sigmoid 有可学习末层行；终止值共享其输出；teacher posterior 属于指定 law | 本轮固定该行，所有臂的共同状态 belief Brier 精确相等。概率合法性不等于校准或未知真实世界正确性 |
| Continuation Q | 三个独立 48 维末层行和三个偏置，147 个可编辑坐标 | 最合适的确定性闭式子问题。每行采用合法动作 mask、旧参数锚定和独立价值选择 |
| NDU 全局价值控制 | 每个动态世界有明确合法动作、成本、delayed READ、failure、repair、deadline-six target；Oracle 只对指定 CTMC+训练混淆矩阵最优 | 能精确评估指定有限模型中的期望策略价值。不能从局部 Q 拟合推出全局未知任务最优，更不能外推到 HeptaTrader 实盘 |

在 V13，`FinancialMap` 的文档直接写明 **No financial parameter is trained**；实际学习的是 asset encoder、gate、candidate、rate、reset_content 和 content reader。金融函数提供 equity、F、G、bond 的解析通道，边界被注册为 buffer。神经 reset 是 source tick 规则及固定 cooldown，不是连续 first-passage 精确采样。[V13 金融映射](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1a8f0b22e318bf919050f76b52a9c5feb5521ce9/experiments/hcsn_v13_followup_20261102/joint_core/hx_torch.py)、[V13 模型](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1a8f0b22e318bf919050f76b52a9c5feb5521ce9/experiments/hcsn_v13_followup_20261102/joint_core/model.py)。

R22 的九物理参数导数在 595 个注册点通过，但完整有限数组只经 boundary、drift、diffusion 三个摘要构造，Jacobian 秩至多 3。这是可识别性结构限制；九个非零导数并不等于九个可独立定位修复的机制。[R22 完整参数报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b35dc241271a111c27b1a5fea72ad0112b43cd1a/tools/hcsn/full_parameters_r22_20261102/REPORT_ZH.md)。

### 原有端到端证据仍然有限

Digital joint 原研究：20/20 拟合准入，完整 CPU 58.882757–59.387372 秒，4,800 确认 episodes、400 个独立世界。14 个主校正门仅 3 个通过，renewal 自身两项 useful-gain 门和六项 ordinary 优势比较均未通过；secondary 0/6，raw/slim robustness 均未通过。原生运行一致性 20 个权重、80 个已见验证 episodes、240 CLI、最大数值差 7.77e-16，说明执行路径可复核，没有转化为效力通过。[PR4650](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4650)。

V13 的 36 个 joint content 拟合和 1,944 个实际策略 episodes，在同一控制器下 HX–GRU utility 差仍为 emotion −0.1400008333、binding −0.0027785417；数据暴露与独立新录制验证的限制依然存在。[PR4658](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4658)。


### Call/Put 的守恒关系必须与具体语义一致

在本次 joint 任务里，`1-2p` 和 `2p-1` 是二分类提交动作的期望奖励，二者和为0。它们既不是两个独立可编辑的头，也不能用来证明一般金融 Call/Put 互补。V13 `FinancialMap.channels` 返回 equity、F、G、bond；F 是违约/触界概率型量，G 含折现/触界权重，源码没有给出 F+G=1 的约束。

若某个模块确实定义为首次触及上边界、首次触及下边界两个互斥事件，其概率通常还必须保留未触界存活残差：`P(先触上且在T前)+P(先触下且在T前)+P(T内未触界)=1`。reset/renewal 的跨周期累计事件还要另外定义，不能把两侧累计通量直接当成一次二元事件。一般有生存、违约、折现或回收项的金融通道，也不能强行投影为两行权重相反。这里给出的是针对已审阅 joint 与 V13 源文件的语义映射，没有穷尽全仓库所有以 Call/Put 命名的实现。

## 3. 本轮闭式编辑协议

代码 `run_head_edit.py` 在读取测试结果前把候选网格、种子和门写入 `protocol_before_results.json`。源代码并未事先发布 GitHub，因此这是可审计的当轮前置协议记录，不应描述为公开预注册。

- 五个原 renewal Checkpoint，验证原始文件 hash；共同训练 1,582 状态，验证 366 状态，64 个训练世界与 16 个验证世界/fit。
- 冻结 85→48 的表示和 belief 行，只改 WAIT/READ/REPAIR 三个末层行及偏置。特征向量为 48 维 Tanh 输出加常数 1。
- 六个正则参数：`[1e-5,1e-4,1e-3,1e-2,.1,1]`。参数半径为原 continuation 头范数的 0.5 倍；最终五个选中解都未触及半径。
- 验证选择优先指定 law 下的精确期望 utility，再按 masked Q error 与范数打破平局。只有验证 utility 比原模型至少改善 .005 才接受；否则回到原参数。
- 固定头梯度下降基线使用相同目标及由直接编辑组选择出的正则，迭代预算为 `[1,5,20,100,500,2000]`。它是固定头梯度基线。GD没有独立搜索λ；这不是独立超参数选择、相同总计算预算或新的全模型重训对照。
- 六个独立随机方向保持与选中闭式编辑相同的 Frobenius 范数，使用同一验证选择规则；这比只给随机方法一个无选择的样本更有比较意义。
- WAIT-only、READ-only、REPAIR-only 使用选中闭式更新的对应一行，其他行恢复原值。
- 每个 fit 生成 32 IID 与 32 OOD 新公共 schedule，测试 seed 固定为 `870040000` 派生；不进入选择。按所有后续二元观测和 failure 的概率树求期望 utility，避免单次 Monte Carlo 结果噪声。

对动作 j，采用与原 masked Q loss 一致的行权重 \(w_{ij}=m_{ij}/(n\sum_km_{ik})\)，解

\[
\min_{\theta_j}\sum_iw_{ij}(x_i^T\theta_j-y_{ij})^2+\lambda\|\theta_j-\theta_{0j}\|^2,
\]

\[
\theta_j=\theta_{0j}+(X^TW_jX+\lambda I)^{-1}X^TW_j(y_j-X\theta_{0j}).
\]

因为 λ>0，这个**固定特征、固定目标的子问题**具有唯一全局解。它仍使用数据和 teacher 目标，并不是凭空理解任意神经网络权重。脚本的半径裁剪在最终所选解上未激活；若将来激活，径向裁剪不能一般地宣称为球约束二次问题的精确最优解，Rust 应用 Lagrange multiplier 搜索或明确称为保守裁剪。

**语义范围**：测试 law 是独立 SciPy expm 的指定有限 CTMC，译码 law 使用原 TRAIN 混淆矩阵。没有打开新的 FullHX packet，没有新的实际 decoder 泛化测量，也没有 HeptaTrader 交易收益。此范围故意小，方便独立验收，不能扩大解释。

## 4. 实际结果

期望 utility 均值，以原始五个训练 fit 为独立统计单位；每个 fit 含 32 个新公共世界/域。

| 编辑臂 | IID utility | 相对原模型 | OOD utility | 相对原模型 |
| --- | ---: | ---: | ---: | ---: |
| 无编辑 | 0.21309701 | 0 | 0.11797339 | 0 |
| 闭式编辑，验证门后 | 0.22727900 | +0.01418199 | 0.14490749 | +0.02693410 |
| 固定头梯度，验证选择 | 0.22891382 | +0.01581681 | 0.14436131 | +0.02638792 |
| 等范数随机，验证选择 | 0.23049919 | +0.01740218 | 0.12482056 | +0.00684717 |
| 仅 WAIT | 0.19363591 | −0.01946110 | 0.12398983 | +0.00601644 |
| 仅 READ | 0.21183752 | −0.00125949 | 0.13170907 | +0.01373567 |
| 仅 REPAIR | 0.21302398 | −0.00007303 | 0.11777080 | −0.00020259 |

闭式编辑的 paired 95% 区间：IID `[−0.01849575, +0.04685973]`，OOD `[−0.02344963, +0.07731782]`。它们是未作多比较修正的描述性区间，已经跨零，因此没有正向显著门通过的基础。

共同测试状态的 continuation Q MSE：IID 从 0.02069472 降到 0.01753157；OOD 从 0.06605200 降到 0.06426494。Belief Brier 在所有编辑臂精确不变（IID 0.00057514、OOD 0.00381035），符合冻结协议。WAIT 单行在 IID 反而降低均值，表明把特定权重组的监督误差下降视为全策略收益，会给出错误结论。

| fit | 选中 λ | 验证 utility 改善 | IID 改善 | OOD 改善 |
| --- | ---: | ---: | ---: | ---: |
| 11 | .1 | +.0189440 | +.0247109 | −.0085166 |
| 23 | .01 | +.0419803 | −.0139710 | +.0484920 |
| 37 | .01 | +.0291310 | +.0527342 | +.0861490 |
| 53 | .001 | +.0108779 | −.0052756 | −.0085958 |
| 71 | 1 | +.0677003 | +.0127114 | +.0171420 |

直接编辑五个验证门均接受；进一步按同一 `.005` 门核查直接编辑、GD、随机三组共15个最终选择，15/15均接受。冻结脚本只有直接编辑臂显式实现回退，GD和随机臂直接报告已选结果；把相同门应用于后二者不会改变本次结果。没有把门实现差别隐藏为完全等价的事先协议。自然失败回滚路径没有在最终候选上被触发；脚本验证了候选恢复后的模型对象与原模型语义完全相同。**不能把 `rollback_verified=true` 解释为本轮真实候选失败后发生过五次自动回滚，也不能把 JSON 语义恢复等同于原文件字节恢复。** Rust 层应独立验收字节恢复、拒绝结果、进程中断和原文件未改动。

## 5. 数值、性能和成本核查

初次 NumPy 运行共 14.741794 CPU 秒、14.824582 wall 秒；五 fit 的全部 30 个闭式候选求解合计 .005033 CPU 秒，固定头梯度候选合计 .102993 秒。该约 20 倍差距只指这个极小二次问题的候选求解部分。数据获取、表示提取、teacher/DP、验证选择、独立审计成本没有被归零；全流程并不获得 20 倍加速，也未与本轮同起点全模型重训比较。

原先全模型约 59 秒的历史预算发生在不同完整训练流程和机器/目标范围，不构成同预算速度或效力优越的证据。已有特征缓存被不同臂共享，`eval_cpu_seconds` 存在评估次序和缓存优势，不能用于声称推理加速。能源、GPU 和实时部署成本没有测量。

macOS NumPy 初次执行出现多个 matmul 浮点状态警告。没有直接忽略这一问题作为成功。`checked_replay.py` 对每个矩阵乘积计算显式求和/无 BLAS einsum 参考，检查输入、输出有限性，并且**实际后续执行使用参考结果**，在完全相同的固定协议上重新运行。

- 审计 1,079,307 个矩阵乘积。
- 最大 BLAS 与显式求和差 `8.881784197001252e-16`。
- 非有限输入/输出 0；最大输入绝对值 1.19695、最大输出绝对值 3.56784。
- 独立重放无 stderr；CPU 30.144813 秒（含审计），逐臂平均 utility 与初次运行最大差 `8.326672684688674e-17`。
- 警告没有对应已观察到的数值溢出；具体后端浮点标志原因未定位。该重放解决了本研究结果对错误矩阵乘积的担忧，没有宣称修复 NumPy 后端。
- 原始 macOS `rust_fixture.json` 还在本地 Linux NumPy 独立解算，最大参数误差 `2.0816681711721685e-16`。

随后在完全固定种子的协议下，又以 `np.errstate(over="raise", invalid="raise", divide="raise")` 包裹整个 checked 执行路径及线性求解器，完整复跑成功、stderr 为空。仅独立比较用的 BLAS 诊断结果在局部忽略状态标志，其数值仍逐次检查，而且绝不用于后续计算。严格复跑和 checked 复跑的每 fit、每域、每臂期望 utility 差为0；所有选择一致。严格主流程 CPU 30.344259秒，含审计外围 30.378142秒。该额外成本是确认结果可靠性的代价，不能从“优化更省算力”的账单里去掉。

证据文件：`strict_fp.json`、`matmul_audit.json`、`strict_replay_comparison.json`、`results_strict.json.gz`；`results.json` 初次完整结果，`results_checked.json` 独立重放，`checked_process_receipt.json` 原进程输出，`rust_fixture.json` 跨平台输入/期望解。

## 6. 给 Rust 原生子系统的具体交接

`rust_fixture.json` 包含真实 fit11 的 64 个状态、49 维冻结特征、3 个 Continuation Q 目标、每动作 sample weights、原三行参数、λ=.01、未剪裁精确目标参数、固定 belief 行和源模型 SHA256。对 Rust 新 solver 来说，不需要安装 Torch 或接入 live checkpoint 就可验证线性代数实现。建议误差门 `max_abs <= 1e-10`，同时验证有限性、维度、对称正定求解、不同 λ、空/错误 shape 拒绝。

Rust 操作事务应保存：源模型完整 hash → 特征/targets/协议 hash → 候选补丁与范数 → 数学约束 → 独立任务价值收据 → 接受/回退及新旧 hash。仅构造“工具可以编辑 safetensors”没有覆盖模型语义或科学资格；只完成凸 solver 也没有解决 checkpoint 全图分析。

后续可能有价值的真实方向是：使用上游可识别子空间控制物理参数；对 CTMC 改动强制重生成 transition tables；在固定特征凸子问题上使用解析解；用精确有限 NDU 枚举/DP 评估候选；仅在独立效力门通过后发布研究候选。是否采用必须取决于任务价值和可接受成本，而非“是否无梯度”。

## 7. 未闭合事项

1. 真实 FullHX packet、未暴露数据与 HeptaTrader 端到端价值没有在此子任务运行；不将有限仿真成绩替代它们。
2. 五 fit 数量、16 验证世界、每域32测试世界不足以把目前宽区间缩到预先规定的实用门。不得看过测试后选择更有利的子群或超参数。
3. 本轮 fixed-head gradient baseline 不是同起点、同总预算的 full-model retraining。需要另外的约束预算实验才能比较完整训练范式。
4. 状态表示、物理 raw、Belief 均被固定。不能把本轮局部 Q 结果描述为这些机制已被自动定位和修复。
5. 参数对称性/可识别性、连续自由边界、未知真实 decoder law、通用权重电路理解仍开放。
6. 没有将本轮候选用于生产，也没有 merge 或激活任何模型；父代理可提交源码、夹具和负结果，保留科学门 OPEN。

## 复现入口

确保上述原始归档已按 `PARTS.json` 拼接、验证总 hash，并在独立目录中安全提取 `fit_*/model_renewal/model.json` 与 `fit_*/data/fit_*_data.json`。保留本目录原始来源的 `joint_task.py`、`joint_deploy.py`、`joint_law.py`、`legacy_task.py`、`joint_protocol.json`。`truth_transitions.npz` 是从原 `IndependentLaw` 用 SciPy expm 生成的 12 个 duration/drive 真值矩阵，SHA256 `3a62c48272d90b459622ed8818fddf36de983831fbc0c1306fc39b27345228f0`。

```sh
python run_head_edit.py /absolute/path/to/extracted /absolute/path/to/new-results
python checked_replay.py /absolute/path/to/extracted /absolute/path/to/new-checked-results
```

每次输出目录必须不存在。保留相同输入和协议；重放验证数值一致性，不增加独立科学重复数。

## 8. 原始 TRAIN 状态上的策略可实现性诊断

此项在固定效力实验结束后增加，是明确披露的数学诊断，不是新的候选搜索；没有使用新测试世界，也没有把 LP 的任何参数用于测试或部署。输入是原始1,582个训练状态的真实49维特征、原oracle动作值、legal mask和原4×49末层参数。只允许改变147个 continuation 系数，Belief、STOP和两个SUBMIT值固定。为了避免人为选择 oracle 平手，跳过最优动作间隙≤1e-10的平手行。

对每个具有唯一最优动作a的TRAIN状态，要求其编辑后分数满足 `score(a)-score(b)>=m`，对每个其他合法动作b建立线性不等式。固定检查 m=0 与 m=.001。共有：fit11 1,061个约束、fit23 984、fit37 1,043、fit53 1,172、fit71 1,185；跳过平手行分别8、12、7、8、11。

| fit | 无改动幅度限制 | 含原L2球的较宽L∞盒 | 具体结论 |
| --- | --- | --- | --- |
| 11 | 两个margin均可行 | 两个margin均可行 | 当前可行解L2范数约6，超过原半径.614；这里只证明盒可行，原L2球可行性未证明 |
| 23 | 两个margin均不可行 | 不可行 | row227原oracle选择SUBMIT1，但冻结Belief使SUBMIT0与STOP分数更高 |
| 37 | 两个margin均不可行 | 不可行 | row87、105、106、113固定终止动作排序与唯一oracle动作冲突 |
| 53 | 两个margin均不可行 | 不可行 | row66原oracle选择SUBMIT1，但冻结Belief的终止排序相反 |
| 71 | 两个margin均可行 | 两个margin均不可行 | 即使放宽为每坐标±ρ，也不能匹配所有唯一oracle训练动作；因此原半径L2球也不可行 |

三个固定终止排序冲突模型有直接证书：相应不等式的147维系数全零，但右端小于0；无论 continuation 权重怎么改，均不能满足它。以fit23 row227为例，oracle的SUBMIT1–STOP差+.00461779989，而冻结模型的该差−.00024980446。可取该约束的单位向量y，得到 `Aᵀy=0`、`y>=0`、`bᵀy<0`。这是针对当前浮点表示和原TRAIN标签的局部不可能性证据，不能外推为完整网络永远不可修复。

fit71盒约束的数值Farkas证书在m=0下为 `bᵀy=-.000514900250229`、`max|Aᵀy|=4.79e-16`；m=.001下分别为`-.00148746891928`、`5.71e-16`，y非负且归一。完整非零支持与约束顺序保存在 `train_policy_feasibility.json`。这是可重算的浮点证书，没有冒充精确有理数证明。无约束可行解只满足训练子集，且范数很大；没有证明全状态空间、IID/OOD或未知真实世界的NDU最优。

这些结果支持先审计可编辑子空间：Belief终止排序错时，Continuation Q改得再精确也不能直接纠正终止动作之间的关系；信赖范围不足时，应报告不可行，而不是不断重复求解。解除冻结、扩展表示或改变预算属于新研究协议，需要新的效力验证。

## 9. 输入恢复与交付验收

发布材料完全来自已经公开的固定joint归档。归档14,316,376字节及全部3,550个普通成员的SHA256均已实际核查；五个源模型和训练/验证数据逐个固定身份。`acquire_inputs.py`支持从已有git对象以二进制`git show`恢复或从固定public raw URL取分片，也支持既有归档复验；完成所有hash检查后才在新目录写入10个所需文件。

交付目录 `hepta_private_ci_delivery` 可整体放入仓库 `tools/hcsn/wsp_20261104`。`SOURCE_MANIFEST.json`逐项映射复制源码和原始blob路径；`INPUT_ACQUISITION.json`给出原模型、数据及公开来源；`DELIVERY_MANIFEST.json`记录交付文件hash。完整结果有初次、独立checked及strict三种记录；`verify_delivery.py`检查身份、共同接受门、有限性、冻结belief、Rust数值夹具及仍未通过的科学门。

`fixtures/rust_fixture.json`与`fixtures/train_linear_geometry.npz`包含真实模型导出的参数/特征片段，但上游模型和TRAIN数据本身已在同一公共仓库发布。这不是新增HeptaTrader私有数据，也不能笼统标成“去敏后私有模型”。本子任务没有取得或复制新的live HeptaTrader checkpoint内容，仓库提交由父代理统一完成。

恢复器和特征导出器已在原归档上实测：3,550成员复验、10个输入文件恢复成功，重新导出的25个数组与原几何完全相同，NPZ字节hash也相同。原推理导出器仍触发已记录的macOS BLAS状态警告；完整科学复跑另用严格显式参考执行并通过，未宣称修复系统后端。
