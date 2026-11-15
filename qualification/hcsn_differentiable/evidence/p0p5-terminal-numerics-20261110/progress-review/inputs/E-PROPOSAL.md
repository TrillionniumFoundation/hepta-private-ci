# Confirmation-E 候选方案：保留正式协议，暂不解封 E

**状态：只读协议研究后的候选草案。没有 E 数据访问、模型读取、评价执行或自动启动门。**

当前应继续保留 E。等六条 C2 续训全部终态、独立恢复链与质量复放审核完成，再由根任务判断是否值得消耗这次不可回收的确认机会。满足下面的必要条件也不自动授权执行。这个候选不属于现有 1,800 秒 C2 终态审计预算。

## 现有协议已经规定什么

既有 [formal_protocol.json](source-context/formal_protocol.json) 的正式路线是：每个模型家族用 12 个学习率、衰减和裁剪组合，每个组合用 3 个 tuning seeds；在 D 上选定配置后，以 **11、23、37、53、71 五个全新初始化种子**重新训练。温度校准只用 D，E 作为单独受试者确认；所有模型使用相同的 256-event 非重叠 episode 语义。这里的五个种子并不是当前 101、211、307 的别名。

当前 [v3 说明](source-context/localization-v3-README.md) 与 [42-fit 计划](source-context/campaign-v2-plan.json) 明确是另一条较小的 development study：7 个 temporal cores、2 个学习率、3 个种子、固定公共接口及可学习 adapter。C1 与 C2 又是分别针对原 epoch cap 和原软 wall cap 的后续阶段。它们都必须按实际额外训练、恢复、记录和失败成本记账。

| 项目 | 从既有正式协议沿用 | 当前 v3 / 本候选的实际边界 |
|---|---|---|
| 受试者划分 | ABC 训练，D 选择及校准，E 独立受试者检验 | E 至今未作模型评分；既往 schema、时钟和全局 gap 审计暴露仍须披露 |
| 输入与时间 | ABC-only normalization；12 坐标、12 mask、log1p(dt)；原始 tick/source-row 顺序 | 复用实际训练时的冻结 frontend，绝不在 E 重估均值、方差、类别权重或时间规则 |
| Episode 语义 | 全事件，256-event、stride 256；每个 episode 重置；人工边界保留原 first gap | 所有 7 cores 一致；不给 HCSN 或普通 recurrent core 额外历史；不删短尾窗 |
| 训练选择 | 用 D 在调参种子间选择配置，不用 E 选择 | 实际 v3 对每个 fit 保留 D 的首次严格最大值 checkpoint、三个种子共同选择一个 LR；当前仅 2 LR×3 seeds，两 LR 的全部失败、已用资源及删失都保留 |
| 新训练种子 | 原正式协议要求 5 个 fresh confirmation seeds | 本候选只考虑已有 3-seed 模型的一次 E 检验；**不能声称完成了五种子正式确认** |
| 训练批次与配方 | 原正式方案声明 batch1、相应容量及调参配方 | 实际 v3 为 effective batch32，HCSN 的训练 microbatch8，评价 batch32；本候选只重放既有系统，不追认其为原正式配方 |
| 模型容量与控制 | 正式路线要求已获准 HCSN 容量参考、参数范围及机制消融 | 当前 width16/公共 adapter 的接口控制不自动完成该容量资格与消融要求 |
| Baseline 身份 | 明示各实际实现 | 当前含 analytic event-time LIF，不冒称 EventProp；S4D 不冒称 Mamba；CPU FP64 attention 不冒称优化 GPU 对比 |
| 预算 | 全部调参、失败、数据、校准、评价成本 | C1/C2 为新增阶段；原 300/900/1800 秒曲线保持不变；能源、显存、货币成本缺失继续为 null |
| 科学信用 | 独立检验与训练、数值、机制解释分别记录 | 一次 E 得分不能修复未获准的数值域、缺失机制消融或未执行的正式训练配方 |

因此有两个未来选项。**默认选项是继续封存 E**，等待判断当前结果是否值得进入确认，或先完成更充分的正式配方。另一个选项是下面这个有界的“当前已训模型的独立受试者 E 检验”。它是一项明确追加的研究，不覆盖、不追认原正式协议。

如果选择后者并观察 E，之后再补训五个种子不能把同一个 E 重新称为从未接触的确认集。后续研究必须披露这个历史，或获得新的独立数据。E 检验只有在计划、源码、选择和预算都冻结后才有意义。

## 执行前的必要条件，以及仍保留的人为决策

1. 六个原 HCSN 及六条 C2 机会均已有真实终态，未知 launch/PID、缺失 terminal receipt 或正在写入的文件全部阻断；所有完整、失败和部分更新的成本都已保留。无退款。
2. 冻结的独立 C2 auditor 对恢复 witness、父 partial work、不可变 epoch commit、源/模型/配置/数据身份和全 D strict-best 复放给出可审查的终态。审计器自身超 wall/RSS、来源变化或漏项均不能授信。
3. 对每个候选 family，按冻结规则对两个 LR 的全部三种子 D 成绩做一次 common-LR 选择，不按 seed 各挑 LR，不用最好的一个 seed 代替期望质量。两个 LR 任一必要结果缺失则不能偷删该项来完成选择。
4. 每个选定 LR 的三个种子均通过已有的训练充分性启发式：训练-only memorization、至少 30 个完整 epoch、.002 / patience10 的 plateau、完整有限梯度/更新及来源链。HCSN 还需独立链审计支持该状态。**这不是全局最优或绝对充分训练的数学证明。** 如果最高均值 LR 含不充分种子，不能临时改选较差但合格的 LR 来解封 E；整体保持 HOLD。
5. 所有待比较 baseline 也必须满足同样的 selected-three-seed 条件。复用先前 36 baseline / 7 C1 的独立审核，并披露 C1 没有保存第一次恢复 step 前状态、只能审查现有终态不变量和冻结实现的限制。不能只检查 HCSN，忽略比较对象的不足。
6. 根任务审阅 C2 的质量增量、全部费用、未关闭的数值问题及科学价值后，另写明确 decision，绑定这份计划最终版、程序 SHA、全部 checkpoint/config、D 选择结果和独立预算。**此第六步始终是单独决策，不由前五步自动触发。**

未通过任何一项就不读取 E，也不生成 E 子集、标签分布、难例或试跑成绩。当前草案中所有待选 LR、checkpoint、temperature、E event count 都为空，不预读真实 C2 输出来填它们。

## 如果将来批准：一次固定选择，完整 21-model 评价机会

固定 7 cores：GRU、CfC、PLIF spike-trace、event-time LIF、S4D、attention、HCSN。每个 core 只评价其 D-selected common LR 的 101、211、307 三个种子，共 21 个已有模型。保持此固定顺序，单 worker、单 CPU thread；不得删除失败候选、替换 seed 或改用 last checkpoint。原 42 fits、C1/C2、PLIF 额外 tuning 和 HCSN 数值资格费用仍全部属于成本背景，不因仅有 21 个 E 评价而消失。

在任何 E 读取之前，封存一份选择 manifest：两个 LR 的全部 D 记录及未通过项、每个 family 的 selection 算式、三个 strict-best checkpoint 的字节 hash、完整 construction config、运行时/依赖/源码、共享权重 hash，以及最终温度参数。选择过程中不得查询 E。两个 LR 的三种子均值若精确相等，沿用已冻结资源分析与 C2 审计器的确定性规则，取较低 LR .001；这是当前 v3 分析的 tie rule，不冒称与正式方案的容量/计算量 tie rule 相同。

温度拟合沿用正式协议的 D-only 原则，可用已独立核验的 D logits，不再训练模型。候选确定实现为在逆温度 β∈[.01,100] 上最小化未加权 D NLL：导数是平均预测 logit 减真实类 logit，二阶导是 softmax 下 logit 方差，故一维目标凸。用最多 100 次二分导数求根，在 bracket 宽度不超过 1e-12×max(1,|β|) 或没有可表示的内点时停止，记录端点导数与最终 bracket；只有每行 logits 的所有类别精确相等时，采用平坦目标特例 β=1。端点满足最优方向条件则保留端点并记录，不扩区间、不多起点、不看 E 再改算法。T=1/β，正温度在精确算术中不改变 argmax，实际 raw/calibrated 预测也须逐项相同。这些数值算法细节是本候选新增选择，不宣称原正式协议已经指定。温度选择、数值检查及其成本在 E 解封前封存。失败时整体 HOLD。

E featurizer 必须新建独立路径，不能修改或复用 ABC/D manifest 来冒充 E 来源。它先核现有 official archive/text/description SHA，使用现成 ABC frontend，按 E01–E05、整数 tick、source row 排序；从每段开头以 256 stride 划分全事件。每个自然序列第一项 dt=0；其他 episode 首 gap 仍来自原序列前一事件。保留所有原事件、重复 tick、尾部短窗；不能 clip gap、补采样、按标签选窗或调整 reset。既往全数据 clock/gap 审计的暴露仍在 E报告中单列。

建议将 feature/order 与 label payload 分开封存。预测 workers 只用输入、时间、真实长度和 padding mask，不能读取活动标签；有效位置可用 dummy label 生成 mask，不参与任何模型更新。21 个完整 logits 文件全部封存后，才由独立 scorer 连接 E 标签与相同 source-row order，进行一次评分。若某模型未完成，保留失败和费用，整组不作优胜结论；不得趁其余结果已可见而重选模型或放宽预算。

每个模型仅一次全 E forward，CPU FP64、batch32、no_grad、冷 cache、完全相同 episode 重置语义。不构造/恢复/step 优化器，不 backward。首尾核 checkpoint、源和输入 SHA，保存完整 logits、每行标签/episode/position/source row、batch 费用、完整 stdout/stderr、exit rusage/RSS 以及独立外层 receipt。E 不进入 calibration、loss weighting、early stop、feature fit 或选择。

## E 评价前固定的输出与解释

主结果为每个种子的全 E **11 类 macro-F1**、accuracy、混淆矩阵和与 GRU 的 seed-paired F1 差值；其余 5 个 comparator 的 paired 差值也完整报告，不依 E 临时选对手。并报告 balanced accuracy、present-class F1 作为次指标，以及 raw / D-temperature-calibrated NLL、15 等宽 ECE、half-sum Brier 与 mean-class Brier；明确各 Brier 归一化。正温度校准的 raw/calibrated 类别预测必须一致。

保存全事件汇总和 E01–E05 各序列结果，同时展示三个种子原值、均值及 sample SD。三个 tuning seeds 的结果只描述这些已有初始化的变异，不冒称五个全新 confirmation seeds。不要把每个 episode 或事件当独立重复训练。

本候选固定 5,000 次整序列 cluster bootstrap，固定统计随机种子 20261110，重采样 E 的五个完整序列并保持所有模型、三 seed 的配对；先汇总重采样的原混淆矩阵，再算各 seed 的 macro-F1 与三 seed 平均 paired 差值，给出描述性 2.5%/97.5% percentile 区间。具体随机数与分位数规则见 PLAN.json，不能在看到区间后改抽样单位。该区间只有一个 held-out subject，不能解释为总体受试者泛化区间。三 seed 的符号置换只有 8 种，双侧最小离散 p 值为 .25；本候选不据此宣布显著优胜，也不将大量相关事件伪装成统计功效。

只有全部 21 个预定结果和门完整时，才给出完整比较表。一次 E 成功只支持这些固定系统在该新受试者上的外推情况。共享生成元、首达、再生、自由边界分别带来的因果收益仍需要各自资格与消融；现代 GPU 性能、完整能量及正式五新种子配方继续单独 HOLD。

## 单独的候选预算：尚未分配或授权

建议新建 **7,200 秒 whole hard envelope**，单 worker/thread、CPU FP64、RSS2 GiB、AS8 GiB。上下文/数据准备最多 600 秒，D 温度拟合合计最多 600 秒；21 个模型每个最多 240 秒；最终评分/统计最多 600 秒；内部留 120 秒归档，但不保证收尾完成。所有阶段受实际剩余总预算优先截断，未测保持 HOLD，无自动重试或隐藏续期。

旧全 D HCSN replay 的六次真实过程墙钟约 120.15–122.44 秒、RSS 约 .900–.922 GB，见 [资源依据](BUDGET-BASIS.json)。这是给候选上限的参考，**不是 E 运行时间保证**；E 事件数目前不读取，新的并发负载也可能造成超时。240 秒上限不在观察 E 成绩后增加，不以较小子集替代未跑完的全 E。

等待原实验全部终态后再决定是否单独安排此窗口，尽可能记录实际并发背景。评价 CPU/wall/RSS、数据准备、校准、统计、审计、传输与已知失败全部单列；嵌套 timer 不相加。现有调参历史中不完整费用和能源仍明确 unknown，不因这次账目完整而改成“全过程成本已全”。

这份候选只说明一种可审查的下一步。当前正式配方尚未完成，E 保持未评分；根任务仍可以在 C2 结果后决定不消耗 E，继续修正模型或用新任务验证结构。
