# R14：物理参数与观测可辨识性

## 结论与准入范围

本轮将 R13 的三个物理自由参数收敛为 **sigma、liquidity 两个自由参数，maturity 固定为 1.3**。这是一个公开的模型约定；它没有从原始符号流估计出 maturity。`reduced_cell` 强制采用这一固定值，并把每行 emission logits 中心化，从表示中去掉两个无效的共同平移方向。

固定 emission 时，R13 的三个物理参数对本轮原始观测设计的 Jacobian 秩为 2。加入 12 个 emission logits 后，15 坐标的联合 Jacobian 秩为 12；去掉 maturity 和每行一个 emission gauge 后，剩余 12 个坐标在当前点局部满秩。**这些是固定有限模型、固定单位、固定观测设计及给定参数点的局部结果。**它们没有证明全局唯一恢复、有限样本精度、任意任务上的辨识性或连续极限。

本轮还构造了六组原始观测流相同、任务费用不同的参数。因而训练任务价值时，必须使用实际训练回报/费用，或者把价格作为公开任务定义；不能用流拟合出的某一组物理参数，冒充已辨识的任务收益模型。

## 来源与独立检查

控制性父提交是 `b0802dc314251f5332bd026cb2984a0b5c75f768`，对应 `research/hcsn-unified-task-flow-r13-20261031` 的 R13 实现。该审计直接使用父实现的 `Cell`、原始 `PROTOCOL.json` 和完整金融 kernel。

本模块最初来自 `/workspace/scratch/b898b10cd696/hepta-qpi-r14` 中未发布的开发稿。本轮重新读取了实现并独立运行检查，增加了真正固定 maturity 的入口、emission gauge 中心化、联合物理/发射 Jacobian、独立中央差分复核和 Fisher 条件数。本文件不把旧草稿当作已经发表或通过确认的数据。

可复算结果保存在 [evidence/identifiability.json](evidence/identifiability.json)，其中保存执行源码、测试、父 `Cell`、父协议及金融 kernel 的 SHA-256。审计完全由公开的结构设计计算，不使用训练、校准或确认 episode，也不选择确认种子。

## 为何第三个物理参数不能从流中恢复

在 R13 固定的其余六个金融参数、网格和观测规则下，令

\[
\theta=(\sigma,\ell,m),\qquad b=b(\sigma,\ell,m).
\]

`Cell` 的 active diffusion rates 仅依赖 \(\sigma\)；reset insertion weights 通过 \(\log(90/b)\) 依赖 boundary。两阶段 recovery 的速率、bit retention 和显式 RESET 矩阵均固定。因此

\[
Q=Q(\sigma,b),\quad p_0=p_0(b),\quad R=R_0,
\]

而 emission 矩阵 \(E\) 与这三个物理参数无关。

固定 \(\sigma\) 并保持 \(b\) 不变时，\(Q,p_0,R,E\) 全部相同，故任意相同因果动作规则产生的原始符号流定律相同。这不只是一项有限样本统计检验：它来自模型结构。局部零方向为

\[
v=(0,\partial_m b,-\partial_\ell b),\qquad D b\,v=0.
\]

代码先用此解析方向验证 generator/prior/emission 的导数，再枚举完整符号序列验证 raw-law 的导数。没有用数值 SVD 反过来挑选这个方向。

### 六组等边界 profile

固定 sigma=0.3，在预定的六个 maturity 点上解一个标量边界等式，得到以下代表。表中差异均相对原始 `(0.3, 0.02, 1.3)`：

| maturity | 等边界 liquidity | 最大原始流概率差 | 最大 READ fee 差 |
|---:|---:|---:|---:|
| 1.00 | 0.0044070763 | 1.43e-15 | 0.00094594 |
| 1.15 | 0.0128221348 | 1.03e-15 | 0.00045760 |
| 1.30 | 0.0200000000 | 5.00e-16 | 约 1.4e-17 |
| 1.45 | 0.0262771180 | 4.02e-16 | 0.00043074 |
| 1.65 | 0.0336219536 | 0 | 0.00098677 |
| 1.80 | 0.0385537521 | 0 | 0.00139022 |

六个公开 observation designs 各自的总体负对数似然差，在舍入误差内为零。这里计算的是总体分布的等价 profile，**不是用有限训练样本拟合出来的置信区间**。超出 liquidity 参数盒的候选会被记录为不可行，不会被丢弃后改换候选点。

## 观测设计和局部秩

观测设计在代码中固定为：单次 READ 的 dt 为 0.15、0.45、1.05；两次 READ；三次 READ；以及一次 RESET 后两次 READ。每个 READ 只公开区间终点的七值符号。RESET 先作用于联合状态，然后消耗完整区间并传播；费用、真实 phase、bit 标签及 teacher posterior 均不进入 raw-law 表。

合计枚举 462 个原始符号结果。每个设计的概率质量单独归一。物理坐标使用协议参数盒宽度 `(0.25, 0.038, 1.5)` 缩放，emission logit 坐标使用单位缩放。秩判定阈值固定为最大奇异值的 `1e-8`。

| Jacobian | 坐标数 | 数值秩 | 主要尺度化奇异值 |
|---|---:|---:|---|
| 物理参数，emission 已知 | 3 | 2 | 0.290331、0.0460472、9.26e-17 |
| 固定 maturity，emission 已知 | 2 | 2 | 0.195079、0.0338751 |
| 物理参数与完整 emission logits | 15 | 12 | 最大 0.292848；最小非零 0.0252765 |
| 固定 maturity 且去除两行 gauge | 12 | 12 | 最大 0.272454；最小 0.0129074 |

在均匀随机选择六个设计的约定下，固定 maturity 且 emission 已知的 Fisher 加权 Jacobian 奇异值约为 0.432703、0.122830。平方值为尺度化坐标下每次完整试验的 Fisher 特征值。此条件数用于描述该观测设计；它不保证任何有限训练集都能准确恢复参数。

物理 Jacobian 和联合 15 参数 Jacobian 都用重新构建完整 `Cell` 后的中央差分作独立复核。中央差分仅用于审计，不进入训练路径。

## Emission gauge 与语义锚定

每行 softmax logits 加上任意常数，概率都保持不变。因此两个 emission 行具有两个连续冗余方向。本轮的 `reduced_cell` 总是把行均值减掉，保留全部原始序列概率；联合秩审计另用每行五个自由 logits、末位固定为零的等价坐标。

两类 bit 的发射行互换，在当前对称先验和 bit 动力学下也保持未标注原始观测流不变。这是离散的 label permutation，不能靠消除连续 gauge 或增加局部秩解决。训练终点的真实内容标签可以锚定 bit 含义。所有普通核心应获得同样的训练标签，执行期不得获得未观察到的 bit。

## 对本轮任务训练的约束

1. 使用固定 maturity 的两物理参数表示，并在更新 emission 时维持中心化或等价的十坐标表示。
2. 实际费用与终点回报作为训练监督，或由任务公开规定；不能从 flow-only 拟合结果中自动宣称恢复费用模型。
3. 若执行器只在训练结算时获得 sampled fee，则它不得在运行中把该费用作为隐含的状态观测。要公开费用时，应把它作为观测模型的一部分，并给普通核心相同信息。
4. 局部秩和预测等价性分别报告；不以某个参数估计数值稳定替代可辨识性证明。
5. 本审计没有准入完整金融核纯 FP32、生产 Rust ownership、多层语义网络或长期语义记忆。

## 复算

从仓库根目录执行：

```bash
python -m unittest tools.hcsn.task_aligned_r14_20261101.test_identifiability -v
python -m tools.hcsn.task_aligned_r14_20261101.identifiability --output tools/hcsn/task_aligned_r14_20261101/evidence/identifiability.json
```

该模块只使用 NumPy/SciPy 和父实验的金融实现。测试包含物理/联合导数、实际 RESET 后继、等观测不同费用、行中心化和 bit-label permutation。
