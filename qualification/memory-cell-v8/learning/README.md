# V8：来自实际访问前缀的分区学习与后续任务评估

本目录为新的可执行实验，不替换 V7 的实现、原始失败结果或验收边界。
它把访问分区学习接入真实原生 population、SQLite owner、发布/独立选择和 Agentd socket，
并保留后续任务、重训前后保留率、固定库存、轻量选择器与直接 owner 参照。
**源码存在不代表结果通过。只有完整实际运行及其可复算收据才是本轮证据。**

## 1. 新增机制

`allocation.py` 只读取已完成请求的地址集合、请求/读出 digest、顺序和来源 cut。
它统计地址频率和共同访问次数，在与固定分区相同的 shard 容量限制下，
按共同访问权重、已分配负载、已分配数量和 shard 编号执行确定性贪心分配。
这是从实际任务访问中拟合分区的计数学习器；不是额外训练的大语言模型路由器。

`population_training.py` 在所得分区内执行新的 NumPy tanh MLP/Adam 参数训练，
保留每个 shard 的原始参数、训练诊断、native 字节、显式 catalog、支持与 lineage。
`worker.py` 使用受 host 固定的解释器与代码摘要、隔离进程、输入/输出尺寸和时间上限。
固定参照复用冻结的 V7 分区训练代码；新的学习分区使用独立 V3 schema/profile：

| 项 | 值 |
| --- | --- |
| Native schema | `hepta.memory.population.native.v3` |
| Partition profile | `hepta.memory.causal-coaccess-greedy.v1` |
| Observation schema | `hepta.memory.causal-coaccess-trace.v1` |
| 原生实现 | `hepta-neuron/src/memory_population_learned.rs` |

原生 loader 独立复算访问摘要和全部分区，V3 trace 的 cut 在 bundle decode 和实际 owner admission 两层绑定。
原 V2 的 SHA 地址排序分区检查保留；给 V2 换一个任意路由或将 V3 字段混入 V2 不能绕过加载检查。
trace 的 digest 只证明内容一致：重新编造 trace 再计算 hash，并不能证明它来自真实过去。
真实观察及顺序需要下述 pinned host/CI 和原始字节共同审计，不能成为自发发布权限。

## 2. 预先固定的实际试验

父测试在任何 trial 前写 `MANIFEST.json`，固定源文件、训练代码摘要、预算、任务构造、权重和本次随机 nonce。
各 arm 在新的 OS 子进程中重建同一 owner：基础实体加 24 个当次写入的实体，每个都有事件、语义、过程记录。
来源 cut、实体、值、请求、每类型 16 KiB 的逻辑驻留预算以及未来评估量必须相同。
逻辑预算不是 RSS；训练和 host RSS 另行测量。

一个参数 arm 的顺序为：

1. 真实 SQLite 新写入、完整 owner export、固定四分片 bootstrap 参数 fit 与发布。
2. 用 bootstrap 执行 4 个六读取的保留任务，保存 `before-retention.json`。
3. 执行 16 个六读取的 `current` 请求任务；记录完整 typed 请求、解码后的读出、共同访问与实际 socket 计数。
4. 只将当前 owner export 和已完成访问前缀送入候选训练。保留 worker 的精确 request/response JSON 字节。
5. 发布并独立选择候选，保存 `FIT_LOCK.json`，随后执行 selection、future、retention 三批请求。

selection 为 4 个任务，future 为 12 个任务，retention 为与第 2 步完全相同的 4 个任务。
非前缀任务依次组合 `apply`、`semantic`、`procedure`，通过返回值计算有符号加和与阈值决策。
future 有逆序、跨相邻访问组、交错访问组三类组合；训练器没有未来请求或结果字段。
保留任务在候选前后都实际执行，不用候选事后分数冒充遗忘变化。

这测量的是**已经写入并进入支持集合的信息，在参数重训/重新分区之后的组合用途**。
没有增加未写入地址的泛化能力，也不是引入新数据数月后的长期遗忘研究。
所有请求通过显式受信 integration resolver；本试验不评估自然语言寻址。
作者构造的任务族也不满足独立同分布总体风险推断条件。

## 3. 三种不同参照，完整 11 个 arm

| 参照 | 如何选用 | 对应成本 |
| --- | --- | --- |
| 固定库存 `fixed-1` … `fixed-8` | 每个实际训练并运行；评分时取事后最强者 | 各自只计本 arm 与共同证据材料；免收从八者选出的搜索成本，明确标为 hindsight oracle / conservative fixed hurdle |
| `lightweight-prefix-selector` | 只以八者 selection 批次的决策错误、完整批次 wall、shard 数选择数量，保持固定地址分区 | 与 learned 一样承担全部八个 trial 的资源成本及同一个 selector；相同来源、前缀和 selection 信息可用 |
| `learned-coaccess` | 采用同一个 shard 数，从自己的同构已完成前缀学习共同访问分区 | 自身真实训练/读取加相同的完整搜索账 |
| `direct-owner` | 预声明精确参照；通过真实 control API 分页读取同一 typed 事实，在每次使用前后通过 socket 重验 cut，执行相同注册 opcode | 实际 owner 缓存、来源账本、通信、运行时间与证据；不计它没有执行的训练、模型搜索或模型存储 |

轻量选择器和 learned 的前缀请求、支持信息、selection 信息相同；各 fresh process 的运行时间和 artifact/readout digest 自然可以不同。
选择器的完整输入保存于 `SELECTION_LOCK.json`。Rust 单测检查改变未来答案/成本不会改变所选数量。
固定候选的未来批次虽然已经在各自子进程中执行，其结果不进入这个选择函数或 worker。

搜索账保守地计入八个 trial 的**完整实际生命周期**，包括它们的 future/retention 诊断。
这不是部署时必需的前缀选型成本估计。三种参照分别报告，不能把 oracle 与同信息轻量策略混称公平基线。
直接 owner 胜出、参数不改善、预算拒绝、读错、退化等结果全部保留；任一 arm 失败或缺失使比较无效，不能筛掉失败样本。

## 4. 可复算的证据与成本

每个原始 trial 保留：配置、来源 export、精确训练输入和响应、所有原始参数、
训练前保留批次、已完成前缀、trace、候选锁、selection/future/retention、成本与生命周期诊断。
`PROGRESS.jsonl` 每步追加并 fsync，将前缀内容 hash、对应 artifact hash 与阶段顺序绑定。
父进程保存退出码、实际 PID、完整生命周期 wall、受限 stdout/stderr 和原始 trial hash。
失败/超时不删除证据；子进程由父进程回收。

`evidence.py` 从 owner 事实及注册 opcode 独立重算预期读出和组合任务，
对 `request_bytes`/`readout_bytes` 中真正参与 hash 的 UTF-8 批次编码重新计算 digest，再与结构化字段比较。
它们来自本地 typed 请求和 client 解码后的读出；direct 读出是本地组合运算结果，均不是原始 Unix control envelope。
实际应用传输字节由 AgentdClient counters 计量，原始 control envelope 未持久化。
不重新编码浮点来猜批次 hash 输入，也不把保存的 expected answer 当权威。
`fit_evidence.py` 对精确 worker 响应复核请求绑定、支持、lineage、原始/native f32 参数和训练 receipt。
Rust 摘要中的浮点诊断只容许编码舍入差；保留的 worker 原串是诊断复算依据。

`costs.py` 使用预先固定的正权重：错误决策 1,000,000,000；wall ns 1；
逻辑材料 byte 100；应用传输 byte 10；分别观测到的进程 HWM byte 1。
这是用于比较的任意加权代理单位，不是货币或完整生涯成本。

- 完整 child lifecycle wall 计一次，已包含训练、读、唤醒、IPC、发布、阶段文件/fsync 与退出；不再叠加内含阶段计时。
- native 成本快照是累计量，只取末值或相邻差，不把三份快照相加。
- 来源 SQLite 文件、artifact owner 文件、原始实验材料及外部 execution 文件分别按实际逻辑字节计费。
  catalog 与参数 payload 列为诊断，但已包含在存储材料中，不重复加入同一存储副本。
- Agentd 的发送/接收字节与 RPC 尝试，以及训练/诊断 pipe 的实际字节均保留；不声称它们是内核 wire byte 或跨机器流量。
- host 与训练进程各自观测 HWM 后求和是显式代理；不是同时峰值，也不是 RSS×时间积分。
  host 在报告构造/序列化前、worker 在最终响应序列化前采样；后续尾部可能有更高峰值，未取得 exit rusage。
- 缺失的 HWM 传播为 `null`，相应代理总分不能计算；八个固定候选里有缺测就不能只筛剩余候选选 oracle。
- 独占通信时间保持 `null`，无需从总 wall 减法猜测。总 wall 已含通信，不能为它伪造额外零成本。

存储 byte-time、同时进程 RSS byte-time、父协调器完整簿记/最终报告写入时间仍未完整观测。
因此完整成本门明确返回 **`NoChange`**；测得的代理收益不能改写为完整成本胜出。
实验没有执行 Rust budget proposal bridge，也不授予自主结构调整/发布权。

## 5. 执行与输出

由统一执行者运行仓库认可的 `just test`；本目录自身不调用 Cargo 测试。
设置绝对路径 `MEMORY_CELL_TRAINING_PYTHON` 指向固定 NumPy CPU 环境，
设置 `MEMORY_CELL_V8_LEARNING_RECEIPT_PATH` 指向尚不存在的输出 JSON。
实际 ignored 父测试名为：

```text
actual_memory_cell_prospective_learning_future_combinations_and_retention
```

helper `memory_cell_prospective_tests::support::memory_cell_trial_child` 只由父测试启动，名称不含 `actual_`。
结果旁的 `.artifacts` 目录与结果必须一并保留。移机后评分器按相对 artifact 路径查找材料，不跟随配置里的原始绝对输出目录。

```bash
python -I -B qualification/memory-cell-v8/learning/score.py \
  /absolute/output/prospective-learning.json \
  /absolute/output/prospective-score.json

python -m unittest discover -s qualification/memory-cell-v8/learning -p '*_tests.py'
```

评分必须使用记录所绑定的同一源码 checkout。输出创建后不可覆盖。
完整有效的负结果/`NoChange` 返回退出码 0；缺失 arm、哈希不一致或无法重建因果证据返回非零并写明原因。
统计显著性、总体校准、参数压缩、开放领域泛化和通用记忆涌现都不从这份试验推导。

## 6. 可分开审查的实现阶段

1. 新 trace/分区算法、独立 V3 原生读取与拒绝测试；保留 V2 加载约束。
2. 新 worker 与实际参数训练；既有 owner/bundle 增加 source-cut 绑定。
3. 新 OS-process prospective harness、真实 direct-owner 参照与生命周期证据。
4. 原始字节/来源/参数审计、成本比较和相应攻击/负例测试。

仓库单模块均保持有界；这些阶段可以继续按调用依赖拆为小提交。
