# 既有 JointGenerator 的生成桥接

本阶段把选定的已有 JointGenerator 计算内核接入 V2 Cell 生成契约。它保留现有 Agentd、Neuron 和 durable inference owner，各层只有原来的职责：生成进程提出结果，control owner 保存原操作结果，Cell owner 提交运行状态和输出，交付方单独确认。

本目录说明实现与验收边界。是否执行、在哪个源码和环境上执行、是否通过，均以独立的原生执行记录为准。源码中存在测试、历史研究分支通过过测试、或 reference 文件中存在摘要，都不构成本阶段的执行资格。所有生成回执继续 `DENY_ALL`。

## 一、事实由谁持有

| 层 | 持有的事实 | 不由该层决定的事项 |
| --- | --- | --- |
| `JointGenerationProcessWorkerV1` / `hepta-joint-propose` | 实际资产字节、计算后的状态提案、未发布输出增量、可观测成本 | Cell journal、已发布 prefix、outbox、采用许可 |
| `DurableInferenceControl` 的 generation family | 完整请求绑定、唯一 live dispatch token、取消意图、原始终态结果字节 | Cell 状态和输出是否提交 |
| `ControlledCellGenerationPortV2` | 有界 RPC、一个 control actor、独立 worker、原结果读取 | 重新执行未知操作、授予模型资格 |
| `AgentdNeuronGenerationOwnerV2` / Cell journal | 状态、不可改写 prefix、outbox、任务成本与提交回执的原子持久化 | 模型质量结论、下游是否收到输出 |
| 显式 delivery ACK | 精确 outbox 项已交付的观察 | 修改原输出、回写另一个结果 |

`execute` 可能返回 Pending。此时调用者应使用同一完整请求绑定读取和 reconcile 原结果；超时、取消、进程丢失、重开都不能自动生成第二次 dispatch。一个未决 generation 记录占住 worker 槽，重开不会丢掉该约束。

control 的 generation 记录复用现有文件 owner、锁和 journal。它与现有 native/通用记录共享请求 ID 和容量预算；追加其它记录时为未决 generation 的最大结果预留空间。token 不可克隆、不可序列化，也不会从 replay 中恢复。只有仍持有未消费 live token 的调用者能证明尚未 dispatch，并提交本地 abort。

## 二、选中的真实后端与身份绑定

计算内核来源固定为 `18dac3ccd30317893ad922792c12400390522f00` 下的 `experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/native_generation`。逐文件原始 Git blob 与 SHA256、改动类型、被排除的旧 driver owner 路径保存在 [`JOINT-PROVENANCE.json`](../../codex-rs/hepta-infer-worker-host/JOINT-PROVENANCE.json)。

新 binary 使用原 Encoder、递归状态、Head、actor/critic、采样与多模态解码计算。旧 driver 的文件锁、session 写入、publish 和 export 路径没有进入该 binary。这里没有为 JointGenerator 虚构一个 World Model。

宿主显式配置 executable、weights、public packet 的路径和内容摘要，并绑定 source 与实际观察到的 Linux CPU/kernel profile。加载后 weights/public 保留为不可变字节；请求只传 public digest 和 typed command，不能传路径、shell、替换权重或另一个 executable。

executable 保持打开的 inode，通过 `/proc/<parent-pid>/fd/<fd>` 执行，并在执行前后重新核验内容。路径替换不会切换已打开文件。宿主必须保持被准入 executable 的内容不被原地修改；前后摘要检查不能证明两次检查之间没有发生内容 ABA 改写。这是受信宿主的 artifact 边界，不是对任意宿主篡改的证明。

manifest 对 profile、source、runtime、device、Encoder/Head/Memory/decoder 身份、Frozen weights、输入/状态/输出 schema 和容量逐项校验。这里的 device digest 是能力 profile，不是硬件序列号或采用许可。完整训练 checkpoint 属于独立的 V13 内容验证阶段，不会被伪装成这个生成后端的 Frozen weights。

## 三、纯 proposal 协议与状态闭包

请求为有上限的 stdin 字节：`HJREQV01`、原操作 digest、weights、public、前驱 state、已提交 prefix、typed command。结果为 `HJRESV01`、相同 digest、停止状态、四个互不重叠的阶段计时、后继 state、delta 和响应校验和。完整长度及字段都检查，额外尾字节拒绝。

| 字段 | 硬上限 |
| --- | ---: |
| weights packet | 8 MiB |
| public packet | 1 MiB |
| 递归状态 | 65,536 bytes |
| 已提交 prefix | 262,144 bytes |
| 单次 delta | 65,536 bytes |
| stderr | 16 KiB |

`Init` 只允许空 state/prefix。`Advance` 调用实际递归计算；`Auto` 使用原 actor/critic；`Commit` 仅提交指定模态的剩余单位。STOP 先走实际停止转换，再在一个提案中补齐四种模态的剩余输出。

状态保存原递归状态、权重/输入身份、seed、sampler、各模态 cursor、已提交模态字节和整体 prefix 摘要。恢复时重新构造完整 canonical state packet，并从真实 prefix 的 `HGC1` 帧重新解析各模态字节和 cursor；仅修改自报 hash 或 cursor 不能通过恢复校验。输出采用有界 RGB 行、PCM16LE 样本、RGB 帧和文本单位，prefix 不可回写。

宿主的进程监控独立处理取消、deadline、时钟回退、stdout/stderr 溢出和进程终态。只终止自己持有的 child。终态不能在有界时间内确认，或管道未能完成收集时，操作保持未知；未知结果不会被转换成虚构的零成本失败。已确认终止但协议损坏时，记录实测消耗并返回 Failed，保持前驱状态且不给出输出。

## 四、正常 Agentd 生命周期

桥接使用已有的显式 generation bootstrap 配置和普通 runtime task，不增加第二条研究 driver 启动路径。默认配置仍须由调用者显式选择并绑定后端。正常启动、execute/reconcile、cancel、drain、ACK、shutdown 和 same-owner reopen 共用前一阶段建立的身份、Fleet lease、文件 witness、完整 journal continuity 与 owner 规则。

新测试覆盖两层：宿主测试运行真实 helper 完成 Init → Advance → 部分 Commit → STOP；Agentd 测试将真实 `DurableInferenceControl`、有界 control actor 和真实进程 worker 放入普通 runtime/Fleet 路径。测试资产是明确标记的合法 synthetic 67 张量，不能用来证明历史训练模型质量。

same-owner reopen 验证同一 manifest、journal 和原状态继续可读。已有 service generation replacement 验证 owner 连续性；它不等同于跨 manifest 的模型更新或不同 checkpoint 的采用。后者仍须与现有发布、依赖、评估和撤回 authority 组合并独立验收。

## 五、统一成本中的已知与未知

| 观察 | 记录方式 |
| --- | --- |
| child codec、encoder、inference、planning | 成功结果中的四段互斥 wall microseconds |
| 原 actor 与 continuation/delivery critic | 包含在 planning；不重复另记 Critic |
| 父进程启动、IPC、响应校验和未分配开销 | 总 wall 减去已测 child 阶段，作为一个互斥余项 |
| 实际 stdin/stdout/stderr 字节 | 实测通信字节，仅计一次 |
| control 排队及准入/dispatch | 独立 Queue 与 Persistence wall 记录 |
| 失败/取消/超时，但已确认进程终态 | 实测整体消耗；未得到的 child 分段保持未知 |
| CPU、能耗、完整保存/恢复与最终 fsync 等未覆盖阶段 | 未知，不能用 0 替代或宣称全覆盖 |

这些记录可以合并进同一任务账本，不能直接推出分化收益。公平固定专家对照还需要真实相同容量、累计训练预算、选择性更新条件和完整任务成本观察；本阶段没有运行训练或这项比较。

## 六、验收与评审顺序

最小可独立评审的顺序如下，各层的测试随拥有对应不变量的代码放置：

1. `hepta-infer-core/src/generation_control.rs`：原操作结果、token、容量预留和 replay。
2. `hepta-neuron/src/cell_generation_control*.rs`：有界 actor、独立取消和原结果 readback。
3. `hepta-infer-worker-host/src/joint_generation/`：来源明确的数值内核及纯提案协议；先核对 provenance，再看新 decoder/state 校验。
4. `hepta-neuron/src/cell_joint_*.rs`：实际进程、artifact binding、终态观察与成本；随后看普通 Agentd 生命周期测试。
5. helper/Bazel/原生验收声明：运行真实构建产物；测试从 Cargo artifact metadata 得到路径，不猜测旧 target 中的同名文件。

原生门按顺序执行 scoped `just fix`、独立 strict Clippy、10 个实际 helper 的 metadata/hash 验证、20 包 scoped `just test --locked`，通过后执行完整默认 `just test --locked`。Core 已在前一阶段修改，因此最后一门不能省略。每个 test stage 独立隔离旧 JUnit，记录 fresh XML、原始摘要、精确源码与环境；187 个声明 workspace member 不会被当成实际执行包数。

上述顺序指统一原生调度。GitHub workflow 是两个独立 lane：mechanisms 检查 9 包并构建 1 个真实 Joint helper，agentd-composition 检查 11 包、构建全部 10 个 helper，并在 scoped suite 通过后执行完整默认 suite。CI 直接运行 strict lint，不运行修改源码的 `just fix`。两种执行记录分别绑定各自环境和终态。

实际 trained weights/public 的所需摘要及此前有界查找记录保留在独立 evidence 中。尚未取得并验证这些字节时，可以验收 synthetic 资产上的实际控制/进程/lifecycle 行为；不得把它写成所选历史训练模型已运行或已被产品采用。
