# 持续原首达／复位比较：严格结论仍为 HOLD

本轮回到原始 IG 首达／复位／恢复期过程，完成跨观测 tick 保留状态的 GRU／SSM、同信息 latest-packet MLP、原控制器四格比较，以及固定规模的新独立确认。**固定 384-world 确认没有建立解析核心的稳定正向净增益。** 它没有接入新独立 AV 录制，也没有替换生产 Rust 神经元。

| 384-world 固定确认 | matched 均值 | 双 primary 调整后 97.5% 区间 | hidden refractory mismatch 均值 | 次要 95% 区间 |
|---|---:|---|---:|---|
| D−B：解析相对所选持久普通核心 | +0.00609375 | [−0.01327096, +0.02486484] | −0.00405208 | [−0.01990651, +0.01110443] |
| D−M：解析相对同 packet 学习 MLP | +0.00173958 | [−0.01647943, +0.01929206] | −0.00714583 | [−0.02397917, +0.00871901] |

两项 matched primary 都没有通过各自调整后的正向下界门槛。mismatch 两项点估计为负，区间也跨零。A/B 使用普通持久模型，C/D 使用解析 renewal；A/C 为原轻量控制，B/D 为同一原任务价值控制。M 使用同一任务价值控制。这里的净收益始终是四次输出平均准确率减实际 READ 费用，CPU 单独记账，未换算进效用。

| 固定确认的描述性分解 | B 准确率／READ 次数 | D 准确率／READ 次数 | M 准确率／READ 次数 | D−B 准确率差 | D−B READ 费差 |
|---|---|---|---|---:|---:|
| matched | 0.87890625／2.750000 | 0.88541667／2.760417 | 0.88359375／2.758333 | +0.00651042 | +0.00041667 |
| hidden mismatch | 0.87500000／2.712500 | 0.87369792／2.781250 | 0.87838542／2.719792 | −0.00130208 | +0.00275000 |

解析 NLL／Brier 在两条件的点估计较好；这没有替代准确率、实际 READ 后果和未通过的净效用比较。上述分解由独立审核器从 raw 重算，属于描述，不添加新的通过声明。

任务价值控制的描述性收益在两类核心上都存在：matched 下 B−A=+0.04897917、D−C=+0.03557292；mismatch 下分别 +0.05448958、+0.03098958，描述性 95% 区间的下界均大于零。它们属于冻结的次要比较，不等同于解析核心的独立增益。持久普通核心相对 MLP 的 B−M 两条件均为负点估计，描述性区间跨零。

H 从可见 READ 历史重建最新 packet 并按同一解析律重算，与 D 的全部概率、动作和收益完全一致，最大概率误差 0。**H 仍使用解析算子**；这个等价说明本声明模型内持续隐藏状态的实现不是质量所必需，不能用来宣称移除解析算子本身没有影响。MLP 才是不使用解析传播算子的学习参照。

## 训练、扩预算与独立确认

五个拟合种子分别训练 GRU、SSM、MLP，各有宽度 16、32，共 30 个候选；每个种子 512 条训练序列、192 条独立验证序列，随机缺测和读取计划在候选之间共用。训练至少 80、最多 320 epoch，40 epoch 没有达到 1e-4 的验证改善时早停。选容量、epoch 和普通模型族只使用验证集；五种子的所选普通族均为 SSM。模型强度资格仍限于本轮容量、数据和拟合范围。

首次有三个 SSM 候选在 320 epoch 未达到预定 plateau，因此追加了一条 **validation-only 扩预算规则**：只扩展 `(100107,ssm,16)`、`(100113,ssm,16)`、`(100113,ssm,32)`，最多 960 epoch，其余 27 项不重训。它不是最初预注册的一部分。三项重启时逐值核对首 321 个验证值和 epoch320 最佳权重，再继续；分别在 338、361、350 epoch 达到相同 plateau 条件。现 30/30 候选满足登记的停止规则。独立审计确认其余 27 个权重哈希和所有训练数据哈希保持不变。

扩预算冻结并执行完成后，先在新的 48-world 留出集中完整比较。因区间仍宽，再追加一次固定规模的独立确认：192 world／condition，共 384 个世界、8 个 shard；最多 6 片并发，所有片全部执行，按结果决定继续或停止的规则不存在。训练、选择和模型哈希完全保持不变；新 seeds 预先排除训练、验证和前两批世界。

这次扩大样本量属于**看到先前区间宽度后制定的新确认设计**，不是最初预注册。matched 的 D−B、D−M 是两个 primary，各报告 97.5% 双向 crossed world×fit percentile-bootstrap 区间，按 Bonferroni 的整体 95% 描述性覆盖目标处理；mismatch 为次要 95% 描述。全部模型共用成对世界，独立单位是世界和拟合种子，不能把 52,224 个强制输出当成独立重复。bootstrap 近似与只有五个拟合种子的限制保留。

| 结果批次 | 独立世界数 | matched D−B | mismatch D−B | 状态 |
|---|---:|---:|---:|---|
| development002 | 48 | −0.01866667 | +0.01266667 | 三候选到预算上限，原始结果保留 |
| extension001 新留出 | 48 | +0.02266667 | +0.02650000 | 验证停止条件已满足，两个区间仍跨零 |
| confirmation001 固定确认 | 384 | +0.00609375 | −0.00405208 | 两 primary 调整区间跨零，未通过 |

这些批次使用不同世界，点估计变化不能归因于扩预算的因果效果。全部负结果和先前成本保留；固定确认结束后没有再追加样本或更改模型。`results/TEST_ACCESS_LEDGER.json` 与确认目录内的同名记录固定核心所有者首次查看效果的时机；不假定其他代理完全盲法，扩预算的规则和三个名字只依赖先前验证预算耗尽。

## 实际工程闭合与检查范围

原过程、信息边界和 source extraction 见 [METHODS.md](METHODS.md)。READ 一 tick 后到达，不重置世界；STOP 关闭后续感测，四个强制输出仍执行。GRU／SSM 跨 tick 和 READ 保留 hidden state。共同 head 对 fresh READ 返回完美感测 one-hot，首次 READ 前保持平稳均匀先验。该完美感测语义不能直接作为真实 AV 前端的资格。

六项行为／数值检查通过：多类 BPTT 独立有限差分、分支隔离和状态持久、前缀因果、精确历史等价与原控制器候选值对照、共同完美 READ head、优化 forecast 与 literal tick 推进逐值等价。旧首次五项检查和源快照也保留。

三批合计 480 个新世界、16,320 次完整运行、65,280 个强制输出、342,720 个 tick state。独立审核器不导入候选实现，重建实际状态、概率、READ 准入、head 和评分，并核对保存候选值与所选动作的一致性；它没有完整重跑每一个随机假想 planner。原控制器候选值的逐值对照属于前述行为检查，其覆盖范围不扩大为全程序证明。

固定确认的独立重算已完成：13,056 个运行、274,176 个 tick state、52,224 个强制输出全部核对，最大 hidden-state 误差 0。检查还确认所有选模及 checkpoint 哈希不变、新世界与排除来源不相交、两个 primary 的调整区间及次要区间均可重算；结论仍为两个 primary 未通过。

## 证据入口

- 原始冻结、物理定义 AST 来源与候选记录：`results/development002/`。
- 三个验证扩预算及新留出：`results/extension001/EXTENSION_PLAN.json`、`EXTENSION_RESULTS.json`、`SUMMARY.json`。
- 固定确认：`results/confirmation001/CONFIRMATION_PLAN.json`、`WORLD_SEEDS.json`、`SHARD_MANIFEST.json`、`PAIRED_CONTRASTS.npz`、`SUMMARY.json`，以及八片原始 `worlds.jsonl.gz`／`runs.jsonl.gz`。
- 独立审计：相邻 `review/RENEWAL_RECONSTRUCTION.json`、`RENEWAL_EXTENSION_RECONSTRUCTION.json`、`CONFIRMATION_RECONSTRUCTION.json`；各报告附实际使用的独立源快照。
- 逐阶段成本：相邻 `economics/results/` 内的 `PHASE_RECEIPT.json`；唯一可加 CPU 字段是外层 `outer_wait4_cpu_seconds`，内层 worker／observer 字段已经包含。

首次准备、验证、原 30 候选拟合、旧测试、三项重复前缀与扩展、新测试、八片确认、聚合和审计都保存成本。八片确认合计外层 CPU 为 1300.307611 秒，实际并发 wall span 为 631.716058 秒（10.53 分钟，超过先前估计）；各片 wall 的和不是整个 batch elapsed。完整进程族连续内存峰值、可归因设备能量、源编写／工具传输和部分历史准备成本仍没有完整归因，因此没有完整执行经济性通过声明。当前环境元数据见 `ENVIRONMENT.json`。

本线 22 个互斥阶段的外层可加 CPU 合计 **1782.808860 秒**，包括全部前置检查、重复前缀、两批旧留出、八片固定确认及三次独立审计。`COST_SUMMARY.json` 仅是这些现有收据的子集汇总，不是额外 CPU 账项，也不能再与同一全局 ledger 重复相加。阶段 launcher 自身导入与最后收据写出等边界外工作仍明确排除。

## 重放

从仓库根目录，保留现有全部结果，在新目录重放固定确认（模型和命名空间保持原身份，重放无需重训）：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v10_closure_20261101.persistent_renewal.confirm prepare --base experiments/hcsn_v10_closure_20261101/persistent_renewal/results/extension001 --output /tmp/hcsn-renewal-confirm-replay
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v10_closure_20261101.persistent_renewal.confirm shard --output /tmp/hcsn-renewal-confirm-replay --shard 0
```

对 shard 1–7 执行同一命令，全部成功后运行 `confirm aggregate --output /tmp/hcsn-renewal-confirm-replay`。外层成本需按本轮同样方式包裹计量。逻辑世界、概率和动作可按冻结种子、模型及软件环境重放；时间字段、压缩头与计时会变化，交付哈希固定的是本次原始字节。

已闭合的是原有限过程的持久执行、明确的信息边界、全部候选达到登记的验证停止条件、固定规模独立确认和可复核记录。**解析核心稳定净增益、强普通模型的一般资格、真实独立 AV 前端、完整机制必要性、完整经济性和生产采用资格仍保持未通过。**
