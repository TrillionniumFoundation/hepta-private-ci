# V13 执行经济性：真实非重叠 CPU 范围

本账按回执的命令、监督哈希和进程包络重算，不以目录名或时间包含代替父子关系。它是已计量工作下界，不是完整项目或部署经济性。

| 本地完整 waited-worker 范围 | CPU 秒 |
| --- | ---: |
| control | 263.359724 |
| emotion_encoder | 52.116700 |
| frontend | 11.846144 |
| joint_core | 200.268452 |
| review | 47.904648 |
| 不重复合计 | **575.495668** |

本次快照有 115 份完整回执，移除 72 个已含子 fit，保留 43 个顶层包络。失败 5 轮的 13.204501 CPU 秒已经计入，不再次追加。

| 已含嵌套范围 | 子 fit 数 | 子 CPU（不加） | 父 CPU（已加） |
| --- | ---: | ---: | ---: |
| experiments/hcsn_v13_followup_20261102/control/orchestration/fit_batch.py | 36 | 185.700554 | 188.711332 |
| experiments.hcsn_v13_followup_20261102.joint_core.operations.run_roster | 36 | 180.414056 | 186.807716 |

独立审阅／前端 worker 即使落在训练 batch 时间内部，也不是其已等待子进程，仍须计入。并发 worker 的 wall 秒不相加冒称等待时间。

| 远端独立主机的完整 worker 范围 | CPU 秒 |
| --- | ---: |
| experiments.hcsn_v13_followup_20261102.emotion_encoder.acquire | 1.696364 |
| experiments.hcsn_v13_followup_20261102.emotion_encoder.campaign | 78.479032 |
| 远端已记录完整包络小计 | **80.175396** |
| 本地＋远端已记录完整包络下界 | **655.671064** |

远端 acquisition／model worker 各自只计一次，内部 process-body、逐前缀与 OOF 计时已包含，不再相加。远端 monotonic 与本地属于不同主机，不用于互相判断包含或重叠。

既有相邻 ASR 缓存准备的 107.396369 CPU 秒另列，不能当作本轮新执行，也不能把共享准备成本填零。未完整包络的早期数学探针另有 0.379491 self CPU 秒下界。

情绪 CI 状态：`success`。未物化回执时 CPU 为 null；已获得 acquisition/model worker 回执后，依赖安装、source identity 和传输重组等 workflow 外部阶段仍须单列未知，不可声称整轮完整 CPU。

V13 的完整项目 CPU、历史准备、进程族 RSS、可归因设备焦耳和 H=20／10,000 完整摊销继续为 null。V12 的 70–74 MiB 只属于旧 16 个 NumPy 模型的可信单任务 profile，不能借给新 Torch/HX 模型或 377／661 MB 预训练编码器。

可用 `python -m experiments.hcsn_v13_followup_20261102.economics.aggregate_costs` 重算；未来新增 TEST／独审回执会自动纳入，CI 原包物化后显式传 `--ci-artifact`。完整明细、sha 与包络边界见 `COST_SCOPE.json`。
