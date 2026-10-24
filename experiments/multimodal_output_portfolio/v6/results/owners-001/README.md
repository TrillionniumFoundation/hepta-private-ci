# 原生 owner 执行、学习、评估与准入拒绝

本目录保存实际 owner 执行的紧凑摘要，原始字节哈希及来源见 [manifest.json](manifest.json)。这些是本地工程证据，权限始终为 `DENY_ALL`。它们既不增加独立科学样本，也不替代生产 trust、daemon 注册或新实验的预注册。完整质量结论见 [full-002](../full-002/README.md)。

## 1. 同一已训练生成模型进入 inference owner

[trained-owner-replay.json](trained-owner-replay.json) 使用 full-002 的首个 seed 17、NDU 训练、future-0060、预算 128。选择规则在工程导出中固定为首个有实际追加动作的 risk-aware 行；没有按正确率挑选。相同 checkpoint 经现有 `ModelDriver`、`InferenceWorker` 和 `DurableInferenceControl` 执行原记录中的 `couple → refine_semantic → couple`。

实际验证包括 submit/reserve/assign/execute/settle、精确进程内 retry、低 token 拒绝与 settled journal recovery。之后独立 verifier 检查原始 rows 的外部保留 SHA、唯一原行归属、summary checkpoint pin、完整 V1 request wire、真实输出字节及最终 backend state，全部一致。仅核对行自哈希并不足以证明原行归属；此缺口已补强并有专门回归。

| 实际测量                    |                值 |
| --------------------------- | ----------------: |
| 冷子进程 host wall          |          8.257 秒 |
| worker 内执行 wall          |          4.116 秒 |
| worker 内执行 CPU           |          3.885 秒 |
| child peak RSS              | 360,583,168 bytes |
| 原常驻 runner 的完整行 wall |         59.501 ms |

这里重放已选动作，没有在原生 owner 中重新执行在线控制器。冷 Python/Torch 进程与常驻研究 runner 是不同成本范围。实际选定测试 1/1 通过；同一 test target 中其余四个此前已执行的 fixture 被本次过滤，没有把过滤项计为通过。

## 2. 真实终值学习与恢复

[terminal.json](terminal.json) 从 full-001 固定组导入七个实际策略的结果，使用明确的本地测试角色签名。现有 `LedgerWriter` 接收七对 Decision/Outcome，共 14 条；evaluator 冻结精确数据集，owner 派生七个 terminal targets，经既有 fitter 与 artifact registry 保存、加载后执行预测。加载的七个 cell 与原始 Q32 targets 相同，恢复后的 owner 重新拟合也相同。

完整 candidate grammar 包括原七种策略和保留的 `abstain`，但原实验只实际执行七种策略。新 supported-subset 入口要求全部已观察动作均被包含，且每个拟合动作达到真实支持数；不能丢掉不利结果。未观察的 abstain 返回 unsupported，没有补造零效用目标。原 V1 全覆盖入口保留原合同与 digest 路径。

篡改 raw 输出、错误签名角色、错误单位、遗漏已观察动作和重用 record ID 的冲突均被拒绝。该一状态、每动作一个样本的精确拟合不证明泛化，也没有把 Python 神经梯度改称原生 terminal/plasticity 更新。实现及复现见 [OWNER_TERMINAL.md](../../OWNER_TERMINAL.md)。

## 3. Neuron 有界投影与实测 NO-GO

完整模型状态为 `h,image,text,context` 四个 96 维块。模型执行层保存全部 384 个 float32 bit patterns，Neuron feature 使用固定的 96 维投影；全部块参与投影，完整输入与前态另外绑定，不能用有损投影相等替代身份相等。

冻结的 predictor 是 persistence：预测前态投影，drive 为后态投影。其 residual 不能直接被解释为语义置信度或 OOD 概率。一个预注册 pilot 使用两个各 64 个独立验证源 pair 的 cohort，每组 32 个普通输入和 32 个事先定义的无视觉/无数字提示 OOD。

| 指标              |   Calibration |  Verification |       冻结门槛 |
| ----------------- | ------------: | ------------: | -------------: |
| ECE               |   503,354 ppm |   612,707 ppm |    ≤30,000 ppm |
| OOD 假接受        |         32/32 |         32/32 | FAR ≤4,999 ppm |
| OOD FAR           | 1,000,000 ppm | 1,000,000 ppm |     ≤4,999 ppm |
| Reward A 联合成功 |         29/64 |         22/64 |     描述性结果 |

[calibration.json](calibration.json) 保留实际测量。[neuron-admission.json](neuron-admission.json) 记录真实 owner 执行后，`NeuronRuntime::bootstrap` 使用未经放宽的实测值返回 **`InvalidCalibration`**；没有提交 checkpoint，Neuron journal 长度为零。实际拒绝集成 1/1 通过，14.504 秒，无 skip/retry。

这一执行的冷子进程 wall 为 7.857 秒，投影本身为 51.338 微秒，driver 至 observation 为 9.877 秒，child RSS 为 361,455,616 bytes。RSS 在明确的 resource profile 中只是 resident-byte charge，不是 allocator 峰值、累计分配或目标主机资格。投影很快也不能证明完整 hot tick 满足资源预算。

测试 NDU context 明确标记为 `test-only / no-NDU-valuation-owner`。合格 predictor、admitted Neuron tick、intuition 使用及生产激活均未建立。更多实现边界见 [GENERATION_NEURON.md](../../../../../codex-rs/hepta-infer-worker-host/GENERATION_NEURON.md)。

## 4. 塑性更新在真实前置条件处停止

[plasticity-prerequisite.json](plasticity-prerequisite.json) 先从真实 terminal artifact 读取固定 dev 策略的值 `−3504111200` Q32，再在其原 objective/subject 内经真实 `NduProjectionStoreV1` append/select/backup/reopen，记录及选中值保持相同。

被拒 Neuron 来自另一原始研究上下文。测试重开它的真实 witness，`AnchorWitnessStore::current()` 返回 `None`；原空 journal 和所有来源文件均未改变。因此没有能够交给 dynamic resolver 的 acknowledged checkpoint。

`MissingAcknowledgedNeuronCheckpoint` 是这一前置条件的测试标签，**不是** proposal owner 返回的错误。实际未构造 resolver、未调用 parameter generator 或 proposal admission、未写 eligibility、未产生 update。terminal 的原 objective/subject 与 Neuron 的独立 scope/objective 没有被重标为同一个上下文，这也不构成同上下文的完整提案尝试。实际集成 1/1 通过，2.457 秒，0 skipped。

## 5. 真实成对结果进入同一 fenced evaluation owner

[paired-evaluation.json](paired-evaluation.json) 使用 full-002 的 N/N 对 N/S、future/128，全 60 源 case × 3 固定 seeds × 2 arms = 360 个观测。导入绑定独立保留的 rows SHA、已完成摘要、完整原清单、720 个原始媒体、模型/forecast/observer、历史输入 recipe、源像素及 source→case 映射。

在同一 locked CAS 成功消费后，provider 才释放 typed outcomes。owner 按源 case 内的固定 seed 均值派生结果，随后通过已有三角色签名验证、实际 fsync sink、关闭并恢复 journal、重新派生相同结果。改变真实 loss 的一个 Q32 单位会在 evaluator 签名前被拒绝；恢复前后只有一条消费记录。实际应用集成 1/1 通过，12.617 秒，0 skipped。

| Candidate N/N − baseline N/S |                 Owner 结果 |
| ---------------------------- | -------------------------: |
| 平均 joint loss              |             约 +0.00544652 |
| 平均 factual error           |             约 +0.01666667 |
| 工程 loss 区间               | [−0.62700901, +0.63790205] |
| 工程 factual-error 区间      | [−0.61578887, +0.64912220] |
| `observed_thresholds_pass`   |                      false |
| Qualification / promotion    |                      false |

这是已观察数据的工程重放。这里使用 family 64 的保守 Q32 区间，与原科学实验注册的 family 32 区间分开报告；条件范围仅覆盖独立 source cases 和冻结模型，不覆盖训练 seed 总体或尾部。原始记录没有单独的签名 Audit receipt，因此此次签名明确是对原 combined row receipt 与 Audit B bytes 的 **posthoc observation witness**，不声称原始外部签名或重新评分。

旧 OPE 合同没有放宽，没有伪造 propensity 或 folds。新 profile 通过同一 `ProductEvaluationRunnerV1` 和 `FencedFinalHoldoutOwnerV1`，保留旧 journal/event-1 字节与 hash。公开 CAS snapshot 字段升级到 V2 envelope，直接依赖旧字段 Rust 类型的调用方需迁移。实现和复现见 [OWNER_PAIRED.md](../../OWNER_PAIRED.md)。

## 6. 验证与适用边界

本批最终 Python 集成 suite 为 **99/99**，其中四项为 custody 回归。受影响 Bellman crate **27/27**；eval crate **127/127**，包括旧 OPE、旧 snapshot/mixed journal、CAS、签名与恢复。新 feature unit **3/3**。各真实 owner 路径的测试和首次失败日志均保留。

源码在实际测试后按仓库要求执行 scoped fix 和最终 `just fmt`；执行时二进制与源哈希另存，不能把格式化后的提交 SHA 冒充此前所有进程的唯一源身份。原 finite NDU 的 82 个 scoped tests、67 个 inference library tests、五个首次 lifecycle cases 和独立数值 oracle 继续按其各自记录解释，不以重复计数增加证据量。

托管 CI 必须在最终待合并提交上实际完成。本地通过、正确拒绝、编译成功或 `completed` 清单均不替代该门槛。当前科学与生产放行结论仍以 [GATES.md](../../GATES.md) 为准。
