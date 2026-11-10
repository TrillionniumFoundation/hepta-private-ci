# Localization v2 实际接口执行与证据审计

**本轮完成了六个真实模型接口 × 三个独立初始化，共 18 次受限接口训练、72 次优化更新。正式效果实验为 0。** 原生执行退出码为 0；只读张量审计的 528 项检查全部通过；18 份保存 logits 的指标计算也通过。这里没有可用于模型排名、识别性能或泛化收益的结果。

## 任务片段的实际限制

| 固定片段 | 事件数 | 实际类别数 | 标签分布 |
|---|---:|---:|---|
| A01 前 128 个事件 | 128 | 2 | walking 122；sitting down 6 |
| D01 前 64 个事件 | 64 | 1 | walking 64 |

这些是原先锁定的窗口，未因标签、间隔或结果而替换。D01 片段中，常量输出 walking 就能得到 100% ACC。该片段的 ACC、NLL、Brier 与 ECE 只能检查读数和计算流程；三个训练种子不能补偿单类开发集、四步优化或容量不等的限制。[逐序列与窗口原件](abc-gap-audit.json)

E 的全部原始行此前已被读取，用于完整性、schema、时钟和全局 gap 审计；E 未进入模型训练、调参或计分。因此不能将 E 描述为“从未读取”。d=.2 的实际选择发生在包含 E 的全局元数据审计之后。本轮补充的只读 ABC 核查发现：ABC 自身最大 gap 也为 **0.162175 秒**，位于 C02、原始行 69343–69344，独立足以满足 `.2` 秒的时长域覆盖；这不会把既有选择历史追认为 ABC-only，也不会把时长覆盖变成完整数值或泛化资格。

## 真实模型与容量

| 接口 | 可训练参数数 | 实现与时间语义 |
|---|---:|---|
| GRU | 427 | Torch GRU；共同 dt 特征 |
| CfC | 807 | 官方 ncps 1.0.1；传入实际 timespans |
| recurrent PLIF | 176 | 官方 SpikingJelly 0.0.0.0.14；event-indexed 神经元与共同 dt 特征 |
| S4D-Lin | 335 | 官方固定提交；event-indexed SSM，与 Mamba 分开命名 |
| causal Transformer | 1,179 | Torch 因果 attention；共同 dt 特征 |
| HCSN | 9,804 | 已通过新 `.2` 数值 profile 的修复源码；物理冻结 |

PLIF 的 12 个训练窗口中，8 个窗口脉冲率为 0；其他 4 个窗口脉冲率介于 0.0078125 与 0.046875。所有记录的 tau 有限，surrogate 梯度和参数更新确实发生；四步训练与这些稀疏放电记录不能支持“现代 SNN 已充分训练”的说法。tau 是对应前向的更新前诊断，不能误称为第四次优化后的最终值。

## 已核实的执行事实

- 六个臂的三个种子均为 20261108、20261109、20261110；每臂实际初始张量和最终张量的规范哈希各有三个不同值，独立单位是重新初始化并训练的模型。
- 已读取全部 90 份 checkpoint：18 个初态与 72 个更新。每个更新的实际模型张量改变，Adam step 为 1–4，原始数据行号匹配锁定窗口，最终 checkpoint 文件哈希匹配执行记录。
- 18 份逐臂结果与 suite 一致；持久事件日志记录每次 optimizer step 的开始与完成；原始 185 份运行产物前后未变。
- 共同 frontend SHA256 为 `11bd263a2ae3515347b3ab4e3228c83c66cc3e9296f36c9943efb4fc3a794c55`；共同 features SHA256 为 `f53de6fcb1d7b497126ed002bc69b310b6ae287550e0a204a6184d4a8a2a296e`。
- HCSN 的 discount、raw drift、raw diffusion、raw boundary 和 raw reset 在四次更新中逐张量保持不变。每个 32-event 窗口重置状态，但保留原第一 gap；优化没有插入保留的同一 episode 内。
- 各模型实际加载的 Python 依赖源码哈希在审计时匹配。源包 36 个成员逐项匹配 source-manifest；原生执行记录 `source_unchanged=true`。HCSN 还核对了新数学回执的源码、物理 FP64 hex、原始行号与 tick 差。

原始证据：[suite.json](evidence/interface-001/suite.json)、[张量审计](evidence/interface-001-audit/native-audit.json)、[36 文件源包校验](source-archive-verification.json)。额外对当前 live 36 文件的读取请求曾在 MCP 层超时；沿同一 idempotency key 对账也超时。随后直接只读取得的[原生产物](all-source-audit.json)已完成对账：36/36 当前文件逐项匹配，`unchanged=true`、`training_or_model_forwards=0`，SHA256 为 `5e65cebae09cf6eaa2d863ff9d67b84d624b955e1e7f40267fec1adb133ba98b`。两份超时回执仍保留；没有为解决工具响应问题重跑训练。较早的源包校验 sidecar 记录的是取得该产物前的对账状态。

## 指标计算管线

[metrics-pipeline.json](metrics-pipeline.json) 保留了 18 份未排序、未汇总成质量排名的逐模型/种子读数。仅从已保存的 64×11 logits 计算，未运行模型、拟合温度或进行任何新训练。

- ACC 使用 argmax，平局选择最小类别下标。
- NLL 使用自然对数 log-sum-exp；与原生 FP64 cross-entropy 最大绝对差为 **2.6645352591003757e-15**，低于预声明的 `1e-12` 核对界限。
- 多类 Brier 为事件平均的类别平方误差之和，范围 `[0,2]`；另报除以 2 的 `[0,1]` 版本。这里没有用类别数 11 作归一化。
- ECE 使用 top-label confidence、15 个等宽区间，最后一格含 1，并保留每格 count、correct 和 confidence sum。

重算命令：`python metrics.py --evidence evidence --output NEW-metrics.json`。输出路径必须是新文件。

## 成本与缺失测量

原生外层接口执行墙钟为 **175.057531 秒**；suite 墙钟为 170.040363 秒；18 个 worker 内墙钟之和为 151.108464 秒。worker peak RAM 范围为 **625,102,848–782,454,784 字节**。这些时间包含导入、构表、优化和 checkpoint I/O，不是稳定推理吞吐或 p99。它们也不包含全部依赖准备、数学资格、失败准备和证据回收成本。

持续状态字节、p99、稳定推理吞吐、峰值 VRAM 和完整系统能耗均显式为 `null`，附有各自未测量原因。禁止 GPU 且参数位于 CPU，不等于采集了 VRAM 峰值计数器。未计量能耗没有填 0。

## 归档身份与范围

[完整接口归档](interface-001-evidence.zip)：4,103,593 字节，SHA256 `f32b15255a0a5cfa083d2db3b020b60d3945aeed3ca851da6f4fe8c0b4077fd0`。包含 210 份原始/审计文件及归档 manifest；63 个固定版本分块的 SHA、完整 ZIP SHA、全部成员 SHA 和 ZIP CRC 均通过。[传输验证](transfer-verification.json)

原始 suite SHA256：`2925658aa11c071bdcd0fef33f274c8735f9751ebb0585e7f3d7e3c2b0d7ff54`。源包 SHA256：`d5d745c839204512ca53d617a7d2dbb84dad94e0de13d382174f67bbd8e59c82`。新数学回执 SHA256：`1c31a015de53ad720bfa7ac3e952fdbe494a8251161f5741c49239b247a53ddc`，随源包保留。

归档包含全部选定数据、frontend、features、90 checkpoint、18 logits、执行日志和初次依赖准备失败回执。原官方 6,290,730 字节 ZIP 仍由既有数据取得记录及其原生保留路径关联，SHA256 为 `6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da`；没有在本包再次复制。初次 SpikingJelly Git fetch 的 180 秒超时保留为失败，未伪装为成功 wheel 安装记录。

成功依赖准备回执作为[独立不可变补充](dependency-recovery-002.json)保留，SHA256 为 `eea34fcfa4629d9f3db063ac21f00944604e1c4c0fbbdbe94772fc66187bdc1f`，未改动原 4MB 归档。其 status 为 `prepared`，所有命令退出 0，`training_started=false`，原环境关键模块哈希不变。官方 PyPI 的 `spikingjelly-0.0.0.0.14-py3-none-any.whl` 为 437,590 字节、SHA256 `9f43c8f3164909e8503d6b5488a16c07b4e5338c6a70529fca408593c4baf151`；没有宣称该 wheel 等同于参考 Git commit。官方 S4 checkout 提交为 `e757cef57d89e448c413de7325ed5601aceaac13`。该回执的 predecessor SHA 还与归档保留的初次失败回执衔接。

## 真实剩余阻点

已观察到的接口和计量检查没有未解决失败。正式效果对照仍缺少完整/充分的多类训练与开发片段、容量匹配、合理调参和收敛证据、足够训练的 SNN、完整上下文与观察条件化动力学的数值资格、可训练物理参数域资格、真实物理旁路删减与普通双门控等消融，以及完整资源计量。当前固定物理资格不能替这些项目背书。用户授权已经具备；这些是科学与实现准入条件。
