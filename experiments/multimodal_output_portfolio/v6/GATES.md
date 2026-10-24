# Section VIII：交付边界与未闭合条件

本表区分“实现可以执行”“实验支持某个结论”和“获得生产 owner 权限”。`status=completed` 只说明一个冻结协议的执行清单完成，不能替代后两种判断。[full-002](results/full-002/README.md) 已按 [protocol.conditioned.json](protocol.conditioned.json) 完成并独立复核；[首轮负结果](results/README.md) 保留。研究问题可以得到明确负答案，不能把它改称优势门槛已通过。

## 研究原型的执行与证据

| 条件                    | 已提供的具体能力或证据                                                                | 结论边界                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 同一真实生成 rollout    | 共享 encoder、实际自回归文字与像素 decoder、参数更新、内部语义/模态动作、有限递归选择 | 两轮各 7,560 行已完成；约百万参数的数字对任务，不是通用全模态大模型                   |
| 基础生成能力            | 预注册修复通过验证；新源 N/N clean future 联合正确率 86.67%，clean-retention 90%      | 六层混合 future/128 只有 48.33%；错误提示与无视觉/提示层为零，稳健性未通过            |
| 训练与推理 2×2          | 新源上七策略、两预算、三 seed、真实 allocation-only 消融；所有 32 个登记区间含零      | 训练有描述性收益；动态推理增量、内容控制和成本优势未通过，不能宣布总体优越性          |
| 风险建模可区分性        | 相同场景/收费下 gamma0 与 gamma2 在 NDU future/128 有 40% 原始输出不同                | 风险确实影响生成；风险感知仍未胜过风险中性，条件/自适应覆盖未认证                     |
| 数值正确性              | 独立 80 位 Decimal 枚举 128 个有限问题、803 个停止路径                                | 价值与策略在声明容差内；不证明一般 FBSDE 或无限策略空间最优                           |
| 完整成本                | 实际 wall/CPU、候选搜索、状态更新、decode、落盘/回读/audit，另列训练与 native 调用    | 新 full 总时长 861.013 秒；NDU future/128 动态推理为 dev 固定的 2.336× wall；未测能耗 |
| 源与文件身份            | 数据去重、train/validation/observer/test 分离、每行 raw hash、严格 census、恢复后执行 | 本地主机的完整性证据，不是外部认证                                                    |
| 新实验不复用已观察 case | 干净 b98961ce 源码执行；新 180 个源像素与旧 180 个零重叠；formal/smoke 使用不同 case  | 独立复核通过；旧新分数不能作为同源架构干预的因果比较                                  |
| 四模态联合状态设计      | 固定 text/image/audio/video 槽位、必需集合、共同 clock/event 与输出绑定               | 当前只有 text/image decoder；audio/video 必需请求拒绝，逻辑 event 不证明音画同步      |

## 沿现有 owner 接口接入的实际状态

| Owner 责任                            | 当前接入                                                                                                                                                                                                                                        | 仍需完成的生产条件                                                                                                                                                                                                                                                |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `inference.control` / model execution | [GenerationDriver](../../../codex-rs/hepta-infer-worker-host/GENERATION_EXECUTION.md) 经现有 worker/durable owner 执行真实模型；full-002 trained checkpoint 重放的文字、PNG、最终 backend state 与原行完全相同                                  | 重放记录动作不等于原生在线控制。该次冷子进程 8.257 秒，原常驻完整行 59.501 ms，成本范围不同；生产 host、artifact 选择、resource grant 与生命周期仍需正式配置                                                                                                      |
| `neuron.runtime` / `intuition.policy` | [NeuronFeatureDriver adapter](../../../codex-rs/hepta-infer-worker-host/GENERATION_NEURON.md) 保留完整 384 维模型状态，所有分量参与 96 维有界投影；真实 owner 执行和 bootstrap 拒绝已验证                                                       | 预注册 persistence predictor 的 ECE 为 503,354/612,707 ppm，OOD 假接受为 1,000,000 ppm，超过 30,000/4,999 门槛；runtime 返回 InvalidCalibration，journal 为空。合格 predictor、admitted tick、intuition 使用和目标主机资源资格均未建立                            |
| `utility.ndu`                         | Python 有限条件 entropic 控制器在线选择；现有 Rust evaluator 对完成的候选给出 V2 advisory                                                                                                                                                       | 原生 bridge 是事后建议，未接管在线神经控制。已有 native `recursive.rs` 的标量零噪声递归也不是 Python 的条件分布树求值；两者不能混称同一生产策略                                                                                                                   |
| `learning.operator`                   | [真实生成 terminal owner](OWNER_TERMINAL.md) 执行本地角色签名 admission、14 条 ledger 记录、精确 freeze、七 cell 拟合、artifact 保存/加载与恢复后相同预测；原 Python 梯度训练另行保留                                                           | 工程 fixture 使用已观察的旧记录和本地测试 trust；未观察的 abstain 无预测。它不代替外部 observer trust、生产 artifact 选择或生成器神经梯度的原生 owner 接管                                                                                                        |
| `learning.plasticity`                 | 研究模型和 gate 有真实参数更新及梯度记录；terminal owner 产生真实受支持 cell artifact                                                                                                                                                           | 正式 resolver 需要已确认的非零 SparseJournal anchor、通过 admission 的 checkpoint eligibility、同上下文 NDU modulator 和注册参数映射。实际 Neuron 校准失败、journal 为空，不能伪造合格 trace 来取得 parameter proposal；局部 eligibility 与生成器反传仍须分别记录 |
| `learning.eval`                       | [成对执行 profile](../../../codex-rs/hepta-intelligence-eval/PAIRED_FULL_INFORMATION.md) 经同一 `ProductEvaluationRunnerV1` / `FencedFinalHoldoutOwnerV1` 实际消费 360 个 N/N、N/S 观测；受控释放、原生统计、角色签名、fsync 落盘和恢复均已执行 | 已观察数据的 posthoc 工程重放，始终 DENY_ALL；不伪造 propensity 或 cross-fit folds，也不修改旧 OPE 约束。需要另行建立新实验预注册、外部效用与生产 evidence owner 授权，不能将本地测试签名改称外部资格认证                                                         |

原生执行验证包括**现有 inference owner 与 worker 的执行闭环**，以及本地 terminal learning owner 的真实导入、冻结、拟合、加载和恢复。Neuron 的拒绝路径使用实际测量值；“正确拒绝”通过并不意味着 predictor 通过校准。这些切片不激活 Agentd daemon，不产生外部 observer 认证或生产写入权限。

塑性前置条件另已实测：真实 terminal artifact 的值经 `NduProjectionStoreV1` append/select/reopen 保持一致；被拒 Neuron 的真实 `FileAnchorWitnessStore::current()` 返回 `None`，journal 仍为空。因此没有可提交的 acknowledged checkpoint，未构造 dynamic resolver、未调用 proposal owner、未产生 update。`MissingAcknowledgedNeuronCheckpoint` 是对此前置条件的工程标签，不是 proposal owner 返回的错误。两个原始 objective/subject 上下文均保留，没有改写成同一个上下文来拼接成功链路。

自动 CI 执行当前 run 的真实 trained-model 重放、terminal import 和 paired evaluation，以及通用 feature 边界和 Python 校准算术回归。原始 rows SHA 在完成验收时单独固定，导出与原生导入复用这个 pin。绑定 full-002 checkpoint 的 Neuron 实测与塑性前置条件集成只在明确提供完整 fixture 与独立 SHA 时执行；自动 CI 对这两个 opt-in target 仅编译，不能把 ignored 或 compilation 计为实测测试通过。

## 放行原则

正式结果必须分别回答：基础联合生成是否可用；NDU 训练和动态推理的边际效果是什么；共享语义控制是否优于 allocation-only；风险感知是否优于相同计算的风险中性控制；改善是否覆盖实际成本。任何负结果都保留，不通过更换统计口径、源 case 或输出修补转换为成功。

GitHub 托管 CI 还须在待合并的实际提交上执行成功。本地通过的测试可以提供证据，但不能将远端 `pending`、尚无 job、被跳过或未运行的检查计为通过。PR 在研究结论和适用的工程门槛未明确前保持 draft。
