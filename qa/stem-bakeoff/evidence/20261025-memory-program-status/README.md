# Hepta 可训练 memory cell：八项 blocker 综合报告草稿

**当前完整关闭数仍为 0/8，`production_accepted=false`。** 已有真实参数训练、长期事件流、分裂/连边对照、实际生命周期操作，以及两个独立 hosted runner 的迁移与撤回证据；目前的数据没有证明长期可靠记忆、同预算分裂优势、学习边优势、未来任务优势或净压缩。

这轮已实际跑通两个不同入口：**v1 经 Agentd 真实控制 socket → `NeuronModelPort` → Python worker；v2 经真实 source owner → `NeuronRuntime::tick_shadow` → Python v2 → journal/witness → delivery。** 两次原生输出均为原始 `order`，同一已暴露历史样本各1/1；关闭 adapter 与打乱参数均0/1。v2使用独立标明的 controlled qualification provider，始终 abstain、deny all，没有校准和生产接受。

执行身份严格分开：原固定96更新在 `8a47cdd26574a85cd314fabce65cc395dbe316a8` 完成，随后 source-owner 恢复失败；显式续跑和v2成功于 [PR3823固定源码](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/3a1431c5879d084bf49b9df67f9792af8f3acbc7)，新增训练、下载均为0。整个本地原生活动共有1个训练进程、4个推理进程，96次训练forward、4个decoder query、2个显式feature forward；这些计数不相互替代。失败成本和全部原始目录保留。

六crate attempt006实际651/651通过、13skip；close修复后的Agentd attempt007另有224/224通过、6skip。两次byte/mode桥接、clean-head example构建和真实模型输出分别留证，不能把旧测试回填成所有新head的测试。**最终格式化提交的独立完整CI资格仍待实际receipt；本地成功head始终记为3a143，训练head记为8a47。** 全部八项完整研究门槛仍为false。

长期、连边、预算和 hosted relay 的下列数值来自已发表的不可变证据。此次整理没有重跑这些模型或改变冻结任务流。新增本地资格记录的原始日志/receipt 在配套 `evidence-index.json` 中按完整 SHA-256 固定；尚未观察到远端归档的记录不编造 GitHub 链接。

## 1. 验收表

| Blocker | 已有实际进展 | 尚不满足的关闭条件 | 完整关闭 |
|---|---|---|---|
| 长期纠正与保留准确性 | 三个预注册 seed、每 seed 六轮、24 次来源事件；共 5,184 次真实更新、558 条原始解码输出；即时来源层与参数读取分开计数 | 三个 seed 都未通过逐轮 ≥90%、保留 ≥90%、纠正全对的联合门槛；自然长期任务成功仍未证明 | 否 |
| 真实来源与查询绑定 | 原生 `CognitiveStore`／durable writer、typed query、durable nonce、参数身份、调用前后及交付时来源复核已有实现；受控原生v1/v2已通过真实模型读取与纠正/撤回准入资格 | 真实外部来源授权、生产资格仍未闭合；生产 NDU owner 尚未接入当前 Agentd，上下文不能用固定摘要替代 | 否 |
| 未来任务优于强检索 | 历史工作流语料、原始任务输入、实际 action admission、冻结 prospective 窗口与排除记录已保留 | 独立未来任务组为零；现有 BM25 提案器并非完整强 RAG/修复 agent；没有相同上下文下的未来任务优势 | 否 |
| 相同总预算下的分裂收益 | 继续训练、扩容、数据分裂、随机分裂共 416 次真实更新；实际成本、未执行请求、输入拒绝和参数数量有账本 | 共同上限不等于相同实际总成本；single 容量仅为其他三组一半；数据分裂没有胜出；缺多 seed 与强检索的完整共同预算比较 | 否 |
| 学习连边与自治生长 | 同一组 cell 的无边、固定边、随机边、学习边、能力路由、直接参数和来源读取对照；真实 owner 上执行 split、merge、rollback | 学习边仅 1/6，直接参数 2/6、精确来源 6/6；生命周期次序预设，未由任务效用和压力自主触发 | 否 |
| 多物理节点与数据本地性 | 两个独立 hosted runner 实际迁移同一 adapter；目标首次读取 3/3，32 次冷请求全对；撤回和重启重放拒绝均无新增模型回调 | 无物理硬件独立证明；本次为单 signer 的异步 artifact relay，无跨主机在线 mTLS／quorum、authority 故障切换和完整分区恢复 | 否 |
| 净压缩和规模成本 | base、adapter、来源、checkpoint、进程、通信和部分 runtime 成本已有清单；32 次冷请求延迟和吞吐有实测 | 没有相同支持质量下的完整成本优势；依赖与瞬时存储成本不完整；短串行重复请求不足以证明持续规模能力 | 否 |
| 原生生产集成 | 已提交真实 Agentd v1 控制路径、`NeuronRuntime::tick_shadow`、Rust/Python 完整绑定与独立 pretrained v2 探针；六crate651/651、后续Agentd224/224和两example构建通过；原96更新复用，真实v1/v2读取与来源围栏均通过 | 最终格式化提交独立CI资格、生产 Objective/NDU bridge、默认 daemon/InferenceControl 接线、校准和生产接受仍开放 | 否 |

上述“否”针对用户给定的完整验收条件，不否认较窄的工程机制已经执行成功。
所有来源和证据链接均固定到具体提交或运行，不依赖会继续移动的分支名。

## 2. 长期参数记忆：联合门槛仍然失败

预注册活动固定了三种种子、六轮事件、训练配方和成功门槛，质量失败后仍跑完原定事件流。
每轮要求同一来源的两种问法都回答正确；保留面板也必须达到 90%，当前纠正项必须全部准确。
最终结果如下。

| Seed | 各轮来源正确数（两种问法同时正确） | 最后一轮保留 | 所有纠正全对 | 联合门槛 |
|---|---|---:|---|---|
| 24019 | 7/8、6/9、4/10、7/10、1/10、5/10 | 3/8 | 否 | 失败 |
| 24023 | 8/8、9/9、10/10、10/10、10/10、8/10 | 6/8 | 是 | 失败 |
| 24029 | 8/8、9/9、10/10、10/10、7/10、2/10 | 1/8 | 是 | 失败 |

这里的“保留”是在 fresh-base replay 后，相邻两轮仍保有相同 key/value 的项目是否读对。
它衡量的是服务刷新后的保留表现，不能解释成同一 adapter 连续训练过程的纯遗忘率。
三组都是相关的合成颜色任务流，也不能算三组独立自然任务。

来源层的结果明显不同：72/72 次即时 overlay 响应正确，其中 63 次 answered、3 次 conflict、6 次 revoked；204 次 dirty 参数准入均在模型前拒绝。
九个已被后续事件取代的后台训练确实各运行 64 步，另有十八次清洁发布各运行 256 步，总更新数包含这些没有成为活动版本的工作。
旧 checkpoint 保留作审计，不再准入并不等于物理擦除或精确机器遗忘。

这组结果说明来源状态机、后台发布和参数能力必须分别验收。
即时来源读取可以正确，参数模型仍可能在之后退化；不应把 overlay 的 72/72 混进参数正确率。

来源：[长期冻结活动与完整证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/de196b47a509ccc4cc5f57844c1752271d2cd20d/qa/stem-bakeoff/evidence/20261024-memory-longitudinal/README.md)。

## 3. 真实领域与未来任务：有开发实验，尚无未来优势

语料覆盖固定提交下全部 75 个 YAML workflow，抽出 455 个命令候选，按来源哈希与不变 token 契约选入 128 条来源记录。
四个自然任务分别对应 Clippy 安装、Ruff F401/E731、Cargo.lock 消歧，以及 codec job 全部跳过仍显示成功。
整理者此前见过其公开修复，所以这四个任务是已暴露的历史开发样本。

冻结的 prospective 窗口内观察到 13 条失败运行，其中 12 条属于注册前已知的同一个 `runner.temp` 表达式错误，另一个没有足够诊断来确认根因。
最终没有合格的独立未来任务组：**0 个组、0 次预测、accuracy=null**。
零分母不应改写为 0% 或 100%，也不能延长窗口后把已观察任务包装成盲测。

来源 BM25 使用完整语料和路径重合信息，但它只是原始命令提案器，没有完整 reasoner、reranker 和修复工具循环，因此尚不足以充当强检索基线。
A 使用含部分线索和路径的原始输入，B 使用错误文本，两个输入条件也并不完全一致。
唯一复原执行到的原始 lint gate 在修复前后均失败，76 个后续语义测试并未运行。
神经四组对四项自然任务均没有产生可准入修复：0 个动作、0 次新的原始任务 gate 执行、每组 0/4 个已验证成功。
这不等于四个完整原始环境都已经执行了一遍。

来源：[真实工作流预算、任务和 prospective 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bfe77f5cdd04935d8bbfba9199a725ffc48b69e7/qa/memory-budget-20261024/README.md)。

## 4. 分裂与增长：先保留已观察到的劣势

| 方案 | 活动 adapter 参数值 | 16 个已知来源问题精确正确 | 有 lineage 支持且精确正确 | 原始解码行 |
|---|---:|---:|---:|---:|
| 单 cell 继续训练 | 230,400 | 3/16 | 1/16 | 54 |
| 扩容 | 460,800 | 3/16 | 1/16 | 54 |
| 数据分裂 | 460,800 | 1/16 | 1/16 | 51 |
| 随机分裂 | 460,800 | 2/16 | 1/16 | 51 |

共享父版本实际训练一次、32 步；每组另执行 96 步，split 分成两个子 cell 各 48 步。
物理执行总数是 416 步。独立部署视图可以把父版本工作分配给每组，但不能把这种费用分配再次当作新增实验。
继续训练组只有一半活动参数，故四组并非全部等容量；三个大容量方案之间可比较容量，single→expanded 则属于增长计价。

总计划 256 次请求中，210 次进入解码器，38 次因输入契约被拒绝，8 次 load 请求未执行。
codec 输入是 442 token，超过冻结的 192-token 上限，保持拒绝，没有事后截断。
两个 split 在注册的 final-inventory 资源保护条件下停止，不能称为跑满了 600 秒预算。
共同资源上限、实际资源消耗和最终任务收益应同时报告；这一轮没有证明分裂收益。

来源同上。其独立 hosted 标准库行为测试为 [run 40101978822](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40101978822)；29/29 测试通过属于预算机制资格，不改变模型的低正确率。

## 5. 学习连边与真实生命周期：机制存在，收益未出现

这一轮对同一组三个 checkpoint 比较各个连边策略，实际执行 1,024 次 decoder 更新、400 次 router 更新和 75 次 decoder 读取。
router 只使用来源 utility 训练，其策略在最终问题前冻结；每次 next-cell 决策在第二次调用前持久化。

| 策略 | 精确答案 | 模型回调 |
|---|---:|---:|
| 无边 | 0/6 | 6 |
| 固定边 | 1/6 | 9 |
| 随机边 | 1/6 | 10 |
| 学习边 | 1/6 | 7 |
| 能力元数据路由 | 1/6 | 12 |
| 直接参数读取 | 2/6 | 6 |
| 精确来源读取 | 6/6 | 0 |

无边组只能输出 hint，而任务要求 color，因此它是执行路径消融，不能充当强独立记忆基线。
学习边使用更少回调并不足以证明效用提升，其正确率没有胜过固定或随机边，也低于直接参数读取。

实际 owner 和 checkpoint 上执行过 split、merge、两次 rollback，总计形成十四个 owner 版本。
split 复制已训练 checkpoint，merge 重用已覆盖全部 hint 的 checkpoint，没有暗中新增训练。
这些操作次序与分区均预设；它们验证了生命周期操作，不是压力驱动的自治生长。
撤回后旧参数、学习策略和旧拓扑三条路径均在模型前拒绝；清洁重建后的实际回答仍把 `cool` 回答成 `warm`。

来源：[连边与生命周期的负面开发结果](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/654b3b5b22d62d98704f841832a6fd9430be643a/qa/stem-bakeoff/evidence/20261024-memory-edge-lifecycle/README.md)。

## 6. 两个 hosted 环境：已经超出单机 loopback，完整分布式门槛仍开放

实际 run 40102776848 使用两个独立 runner，boot digest 和 runner name 不同。
源端对三个训练事实回答 3/3，关闭 adapter 与打乱参数均为 0/3；同一 checkpoint 到达目标端，首次 fresh-process 读取仍是 3/3，随后 32 次串行冷请求全部正确。
主实验有 256 次训练更新、44 条原始解码行、37 个模型子进程凭证。
额外 preflight 的 16 个测试包含 tiny 模型 12 次更新、14 条输出，必须另计；其临时逐调用凭证未上传，不能称为完整成本闭包。

撤回之后，目标端模型回调计数保持 33；重启后重放旧 signed cut 也在模型前拒绝。
源端使用 target/node-B、generation-1 视图两次拒绝 source/node-A 调用，计数保持 3；未执行额外的 source/node-A、generation-0 重放，不把它写成已通过。
174 字节远程证据确实传输，但到达时来源已撤回，因此当前支持资格被拒绝。
当前有效来源远程证据的正例仍没有运行。

这次采用单来源 signer、同一 Actions run 的异步 artifact relay，尚未组合成跨主机在线 mTLS＋多数派 authority。
两个不同执行环境不能替代物理硬件独立证明；源 authority 故障、分区恢复、未送达撤回期间的语义和完整卷回退也没有得到这次实验的证明。

来源：[原始 hosted 执行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40102776848)及[固定提交的完整 relay 证据包](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/77817ec5479cec19e14a5946799fe5998168efc8/qa/stem-bakeoff/evidence/20261024-memory-hosted-relay/README.md)；其中保留六个原始 ZIP、两个作业日志、41 份来源文件和 `audit-run-003/result.json`。独立审计为 952 次比较、零失败、零模型调用；比较次数不是新增实验样本。

## 7. 成本：已有分项实测，不能宣称净压缩

Hosted 32 次请求采用 concurrency=1 的串行 closed loop，每次均重新启动 decoder 进程。
总 wall 为 222.768862488 秒，p50（预注册 lower-middle）6.956435145 秒，p95（nearest-rank）7.011685334 秒，吞吐 0.143646646 请求/秒。
它们是三事实、短负载、冷进程的观测值，不是持续服务吞吐或大规模系统 SLA。

主实验 adapter tensor payload 为 1,843,200 字节，完整 safetensors 文件为 1,858,776 字节。
每端六个模型文件均为 271,170,520 字节，加下载元数据后目录分别为 271,171,147 与 271,171,150 字节。
来源、复制的 checkpoint、lineage、权威状态、恢复数据库、router、runtime、原始证据仍须分别计入部署成本。
把保留原始来源且质量不等的参数系统与无损来源压缩直接比容量，无法得出净压缩收益。

工作流原始 JSON 645,305 字节可无损压缩到 lzma 81,720 字节；这只是无损来源编码参照。
参数方案既未提供相同支持质量，完整依赖、历史 acquisition、瞬时存储 byte-time、完整网络开销与 provider 费用也未闭合。
零记录的维度仍是未测量，不能作为零成本。

本轮原生实测还补充了更完整的参数与存储边界：base有134,515,008个参数，adapter有460,800个，总134,975,808个；实际CPU float32参数resident为539,903,232字节，与序列化tensor header独立求和一致。两次原生worker的peak RSS分别为1,131,851,776和1,131,753,472字节；参数大小不包含allocator，RSS单独记录。

完整续跑目录实际有5,611个普通文件、93,394,724字节，其中包含App Server privatehome安装的插件资源；v2目录57文件、6,081,243字节，原失败目录83文件、4,954,052字节。共享base另占271,170,520字节，编译产物和完整依赖也必须另计。这些是实际普通文件内容大小，不含所有文件系统开销；不能只用1.84MB adapter宣称净压缩。

## 8. 原生集成：受控真实运行通过，生产资格仍开放

### 已实际完成的实现与审查

`NeuronRuntime::tick_shadow` 与既有 sparse journal/witness 共享真实持久化事务，但使用独立的无校准配置和输出类型，始终 abstain、deny all。原有 calibrated `tick` 拒绝该 profile。完整 tick 摘要与 source/query 摘要分开，Python v2 独立重算规范编码及三者联合绑定；v1 的闭合 schema 和来源绑定仍保留。

`AgentdNativeMemoryCell::shadow_owner` 组合真实 source writer、nonce、decoder、dispatch semaphore、取消状态、独立 witness 和显式 context provider。稳定 namespace 绑定 owner、logical cell、subject、来源切面及模型/profile；已完成的 result 只能通过不可变 getter 读取，交付时再次核对 source 与 context。这里 SQLite 来源提交和 sparse journal 不是一个 ACID 事务，失败后显式恢复仍是重要边界。

新增 pretrained shadow example 已实际复用 v1 的 base/adapter/lineage/source document，额外训练为零。v1 observation width 为 4，sparse kernel 要求至少 5，因此单独注册 width 5 的 shadow profile并保留旧配置，不改变 decoder 训练配方。受控 Objective/NDU 文件明确标为 qualification provider，不冒充生产 owner；两次 Recover 共享一个真实 monotonic clock 原点，只覆盖同进程恢复。

探针已实际核对：一次 Python v2 callback、原始文本/tokens、完整 tick/source/query/runtime 绑定、journal/witness anchors；相同 nonce 实际以 `Source::Replay` 拒绝；再次 Recover 后先成功 delivery，再真实 tombstone，随后以来源 head 变化拒绝 delivery，且没有新增 callback。独立审查已修正将裸 runtime receipt digest 与完整 model binding digest 混比较的问题。withdrawal content/reason 的同型错误和 v1 helper 重执行入口已在 PR3812 修正，相关六crate测试与两个example构建已通过；随后prepare显式close修复后，通过了独立owner上的完整v1续跑与v2 shadow。v1 run 分支使用标准 arg0 runtime builder，不宣称 Rust worker 线程数与原探针相同；96-update 配方、数据和模型对照没有因此改写。这些是实现资格问题，不是模型质量结果。

来源：[shadow runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3a1431c5879d084bf49b9df67f9792af8f3acbc7/codex-rs/hepta-neuron/src/runtime_shadow.rs)、[owner 与交付复核](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3a1431c5879d084bf49b9df67f9792af8f3acbc7/codex-rs/hepta-agentd/src/native_memory_tick_owner.rs)、[完整绑定](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3a1431c5879d084bf49b9df67f9792af8f3acbc7/scripts/memory_cell_native/native_tick_contract.py)、[独立 pretrained probe](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3a1431c5879d084bf49b9df67f9792af8f3acbc7/scripts/memory_cell_native/shadow/README.md)。

### 已核验的运行结果与失败

| 资格记录 | 实际结果 | 模型阶段 |
|---|---|---|
| hosted `c11` / run 40102780899 | 510 run、506 pass、4 fail、13 skip | 未运行，0 次 pretrained native 调用 |
| hosted `f214` / run 40103922428 | 510 run、507 pass、3 fail、13 skip；blocked-stdin fixture 修复已通过 | 未运行，0 次 |
| 本地 repair-tests-001 | 635 run、621 pass、14 fail、13 skip；源码前后 9,685 文件哈希一致 | 未运行，0 次 |
| 本地 shadow-tests-002/003/004 | 编译阶段失败；记录缓存失效边界、assert 导入与 trait 导入问题，不能充作已执行测试 | 未运行，0 次 |
| 本地 shadow-tests-005 | 651 run、650 pass、1 fail、13 skip；旧十四项失败全部通过，新撤回 fixture 仍失败 | 未运行，0 次 |
| 本地 shadow-tests-006 | 651 run、651 pass、0 fail、13 skip；测试54.325秒/总96.520秒，源码不变 | 0 次模型 |
| clean 8a47cdd example build | 两个实际 example 构建成功，2.782秒，已保留binary SHA与源码前后身份 | 0 次模型 |
| native-model-001（clean 8a47cdd） | 实际训练96更新完成；daemon-probe 在 source owner 恢复时报 immutable file identity 失败，0.032秒退出 | 训练进程1；native/control decoder0、feature0、shadow0 |
| prepare-close后Agentd attempt007 | 224 run、224 pass、0 fail、6 skip；测试45.997秒/总64.449秒，源码不变 | 0次模型 |
| clean 3a1431c example build002 | 两个example重新构建成功，2.585秒，精确新binary SHA保留 | 0次模型 |
| native-resume-001 | 新独立owner上v1工程门槛通过；原输入冻结不变 | 新训练0/下载0；decoder3、feature1、模型子进程3 |
| native-shadow-001 | 真实tick_shadow、两次Recover、replay与tombstone交付围栏通过 | 新训练0/下载0；decoder1、feature1、模型子进程1 |
| 独立 Python wire tests | 4/4 通过，0 skip；仅标准库，验证 v1/v2 绑定边界及篡改拒绝 | 0 次模型、0 次训练 |

native-model-001 的原始训练 receipt 记录 7,296 个输入 token、192 个监督 token、460,800 个可训练参数；参数和梯度各 1,843,200 字节，optimizer tensor 为 3,686,880 字节。原 driver 总 wall 77.564 秒，训练子进程 67.698 秒（训练函数内 58.647 秒），下载 8.559 秒；这些时间范围互相嵌套，不能相加。wrapper 总 wall 为 77.663 秒，源码仍 clean。此次失败及已训练checkpoint完整保留；显式续跑仅接纳这一种模型前失败，实际使用新目录、独立owner，原始输入全库存不变，新增训练与下载均为零。

失败记录和后续修复应继续保留；nextest 对同一失败的两次尝试不是两个独立测试，也不能把 13 个既有 skip 当作成功。已通过的本地测试与源码身份对齐、clean-head构建分别保留。受控真实v1/v2已成功；最终lint/format及其后独立完整提交的CI资格仍另行记录，当前保持pending。

已发表的两次 hosted 失败及原始 ZIP 见[不可变 native CI evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8a47cdd26574a85cd314fabce65cc395dbe316a8/qa/stem-bakeoff/evidence/20261024-native-ci-repair/README.md)。初次本地635项失败已随[固定提交证据包](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8a47cdd26574a85cd314fabce65cc395dbe316a8/qa/stem-bakeoff/evidence/20261025-native-source-qualification-initial/README.md)发布；随后002–005失败已发布在[PR3813固定证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d765b999c0b39b7e0a481d90f5b9ff12dd9eb5dc/qa/stem-bakeoff/evidence/20261025-native-qualification-failures/README.md)；native-model-001已原样发布到[固定故障证据目录](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/9f511ed8fd13aab7c6ee56709d46c61a1af05c2c/qa/stem-bakeoff/evidence/20261025-native-predecoder-failure)；其完整archive SHA为`99c1c0e21eaf246812ab20f93ce12db2eac3a5dbf77ac861068b11724dbbcf07`。新增006/007、metadata桥接、两次build、成功v1/v2及两项独立审计的原始路径/hash在 `evidence-index.json` 中；成功run包正在单独封存，不编造尚未核实的发布head。

### 原始输出、参数参与与来源围栏

| 真实读取 | 原始生成（长输出摘要） | 参数精确正确 | 输入/生成token |
|---|---|---:|---:|
| v1 native固定adapter | `order`，token IDs `[2559,2]` | 1/1 | 74/2 |
| research base，实际关闭adapter | `The asymmetric…`（完整原文保留） | 0/1 | 74/16 |
| research shuffled，实际打乱adapter | `The repair for AssertionError…`（完整原文保留） | 0/1 | 74/16 |
| v2 tick_shadow，同一checkpoint | `order`，token IDs `[2559,2]` | 1/1 | 74/2 |

三个v1对照的实际prompt tokens完全相同。原生text与worker原始stdout相等，答案未后处理，推理请求没有source value、facts或检索答案；四个推理进程PID各异。它们支持这个已暴露单样本的参数参与读取，不构成四个独立任务，也没有执行相应真实代码修复。v1来源真实经历revision1→纠正2→撤回3，旧缓存、旧adapter和撤回来源均被拒绝，backend dispatch始终1。

v2仅一次真实callback，先完成两次同进程Recover；同nonce精确拒绝为 `Source::Replay`，第二次Recover后撤回前实际delivery成功，再真实tombstone。随后交付精确拒绝为当前来源revision/typed identity失效，writer authority仍有效，callback保持1。journal/witness均为sequence1、相同checkpoint；撤回前后实际文件hash相同。context provider实际被查询9次，但仍是受控文件provider；v2未走控制socket、未接默认daemon，不证明跨进程clock恢复、独立witness运营信任或物理遗忘。

v1续跑wrapper耗时36.857秒，v2为14.816秒；连同原失败wrapper77.663秒共129.336秒，原训练/下载已在失败成本内计入一次。实际神经worker的模型阶段为3.668/3.505秒，不能代替包含冷启动与Agentd工作的总wall。总体独立审计核对72项原始证据、源码archive、进程、来源、冻结库存与成本；另一审查从实际运行源码archive独立重算完整tick/source/query/runtime/profile/namespace和二进制journal/witness frame，134项校验通过。两项审计均仅用标准库，新增模型调用为0。

### Objective 已有真实生产链，NDU 接入仍缺

实际编译的路径是 `ObjectiveRuntimeHost`：Agentd runtime 按显式 owner profile 打开和安装它；`ObjectiveStart` 经签名 AuthBus 验证、来源/profile 绑定、防重放和 `DurableRunStartJournal` 后进入运行协调器。现有状态机能够复核当前 generation/fence、issuer/key epoch、签名、expiry。系统允许多个 active run，因此新增 context bridge 必须绑定明确 run/subject，不能假定唯一的全局当前 objective。

NDU 已有 `NduAuthenticatedOwnerV1` 原语；它的 append/select/revoke 通过现有 FinalUseAuthority 验证并持久化。但是当前 Agentd 没有安装该真实 owner 的句柄/生产构造路径，`selected_projection_digest` 也不是自动带有当前 authority epoch/fence/revocation frontier、时间和有效期的 snapshot proof。已有 descriptor-loaded journal 快照无法证明持续写入或之后的撤回状态。

因此仍需：真实 NDU owner 或受认证 IPC capability、实际 policy/principal/generation/fence/frontier、与已准入 run/objective/subject 的授权对应关系，以及 owner 生成的当前 snapshot receipt；provider 在 callback 前后和 delivery 前进行版本一致复核。缺失这些输入应拒绝，不能填入随机 digest、source hash 或本地自签资格声明。

即使 context bridge 完成，默认 daemon 安装、实际 `InferenceControl` 路由和 calibrated `SignalReceipt` 仍需独立证明。资格 example 的 controlled provider 不改变这些生产缺口。

来源：[Objective 安装路径](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3a1431c5879d084bf49b9df67f9792af8f3acbc7/codex-rs/hepta-agentd/src/runtime.rs)、[Objective 真实 owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3a1431c5879d084bf49b9df67f9792af8f3acbc7/codex-rs/hepta-agentd/src/objective_runtime.rs)、[NDU 受认证 owner 原语](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3a1431c5879d084bf49b9df67f9792af8f3acbc7/codex-rs/hepta-ndu/src/owner.rs)、[Neuron/InferenceControl 边界](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3a1431c5879d084bf49b9df67f9792af8f3acbc7/codex-rs/hepta-agentd/src/neuron_runtime.rs)。

## 9. 要关闭剩余项，下一步需要的实际条件

| 工作 | 继续做的具体内容 | 关闭依据与资源条件 |
|---|---|---|
| 原生可靠性 | 保留已通过的651项本地测试与两个example构建；保留已成功的本地3a原生路径和8a训练谱系；最终格式化head交独立CI重新执行冻结完整协议 | 原始模型请求/响应、参数和来源 pins、实际 callback、真实 journal/witness、纠正/撤回/恢复拒绝；任何编译或 gate 失败都不能算模型执行 |
| 生产上下文 | 在已有 Objective owner 上提供当前 run proof，安装真实受认证 NDU owner并建立上下文 bridge | 真正的 owner capability、政策与授权世代、snapshot freshness、run/subject 对应关系；这些输入不能由固定 fixture 发明 |
| 长期质量与未来任务 | 在未使用的开发任务修复学习和行动能力，再冻结新的配方、任务流、阈值、seed 和独立 future 窗口 | 完整原始任务环境、独立未见根因组、实际修复 gate；现有已暴露历史任务只能继续作为开发材料，future=0 不能变成优势 |
| 公平分裂/连边 | 相同输入/工具/执行器下比较继续训练、扩容、强检索、数据分裂、随机分裂；同一 cell 集合比较无边/固定/随机/学习边 | 同容量与计价增长两套结果、完整实际成本、多 seed、预注册效用；重复 query 不能充作独立任务组 |
| 分布式与规模 | 使用真实跨主机在线来源与证据服务，加入分区、恢复、authority 故障、撤回传播和持续负载 | 独立 host/authority 能力、访问边界和清楚的撤回延迟语义；两次 hosted provision 不等于物理硬件证明 |
| 净压缩 | 在支持质量相同的工作负载上比较完整系统存储与运行账本 | 来源、base、adapter、router、历史版本、恢复状态、实际93MB privatehome、runtime、网络、持续存储/负载成本全部计入；未测维度保持 null |

目前可支持的结论是：来源和撤回约束下的可训练 cell 工程框架正在形成，若干窄机制已有真实执行证据。关于“像细胞分裂那样自发生长成通用 memory system”的性能与自治结论，仍受上述负结果和独立任务缺口约束，不能通过接口完成度或更多参数替代。
