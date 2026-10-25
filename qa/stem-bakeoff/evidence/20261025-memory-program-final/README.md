# Hepta 可训练 memory cell：执行结果、验收状态与剩余条件

## 当前结论

**八项完整 blocker 的关闭数仍为 0/8，生产接受保持 false。** 这次工作已从独立研究脚本推进到真实 Agentd、`NeuronModelPort`、`NeuronRuntime::tick_shadow` 和持久化恢复路径；受控原生路径已有独立 CI 成功证据。长期参数质量、未来任务优势、同预算分裂、学习边与自治生长、完整分布式容错和净压缩仍没有达到用户要求的关闭条件。

这份状态不把“接口完成”“测试通过”“参数确实参与回答”和“未来任务更好”合为同一个判断。失败实验、未执行请求、缺失的成本维度和零分母都保留。旧的冻结报告与原始产物不会因本次工程修复而被改写。

最新实现提交为 [`a47190bb84714cb1262fcd85ebb723081fdb0581`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a47190bb84714cb1262fcd85ebb723081fdb0581)，[PR #3833](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3833)。前序原生路径精确提交 `33c741cb…` 的独立 [CI 40149732280](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40149732280) 已成功，完整原始 ZIP 与两份独立审计见[不可变 CI 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/25b553f3feec0e99ef2f049822e9f1842b41f97c/qa/stem-bakeoff/evidence/20261025-native-final-ci/README.md)。后续首次建库修复的[完整红绿证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7bd4641572b73e75ac004d0fb8da3f886d399d3d/qa/stem-bakeoff/evidence/20261025-native-bootstrap-recovery/README.md)独立保留。

### 最新提交的独立资格

本次最终源码的完整原 ZIP、运行回执、三组审计及方法已发布到[不可变 a471 CI 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/62a19747d5669b2f66799e29c7858366cefcab26/qa/stem-bakeoff/evidence/20261025-native-bootstrap-ci/README.md)，见 [PR #3838](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3838)。

`a47190bb…` 的 [CI 40152367005](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40152367005)、job `121046374239` 已完成并成功。独立一般审计 60/60 通过：实际 653/653 个测试通过、13 skipped，测试阶段 91.982 秒；345 份执行源码前后保持 clean a471；最后的 patch、stat、worktree status 各为 0 B。新训练 96 步，五个真实模型子进程完成四次 decoder query、两次显式 feature forward。完整原 ZIP 为 62,069,755 B，摘要与 GitHub artifact API 一致，5,745 个文件／104,219,945 B 已逐文件核对。

新增崩溃恢复的独立专项审计 90/90 通过：两个 case 各实际执行一次，无 retry；四个 child 均自行记录 `umask=0022`，writer 退出 73、恢复 child 退出 0；完整 cut 一致，随后新写入的 cut 推进，原 DB/WAL/SHM 字节、captured identity/time/mode 前后相同且记录为 `0600`。权限依据 runner 当时的 JSON 快照与实际文件字节，未将 ZIP 解包权限当作原机权限。

本次 v2 完整独立审计 598/598 通过，包括 345 个源码 pin、57 个原 ZIP 成员以及 196 项绑定、Q24 运算、frame 和拒绝路径比较。新 checkpoint 为 `46ef708f9df4713caf0b5e650544e1127c9d9c9580eb2174be9270e5a8147bc9`，使用本次实际输出重算；未拿前一次 CI 的数值代替。三个审计均为只读计算，没有新增训练、模型读取或 SQLite 打开。这些结果关闭了本次受控原生执行与首次建库权限修复的窄工程资格，八项完整研究／生产门槛仍按下表保留。

## 八项验收表

| Blocker | 已有可复核结果 | 完整关闭仍缺什么 | 状态 |
| --- | --- | --- | --- |
| 长期纠正与保留准确性 | 三个 seed、每组六轮冻结事件流；共 5,184 次参数更新、558 条原始解码；来源层 72/72 正确，脏版本准入 204 次均在模型前拒绝 | 三组均未达到预注册联合质量门槛；需要自然长期流上的稳定保留、纠正和任务成功 | 未关闭，质量失败 |
| 真实来源与查询绑定 | 原生来源写入、typed query、durable nonce、参数身份、调用前后和交付时复核已跑通；首次建库崩溃恢复已有红绿对照 | 真实外部来源当前授权、明确 run/subject 的生产 Objective/NDU context、来源访问边界 | 未关闭，受控工程资格已通过 |
| 未来任务优于强检索 | 历史工作流语料、真实任务输入、冻结 prospective 窗口和排除记录已留存 | 独立未来任务组为零；完整强检索加工具执行器尚未在相同条件下比较 | 未关闭，证据不足 |
| 相同总预算下的分裂收益 | 四个参数方案实际运行 416 次更新，解码、拒绝、未执行请求与参数量分别计价 | 单 cell 容量仅其他组一半；实际全成本未匹配；数据分裂没有胜出；缺强检索及多 seed 的共同预算比较 | 未关闭，未观察到收益 |
| 学习连边与自治生长 | 同一组 cell 完成无边、固定、随机、学习边等对照；真实 owner 上执行 split、merge、两次 rollback | 学习边 1/6，未胜固定／随机边；生命周期次序预设，尚无效用驱动自治策略 | 未关闭，机制与收益分开 |
| 多物理节点与数据本地性 | 两个独立 hosted runner 实际迁移 adapter，目标首读 3/3，冷读 32/32；撤回和重放不增加回调 | 尚无物理独立证明、跨主机在线 authority/quorum、有效来源远程读取正例、分区恢复和 authority 故障切换 | 未关闭，已超出单机但未完成分布式资格 |
| 净压缩和规模成本 | base、adapter、来源、运行目录、进程、通信和短负载已有实测；原生 CI 全目录保留 | 尚未达到相同支持质量，完整系统成本和持续负载仍不完整；不能只报 adapter 大小 | 未关闭，没有净压缩结论 |
| 原生生产集成 | v1 真实控制 socket、v2 真实 tick/shadow/journal/witness 在 33c 与 a471 的独立 CI 均成功；各自最终 diff/stat/status 实际为空 | 真实生产 context/owner 接线、默认 daemon 与 InferenceControl、校准、生产验收仍缺 | 未关闭，原生受控路径已通过 |

表中“未关闭”针对完整研究／生产目标。较窄的工程子项已经取得真实进展，不应把它们抹掉；同样不能用这些进展覆盖负面质量结果。前六个研究活动的冻结原始记录和方法见[前序综合报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f92ddcacbe21267514f5040c1df6c380a96f0643/qa/stem-bakeoff/evidence/20261025-memory-program-status/README.md)。

## 一、这次真正修通了什么

### 原生参数读取和来源围栏

v1 经实际 Agentd 控制 socket、`NeuronModelPort` 和 Python worker 返回参数生成文本。v2 经 `AgentdNativeMemoryCell::shadow_owner`、`NeuronRuntime::tick_shadow`、完整 tick/source/query/runtime 绑定、journal/witness 和 delivery。两条路径都使用真实预训练小模型及 adapter。关闭 adapter 和打乱参数是 v1 冻结配方的独立进程对照；v2 复用同一个 checkpoint，以新的 worker 执行一次真实 tick 路径，没有另跑一组 v2 controls。

原生类型契约已经有 `Semantic`／`Procedural` 两个 role，以及 `role + entity + relation` 的 typed key。读请求的模型问题由该 key 的 `question()` 在 owner 侧确定性生成，未知注册 key 被拒绝；来源文档里的 value 不复制到读 prompt。这已绑定受支持的结构化问题，尚不能推导出自由自然语言到 key 的解析能力，也没有证明一个完整程序执行策略可由该 role 标签获得。[类型与问题构造](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a47190bb84714cb1262fcd85ebb723081fdb0581/codex-rs/hepta-memory/src/memory_cell_types.rs)、[实际原生准入](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a47190bb84714cb1262fcd85ebb723081fdb0581/codex-rs/hepta-agentd/src/native_memory.rs)

在 `33c741cb…` 的独立 CI 中，新下载固定 base，按原冻结配方新训练 96 步；共五个有真实 PID、父进程和退出回执的模型子进程，完成四次 decoder query、两次显式 feature forward。v1 和 v2 均输出原始 `order`，token IDs 为 `[2559, 2]`，各 1/1；关闭 adapter 与打乱参数各 0/1。所有 arm 读取同一已见开发案例，不能作为四个独立任务或未来任务成绩。

v1 来源实际经历 revision 1→2→3 的写入、纠正与撤回；未知 key、错误角色、伪造 receipt、nonce replay、撤回 authority、纠正后的缓存、旧 adapter 和撤回来源共八类拒绝均保留。v2 两次同进程 Recover 后，先成功交付，再实际 tombstone；后续交付精确以当前来源 revision/typed identity 失效拒绝，writer authority 仍有效，模型回调保持一次。

完整独立审计不仅比较报告布尔值：它从实际问题重算 512 个整数特征与所有绑定，从五维实际 drive/prediction 用精确 Q24 运算重算首个 sparse checkpoint，并逐字节重建 384 B frame、520 B journal 和 224 B witness。一般证据检查 60/60、独立 tick/frame 检查 595/595 通过。这些是审计比较数，不是新增实验样本。[原始 CI 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/25b553f3feec0e99ef2f049822e9f1842b41f97c/qa/stem-bakeoff/evidence/20261025-native-final-ci/README.md)

### 首次建库的崩溃恢复修复

发现的缺陷有明确因果链：旧构造函数先连接 SQLite 并创建 WAL/SHM，随后才把主库设为 `0600`。实测 `umask=0022` 时，首次创建后的异常退出留下主库 `0600`、WAL/SHM `0644`，严格恢复因不可满足的文件身份条件拒绝。已经经过安全 materialization 的 recovered generation 本来就以 `0600` 创建，因此控制组通过。

22 行实现修复在 SQLite 连接前，仅对不存在的 Unix 主库使用排他创建并设置 `0600`。既有文件沿用原语义；严格恢复、旧证据和 sidecar 权限检查保持不变。`O_NOFOLLOW` 只描述这次新文件创建，不扩大为对所有旧 legacy 路径的加固保证。

新回归让 writer 在池和围栏仍活着时 `process::exit(73)`，不运行 Rust Drop；完整 cut 先同步到外部记录。另一个新 child 使用严格 exact-cut writable recovery，再新增写入，并在该 recovery child 内 close/reopen 验证。父测试比较原来源 DB/WAL/SHM 的完整字节和元数据，负例也先保存 after 证据再失败。

| 实际阶段 | 结果 | 证明范围 |
| --- | --- | --- |
| 原实现＋冻结新测试 | 两项测试中一项通过、一项失败；失败项自动重试仍失败 | 首代真实 strict recovery 拒绝，recovered generation 控制通过 |
| 只应用 22 行实现修复 | 两项均通过 | 测试字节完全相同；首次和 recovered generation 均能恢复完整 cut 并继续写入 |
| 受影响 `codex-hepta-memory` 全部测试 | 280/280 通过，7 skipped | 两个新增回归包含在完整 crate 运行内 |
| scoped `just fix` | exit 0，19 warnings，无源码改动 | warning 原文保留，不称 warning-free |
| 显式丢弃 keep 返回值＋`just fmt` | exit 0；仅新测试文件机械变化 | 独立 token/literal 审查通过；工具后没有重跑同周期本地测试 |

最终实现提交四个文件、360 行新增。完整包保留七次实际测试尝试的十四个 writer/recovery child 回执，包含首代负例及自动 retry 的原 WAL/SHM。`process::exit` 不等于物理断电；WAL 存在也不证明最后 cut 只能从 WAL 取得；authority 仍是受控 fixture。这些边界在[不可变红绿包](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7bd4641572b73e75ac004d0fb8da3f886d399d3d/qa/stem-bakeoff/evidence/20261025-native-bootstrap-recovery/README.md)中明确保留。

随后的 a471 独立 CI 在最终 333 行测试源码上再次验证两代恢复，属于新的执行证据。其 41 个原始 crash-case 文件、3,477,006 B 完整保留；这四个新增 child 也没有混算为十四个本地 child 的重新身份或新的模型任务。

## 二、为什么参数质量门槛仍未过

冻结事件流要求同一来源的两种问法都正确，每轮当前项目及保留面板达到 90%，纠正项全部正确。三个 seed 的结果如下。

| Seed | 六轮正确来源数 | 最后保留 | 纠正全对 | 联合门槛 |
| --- | --- | ---: | --- | --- |
| 24019 | 7/8、6/9、4/10、7/10、1/10、5/10 | 3/8 | 否 | 失败 |
| 24023 | 8/8、9/9、10/10、10/10、10/10、8/10 | 6/8 | 是 | 失败 |
| 24029 | 8/8、9/9、10/10、10/10、7/10、2/10 | 1/8 | 是 | 失败 |

这是相关合成任务流的 fresh-base replay 后保留结果，不是三个独立自然领域，也不是单 adapter 持续训练的纯遗忘率。九次被后续事件取代的后台训练和十八次干净发布都计入总更新成本。来源 overlay 的 72/72、冲突和撤回准入成功不能计入参数召回正确率。旧参数不再准入也不等于物理擦除。[长期冻结证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/de196b47a509ccc4cc5f57844c1752271d2cd20d/qa/stem-bakeoff/evidence/20261024-memory-longitudinal/README.md)

真实工作流实验覆盖固定提交下的 75 个 YAML workflow，455 个命令候选中纳入 128 条来源。四个历史任务已被开发者见过，只能作为开发材料。神经各方案没有产生可准入修复：每组 0 个动作、0 次新的原始任务 gate 执行、0/4 个已验证成功。只实际重建执行到一个原始 lint gate，其修复前后均失败；其后的 76 个语义测试没有运行。

冻结 prospective 窗口里的 13 条失败运行，12 条属于注册前已知的同一根因，另一条诊断不足，因此合格独立未来任务组为 **0**、预测为 **0**、accuracy 为 **null**。当前 BM25 仅是原始命令提案器，没有完整强检索、reasoner 和工具循环，输入条件也未完全一致。现有数据不能支持“未来任务优于强检索”。[真实领域、预算和 future 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bfe77f5cdd04935d8bbfba9199a725ffc48b69e7/qa/memory-budget-20261024/README.md)

## 三、分裂、连边与自治：先保留真实负结果

| 参数方案 | 活动参数值 | 16 个问题精确正确 | 有 lineage 支持且精确正确 |
| --- | ---: | ---: | ---: |
| 单 cell 继续训练 | 230,400 | 3/16 | 1/16 |
| 扩容 | 460,800 | 3/16 | 1/16 |
| 数据分裂 | 460,800 | 1/16 | 1/16 |
| 随机分裂 | 460,800 | 2/16 | 1/16 |

共享父版本仅训练一次、32 步；每组另执行 96 步，split 分为两个子 cell 各 48 步，实际总计 416 更新。256 个计划请求中，210 次进入 decoder、38 次因冻结输入契约拒绝、8 次未执行。两个 split 在注册的库存保护条件下停止，不能称为跑满 600 秒；共同预算上限也不等于相同实际成本。代码版本与原错误仍须回读来源，现有小模型尚未证明可迁移的诊断／操作策略。[预算证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bfe77f5cdd04935d8bbfba9199a725ffc48b69e7/qa/memory-budget-20261024/README.md)

同一组三个 checkpoint 的连边对照，学习边仅 1/6，固定边和随机边也为 1/6，直接参数读取 2/6，精确来源读取 6/6。学习边的七次模型调用少于固定／随机边，但正确率未改善，不能据此宣布效用优势。无边组只能给 hint 而目标要求 color，是执行路径消融，不是强独立基线。

真实 owner 上执行过 split、merge 和两次 rollback，产生十四个版本；split 复制已训练 checkpoint，merge 重用联合 checkpoint。操作次序预设，没有根据未知任务效用、容量和干扰自主触发。撤回后旧参数／策略／拓扑均被拒绝，但干净重建模型仍把 `cool` 回答为 `warm`。[连边与生命周期证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/654b3b5b22d62d98704f841832a6fd9430be643a/qa/stem-bakeoff/evidence/20261024-memory-edge-lifecycle/README.md)

## 四、跨节点和压缩的实际边界

两个不同 runner 名称、不同 boot digest 的 hosted 环境已实际迁移同一 adapter；源端 3/3、关闭与打乱 adapter 均 0/3，目标 fresh-process 首读 3/3，随后 32 次冷请求 32/32。撤回后及重启重放旧 cut 后，目标 callback 计数都维持 33。174 B 远程证据确实送达，但到达时来源已撤回，所以当前支持资格被拒绝，尚无有效来源远程读取正例。

该实验是单 signer 的异步 artifact relay。不同执行环境尚不证明不同物理硬件，也没有组成跨主机在线 mTLS／多数派 authority、分区恢复与 authority 故障切换。loopback 上另有本地分布式机制测试，不能移作跨主机完整资格。[完整 hosted relay 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/77817ec5479cec19e14a5946799fe5998168efc8/qa/stem-bakeoff/evidence/20261024-memory-hosted-relay/README.md)

32 次冷请求是 concurrency=1 的短 closed-loop 负载，总 wall 222.768862488 秒；p50 6.956435145 秒，p95 7.011685334 秒，吞吐 0.143646646 请求／秒。三事实重复请求不能充作 32 个未来任务，也不代表持续服务 SLA。

最新原生 `a471` CI 的实际成本如下。较早 `33c` CI 的独立账本仍完整保留，没有把其训练成本转移到本次复用名下。

| 项目 | 实际值与边界 |
| --- | --- |
| 六个 base 文件 | 271,170,520 B；有 acquisition 和 worker pins，CI 原目录不在 ZIP |
| adapter | 460,800 参数；tensor 1,843,200 B，safetensors 1,858,776 B |
| 每个推理 worker 参数驻留 | 539,903,232 B，不含 allocator |
| v1／v2 worker peak RSS | 1,142,935,552／1,143,173,120 B |
| 完整 v1 run／v2 run | 93,468,377／6,092,954 B；v1 包含真实 private-home 插件资源 |
| 完整 artifact 普通文件 | 104,219,945 B，5,745 文件；包括 41 个新 crash-case 文件，不是完整仓库及 build cache |
| 两个模型资格 driver 总 wall | 75.077134940 s；内部训练／下载时间嵌套，不能重复相加 |
| 完整 job wall | 1,737 s，含安装、编译、测试、lint、上传；API 精度 1 s |

这些实测仍不构成净压缩：支持质量尚未匹配，来源、历史版本、router、authority、恢复状态、runtime、网络、瞬时存储与持续负载还需共同计价，并区分共享与每个 cell 独占的部分。ZIP 压缩率是证据档案的编码效果，不能充作 memory system 的收益。不同 runner 上两次 wall 的变化也不是本次权限修复的性能实验。[最新 CI 与完整账本](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/62a19747d5669b2f66799e29c7858366cefcab26/qa/stem-bakeoff/evidence/20261025-native-bootstrap-ci/README.md)、[此前独立账本](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/25b553f3feec0e99ef2f049822e9f1842b41f97c/qa/stem-bakeoff/evidence/20261025-native-final-ci/README.md)

## 五、剩余工作应按什么条件继续

### 先补齐真实生产上下文

仓库已存在真实 `ObjectiveRuntimeHost`、签名 `ObjectiveStart` 和 `DurableRunStartJournal`；系统允许多个 active run，context bridge 必须明确指定 run/subject，并复核当前签名、issuer/key epoch、generation/fence、expiry 和生命周期。已有 `NduAuthenticatedOwnerV1` 与 FinalUseAuthority 原语，但当前 Agentd 尚未挂载真实 NDU owner；重新读取静态 descriptor/journal 不提供当前授权和撤回新鲜度。

仍未实施的三个工程阶段应分别完成：第一，在 Objective host 内提供按明确 `run_id` 的 checked read，复用当前授权复核，并检查 run 的 phase、revision 和 deadline；第二，在 Agentd 挂载真实 NDU owner，由 owner 生成包含 journal/selection 单调版本、policy 和当前 authority/feed 的不透明读取证明；第三，等真实 owners 就绪后通过生产工厂创建 cell，增加独立 shadow 路由，并将明确 run 与版本化证明绑定到结果和恢复域。当前安装工厂受 `qualification-cognitive-write` 门控，默认 daemon 尚未安装，v1 ingress 也没有 `run_id`。这些属于仍可继续编码的缺口，不能全部归为外部资源不足。

实际启用需要真实 owner 或受认证 IPC capability、策略和 principal、当前 frontier/fence、run/subject 授权关系；provider 在 callback 前后及交付时做一致性复核。AuthBus `key_epoch`、Objective 签名 body 的 `authority_epoch`、FinalUse epoch/revocation revision 以及 host/model generation 各有语义，不可直接等同。内容 A→B→A 需要单调选择版本与有期限的当前授权/feed 证明，仅比较内容摘要不足；同进程 `Instant` 恢复也不证明跨进程时钟连续性。完成 provider 后仍需默认 daemon、真实 InferenceControl 与独立产品资格。当前 shadow 始终 abstain、deny-all、calibration=null，生产校准仍需另行证明。

以上路径与缺口由当前 a471 提交的 27 份源码、四组引用搜索独立复核，原始源码及审查都保留在 [production-context-a471.README.md](production-context-a471.README.md) 对应的归档中；该静态审查没有新增运行资格。

### 再建立可以公平比较的真实任务能力

先在未充作最终评测的开发数据上修复参数学习和动作可执行性；优先学习项目调试的可迁移诊断、工具选择和操作策略，精确版本与原错误回读来源。之后冻结新的训练配方、来源流、阈值、成本、seed、独立根因组和最终评测窗口。

所有方案必须收到相同输入，使用相同执行器和工具权限，按真实任务 gate 判成功。强检索组应包含合格 retriever/reranker、相同 reasoner 和工具循环；继续训练、扩容、检索、数据分裂、随机分裂分别报告固定总容量和计价增长。参数、训练、路由、证据读取、缓存和运行时成本进入同一账本。已看过的最终评测不能继续当作盲测调参。

### 分裂和连边必须以可复现的效用触发

候选分群可以来自任务分布、梯度干扰和错误结构，但真正采用 split／merge／rollback 应取决于冻结开发目标下的收益、保留与成本。使用同一 cell 集合比较无边、固定边、随机边和学习边，并把路由与额外回调计价；最终独立任务组只使用冻结策略。增加参数或更换来源读法都要作为独立变量记录，不能全部归因于“细胞分裂”。

### 最后验证真实部署的 failure model

需要可访问的独立在线节点和真实 source/authority 服务，明确物理身份、placement、访问边界、撤回传播时限、分区时准入规则与 authority 故障模型。届时再执行当前有效证据远程读取、分区／恢复、authority 故障与持续负载。缺少这些运行条件时，fixture、单 signer relay 或两个 hosted job 都不能代替最终验收。

这些条件分别是仍缺的实现、独立质量证据和部署前提。继续工程开发可以改善其中一部分；“同预算优于强检索”和“自发生长提高收益”则必须由未见任务结果决定，不能预先保证为真。
