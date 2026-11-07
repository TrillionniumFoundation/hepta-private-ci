# V13 真实新任务 proposal 与普通 Agentd 生命周期

本目录把已有 V13 MiniLM + residual adapter 的**新任务推理**接到现有
`CellGenerationWorkerV2`、`DurableInferenceControl` 和 Cell sole owner。
调用方提供新的 `text` 与 `payload`；模型选择原有十二种任务原语之一，原
`tasks.execute` 计算输出。worker 只返回状态提案、尚未发布的输出与实际成本，
不能写 Cell journal、prefix、outbox、SourceOwner 或发布状态。

这是显式 typed host 装配。默认 Agentd 不启用 V13，生产 CLI 没有增加自动选型。
所有验证和验收记录均为 `DENY_ALL`。完整学习状态的内容证明不授予训练、采用、
发布、撤回或外部效果权限。

## 固定来源与真实资产

`VENDOR.json` 逐文件记录原路径、Git blob、SHA-256、字节数和零改动声明。
十一份 vendor 原件保持原字节，不能为格式化或通过测试修改其校验值。

- 原 Adapter、FrozenEncoder、下载 manifest、SourceOwner 和 tasks 原语：
  `aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1`。
- 内容验证器：独立后继 `fa1c0592e7d1dea60cd8d8459a4e2b18fdfbab61`。
  不将该后继的测试资格转给本目录。
- 原 frontier-0 checkpoint：250,077 字节，SHA-256
  `c64db4368b56bef47ea4571c31b4b551a43c8064ef976241ae272cbde6ef2948`。
- 原 release artifact：
  `1b5091f1d5a920bddf57999367d60aa56116f2040da933cb8afc2b330c5e4455`。
- MiniLM：`sentence-transformers/all-MiniLM-L6-v2`，revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`。八份真实文件共
  90,873,127 字节；其中 ONNX 为 90,405,214 字节。

原件通过外部显式文件输入提供。本目录不嵌入大型模型，不下载模型，不创建
替代权重，不重新训练，也不读取标签来选择本次任务结果。

## 一次请求经过哪些实际边界

`prepare_agentd_v13_generation_worker_v1` 将实际 Linux boot identity 与
`CLOCK_BOOTTIME` 配对，核验 host 已打开的只读普通文件，并保留实际 inode。
typed bootstrap 在写 owner 之前检查完整 Agentd identity、learning/source
绑定、三份 owner 文件的访问模式、空文件或重开模式，以及它们与资产 inode
之间的分离。恢复失败不会回退为初始化。owner FD 的 pathname label 仅用于诊断，
不会被重新打开或用于目录同步；创建文件的 host 必须同步真实父目录。按路径
创建 control journal 的入口仍同步其真实父目录，并传播同步失败。

资产准备的实测墙钟成本以稳定事件写入原任务 journal。同一个 prepared worker
只能绑定一个 scope/task/source；第一次合法绑定即使随后遇到锁失败也保持，
跨任务必须重新执行准备。原 scope 跨 Agentd spawn 重开可重复提交同一成本事件，
由原 journal 精确去重。这个内存使用限制没有成为第二份持久成本账本。

每次新请求分为两个独立的、host 持有的子进程：

1. **verify，23 份资产。** 原 loader 验证 NPZ 的参数、Adam m/v/step、RNG、
   sampler permutation/cursor/epoch、dataset identity、source/config/encoder
   闭包，以及 release 内容。返回的五成员 digest 必须逐项等于 manifest 的
   `Resumable` binding。这里只做内容验证，不重新推导训练集 embedding。
2. **infer，14 份资产。** 只接收原 Adapter/backend/tasks 源、原 checkpoint、
   encoder manifest、八份 encoder 文件与这次新输入。它收不到 training NPZ、
   source bodies 或原训练 rows。原 FrozenEncoder 编码这条 text，原
   `Adapter.predict` 选择原语，原 `tasks.execute` 执行 payload。

两阶段都只接收已核 hash 的字节，输入不含 owner 路径。所有资源在私有临时目录
解码；验证阶段的 dataset 不会复用到推理进程。推理前后比较完整学习状态 hash，
变化即拒绝。运行状态明确为空，输出是有界 JSON line；它由现有 sole owner
原子提交到 prefix/outbox 后才允许交付。

现有 control actor 的有界 RPC 将计算留在独立 worker 线程。新执行先持久化
原请求绑定，再派发一次。重复、读回和重开只能读取同一 durable receipt；未知
计算结果保持 pending，不通过重新计算补造结果。worker 错误或进程失联不能产生
一条虚构的成功提案。

已持久化 admission、尚未联系 control 时，当前调用栈若观察到明确 Draining，
会在最终 recovery/fence 检查后提交 Rejected、原前驱状态和空输出。截止时间
先到的同类无接触请求提交 DeadlineExceeded。两者记录实际发生的 host admission
与检查区间；最终 fence 失效则保留 pending。冷重开缺少 control 记录、worker
错误或已发生 contact 都不能使用这条无接触结算路径。

## 输入与输出

唯一任务输入 schema 如下。没有 label、expected、选定 skill 或训练行编号字段。

```json
{
  "schema": "hepta.v13.task-input.v1",
  "text": "Keep the first occurrence of each city name and discard later repeats.",
  "payload": ["Riga", "Kyoto", "Riga", "Lima", "Kyoto"]
}
```

成功输出包含 `schema`、原 `request_digest`、`skill_index`、原 `skill` 名和
`value`。示例任务要求稳定去重，目标值为 `["Riga","Kyoto","Lima"]`。
模型实际选择与输出须从独立执行回执读取；单条任务结果不是泛化质量评估。

| 边界 | 实施限制 |
| --- | --- |
| 输入 | UTF-8 text 1–4,096 字节；整个任务编码最多 8,192 字节 |
| 资产 | 精确 24 个逻辑成员；各文件独立上限；总传输最多 512 MiB |
| 帧头 | 最多 32 KiB，严格字段与重复键检查 |
| checkpoint / dataset | 64 MiB / 128 MiB；复用原有 ZIP/NPY 分配前检查 |
| 输出 | JSON line 最多 64 KiB，仍受 manifest 剩余 prefix 容量限制 |
| 进程回执 / stderr | 128 KiB / 16 KiB |
| Rust host 配置 | 每阶段 CPU 1–30 秒，两阶段合计限额最多 60 秒；地址空间最多 4 GiB；整体墙钟最多 120 秒 |
| 子进程资源 | 实施 CPU、AS、128 MiB FSIZE 和 CORE=0 限制，回执报告实际 soft/hard 值 |
| 取消与时钟 | 原子取消标志；真实 native entry 再查 CLOCK_BOOTTIME；独立 Instant 墙钟上限 |

host 只终止自己持有的 Child，并等待真实退出和管道结束。不能确认结束时返回
unknown/unavailable，保留原 control pending。发出 kill 不是完成证明。

## 成本的含义

任务账本接收已观测的控制层排队与准备区间，以及 worker 的验证、编码、
adapter 推理、任务 codec、进程其余工作和 host 其余工作。已完成阶段的墙钟和
CPU 从进程总量中扣除后再记余量，避免重复累计。传输量只在实际 pipe 观察点
计入一次。无接触的拒绝/过期请求另记一次实际 host 区间，稳定事件身份保证
原 receipt 的重复读回与冷重开不再追加费用。

普通 compact ACK 仅表达调用方确认交付，不能证明运输开销，其缺测字段保持
None。真实 runtime 验收例程另外测量接收端 write+sync，并通过原 ACK 进入同一
账本。owner 最终 commit/witness、恢复和记录成本本身尚没有完整独立测量，
不得把局部控制区间或历史 Persistence/Evaluation 记录解释为这些开销全部已计入。

未观测的 CPU、能耗、存储或通信保持 `None`，不会用零填补。实际计时分辨率内
测得的零是独立的真实观测。整个 acceptance 包络另行标为 inclusive，不与
exclusive 任务成本相加。

`runtime_digest` 绑定实际 interpreter ELF、worker 源字节、显式 argv0 和资源
参数；原 encoder manifest 还验证 NumPy、ORT、tokenizers 的版本。当前没有
证明整个 venv、动态库与 host 内核的完整字节闭包，也没有声明 host ABA 安全。

## 固定专家比较接入同一个持久评估器

`freeze_cell_evaluation_plan_v1` 从两侧健康、已 drained 的实际 Cell journal
读取完整账本、manifest、snapshot 和 continuity cut。候选与固定专家必须具备
相同的参数容量、累计训练预算和选择性更新约定；累计预算声明包含继承训练及
候选搜索，固定专家的结构前后必须相同并匹配其实际 manifest。训练计数及来源
receipt 的引用由现有独立签名者负责核实，本地字段相等不构成真实性证明。

计量合同至少要求墙钟与 CPU，并显式指定额外指标；十二类成本阶段必须覆盖。
缺阶段、未知 outcome、所需指标缺测、不同任务或冻结后账本 cut 改变都会在
holdout 消耗和 provider release 之前拒绝。两侧分别核对自己的模型 source，
共享的计量约定单独绑定；未知能耗等未要求指标保持 None。

完整比较记录进入原 estimand 的域分隔摘要，再调用既有
`freeze_product_evaluation_plan_v1`。`CellEvaluationRunnerV1` 实际委托
`ProductEvaluationRunnerV1`，保留原 final-holdout CAS、消耗后数据 release、
estimator 计算、独立签名验证和 durable evidence sink。调用者不能提交最终
metric 来代替原 estimator，也不能用另一个公平预算的旧签名取得本次资格。
所有新增 receipt 仍为 DENY_ALL，不授予模型采用或迁移权限。

这个比较的成本范围固定为 final-holdout 前已完成的两侧任务账本。
之后发生的本次评价计算、签名与 sink 写入开销不在冻结 cut 中；本入口不声称
已得到完整物理成本，也不声称已经执行真实同预算固定专家收益实验。

## 描述符和普通 runtime 验收入口

`make_descriptor.py` 接收原资产目录、encoder 目录、被显式 SHA-256 pin 的内容
验证回执、实际 source snapshot / encoder manifest、interpreter argv0 与新
task 文件。它核对原 bytes/hash 和原 CANDIDATE 内容，确认 task 的 text 与
payload 都不同于原 120 条训练行，然后在新目录写入 `descriptor.json` 和
`ASSEMBLY.json`。它不执行模型或 owner，也不替代 worker 的完整内容验证。

descriptor 的 learning binding 来自命名回执；worker 每次请求仍重新验证。
evolution 的 structure/lineage 由实际原代码、config、release 和 parent 内容
求 digest；adoption_receipt 字段引用的是原研究 scope 的历史 publication
原件 SHA。该引用不是当前 Agentd 的采用授权，当前 SourceOwner frontier 也
没有在这个局部装配中被重新认证。

显式可执行入口是 Agentd example `neuron_v13_acceptance`。它接收三个参数：
绝对 descriptor 路径、预期 descriptor SHA-256、尚不存在的输出目录。原生
构建阶段应保存真实 compiler-artifact 的 executable 路径，再调用该路径。
缺少描述符或任何资产立即失败；没有 ignore、skip 或环境缺失后的伪成功分支。

例程使用真实 `run_with_shutdown`、Fleet、App Server readiness、typed bootstrap
和原 service handle。外部停止 future 只请求原 drain 流程，不暴露或伪造
`AgentdState::ready`。未 ACK 的 outbox 必须保持 drain blocker；跨 runtime
重开读取原结果后才能按原 bytes 确认交付。取消请求只记录真实响应与最终观察，
完成竞态不能写成抢占成功。例程结果是独立原生 receipt，不计入 JUnit testcase。

## 验证入口和证据边界

纯协议负例不需要 NumPy、ORT 或模型资产：

```sh
python3 -B -m unittest discover -s qualification/neuron-v13-generation -p test_proposal_worker.py -v
```

九组覆盖新任务 schema、UTF-8/整体容量、重复 JSON/nonfinite、实际过期时钟、
外来时钟 epoch、checkpoint 声明容量、推理资产隔离、执行源码漂移和重复资产。
CI 单独保存这条 Python 命令的源码身份、日志、计数和退出状态，不将其计入
Rust JUnit，也不把协议负例解释为模型推理成功。

Neuron 的四组实际 Python transport 行为测试和 Agentd 的四组 typed bootstrap
行为测试随相应 Rust package 门运行。后者使用真实 Python 加明确 invalid
closure，检查拒绝、成本、身份、实际 FD、scope 竞争与普通 owner 重开。它们不
证明真实模型成功；Rust 资格只属于同次运行的冻结源码。

真实资产的 Python verify/infer 观测须分别保存输入前后字节、学习状态、实际
native clock guard、资源限制和阶段成本。这样的 Python 观测没有经过 Rust
control owner，其请求 digest 也不是 Cell request digest。普通 runtime 的
真实资产例程必须单独执行，并保存原生记录、接收端写入与 ACK 及恢复结果。
历史源码的结果、仅有源码或内容闭包验证都不能代替该执行证据。所有动态成功、
失败与超时记录保存在精确源码绑定的外部证据中。
