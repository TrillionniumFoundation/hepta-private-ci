# 五问题的增量封存后分析，2026-10-31

本目录把原已登记的五问题分析补成可执行、可逐项核查的解释层。它保留原实验、样本、baseline、训练预算、bootstrap、统计 family、阈值与结论，读取完成且封存的原结果后增加有限描述性诊断。

**本次源文件准备和审查仅使用源码、元数据及人工构造的测试。新增补充尚未对真实科学结果执行，本文没有填写实验结果。** 工程代码和测试通过不代表原全量研究完成、科学有效性成立、收益为正或可以采用该控制器。原历史失败、缺失成本和未满足的资源合同仍由原记录保留。

文件名 `p0_actions.py` / `p1_interpretation.py` 表示新增实现模块，不能与原研究的 P1–P5 问题编号混用。

## 五问题与实现的对应

| 原问题 | 原证据与本目录的增量 | 解释边界 |
| --- | --- | --- |
| **P1：动作是否改变合法后继？** | 原 path/bank 统计、原 `A_INACTIVE_GLOBAL.json`；`p0_actions.py` 将 A 的实际 strict-gate 选择与同 parent 的 baseline 后继差异连接。 | 请求 override、guard 接受、完整物理状态改变、参数/optimizer 改变、语义输出改变及收益分别记录。A 校准活动不能代替 B 部署活动；C 首个整体 hash 改变不能定位参数/optimizer 改变。 |
| **P2：标签、baseline、时钟和剩余预算是否一致？** | 保留原 A 的 108 行 gated calibration；新增 C 两个 heads 各 24 行的 strict-gate 校准诊断，并核对原 bank 标签、分割与 baseline-tail 状态链。 | A 为候选 macro48 后固定各 seed baseline 至 clock288；C 为候选 macro16 后 baseline2 至 clock96。这些是固定 tape 的 realized contrast；不是 expected Q 或 uniform certificate。 |
| **P3：field 遗漏什么决策信息？** | 保留 B 的 `field-history task`、`full-state-field task` 与原 W shared-action 诊断；`p1_interpretation.py` 限定这些比较能支持的解释。 | Full-current-state ridge 是学习出的估计器，不能视为信息 oracle；history 仍付 H12 观察成本。W 的三个预定近场构造对不代表实际访问状态的分布；最优动作集合相交时，排序差异不强迫决策损失。 |
| **P4：独立收益是否胜过 ordinary 与轻量控制？** | 原 B 全部十项效应、两个 observer、逐固定模型值和原 gates 全部保留；operational coverage 检查当前已声明的 path/stage/scoring 成本范围。 | `fixed-taper-field` 的正值有利于 taper。原 field gate 不包含 taper 比较或完整成本 Pareto 条件；选择操作的 timer 不等于整条路径耗时，历史未知成本不补零。 |
| **P5：Hepta 是否额外适配？** | 原 C 的 interaction、两个 simple effects、跨架构 field 比较及四项 own-warmstart retention 共八项全部保留；新增机器可读的解释分类。 | 正 interaction 可以只是两个负 simple effects 中 dual 较少受损。原 interaction+retention gate 不要求 dual simple effect 为正。C 的有限解析事件律处理不能推广为完整 Hepta/NDU 或 LLM 尺度优势。 |

五问题的原定义和完整解释范围见 [原 review 文档](../../operational/parameter_field_recovery06/postseal/README.md) 与 [原结论模板](../../operational/parameter_field_recovery06/postseal/FINAL_CONCLUSION_TEMPLATE.zh-CN.md)。本目录不替换原 `REVIEW.json`、`COMMENTS.zh-CN.md`、`A_INACTIVE_GLOBAL.json` 或 primary aggregate。

## 原冻结身份与读取边界

本次实现对照的源仓库提交为 `bc4e757f5c90f6365f383c1127be710d2ded874a`（C2）。以下是已核对的原文件字节身份；表格本身不是运行完成凭据。

| 原文件（相对仓库根目录） | SHA256 |
| --- | --- |
| `experiments/parameter_field_fullstudy_20261029/PROTOCOL.json` | `2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55` |
| `experiments/parameter_field_fullstudy_20261029/analysis.py` | `46ace84fa720026daa2f0b9de95b8c446f4e87ae6f1873ba43e9bceaca3f73e2` |
| `experiments/parameter_field_fullstudy_20261029/heads.py` | `19254959a30e3719024841dc91376d1ecdfa018c30427b962a265e3b3d4647f7` |
| `experiments/parameter_field_fullstudy_20261029/registrations/A_SOURCE_FREEZE.json` | `2a5219147d38ebb6514059bd69e2d3489bf7d69d213cd01343455f63a08a53d2` |
| `experiments/parameter_field_fullstudy_20261029/registrations/C_SOURCE_FREEZE.json` | `5f427c8a8cebe8c96a2a0d81318e22d286dc0aaa8b3dbf4d5844df2177949c6d` |

真实调用需要实际原 postseal review 的 `COMPLETE.json` 及调用方独立持有的 SHA256。入口先核对该完成元数据和它绑定的原 review 实现，再重新进入原 `open_gate`；只有原门接受后才解码已封存的 review、aggregate 与所需 bank payload。

原门要求 `FULL_PRIMARY_PIPELINE_AND_LITERAL_RESTORE_VERIFIED`、完整 14 个 controller jobs、30 个 completion seals、原源文件身份及完整 literal-restore 范围。C2 的原 execution06 入口继续核对实际 primary/17-ACK 审计、imported A17 的 producer 链以及原测量与完成记录。新入口不把单个 `COMPLETE.json`、source hash、测试通过或预期文件名当作这些条件的替代。

新增代码及实际集成方式须在首次真实使用前单独冻结。不要将本目录反填进旧 A/C source freeze；原冻结身份保持不变。原 review 有 integrity issues 时，补充保留这些问题并阻止无条件解释。未通过读取门时没有补造科学结论。

## 调用方式

从包含冻结原代码和本次新增文件的仓库根目录调用。以下是**真实原 review 已完成之后**的调用模板，路径和 SHA 必须替换为实际独立选定的输入；不是本次准备期间已经执行的命令。

```bash
python -B -m supplements.parameter_field_execution_20261031.run_review \
  --review-complete '/absolute/path/to/original/postseal/review/COMPLETE.json' \
  --expected-review-complete-sha256 'ACTUAL_EXTERNALLY_SELECTED_SHA256'
```

正常诊断向 stdout 输出一个 JSON 结果；进入处理后的拒绝或失败写入 stderr。缺少输入或 SHA 格式错误时，只在 stdout 返回 `NOT_EVALUATED`，不读取科学输入。由实际已登记的测量包装器把输出保存至新的、不覆盖已有结果的路径，并保留退出码、源身份和测量凭据。本入口不创建新的科学 RAW，不重跑原 review、原补充、训练、端点评分、拟合或 bootstrap。

统一输出 schema 为 `hepta.parameter-field.unified-postseal-review.1`：

| 字段 | 含义 |
| --- | --- |
| `P0` | A 后继连接和 C gated calibration 的完整诊断行与汇总。 |
| `interpretations.B` / `.C` | 原效应、两 observer 区间分类、原 gates 与有明确 scope 的证据状态。 |
| `coverage_audit` | 原分析算术与当前已声明成本字段的覆盖检查。 |
| `original_statistical_gates` / `original_review_integrity` | 原统计布尔值与完整性问题原样保留。 |
| `consumed_inputs` / `gate_input_descriptors` | 原读取追踪器的输入身份，以及实际 review-completion、review、aggregate 描述符。 |
| `implementation_sources` | 参与本次运行的五个源文件字节身份，包括三个新增实现和两个既有 operational 依赖；不替代独立注册。 |
| `timing` | 分步骤 wall/CPU 和包围这些步骤的本次总时段，明确排除项与不可重复相加范围。 |

| 退出码 | 状态 | 可得结论 |
| --- | --- | --- |
| `0` | `DESCRIPTIVE_COMPLETE` | 补充描述检查完成；不是正向效应、完整历史成本或采用证明。 |
| `3` | `ORIGINAL_INTEGRITY_ISSUES` | 保留原问题，阻止无条件科学解释。 |
| `3` | `COST_COVERAGE_INCOMPLETE` / `EVIDENCE_CONTEXT_INCOMPLETE` | 成本或证据缺口保持可见，未改写原统计结果。 |
| `2` | `NOT_EVALUATED` / `INTEGRITY_FAILURE` | 读取门未完成或后续检查失败，没有可采用的本次描述性完成结果。 |

如仅需 A/C 动作诊断，也可在同一完整门之后使用：

```bash
python -B -m supplements.parameter_field_execution_20261031.p0_actions \
  --review-complete '/absolute/path/to/original/postseal/review/COMPLETE.json' \
  --expected-review-complete-sha256 'ACTUAL_EXTERNALLY_SELECTED_SHA256'
```

`p1_interpretation.interpret(stage, formal_analysis, evidence_context=...)` 是无文件读取的纯函数。真实数据应通过统一入口传入，使原门、效应算术核对和证据范围一起保留。独立调用该函数不能验证输入来源。未提供完整性、活动或成本证据时，相应状态为 `unknown`，不会从正向 CI 推断。

## 新增诊断的精确范围

### A/C strict-gate 选择与后继

`p0_actions.py` 的 A 分母为三个固定 seed、每 seed 48 个 parent、四动作，合计 576 个原后继记录。选择连接只涵盖每 seed 三种 head 各 12 个 calibration parent，即 **108 行、36 个不同的已登记 parent slots**。每行保留请求 override、guard 接受、同 parent 的 baseline 物理后继是否相同、参数/optimizer 组件是否改变及原数值范数。controller history 比较不可用，不声明任意未来 history-policy 等价。

C 每架构读取完整 96 行原 bank，核对 72 fit / 24 calibration 分割、12 维 field head、固定 baseline2、原每例配对标签及所有已记录 baseline-tail 交易链；只有 24 行 calibration 进入 gated 结果。两个架构共 **48 行、零个新独立样本**。C 的首个完整 training-state hash 比较有固定 parent、schedule、clock 和 baseline tail 约束。C 没有本诊断可用的逐组件数值差，因此明确输出 `component_resolution_available=false`。

选择仍执行原冻结 `predict` / `choose` 的严格规则：唯一最佳非 baseline 且 margin **严格大于**原 threshold 才 override；tie 或阈值不通过仍按原规则 fallback。校准 parent 已经参与 threshold 的选择，同 schedule/prefix/seed 的行存在依赖；结果不提供独立测试保证。`certificate=false`、`new_independent_samples=0` 始终保留，可得增益为零时 regret/gain 比率为 `null`。

新 C 检查使用原记录的标签和 hash 链，不恢复或重新训练模型。它不扩充原四个预登记 C reconstruction audit 的 literal-replay 范围，也不把 A/R 的 576 个 terminal 重放范围移植到 C。

### 原区间与解释

`p1_interpretation.py` 原样保留完整效应记录及 `statistical_thresholds`。它对 reward/audit 分别比较已有 CI 与原方向阈值，再区分共同支持、共同低于阈值、跨 observer 冲突、未定和缺失。CI 触及阈值不构成严格通过，零差或不显著不表示等价。原 family 的覆盖范围仍按每个 observer 解释，不新增跨 observer 联合同时覆盖保证。

B 的 `field-ordinary task` 阈值为原 `0.001`；clean effects 保留原 `-0.01` retention margin；其他方向性比较对照零。原 B field gate 的逐固定模型非负条件继续由原分析保存，不被简化为 pooled CI。

C 使用原关系：

```text
dual increment     = dual+field12     − dual+ordinary
ordinary increment = ordinary+field12 − ordinary+ordinary
interaction        = dual increment − ordinary increment
```

正 interaction 且两个 simple effects 都被原区间支持为负时，分类为 `positive_interaction_with_two_negative_simple_effects_less_harm`；只有该双负条件成立才赋予“较少受损”分类。正 interaction 而未建立正 dual increment 时，不声称 dual 收益为正；缺失、不确定与负效应分别保留。原 gate 的通过/未通过绝不因这层解释而重写，所有八项 C 效应和四项 retention 都保持可见。

### 完整性、活动和成本

[operational coverage](../../operational/parameter_field_five_questions_20261031/postseal_analysis_coverage.py) 核对原 B/C 完整 family、seed、source-pair digest、8000 draws、原 quantiles、逐 seed/arm/point 算术与原布尔条件。它没有重建原始像素身份或再算 CI。

成本核对范围是已声明的当前 path/stage/scoring 与原 engineering preflight 行。仅当原 producer 明确采用完整路径总体上的可选稀疏计数器时，缺省项可按该 schema 的零解释；其他缺失不得补零。B 路径 timer 仅覆盖已命名操作，当前完整字段覆盖不表示完整历史成本已知。所有组件计时与包围它们的总计时均有嵌套关系，不能相加；wall time、peak RSS 也不能跨记录简单求和。本入口的总时段从模块导入、CLI 解析之后开始，在输出序列化之前结束；进程启动、导入、解析、输出和凭据写入成本由实际外层 `wait4` 包装器测量。

统一解释将 B/C 部署活动保留为 `unknown`：本目录的 A/C calibration 诊断并不建立 B/C evaluation occupancy 的活动证据。原部署 trace 和原 inactivity 判断另由原 review 保留。成本覆盖状态必须连同 scope 阅读；完整性问题不等于普通阴性结果。`adoption` 和 `unconditional_net_benefit` 始终为 `not_assessed`，不增加价格、摊销期限或新的科学接受门。

[finite head guard](../../operational/parameter_field_five_questions_20261031/finite_head_guard.py) 只验证原 chooser 的有限数值域；失败中止而不伪装成 baseline fallback。新增 postseal 诊断使用该检查，并不证明原训练已安装此 guard。真实运行绑定需要独立冻结的集成与实际调用凭据。

## 工程验证与科学状态

从仓库根目录运行人工构造的测试：

```bash
python -B -m unittest discover \
  -s supplements/parameter_field_execution_20261031 \
  -p 'test_*.py' -v
```

测试覆盖原方向/配对、双负 simple effects 下正 interaction 的解释、retention 独立失败、missing/inconclusive/negative 区别、strict gate/tie、请求与实际后继的区分、完整 calibration 分母、C tail 链损坏，以及门前拒绝、统一入口仅进入一次原门和原结论保留。人工小 fixture 的计数不更改科学计划，也不能替代完整研究。原 B 仍是三个固定模型 ×16 schedules ×五方法的 240 条路径；原 C 仍是八个 paired seeds ×四臂的 32 条 final paths，另有 16 个 own-warmstarts。所有其余原阶段、重放、评分、封存与实际成本要求继续有效。

需要分别报告：新增工程实现与测试状态、原全量科学执行/封存状态、原完整性问题、原统计 gates、描述性解释和成本未知范围。合法的阴性或未定结果可以完成分析；不得通过缩小 frozen population、改 baseline、追加样本或换阈值取得期待的结论。实际科学结果只能来自原全量流程完成且本入口通过真实读取门之后保存的凭据。
