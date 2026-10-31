# 第二轮：保留均值与不确定性的有符号事件状态

本模块解决首轮随机类别采样丢失连续幅值和条件方差的问题。已训练的
Gaussian driver 仍计算公开历史的条件分布；其 posterior mean 与 log-variance
通过有符号整数事件传给独立接收端。预测头从接收端的整数状态恢复条件分布，
再计算 put、neutral、call 终点概率。

这采用已有 sigma-delta／error-feedback 编码原理。O'Connor 与 Welling 的
[Sigma Delta Quantized Networks, arXiv:1611.02024v2](https://arxiv.org/abs/1611.02024v2)
已研究神经网络层间传送离散激活变化。本研究不声称发明这一编码原理，
也不把这类编码直接解释成新的概率函数类。

## 1. 状态、时间、事件和复位合同

编码目标为 `z_t = (m_t, log(v_t))`，初始先验 `z_0=(0,0)` 对应 `Normal(0,1)`。
两个通道分别有固定步长 `h_m,h_l`。编码端持有上次目标和舍入残差；接收端仅持有
整数累计 levels、逻辑 sequence 与物理 time。每次 active history update 执行：

\[
a_t=z_t-z_{t-1}+r_{t-1},\qquad
n_t=\lfloor a_t/h+1/2\rfloor,
\]

\[
\widehat z_t=\widehat z_{t-1}+hn_t,\qquad
r_t=z_t-\widehat z_t.
\]

运算按两个通道逐项进行。减去已发放的 `h*n` 是 subtractive reset；舍入残差
保留到下一次更新，没有独立 Bernoulli 类别采样。`n` 是有符号整数批计数，
可解释为同方向 unit events 的数量，但当前实现实际传输整数 packet。

Packet 仅包含版本、配置摘要、sequence、time、observation kind 和两个整数 counts。
不存在逐例的连续均值、方差或 residual 旁路。接收端自己累计 counts，得到：

\[
\widehat m_t=h_m L_{m,t},\qquad
\widehat v_t=\exp(h_lL_{l,t}).
\]

共享的训练参数 drift 和 process variance 用于目标期限传播：
`mean(horizon)=decoded_mean+drift*horizon`、
`variance(horizon)=decoded_variance+process_variance*horizon`。
它们是冻结模型配置，不是逐例连续信号。

`observed`、`missing`、`propagation` 是三个显式信息状态。物理 time 可以相同，
以允许同时刻修复观察；逻辑 sequence 必须逐一递增。不存在观察的 padding 不产生更新。
缺失观察依然可能因时间传播发出事件。两个 counts 都为零意味着编码器没有越过
量化边界；它不表示 neutral 事件发生，也不表示缺失观察。

终点 call/put 是解码条件分布上的事件。均值通道的正 count 不意味着最终 call 发生；
log-variance 通道的正 count 表示不确定性增加，也不是神经元 confidence。

## 2. 误差界和等价对照

精确算术中，用上述 residual invariant 归纳可得：

\[
z_t-\widehat z_t=r_t,\qquad -h/2\le r_t<h/2.
\]

因此每次更新均满足：

\[
|m_t-\widehat m_t|\le h_m/2,\qquad
|\log v_t-\log\widehat v_t|\le h_l/2,
\]

\[
e^{-h_l/2}\le\widehat v_t/v_t\le e^{h_l/2}.
\]

它们不随更新次数线性累积。浮点实现保留编码残差并单独验证舍入容差，
没有声称任意浮点序列上的位级实数算术定理。加入共同的非负过程方差 `q*dt`
不会增大 log-variance 相对误差；均值传播保留相同的绝对编码误差。

令 `F(k;m,v)=Phi((k-m)/sqrt(v))`。由 CDF 对均值及 log-variance 的导数界，
任意有限阈值均满足：

\[
|F(k;m,v)-F(k;\widehat m,\widehat v)|\le
B:=\min\left\{1,
\frac{|m-\widehat m|}{\sqrt{2\pi\max(v,\widehat v)}}+
\frac{|\log v-\log\widehat v|}{2\sqrt{2\pi e}}
\right\}.
\]

证明中先在较大的方差下改变均值，再改变 log-variance；
`sup_z |z*phi(z)|=1/sqrt(2*pi*e)`。put 和 call 的绝对概率误差各不超过 `B`，
neutral 区间误差不超过 `min(1,2*B)`。极小方差时该界可接近 1，
它不保证极尾相对误差、NLL、校准或决策收益。

`event_direct` 每步独立计算 `floor(z_t/h+1/2)`，再发出相邻整数 levels 的差。
精确算术中它与 error-feedback 的解码状态完全一致。这是强制保留的负对照；
两者相符不能用于宣称结构性统计优势。

`event_no_residual` 对每次增量单独舍入并丢弃 residual。每步增加 `0.49*h` 时，
它可以始终沉默而使累计误差增长；保留 residual 的版本不会出现这种无界误差。
此反例只识别编码机制，不能替代真实任务上的收益比较。

## 3. 有效域与持久化

该 log-variance codec 接受有限 mean 和严格正的有限 variance，
并将 log-variance 限制在 `[-600,600]`。零方差点质量仍由上一轮解析核处理，
不能偷偷塞进 log-variance codec。步长必须有限且属于 `(0,32]`。

默认单通道一次 count 的绝对值最多 `2^31-1`，累计整数 levels 的绝对值最多 `2^52`，
解码 log-variance 的绝对值最多 700。超出数值范围、乱序、重复、配置不匹配及
不一致的 residual checkpoint 均拒绝。拒绝的更新不改变已提交编码器状态。

`EventDecoder.snapshot/restore` 是只包含解码状态的版本化格式。
`SignedEventNeuron.snapshot/restore` 另保存编码端的 last_target 和 residual，
以便恢复后产生相同的后续事件。恢复能力不等于文件真实性证明；
防回滚和完整性须由外围 journal/witness 及其身份绑定保证。

## 4. 训练与冻结

`fit_event_models(models, development, driver_training_receipt=receipt)` 接收首轮同接口
实际训练的连续 Gaussian driver。receipt 绑定初始／最终参数、参数变化、优化器状态、
原训练回执摘要和完整 objective trace 摘要。这里没有把一套手设参数称为已训练模型。

随后只用 development 数据选择两个编码步长。默认各通道候选为
`[1/128,1/64,1/32,1/16,1/8]`，共 25 个组合；首先要求相对冻结 driver 的
development composite NLL 劣化不超过 `0.002`，再选 logical unit counts 最少的组合。
若无组合满足，保留该失败并选择 NLL 最低候选，不把预算状态改为通过。

三个机制臂使用相同 driver、步长和规划参数。根运行器还保留首轮随机 pulse、
mean-drive、取消复位、完整历史、原生 sparse 与独立 dense Gaussian/probit 对照。
step selection 是离散开发集模型选择；本模块没有声称训练了穿过硬事件的梯度，
或给出了全局最优 SNN。

编码精度非劣门槛和原来的脉冲收益优势门槛分开验收。
即使新编码相对连续模型几乎无损，也不能把原先 `>0.01` 的收益优势门槛改成已通过。

## 5. 成本与可复现验证

每条历史记录更新次数、非零通道数、logical unit-event 总量、序列化 packet bytes
和最终状态摘要。整数批计数不能等同为一条硬件 spike 的成本。
编码器仍运行完整 Gaussian filter；本模块没有证明省去了该计算，也没有硬件能耗声明。
实际文件、原生调用与端到端 wall/CPU 成本由根评估器和 runtime bridge 另行测量。

开发验证入口：

```sh
python3 -m experiments.analytic_event_neuron.round2.pulse_validation --output /tmp/pulse-validation.json
```

验证包括 4096 次非平稳更新的误差界、独立绝对量化参照、五次 checkpoint 续接、
2000 组独立 CDF 误差界检查、丢弃 residual 的反例、缺失／静默语义、失败事务、
真实 driver 拟合和只经 packet 重建的预测。训练／开发 fixture seeds 为
`87301/98301`，训练初始化 seed 为 `7301`；未生成或读取第二轮确认数据。

这些验证建立数值与执行合同。跨任务收益、长期保留、漂移泛化和生产晋级
均由独立的冻结确认实验决定。
