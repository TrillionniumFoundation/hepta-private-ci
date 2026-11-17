# 研究 01：封存结果独立复核

## 结论

研究 01 的终态是 **RESEARCH_PARTIAL_UNQUALIFIED**。四个 SFT 分支进入训练函数后，均在首次模型初始化之前被固定的 **4 GiB 空闲显存门槛**拒绝；四次进入均未推进到优化器步骤，也未完成任何训练候选。parent 和 retrieval 两个分支同样在初次评估加载前被该门槛拒绝。因此，本次没有可比较的新 A/B 业务结果，没有冷恢复结果，也没有 E1/E2 的训练效果证据。

已实际完成并保留的工作是：六次未执行补丁的 shadow 生成，以及 36 次对六个 authored A 目标的业务重验。36 次重验均有通过原始实现、拒绝错误输出对照的完整回执。它们证明这些目标在约定的隔离函数契约检查中有效；它们不构成 36 个独立任务，不是学生模型完成任务的成功记录，也不是完整仓库集成验证或独立用户使用证据。

协调器的真实 `Popen.wait` 返回值为 0，表示协调器完整保留并报告了这些部分失败。六个 primary 子进程的真实退出码均为 1，均非超时，均未自动重试。

## 复核范围与证据身份

本报告在结果已经产生之后编写，属于事后审查。此前保存的 `REVIEW_PLAN.md` 是结果复核清单，编写于根代理报告实际启动之后、复核者读取结果之前；它不是实验预注册。

本次读取的是 Mac 上已封存的 `research-final-evidence-01`，原件保持不变。执行的唯一分析程序使用 Python 标准库读取文件、验证哈希、核对回执及计数；它从冻结源中按 AST 选取三个纯回执阅读函数，未导入模型或训练模块，未调用模型、tokenizer、业务 verifier，也未重跑工程测试。没有读取新 C。

| 原件 | 字节数或范围 | SHA-256 |
| --- | --- | --- |
| TRANSFER_MANIFEST.json | 8,801 B | `785f5f4c4bfbb9f5c68131cfe1116c870274dd0cb7ec9473c671ebe38af039cf` |
| qwen-research-sft.zip | 1,590,081 B；694 个成员 | `3b6b10a9bfdcb2cf3c7df965dd45e5cac3143463b3b8a615ff544aeb417b437a` |
| MEMBERS.jsonl | 694 条成员身份 | `336e7308d967918413b0c0fc6b8e5e2acefc16476e70b419f100b3752731afa5` |
| research-sft-01/FREEZE.json | 55,573 B | `ff08f18b0479ae089303787ec71013d558cf057b685e9c93432504877364db41` |
| research-sft-01/RESULT.json | 18,639 B | `bbb77cb25b2f7e28caa3a71f7112d549734b3ff8bbdd32b562fc2bbbf5bc0e33` |
| research-diagnostic-01/DIAGNOSTIC.json | 37,021 B | `b623702d5611bd24bd3f9736300938c6e02f2ec75bed838962d33b05e6b7af37` |

独立分析核对了 **242 个实际文件**与封存成员清单的字节数及 SHA，完成 **604 项一致性检查，未发现不匹配**。这些是回执一致性检查次数，不是新增工程测试、独立样本或模型任务成功数。没有重新验证所有 694 个成员的语义；完整归档保存由根代理的封存程序完成，本复核另外核对了整个 ZIP 的固定字节身份。文件读取不被声称为文件系统原子快照。

逐文件身份、逐回执检查和实际分析终态见同目录：

- `CLOSED_RESULT_REVIEW_01.json`：107,676 B，SHA `f5ed93d4013baa560ef781ae2c36b0bd502841cb1d5be13a83f1f9c8a8f159a3`。
- `review_closed_research01.py`：28,128 B，SHA `265f77d60233e641bbe84b14ea7d01965bb28a4a7edd0884c20db5e233c39204`。
- `REVIEW_EXECUTION_RECEIPT_01.json`：保存分析启动身份、完整 stdout、真实退出 0 和 output_complete=true。
- 本轮分析 PTY：`dpty-6c09d0cfb5bb6b4bbf9c36ea1622e62e193ea4d7aa013a7317ad6c079ef897c2`。

## 四个训练分支究竟停在哪里

六个 primary 的错误均为：

`ValueError('selected CUDA device has insufficient free memory')`

四个拟训练分支的原始 traceback 都指向：

1. `research_sft_execution_v1.py:281` 调用训练；
2. `research_sft_train_v1.py:135` 执行首次 `probe.check_device`；
3. `causal_probe_v3.py:311` 因空闲显存低于冻结门槛而抛出异常。

冻结训练源的顺序明确：六个 reference 重验完成并保存后，才进入第一次设备检查；设备检查之后才创建 Predictor、tokenize 训练例子、构造 LoRA 和 optimizer、执行训练循环。四个失败都发生在这条边界之前。

| 分支 | 实际进入训练 | 该分支 reference 重验 | 优化器步骤回执 | 新 A/B 结果 | 冷恢复 |
| --- | --- | --- | --- | --- | --- |
| parent | 不适用 | 不适用 | 不适用 | 未取得 | 未启动 |
| retrieval | 不适用 | 不适用 | 不适用 | 未取得 | 未启动 |
| final_answer | 是 | 6/6 有完整成功回执 | 0 | 未取得 | 未启动 |
| trajectory | 是 | 6/6 有完整成功回执 | 0 | 未取得 | 未启动 |
| shadow_correction | 是 | 6/6 有完整成功回执 | 0 | 未取得 | 未启动 |
| controlled_correction | 是 | 6/6 有完整成功回执 | 0 | 未取得 | 未启动 |

parent/retrieval 的 traceback 指向 `research_sft_execution_v1.py:129`，同样位于 Predictor 构造之前。归档中没有这六个 primary 的完成 RESULT；没有任何训练的 STEPS/TRAINING 完成证据；没有 cold worker 输出。保存的四个 STARTED 只证明四次进入训练函数，不能当成四次成功训练或 256 个已执行步骤。

因此，当前唯一记录到的 primary 终止类别是**资源准入拒绝**。这不是实际训练中的 CUDA OOM，也不能据此判定模型在相同 GPU 上训练必然无法容纳，或者某种监督方法无效。错误回执没有记录失败瞬间的实际 free bytes；本复核没有采集 GPU 进程或进一步归因外部资源占用。更早 shadow 生成所记录的显存值不能替代失败瞬间的测量。

## 36 份 reference 回执核对

36 份由 12 次 collector correction 重验和 24 次训练前重验组成；四个 REFERENCE_RECHECKS 汇总文件与其各自六份原件逐项一致，汇总没有被再计作调用。

逐份检查覆盖了：

- 原始 A task、record、input、authored target 与 verifier 参数、版本、冻结 verifier 源 SHA 的绑定。
- REFERENCE_REQUEST 的 record digest 与答案 SHA。collector 的 request 在替换新 reference 字段之前写入，因此按实际冻结代码构造的调用前 record 核对，未将它错误地与替换后的 cohort 直接比较。
- REFERENCE.json 内部 semantic receipt digest 与 REFERENCE_MEASUREMENT 引用的实际文件 SHA。
- 原始实现的真实调用观测、对照数量、拒绝计数及每个对照的实际失败观测。
- correction cohort 与真实 shadow/controlled step 构造结果完全一致，学生 action 均不作为训练 target，最终 correction 来自已授权的 authored A 目标。

| 已测项目 | 结果 | 解释边界 |
| --- | --- | --- |
| 新 reference 实际调用 | 36 | 六个 A 目标的重复重验 |
| 原始 A 任务身份 | 6 | 不因重放、分支或重验增加 N |
| 完成的原始实现 subject 调用观测 | 54 | 原始调用完成数；不是所有可能尝试调用数的估计 |
| 完整对照观测 | 84 | 每次重验的所有规定对照均拒绝 |
| authored reference 业务成功 | 36/36 | 隔离函数契约检查有效 |
| 完整仓库集成标记 | 全部 false | 不能升级为完整仓库修复验收 |
| 独立用户证据标记 | 全部 false | 没有新增经过认证的用户或来源 |
| 学生执行成功声明 | 全部 false | reference 不归因给学生策略 |

六个 A 任务是 counter、MSE、readout score、clipped metrics、pair map 和 colon repair 的已固定隔离任务。来源、任务及 lineage 身份全部保留；authored reference 的质量与原始用户使用轨迹的真实性是不同问题，本次没有验证新的真实用户轨迹。

## Shadow、controlled 复用与 E1/E2 解释

六个 shadow 请求/输出/step 的哈希、原始请求、聊天历史、generation 设置和 parent 模型身份一致；记录了 **1,727 个输入 token、1,764 个输出 token**。这六次生成没有应用补丁、没有执行测试，业务成功值为 null；不能根据输出文本看起来像代码而改写为成功或失败。

controlled correction 精确复用 parent03 的六个 A 任务、合计 12 个原始执行步骤。复核将保存的 CONTROLLED_REUSE 与 parent readiness 的六行、对应 request/output/step 原件逐项核对。复用本身没有新增模型或 verifier 调用；它仍是同一固定 parent 的旧经验，不是已经训练的学生偏离新策略后收集的在线经验。

本协议预定的四个 fit 均为 64 步、1536 序列上限，并在首次 fit 进入前完成了四个 plan 的冻结。这个预算限制不能推出四种方法具有相同的监督 token 数或相同的信息量。final-answer、trajectory、shadow correction 和 controlled correction 的被监督位置与上下文不同；即使未来四个 fit 完成，也需要查看实际训练 step 的 input/supervised token、损失、计算和业务结果，才能描述匹配的程度。

本次在训练编码与优化前停止，因此**没有实际消费的监督 token、训练损失或训练后业务结果可比较**。不能用计划的 393,216 padded positions 冒充本次已消费计算，也不能把预定的四组 64 步写成完成值。

parent03 的完整历史基线确为 A 0/6，身份由原 RESULT/FREEZE 绑定。对“原先成功的 A 任务仍保留多少”这一指标，分母是 0，retention 应保持 null；绝对 A 成功数是另一个指标。本次六个 primary 没有得到新 A 结果，新的绝对成功率同样是 unavailable，不能填成 0%。

旧 B 已经暴露，协议本身也是在观察失败后明确新建的探索。即使后续独立编号运行取得 B 改善，也首先是该旧开发面板上的描述性结果，不能直接声称未见来源、未来时间或新用户上的泛化。研究 01 连这一层开发比较也没有产生。

## 费用：保留已测小计，整体仍不完整

| 费用记录 | 已测值 | 可否相加 |
| --- | --- | --- |
| 整个 coordinator wall | 246.6030926690146 秒 | 作为这个 scope 的 wall |
| coordinator 自身 CPU | 2.591109 秒 | 与该记录的 completed-child CPU 是不同范围；不与嵌套 worker 再重复叠加 |
| 完成子进程 CPU | 244.295266 秒 | 已包括完成子进程，不再加训练/collector 子范围 |
| owned wrapper child wall | 246.76812488000724 秒 | 外层观测，不能再与 coordinator wall 相加 |
| 36 个 reference callback wall 小计 | 6.755185771 秒 | 已在更大 reference/worker/coordinator 范围内 |
| 36 个 reference measurement wall 小计 | 6.836760047008283 秒 | 包含其 callback，不能把二者相加 |
| GPU 活跃秒、能耗、货币费用 | null | 未测得，不能用 0 代替 |

原 ledger 保留六份完成 output、36 份完成 reference、0 份 student verification、0 份 optimizer step 回执。它也明确保留 `global_totals_unknown=true`，model_calls、input_tokens、output_tokens、training_steps、reference_calls 和 student_verifier_calls 等全局总计为 null。虽然封存源与 traceback 可以定位本次资源拒绝发生在训练之前，本复核仍没有把这些原始不完整全局字段“补齐”为零或小计。

本轮 retained ledger 没有 measurement errors/gaps，也没有观察到预算越界；这不等价于 GPU/能耗/完整失败尝试费用已知。历史 parent readiness 的费用另外保留，本研究未将它并入新调用计数。

若后续启动明确新编号的运行，01 的生成、参考检查、失败进入和费用必须继续保留。相同任务的重排执行不增加独立样本 N，也不抹除 01 的资源失败。

## 资格与后续可报告边界

独立诊断没有 binding errors；三个固定 expert slot、单列 shadow arm、parent 和 retrieval 全部为 UNAVAILABLE，没有替换失败槽位。first-attempt union 为 null，实际 routing executions 为 0。

本轮所有 scientific confirmation、native cell adoption、PoUW 和 Circuit 资格均为 false，candidate_selected=null，new_C=false。E3 没有新增经过认证的教师；E4 没有训练 circuit、匹配成本比较及逐边/逐 Cell 消融；E5 没有独立用户/来源增长实验；E6 没有独立选择、新 C 使用或真实采用闭环。

可公开报告的是：**研究 01 的冻结、实际启动、已完成的有限生成和 authored-reference 重验、明确保留的资源拒绝、以及没有形成训练效果结论的事实**。
