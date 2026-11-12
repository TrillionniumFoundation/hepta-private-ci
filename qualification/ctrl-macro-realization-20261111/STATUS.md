# CTRL：工程闭环与当前证据边界

当前代码锚点：`e5ed7174fe80201a942395a5b1f8366f3f0a7314`（[#6078](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6078)），前置锚点为 `eabe2d8c1a23834bd0db39f683c33977b477fd9f`。
**六策略与学习内容 × 学习控制 2×2 的执行、取证和核对代码已就绪；真实实验尚未执行。当前结论为 HOLD / NoUpdate。**

## 已交付的行为

四段观察器分别记录原始公开回复与可解码观察、当前候选集合、原始选择索引及 selected_used、实际 payload/delivery/独立评分绑定。
候选命中但选错，与交付或评分不一致，分开报告；缺原始输入或旧版选择 witness 保持 null，不把历史候选当作当前可获得信息。
READ 宏完整包含 `PREPARE_ROI → READ_ROI → 重新选择 → WRITE_TEXT → STOP`，并记录其实际成本；STOP 使用同一 `WRITE_TEXT → STOP` 终结过程。

固定内容、控制计划、合法动作、评分与价格后，可预登记 `STOP / light / tuned-fixed / point / unconditional / conditional` 六臂。
另可预登记内容学习 on/off × 控制学习 on/off 四臂；mode 声明本身不证明发生过学习。
这里 **light 是本轮宏动作的经验 cell 基线，不是旧 utility=0.47125 实验的复现**，不得直接跨协议比较数值。

完整分母固定为 contexts × arms；同 source/case/seed 配对，按来源等权汇总。
实际 native source SHA、原始 wire、候选与选择、公开输入、delivery 和 score 均须通过各自绑定；fit/calibration/evaluation 的来源 ID 或原始字节别名不能相交。
新的 matched collection 到 fit-row 转换器保留整个计划分母：UNKNOWN、重复身份、缺证据或不适用 READ 条件不能通过删行变成有效拟合输入。

执行输出为 create-only；每个 START 先于 host 构造。构造或入账失败为 FAILED，host 调用未确定结束为 UNKNOWN，START 无 terminal 为 UNKNOWN，未开始计划项为 NOT_STARTED。
已有输出不可自动重放；reconcile 只读，不启动 actor。参考答案仅在原始完成证据、允许角色及 scorer/reference SHA 检查后用于 posthoc 诊断，并隔离于后续 actor 的可读路径。
具体注册字段、pin 的两种口径、部署和命令见 [RUNBOOK.md](RUNBOOK.md)。

## 本地验证：明确区分批次与覆盖清单

| 记录 | 实际观察 | 口径 |
|---|---:|---|
| 既有 CPU 批次 | 23 个模块，153 tests，通过且零 skips | 原 RESULT 与每模块原日志均核对；原记录没有 commit 字段 |
| 本次 collector 定向验证 | 7/7，通过且零 skips | 干净 `e5ed7174`，执行前后 commit/tree/clean 一致 |
| 本次 converter 定向验证 | 6/6，通过且零 skips | 同上，单独调用 |
| 最新已观察的方法覆盖清单 | 160 | `153 − 旧 collector 6 + 当前 collector 7 + converter 6`；**不是一次 160 tests 整跑** |

本次只重新运行上述两个新增/变化套件，没有重跑其余模块，也不把既有 153 方法追认成最终 head 的一次完整验证。
实际本地解释器为 Python 3.12.14、NumPy 2.3.5、Pillow 13.0.0、Torch 2.5.1+cpu；当前 CPU CI workflow 固定 Pillow 11.3.0，因此本地结果与 CI 环境不能视为相同。
计数、原日志摘要、实际 source-head 执行记录及本轮变更的源码/测试 SHA 见 [LOCAL_VALIDATION.json](LOCAL_VALIDATION.json)；两个定向调用的原始合并 stdout 见 [TARGETED_TESTS.log](TARGETED_TESTS.log)，各原始字节段有独立 SHA 与偏移。

既有本地 native fixture 在 setUpClass 的强制隔离检查处失败：Landlock `abi=-1, errno=38`，`enforced_before_actor_exec=false`，实际执行 native 测试方法数为 **0**。
这是明确失败门禁，不能记为 native 通过、skip 或业务实验完成；本轮未降低隔离要求。本地通过不代替 CI。
逐阶段 exact-head 状态和已核验的原始日志证据见 [CI_STATUS.json](CI_STATUS.json)，状态以该记录的观测时间为准。
阶段 1 的 [run 43128919632](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43128919632) 实测 85 项通过，阶段 2 的 [run 43129296842](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43129296842) 实测 98 项通过，阶段 4 的 [run 43130973217](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43130973217) 实测 122 项通过；三次对应不同 head，包含重叠套件，**85、98、122 不相加**，也不替代最终 head 的验收。

## 原始业务身份与效益结论

[READ_ONLY_ORIGINALS.json](READ_ONLY_ORIGINALS.json) 是 `2026-11-12T01:11:42+00:00` 只读观测记录的逐字节副本。
V4 和 FIT40_GAP 的精确私有原请求尚未恢复，没有已验证的原业务 job ID；原 terminal_status 均为 UNKNOWN，公开记录摘要未变。
一次 inventory 探查的 cursor chain 不完整，不能从空的部分返回推断不存在业务任务；staging job 不计入业务结论。
该观测明确记录 business launch、replay 和无原 ID 的状态查询均未尝试。未补造原身份、未换 key 重跑、未补终态。

当前新交付没有新增已完成真实 matched 来源、六策略效益或 2×2 交互结果。
runner 的 task_cost 口径仅为初始化、选择、动作、评分与 admission 耗时 × 固定 latency_weight；provider、energy 与拟合/校准/调参的一次成本仍未知。
因此 full_cost_observed=false，完整成本净收益、配对效益与因子交互不能获准出数；未知不能填 0，fixture 改善不能作为策略收益。
生产采用、原生 owner 认证与新来源统计效益均未获证明，继续 **HOLD / NoUpdate**。

## 评审入口

- [#6050](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6050) · [#6052](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6052) · [#6055](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6055)
- [#6065](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6065) · [#6067](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6067) · [#6070](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6070)
- [#6071](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6071) · [#6077](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6077) · [#6078](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6078)
