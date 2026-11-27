# 参数记忆生成可执行 Ruff 操作：冻结开发实验

## 实际结果与范围

三个预先固定的 seed 都生成了可准入的修复操作，并在同一份历史项目 fixture 上实际通过原 Ruff gate 和全部 **76 个原语义测试**。关闭 adapter 的一次共享对照、三个打乱 adapter 对照都没有产生可准入操作。来源驱动的 typed tool retrieval 控制也通过相同任务。本轮支持“参数化程序 cell 能产生真实有效动作”这一窄能力，不支持参数优于强检索、未来任务泛化、分裂收益或生产接受。

这仍是 **一个已暴露的项目任务、两个已知失败类别**。三个 seed 不是三个独立任务；新问法和 F401/E731 组合也不是新的独立根因组。prospective groups=0，future accuracy=null，八项完整研究／生产门槛不因本实验关闭。

| Arm | Seed | 两条来源操作的新问法 | 组合任务动作准入 | 原 lint gate | 原 76 个语义测试 | 项目任务成功 |
| --- | ---: | ---: | --- | --- | --- | --- |
| 参数 cell | 24041 | 2/2 | 是 | 通过 | 76/76 | 是 |
| 参数 cell | 24043 | 2/2 | 是 | 通过 | 76/76 | 是 |
| 参数 cell | 24047 | 2/2 | 是 | 通过 | 76/76 | 是 |
| 打乱 adapter | 三个 seed 分别执行 | 各 0/2 | 均否 | 均失败 | 未执行 | 均否 |
| 关闭 adapter | 24041，共享一次 | 0/2 | 否 | 失败 | 未执行 | 否 |
| Typed tool retrieval | 无参数训练 | 不作参数记忆评分 | 是 | 通过 | 76/76 | 是 |

三个正常 adapter 的原始输出完全一致：F401 为 `ruff check --fix`；E731 和组合诊断为 `ruff check --fix --unsafe-fixes`。raw text、token IDs、进程退出码与 gate 结果都在 [summary.json](summary.json) 中逐项列示。所有成功动作只改变固定目标文件，原测试和其他 16 份 fixture 文件不变。

## 这次针对的具体问题

[先前预算实验](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bfe77f5cdd04935d8bbfba9199a725ffc48b69e7/qa/memory-budget-20261024/README.md)训练的是 workflow 文件名／行号到短命令的记忆，却在最终要求错误到修复动作的映射。128 条来源中，每个主要 arm 的新增 96 步只实际访问部分事实；其训练目标没有覆盖最终 Ruff 动作契约。因此，旧的零动作不能单独归因于容量、路由或分裂不足。

本轮先验证能够执行的程序记忆。两个教学程序分别真实触发 F401、E731；每个程序都执行预先允许的 safe-fix、unsafe-fix 两个候选，并检查后续 lint 与四个输入上的 identity 行为。训练标签从实际成功操作中，按冻结的最低权限顺序选择。训练事实的 source digest 绑定完整工具观察；这些是本机受控来源，不是外部来源授权资格。

每个模型只学习两条诊断到操作的映射。任务路径由共同执行器从固定来源绑定，模型不生成任意 shell，也不负责记忆精确代码版本和文件路径。执行器只接受冻结的两个完整操作，以直接 argv 执行同一个固定 Ruff 二进制；unsafe-fix 从注册时即明确允许，并受原语义测试约束。

与旧实验相比，语料大小、训练目标、模板、学习率和曝光次数都改变了。本轮是可执行能力的开发验证，不是将全部增益因果归于“动作对齐”的单因素 A/B 实验。

## 冻结与执行

[protocol.json](protocol.json) 在首次模型训练前写入，SHA-256 为 `2e565543b49abc8b17202d1daee1b9e215e86129e5b2411ed7ef7f41153c829e`。它记录全部来源、动作集合、seed、训练预算、问题、测试条件与实现 SHA。三个实验源码及协议在执行前后保持相同字节。

- 固定 SmolLM2 base 六文件；rank 8；seed 24041、24043、24047；每个 seed 96 步、learning rate 0.003、原 `completion_ce`。
- 每条事实实际访问 48 次，四种训练模板各访问 12 次。最终问法未放入训练 spec；第三个问题组合两个已知诊断。
- 训练 worker 仅接收独立 training spec；fresh-process reader 不接收事实文本、检索结果或答案词表。正常、关闭和打乱参数使用既有严格 reader。
- 来源控制通过诊断 code 检索已成功的候选操作，对所有当前诊断求交集，再按最低权限顺序选择；它执行完整任务 gate，但仍不是带通用 reasoner 的强 RAG agent。
- 原项目 fixture 的 17 个文件和 Ruff 0.15.13 二进制逐字节匹配旧冻结清单；新隔离副本用于每个 arm。初始 gate 都实际重现 F401/E731。

## 成本与未测量项

| 项目 | 本次实际值 |
| --- | ---: |
| 新 optimizer updates／训练 forward | 288／288 |
| 训练 input／supervised tokens | 24,120／2,304 |
| Fresh decoder queries | 21 |
| Decoder input／generated tokens | 1,694／273 |
| 模型子进程 | 10：3 次训练、7 次读取，全部 exit 0 |
| 三次训练 child CPU／wall | 364.263692／196.432832 秒 |
| 七次读取 child CPU／wall | 111.354775／84.355763 秒 |
| 完整 run driver CPU／wall | 489.064472／294.263152 秒 |
| 一份 adapter | 460,800 参数；1,843,200 B tensor payload |
| 三份 safetensors 文件合计 | 5,576,328 B |
| 共享 base 六文件 | 271,170,520 B，复用现有固定文件 |
| 原始 run 截止清单 | 354 文件、6,852,834 B，包含后续 runtime metadata 检查记录 |

训练 CPU 低于预先分配的 600 秒，新文件低于 1 GiB。driver 与 child 时间有包含关系，不能相加。51 份工具／模型命令逐条保留 wall／CPU 回执；准备阶段文件读写与 Python 启动、全运行时／OS／网络／历史下载、RSS 和持续存储仍未完整测量。两条操作的参数存储也不构成净压缩；检索控制达到相同任务成功。

运行时记录限定于这次执行：Python 3.12.14、torch 2.5.1+cpu、transformers 4.57.1、peft 0.17.1、safetensors 0.6.2、numpy 1.26.4。最后一份模型读取回执在 2026-10-25 10:29:18.943670 UTC 写入，完整 driver 回执在 10:29:22.155085 UTC 写入；这些 UTC 来自事后读取的文件 mtime，子进程实际时长来自运行时单调计时。主 driver 开始时间加 wall 时长给出的结束估计为 10:29:22.154867 UTC。另一个 relay 任务随后向共享环境新增 cryptography 50.0.2、cffi 2.1.1、pycparser 3.12，其 dist-info mtime／ctime 在 10:33:34.913586–10:33:34.915606 UTC；这是运行后的环境变更，不是本实验的模型依赖或额外训练。没有因此重跑实验，也不声称整个共享 venv 永久不变。逐子进程回执时间和后续包元数据观察见 summary 的 `post_run_environment_observation`；mtime 是本地文件证据，不是独立时间见证。relay 安装回执的 SHA-256 为 `25fceb74bff3af6de13dd70863684f5b18781ef220418a059ba13ea08670bab7`，完整回执嵌入同一字段的 `relay_installation_receipt`，包含先前 pip 不可用的失败和后续 uv 成功安装记录。

## 复现、发布与后续边界

实现位于 [procedural_trial.py](../../scripts/memory_cell_development/procedural_trial.py)、[procedural_support.py](../../scripts/memory_cell_development/procedural_support.py)、[procedural_worker.py](../../scripts/memory_cell_development/procedural_worker.py)。在 Linux 上用 `prepare` 创建全新的 output，传入固定 repo、base、Python 与 Ruff 路径；取得生成的 protocol SHA 后，再用 `run --protocol-sha256` 执行。既有 output 不会被覆盖。

本次仅发布详细报告、紧凑 metrics、冻结协议和可复现源码；大原始运行目录与 checkpoint 不重复归档。summary 中保留主要产物摘要、精确 runtime 版本和每条命令回执。发布副本随后单独运行 `just fmt`；[publication-format.json](publication-format.json) 内嵌三份实际执行 Python 的完整 UTF-8 源码、原执行 SHA、格式化后 SHA 和包含原始 docstring 值的精确 AST 等价记录，可以逐字节重建执行版本。冻结 protocol 的 `2e565543b49abc8b17202d1daee1b9e215e86129e5b2411ed7ef7f41153c829e` 不变，其 implementation SHA 继续指向原执行源码；summary 和 future-candidate-update 的字节也未改。格式化后未运行模型或测试。

下一步的实验前提是扩大真实可执行任务和完整强检索控制，再冻结独立任务组及共同预算；当前只有两类诊断，尚不足以构造有意义的容量干扰或分裂压力。旧长期质量失败、future 空集、分裂负结果和生产接线缺口保持原状态。
