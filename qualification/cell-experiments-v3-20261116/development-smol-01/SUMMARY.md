# Smol 开发探针原始证据归档

父模型与 trajectory 模型在同一组 9 个已暴露开发任务上均为 **NOT_READY**。两个实验臂共记录 36 次生成，全部被 `invalid_test_patch` 拒绝；没有学生补丁进入业务执行，也没有成功任务。

| 原始记录指标 | Parent | Trajectory |
| --- | ---: | ---: |
| 开发任务数 | 9 | 9 |
| 模型调用数 | 18 | 18 |
| 格式准入次数 | 0 | 0 |
| 实际执行次数 | 0 | 0 |
| 成功任务数 | 0 | 0 |
| 恢复成功 / 机会 | 0 / 9 | 0 / 9 |
| 输入 token | 9,035 | 8,772 |
| 输出 token | 4,608 | 3,770 |
| 输出上限命中次数 | 18 | 11 |
| 报告墙钟秒数 | 174.413477 | 149.342817 |
| 报告父进程 CPU 秒数 | 334.508266 | 286.469362 |

计数和 token 已从原始 step、request、output、RESULT 重新汇总。墙钟、CPU 和 RSS 保留原始测量值；计时范围排除模型加载和 reference rebinding。GPU 秒和能耗未记录，原报告的 `cost.complete=false`。

## 文件与完整性

- `SMOL_PROBE_EVIDENCE_01.zip`：154 个原始文件，未压缩共 712,255 字节，ZIP 为 211,433 字节。
- `SMOL_PROBE_MEMBERS_01.json`：原始成员路径、大小和逐成员 SHA256，保留远程导出清单原字节。
- `TRANSFER_RECEIPT_01.json`：远程固定操作 key、任务 ID、成功状态，以及 64 KiB 分块的版本与 SHA256。
- `RESULT_SUMMARY_01.json`：重算指标、摘要链核验结果和解释范围。
- 两个 `probe-smol-*-01/` 目录分别解出了原字节的 `READINESS.json` 和 `FREEZE.json`。其余原始文件完整保留在 ZIP 中。

ZIP SHA256：

`7317355beb06eefb315e68249bf062981752536bbade008d7485240be1101066`

清单 SHA256：

`516ac32fed57049a87f7025c97453a87d8ef2e0c7030c9a87625f68e4c0504e6`

源码快照位于 `../operations/smol-probe-source-01.zip`，SHA256 为：

`7d822083fd95b790a3d39196fe960f7e2848b9b971b2463622703d4ec316a95f`

已核对全部 ZIP 成员的 SHA256、CRC、文件数和大小；每个实验臂 FREEZE 中的 47 个源码文件与指定源码快照完全一致。READINESS、FREEZE、RECORDS、RESULT、step、request、output 和日志之间的摘要与内容关系已复核。语义 receipt 按冻结源码的算法核验：其顶层派生字段 `success` 在计算 receipt 摘要之后添加，核验时将其排除，同时单独确认它等于 `result.success`。没有以当前源码替代原始快照。

实际生产日志名为 `parent-probe.log`、`trajectory-probe.log`；`*-probe-command.log` 不存在。ZIP 同时保留两个 `*-probe-command.json`。

## 解释范围

同一任务的两个尝试和两个实验臂不增加独立样本数；原始报告的 `independent_sample_increment=0`、`external_teacher_count_added=0`、`scientific_confirmation_qualified=false`、`native_cell_adoption=false` 均保留。任务来源字段不能转换为真实用户或组织数量。这批结果定位到动作格式准入失败，不能证明未见任务上的轨迹训练收益。

远程导出使用新建 exclusive 目录，前后复核原始文件元数据、内容 SHA256 和文件集合；它仍不是文件系统级原子快照。归档不包含权重、候选源码树或外部依赖环境，内容自洽不等于独立认证模型权重。本次归档没有运行模型、训练或业务任务，没有修改原始文件。
