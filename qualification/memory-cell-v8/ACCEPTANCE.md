# Memory Cell V8：冻结协议的验收解释与结论边界

**本文解释现有冻结协议，不改变验收门。** 本文不修改任务、模型、训练配置、分区算法、阈值、成本权重、scorer 或发布权限；它规定已有结果可以支持哪些结论，防止把工程执行成功扩写成尚未建立的研究结论。

本说明在取得 CI02/CI03 完整原始材料前整理。更早的 CI01 未完成尝试继续保留，不作为完整参照矩阵，也不用于调整参数。逐项 retention 派生规则已记录于 [RETENTION_AUDIT_PROTOCOL.json](evidence/RETENTION_AUDIT_PROTOCOL.json)，只增加对既有测量的诊断，不替代冻结 scorer 的净变化旗标或 `NoChange` 门。

核心限制是：**当前设计可以验证训练后模型参与后续组合任务，并比较预先声明的策略；它不能单独证明梯度训练导致未来任务改善。即使 11 个 arm 全部正确，第 3 项的这一因果验收也不能自动通过。**

本文主要解释用户第 3、4、6 项验收。实际执行入口与材料格式见 [learning/README.md](learning/README.md)。任何通过率、净收益与执行状态均须以对应完整运行及原始收据为依据，本文本身不宣告一次运行已经通过。

## 1. 实际对照是什么

每个参数 arm 都先以全部当前来源训练四分片 bootstrap，执行一次 retention 和已完成访问前缀，再在同一 source cut、同一批事实之上 clean fit 候选。候选没有接收 bootstrap 参数，bootstrap 与 candidate 之间也没有新增记忆事实。future 只在候选安装之后执行。

这一顺序由 [memory_cell_prospective_support.rs](../../codex-rs/hepta-agentd/src/memory_cell_prospective_support.rs) 固定；父测试的库存、选择器与共同预算见 [memory_cell_prospective_tests.rs](../../codex-rs/hepta-agentd/src/memory_cell_prospective_tests.rs)。

| 待判断的命题 | 当前设计提供的证据 | 解释上限 |
| --- | --- | --- |
| 确实发生参数训练 | 真实 worker、初始与最终参数摘要、原始/native 参数一致性、步骤与训练诊断 | 参数更新确实发生；训练内损失下降仍是训练内诊断 |
| 训练后模型能用于后续任务 | candidate 的实际 native digest 绑定到 future 读出，结果从 owner 事实独立重算 | 已写入支持集合上的后续组合可执行 |
| 候选优于某个参照 | 同来源、请求和冻结预算下的 future 质量与成本比较 | 本次分区、重训、缓存和执行策略组合相对该参照的观测差异 |
| 梯度训练本身改善 future | 没有对同一 future cohort 执行未训练或停止训练的反事实 | 当前不能单独建立 |
| bootstrap→candidate 控制遗忘 | 同一 retention cohort 的前后观测 | 一次同来源切面的 clean refit / repartition 后，已测旧项目的保留变化 |

冻结库存中的 `fixed-4` 与 bootstrap 使用相同训练配置。只有在完整材料逐项证实参数、路由、catalog、阈值和预算等价时，才可把它解释为参数等价的四分片重建参照。它仍是已训练模型，不能变成未训练反事实，也不能把与它的差异单独归因于梯度训练。

分区变化同时改变 shard 内训练样本、catalog、实际参数规模与缓存行为。因此相同 shard 数下 learned 与 lightweight 的差异，仍是分区加重新训练策略的差异。相同 `total_hidden` 与训练上限不意味着实际参数字节严格相同；实际字节须按收据报告和计费。

## 2. 固定分子、分母与质量指标

以下规模来自冻结的 [memory_cell_prospective_batches.rs](../../codex-rs/hepta-agentd/src/memory_cell_prospective_batches.rs)，不随结果调整。

| 指标 | 分子 / 分母 | 支持的结论 |
| --- | --- | --- |
| Future 正确读取覆盖 | `status=ok` 且完整 typed value 正确的次数 / **72 次请求** | 后续读取的端到端正确覆盖 |
| Future 分类型正确覆盖 | Apply、Semantic、Procedure 各自正确次数 / **各 24 次请求** | 哪类读取发生改善或退化 |
| Future 接受后错误率 | `status=ok` 但值错误的次数 / `status=ok` 次数 | 已接受输出的实际错误；接受数为零时记 `null` |
| Future 失败构成 | abstain、stale、unavailable、budget_exceeded 各次数 / **72** | 区分拒绝、预算不可执行和返回错误答案 |
| Future 组合决策正确率 | 正确最终决策数 / **12 个组合任务** | 本次下游组合用途的成功率 |
| Future 各构造族正确率 | 对应正确决策数 / **每族 4 个任务** | 三种冻结组合方式下的观测表现 |
| Retention 读取前后 | 前、后分别正确读取数 / **各 24 次请求** | 同一旧 cohort 的读取变化 |
| Retention 决策前后 | 前、后分别正确决策数 / **各 4 个任务** | 同一旧 cohort 的下游决策变化 |
| Prefix 事件读取 | 正确 Current 数 / **96 次请求** | owner 事件观察前缀完成；不是参数学习增益 |

正确读取必须同时满足成功状态与完整 typed value 相等。预期值由已核验 owner 事实及注册 opcode 独立重算，不能直接相信保存的 expected answer 字段。正确决策要求实际 action 等于独立重算的 expected action；未形成 action 不能算正确。

不能只报告 `12/12` 决策正确而省略 72 次完整值的准确性。加和与阈值决策可能掩盖部分数值错误，一些 typed 字段也不进入该二值决策。最终动作正确不等于所有记忆内容正确。

11 个 arm 都完整执行时，可以把 792 次 future 读取执行、132 次组合任务执行作为工程执行量。但这些是同一 cohort 的多次参照执行，不是 792 个独立记忆样本或 132 个独立任务族。各 arm 的分母仍是相同的 72 次读取与 12 个组合任务，且实体/操作组合存在重复；不能通过跨 arm 合并分母扩大统计把握。

future 的三种构造是逆序、跨相邻访问组、交错访问组。任务构造虽未作为输入提供给训练 worker，却由作者预先编写；所有事实已进入训练支持集合，部分实体/操作组合已在 selection 或 retention 中出现。这里的后续评估隔离不等同于未知事实泛化或独立同分布总体抽样。

## 3. 第 3 项：训练收益、回放、校准与干净重建

### 3.1 可以报告的正结果

若完整实际材料支持，可以写：

> 候选在训练器未接收 future 请求或结果的条件下，完成了已写入支持集合上的后续组合任务，正确读取覆盖为 X/72，组合决策为 Y/12。

若预先声明的参照表现更差，可以进一步写：

> 在同来源和冻结预算下，本次候选策略相对该参照提高了后续任务正确覆盖，或降低了对应观测成本。

第二句话仍是策略组合的比较，不能缩写成“微调本身导致改善”。当前没有对同一 future cohort 进行未训练→训练的测量，也没有在候选 arm 中原样保留 bootstrap 并执行同一 future 批次作为同时对照。初始参数摘要、训练损失下降和训练内读回率不能填补这一缺失。

新的 prospective 试验使用 clean fit。retention 请求的重新执行，不应被称为参数 replay 训练。V7 既有真实 replay、纠错与撤销后 clean rebuild 的执行证据继续按其原收据解释，不能因本轮后续任务正确就扩展成已证明长期学习收益。

### 3.2 Retention 必须同时报告净变化与逐项转移

只有完整 11-arm 原始矩阵通过主 scorer 完整性检查，才执行 [RETENTION_AUDIT_PROTOCOL.json](evidence/RETENTION_AUDIT_PROTOCOL.json) 所定义的派生审计。所有 before/after phase hash 继续绑定原始材料。

读取以 `(record.request_digest, readout_offset)` 配对，共 24 项；组合决策以 `record.request_digest` 配对，共 4 项。每个 arm、每种粒度均保留以下完整转移表：

| 转移类别 | 定义 |
| --- | --- |
| `remained_correct` | before 正确，after 仍正确 |
| `previously_correct_became_wrong` | before 正确，after 错误 |
| `previously_wrong_became_correct` | before 错误，after 正确 |
| `remained_wrong` | before 错误，after 仍错误 |

设 `F = previously_correct_became_wrong`、`R = previously_wrong_became_correct`：

```text
after_correct - before_correct = R - F
after_errors - before_errors = F - R
forgetting_rate = F / before_correct
```

`before_correct` 为零时，`forgetting_rate` 必须为 `null`。**净变化为零，不代表 F 为零。** 一个旧项目变错、另一个旧项目被修好，可以使净正确率完全不变。

冻结 scorer 的 `retention_no_observed_regression` 只表示读取和决策的聚合错误数没有增加，不修改其含义。只有逐项 `previously_correct_became_wrong` 为零，才能写“本次已测、先前正确的项目没有变错”；同时必须给出先前正确项目数。若先前没有正确项目，该条件不能用作保留能力证据。

预算失败导致的旧项目退化，应称为端到端保留退化，不能直接诊断为参数知识遗忘。状态分类应与完整值正确性共同报告。

即使所有旧项目保持正确，这也只说明同一 source cut、完整旧来源仍被提供给 clean fit 时，一次重训和分区切换之后的情况。它不是跨多轮新增来源、长期预算竞争或来源删除条件下的遗忘保证。

### 3.3 即使 11 个 arm 全正确，也不能直接通过的部分

- 没有建立梯度训练对 future 任务的独立因果增益。
- 没有建立多轮新增信息下的长期遗忘控制。
- 固定 `0.5` 阈值与训练内损失不构成独立概率校准。
- catalog 和来源账本仍显式保留，不能称为参数独占存储或内容压缩。
- prefix 的 96 次 Current 读取来自 owner，不证明参数模型通过这些读取获得了未知知识。

## 4. 第 4 项：三种参照与完整成本门

冻结比较器见 [learning/costs.py](learning/costs.py)。三种参照对应不同问题，必须分别报告。

| 比较 | 可以支持的结论 |
| --- | --- |
| Learned 对 same-information lightweight prefix selector | 相对于预先声明的轻量选择器，访问分区学习与重新训练组合在本次的增量 |
| Learned 对 hindsight fixed inventory oracle | 是否越过冻结 1–8 shard 库存中、免收搜索成本的强保守门 |
| Learned 对 direct-owner | 在相同 typed 信息与注册操作上，是否优于实际精确 owner 读取参照 |

轻量选择器与 learned 使用同一个、只从 selection 批次得出的 shard 数，都有相同来源、前缀与 selection 信息可用。它们各自承担真实运行成本，并同样承担完整八候选搜索账。这一比较不代表穷尽所有可能的轻量算法。

固定 oracle 从完整冻结库存中事后选择，但只计自身 trial 与共同证据材料，免收选型成本；因此明确称为 hindsight oracle / conservative fixed hurdle，不能与同信息前缀选择器混称公平基线。

direct-owner 是预声明的强参照：通过真实 owner/control API 取得相同事实，使用前后重验来源 cut，并执行相同注册 opcode。它的缓存、来源账本、读取、通信和证据材料都计费；没有执行的训练、模型存储与模型搜索不应被虚构出来。

### 4.1 冻结的观测代理

以当前成本权重表示，每个 arm 的资源代理为：

```text
R_i = W_i + 100 * B_i + 10 * X_i + H_i
S = sum(R_fixed-k for k in 1..8) + selector_wall_ns
P_learned = 1_000_000_000 * future_decision_errors_learned + R_learned + S + C
P_lightweight = 1_000_000_000 * future_decision_errors_lightweight + R_lightweight + S + C
P_fixed-k = 1_000_000_000 * future_decision_errors_fixed-k + R_fixed-k + C
P_direct = 1_000_000_000 * future_decision_errors_direct + R_direct + C
gain_against_reference = P_reference - P_learned
```

其中：

- `W_i` 是完整 child lifecycle 的 ns，包含实际训练、读取、唤醒、IPC、发布、文件/fsync 与退出；不重复叠加内含阶段计时。
- `B_i` 是已定义的来源、artifact、原始实验材料、execution 文件及适用的 direct cache 逻辑 bytes。catalog/参数 payload 另列诊断，不能重复加入同一存储副本。
- `X_i` 是已观测的应用传输与训练/诊断 pipe bytes，不是内核帧或跨机器 wire bytes。
- `H_i` 是各进程采样点之前的观测 HWM bytes 之和，不是同时峰值，也不是 RSS×时间积分。
- `C` 是每个比较策略都承担一次的共同证据材料分数。

`gain_against_reference > 0` 只表示本次 learned 的冻结代理分数较低；负值须原样保留。若必要的观测成本为 `null`，代理总分及相关比较也不能通过填零得到数值。

### 4.2 结果出来后不能改变的口径

- 八个搜索 trial 的完整生命周期，包括其 future/retention 诊断，已计入搜索账。不得为获得正收益再扣除这些成本；同时明确这是保守完整实验账，不是部署必需的前缀选型成本估计。
- 不增加新的未来使用次数或摊销期限，把当前负收益外推成长期正收益。
- 不只挑一个预算不适配的固定 arm 作为“强固定结构”；比较对象是完整冻结库存的相应 oracle。
- 不因某个固定候选缺测而筛掉它、改选更有利的 oracle。
- 不把单次 CI 的时延差写成稳定的总体性能优势。结果限定于本次 nonce、任务构造、预算与执行环境。
- 不把所有 arm 的正确率都达到上限，解释为 learned 提高了正确率；此时能比较的是对应成本与执行差异。
- 任一 arm 未完成、绑定失效或数据不完整，都不能只保留成功 arm 做公平矩阵比较。

### 4.3 `NoChange` 保持不变

**即使观测代理净收益为正，完整成本门仍然是 `NoChange`。** 以下维度仍未完整观测：存储 byte-time、同时进程 RSS byte-time、父协调器完整簿记与最终报告写入时间，以及 HWM 采样后序列化/退出尾部可能出现的峰值。

独占通信时间继续为 `null`。总生命周期 wall 已含通信，无须用差值猜测一个独占项，也不能为它伪造额外零成本。

本轮没有执行 Rust budget proposal bridge，也没有由这份试验验收预算竞争→自主分裂/合并→独立接受→发布的闭环。代理结果和测试 fixture 的发布身份都不能授予这些权限。

## 5. 第 6 项：访问驱动分区与专业化迁移的区别

[learning/allocation.py](learning/allocation.py) 从真实完成前缀统计频率和共同访问关系，自动生成有界分区；[memory_population_learned.rs](../../codex-rs/hepta-neuron/src/memory_population_learned.rs) 独立复算该分区。它不需要为每个实体手写路由边，但相应结论仍须逐级满足。

1. **机制成立**：实际 V3 routes 通过原生复算，并绑定已核验的完成前缀与 source cut。
2. **实际结构发生变化**：learned routes 与同 shard 数的固定地址分区确实不同。若所选数量为 1，或 routes 完全相同，就不能称本次形成了新的分工。
3. **后续用途成立**：候选在三种冻结组合方式上的质量和成本实际测得。
4. **本次增量成立**：相对预先声明的同信息轻量策略取得相应观测改善，同时保留完整成本和 retention 结果。

即使四步全部成立，结论也只达到：

> 在已写入的有限 typed 支持集合内，根据访问共同出现关系自动形成了分片布局，并在本次后续组合任务中观察到相应效果。

当前四个访问组不是独立语义领域。三种 future 构造重新排列和组合已有实体与操作；值域和 opcode 由既有契约限定，任务使用显式受信 integration resolver。没有观测到新的 memory type、程序语义或任意功能图由系统自行生成。

因此不能从本轮宣称：

- 未写入地址或未见实体泛化。
- 开放自然语言任务族或新的语义领域迁移。
- 形成具有语义领域知识的专家分工。
- 取得任意程序学习、参数独占压缩或通用 memory system。
- 能够自发改写整张功能图并独立发布。

## 6. 用户第 3、4、6 项的最终状态表口径

| 用户项目 | 当前试验可以新增的证据 | 即使 11 臂全正确仍不能直接通过的验收 |
| --- | --- | --- |
| **3：参数训练、回放、校准、干净重建** | 真实参数使用、训练后 future 用途、同 cohort 前后及逐项保留审计 | 梯度训练导致 future 改善；长期遗忘控制；独立校准 |
| **4：分裂、合并、休眠、预算竞争** | 预声明结构库存和学习策略的实际质量、成本、负结果 | 超过强固定结构的完整成本净收益；自主结构行动闭环 |
| **6：新领域、新组合、新专业化迁移** | 观察驱动分区、已有支持集合的新组合用途 | 新领域泛化、语义专业化迁移、通用记忆涌现 |

“已实现”表示存在相应工程路径，“已验证”必须指向实际收据，“验收通过”还须满足该项完整判据。后续 DERIVED 仅从已经测量并核验的 retention cohort 计算逐项变化，不改冻结 scoring gate，不通过新分母、删去负结果或追加事后摊销来改变结论。
