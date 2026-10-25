# V3 机制补充：规划改善的究竟是哪一个目标

**Loss2 H8 相对 myopic H1 的共同目标改善，可以被精确分解为：当前风险升高，二次动作惩罚下降得更多。Loss2 与 Full 两个 critic 都预见了这一对动作的权衡，真实分支也呈现相同方向。因此，这一对动作的风险变化不能归因于错排；Loss2 在整个候选池中的排序失真是另一项证据。**

用户提出的“同完整状态下的动作排序与保留可行性实验”已在 [V3 报告](../20261024-cell-parameter-field-v3/README.md)完成。本目录是对其冻结分数的事后机制复算：没有新增训练、候选动作、标签 payload 访问、策略选择或置信区间。18 个 anchor 来自六条固定 seed/Head 路径，下面的均值与计数均为描述性结果，不能视作 18 个独立任务。

## 1. 来源与比较范围

| 项目 | 固定身份或规则 |
|---|---|
| 仓库 | `TrillionniumFoundation/hepta-private-ci` |
| V3 执行源码 | `c69e4e7ab55456e75476be4ca9a3bcaeaea1934c` |
| V3 已发布证据 | `a062749d768ea09838921c7f3bfd8b644541b873`，原 [PR #3825](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3825) |
| 输入 | 已发布的 `protocol.json`、`external-analysis.json` 和 18 个 `runs/anchor-*.json`，共 20 文件 |
| 对照 | 同完整初态、动作 box 上限、共同 direct 目标、实际 H8 时域 |
| 动作语义 | 第一步 Adam 后施加一次参数干预，随后七步额外干预为零 |
| myopic | `loss2_h1_direct_soft`；18 个状态上与 `full_h1_direct_soft` 的完整终态及实际分数完全一致 |

输入身份由 [source_manifest.json](source_manifest.json) 的固定 commit、目录、精确文件集合及 Git blob SHA1 绑定；[objective-decomposition.json](objective-decomposition.json)另记录输入 SHA256。独立审计使用从原 `runs-index.json` 与协议得到的 [independent-source-binding.json](independent-source-binding.json)，不只依赖主分析的清单。

## 2. 共同 J 的改善来自动作惩罚

将原协议已经记录的 direct 目标分为三个成本项：

\[
J=R_{\mathrm{current}}+P_{\mathrm{forget}}+E,\qquad
E=\frac{h\rho}{2}\|u\|^2
=\frac{\rho}{2h}\|\delta\theta\|^2,
\quad h=0.02,\quad\rho=0.1.
\]

这里的 `direct_current` 是共同 H8 评分中的当前风险成本，末步 current-probe NLL 另外报告。下表为左减右、18 个 anchor 的等权描述性均值；四个成本列统一以 **10⁻⁶** 为单位，负值代表该项降低。

| 对照 | Δ 当前风险成本 | Δ 旧任务惩罚 | Δ 动作惩罚 | Δ J |
|---|---:|---:|---:|---:|
| Loss2 H8 − H1 | +2.701046 | 0 | −3.175231 | −0.474184 |
| Full H8 − H1 | −2.925668 | 0 | −1.155327 | −4.080995 |
| Full H8 − Loss2 H8 | −5.626714 | 0 | +2.019903 | −3.606811 |

对 Loss2 H8/H1，**18/18 个状态均同时满足：当前风险成本上升、动作惩罚下降、总 J 下降、末步 current-probe NLL 上升。** 末步 NLL 平均升高 `7.71297814e-5` nat。动作范数比 H8/H1 平均为 `0.836146`，范围 `[0.656584, 0.922656]`。同一个动作预算上限并不意味着同一个实际动作范数。

动作惩罚是目标内对参数干预幅度的计价，不是实测运行时间、CPU、内存或能耗。两种控制器的真实评估分支都执行八步；不能把 H8 的较低动作惩罚写成“节省训练算力”。

Full H8/H1 则在全部 18 个状态同时降低当前风险成本和动作惩罚，末步 current-probe NLL 平均降低 `9.86561875e-5` nat。因而也不能把所有现象都归因于动作价格太高；Loss2 的多步模型与目标计价需要分别检查。[逐状态与聚合数据](objective-decomposition.json) · [自动生成摘要](objective-decomposition.md)

## 3. 这一对动作没有被两个 critic 错排

对同一组已经冻结的 **Loss2 H8 与 Loss2 H1 动作**，独立审计另外比较了两套 critic 的预测，而不是只看动作生成器自己的输出。

| 共同 H8 评价 | 平均 Δ J，单位 10⁻⁶ | 18/18 状态的方向 |
|---|---:|---|
| Loss2 critic 预测 | −0.433471 | 当前风险升高、动作惩罚降低、J 降低 |
| Full critic 预测 | −0.482318 | 当前风险升高、动作惩罚降低、J 降低 |
| 真实执行 | −0.474184 | 当前风险升高、动作惩罚降低、J 降低 |

两套预测还都预见末步 current-probe NLL 上升。因此，对这一个预先固定的 pair，“J 改善但当前风险变差”是模型预见的标量目标权衡。[独立审计的 critic 比较](independent-cost-audit.json)

原 V3 中，Loss2 对完整候选池的 direct 平均 Kendall τ_b 为 `−0.110487`，Full 为 `1`，仍然是独立存在的排序事实；不能把全池失真移用为每一个具体 pair 的错误解释。两种模型都用完整 checkpoint 构造参考导数，Loss2 是沿轨迹的两损失无记忆闭合近似，而不是端到端只接收两个数字的控制系统。[原排序](../20261024-cell-parameter-field-v3/ranking.json) · [原机制说明](../20261024-cell-parameter-field-v3/README.md)

## 4. 动作价格敏感性只重评冻结动作

固定原有两个动作，不进行重优化，则：

\[
\Delta J(\rho')=\Delta R+
\frac{\rho'}{\rho_0}\Delta E,
\qquad
\rho^*=-\rho_0\frac{\Delta R}{\Delta E},
\quad\rho_0=0.1.
\]

其中 ΔR 包括当前风险成本与旧任务惩罚的变化，本批对照的后者为零。Loss2 H8/H1 的 18 个交点范围为 `[0.068367347, 0.091229192]`，逐 anchor 交点均值为 `0.083061488`；先等权平均成本再求出的交点是 `0.085066145`。这两种聚合不同，不应混用。原价格 `0.1` 高于全部交点，足以使动作惩罚的节省抵消当前风险成本的增加。

这些数字解释原有两动作如何被计价，**不构成选择新 ρ 的验证结果，也不等于在新 ρ 下重新优化后的控制器表现**。在冻结动作的范围内，Full H8/H1 同时降低风险和惩罚，因此对所有非负 ρ 都保持这一对的优势；这仍不是对任意动作或新任务的保证。

## 5. 外部表现的统计结论保持原样

原 V3 的 anchor 16 未来等月 NLL 比较，仍使用原先登记的 family 校正区间。下表为 Loss2 H8 − H1，单位 nat；正点差表示 H8 较差。

| Head | 未来 NLL 点差 | 原校正区间 |
|---|---:|---:|
| Linear | +6.08512041e-6 | [−8.13679150e-6, +2.13102757e-5] |
| Gated | +3.46754229e-6 | [−4.56622367e-6, +1.17566913e-5] |

两个区间都跨零。本补充解释了内部 J 与当前 probe 风险方向相反的具体机制，不能宣称已经确认未来任务显著退化，也没有识别全部泛化机制。原区间条件于固定拟合模型和来源；没有新增统计推断。[原外部评价](../20261024-cell-parameter-field-v3/external-analysis.json)

## 6. 保留可行性仍需要有实际压力的开发条件

原 V3 的 108/108 个 hard/soft 配对动作与完整终态相同，hard 乘子全零；最小预测 slack 为 `0.0012439177`。包括 18 个 zero 在内，342 个分支在已测 probe、独立 validation、final old-test 的路径均值检查中都通过。这支持该批有限来源上的保留结果，但没有识别硬约束的增量作用，也没有验证任务总体保留。[原保留结果](../20261024-cell-parameter-field-v3/README.md)

附带的 [retention-pressure-design.json](retention-pressure-design.json)明确标记为 **`proposed_not_executed`**，未运行，也未作为独立确认使用。它保留当前 Encoder、两种 Head、观测、单 Cell 和原 warmup 保留阈值，通过普通当前任务训练路径产生实际压力：

1. 仅用控制 old_probe，在至多 256 步内寻找首次越过原 warmup 阈值的 τ；没有越界就报告 `no_pressure_crossing`，不事后放宽规则。
2. 分开保存越界前 `max(0, τ−8)` 与越界时 `τ` 的完整状态，分别研究防止遗忘和修复已经继承的遗忘。每个条件仍对所有方法固定同一个 checkpoint。
3. 预先固定预算倍率 `[0.25, 1, 4]`，另保留 zero 诊断；完整报告 soft 违规、hard 实际保留、预测可行但实际违规、切线不可行证据、候选未找到可行解、数值 unresolved 和无压力条件。

一个必要的设计事实是：**只要零动作可行，任何包含零的嵌套动作 box 都可行。缩小预算不能凭空制造该条件下的 hard 不可行。** 把阈值从 warmup 改成 warmup−δ 则把“无遗忘”改成了“必须改善旧任务”，不能混作原保留问题。切线不可行证书只约束声明的切线问题；有限候选全部失败不能证明真实非线性动作空间不可行。

方法开发可利用已暴露的 V3 train/probe，但新的独立确认必须重新冻结来源，排除已暴露的 V1/V2/V3 组件；若要推广至任务总体，还需要新的旧/当前训练任务实例。已打开的最终标签继续承担报告与机制说明角色。

## 7. 可复算与独立检查

主脚本校验 342 组实际分数、684 组预测分数、两种目标的成本求和、干预范数与动作惩罚恒等式，以及 18 组 H1 完整终态与实际分数一致性。独立脚本不导入主分析或训练/评分器，另行核验 1,926 个标量等式、54 个实际对照和 36 个 critic 对照；最大算术差异为 `2.22044605e-16`。两份 JSON 与自动摘要从固定输入重跑后均逐字节一致。[主分析代码](objective_decomposition.py) · [独立审计代码](independent_cost_audit.py) · [复算记录](verification.json)

在本目录下，对包含原 V3 证据的 checkout 运行：

```bash
python -B objective_decomposition.py \
  --input-directory ../20261024-cell-parameter-field-v3 \
  --manifest source_manifest.json \
  --output /tmp/v3-objective-reproduced.json \
  --markdown /tmp/v3-objective-reproduced.md
python -B independent_cost_audit.py \
  --inputs ../20261024-cell-parameter-field-v3 \
  --binding independent-source-binding.json \
  --analysis /tmp/v3-objective-reproduced.json \
  --output /tmp/v3-objective-independent.json
```

本轮在恢复的局部 checkout 上执行仓库要求的 `just fmt`；该 formatter 没有为 `qa/` Python 分派格式工具，不能据此宣称全仓格式检查通过。原 V3 数据与源码保持冻结，本目录只增加分析、审计和明确未执行的设计，不重复存档模型或原始训练轨迹。

对参数场理论与 Hepta 的联合研究，下一项有识别力的开发对照应把实际干预幅度与方向分开：在共同可行半径上比较同范数动作方向，再比较同一方向的幅度扫描，并逐项报告风险与动作惩罚。该对照也尚未执行。这样才能区分动作方向、目标计价和多步闭合误差，再决定是否需要增加观测或改变 Head。
