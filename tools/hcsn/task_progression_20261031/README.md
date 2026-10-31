# Hepta 任务价值控制：2026-10-31 研究轮次

本目录汇总强普通规划基线、可训练任务价值边界、增量 cell owner 和原生策略接口的正式结果。两组确认共完成 **29,440 次策略执行**，独立原始记录审计通过。**残差模型未通过净收益准入；同边界普通执行与解析执行具有相同任务效果；价值边界收益伴随质量取舍。主干激活保持关闭。**

- [完整中文结果报告](RESULTS.md)：设计、数学与训练范围、任务收益、内容质量、CPU、失败修复及主干决定。
- [Blocker 账本](BLOCKER_LEDGER.json)：区分已闭合工程问题和仍未建立的科学／生产资格；`all_blockers_closed=false`。
- [独立确认审计](../progression_audit_20261031/CONFIRMATION_AUDIT.md)：从 RAW 重新计算后继、内容推理、统计和成本。
- [PR #4461](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4461)：研究分支审阅入口。

PR 保持 research-only draft；发布核查时远端 `blocking-ci`、`architecture` 仍 pending，`v8-canary` 为 in_progress。当前报告没有宣称远端 CI 通过或批准主干激活。

## 冻结身份

科学冻结提交为 [`a37c99a87a25fe8417ec29ddbebb1c035d356a53`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a37c99a87a25fe8417ec29ddbebb1c035d356a53)。104 个远端文件／blob 及准备归档在 **2026-10-31 02:42:31 UTC** 核验，随后才生成两组正式确认数据。[完整核验记录](FREEZE_VERIFIED.json)

| 冻结准备 | Manifest SHA256 |
| --- | --- |
| 五 seed 策略 | `a6c002ff2d61ca0d387af8cbc7d45ab9399aeda8019ef2ea9ba1a46791fd9694` |
| 40 个价值边界拟合 | `d91df0ef83c9431777b17ec6f1071bd611e0ab3698e9efd86aef9db8a39ef356` |

两组任务独立：第一组沿用固定期限／公开日程，第二组采用明确另行声明的指数期限与再生证据过程。不要合并它们的效力样本，也不要把第二组的逐合同重新拟合称为摊销模型 OOD 泛化。

## 代码与证据布局

| 包／目录 | 内容与入口 |
| --- | --- |
| [task_policy_v2_20261031](../task_policy_v2_20261031/README.md) | OneRead、非零残差训练、共同 Q24 执行及 3,840 runs；[准备布局](../task_policy_v2_20261031/evidence/formal_prepared/PUBLICATION_LAYOUT.json)、[确认归档](../task_policy_v2_20261031/confirmation_publication/ARCHIVE_INDEX.json)、[全部开发尝试](../task_policy_v2_20261031/development_evidence/INDEX.json) |
| [value_boundary_v2_20261031](../value_boundary_v2_20261031/README.md) | 有限 QVI、直接价值优化、实际再生 owner、25,600 runs；[准备归档](../value_boundary_v2_20261031/publication/ARCHIVE_INDEX.json)、[确认归档](../value_boundary_v2_20261031/publication/formal-confirmation01/ARCHIVE_INDEX.json)、[质量与成本](../value_boundary_v2_20261031/publication/formal-confirmation01/QUALITY_AND_COST.json) |
| [recurrent_owner_v2_20261031](../recurrent_owner_v2_20261031/README.md) | 原有冻结 cell 法则的增量实现；[3,200 条轨迹回放](../recurrent_owner_v2_20261031/evidence/REPORT.json) |
| [native_task_bridge_20261031](../native_task_bridge_20261031/README.md) | 真实 native MLP／neuron owner、源码与构建身份、共同数值合同及开发资格 |
| [native_publication](native_publication/SUMMARY.json) | 五正式模型、2,560 状态、160 任务对；两轮工程复核全部原始收据、journal、witness、计量和失败 |
| [progression_audit_20261031](../progression_audit_20261031/CONFIRMATION_AUDIT.md) | 独立数学参照及三组正式 RAW 审计；[机器摘要](../progression_audit_20261031/CONFIRMATION_AUDIT_SUMMARY.json) |

准备和确认的逐文件 SHA 保留在对应 manifest；较大原始记录采用 gzip 或 tar.gz，归档索引与成员清单允许逐字节复核。五 seed 的准备／确认 tar 以 `seedNNNNN/` 为成员前缀；价值准备 tar 包含 `prepared-v2/`。价值确认按八个合同拆包，并有公共归档，完整范围以其 `ARCHIVE_INDEX.json` 为准。无需重复公开展开的小文件树。

## 复现原则与入口

从仓库根运行各模块，使用源包声明的 NumPy／SciPy 依赖；原生构建遵循 native 包中的固定 upstream 与工具链身份。先按索引解压保存的数据和准备模型，并核验 manifest，保留原始文件字节。部分原始 JSON 保存了采集时绝对目录；对读取该字段的入口，应恢复对应目录或在单独记录的重放适配层映射路径，不能把重写过路径的 JSON 冒作原样证据。

以下独立审计入口读取已有数据，不训练或替换确认样本。`--out` 必须是新的审计文件；示例路径应替换为实际解压位置。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.progression_audit_20261031.teacher_confirmation_audit \
  --prepared /path/to/teacher-prepared \
  --confirmed /path/to/teacher-confirmed \
  --process /path/to/teacher-PROCESS.json \
  --out /path/to/new-teacher-audit.json

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.progression_audit_20261031.value_confirmation_audit \
  --prepared /path/to/prepared-v2 \
  --confirmed /path/to/value-confirmed \
  --process /path/to/value-PROCESS.json \
  --out /path/to/new-value-audit.json
```

正式五模型原生复核的可用入口是 **`native_confirmation_reporting_fix`**。原 `native_confirmation.py` 为冻结的失败末端日志版本，保留作为 provenance，不应作为已修复入口。修正仅将末尾 `flush=True` 移至 `print`；模型、样本、执行逻辑和准入均未改变。[一行修复及其先行提交](NATIVE_REPORTING_REPAIR.json)

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.task_progression_20261031.stage_process \
  --out /path/to/new-native-process -- \
python -m tools.hcsn.task_progression_20261031.native_confirmation_reporting_fix \
  --prepared /path/to/teacher-prepared \
  --confirmed /path/to/teacher-confirmed \
  --binary /path/to/codex-task-native-v2 \
  --out /path/to/new-native-qualification
```

`stage_process` 的 Linux `wait4` 记录完整子进程生命周期。组件和内部 stage 计时为包含关系，不能再叠加到外层 CPU。相同冻结模型与既有样本的重放属于工程复核，不增加独立确认样本数，也不能替换原始正式结果。

重新准备／确认的算法入口及事件合同见各包 README。新的科学主张需要另行固定协议和新确认数据；当前两组已完成记录、失败尝试及所有候选都保持原样。`main_activation=false`、`native_physics_executed=false`，当前证据不包含任意崩溃外部效果结算、开放域内容泛化或硬件节能资格。
