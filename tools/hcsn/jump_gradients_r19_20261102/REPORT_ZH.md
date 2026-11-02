# R19：实际 jump-aware 任务求解器的完整声明坐标梯度

已为实际 R18 jump-aware 求解器实现 **15 个声明可训练坐标**的一阶 Jacobian，接通准入时刻左右极限、延迟复位、内容模式、费用和终止奖励；同一普通正 Gaussian 参照也有完整坐标导数。独立全时域线性系统及 heat tangent ODE 支持这些实现。固定物理输入／目标的二十步参数更新已实际执行。

资格限于登记的有限网格 profile 与正规局部邻域。原较大扰动有两次跨分支，原失败完整保留；后续局部检查单独发布、全部通过。连续自由边界的全域导数、可变恢复时间／网格拓扑、全金融模型与生产资格仍未闭合。

推导见 [DERIVATION.md](DERIVATION.md)，范围台账见 [BLOCKERS.json](BLOCKERS.json)。

## 1．直接对应实际新求解器与全部声明坐标

基线是 R18 固定交付 `b25601c9bae257ffb651c8f9354fc380d8333f38`。三个实际继承源由 [DEPENDENCIES.json](DEPENDENCIES.json) 固定，并在执行前完成远端正文／SHA256 回读，见 [DEPENDENCY_READBACK.json](DEPENDENCY_READBACK.json)。

调用的是未修改的 `jump_solver.solve`。受限 return-profile 回调绑定其确切 code object，捕获实际内部 `left_limits`，核对数组身份、形状与首个左极限；成功或异常均恢复原 profiler。没有另造一个不同 primal 来产生验收值。这是读取 Python 私有局部变量的研究包装，不是稳定生产／原生 tangent API。

| 声明可训练量 | 坐标数 | 参数化 |
| --- | ---: | --- |
| 扩散风险 σ | 1 | log |
| WAIT／恢复时间单价 | 2 | log |
| 两模式复位费用 | 2 | log |
| 复位后的物理质量 x | 1 | 直接坐标、显式插值 knot 合同 |
| 两行内容转移矩阵 | 4 | 行 softmax logits；保留并检查两个冗余 gauge |
| 两模式终止奖励及共同 slope | 5 | base logits、amplitude-share logits、log slope |
| 合计 | **15** | 无概率 floor 或参数 clipping |

另验证外部连续查询状态 x 在插值单元内部的导数。域端点、dx、dt、T、ρ 和离散内容模式固定；它们不计入十五个可训练坐标。离开当前时间格的 T／ρ 修改会拒绝，不能把拓扑改变冒称为零梯度。

源码在正式检查前发布。独立 API 审计在任何正式结果开启前补齐模型绑定、查询下标与实际积分节点校验，V2 源为 `c821ecde51f0eb76ce0df5e165ed98358630f860`，冻结 SHA256 为 `c5875144cb288d58c093cbf2b681f81dc2321d9770ddee9b4a4d097b5135415e`。旧源码和审计修正时序均保留。

## 2．左右极限与复位后继被真实求导

正规 continuation 行使用

`A dV_n^- = dV_(n-1)^+ − dt dc_wait − dA V_n^-`。

复位导数包含完整延迟后继：

`dB = M C dV + dM C V + M dC V − dk − ρ dc_rec`。

其中 `dC` 是复位质量移动带来的真实插值权变化。准入点分别使用正确的过去左／右极限，再对当前 `max(V^-,B^+)` 求正规分支导数；没有把它折回旧四坐标求解器。

正 Gaussian 参照直接微分实际正权积分：logσ 的密度导数为 `density*(z²−1)`，并使用实际 primal 的 8 或 16 节点设置。错误模型 raw／primal 绑定、负查询下标等请求会拒绝。

## 3．原九项通过与一项失败全部保留

[run_01/RESULTS.json](run_01/RESULTS.json) 覆盖三风险 `.7／1／1.3`、两网格、十五坐标，共 **90 个参数／配置检查**；两种中心差分步长为 `1e−5／5e−6`，同时验证实际 jump 与正参照。登记的十项 gate 中九项通过，一项 regular-FD gate 失败。

失败来自 σ=1.3、细网格的两个 `1e−5` 有限扰动跨过分支：logσ 的最大右值差 `3.56e−4`，reset_x 为 `5.19e−5`。在同一配置的 `5e−6` 扰动下，分支未改变，误差均低于 `3.41e−10`。这项失败没有从原结果中删除或重新标为通过。

其余独立验证结果：

| 核查 | 最大缩放差／结果 |
| --- | ---: |
| 独立全时域 sparse 系统与前向 Jacobian | `2.91e−16` |
| 三个系统各 8,710 方程、15 RHS 的残差 | `2.50e−16` |
| 独立 Fourier heat／tangent ODE | `4.99e−14` |
| 144 个单元内连续 x 查询导数 | `4.36e−11` |
| 三种非光滑构造的双侧方向导数 | `1.69e−7` |
| 实际 16 节点参照的 logσ 导数 | `8.33e−11` |

缩放差定义为 `max(abs(a-b)/(1+abs(b)))`，不是纯相对误差。Sparse reference 独立组装全部时间和左右极限未知量、延迟跨模式耦合及参数 RHS，不导入主 tangent 引擎的矩阵、reset helper 或奖励导数。ODE 单独检查 heat 分量，不能替代连续 QVI 自由边界导数证明。

## 4．明确的局部邻域 followup

观察到原有限步长跨分支后，保持全部物理配置、十五坐标、解析导数源码及原 `2e−5` 误差门限，另行冻结 **所有相同 90 cases／双引擎** 的 `2e−6／1e−6` 局部差分。源先发布于 `0752a3cafbc1a63acbd45003e2ab23ff641c389a`，冻结 SHA256 为 `9646797773e10941167feb1116f7844686c809051177f22a2b64cf98f5de11fd`；这明确是看过原结果后的确定性导数邻域检查。

[run_02/RESULTS.json](run_02/RESULTS.json) 的四项 gate 全部通过：**每个坐标在全部六个 profile、两个新步长、两个引擎均保持正规分支**，无通过子集选择。实际 jump 左／右 Jacobian 差最大 `3.55e−9`；正参照最大 `5.32e−9`。

原大步长变化也被精确定位：`t=1.06、mode0、x=−.625` 的左 LCP，logσ 正向 `1e−5` 与 reset_x 负向 `1e−5` 各跨一个分支格。局部导数通过不撤销该动作切换事实，也不证明一个适用于任意参数更新的统一平滑半径。

## 5．非光滑处没有假造普通梯度

精确构造的右准入 KEEP／RESET tie、左 LCP 双活跃行、reset 插值 knot 均拒绝普通 Jacobian。给定方向时，求解 critical-cone 互补问题，再通过右 max 的方向导数；不是对 hard action 使用 straight-through。

例如右准入 tie 的正／负费用方向并不互为相反数；reset knot 亦有不同左右方向。查询 x 的 knot 返回左右 slope／Clarke 区间。登记的时间准入例中，右值 `.430189`、左值 `.149821`，差 `.280368`；没有为此返回一个光滑时间或恢复期导数。离格 T／ρ 修改拒绝，异常后 profiler 恢复检查通过。

## 6．实际梯度更新和成本

固定 24 个物理输入及 canonical teacher 目标，目标字节哈希在全部更新中不变。实际解析 Jacobian 驱动二十步参数更新；每个候选均由实际 canonical 求解器重评，不对 hard action 求导。

MSE 从 **`.000362312` 降至 `.0000846085`**，下降约 **76.65%**；二十步均接受，**100 个 Python canonical 网格动作／边界标签发生变化**。结果历史字段 `changed_native_action_cells` 只指这些 Python 网格标签，不表示 Rust 原生 actor、连续首次触界或完整策略 rollout 训练。这里只建立固定目标的 value-model calibration／梯度接线 smoke；不宣称参数可识别性、神经内容质量、独立留出收益或核心优势。

外层 `wait4` 包含解释器、导入、全部有限差分、独立系统、ODE、训练目标与候选更新和输出：原 run **29.243757 CPU 秒**，局部 followup **23.458146 CPU 秒**，合计 **52.701903 秒**。训练内部约 1.94 秒已包含在原 run，不能重复相加。开发探针成本未知，不记为零；独立审计另计。这不是逐策略保质在线成本、GPU／能耗或完整项目生命周期账。

完整连续金融／神经模型、可变恢复期／期限的有效连续导数、跨自由边界拓扑的通用梯度、语义／真实跨模态训练、Rust 公共 tangent API 和生产采用仍开放。

## 复现

使用新的输出目录，保留原失败及通过记录：

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.jump_gradients_r19_20261102.checks --output /tmp/new-r19-gradient-check
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.jump_gradients_r19_20261102.neighbourhood --output /tmp/new-r19-local-neighbourhood
```

这是冻结源码的确定性复算，不是新增的独立科学确认。原普通 gate 的失败应在复算中同样保留。

### 原始结果的压缩传输

远端可用确定性 `run_01/RESULTS.json.gz` 交付原始结果；本地未压缩原件不变。`TRANSPORT_MANIFEST.json` 绑定原始／压缩 SHA256 和字节数。读取前可逐字还原：

```sh
gzip -dc tools/hcsn/jump_gradients_r19_20261102/run_01/RESULTS.json.gz > /tmp/r19-original-results.json
```

这只改变传输容器，不能修改或撤销原 regular-FD gate 的失败；解压后的哈希应与传输清单中的原始哈希一致。
