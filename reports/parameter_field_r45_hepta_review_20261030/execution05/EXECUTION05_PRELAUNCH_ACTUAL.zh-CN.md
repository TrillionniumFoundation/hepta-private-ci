# Execution05 实际预启动证据与成本范围（实际凭据）

观察时间：2026-10-30T13:07:44.197575+00:00。执行登记：`execution05_backpressure_20261030`。冻结 C2：`7544b0a57a3b5624f3f2190449efeb84854b414d`。

**当前可确认：独立元数据复核03通过，production probe03通过，随后按原阈值完成初始容量准入并实际启动 supervisor/controller。此证据不表示研究已经完成，也不表示参数场或 Hepta 已产生正收益。**

本报告仅引用实际运维凭据并生成元数据投影；旧失败记录、源码、登记与 seal 均保持原字节。本报告生成仅处理运维元数据；实际 A17 归档与 ACK 的后续事实另列于 EXECUTION05_A17_DURABLE_ACCEPTANCE.json。

## 已发生的预启动步骤

| 步骤 | UTC 完成时刻 | 退出码 | 子进程及已等待后代 CPU（s） | 独立测量父进程 CPU（s） | 范围小计（s） |
|---|---|---:|---:|---:|---:|
| production_probe01 | 2026-10-30T12:38:48.785409+00:00 | 1 | 2.341152000 | 0.004313194 | 2.345465194 |
| independent_admission_01 | 2026-10-30T12:41:19.741633+00:00 | 1 | 0.028188000 | 0.000812506 | 0.029000506 |
| independent_admission_02 | 2026-10-30T12:42:39.266183+00:00 | 1 | 1.047531000 | 0.001104852 | 1.048635852 |
| production_probe02 | 2026-10-30T12:42:49.816443+00:00 | 1 | 2.709295000 | 0.005103649 | 2.714398649 |
| independent_admission_03 | 2026-10-30T12:44:00.392492+00:00 | 0 | 0.766355000 | 0.001609006 | 0.767964006 |
| production_probe03 | 2026-10-30T12:55:08.941275+00:00 | 0 | 3.488896000 | 0.004990955 | 3.493886955 |
| launcher_prepare | 2026-10-30T12:57:22.960449+00:00 | 0 | 0.106820000 | 0.005257446 | 0.112077446 |

Production probe01 因已登记的 Episode02 历史原始证据目录缺失而失败；原 stderr 为 FileNotFoundError。恢复原字节后的证据为 HISTORY_DEPENDENCIES_RESTORED.json。Production probe02 的失败是背压日志创建将侵占已登记的物理磁盘保留空间，原错误为 `Backpressure journal would consume the registered physical reserve`。两个失败均保留真实退出状态和实测成本，不作科学失败或内存失败改写。

Independent audit01/02 也是失败尝试，成本照计。03 中保存的说明分别为审计脚本对 C2 文件集合过严，以及审计子进程守卫拒绝本应允许的只读 Git 调用；不是通过更改科学源码使其通过。Independent03 完成源码/config/import/layout/初始队列/前瞻分析计划等只读核查，但自身明确不声称完整生产资源资格；实际 production probe03 与随后的容量门提供不同范围的证据。

Production probe03 记录：146 个历史文件绑定、32 个 execution04 root wait4 和 96 个支撑凭据完成验证；RAW 文件身份未变。模型实例、checkpoint 解码、数据值读取、科学 worker 与梯度步骤均为0。它导入实际依赖并核验登记闭合，仍不代表完整科学作业的资源测试通过。其 `own_cpu_seconds` 和 `process_cpu_seconds_total` 已包含在 probe03 的外层 wait4 中，不再累加。

Launcher prepare 的实际结果为 `MEASURED_LAUNCH_PREPARED_ONLY`，worker/upload 启动数均0；真正的启动使用下一节的 START 凭据。

## 实际容量准入与启动

Supervisor 实际 START：2026-10-30T12:57:55.365094+00:00；controller 实际 START：2026-10-30T12:58:25.981167+00:00。初始门保持 RAM 1,879,048,192 B（1.75 GiB）、磁盘 2,415,919,104 B（2.25 GiB）和连续3次通过的要求。第一条容量观测未满足 RAM 门，按冻结代码等待；之后三条连续通过。

| 观测 UTC | 连续通过次数 | 有效可用 RAM（B） | 可用磁盘（B） | OOM / OOM kill |
|---|---:|---:|---:|---|
| 2026-10-30T12:57:55.915579+00:00 | 0 | 1,540,227,072 | 5,502,201,856 | 0 / 0 |
| 2026-10-30T12:58:05.939416+00:00 | 1 | 2,273,832,960 | 5,501,952,000 | 0 / 0 |
| 2026-10-30T12:58:15.956370+00:00 | 2 | 2,813,517,824 | 5,501,800,448 | 0 / 0 |
| 2026-10-30T12:58:25.972942+00:00 | 3 | 2,704,252,928 | 5,501,800,448 | 0 / 0 |

最后一次准入为 2026-10-30T12:58:25.972942+00:00，有效可用 RAM 2,704,252,928 B、可用磁盘 5,501,800,448 B。OOM 0/0 是当前恢复环境的观测基线，不重写 execution04 的历史 OOM 记录。supervisor 窗口仍为12小时，automatic retry 为 false。

原 ADMISSION.jsonl 可继续追加；本报告仅引用前4个完整记录、1189 B，前缀 SHA256 `024e5f426af95a2b38d1ba492bc1ff4a339e41d543fab6e999f46f17f20114f5`，不把可变日志伪装成永久不变的全文件。

## 可加总范围与总成本限制

核心7个预启动工程范围小计为 **10.511428608 CPU秒**。另查得11个标准 root-engineering wait4（运行时检查、登记准备/初始化、历史证据恢复及预启动持久化辅助过程），合计 **9.055442638 CPU秒**。这些18个实际凭据均在 supervisor 启动前完成，记录的子 PID 互不相同；对应范围合并小计为 **19.566871246 CPU秒**。这是已列范围的成本下界，不能称全部恢复或全研究总成本。

另有9个简式恢复 wait4 观测，已在配套 JSON 中逐项保留大小、SHA、PID（若原记录有）、CPU、wall。它们缺少本次标准范围核对所用的完整字段，因此不猜测父进程/嵌套关系，也不并入上面小计。早期源码重建、测试、清理、未封存工程调用及本报告生成也不由这18个范围完整覆盖。

Execution05 最终 outer wait4 尚未出具时，外层 CPU 总量必须留空。最终 outer 的范围为 supervisor 从进入到退出及其已等待后代，包含嵌套 controller、科学 stage、driver、分析和内部 archive 工作；不能再加这些子项的小计。独立 root 工程辅助进程在外层树之外，才可在去重后另外核算；外部服务计算未被本地 wait4 观测。测量 launcher 自身 CPU 在最终 receipt 中独立列出，尚不能预填。

A17 的原科学执行归属 execution04，当前14个逻辑作业研究只计一次；execution05 outer 不包含其历史训练。execution04 的 outer inclusive 已含 A17，不能与含 A17 的 stage ledger 整体相加，也不能用两个不等范围数值相减制造精确 overhead。所有失败尝试保留其已测 CPU；未等待、未测量范围继续标为未知。峰值 RSS 不相加；各步骤 wall 时间不相加后称全流程历时。

## 公开证据清单

配套 JSON 列出每项原凭据的完整路径、字节数和 SHA256，并保留失败分类、独立范围及原 schema；没有复制原日志中与结论无关的内容。下表列出最关键的入口。

| 证据 | 原始路径 | 字节数 | SHA256 |
|---|---|---:|---|
| probe01 wait4 | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_steps/production_import_probe/WAIT4.json` | 1772 | `22eb1e036548f1a021e8864b4ae22604ca951efdc96d95b36d8b1392c6cf54c4` |
| probe01 failure stderr | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_steps/production_import_probe/helper.stderr.log` | 2321 | `a3059945de052ebf0d73de292d2934121b0b7b2ab3409d42f848bcfffc1fd285` |
| probe02 wait4 | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_steps/production_import_probe02/WAIT4.json` | 1767 | `73b4c9e42e360e7d542113d315b276db29dcf3b5eb64b5a27decaab70644fe22` |
| probe02 failure stderr | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_steps/production_import_probe02/helper.stderr.log` | 1421 | `82c2ee8e85482cc44645fda901b1727a61c99f6cb19d16e763a0e4af807aff1a` |
| probe03 PASS | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/import_probe/IMPORT_CLOSURE03.json` | 10390 | `6a52850d6fb498274073630c74d3b18f33b0fd9fd285b8776054c017fc977c2c` |
| probe03 wait4 | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_steps/production_import_probe03/WAIT4.json` | 1774 | `67b95a752eecca2506e49e34fa360980e6dc60aadfbbee5dbef03b13f1450986` |
| independent03 | `/workspace/scratch/178ced6a501f/executor_recovery_20261030T1152/INDEPENDENT_ACTUAL_ADMISSION_03.json` | 11786 | `52061da9c19401c8c9e192390531d0bf84372150080857907d5c3b49190df7de` |
| launcher prepare wait4 | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_steps/launcher_prepare/WAIT4.json` | 1726 | `2ed3e58b3cb06d5aa961ec3d99204d035ccaae3f1fae8ccf2cd5727e95fd5a39` |
| actual supervisor START | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/wait4_launcher/START.json` | 1019 | `3380fb5e437c8d1e3e6a8bbe074b5f47ca4c07ffd7e57f5c1e169dd220d88538` |
| supervisor START_POLICY | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/supervisor_run/START_POLICY.json` | 873 | `17367dc4db5220d05ceefaf7910e4b6a7725933190b979a06977f38573512d91` |
| actual controller START | `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/supervisor_run/children/controller.START.json` | 1431 | `84b3d0bf9fae76f3ad31091f0eb75e2245c0699662d0f01d471608257b790ae5` |

本报告依据原始凭据记录实际预启动和初始准入；研究完成及参数场/Hepta收益须由后续完整封存结果另行判断。
