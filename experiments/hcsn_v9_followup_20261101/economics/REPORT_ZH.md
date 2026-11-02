# V9 完整进程族内存：实测仍不可用，保留反例

本阶段没有关闭完整执行经济性门。基于 v8 精确提交
`059b43a0b20ad07654880c155cc49799e0bb8858`，只新增独立目录；
没有修改 v7/v8 观察器或原证据。新源码身份见 `SOURCE_IDENTITY.json`。

`CAPABILITY.json` 是本次实际运行的内核能力检查：当前 cgroup2 挂载为
只读，统一成员路径为 `0::/`；创建新隔离组实际返回 `EROFS`（errno 30）。
共享根组的 `memory.peak` 没有用作任务数据。没有隔离计量域时，现有环境
不能提供可归因的进程族连续峰值；提高 RSS 采样频率也不能补出这一证据。
本检查只验证能力，不提供尚未成功执行过的 cgroup 工作负载计量实现。

另实际执行两组独立外层 supervisor 探针。每组都产生 root、child、
grandchild、short_leaf 四个真实进程；分别触碰 8、12、16、48 MiB 分配。
第二组 root/child 不等待后代，外层 subreaper 实际收养 child 和 grandchild，
grandchild 再正常等待短命叶子。所有 wait4 子树收集完毕且退出为零。
这属于受控可信 Linux fork/exec 夹具，不是候选模型性能或任意恶意进程覆盖。

| 实测范围 | 正常等待 | 收养后代 |
| --- | ---: | ---: |
| 外层完整 supervisor CPU（秒） | 0.371500 | 0.384137 |
| 注册子集采样 RSS 峰值（字节） | 32,489,472 | 18,886,656 |
| 短命叶子单进程 highwater 诊断（字节） | 60,424,192 | 60,424,192 |
| 叶子记录的存活时间（秒） | 0.071620 | 0.043744 |
| 外层收集的不重叠 wait4 子树根数 | 1 | 3 |
| 完整进程族连续峰值 | null | null |
| 可归因设备焦耳 | null | null |

已注册集合的采样峰值甚至小于叶子自身的 highwater。这是本环境中该指标
不足以界定完整进程族峰值的实际反例。不能将单进程 highwater、子进程
highwater 的和或已注册 RSS 集合改名为完整进程族峰值。RSS 还可能重复
计算共享页；cgroup 层次内存收费峰值本身也不同于物理唯一页或 RSS 总和。

独立标准库 `audit_records.py` 对两组原始记录的图关系、收养后父身份、
退出与 CPU 包络、null 保留及该内存反例共执行 36 项检查，36/36 通过。
另在临时副本中分别伪造完整族峰值、生成边、收养后父身份及 CPU 覆盖，
四项负对照全部拒绝；原始记录未变，结果见 `NEGATIVE_CONTROLS.json`。
外层 CPU 两组共 0.755637 秒，内层数据已包含，不再相加；这只包括夹具
及其 supervisor，不包括本阶段开发、能力探测、审核、旧模型准备或生产
部署成本。历史缺失准备成本仍然缺失。powercap/hwmon/drm 计量目录不可见，
没有把 CPU 秒换算为能量。

复现须从仓库根目录执行，每次用新输出目录，保留已有成功和失败记录：

```bash
python -m experiments.hcsn_v9_followup_20261101.economics.memory_capability --out /tmp/new-memory-capability.json
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/new-waited-meter --sample-interval 0.05 -- python -m experiments.hcsn_v9_followup_20261101.economics.short_tree_probe --out /tmp/new-waited-nodes --mode waited
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/new-adopted-meter --sample-interval 0.05 -- python -m experiments.hcsn_v9_followup_20261101.economics.short_tree_probe --out /tmp/new-adopted-nodes --mode adopted
python -m experiments.hcsn_v9_followup_20261101.economics.audit_records --directory experiments/hcsn_v9_followup_20261101/economics --out /tmp/new-cost-record-audit.json
```

最小可单独审阅阶段为能力检查（`memory_capability.py`），其次为真实分配/
收养夹具，最后为独立原始记录审核及证据。三份实现合计约 230 行，原始
JSON 与报告是独立证据阶段。总仓格式化由集成阶段在全部修改后统一执行。
