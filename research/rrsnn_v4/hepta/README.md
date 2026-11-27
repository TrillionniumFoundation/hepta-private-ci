# R5：真实原生 owner 组件执行与有条件的首提交恢复修复

## 本轮实际推进到哪里

本目录执行了冻结 Hepta 源码中的 `NeuronRuntime`、`SparseJournal`、`FileAnchorWitnessStore` 和注册的 inference-control 请求／回执适配路径。测量中的每个实例都有真正的运行时、独立 journal 文件和独立 witness 文件；每个输入都实际执行固定的 8×22 Q24 矩阵投影。这比“只编译官方类型”或给神经元数组改名为 Cell 更进一步。

规模测量没有实例化生产 Agentd/CNS 路由器、完整 Cell 宿主或 RR-SNN 学习模型。该测量的固定投影是验证持久化执行路径的研究模型；配置中的 calibration/OOD 字段是明确标识的 fixture，不能作为实测校准资格。本目录另有独立的真实 RR 特征后端桥接及故障验证，其权重身份、证明范围和成本记录与这组规模测量分开。所有输出均检查为 DENY_ALL，没有外部 effect 目的地。宿主是本地工作区执行器，尚无 dot 身份证据。

测量中的所有 tick 都完成实际模型运算、状态提交与 witness 发布，但其输出 disposition 全部为 `abstain=true`，由研究 fixture 的严格接受阈值产生。因此这些数值也不能代表已接受决策的下游路由／执行成本。

因此，资源数据的单位是“原生 owner 组件实例”，不能填入“完整生产 Cell”主表，不能据此声称 RR-SNN 的未来效用、负迁移或部署收益已经得到验证。

冻结设计资料 `docs/readiness/NEURON_RUNTIME_EXECUTION.md` 及 `docs/modules/neuron.runtime/TECHNICAL.md` 将 DecisionCell 描述为既有 owner 下的 organ-local 逻辑 slot，由共享 inference worker 服务；Cell slot 不能悄悄附加到 V1 状态键，也不等于独立 subject／进程。本 harness 每个组件采用独立 subject scope、journal 和 witness，尚未实现该 slot 编址、有效参数 bundle、路由选择与 run-owner 回执交接。因此即便实例数恰好为 64／256／1024／4096，也不能将它认定为上述 DecisionCell 集成。

## 源码与构建

基础源码提交为 `f8c9419df6ddeb36ff8b522a50219981fb8d9345`。`native_components.py` 按旧版源清单检查 SHA-256、Git blob SHA 和字节长度，原始 V2 源码保持不变。依赖使用已存在的 vendored crates，Rust 1.95.0 单作业离线构建；执行 `just fmt`、`just build`、`just test`。

两套二进制严格区分：

| 二进制 | 上游源码 | 用途 |
|---|---|---|
| `rrsnn-native-owner` | 原始三 crate，不修改 | 组件规模实测、原有行为与故障复现 |
| `rrsnn-native-bootstrap-repair` | 三 crate 的隔离副本，仅 `runtime.rs` 增加一个显式方法 | 有条件的首提交恢复修复实验 |

这是相关依赖的精简研究工作区构建，不是完整上游仓库 CI。`bootstrap_recovery_source.json` 和 `bootstrap_recovery.patch` 保留精确改动及前后摘要；原始持久化格式和既有恢复 API 的行为没有修改。

## 64／256／1024／4096 原生组件实测

固定协议在运行前写入 `native_results/benchmark_protocol.json`：CPU 8、单线程有界 FIFO、每个规模各启动新进程，4 轮预热、32 轮测量。每个 owner 的 wall time 从 `tick` 前开始到返回为止，包含 journal 与 witness 持久化；上游回执内部的 `execution_micros` 在 witness CAS/fsync 之前取得，不能替代这里的完整 tick 耗时。32 个整批样本的 p99 只是该运行的描述性分位数，不是稳定的尾延迟 SLA 估计。

首次完整矩阵结果：

| 原生 owner 实例数 | 被测 owner ticks | 完整 tick p95 / p99 (ms) | 整批 p99 (ms) | 吞吐 (owner ticks/s) | 测量结束时进程 VmHWM (MB，十进制) | 内存事件窗口 |
|---:|---:|---:|---:|---:|---:|---|
| 64 | 2,048 | 2.826 / 6.024 | 247.083 | 834.889 | 3.682 | 无新增 max/oom/oom_kill |
| 256 | 8,192 | 3.105 / 5.940 | 647.873 | 769.386 | 7.483 | 无新增 max/oom/oom_kill |
| 1024 | 32,768 | 3.308 / 6.561 | 2153.849 | 690.154 | 22.585 | 无新增 max/oom/oom_kill |
| 4096 | 131,072 | 3.634 / 9.167 | 19427.086 | 582.535 | 82.682 | **无效：共享 cgroup memory.max 增加 8044 次** |

RSS 值读取于测量轮次结束、全部恢复之前，包含该进程的输入、时序记录数组和 owner 数据结构，不能直接除以实例数后称为单个 Cell 的净状态成本。单次 tick 分位数不包含排队等待；原始记录另存 queue age 和整批延迟。首次 4096 窗口没有新增 OOM/OOM-kill，但触发了内存上限事件，保留原始值并将资源窗口标为无效，不能以“程序完成”替代验收。其它窗口也只证明没有这三类内存事件，不证明宿主没有 CPU、I/O 或其它工作区的干扰。

各规模在 36 次提交后、继续运行前的 journal+witness 文件长度分别为 1.269、5.077、20.308、81.232 MB。每个计量 journal 字节增量都与真实回执核对。之后关闭并重新打开**所有**实例，核对所有恢复 anchor 的组合摘要，每个实例再执行一次真实模型调用；四个规模均通过。日志长度属于本协议的增长成本，不是长期无界运行的容量规划。

初始完整结果在 `native_results/component_benchmark.json`。4096 的一次限定确认使用相同二进制与协议，结果另存 `component_benchmark_confirmation_4096.json`，不覆盖初次无效窗口。确认是否有效必须读该文件的 `memory_window_valid`，不能仅凭文件存在判定。

这次确认实际完成，并且 `memory.events` 的所有计数增量均为 0：4096 owner 的完整 tick p95/p99 为 **2.899/5.243 ms**，吞吐 **769.972 owner ticks/s**，测量结束时 VmHWM **82.674 MB**，整批 p99 **9229.639 ms**，队列等待 p95 **5536.502 ms**。所有 4096 实例完成重新打开和继续提交。这样四个规模均有无新增内存上限/OOM 事件的本地组件记录；原始受干扰窗口仍保留，不能将两个运行挑选为一条虚构的同时观测，也不将“内存事件有效”扩大解释为完全独占宿主。

## 首提交真实故障：先保留失败，再修复

原始 API 在四种真实 SIGKILL 窗口中恢复了三种：第一／第二次提交，分别在 witness 发布之前／之后杀死进程。失败窗口是：**第一条 journal 已持久化，第一条 witness 尚未发布**。此时 journal 非空，bootstrap 拒绝；独立 witness 为 None，常规 anchored recovery 没有可信锚点。失败证据保存在 `native_results/validation_latest.json`，没有被改写成通过。

隔离补丁增加 `NeuronRuntime::recover_bootstrap_anchored`：调用者必须给出独立保留的预期第一条 anchor；只接受 sequence=1 的非零摘要；独立 witness 必须明确为 None；使用既有 `SparseJournal::open_anchored` 校验外部 anchor；最终状态必须恰好等于这条第一 anchor；最后通过 witness 的持久化 CAS 发布。存在 witness 时必须使用原有 anchored recovery。补丁不会自动从未锚定 journal 取出第一条记录并将其视为可信依据。

### 这个修复的信任前提

一个真实旧 intent 加上一个真实第一 anchor，仍然无法单独识别“journal 和 witness 一起回滚到过去”的情形。**调用者还必须独立知道这个 generation 的初始化当前仍在等待第一次发布。** 这个条件类似于既有 `open_anchored` 的外部可信当前历史前沿：API 接受宿主提供的可信前提，不负责凭 checksum 生成许可。它不能作为删除、撤销或已确认历史丢失的通用修复。

实验控制器在故障 owner 创建之前，独立运行固定输入／模型／纯 Q24 状态转换，计算第一条及后续预期 checkpoint，写入并 fsync intent，再在控制器内单独固定 intent 的摘要。计算过程不开 journal，也不读取 journal。随后控制器保留 owner 外部的生命周期记录及独立 pin；一旦观察到已发布状态，即使旧 intent 文件仍在，也拒绝走初始化恢复入口。该控制器只对它自己启动的全新研究进程提供信任前提；这些记录不是生产 owner 签名或 Control 许可。

### 修复验证

`bootstrap_repair_results/proof_latest.json` 记录：

- 6 条真实 SIGKILL 恢复路径通过：原有四个 owner 故障窗口，以及恢复发布本身前／后再次崩溃的两个窗口。
- 恢复过程中模型调用数为 0，恢复后恰好执行 1 次新调用，得到事前独立计算的下一 checkpoint。
- 14 项拒绝检查通过，包括缺失 intent、外部 pin 错误、intent 篡改、错误 generation、错误第一 anchor、已有 witness、后续历史但 witness 缺失、常规恢复禁止自动降级、已发布生命周期拒绝旧 intent、生命周期文件被篡改。
- 对伪造 journal 的测试使用真正原生提交路径和改变后的有效输入，因而 journal 具备合法格式及校验和；仍因与独立预期第一 anchor 不符而拒绝。
- 错误 anchor 配合 torn tail 的案例在 tail repair 前被拒绝，journal/witness 文件保持原字节。
- 将 journal 和 witness 同时恢复到合法的“第一条已写、未发布”旧快照，并保留匹配的旧 intent，控制器仍凭独立保留的已发布当前前沿拒绝，未调用原生恢复方法。这项拒绝来自控制器的可信状态，不是 API 从两个已经回滚的文件中推断出历史。
- 所有被验证的输出仍为 DENY_ALL。

这闭合的是**在可信当前初始化前沿前提下，研究参考实现的首提交崩溃恢复缺口**。它没有闭合生产宿主的生命周期可信存储、双文件恶意回滚、删除后恢复授权或实际发布治理。

## 复现命令

在原工作区根目录运行；不下载工具链或依赖，不对原仓库执行测试命令：

```bash
python3 rrsnn_v4/hepta/native_components.py
python3 rrsnn_v4/hepta/native_components.py --binary /workspace/scratch/38ad1e295a60/rrsnn_v4/hepta/native_build/target/release/rrsnn-native-owner --measure
python3 rrsnn_v4/hepta/bootstrap_repair.py
```

若只确认先前因共享内存事件无效的 4096 规模：

```bash
python3 rrsnn_v4/hepta/native_components.py --binary /workspace/scratch/38ad1e295a60/rrsnn_v4/hepta/native_build/target/release/rrsnn-native-owner --confirm-4096
```

这些测试会创建新时间戳目录，并只清理由自身创建、已提取测量证据的临时规模测试 stores。原有结果和故障样本保留。完整源码快照与 vendored 依赖仍引用现有 V2 包；本轮没有重新下载来源或依赖。

## 仍需真实外部证据的项目

当前可执行实现不能替代真实完整 Cell 工作负载、dot 主机证明、当前有效生产初始化 intent／生命周期状态、RR-SNN 模型在真实 profile 的注册与校准、真实资源成本下独立未来窗口的效用和负迁移观测。它们在结果 JSON 中保持 false／未证明。新的源代码和真实组件实验解决了本地实现缺口，没有把这些外部事实改成通过。

## 上游草稿补丁与补充验证

修复已发布为 [草稿 PR #4274](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4274)，隔离分支 `dot/rr-snn-v4-bootstrap-recovery-20261029`，提交 `fda9689456189c7dad3a1d033b5488d02b29334a`。没有合并或激活。最终源码经一次仅格式调整（含移除可选的末尾实参逗号），前后源码／patch 摘要与逐字差异保存在 `bootstrap_format_supersession.json`；此前二进制和审查记录继续保留原源摘要。

补充执行了真实 `codex-hepta-neuron` crate 的 **86 项单元测试，全部通过**，这是精简工作区的显式本地 just 包装。随后用精确上游 `run-nextest.py`、完整 `nextest.toml`、local profile 和 8 MiB 栈执行 scoped nextest，因精简工作区缺少全局过滤器引用的其它 package 而在运行前以 exit96 失败；没有删减过滤器来制造通过。完整仓库默认 nextest gate 仍须在真实上游工作区完成。测试二进制、完整日志、失败日志均保留；可重新生成的编译缓存已清理。

## 真实 RR 特征后端桥接

`rr_bridge_native/src/main.rs` 通过未修改的正式 `InferenceControlModelPort` 请求／回执接口启动 `rr_bridge_backend.py`，实际执行冻结 V4 `RRPolicy.step`。输出为 8 维真实脉冲迹线的 `tanh` 值，并采用 nearest-even 规则导出 Q24；模型内部的 81 动作 head 确实计算，但没有路由为原生决策。`rr_bridge_worker.py` 使用独立控制器固定的模型、请求、前一 native checkpoint、host dt/event 元数据和联合状态前沿，完成 prepare／reconcile／commit。原生 V1 sparse state 和外部 RR 状态保持各自明确的表示。

开发权重验证已经完成：`rr_bridge_results/development_latest.json` 记录 6 个真实 SIGKILL 窗口和 19 项拒绝检查全部通过。持久化涵盖 `CoupledState` 的全部 10 个字段以及完整 PCG64 状态（包括 128 位整数和 uint32 缓存），恢复后的状态、随机数前沿、输出 Q24 和实际脉冲数与不中断执行逐字一致。已被独立控制器固定的 prepared 结果在重试时不重新推进模型；还没有获得独立 pin 的准备结果被视为孤立产物，重试从可信前态重新计算，允许重复 CPU 工作，但已提交神经状态与 RNG 只推进一次。

这些桥接窗口从成功建立的第一个联合 checkpoint 之后开始；它们与上面的首提交初始化补丁是两组分开的证明。桥接仍要求故障进程之外的可信当前控制器前沿，不把 checksum 视为授权来源。桥接中的 Python 启动、控制器屏障和正确性检查不构成吞吐基准，也不能用固定投影的 64／256／1024／4096 数值推断训练 RR 后端的规模成本。冻结训练候选的后续证明必须读取 `rr_bridge_results/trained_latest.json` 的具体权重与选择摘要，开发权重证明本身不能替代它。

随后已完成真实训练权重验证：`rr_full` seed101 检查点 SHA-256 为 `32d23ba4e030beb5850b25faff1fd119c08da4af2035ca70ba40aa4c0d5af651`，绑定已发布选择摘要 `dbad2690403992f75c46105722670026e7e13acb523f4973f4726a91d6e5d6bd`，同样 6 个实际 SIGKILL 窗口和 19 项拒绝检查全部通过。训练模型的三个观测实际脉冲数为 `[0,0,1]`，故障注入第二次事务，随后第三次事务的真实脉冲及全状态与不中断执行相同。独立审核原件及训练证据 addendum 分别保存在 `independent_rr_bridge_review.json`、`independent_rr_bridge_trained_addendum.json`。完整身份、接口、覆盖范围和复现命令见 [RR_FEATURE_BRIDGE.md](RR_FEATURE_BRIDGE.md)。
