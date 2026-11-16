# E1–E6：首轮开发实验结果

日期：2026-11-16。运行标识：`run-v1`。

## 结论

六组实验的执行框架、七组真实 LoRA 训练、数值路由实验、逐 Cell/输出边消融、两条 NoUpdate 与新进程重载链已完成。当前结果没有建立独立泛化收益、多教师能力融合、Neural Circuit 必要性、用户增长效应或采用后候选恢复的证据。所有独立科学资格继续为 **BLOCKED**。

最直接的观察是：答案 SFT 在开发 B 上为 2/4，但开发 C 为 0/3；其余 E1 模型对照在 C 也全部为 0/3。E2 没有成功恢复。E4 学习稀疏图的准确率与单模型相同，线性训练 MAC 为其 10/3 倍。E6 遵守冻结门槛，得到两次 NoUpdate。

## 固定来源与可核对原件

- Hepta 源码基线：`f8e54c63700c8ffc40c9ddaec4e3fd44817da0fb`，原 #6400。
- Chain 配置来源：`59bd6ae4223caff6695dc9cf2ee2cdcdc6df5e88`。
- 新实验源码栈终点：`c333ea22eb8f739aeceed429b53c08a556e7ee82`，[#6415](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6415)。
- 20 份实验 Python 文件的冻结摘要：`5b0267cafe466ca382734604ee08a48748c3d9b5023c2d39645f79d36b8dec24`。
- 原始数据文件 SHA256：`a84af1db6d661108ea0b2c5effddac97ecda55c8238e246d94238323803390f1`。
- AI395 实际运行 job：`1a1e391654e-392-3435`；退出码 0，`COMPLETE_DEVELOPMENT_CAMPAIGN`，实际历时 348.875 秒。
- [SOURCE_FREEZE.json](SOURCE_FREEZE.json)、[原始清单](INVENTORY.json)、[执行总状态](execution-logs/RESULT.json)、[冻结执行计划](execution-logs/EXECUTION_PLAN.json)。
- [E1/E2 复核](READOUT_E1_E2.json)、[E3/E4/E5 复核](results/READOUT_E3_E5.json)、[E6 复核](READOUT_E6.json)是原件的衍生分析；它们没有产生新训练或新模型推理。

`INVENTORY.json` 固定原始运行的 498 份文件，不将后生成的复核报告反向加入该清单。归档布局、模型重建及传输核对见 [归档说明](RESTORE.md)。

## 数据与方法边界

这 14 个任务是从两个仓库的固定 JSON 原件中新编的结构化数据维护任务。A/B/C 分别为 7/4/3 个任务 ID；A 有两份来源文件。它们不是外部 AI agent 的历史示范，也不是独立用户的未来任务。A 与 B 存在项目重合，时间切分条件不成立，全部暴露标记为 `development`，`real_users_verified=0`。

来源文件、家族和任务标识的隔离检查仍然执行。重放、教师副本、模型对照、第二次尝试、冷重载和消融都不增加独立样本数。E3–E5 对三个 C 任务进行了 59 次面板访问，不能将其写成 177 个独立样本。

底座为 [HuggingFaceTB/SmolLM2-135M-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct/blob/12fd25f77366fa6b3b4b768ec3050bf629380bac/README.md)，固定 revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`。模型卡标注 Apache-2.0。底座权重 SHA256 为 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`。

七个模型均从同一底座开始，LoRA rank 4，目标层 q_proj/v_proj，可训练参数 230,400，AdamW 学习率 0.0003，seed 1729，各 32 步。E1/领域教师每步固定 256 个 padded positions，E2 三臂固定 512；比较中的实际监督 token 数并不相同。推理上限为输入 512、输出 48 tokens，CPU 执行，每模型 2 个线程，最多两个子进程并发。

所有模型原始输出都经过结构和业务值验收。合法 JSON 本身不算任务成功。数据不得提供待执行 shell 命令，E2 仅执行有界 JSON artifact 写入及读回。

## E1：轨迹是否有额外价值

| 对照 | 开发 B | 开发 C |
| --- | ---: | ---: |
| 冻结底座 | 0/4 | 0/3 |
| 冻结底座＋检索 | 0/4 | 0/3 |
| 最终答案 SFT | **2/4** | 0/3 |
| 完整轨迹 SFT | 0/4 | 0/3 |
| 确定性规则基线 | **4/4** | 未加入同一 E1 C 推理面板 |

答案 SFT 的 C 输出都是合法 JSON，但比例、attention 维度和 token 总数均错误。轨迹模型主要出现回显、说明文字、重复答案或不完整 JSON。因此这轮没有观察到向 C 的收益转移。

训练使用自定义 `### User/Assistant/Tool` 序列化，轨迹含 curator 指令与重复监督目标，而评价要求单次生成一个 JSON。协议与上下文混杂已在冻结计划中声明，不能将这个结果推广成“轨迹训练无效”。

原件：[C 全部输出](results/E1_C_READOUT.json)、[检索 B](results/RETRIEVAL.json)、[答案 B](results/models/final_answer/B.json)、[轨迹 B](results/models/trajectory/B.json)。

## E2：学生自身经验

| 采集臂 | 学生实际调用 | A artifact 写入 | 生成的 SFT 记录 |
| --- | ---: | ---: | ---: |
| 示范 | 0 | 0 | 7 |
| 影子预测 | 7 | 0 | 7 |
| 受控执行＋修正 | 14 | **0** | 14 |

受控采集的 14 次输出都不是合法 JSON。实际发生了学生生成、解析失败和自身状态反馈，但没有成功应用合法 A artifact。14 条修正记录来自确定性参考实现，不能计为学生完成了 14 个任务。

| 学生模型 | B 成功/任务 | B 调用 | C 成功/任务 | C 调用 |
| --- | ---: | ---: | ---: | ---: |
| demonstration | 0/4 | 8 | 0/3 | 6 |
| shadow | 0/4 | 8 | 0/3 | 6 |
| controlled | 0/4 | 8 | 0/3 | 6 |

全 E2 共 63 次真实模型调用，28 次失败后的第二次尝试，成功恢复为 0。只有一次合法 JSON 被实际写入和读回，出现在 demonstration 的 C，内容仍错误。62/63 次输出达到 48-token 上限。

三臂 B 全为零，预先声明的名字平局规则选中 `e2_controlled`。这不是收益胜出。三臂等训练位置预算，但采集成本不等；它们都重复监督 correction/final answer，协议混杂未消除。

原件：[采集](results/E2/collection/RESULT.json)、[选择冻结](results/E2/FROZEN_SELECTION.json)、[C 全部结果](results/E2/C_READOUT.json)。

## E3：多教师互补

本轮教师是两个真正训练过的同底座 LoRA 专家，学生是固定 64 维表示上的 LocalHead。目标为 JSON 输出值的领域分类：数值、含布尔值、其他/无效。这里的正确率不等于完整任务成功率。

| 学生对照 | B 分类正确 | C 分类正确 | 训练 MAC |
| --- | ---: | ---: | ---: |
| numeric 教师模仿 | 1/4 | 1/3 | 86,016 |
| Boolean 教师模仿 | 3/4 | 1/3 | 86,016 |
| pooled | 3/4 | 1/3 | 86,016 |
| domain-routed | 1/4 | 1/3 | 86,016 |
| 学生专家＋router | 0/4 | 0/3 | 114,688 |

直接混合没有优于最佳单教师。专家组合全部预测为 class 2。领域路由结果的参数摘要与 E4 single 相同，没有额外组合收益。

numeric 教师自身 7 条 A 输出中有 3 条 class 2；Boolean 教师有 2 条。numeric 的 4 条领域标签正确输出，其数值答案均错误。该差异说明类型分类分数不能冒充完整任务能力，更不能证明融合外部基础模型长处。

原件：[数值教师](results/teachers/numeric_specialist.json)、[布尔教师](results/teachers/boolean_specialist.json)、[全部候选结果](results/composition/RESULTS.json)。

## E4：Circuit 必要性及逐项消融

| 模型 | B | C | 训练 MAC | 活动参数 | 驻留参数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| single | 1/4 | 1/3 | 86,016 | 195 | 195 |
| fixed | 1/4 | 1/3 | 172,032 | 390 | 780 |
| random sparse | 1/4 | 1/3 | 172,032 | 390 | 780 |
| learned sparse | 1/4 | 1/3 | 286,720 | 650 | 1,040 |

预算上限相同，实际活动参数和成本没有匹配。学习图没有准确率增益，训练 MAC 为单模型的 10/3 倍。它是单跳 logit 混合，不是原生多跳 Cell→Cell 电路。

已完成 12 次逐 Cell 和 36 次逐 Cell→class-output 边消融，完整矩阵保留于 E3–E5 复核报告。6 次删 Cell、18 次删边的 logits 完全不变，涉及未活动部分。删除 learned 的 Cell 0 后，C 从 1/3 升至 2/3；另有 7 条输出边删除后正确数提高。

没有消融降低 C 的总正确数，但有单任务正确性交换和交叉熵恶化。不能据此声称所有连接都无用，也不能据此在 C 上挑选新候选。当前未显示图结构的必要性。

## E5：来源增长

| 设置 | 1 份来源 | 4 份 | 16 份 | 64 份 |
| --- | --- | --- | --- | --- |
| 固定总预算 | 执行：B 3/4，C 1/3 | BLOCKED | BLOCKED | BLOCKED |
| 固定每来源预算 | 执行：B 3/4，C 1/3 | BLOCKED | BLOCKED | BLOCKED |

实际可用 A 来源文件为 2。两种模式选中的都是 GATES.json 内同一条 Boolean 任务，重放 32 次，各 12,288 MAC；最终参数和预测完全相同。4/16/64 被来源不足规则阻断，没有补造用户或样本。

这不是用户规模增长曲线，也没有分布式并发训练证据。采用率、有效真实经验规模和长期遗忘仍没有相应观测。

## E6：采用决策与冷进程

两臂 A 训练与 B 评价均完成，最终均为 **NO_UPDATE**。规则要求候选严格超过所有基线，而规则基线 B=4/4，故本轮配置无法触发 Adopt。

两次被选中的模型都是原 parent：`ae9aa240316a4af47361efcd5ee56473375440a8c6242cb5b3b5b44064f8b582`。各自 C 为 0/3，使用的是同样三个任务。

冷进程 PID 分别为 `2777482 → 2777508`、`2777483 → 2777509`，均退出 0。它们重新读取实验 SQLite 选择状态、加载同一 parent，并复现最后一道 C 的输入、输出 UTF-8 字节、token 数和模型摘要。

因此实际覆盖的是“正确保留父模型并重载”，而不是“采用 LoRA 候选后保持收益”。被复现的是失败输出。原生 CellOwner/daemon/FinalUse/结算没有由此取得资格；生产和独立 E6 均保持阻断。

原件：[答案臂](results/E6/final_answer/RESULT.json)、[轨迹臂](results/E6/trajectory/RESULT.json)、[两臂一致性复核](READOUT_E6.json)。

## 计算量与工程验证

- 七组 LoRA：224 次 AdamW 更新，81,920 个 padded training positions，训练区间 CPU 合计 527.630 秒、wall 合计 266.742 秒。并发区间相加不是整体历时；整体为 348.875 秒。
- 每个模型的训练前后参数摘要改变，七个最终摘要不同。首末 loss 降低发生在可能不同的训练记录上，不能作为独立能力证据。
- 11 个数值候选：2,080 次更新；训练 1,200,128 MAC；加 B/C/全部消融共 1,288,256 MAC。这里仅统计声明范围内的线性投影和参数梯度，未覆盖完整算术、加载、网络与能耗。
- 14 次共享特征编码 wall 合计 1.552096 秒；教师副本没有重复记这笔编码成本。
- 46 项工程完整性测试在格式化前通过；Mac `just fmt` 成功，20 个 Python 文件格式化前后 AST 一致。测试包含 fixture 和 mock，不是独立学习验证。
- 归档重建实际通过：新目录中的 498/498 份文件匹配原始大小/SHA256，父模型加七个候选的 8 份 model manifest 均校验成功。这是材料完整性验证，没有产生新的模型推理或采用收益。
- 源码头专用 [GitHub CI 43836836220](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43836836220) 已于 09:16:38 UTC 完成，conclusion=success；原始日志记录 46 tests / OK。较早 E6 复核中的 queued 状态保留为当时观察，最终状态见 [CI_SNAPSHOT.json](CI_SNAPSHOT.json) 和 [测试日志摘录](CI_TEST_LOG.txt)。CI 通过不改变学习或生产资格。

## 后续正式实验的准入条件

1. 先统一示范、工具观察、动作、终止信号和验收器的输出协议；在 A 上校准 token 预算，冻结后再开始新 B/C。保留本轮原始失败，不用修改旧输出制造通过。
2. 接入有来源授权的实际 agent 轨迹及真实任务验证器。新增任务必须重新按来源、用户/项目、家族、时间和暴露情况分区；当前 C 已被访问，不能循环充当未来确认集。
3. E3 需要有实测互补的教师及任务级指标；E4 需要活动参数、实际计算/通信成本匹配，以及真正 Cell→Cell 边的消融。HIA 可承载类型化调用、状态和收据契约；当前数值实验没有测量 HIA 的运行时收益。
4. E5 需要新增真实来源和用户，在两种预算下分别测量有效经验、采用率、成功率、总成本和遗忘。E6 需要在预先冻结且允许真实收益出现的任务上覆盖实际 Adopt，再验证采用后的候选在新任务和冷恢复中的身份及收益。

以上是缺失证据的准入要求，不是已经取得的结果。
