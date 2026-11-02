# Hosted cgroup 路径静态审阅

本记录是源码与 workflow 的只读审阅，不是在当前机器上执行 privileged run 的结果。审阅对象为 `economics/ci_cgroup.py`、`economics/ci_joint_replay.py` 和 `.github/workflows/hcsn-v10-memory-qualification.yml`；首个提交身份由根负责人报告为 `4ccada8d893a5471a39fec998fb3d14fc9728116`。真实 runner、权限和 kernel 能力仍须由实际作业收据确认。

后续执行状态：首版 run `41371500148` 与增强版 run `41372584433` 已实际成功并下载。两个 `CI_RECONSTRUCTION_<run>.json` 已分别独立核对 kernel 收据、全部 30,720 条预测和冻结摘要的 142 项数值，详情见 `INDEPENDENT_REVIEW.md` 的 hosted kernel 段。本静态审阅的原条件判断作为开发时记录保留，不再表示当前仍无实际 CI 证据。

## 执行与清理边界

默认 probe 不创建或修改 cgroup。显式 run 要求非 root 的任务 uid，且 memory controller 已由 host 开启；代码不写 host 的 subtree_control。新 group 使用独占 UUID，限制和 kill 仅针对该 group。子进程先阻塞在 pipe，父进程写入并核验成员身份后才放行；子进程先启用 no_new_privs、丢弃附加组与 root 身份，再 exec 任务。正常路径同时要求任务成功退出和整个 group 无存活后代，不能以父进程退出代替完整进程族终止。

初审提出的两个问题已在首个提交前修正：timeout 必须为有限正数；cleanup 使用 WNOHANG 和三秒界限，避免阻塞 waitpid 绕过清理期限。源码以 group 自身的 populated 状态及 root 状态决定清理完成，并把清理失败保留为 FAIL。没有新增 privileged 本地执行。

新的 group 初始没有成员；仅创建空 group、零峰值、任务失败、OOM kill 或清理失败不能通过。控制 fixture 同时触摸 16MiB 与 32MiB 分配，用至少 48MiB 的正峰值检查计量通路。它是任务/子进程门控和真实分配的正向资格检查，不是任意工作负载资源上界。

## 计量语义

`memory.peak` 是专属 cgroup 及后代的 kernel memory charge 峰值，不是 RSS、PSS 或去重物理内存。共享页和既有 page cache 的 charge 归属不能从进程迁移推断；fork 前已分配的 wrapper 页也不能自动视为新 group 的完整费用。记录的恰当范围是门控 exec 后该冻结任务在新 group 中产生并保有的 charge，含归属该 group 的 kernel/cache 费用。

该语义来自 [Linux cgroup v2 官方文档](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) 的 memory.peak 和 Memory Ownership 章节。它比稀疏 RSS 样本更适合该专属任务峰值，但不能与同时物理唯一内存、设备能量或完整 AV 服务成本互换。

## 冻结输入与数值资格

workflow 使用只读 contents 权限、既有 action/dependency pins、确切 PR head SHA、稀疏 checkout，以及任务前源身份和 checkpoint/data 哈希核验。`ci_joint_replay.py` 在新输出目录重放已冻结的有限联合模型评价，不重新训练，不为 AV 前端或外部录制提供资格。

首版 wrapper 只检查 prediction_rows。已要求作者补入原冻结 SUMMARY 的质量数值比较，或由独立审核对下载的新 SUMMARY 做比较；行数一致本身不能证明新 host 的预测和指标一致。gzip 输出有时间元数据，不应把不同重放的 gzip 字节哈希相等当数值等价条件。

追加版本已经只读复查：从原冻结目录读取 SUMMARY，逐五个 fit、六臂的 NLL/accuracy/Brier 及五个 contrast 均值做 95 项有限数值、绝对误差 `1e-8` 检查，先保存 `NUMERICAL_EQUIVALENCE.json` 再按结果通过或失败。它不改训练、测试或原 SUMMARY，不复制旧 SUMMARY 到排他写出的新目录。追加版本与首版 run 应分别绑定源提交，不追溯改称首版已经执行这些检查。本地独立 checker 还将重构全部 30,720 条预测及完整 SUMMARY 的数值；准备好 checker 也不等于实际 runner 已通过。

在实际 runner 收据落盘前，静态审阅支持“计量路径可提交执行”，不支持“已得到精确任务峰值”。实际审核需绑定 commit/run/attempt、空 group 到门控 exec 的证据、完整后代清空、正 memory.peak、无 OOM、成功清理、任务输出及冻结指标等价。一次联合模型测量仍不能闭合所有研究阶段和完整 AV 部署内存，更不能填补可归因能量缺口。
