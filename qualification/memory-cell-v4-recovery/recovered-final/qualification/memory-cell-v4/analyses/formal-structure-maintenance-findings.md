# V4 正式结构与新类型维护结果

正式五种子审计支持两个有界结论：变化数值流的结构自适应达到预声明质量与自然成本门槛；事件与仿射程序的追加、更正、撤回、重训和版本隔离通过独立产物复算。严格全流结构优势仍未成立，本报告不把范围内资格写成通用 memory system 或所有 blocker 已关闭。

- 执行源码：`6206dfba0a3219534dd1a0274431bf48fd23673c`
- MANIFEST：`ec975d0e9afc53903ba2d26129446e263d06ebea0abb8b9e729e556546eca3ff`
- 正式种子：401、409、419、421、431。
- [独立结构审计](../validation/formal-structure-audit.json)；[独立维护审计](../validation/formal-typed-maintenance-audit.json)；[机器可读完整结果](formal-structure-maintenance-findings.json)。

## 1. 结构门槛与成本口径

每个 episode 的实际部署 artifact 限额为 4096 B；候选训练、分区搜索、选择读取、失败候选、历史模型、metadata 与公共回放状态全部计入。固定 K=1/2/4 获得全流 selection hindsight，未使用 hidden 结果选 K。自然固定对照保留真实必要搜索成本；匹配工作量对照额外执行的计算单列，不能用它抬高自然部署成本。

变化流要求相对 `max(best_fixed_MSE, 1)` 的归一化质量改善至少 5%，并同时降低自然固定和匹配固定的 priced loss，且满足各分区保留约束。静态流只要求归一化 MSE regret 不超过 0.01、自然 priced-loss 比不超过 1.10；它是允许代价的诊断。

Priced loss = hidden MSE / 单 cell 误差归一化量 + 0.02 × 实际工作代理 / 单 cell SVD 工作归一化量 + 0.02 × 完整保留状态字节 / 单 cell artifact 字节归一化量。该数值是预声明的研究目标，不是货币、实测 FLOPs 或峰值内存。H=1/10/100 的查询工作也保留在 JSON 各 arm 中。

| 流 | 动态门槛 | 静态范围诊断 | 严格改善 | 自然 priced-loss 比范围 | 匹配 priced-loss 比范围 |
| --- | --- | --- | --- | --- | --- |
| heterogeneous | — | 5/5 | 0/5 | 1.0919–1.0936 | 0.9566–0.9588 |
| convergent | 5/5 | — | 5/5 | 0.6645–0.7220 | 0.6258–0.6760 |
| recurrent_regimes | 5/5 | — | 5/5 | 0.6346–0.8705 | 0.5993–0.7941 |
| stable_lowrank | — | 5/5 | 0/5 | 0.3787–0.4209 | 0.3787–0.4209 |
| random | — | 5/5 | 0/5 | 1.0377–1.0381 | 0.9676–0.9808 |

动态两类合计 10/10；静态三类范围诊断 15/15；严格全流改善只有 10/25，所以 strict all-flow 为 false。冻结的 v3 结果仍为 4/20，all-flow 与 convergent-specific 均为 false，未修改。

## 2. 五种子各流结果

MSE 越低越好；成本比为 adaptive / 对照，低于 1 表示 priced loss 更低。质量增益是预声明归一化量。表中自然固定对照按 whole-flow selection 选出；全部 K1/K2/K4 原始成本、另一个按 priced loss 最小的事后诊断均在 JSON 保留，后者不改变 gate。

### heterogeneous

| 种子 | cell 路径 | Adaptive MSE | 自然固定 K / MSE | 归一化质量增益 | 自然 / 匹配成本比 | 动态 / 静态 / strict |
| --- | --- | --- | --- | --- | --- | --- |
| 401 | 4 | 0.000968 | 4 / 0.000968 | 0.00% | 1.0933 / 0.9571 | — / 通过 / 未通过 |
| 409 | 4 | 0.002594 | 4 / 0.002594 | 0.00% | 1.0936 / 0.9588 | — / 通过 / 未通过 |
| 419 | 4 | 0.002607 | 4 / 0.002607 | 0.00% | 1.0928 / 0.9577 | — / 通过 / 未通过 |
| 421 | 4 | 0.002432 | 4 / 0.002432 | 0.00% | 1.0919 / 0.9582 | — / 通过 / 未通过 |
| 431 | 4 | 0.000827 | 4 / 0.000827 | 0.00% | 1.0931 / 0.9566 | — / 通过 / 未通过 |

### convergent

| 种子 | cell 路径 | Adaptive MSE | 自然固定 K / MSE | 归一化质量增益 | 自然 / 匹配成本比 | 动态 / 静态 / strict |
| --- | --- | --- | --- | --- | --- | --- |
| 401 | 4→1 | 0.108839 | 2 / 4.042177 | 97.31% | 0.7041 / 0.6601 | 通过 / — / 通过 |
| 409 | 4→1 | 0.095027 | 2 / 4.692483 | 97.97% | 0.7013 / 0.6576 | 通过 / — / 通过 |
| 419 | 4→1 | 0.078644 | 2 / 2.752240 | 97.14% | 0.7220 / 0.6760 | 通过 / — / 通过 |
| 421 | 4→1 | 0.102357 | 2 / 6.890863 | 98.51% | 0.6645 / 0.6258 | 通过 / — / 通过 |
| 431 | 4→1 | 0.114451 | 2 / 4.489000 | 97.45% | 0.6858 / 0.6441 | 通过 / — / 通过 |

### recurrent_regimes

| 种子 | cell 路径 | Adaptive MSE | 自然固定 K / MSE | 归一化质量增益 | 自然 / 匹配成本比 | 动态 / 静态 / strict |
| --- | --- | --- | --- | --- | --- | --- |
| 401 | 1→4→1→4 | 0.080563 | 2 / 5.346357 | 98.49% | 0.6781 / 0.6374 | 通过 / — / 通过 |
| 409 | 1→4→1→4 | 0.098858 | 2 / 6.464189 | 98.47% | 0.6641 / 0.6252 | 通过 / — / 通过 |
| 419 | 1→4→1→4 | 0.089050 | 2 / 6.352430 | 98.60% | 0.6660 / 0.6269 | 通过 / — / 通过 |
| 421 | 1→4→1→4 | 0.105269 | 2 / 4.724900 | 97.77% | 0.8705 / 0.7941 | 通过 / — / 通过 |
| 431 | 1→4→1→4 | 0.098725 | 2 / 7.421554 | 98.67% | 0.6346 / 0.5993 | 通过 / — / 通过 |

### stable_lowrank

| 种子 | cell 路径 | Adaptive MSE | 自然固定 K / MSE | 归一化质量增益 | 自然 / 匹配成本比 | 动态 / 静态 / strict |
| --- | --- | --- | --- | --- | --- | --- |
| 401 | 1 | 0.024689 | 2 / 0.025496 | 0.08% | 0.4084 / 0.4084 | — / 通过 / 未通过 |
| 409 | 1 | 0.028368 | 4 / 0.027071 | -0.13% | 0.3787 / 0.3787 | — / 通过 / 未通过 |
| 419 | 1 | 0.026071 | 2 / 0.023627 | -0.24% | 0.4148 / 0.4148 | — / 通过 / 未通过 |
| 421 | 1 | 0.027399 | 2 / 0.021563 | -0.58% | 0.4209 / 0.4209 | — / 通过 / 未通过 |
| 431 | 1 | 0.028444 | 4 / 0.023317 | -0.51% | 0.3802 / 0.3802 | — / 通过 / 未通过 |

### random

| 种子 | cell 路径 | Adaptive MSE | 自然固定 K / MSE | 归一化质量增益 | 自然 / 匹配成本比 | 动态 / 静态 / strict |
| --- | --- | --- | --- | --- | --- | --- |
| 401 | 4 | 1362.082782 | 4 / 1362.082782 | 0.00% | 1.0381 / 0.9676 | — / 通过 / 未通过 |
| 409 | 4 | 1434.188847 | 4 / 1434.188847 | 0.00% | 1.0378 / 0.9754 | — / 通过 / 未通过 |
| 419 | 4 | 1390.523383 | 4 / 1390.523383 | 0.00% | 1.0379 / 0.9808 | — / 通过 / 未通过 |
| 421 | 4 | 1398.466602 | 4 / 1398.466602 | 0.00% | 1.0377 / 0.9682 | — / 通过 / 未通过 |
| 431 | 4 | 1391.853812 | 4 / 1391.853812 | 0.00% | 1.0380 / 0.9735 | — / 通过 / 未通过 |

### 静态退化与实际资源

heterogeneous 与 random 的五组结果均与所选强固定结构质量相同，仍支付额外搜索与保留状态成本。stable_lowrank 选择廉价 K1，有 4/5 种子的 hidden MSE 增加；其相对退化不能被归一化容忍掩盖。

| 种子 | 低秩绝对 MSE regret | 低秩字面相对 regret | heterogeneous 自然 priced-loss 开销 | random 自然 priced-loss 开销 |
| --- | --- | --- | --- | --- |
| 401 | -0.000807 | -3.16% | 9.33% | 3.81% |
| 409 | 0.001297 | 4.79% | 9.36% | 3.78% |
| 419 | 0.002444 | 10.34% | 9.28% | 3.79% |
| 421 | 0.005837 | 27.07% | 9.19% | 3.77% |
| 431 | 0.005127 | 21.99% | 9.31% | 3.80% |

| 流 | 实际 work / 自然固定范围 | 保留状态字节 / 自然固定范围 | 实际 mean deployed B 范围 |
| --- | --- | --- | --- |
| heterogeneous | 1.1809–1.1940 | 1.0644–1.0654 | 3764–4084 |
| convergent | 0.6953–0.7214 | 0.7918–0.8000 | 3688–3848 |
| recurrent_regimes | 0.7079–1.0164 | 0.7981–0.9830 | 3800.5–3850 |
| stable_lowrank | 0.1663–0.1838 | 0.4119–0.4589 | 3612–3612 |
| random | 1.1581–1.1632 | 1.0616–1.0620 | 4008–4094 |

recurrent_regimes 的 421 号种子实际训练/选择工作比自然固定对照略多，但更低误差与保留状态仍使预声明 priced loss 降低；不能把所有动态案例描述为计算量都下降。

## 3. 独立真实 pair-merge

五组都真实重训、验证与迁移，cell 数 4→3，部署模型 2164→1900 B，节省 264 B（12.20%）。这是单独的合并机制资格，不能把动态流的 K4→K1 全局重拟合称为 pair-merge，也不能由部署字节减少推断覆盖所有训练/历史维护成本。

| 种子 | 父模型 hidden MSE | 合并后 hidden MSE | 相对变化 | 是否质量退化 | 训练与选择总 work proxy | 完整保留状态 B |
| --- | --- | --- | --- | --- | --- | --- |
| 401 | 0.217041 | 0.198483 | -8.55% | 否 | 1153164 | 67560 |
| 409 | 0.232939 | 0.238288 | 2.30% | 是 | 1154172 | 67555 |
| 419 | 0.228450 | 0.225843 | -1.14% | 否 | 1155324 | 67556 |
| 421 | 0.235084 | 0.212224 | -9.72% | 否 | 1154208 | 67562 |
| 431 | 0.212171 | 0.220771 | 4.05% | 是 | 1158564 | 67561 |

409、431 两组 hidden 质量下降；全部迁移通过不等于每组质量改善，更不等于普遍合并净收益。

## 4. 事件与程序维护链

每个种子使用同一份封存的 640 条零售事件源，先写 320 条，再追加余下 320 条，更正 8 个字段、撤回 8 条事件、清洁重训并更换程序版本。事实字段为 quantity、unit_price_pence、stock_code、country、invoice_no；两个程序版本属于预声明仿射族，每版使用 24 个训练示例真实拟合。更正值、撤回集合和程序示例按冻结的合成维护计划产生，并非观察到的实际交易修订。五个种子并不代表五份独立零售数据集。

全部五个种子各 17/17 检查通过。参数与 model+residual 两种模式的事实结果在全部阶段都为 exact；派生金额按事前绝对误差 1e-7 评分，未把该容差称为浮点逐位 exact。独立标量读出的最大差为 0。

| 阶段 | 模式 | 有效事实 exact / 总数 | 不存在事实返回 None / 总数 | 旧正确事实保留 / 总数 | 派生结果容差内 / 有效 | 不存在派生返回 None |
| --- | --- | --- | --- | --- | --- | --- |
| initial | parameter | 8000/8000 | 8000/8000 | — | 120/120 | 0/0 |
| initial | residual_exact | 8000/8000 | 8000/8000 | — | 120/120 | 0/0 |
| append | parameter | 16000/16000 | 0/0 | 8000/8000 | 120/120 | 0/0 |
| append | residual_exact | 16000/16000 | 0/0 | 8000/8000 | 120/120 | 0/0 |
| correct | parameter | 16000/16000 | 0/0 | 15960/15960 | 120/120 | 0/0 |
| correct | residual_exact | 16000/16000 | 0/0 | 15960/15960 | 120/120 | 0/0 |
| withdraw | parameter | 15800/15800 | 200/200 | 15800/15800 | 80/80 | 40/40 |
| withdraw | residual_exact | 15800/15800 | 200/200 | 15800/15800 | 80/80 | 40/40 |
| refit | parameter | 15800/15800 | 200/200 | 15800/15800 | 80/80 | 40/40 |
| refit | residual_exact | 15800/15800 | 200/200 | 15800/15800 | 80/80 | 40/40 |
| procedure | parameter | 15800/15800 | 200/200 | 15800/15800 | 80/80 | 40/40 |
| procedure | residual_exact | 15800/15800 | 200/200 | 15800/15800 | 80/80 | 40/40 |

以上共核对 192,000 个阶段事实输出、1,440 个阶段派生输出；重复版本与两种读取模式属于重复测量。对真实程序目标的最大绝对误差为 1.432454155292362e-11，小于预声明 1e-7。

| 机制/成本 | 五种子总数 |
| --- | --- |
| actual_candidates | 35 |
| svd_calls | 150 |
| least_squares_solves | 10 |
| phase_fact_outputs | 192000 |
| phase_derived_outputs | 1440 |
| actual_processes | 35 |
| controlled_crash_exit73 | 10 |
| address_only_read_processes | 15 |
| normal_fresh_stale_snapshot_rejections | 50 |
| additional_corrupt_demo_fresh_stale_snapshot_rejections | 25 |
| old_derived_receipt_rejections | 50 |
| graph_cases | 30 |
| fault_cases | 25 |
| current_serving_versions | 5 |
| written_procedure_versions_total | 10 |

所有 fresh read 请求只带地址、模式、版本令牌；历史派生值在独立 stale-admissions 探针中拒绝。参数进程实际 Path.open 访问守卫拒绝 exact/replay/delta，完整访问清单与部署状态逐一核对。35 个进程包括 10 次受控退出码 73、10 次显式恢复、10 次普通 fresh read 和 5 次损坏程序示例回放后的参数读取。

每种子另有 6 个真实 owner-mediated 图案例：当前值成功、更新发生于两跳之间后拒绝、旧 callback 拒绝、新程序拒绝旧 receipt、改值后重算内容 hash 仍拒绝，以及撤回事件拒答。五类故障均检查了实际保留副本：CURRENT 回滚、参数损坏、程序示例损坏、delta 损坏、write receipt 损坏。

## 5. 维护训练、状态与故障副本完整成本

| 种子 | 候选 / SVD / OLS | 最小参数 serving B | 模型+残差 serving B | 全部 owner 历史 B | 5 份故障副本 B | seed 证据 B |
| --- | --- | --- | --- | --- | --- | --- |
| 401 | 7/30/2 | 86002 | 87938 | 685566 | 3427830 | 10028914 |
| 409 | 7/30/2 | 86002 | 87938 | 685564 | 3427820 | 10028790 |
| 419 | 7/30/2 | 86002 | 87938 | 685560 | 3427800 | 10028102 |
| 421 | 7/30/2 | 86002 | 87938 | 685556 | 3427780 | 10028960 |
| 431 | 7/30/2 | 86002 | 87938 | 685564 | 3427820 | 10028938 |

完整历史保留孤立未发布候选、失败前已完成的训练、旧模型和显式 replay；本轮撤回是活动前沿上的逻辑撤回，不包含历史物理擦除。故障副本是测试证据开销，单独列示，没有将它误算成最小生产 serving 状态。seed 证据包含评分输出与进程日志，排除本身的 seed summary；完整 stage 字节在 JSON 中另列。

| 实际 owner 操作/解码累计量 | 五种子合计 |
| --- | --- |
| affine_forward_rows | 1705 |
| derived_admission_recomputations | 255 |
| explicit_replay_array_bytes_decoded | 21006720 |
| explicit_replay_loads | 245 |
| fact_read_calls | 260170 |
| model_load_attempts | 580 |
| parameter_model_loads | 575 |
| pointer_admission_checks | 1845 |
| prepared_evidence_validations | 50 |
| procedure_demo_decoded_bytes | 52654 |
| procedure_demo_loads | 50 |

累计解码字节与训练矩阵字节是已发生工作的累计量，不是峰值 RSS。部署参数大小计入当前地址、schema、owner、CURRENT、独立 witness 与程序模型。当前高 exact 来自 full-rank 参数模型和清洁全量 refit，不能据此声称压缩优于最强无损基线。

## 6. 可支持的结论与未覆盖范围

冻结协议内，新的全局/完整分区候选修复了上一轮局部搜索遗漏强固定解的失败方式，并在两类变化数值流上保留自然成本净收益。新事件/程序类型的本地单写者维护链获得独立证据支持。它们不能替代联合语义任务、全 workspace 产品准入或通用系统资格。

- All-flow strict structural improvement remains false; static bounded regret is a separate predeclared scoped diagnostic.
- The static tolerance uses max(best_fixed_MSE, 1); it is not a uniform one-percent relative MSE guarantee.
- Natural fixed costs exclude work-matching padding. Matched controls do not establish efficient deployment cost superiority on their own.
- Pair merging is a paid, real independent mechanism experiment; two seeds lose hidden quality and no universal merge net benefit is established.
- Structural flows are synthetic numeric matrices; this does not establish a general memory system or arbitrary real-world adaptive improvement.
- The five maintenance seeds reuse one sealed 640-event source. Repeated versions and reader modes are repeated measurements, not independent new sources.
- Maintenance correction values, withdrawals and affine demonstrations follow a frozen synthetic update plan over real source records; they are not observed real-world transaction revisions.
- Maintenance uses full-rank clean event refits and a supplied affine program family; it does not demonstrate arbitrary algorithm discovery or superior compression.
- Maintenance graph ports are supplied and owner-guarded; they are not a new learned-graph result.
- No physical history erasure, power-loss durability, distributed concurrency, full-workspace product admission, or all-blockers-closed conclusion is claimed.
- Container parsers and lossless codecs are shared with runtime. Scalar parameter readout, parent-plus-delta reconstruction, metrics and costs are independently recomputed.
- Historical wall times, process/crash receipts and gap rejection cannot be independently authenticated from saved artifacts alone; scope is declared in audits.

所有统计来自上述正式封存产物及独立审计，未重训、未改变价格/门槛、未删种子；审计器只读读取参数与证据。历史进程、崩溃回执与 walltime 具有内容绑定，但只读审计无法独立认证真实硬件历史。
