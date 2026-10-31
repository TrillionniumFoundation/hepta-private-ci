# V12 四类型真实文档任务实验

## 结论

这组固定类型实验没有证明把读取能力拆成 event、semantic、procedure、meta 四个 cell 会提高能力。移除 event、semantic 或 procedure 后，通用实现实际重放事件、解析声明或解析并执行同一程序；未来阶段的 **618 次评估输出均与完整类型系统完全一致**。这三个消融没有准确率损失，原因不是省略了任务，而是强通用替代确实完成了同样的工作。

学习寻址加类型读取的完整系统，在未来阶段为 **582/618，94.1748%**；同模块注册表、最多两次证据读取的 BM25 加通用读取也为 **582/618，94.1748%**。逐题配对中双方各自独占正确 18 次，净差为零。相对历史问题 nearest 或单个全来源分类器的改善属于寻址改善，不能归因于三种内容读取类型。[完整配对结果](evidence/typed/ANALYSIS.json)

三种 seed 反复评估的是相同的 **206 个未来任务**，不是 618 个独立任务。没有据此给出独立样本显著性或总体泛化保证。这是同一仓库内的方法开发实验，不是独立确认。

## 来源、任务和真实执行边界

输入来自固定 Git 源 `527218f9b823540830907f861a309310b71d38c9` 的 40 份 `TECHNICAL.md`。在原来 600 个来源段落之外，本 profile 补充了被寻址语料明确排除的 40 个真实文档前言与 identity 段，合计 **640 个来源记录**。每条记录保留原文、文档路径、来源摘要和可定位的原文范围。这个 640 来源 profile 与其他 600 来源实验独立报告。[语料](evidence/typed/CORPUS.json) · [原始来源副本](evidence/typed/sources/docs/modules)

任务一共 604 条：151 条 train、151 条 calibration、302 条 test。阶段 0 的 96 条测试是初始化诊断；阶段 1、2 的 102、104 条测试组成未来阶段分析。任务是人工模板请求，不是线上问题日志。

| 类型 | 本次真实执行的能力 | 移除后的通用替代 |
|---|---|---|
| Event | 按请求 cut 读取版本投影，应用更正与撤销 | 从同一受控 journal 重放得到当前版本 |
| Semantic | 从真实来源缓存 owner/deputy 声明，并返回来源与版本 | 对实际选中的同一证据即时解析声明 |
| Procedure | 从真实编号步骤编译有序 checklist，推进 cursor，输出实际 actions、下一项和剩余项 | 即时解析同一编号块，并调用相同有界执行器 |
| Meta | 共享 literal module 注册表加学习型 heading 寻址 | 相同注册表下的 full-text BM25 |

semantic、procedure、event 在这个实验中是确定性读取和状态机制。它们不是三个训练过的生成模型；训练发生在寻址层。Procedure 执行的是有界 checklist 模拟：它实际推进执行位置和返回的动作序列，但不会向 GitHub、进程、网络或真实系统发出步骤中描述的外部效果。

真实文档中被本次任务采用的编号块只有五个。没有把普通段落改写成更多程序；若一个来源段含多块，本实验只使用第一块。

| 文档模块 | 来源段 | 采用的原始步骤数 |
|---|---|---:|
| automation.taskflow | Implementation sequence and work packages | 13 |
| browser.servo | Runtime, concurrency and transaction model | 6 |
| cognitive.read | Observability and operations | 7 |
| context.compiler | Internal architecture and component decomposition | 7 |
| memory.federation | Runtime, concurrency and transaction model | 6 |

`TASKS.json.procedure_source_spans` 保留完整原始编号块、逐步原文、路径、heading、文档摘要，以及在来源记录中的 start/end。组合任务必须在两次证据预算内取得声明与程序两个来源，并输出正确声明、版本及执行后的状态。[任务与原文步骤](evidence/typed/TASKS.json)

事件轨迹明确是构造的摄取场景：revision 1 只摄取原程序的前三个真实步骤；revision 2 更正为完整原文；revision 3 撤销。它不是文档历史版本，也不是生产事件历史。相同请求在不同 cut 会得到不同版本与程序执行结果；撤销后不能返回该来源。任务输出带 source ID 和 revision，因此碰巧相同的 owner 字符串不能掩盖错误来源。

## 固定训练、读取和时间协议

完整系统及前三种内容消融复用完全相同的寻址权重和分数。移除 meta 使用 BM25。另设 BM25、历史问题 nearest 和单来源分类器三种控制，内容侧都使用能完成全部操作的通用 reader。没有 `if ablate: fail` 路径。

所有策略得到相同的当前来源、允许使用的历史标签、literal module 注册表，以及 **每个请求最多两次证据读取**。这是相同的上限；实际读取数可以因拒答、撤销或来源分数为零而减少，并分别计量。不存在用第三次隐藏读取补全组合答案。

学习 heading 分类器与单来源分类器均使用 dimension 256、hidden 32、240 steps、batch 32，即每次拟合各 7,680 次样本呈现。前者输出 16 个 heading 类别，后者输出 640 个来源类别。参数量和计算量因此不同；这里不声称等 FLOPs 或等参数。检索控制不需要梯度训练，其索引构造和保留的历史标签仍计入资源。

阶段 0 使用本阶段 train 问题；后续阶段只能使用过去非 calibration 问题的来源标签和新到达的 canonical 来源。阈值只由过去 calibration 的来源覆盖/未知模块拒绝选定，阶段 0 用自己的 calibration。模型恢复自导出的真实 checkpoint 后才测试。未来测试答案和任务状态不传给寻址训练器或 scorer。[冻结协议](TYPED_PROTOCOL.json) · [执行前承诺及环境](evidence/typed/FREEZE.json)

## 未来阶段结果

结果包含 408 次可回答任务和 210 次不可回答任务。不可回答包括未知字段、撤销来源和未知模块。必须同时观察可回答成绩，避免用统一拒答取得看似很高的分数。

| 方法 | 全部任务 | 可回答任务 | 不可回答拒绝 | 相对完整系统的逐题配对 |
|---|---:|---:|---:|---|
| 完整四类型 | 582/618 = 94.1748% | 372/408 = 91.1765% | 210/210 = 100% | 基准 |
| 移除 event | 582/618 = 94.1748% | 372/408 = 91.1765% | 210/210 = 100% | 618 个输出完全相同 |
| 移除 semantic | 582/618 = 94.1748% | 372/408 = 91.1765% | 210/210 = 100% | 618 个输出完全相同 |
| 移除 procedure | 582/618 = 94.1748% | 372/408 = 91.1765% | 210/210 = 100% | 618 个输出完全相同 |
| 移除 meta，使用 BM25 | 582/618 = 94.1748% | 372/408 = 91.1765% | 210/210 = 100% | 双方各独占正确 18 次 |
| BM25 + 通用 reader | 582/618 = 94.1748% | 372/408 = 91.1765% | 210/210 = 100% | 双方各独占正确 18 次 |
| 历史问题 nearest + 通用 reader | 546/618 = 88.3495% | 336/408 = 82.3529% | 210/210 = 100% | 完整系统独占 40 次，控制独占 4 次 |
| 单来源分类器 + 通用 reader | 347/618 = 56.1489% | 137/408 = 33.5784% | 210/210 = 100% | 完整系统独占 235 次，控制独占 0 次 |

在地址正确的子集内，各方法的 reader 输出都正确。这将当前误差定位到地址选择，不能证明类型 reader 获得了更强的自然语言理解。原始逐题记录保存实际 output、操作路径、地址、材料化证据和资源计数；不仅保存汇总正确率。[汇总](evidence/typed/SUMMARY.json) · [逐题示例：seed 31031，phase 2](evidence/typed/seed-31031/phase-2/test-full_typed.json)

| Seed | 完整系统未来任务 | BM25 + 通用 reader |
|---:|---:|---:|
| 31031 | 194/206 = 94.1748% | 194/206 = 94.1748% |
| 41033 | 192/206 = 93.2039% | 194/206 = 94.1748% |
| 51047 | 196/206 = 95.1456% | 194/206 = 94.1748% |

完整系统的 seed 间样本标准差约 0.9709 个百分点。它不是任务总体的置信区间。三个 seed 的共同语料、模板、模块与步骤高度相关。

## 资源：读取、解析、训练、缓存与共享运行时

下面的运行计数汇总未来阶段的 618 次评估。原始来源一直保留，读取上限相同不等于实际读取数相同。

| 方法 | 实际证据读取 | 材料化证据 bytes | 即时 parse calls | 即时 parse bytes | 扫描 event rows |
|---|---:|---:|---:|---:|---:|
| 完整系统 | 1,122 | 1,809,231 | 0 | 0 | 0 |
| 移除 event | 1,122 | 1,809,231 | 0 | 0 | 288 |
| 移除 semantic | 1,122 | 1,809,231 | 686 | 1,259,896 | 0 |
| 移除 procedure | 1,122 | 1,809,231 | 142 | 259,445 | 0 |
| 移除 meta | 1,164 | 2,204,823 | 0 | 0 | 0 |
| BM25 + 通用 reader | 1,164 | 2,204,823 | 909 | 1,558,806 | 270 |
| 历史问题 nearest + 通用 reader | 564 | 933,096 | 582 | 950,064 | 108 |
| 单来源分类器 + 通用 reader | 829 | 1,267,126 | 802 | 1,268,269 | 93 |

`parse_bytes` 可以对同一证据因不同任务操作重复计费，因此不能与 `read_bytes` 相加后当作唯一数据量。缓存把解析提前到初始化；不代表这部分工作消失。当前 event cache 的序列化表示含重复快照，完整缓存尤其不紧凑。

| 实际表示大小（bytes） | Phase 0 | Phase 1 | Phase 2 |
|---|---:|---:|---:|
| 当前来源正文，共享 | 300,924 | 599,809 | 903,831 |
| 共享 event 表示 | 18,300 | 39,472 | 65,364 |
| 完整类型缓存序列化 | 1,025,268 | 2,033,700 | 3,057,113 |
| 去掉 event 的类型缓存 | 36,438 | 74,215 | 117,717 |
| 通用 reader 空缓存表示 | 10 | 10 | 10 |
| 模块/来源注册表 | 29,099 | 56,154 | 83,113 |
| BM25 索引 | 350,281 | 658,300 | 959,047 |
| 历史问题 nearest 索引 | 996,608 | 1,799,552 | 3,281,408 |
| 训练 feature buffers | 1,875,968 | 3,387,392 | 6,176,768 |
| 训练 heading targets | 58,624 | 105,856 | 193,024 |
| 训练 source targets | 2,344,960 | 4,234,240 | 7,720,960 |

历史索引复用训练 feature/heading target 数组；以上行有重叠，不能直接相加当作 RSS。缓存大小是实际 canonical 序列化的字节长度，不是 Python 对象 RSS。每个正式 model artifact 同时保存实验的两个分类器、Adam 状态和历史索引，不能把该共享 artifact 全部归入每一个控制后再次相加。

| 模型 | 可训练参数数 | f32 参数 bytes | Adam m/v bytes | 每阶段每 seed 的 steps / batch / presentations |
|---|---:|---:|---:|---|
| 学习 heading 寻址 | 8,752 | 35,008 | 70,016 | 240 / 32 / 7,680 |
| 单来源分类器 | 29,344 | 117,376 | 234,752 | 240 / 32 / 7,680 |

训练 observations 随阶段为 916、1,654、3,016。每个阶段每个 seed 的真实权重、完整 Adam 状态、初始/最终参数摘要、梯度范数、参数变化、schedule 摘要、loss trace、fit wall/CPU 均在 `address.json.gz` 及 `PRE_TEST.json` 的训练回执中保存。九次共享寻址拟合的 wall time 合计 19.5046 秒，CPU 合计 18.1600 秒；它包含 source/query 特征构造和两个模型，而非仅 SGD 内核时间。[训练与模型例](evidence/typed/seed-31031/phase-2/PRE_TEST.json)

完整运行 wall time 为 33.8722 秒、CPU 为 41.0745 秒、进程 peak RSS 为 102,056 KiB。生成汇总之前的证据文件总计 21,948,339 bytes。它们来自共享开发主机上的一次执行，不是生产目标主机性能门槛。

原始 JSON 中的资源字段可逐项审计：

| 位置/字段 | 含义 |
|---|---|
| `metrics.work.evidence_reads/read_bytes` | 实际读取次数和材料化证据字节 |
| `metrics.work.parse_calls/parse_bytes` | 通用替代在查询时执行的解析次数与输入量 |
| `metrics.work.event_rows_examined` | 通用 event replay 实际扫描的行数 |
| `metrics.work.wall_seconds` | reader 执行时间，包含 trace 构造；不包含寻址 |
| `reader_resources.prepare_wall_seconds` | 类型缓存/通用 reader 的准备时间 |
| `reader_resources.cache_serialized_bytes` | 类型缓存的实际编码长度 |
| `reader_resources.source_text_bytes/shared_event_bytes` | 所依赖的共享来源与事件表示 |
| `address_runtime.calibration_seconds/test_address_seconds` | 阈值校准阶段与测试寻址阶段实际时间 |
| `shared_address_resources.index_build_seconds` | 共享模块/BM25 索引构造时间 |
| `shared_address_resources.registry_bytes/bm25_index_bytes/history_index_bytes` | 三种地址辅助表示的大小 |
| `shared_address_resources.feature_bytes/source_target_bytes/heading_target_bytes` | 训练数组，含与历史索引重叠的项 |
| `shared_address_resources.fit_wall_seconds/fit_cpu_seconds/training_rows` | 含特征构造的共享拟合开销和真实训练行数 |
| `shared_address_resources.models` | 分模型参数、优化器、呈现次数和训练回执 |
| `address_artifact.bytes/decoded_bytes/sha256` | 实际 gzip 文件大小、解码长度和文件身份 |
| 汇总 `wall_seconds/cpu_seconds/peak_rss_kib` | 整个实验进程的运行成本 |

同一寻址分数在共享权重的多个消融中复用，因此 `address_runtime` 是共享支出，不是每个消融都重新发生的独立调用。缓存可能减少即时解析，但此处的微秒级差异不足以支持普遍效率主张；比如去掉 semantic 的 reader 总时间反而略低于完整系统。确定的结论是工作发生位置与保留表示不同。

## 验证、复跑和身份

执行 `python qualification/memory-cell-v12/typed_tests.py`，五项行为回归通过：原文步骤与执行边界；每个 specialist 移除后的可用 generic 路径；更正/撤销与两证据预算；篡改事件内容拒绝；真实文档原文范围及 604 条任务的正确证据 oracle 验证。Oracle 仅检查解释器与标注的一致性，正式成绩全部来自实际地址方法。

正式复跑命令要求一个不存在的输出目录：

```sh
python qualification/memory-cell-v12/typed_experiment.py --output /tmp/hepta-typed-repeat
python qualification/memory-cell-v12/typed_analysis.py /tmp/hepta-typed-repeat
```

正式执行前已保存源码、协议、语料身份和运行环境，结束时再次核对源码摘要。`EXECUTED_SOURCE` 保留确切执行版本；后处理不参与拟合或选择。[冻结执行源码](evidence/typed/EXECUTED_SOURCE)

- 语料 SHA256：`ea519ba0a0d3e1973409e862f205f3e7c943e7d1370d3d1ead667369c7c4f82a`
- 任务 SHA256：`e378f5219017482ce127775c8002842dbb5b596bbc17e5e188c87d18623222a9`
- `SUMMARY.json` 文件 SHA256：`36de5c13c0020cdf7fda5282823340e4fde3898c975e26ddf6a9eea40b8091e0`

这组证据支持实现可替换的类型端口、来源绑定的读取与真实状态转换。它尚不支持参数化正文压缩、通用推理、自发分化、拓扑净收益、原生多类型模型部署，或超越强检索加通用 reader 的结论。
