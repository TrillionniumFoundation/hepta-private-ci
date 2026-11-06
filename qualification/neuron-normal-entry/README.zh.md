# 显式选择 Joint 后端的普通 Agentd 入口

本阶段把已经存在的 `JointGenerationProcessWorkerV1`、durable inference control、Cell V2 journal 和 generation service 接到实际 Agentd `main`。配置仍然默认关闭。显式选择后，普通 runtime 启动服务，现有私有 control socket 提供有界命令、原结果读取、输出分页和确认；没有另建生成状态 owner。

本文描述本分支源码与新增测试的合同。新增测试尚须由同一提交的原生门执行；源码就绪、历史测试结果和真实训练权重资格是不同事实。

固定 7391 原生门的实际失败、源码诊断、helper 字节边界与待验证修复见 [BASELINE-FAILURES.zh.md](BASELINE-FAILURES.zh.md)。

## 入口及身份

普通启动新增一对必须同时提供且不可重复的参数：

```text
--neuron-generation-bootstrap-descriptor /absolute/canonical-parent/bootstrap.json
--neuron-generation-bootstrap-descriptor-digest <descriptor 原始字节的 SHA-256>
```

这两个参数经过原有 `AgentdProductionStartup`、完整 Agentd 身份装配和参数处理后，先用只读 profile 检查拒绝有限 Notes/Desktop 或重复装配，再调用 [`load_neuron_generation_process_bootstrap_v1`](../../codex-rs/hepta-agentd/src/neuron_generation_process_bootstrap.rs)，然后显式启用 `with_control_endpoint()`，把原 typed bootstrap 交给 `AgentdConfig::with_neuron_generation_bootstrap`。主进程调用点在 [`main.rs`](../../codex-rs/hepta-agentd/src/main.rs)。profile 冲突在 owner 文件创建前拒绝。

这不是独立运行任意 Agentd 的身份捷径。正常启动仍要求 Fleet/Supervisor 提供原有 Starting 状态、路径、资源预算和 spawn generation。外部调用者不能用 generation 请求选择 executable、替换权重、修改 manifest 或授予采用权限。

公开的 `neuron_generation_process_identity_digest_v1` 绑定完整 `AgentdIdentity`：agent ID、layout 的 agent ID 及全部路径、Fleet/workspace/resources、home/run/control/App Server 路径和本次 spawn generation。零 spawn generation 在 owner 文件创建前拒绝。descriptor 的 `identity_digest` 必须来自将实际启动的完整身份，而不是仅绑定 agent ID。

## Descriptor v1

JSON 拒绝未知字段，原始文件上限 262,144 字节。给 CLI 的摘要核验实际读取的原字节，重新排版也需要新的摘要。

| 字段 | 合同 |
| --- | --- |
| `schema` | 固定 `hepta.agentd.neuron-generation-bootstrap.v1`。 |
| `identity_digest` | 上述完整 Agentd 身份摘要，64 位十六进制。 |
| `boot_id` | 本 Linux 主机 `/proc/sys/kernel/random/boot_id` 的实际值。 |
| `mode` | 仅 `create` 或 `reopen`；没有自动回退。 |
| `journal_path`、`witness_path`、`control_path` | 三个独立 owner 文件，绝对路径和规范化父目录；禁止与 descriptor 或模型资产别名。 |
| `max_records` | 6–4,096，绑定原 journal/witness 容量。 |
| `worker_generation` | 等于 `config.initial.writer_epoch`，恢复沿用原值；独立于 Agentd 进程 spawn generation。 |
| `control_capacity` | 1–16,384，交给既有共享 durable control 容量管理。 |
| `queue_capacity` | 1–64；实际控制队列有界。 |
| `rpc_timeout_millis` | 10–5,000，控制往返等待边界。超时不被转换成已知模型终态。 |
| `config` | 完整 `CellGenerationConfigV2`，包括初始 snapshot、manifest、task 和 source frontier；初始 revision 为 0，state/prefix 为空，未 stopped。恢复用同一 genesis config 验证原 journal，而不是把最后 snapshot 当新 genesis。 |
| `executable`、`weights`、`public` | 各含绝对 `path` 和实际内容 `digest`；实际 executable、输入、权重以及观察到的设备 profile 均被核验。 |

manifest 的 source/bundle/evolution/adoption 字段仍是已有契约中的身份引用。loader 不把配置者填写的摘要升级成原生来源签名、学习资格、采用 receipt 或撤回授权。选中实现仍要求 Frozen 权重，且实际权重 SHA、模型组件、runtime SHA、schema 和设备 profile 与 manifest 一致。缺失历史训练权重不能被 synthetic fixture 的权重替代为训练资格。

## 文件恢复与时钟

[`neuron_generation_process_bootstrap_files.rs`](../../codex-rs/hepta-agentd/src/neuron_generation_process_bootstrap_files.rs) 负责路径和实际打开文件的检查。`create` 要求三个 owner 路径全部不存在，然后使用 `create_new`；`reopen` 要求全部存在且 journal/witness 非空。任一步骤失败都不会清空旧文件或尝试 fresh 初始化。创建途中留下的文件保留为失败证据，需要宿主显式处理。

loader 使用已有宿主依赖的 `O_NOFOLLOW | O_NONBLOCK` 打开实际 descriptor、executable、weights 和 public 文件，打开后检查 regular-file 类型。选中的真实 FD 移交 `JointGenerationProcessWorkerV1::open_files`，不再通过资产路径打开；descriptor 与三个资产的原 FD 保留至 owner 初始化前，与三个实际 owner FD 交叉检查 device/inode。因此，预检后替换成 FIFO 不会卡在等待另一端，预检后把 owner 换成资产硬链接也会在 owner 解码/写入前拒绝。原 `open(path)` API 保留其原有宿主稳定路径前提，不借用这个新 loader 的抗竞态资格。

control 通过新增的 owned-file 入口移交给原 `DurableInferenceControl`，复用原独占锁、回放和 append/sync 路径；不重新按路径打开目标，也不改变既有 family 的持久字节。Linux owned-file 入口读取实际 FD flags，拒绝只读、只写和没有追加模式的句柄；当前显式支持 x86/x86_64/aarch64 flag ABI，其他 ABI 拒绝这一新入口。原跨平台 path constructor 保持既有行为。调用者不得在移交后通过别的 FD 改变该 open-file description 的标志或继续写入。

独立 witness 的 scope 同时绑定实际 boot ID、完整身份中跨进程稳定的上下文、genesis config、owner 路径、容量和原 worker generation。新进程可以在**同一次 Linux boot**下用新的完整 Agentd 身份摘要打开原 owner 文件；不能把 descriptor 改成新 boot ID 后继续原 journal。当前没有跨 boot 时钟迁移资格。

actor、native worker 和 service 使用同一 `CLOCK_BOOTTIME` 时钟域；Status 向客户端提供本域实际观测时间，Step deadline 使用这个域。读取时钟失败返回无效样本，native worker 在创建子进程前拒绝零样本，不伪造超时结果或成本。

两个独立 inode 不能单独证明整个存储根未被一起回滚。witness 的独立保留与文件系统保管是宿主前置条件，本阶段没有新增抵抗 journal+witness+control 整体回滚的外部信任锚。固定 executable inode 和运行前后内容核验也不证明执行期间从未发生短暂原地修改；宿主必须保持已选择 executable 不可变。

## 有界控制与最终使用

请求与响应定义在 [`generation.rs`](../../codex-rs/hepta-agent-protocol/src/generation.rs)。原 control frame 仍限制为 65,536 字节，不传输完整大 state/prefix。

| 命令 | 实际 owner 行为 |
| --- | --- |
| `Status` | 返回 snapshot/manifest 摘要、状态与 prefix 长度、pending/outbox 引用及实际 host clock。 |
| `Step` | 客户端提供 operation key、预期 snapshot 摘要、task/source frontier、至多 8,192 字节 input 和绝对 deadline。owner 提供完整 predecessor 与真实 admission 时间，并从完整 compact intent 派生稳定 operation ID。 |
| `Reconcile`、`Cancel` | 绑定原 request digest；取消是持久意图，未决计算不会因控制超时变成已知完成。 |
| `Output` | 绑定整块 chunk digest，分页最多 8,192 字节。完整读完也不自动确认。 |
| `Acknowledge` | 绑定原整块输出引用和接收方实际确认摘要；exact retry 可返回原确认。 |
| `Cost` | 返回同一 task/source 账本的已知小计、未知测量计数、未覆盖阶段和 inclusive/exclusive 分类，不把缺测当 0。 |
| `Drain`、`Resume` | 交回既有 service/owner lifecycle；pending 或未 ACK outbox 阻止完成 drain。 |

`with_control_endpoint` 明确保持 endpoint 对应的强 sender；普通 typed 调用者不因本改动自动暴露控制接口。服务退出、代际 fence、未知计算和 journal 错误继续受既有 owner/projection 规则约束。客户端拿不到 live dispatch token，也不能通过 readback 重新启动已不明的操作。

本阶段没有放宽 service generation 的严格 journal 连续性检查，没有实现跨 manifest 采用、旧状态迁移或撤回后销毁未 ACK outbox。新 manifest 仍需另行有证据的授权 handoff；不能用进程 restart 或新 descriptor 偷换此边界。

## 新增验证范围

1. [`durable_control_file_tests.rs`](../../codex-rs/hepta-infer-core/src/durable_control_file_tests.rs)：实际文件模式拒绝、共享偏移不会覆盖已有事件、改名后继续原 inode、独立第二 writer 拒绝、损坏原字节不被修成成功。
2. [`neuron_generation_process_bootstrap_tests.rs`](../../codex-rs/hepta-agentd/src/neuron_generation_process_bootstrap_tests.rs)：完整身份/零 generation/资产/boot/digest 先验失败；别名和缺失 reopen 拒绝；预检后真实 hardlink/FIFO 替换在实际 FD 边界拒绝且旧 owner 字节保留；实际 Joint 子进程执行 Init→Stop 后原 state/prefix/outbox/cost 通过同 boot 文件重开保留，原请求返回原 receipt 且 lower control 不重算。
3. [`neuron_generation_process_e2e.rs`](../../codex-rs/hepta-agentd/tests/neuron_generation_process_e2e.rs)：实际 Supervisor 启动 Agentd 二进制，通过 main 和普通 runtime 使用真实 control socket；Init→Advance→部分 Audio Commit→Stop；输出重复分页；接收端实际 write+sync 后 ACK；未 ACK drain=false、ACK 后 drain=true；读取实测 wall/未知 CPU 与 energy；正常 Supervisor stop。
4. Joint worker 的无效时钟回归：零时钟样本返回 Unavailable，不生成伪造 terminal proposal；生产采样位置在 `Command::spawn` 前。

以上数值测试复用固定、明确标记 synthetic 的合法 HPS fixture，执行实际 Joint 数值核和真实子进程，不是原训练权重资格。共享 helper 使用 `codex_utils_cargo_bin::cargo_bin("hepta-joint-propose")` 读取实际构建元数据；没有猜测 `target/debug` 路径或依赖会被 shell 丢弃的单一连字符环境键。Bazel 显式声明共享 fixture 源/数据与实际 helper 目标。

CLI 测试在正常停机后提取实际已写 journal 中最后一份 state，用于核对四种模态的实际输出、cursor 与 prefix；该提取器不是独立 hashchain/witness 审计。独占回放和 witness 校验仍由真实生产 owner 负责。此测试也不把同 boot loader 重开泛化为跨 manifest 更新或跨 boot 恢复。
