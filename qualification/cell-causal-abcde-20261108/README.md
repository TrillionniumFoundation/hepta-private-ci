# Cell A–E 因果实验：本轮执行结果

日期：2026-11-08。审阅入口：[Draft PR #5345](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5345)。

## 结论

**本轮判定为 HOLD。B 已完成一轮真实、配对、有限预算的工程试跑；当前结果没有建立 NDU 或持续状态的部署净收益，也没有建立 Cell 或 RSI 路线成立的证据。A、C、D、E 已补齐关键证据契约与能力审计，但没有完成对应的真实因果实验。**

在事先采用的部署效用 `score − 0.01 × deployment_wall_seconds` 下，开发集上全部 8 个 NDU−Light 对照的点估计均为负。联合训练的 NDU/reset 出现小幅评分提高，但额外耗时超过了这部分提高。联合训练中，NDU 的 persistent−reset 评分和部署效用点估计都下降。完整改进预算仍有未知项，因此这里的部署效用不等于训练、搜索、组织、能源和平台费用全部计入后的效率。

这是一轮小样本工程试跑：只有 **2 个独立训练 seed**；开发集为 **10 个 case、2 个 source group**，保留验证集为 **2 个 case、2 个 source group**。五种任务家族来自同一个收据理解领域。960 条部署记录和 56 个训练作业都不能当成 960 或 56 个独立训练重复。全部区间为未做多重比较校正、没有功效保证的描述性区间。joint/Hepta/reset 的 NDU−Light 评分增益只出现在两个训练重复中的一个；两个重复的部署效用差均为负。

## 实际完成范围

| 项目 | 实际结果 | 解释 |
|---|---:|---|
| 新采集 v2 训练轨迹 | 20 条完整 episode chain、50 条记录、30 个已观察 successor | 2 个训练 source group；原采集模式全部为 reset，持续状态训练重放同一份离线数据 |
| 训练 | 56/56 作业完成 | 8 个 content pretraining；8 个 frozen fit；40 个 joint fit |
| 独立训练重复 | 2/2 seed 组完整 | seed 104729 与 130363 |
| persistent/reset 训练配对 | 28/28 通过 | 数据、完整 episode、批次顺序、优化器步数和训练机会匹配 |
| 构造器初始化字节审计 | 2/2 通过 | 比较的是预训练之前的随机起点 |
| 模型迁移与参数重放 | 56/56 精确一致 | 只改变模型所在目录，保留原权重、receipt 与 deployment profile |
| 调优 | 80/80 profile 候选完整；400/400 原评价记录保留 | 原终态 Completed 380、BudgetStop 20；每个 profile 5 个调优 case |
| 开发与保留评价 | 960/960 计划记录存在 | 80 个选中 profile × 12 个 case |
| 原部署终态 | Completed 916；BudgetStop 44 | 保留原执行状态，不把 BudgetStop 改写为原执行成功 |
| 统计可观察终态 | 960 条 | 44 条 BudgetStop 均有绑定的实际评分和非负部署耗时，按前瞻冻结规则进入统计 |
| 配对分析 | 396/396 对比完整 | 33 个预注册 contrast × 2 regime × 2 split × 3 metric；无删除的未知行或缺失分母 |
| 工程测试 | 79 通过、0 skip | 包含真实 Torch 初始化比较；A/C/D/E 的 fixture 只验证契约逻辑 |

训练 regime 中，`frozen` 使用共享的冻结内容路径，`joint` 包含各控制器条件下的训练路径。两者均独立报告，不合并成一个总体效果。

## B 的主要结果

下面均为开发集配对点估计，正数表示表中左侧条件更高。`Δscore` 使用原始独立评分；本轮没有需填入失败惩罚的已知失败，因此与 failure-adjusted score 的这些点差相同。`Δutility` 仅扣除事先定义的部署耗时。

| 训练方式 | 对照 | Δscore | Δutility |
|---|---|---:|---:|
| frozen | Ordinary：NDU − Light，reset | +0.000191 | −0.019259 |
| frozen | Hepta：NDU − Light，reset | +0.000191 | −0.018274 |
| joint | Ordinary：NDU − Light，reset | +0.005591 | −0.016418 |
| joint | Hepta：NDU − Light，reset | +0.006107 | −0.011754 |
| frozen | Ordinary/NDU：persistent − reset | +0.000003 | −0.009048 |
| frozen | Hepta/NDU：persistent − reset | +0.000003 | −0.009167 |
| joint | Ordinary/NDU：persistent − reset | −0.005235 | −0.018106 |
| joint | Hepta/NDU：persistent − reset | −0.005722 | −0.013771 |

**Hepta 内核的局部差异。** 在 joint/NDU/reset 下，Hepta−Ordinary 的评分点差为 +0.000516，部署效用为 +0.004492；在 joint/NDU/persistent 下，两者分别为 +0.000028 与 +0.008828。Light 条件下没有观察到内核评分差异。上述局部差异没有改变本轮 NDU 相对 Light 的负部署效用，亦不足以归因为新的学习机制。

**更强的规划比较不能省略。** joint/reset 下，NDU 相对同内核 MPC 的部署效用点差为 Ordinary +0.002882、Hepta +0.005194；相对同内核 VOI 则为 Ordinary −0.020688、Hepta −0.016511。全部固定策略、VOI、MPC 和状态对照都保存在 [B_CONTRASTS.csv](B_CONTRASTS.csv)，没有只挑选正向结果。

**原先锁定的最强对手。** 在每个 fit/regime/memory 中，从两个内核 × fixed/VOI/MPC 的六个比较器里，按调优效用和既有 tie-break 规则选中的对手已逐项复核。NDU 在八个开发条件下相对该对手的部署效用点差也全部为负；joint/reset 为 Ordinary −0.020456、Hepta −0.015964。该对手在 pilot 结果之前已经锁定；本次汇总仅为描述性报告，没有新增预注册 contrast、区间或显著性宣称。详见 [B_LOCKED_COMPARATOR.csv](B_LOCKED_COMPARATOR.csv) 与 [B_PROFILE_REPORTING_BINDING.json](B_PROFILE_REPORTING_BINDING.json)。

**保留验证暴露了零分问题。** 本轮保留验证的 160/160 条原记录评分均为 0，因此 33 个 contrast 在两个 regime 下的评分点差全部为零。这没有建立保留能力、无退化或未见任务泛化。开发集 800 条原记录中，388 条评分为 0、412 条大于 0；跨全部配置的原记录描述性均值为 0.301098。原协议没有二元质量通过阈值，不能将执行 Completed 当成质量通过率。这里没有添加虚构的 initial incumbent profile，也没有运行封闭确认测试。

### 保留零分的事后只读诊断

在冻结主分析完成后，逐一读取并核验了这 160 份原 `result.json` 的 SHA。记录到的动作序列为：47 次直接 `STOP`；110 次 `WRITE_TEXT → STOP`；3 次连续五次 `WRITE_TEXT`，随后 `PREPARE_ROI → STOP`。最终 160 次都没有交付图像，图像像素验证和 coverage 均未成功；113 次最终文本非空，但文本质量仍为零。输出承诺保存检查全部通过，因此现有零分不是该检查损坏造成的惩罚。

这些是原决策与输出的观察结果，不能推断所有内部工具均未运行，也没有将其包装成新的预注册假设检验。只读诊断 v1 因把 compact 层 evaluator 字段当作原 result 字段而失败；原失败回执保留，v2 修正字段绑定位置后成功。没有重新执行 episode。详见 [RETENTION_ZERO_DIAGNOSTIC.json](RETENTION_ZERO_DIAGNOSTIC.json) 与 [RETENTION_DIAGNOSTIC_ATTEMPTS.json](RETENTION_DIAGNOSTIC_ATTEMPTS.json)。

### 持续状态究竟测到了什么

当前实现测量的是 `matched_training` 总效应：reset/persistent 从同 seed 的相同构造器参数出发，使用相同记录、训练机会和分组批次，但各自执行对应状态模式的 content 预训练和后续训练。因此实际 prefit checkpoint 可以不同。

**尚未完成同一个已训练 checkpoint 上、仅切换部署状态的 `deployment_state_ablation`。** 当前 profile 严格绑定训练与部署模式；不能移除校验后混用 checkpoint 来制造这项对照，也不能把上述总效应解释为纯部署记忆效应。

## 成本与执行来源

| 阶段 | 实测墙钟秒 | 实测 CPU 秒 | 计量范围 |
|---|---:|---:|---|
| 新训练轨迹采集 | 34.734 | 未知完整值 | collector 自身 CPU 不包含全部子进程 |
| 56 作业训练外层进程 | 451.670 | 423.588 | 包含内部各训练作业；内部 451.433 秒 campaign 和各 job 之和与此重叠 |
| 评价 runner 内部总封套 | 858.689 | 2226.788 | 已包含下属调优、pilot、控制器、预测、搜索及 episode 路径的进程计算 |
| 其中调优子阶段 | 301.706 | 848.721 | 已包含在上一行，不再相加 |
| 其中 pilot 子阶段 | 554.837 | 1376.002 | 已包含在评价总外层，不再相加 |
| 冻结统计分析 | 3.443 | 3.435 | 读取既有结果，没有重新训练或重新执行 episode |

能源、平台费用、完整上游采集 CPU、准备与失败平台预检、原生作业最外层包络、传输与存储，以及尚未实际运行的 D 组织成本仍未完整计量。未知值保持未知。没有把测试、搜索、评价或者控制器的嵌套计量反复相加，也没有宣布 `full_improvement_budget_complete=true`。

实际训练与评价运行在原 HeptaRuntime 的 **ai395 CPU 环境**。Kaggle 原请求返回 `REJECTED / NOT_SENT`；Colab 没有分配计算。本轮没有 GPU 云执行结果。相同冻结源码、数据和 56 作业计划在原 ai395 通道完成，没有修改云平台的范围或预算限制来强行提交。

主分析第一次提交的 RPC 回执超时，之后读取原结果并以同一个完整请求和操作标识对账：原 job `1a1baa1acfc-12894-1c0d`，`reused=true`、`retried_launch=false`、最终 `succeeded / exit 0`。超时和 registry 清单字节上限错误保留为传输诊断，没有新建分析尝试。

## A、C、D、E 的当前门槛

| 实验 | 已落实 | 本轮尚缺的真实证据 |
|---|---|---|
| A：Cell 增益来源 | 匹配模型、信息、记忆、工具、训练与调优机会的协议；局部状态与可训练分化能力检查；状态、分化和角色消融要求 | 本轮连接的 Python 研究 runner 尚未实现并执行三种严格匹配架构。共享模型的多个 head 不能单靠命名充当具有独立局部状态和可学习分化的 Cell |
| C：组合与继承 | none/A/B/AB/shared-base 与 reset/migrate 的组合契约；完整 bundle 一致性；原 owner 的下一任务消费与两类恢复证据接口 | 两个真实相依 Cell 的更新实验、被选完整 bundle 的实际后继任务消费、状态迁移/清空，以及模型回退和外部效果恢复的原证据 |
| D：动态拓扑收益 | 固定图自适应调度与动态图的公平比较契约；实际转换、迁移、消息、后继执行和恢复证据检查 | 仓库已有 `apply_governed_topology`、migration-owner、恢复与 TaskFlow 编译原语，但本轮没有绑定这些原语完成严格 D 对照；没有本轮原 owner、实际图变更及完整组织成本证据 |
| E：父代与后代改进器 | 共同起点、完整改进预算、全部尝试分母、独立接受、净增益、成本、回退、泛化检查；UNKNOWN 上下界保留 | 没有真实成对的父代/后代改进器执行与独立接受结果，因而没有 RSI 实验结论 |

详见 [ACE_CAPABILITY_AUDIT.json](ACE_CAPABILITY_AUDIT.json) 及其后续字节绑定，以及 [D_CAPABILITY_AUDIT.json](D_CAPABILITY_AUDIT.json)。这些审计定位实现和原始证据缺口；它们不会通过本地哈希、fixture 或新造的签名身份补出缺失的 owner、独立评价或真实外部效果。

## 路线决定

本轮数据不支持扩大 Cell 数量、将 NDU 的部署净收益视为已成立，或宣布真正 RSI。优先需要闭合的是：保留验证全零分的原因与基本任务质量、同 checkpoint 的状态消融、NDU 的预测/规划耗时和更强比较器、更多独立训练与独立来源、完整成本账本；随后才有足够条件讨论状态或结构变化是否带来可复现收益。

A 需要真正实现三种架构的公平执行；C 需要完整 bundle 的下一任务实际消费及双重恢复；D 需要已有原语下的严格固定图/动态图对照；E 需要真实父代/后代改进器的独立评价。上述门槛均保持为未通过，没有以工程测试通过替代。

## 源码、检查与证据索引

代码 head：`1e9c2890fef92ea63dab472e1bdb0c444c9656b5`；tree：`20f0836afc9c790fee23ddd150817a6d11550598`。本轮基线及提交链起点：`9c6c18cec8c56260d633de5a6adf321de2a4e3d4`。

本轮修改 18 个 Python 文件，分成 14 个源码审阅提交。实际执行 capsule 中 50 个源码文件均有精确字节绑定，其中 18 个为修改后的文件、32 个匹配原基线 Git blob。执行范围为该源码闭包与原环境依赖，没有声称执行了整个 Git tree 或完整 Rust 构建。

Ruff 0.15.13 格式化后，18 个源码文件的 AST 全部一致。原 ai395 测试 79 通过、0 skip。`just fmt` 在本地导出环境因缺少 `just` 与对应 justfile 无法执行；本轮没有 Rust 变更。GitHub CI 尚未全绿：已检查的两项失败分别在 DotSlash 与 Bazelisk 下载阶段返回 HTTP 504；这不能解释所有其他失败。状态和原日志摘录保留于 [CI_CODE_HEAD_LATEST.json](CI_CODE_HEAD_LATEST.json) 与 [CI_CODE_HEAD_SNAPSHOT.json](CI_CODE_HEAD_SNAPSHOT.json)。

关键可审阅文件：

- [PROTOCOL.json](PROTOCOL.json)：前瞻 A–E 协议。其 `execution_started=false` 是冻结时的状态，当前执行结果应读取本报告及结果回执。
- [SOURCE_CLOSURE.json](SOURCE_CLOSURE.json)：执行源码与已发布 Git 代码身份对应。
- [B_TRAINING_PROJECTION.json](B_TRAINING_PROJECTION.json)、[B_TRAINING_JOBS.jsonl](B_TRAINING_JOBS.jsonl)、[B_TRAINING_PAIRS.jsonl](B_TRAINING_PAIRS.jsonl)：完整训练分母与配对审计。
- [B_ANALYSIS_SUMMARY.json](B_ANALYSIS_SUMMARY.json)、[B_CONTRASTS.csv](B_CONTRASTS.csv)：全部 396 项配对结果与限制。
- [ANALYSIS_POLICY.json](ANALYSIS_POLICY.json)、[B_STATUS_ADAPTATIONS.json](B_STATUS_ADAPTATIONS.json)：前瞻终态处理与每一条 BudgetStop 的保留记录。
- [EXECUTION_HELPERS.json](EXECUTION_HELPERS.json) 与 `tools/`：实际评价、冻结分析及描述性 profile 报告所用 helper 的字节绑定。

完整下载证据包含 56 个模型及其原回执、583 个训练输出文件、冻结源码/训练输入、原始评价与搜索账本、完整分析 JSON 和原请求对账/传输恢复记录。训练 archive 为 4,707,631 字节，SHA-256 `dff6710ce9f2a9698bc619fb545c76a51d0a1b7baa02777f870a0593269c0b36`。最终评价原文件 archive 为 961,082 字节，SHA-256 `97560c34ebe322956f3b23d4d20a2f0ecffb7419586a22265f6f0ff10e109f78`。完整分析 JSON SHA-256 `64886fec9deca29abe5b9cb52b383f8cee5dd073a76bf8d894580d9953bb3f70`。

旧采集设计里继承的描述性备注保持原字节；本轮实际训练和评价规模以冻结的新计划、原结果与完整分母为准。所有修改保持在研究 draft；没有合并、生产采用或确认性结论。
