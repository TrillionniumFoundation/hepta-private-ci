# Q24 之后分别保护 Gaussian 密度和终点事件 logscore

浮点 Gaussian guard 的结论不能自动传递到事件编码、参数量化和概率量化之后。
本模块分别提供参数 guard 和概率 guard，并保留未保护路径作为反例与对照。
两个 guard 都额外使用冻结 anchor 在**同一公开历史**上的预测。它们不是纯事件流
单独给出的保证，也不赋予任何部署权限。

## 1. 量化可以破坏原有保护

若 anchor 是 `N(0,1+2^-26)`，原预测不作任何改动时 NLL 增量为零。
但最近 Q24 舍入把 variance 变成 1，得到更窄的 Gaussian；在足够远的尾部，
其相对 anchor 的 NLL 增量无上界。

若 anchor 是 `N(2^-26,1)`，最近 Q24 舍入改变 mean 而保持 variance 为 1。
两个等方差 Gaussian 的 log-density ratio 是非恒定线性函数，同样存在无界方向。
数值差很小不能替代全局密度比保证。

另外，Gaussian 的某一终点事件可能有有限但极负的 log-probability。
原生最大余数 Q24 概率分配可能给它零质量，使该事件的交付 NLL 变为无穷。
因此 Gaussian 参数保证与 categorical 概率保证必须分别验收。

## 2. 参数 guard：检查最终交付的 Q24 Gaussian

`guard_quantized(m0,v0,proposal_mean,epsilon=0.02)` 接受广播数组，返回
`(mean, variance, certificate)`。scalar runtime wrapper 为
`guard_quantized_scalar(...)`，返回可直接 JSON 保存的字典。

输入限定 `|m0|<=10000`、`v0∈[0.0001,100]`、finite proposal，
本资格 profile 支持 `epsilon∈[0,0.02]`。设 `M=2^24`，依次计算：

\[
d=\operatorname{clip}((m_1-m_0)/\sqrt{v_0},-\epsilon/2,\epsilon/2),
\]

\[
m_Q=\operatorname{round}_{\mathrm{ties\ even}}
\bigl(M(m_0+\sqrt{v_0}d)\bigr)/M,\qquad
d_Q=(m_Q-m_0)/\sqrt{v_0},
\]

\[
v_Q=\left\lceil Mv_0(1+|d_Q|)\right\rceil/M,
\qquad v_Q\ge v_0.
\]

实现额外用 anchor variance 的 ceiling 强制最后一个条件。
先预留一半预算，再依据实际舍入后的参数检查；这里不继承舍入前的证书。
Native typed 输入执行 ties-even 舍入，而已在 Q24 网格上的输出是精确二进制数。

对 `vQ>v0`，令 `c=vQ/v0`。密度损失差是一个关于目标值 x 的凹二次函数，
其最大值为：

\[
\sup_x\{\operatorname{NLL}(m_Q,v_Q;x)-\operatorname{NLL}(m_0,v_0;x)\}
=\frac12\log c+\frac{d_Q^2}{2(c-1)}
=\frac12\log(v_Q/v_0)+\frac{(m_Q-m_0)^2}{2(v_Q-v_0)}.
\]

若两组参数完全相同，最大值定义为零；其余 `vQ<=v0` 情形拒绝。
代码先计算 `(vQ-v0)/v0`，用 `log1p` 避免先把 c 舍入成 1。
只要最终计算的上界超过 epsilon，函数就失败，不返回“已保护”候选。
epsilon=0 仅允许能精确保持 anchor 的情况；整数可行性不是自动保证。

浮点证书在独立验证中与 90 位 Decimal 密度函数的直接驻点求值比较。
这些是有明确数值 profile 的计算证据，不是对任意 libm／CPU 的形式化证明。

### 原 native 的较窄有效域

原 typed head 要求每个输入参数绝对值不超过 8，正 variance 不小于 `2^-24`。
因此上述数学域不等于 native 资格域。证书的 `native_typed_domain_mask` 单独标记
`|mQ|<=8`、`2^-24<=vQ<=8`；超出交集的实际 native 调用仍拒绝。
本轮没有扩张原 native 参数域，也没有改动其量化规则。

## 3. 事件 guard：在原 native 输出之后单独投影

`protected_event_quantize(anchor_logp,candidate_probs,epsilon=0.02)` 的最后一维
必须是 `(put,neutral,call)`，返回整数 counts 和证书。
runtime wrapper `protected_event_quantize_scalar(...)` 返回 JSON 字典。

anchor 使用稳定 log-probabilities，不能先转成可能下溢的普通概率。
对有限 `logp0_i` 设整数下限：

\[
b_i=\max\{1,\lceil M\exp(\log p_{0,i}-\epsilon)\rceil\}.
\]

真正零概率的 anchor 事件以 `logp0_i=-inf` 表示，可以使用下限 0。
对于很小但严格正的 anchor 概率，即使普通浮点 `exp(logp0_i)` 为零，下限仍是 1。
下限计算用 80 位 Decimal exponential 及向上包络；normalized anchor 与 candidate
分别校验，不能把输入质量错误静默改成有效预测。

三事件、`epsilon=0.02` 时，实数上界
`sum(b_i) <= M*exp(-epsilon)+3 < M` 留出充足整数质量。
一般预算可能不可行，代码检查 `sum(b_i)<=M`，不可行则拒绝。

在可行整数集合 `q_i>=b_i, sum(q_i)=M` 中，选择与 candidate 归一化概率最近的
Euclidean 整数向量。实现先做带下限的连续 simplex 投影，再按整数边际平方成本分配
剩余质量；代价相同时使用固定类别顺序。独立验证用较小总质量下的完整整数枚举
检查同一投影程序的最优性。

最终整数 counts 满足：

\[
\log(q_i/M)\ge\log p_{0,i}-\epsilon,
\qquad
-\log(q_i/M)\le-\log p_{0,i}+\epsilon
\]

对每个 anchor 严格正的事件逐项成立。证书保存实际的
`pointwise_event_nll_bound = logp0-log(q/M)`、最大增量、质量守恒和正支持检查。
零 anchor 的项不参与有限差比较；scalar JSON 将该项记为 null 并保存零 anchor mask。
独立验证用 90 位 Decimal logarithm 再核验最终整数质量的上述不等式。

该 floor 会提高极小事件的概率，因此它不自动改进概率校准、Brier、行动收益或能耗。
保护的是相对指定 anchor 的事件 logscore；它不能代替实验验收。

## 4. 数据流、owner 与证据边界

runtime 的明确顺序是：

1. 从已回读的事件 decoder 得到 proposal；
2. 用同一公开历史和冻结 anchor 计算额外参照；
3. 参数 guard 生成 Q24 Gaussian，再调用原 native typed owner；
4. 从原 native receipt 回读实际量化参数，重新检查参数身份和密度上界；
5. 保留原 native Q24 概率，另做 categorical guard 并交付 guarded counts。

原 Rust owner/journal/witness 绑定的是原 native 输出。最后一步是额外的研究 adapter
投影，必须由自己的 durable record／witness 绑定 anchor 身份、输入历史、原输出、
最终整数 counts 和校正证书。不能把原 Rust witness 冒称为最终投影的见证。

retention 中的 `protected_quantized` 和其独立 classical 对照，分别保留
Gaussian NLL、稳定 CDF 的连续事件 NLL，以及最终受保护 Q24 事件 NLL。
任何一个通过都不能替代另外两个，也不能把原未量化保护臂的门槛改名。

## 5. 独立验证与限制

```sh
python3 -m experiments.analytic_event_neuron.round2.independent_validation \
  --output /tmp/quantized-guard-validation.json \
  --work-dir /tmp/quantized-guard-native-evidence
```

验证保存真实 native journals／witnesses、原始 receipts 和逐文件摘要，包含：

- 数学域边界及随机参数上的 Gaussian 密度包络；
- naive 参数量化破坏包络的两个反例；
- 严格正极尾在 ordinary exp 下溢或 native Q24 为零时的修复；
- 受下限约束整数分配的独立穷举最优性；
- 实际 native ties-even、参数逐位一致和原生 CDF 相对独立数值积分；
- 参数／概率域拒绝和整数预算不可行时的失败行为。

验证 fixture 不含确认任务标签。原 native 二进制沿用已验证的构建产物，
本轮不声称重新编译。保护范围限定为这里明确的密度与离散事件 logscore，
不包含任意长期语义记忆、生产权限、跨 owner 原子事务或新的函数类。
