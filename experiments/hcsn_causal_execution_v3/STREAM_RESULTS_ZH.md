# 因果读取、真实恢复与完整本地执行：formal002

本轮完成 **26 个受监督 worker、36 次实际新进程恢复**，逐动作证据和成本记录均可复核。两个任务按冻结验证规则都选择 **READ-all**；没有任何减少读取的候选满足同时保持验证准确率及 CE 容差的条件，因此**本轮没有合格的编码节省或经济性优势**。这批实验验证了因果读取和恢复执行接口；共同 AV 前端的跨 actor 泛化仍不足，不能由接口通过推导识别能力已解决。[正式汇总](results/stream/formal002/SUMMARY.json) · [验证选点](results/stream/formal002/SELECTION_COMPLETE.json)

## 1. 执行合同与冻结身份

普通策略使用同一选中普通内容模型、同一源数据和同一读取接口。策略顺序显式冻结为 READ-all、periodic、confidence 0.6、0.75、0.9。先在验证集比较全部候选；候选必须满足准确率不低于 READ-all、CE 不超过 READ-all + 0.1，再最小化 encoder 调用数，同分按冻结顺序处理。两个任务完成选点后才准备本轮测试流。[协议](results/stream/formal002/PROTOCOL.json)

源代码与模型在执行前冻结，远端提交为 [58734d86b5dd8436f56a210632fca1acf8f3ea6c](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/58734d86b5dd8436f56a210632fca1acf8f3ea6c)。formal002 协议 SHA-256 为 `7825b69fbd335d3c52502b8ad6cb9090f698cd95609cd222137ba85b035e38af`。先前执行前审阅材料被保留；本报告只对应 formal002 的源码与运行。

公共 header 只向策略提供当前的索引、时刻、模态与可用性。选择 READ 后才读取该条 16 维 float32 payload，共 64 字节，并调用 encoder。WAIT 不读取 payload、不调用 encoder；STOP 不读取未来 payload。继承 delta 不存入源数据；执行器从实际接受的同模态历史重新计算 delta/age。每条读取同时核验预先固定的 payload 哈希，恢复检查 source header 与 encoder 身份。[执行器](stream_runtime.py) · [研究执行入口](stream_study.py)

这是已准备特征的本地文件读取代理。它不代表摄像头、麦克风或网络在物理上少采集了同样数量的数据。文件请求字节、encoder 调用数和实际进程成本分别记录；这里的“时延”是计算回放 wall time，没有按媒体时钟实时等待。

## 2. 验证集的全部策略结果

### AV 情绪

| 策略 | 准确率 | CE | encoder 调用数 | 是否满足冻结质量约束 |
| --- | ---: | ---: | ---: | --- |
| READ-all | 33.33% | 1.287940 | 549 | 是，获选 |
| periodic | 41.67% | 1.533236 | 266 | 否：CE 超过允许上限 1.387940 |
| confidence 0.6 | 16.67% | 3.627933 | 48 | 否 |
| confidence 0.75 | 16.67% | 3.524602 | 87 | 否 |
| confidence 0.9 | 25% | 2.650581 | 322 | 否 |

periodic 的准确率更高，但其概率预测的 CE 不满足预定约束，不能看到调用数下降后再更改验收目标。[逐候选原始记录](results/stream/formal002/validation/async_av/)

### AV 同录制 binding

| 策略 | 准确率 | CE | encoder 调用数 | 是否满足冻结质量约束 |
| --- | ---: | ---: | ---: | --- |
| READ-all | 75% | 0.610472 | 720 | 是，获选 |
| periodic | 62.50% | 0.599120 | 336 | 否：准确率下降 |
| confidence 0.6 | 54.17% | 0.767150 | 104 | 否 |
| confidence 0.75 | 58.33% | 0.933533 | 222 | 否 |
| confidence 0.9 | 70.83% | 1.135929 | 479 | 否 |

调用数大幅减少时，内容质量或校准均未按冻结规则保留。选点保留这些失败候选，没有把 READ-all 的正确率与另一个策略的低成本拼成一个不存在的结果。[逐候选原始记录](results/stream/formal002/validation/av_binding/)

## 3. 测试质量与实际计算成本

两个选中策略恰好等于 READ-all。因此原定每轮 baseline/selected 的两个位置都是同一个策略，共获得每任务 **6 次相同样本的重复执行**，而非 6 组独立质量样本。汇总使用全部重复：episode p50/p95 来自合并的请求时延，worker CPU/wall 为六次的中位数。

| 项目 | AV 情绪 | AV binding |
| --- | ---: | ---: |
| 独立旧测试 actors / 样本 | 2 / 12 clips | 2 / 24 pairs |
| 准确率 | 41.67%（5/12） | 54.17%（13/24） |
| CE | 1.877591 | 0.728022 |
| 每次完整测试集 encoder 调用数 | 521 | 720 |
| 每次请求 payload 总字节 | 33,344 | 46,080 |
| 相对同 encoder READ-all 节省 | 0 | 0 |
| episode 回放 p50 / p95 | 13.867 / 19.049 ms | 8.686 / 12.228 ms |
| fresh worker CPU 中位数 | 0.284575 s | 0.344923 s |
| fresh worker wall 中位数 | 0.285015 s | 0.345250 s |
| 单 worker 峰值 RSS | 27,164,672 bytes | 27,164,672 bytes |

fresh worker 记录包含该进程的启动、导入、模型读取、源 header、所有逐步推理及结果写入。它不包含事先准备特征文件或先前模型拟合的成本；这些必须另列。当前运行采用整个已接受前缀重新编码，不能宣称已经实现增量缓存后的成本。[所有进程记录与六次重复](results/stream/formal002/SUMMARY.json)

READ-all 与先前冻结完整输入 probe 的最大概率差为情绪 `2.22e-16`、binding `7.77e-16`。这是数值等价检查，说明拆成因果 READ 接口没有改变既定最终内容预测。前端本身的质量限制没有因此消失：情绪验证筛查未通过，binding 的验证 75% 没有转化为旧测试上的可靠泛化。[共同前端结果](AV_RESULTS.md)

## 4. 36 次实际新进程恢复

每个测试 episode 在前两个 header 后序列化；退出该源句柄，然后启动新的 Python 进程、重新读取模型、验证 source/model 身份、恢复已接受历史并继续。情绪完成 12 次、binding 完成 24 次。恢复后的每个动作、前后概率、accepted 内容行、读取字节及调用数均与不中断执行一致。

| 恢复条件 | AV 情绪 | AV binding |
| --- | ---: | ---: |
| 实际新进程恢复 episode 数 | 12 | 24 |
| 最终准确率与读取量 | 与连续执行相同 | 与连续执行相同 |
| 含重启的 episode p50 / p95 | 116.873 / 149.792 ms | 107.469 / 121.939 ms |
| 整个 recovery worker CPU | 1.585338 s | 2.728697 s |
| 整个 recovery worker wall | 1.585956 s | 2.732213 s |

这里的进程计量使用 Linux `wait4`，包括 worker 等待结束的恢复子进程。逐 episode 的 `parent_episode_cpu_seconds` 刻意仅表示父进程 CPU，不能单独拿来代表恢复总成本。[恢复情绪记录](results/stream/formal002/test/recovery_async_av_all/RESULT.json) · [恢复 binding 记录](results/stream/formal002/test/recovery_av_binding_all/RESULT.json)

## 5. 成本总账的范围

26 个内部 worker CPU 合计 **13.064231 s**、wall 合计 **13.081777 s**。外层完整研究进程 CPU 为 **13.263035 s**、wall 为 **13.271965 s**；它已经包含这些 worker 及其等待完成的恢复子进程，**不能再加上内部 worker 合计**。外层 receipt 位于 `meter/` 之外，独立审核确认汇总没有双计。[外层全过程 receipt](results/stream/STUDY_PROCESS_RECEIPT.json) · [内部 worker 汇总](results/stream/formal002/SUMMARY.json)

其中，验证流准备使用 1.429521 CPU s，测试流准备使用 1.408244 CPU s。全过程最大单进程/等待后代峰值 RSS 为 208,314,368 bytes；不能将多个独立峰值相加称为同时峰值。所有实验在同一共享 CPU 主机、单线程限制下运行，其他租户影响不能排除。

该总账覆盖这次本地 prepared-feature 研究执行，包括验证选策略、测试、证据写入及恢复。**它不包含先前普通 encoder 的全部训练过程、最初原始媒体解码、真实传感器和网络通信；设备 joule 能量不可用。** 边界求解器调用为零，因为这部分研究的是同一普通内容前端上的读取策略，解析/普通核心的 2×2 归因属于另一组实验。缺失的成本没有被记成零，也没有以 FLOPs 估算代替能量观测。

## 6. 独立审核与复现

`stream_audit.py` 不导入候选分析或评分函数，独立检查 24 份逐例结果中的 **12,575 个动作记录**、所有 payload/encoder/source 哈希、逐样本最终分数、完整验证候选与顺序、六次重复的成本汇总及 36 份恢复状态。全部通过；两个任务唯一符合冻结选择条件的候选均为 READ-all。[独立审核程序](stream_audit.py) · [审核记录](results/stream/formal002/INDEPENDENT_AUDIT.json)

从仓库根目录重算审核，使用尚不存在的输出文件：

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
python -m experiments.hcsn_causal_execution_v3.stream_audit \
  --study experiments/hcsn_causal_execution_v3/results/stream/formal002 \
  --output experiments/hcsn_causal_execution_v3/results/stream/formal002/AUDIT_REPLAY.json
```

源数据和选中模型恢复后，可在新目录重新冻结并执行。准备数据的 Python 需具备上游模块所用 PyTorch；热执行只需要 NumPy：

```bash
python -m experiments.hcsn_causal_execution_v3.stream_study freeze \
  --output experiments/hcsn_causal_execution_v3/results/stream/replay001

python -m experiments.hcsn_causal_execution_v3.stream_study execute \
  --output experiments/hcsn_causal_execution_v3/results/stream/replay001 \
  --training-python /path/to/torch-python
```

重跑的 wall/CPU 数值会随主机负载改变，质量与动作应按相同源码、模型和输入复核。本轮结束时，因果读取及实际新进程恢复已有完整执行证据；更强、能跨 actor 泛化的 AV 内容前端，以及同质量条件下可兑现的读取和计算节省，仍是开放的科学验收项。
