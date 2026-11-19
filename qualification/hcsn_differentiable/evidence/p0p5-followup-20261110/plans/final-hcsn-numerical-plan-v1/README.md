# HCSN 终态 checkpoint 的受限数值审查计划

**这是执行前冻结的计划，尚未读取六个 HCSN 训练任务的终态模型，也不授予任何数值或科学资格。**
机器可读的完整条件、输入身份、固定 gap 列表和预算位于 `PLAN.json`。
它独立于已经封存的 P0/P1 与 36 个基线加 7 条 C1 续训链证据，后续实际结果另建子包。

## 何时读取模型

先取得原进程的真实 terminal 证据，再检查稳定的报告和 checkpoint。
正常完成的任务、因 soft wall 停止的任务、被截尾的任务分别保留原始状态。
有完整报告、源码绑定和完整 epoch checkpoint 的已终止任务，可以进行“已训练 checkpoint 的受限数值审查”；
这并不说明训练充分，也不把失败或截尾的任务改写为完成的续训 parent。
硬杀且缺少完整结果、来源不完整或 checkpoint 仍变化时，保持 HOLD。

六个候选固定为 seeds 101、211、307 与 LR .001、.003 的笛卡尔积。
每个可审候选都按其完整 epoch 的 D macro-F1 首个严格最大值绑定 `best.pt`；
另绑定 `last.pt`、真实 epoch/update 数，检查最终更新后的状态。
共同 LR 仅由三个 seed 的 D 均值决定，数值检查结果不能影响 LR 或候选选择。
缺少候选或独立 D 指标时，选择保持不完整。E 不访问。

## 原训练记录能够说明什么

独立源码审查原件保留在本包的 `recorder-scope-*` 文件中。
4096 是 `(time position, layer, microbatch)` 向量记录上限，每条最多 8 个有效样本，
所以最多记录 32768 个样本时点。实际训练每 epoch 有 89216 个事件；
即使字节上限从不触发，这也不足一个 epoch，对 30 epoch 的覆盖上界只有 **1.2242946%**。
32 MiB 上限可能使实际覆盖更低。

这是一段按时间顺序保留的前缀，不是随机抽样。记录发生在 main microbatch forward 完整返回后、
该 update 的 optimizer.step 之前；诊断和 D 评估没有记录。成功记录也不证明随后 backward 或 step 成功。
原 trace 不含 content state，model digest 仅覆盖内部 network tensor，而非完整 wrapper。
真实 retained/seen/dropped 数量、触发何种限额和最终 footer 必须等任务真正终止后读取，不能从上限推断。

原 trace 的完整性和 ledger 会审查；原始前 16 条保留向量记录沿用现有 `audit_trace` 做有限数值复核，
明确报告实际 batch 样本数和未覆盖部分。截断或只审前缀的 trace 继续保持整体训练域 HOLD。

## 固定 checkpoint 的补充重放

每个 `best.pt` 固定重放 A01-0、A01-256、A04-3072、B01-0、C01-0、D01-0。
六个候选全部可审时共 9216 个有效样本时点；每个 `last.pt` 另重放 A04-3072，最多再加 1536 个。
所有 episode 原始 SHA、partition、256 个真实 gap 都已在模型读取前确定。

重放使用实际 v8 full wrapper，保留 frozen frontend/head、学习后的 adapter/core、valid mask 和 exact GridSpec。
应优先在原训练 runtime 导出实际 posterior，绑定模块实际加载路径、依赖版本、checkpoint 与完整 wrapper digest。
独立高精度阶段可以在另一已记录 runtime 处理这些不可变的 law；跨 runtime 重新产生的模型状态必须单独标注。
同一次 wrapper 返回的 trace 和 recorder 记录要逐元素一致。缓存建立时间和内存计入审查开销。
补充可观察的 content/state 有限性检查与原训练缺少 content 记录是不同证据，不能补称历史覆盖。

这些都是终态固定模型的**补充评估**，不会补全原训练轨迹，也不冒充训练访问过的最后更新后 posterior。

## 数值对象与阈值

对导出的概率状态检查非负、归一化、padding 排除、一步事件/计数一致性，以及 tail、首格和 refractory phase 的质量。
独立 80 位 continuum 基底与有限差分用于实际固定物理参数的基底导数；每个 posterior 的权重固定后再比较加权导数。
这不证明通过 learned observation/content update 的完整端到端梯度，也不授予可学习物理参数全域资格。

log F / log G 使用独立 80 位反射公式和导数，在实际 gap 与空间支撑探针上检查。
概率下溢时仍保留有限 log 值；分别报告 log 绝对误差、概率绝对误差与相对误差。
零 deadline 单列其概率 0、log 概率负无穷的定义分支，不将它算作数值故障。

每个 best 模型固定九个有限 schedule，六个模型共 54 个：此前 width16 的五个 A 系列案例、
B/C/D 各一个 32-gap 案例，以及 A01-0 的 255-gap 案例。
每个 last 模型另做真实 burst8，共最多 60 个有限案例。
每个起点必须来自实际导出 posterior，完整 future gaps、grid、物理参数和 reward/reset 配置都参与哈希。
未来 observation update 关闭，因此比较的是该真实起点分布的有限再生传播，并非整个观测任务的概率 oracle。

比较 value、event count、discounted event count 和 active probability，保留原门槛：

- `abs(candidate-reference) / max(1, abs(reference)) <= .01`；
- 80 位参考，Gaussian order 8 与 16 的敏感性不超过 `2e-8`；
- 概率质量残差不超过 `5e-11`。

当参考值小于 1 时，这个门槛检验的是绝对误差，不能称为所有量的 1% 相对误差。
报告另列绝对误差与可定义的相对误差。Order doubling 是实测敏感性，不是严格参考误差界。
128/255 gap 案例会检查多次再生的实际 reference count；只有 count 支持时才称其包含多次发放。

原 A04 两个极短 gap 的无限重复压力失败、135 个旧压力配置失败、N128 有限 count 失败以及旧 exit137 的未知原因都保留。
新的有限 schedule 通过不会擦去这些结果。压力复核只用于预先声明的三个 sentinel，不将无限重复构造冒充真实时间序列。

## 执行、资源与结论边界

单 worker、单 CPU 线程、FP64；每阶段最多 900 秒，整个审查最多 10800 秒，RSS 上限 2 GiB、地址空间上限 8 GiB。
任何超限都保存已有证据，将未完成案例标记为未测/HOLD；不得因为结果不好而放宽阈值、删候选或默默重试。
source-frozen 的执行 wrapper 和必要的输入绑定测试要先完成，随后才能读取终态模型执行本计划。

每个阶段保留源/模型/数据/配置/原始日志、完整外层 wall、waited CPU、RSS、缓存成本和 UTC 并发区间。
原训练、诊断、失败重试与本次数值审查分别记账；嵌套计时不相加，能量不推测。
全部结果仍区分任务 completion/censoring、训练充分性、有限数值资格与科学收益。
成功结论最多是精确模型和列明 fixture 上的受限资格，原训练全域和科学收益继续独立评估。
