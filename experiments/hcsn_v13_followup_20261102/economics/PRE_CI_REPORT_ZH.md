# V13 执行经济性：真实非重叠 CPU 范围

本账按回执的命令、监督哈希和进程包络重算，不以目录名或时间包含代替父子关系。它是已计量工作下界，不是完整项目或部署经济性。

| 本地完整 waited-worker 范围 | CPU 秒 |
| --- | ---: |
| control | 263.359724 |
| emotion_encoder | 51.900107 |
| frontend | 11.846144 |
| joint_core | 200.268452 |
| review | 46.421809 |
| 不重复合计 | **573.796236** |

本次快照有 111 份完整回执，移除 72 个已含子 fit，保留 39 个顶层包络。失败 4 轮的 12.906008 CPU 秒已经计入，不再次追加。

| 已含嵌套范围 | 子 fit 数 | 子 CPU（不加） | 父 CPU（已加） |
| --- | ---: | ---: | ---: |
| experiments/hcsn_v13_followup_20261102/control/orchestration/fit_batch.py | 36 | 185.700554 | 188.711332 |
| experiments.hcsn_v13_followup_20261102.joint_core.operations.run_roster | 36 | 180.414056 | 186.807716 |

独立审阅／前端 worker 即使落在训练 batch 时间内部，也不是其已等待子进程，仍须计入。并发 worker 的 wall 秒不相加冒称等待时间。

既有相邻 ASR 缓存准备的 107.396369 CPU 秒另列，不能当作本轮新执行，也不能把共享准备成本填零。未完整包络的早期数学探针另有 0.379491 self CPU 秒下界。

情绪 CI 状态：`queued`；未物化回执时 CPU 为 null。即使获得 acquisition/model worker 回执，依赖安装等 workflow 外部阶段仍须单列未知，不可声称整轮完整 CPU。

V13 的完整项目 CPU、历史准备、进程族 RSS、可归因设备焦耳和 H=20／10,000 完整摊销继续为 null。V12 的 70–74 MiB 只属于旧 16 个 NumPy 模型的可信单任务 profile，不能借给新 Torch/HX 模型或 377／661 MB 预训练编码器。

可用 `python -m experiments.hcsn_v13_followup_20261102.economics.aggregate_costs` 重算；未来新增 TEST／独审回执会自动纳入，CI 原包物化后显式传 `--ci-artifact`。完整明细、sha 与包络边界见 `COST_SCOPE.json`。
