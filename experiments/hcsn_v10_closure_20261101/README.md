# HCSN V10：执行、持续核心、历史 AV 与成本核验

本目录承接两条明确区分的 v9 来源，只追加 v10 实现及证据，不把两条历史结果合并成共同通过结论。本文是入口与严格范围说明；最终科学和 CI 状态由本目录最终报告及验收记录决定。

| 来源 | 固定身份 | 本轮用途 |
| --- | --- | --- |
| 主要代码基线，PR #4579，`research/hcsn-v9-mechanism-economics-20261101` | commit `8cc469fcb0e6527fac56e26b65baa3ae1c09c86b`，root tree `15ef79d5f0382ce7ee131ef2059b25da3ba7567a` | 当前 v10 继承基线 |
| 新恢复 Library v9，`research/hcsn-v9-followup-20261101` | remote commit `03f338eb44bf585bfe9d4f87e4f5ef7af98884ad`，v9 directory tree `dcfc600b44c6dfa2698969558a56b9df6dc753f3` | 核对 250 个文件，恢复所需历史 AV 接口、特征与权重身份 |

额外 v9 包的本地增量 bundle HEAD 是 `ad2a79d0699979108543d3052b76942b14e0e8a6`，与其远端提交不同。两者的 v9 目录字节已逐项核对；提交身份不能互换。来源与树对象说明见 [SOURCE_CONVERGENCE.json](SOURCE_CONVERGENCE.json)，包核验见 [frontend/RECOVERED_PACKAGE.json](frontend/RECOVERED_PACKAGE.json)。

| 入口 | 范围与记录 |
| --- | --- |
| `frontend/` | 原 v3 历史资产恢复、部分录制排除、普通音频候选实际拟合/重放和独立输出核验；[报告](frontend/REPORT_ZH.md)、[复现](frontend/REPRODUCE.md) |
| `risk/` | READ 服务风险、截止时间与实际执行合同；结果以各冻结计划和最终审核为准 |
| `persistent_renewal/` | 不规则时间的持续普通/解析候选、共同控制及普通、历史无核心候选参照；保留开发、扩展与独立确认的角色差别 |
| `joint_retrain/` | 机制干预及重新训练；结论必须限于实际被训练和执行的参数、任务与数据 |
| `av_analytic/` | 历史 AV 上的解析 latent 候选与共同内容/价值接口；不得将模型假设写成真实 AV 物理律资格 |
| `economics/` | 各阶段独立外层 CPU、失败运行、内存能力和生命周期缺项；[计量范围](economics/LIFECYCLE_SCOPE.json) |
| `review/` | 独立原始记录、统计、合同与范围审核 |
| `publication/` | 交付身份、打包和远端核验材料；发布完成不等于科学或生产准入 |

实际 `train`、`execute`、`audit` 等阶段应通过 [economics/stage_meter.py](economics/stage_meter.py) 的当前接口包裹。外层 CPU 已包含内部训练、子孙与监控开销，内部诊断计时不可再次相加。成功退出说明阶段执行完成，不能替代内容质量、核心增益或完整经济性验收。

固定 384-world confirmation 已全部完成并独立重构：两项 matched primary 的 97.5% 区间均跨零，解析核心独立净增益仍未建立。计划、源码快照、原始运行和成本凭证共同确定其适用范围。旧 test、重复前缀、重复模型种子和新模拟世界分别保留原身份，不改称新独立真实录制。

稳定完成条件见 [EXTERNAL_BLOCKERS.json](EXTERNAL_BLOCKERS.json)。原 v6/强头、完整历史排除和新独立录制仍须对应真实资产。当前容器私有 cgroup 创建失败；两次 GitHub CI 私有 cgroup 实测与独立重构已成功，严格版冻结 joint 评价的 kernel charge 峰值为 51,703,808 字节；这不等于冷缓存、AV全生命周期或RSS/PSS的完整测量。可归因设备能量仍未知。此前集成检索未建立可归因能量测量 runner，并不排除其他服务或用户自有机器。

软件修复、更多运行和通过行为检查可以增加可信证据，不能保证科学净优势。负或不确定的 D−B、缺失的质量/成本条件须继续保留；本目录不承诺以修改门槛或重命名证据强行关闭这些项。
