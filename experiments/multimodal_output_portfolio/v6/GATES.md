# Section VIII：交付边界与未闭合条件

本表区分“实现可以执行”“实验支持某个结论”和“获得生产 owner 权限”。`status=completed` 只说明一个冻结协议的执行清单完成，不能替代后两种判断。首轮证据见 [results](results/README.md)，新完整对照使用 [protocol.conditioned.json](protocol.conditioned.json)。

## 研究原型的执行与证据

| 条件                    | 已提供的具体能力或证据                                                                         | 结论边界                                                                         |
| ----------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 同一真实生成 rollout    | 共享 encoder、实际自回归文字与像素 decoder、参数更新、内部语义/模态动作、有限递归选择          | 已执行首轮完整 7,560 行；不是通用全模态大模型                                    |
| 基础生成能力            | 单个预注册 LayerNorm/command-FiLM 变体通过 S/N 各六项验证门槛，注册后 512 个输出与探针字节一致 | 验证集诊断成立；新的独立完整对照仍须实际完成                                     |
| 训练与推理 2×2          | 两个训练目标、固定 dev 基线、七种策略、两预算、三 seed、真实 allocation-only 消融              | 首轮为负；执行比较不等于证明 NDU 优势                                            |
| 风险建模可区分性        | 按源 pair 的 OOF error scale、独立 pair 的经验残差、相同场景/成本下 gamma0 与 gamma2           | 机制测试可改变选择；条件/自适应覆盖与真实收益不能由该测试推导                    |
| 数值正确性              | 独立 80 位 Decimal 枚举 128 个有限问题、803 个停止路径                                         | 价值与策略在声明容差内；不证明一般 FBSDE 或无限策略空间最优                      |
| 完整成本                | 实际 wall/CPU、候选搜索、状态更新、decode、落盘/回读/audit，另列训练与 native 调用             | 已完成首轮与逐字节相同的重放；未测能耗，工作单位不是 FLOPs                       |
| 源与文件身份            | 数据去重、train/validation/observer/test 分离、每行 raw hash、严格 census、恢复后执行          | 本地主机的完整性证据，不是外部认证                                               |
| 新实验不复用已观察 case | 排除首轮全部 180 个源像素；formal offsets 60/30，smoke offsets 900/450                         | 新完整协议必须在干净源码下运行；失败或部分结果须保留                             |
| 四模态联合状态设计      | 固定 text/image/audio/video 槽位、必需集合、共同 clock/event 与输出绑定                        | 当前只有 text/image decoder；audio/video 必需请求拒绝，逻辑 event 不证明音画同步 |

## 沿现有 owner 接口接入的实际状态

| Owner 责任                            | 当前接入                                                                                                                                                                          | 仍需完成的生产条件                                                                                                                                                                                                                                                             |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `inference.control` / model execution | [GenerationDriver](../../../codex-rs/hepta-infer-worker-host/GENERATION_EXECUTION.md) 使用现有 `ModelDriver`、`InferenceWorker` 和 `DurableInferenceControl` 执行真实冻结神经模型 | 安装到实际 host，绑定当前选定 artifact、生产 resource grant、fence 与生命周期；fixture grant 不代表这些已配置                                                                                                                                                                  |
| `neuron.runtime` / `intuition.policy` | 保存真实逐动作 latent/state/output 身份；研究 joint contract 保留四槽和有界动作                                                                                                   | 还没有 `GenerationDriver: NeuronFeatureDriver`。384 维完整 latent 应留在模型执行层；Neuron V1 需注册到其 ≤256 宽度的有界投影、prediction profile 和真实 calibration/OOD 证据，或另行设计持久化 V2。不能截断后冒称等价状态                                                      |
| `utility.ndu`                         | Python 有限条件 entropic 控制器在线选择；现有 Rust evaluator 对完成的候选给出 V2 advisory                                                                                         | 原生 bridge 是事后建议，未接管在线神经控制。已有 native `recursive.rs` 的标量零噪声递归也不是 Python 的条件分布树求值；两者不能混称同一生产策略                                                                                                                                |
| `learning.operator`                   | 真正执行梯度更新，保留计划/候选/参数/轨迹证据                                                                                                                                     | `LedgerWriter` admission、dataset freeze、operator 请求仍需实际 signer、observer trust、current artifact 与精确 source membership；普通 JSON hash 不能代替授权的学习证据                                                                                                       |
| `learning.plasticity`                 | 研究模型和 gate 有真实参数更新及梯度记录                                                                                                                                          | 已有 `PlasticityDynamicOwnerEvidenceResolverV1` 可组合 NDU projection journal、anchored eligibility 和 artifact broadcast，走正式 parameter proposal 路径；尚未把本实验轨迹接入该路径。neuron eligibility 更新与百万参数生成器反传仍须分别记录，不能借用其名称宣称同一训练过程 |
| `learning.eval`                       | 独立源和参数的 Audit B 对真实媒体评分，保留失败、尾部、种子及消融                                                                                                                 | 产品 `ProductEvaluationRunnerV1` / `FencedFinalHoldoutOwnerV1` 需要正式预注册、heldout provider 与签名证据。当前同主机 benchmark 分数不能改称外部资格认证                                                                                                                      |

原生执行验证的准确范围是**现有 inference owner 与 worker 的执行闭环**，包括 submit/reserve/assign/execute/settle、重复请求、失败、超时及 journal recovery。它不激活 Agentd daemon，也不补造 neuron calibration、签名 observer 或权限。

## 放行原则

正式结果必须分别回答：基础联合生成是否可用；NDU 训练和动态推理的边际效果是什么；共享语义控制是否优于 allocation-only；风险感知是否优于相同计算的风险中性控制；改善是否覆盖实际成本。任何负结果都保留，不通过更换统计口径、源 case 或输出修补转换为成功。

GitHub 托管 CI 还须在待合并的实际提交上执行成功。本地通过的测试可以提供证据，但不能将远端 `pending`、尚无 job、被跳过或未运行的检查计为通过。PR 在研究结论和适用的工程门槛未明确前保持 draft。
