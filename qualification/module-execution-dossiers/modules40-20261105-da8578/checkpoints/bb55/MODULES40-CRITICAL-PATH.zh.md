# 跨模块关键路径

以下优先顺序由固定源码的开放 gate 与 owner 依赖关系整理，属于工程依赖分析；各项是否完成仍以对应候选和实际宿主的执行回执为准。授权/资源准备、运行时组合和上下文/记忆接入可以并行推进，最终效果执行与验收仍须满足各自 owner 的前提。

## 1. 收齐固定候选的集成证据与平台、合并验收

按各自固定 commit/tree 收齐原始完整回归、关键清单核对、格式/严格 lint、平台 CI 与有序合并候选的证据。已经完成的候选原生回归由独立执行总览记账，后续验收继续引用对应原始回执；每次原始失败、重试、跳过、构建准备变更与运行终态分别保留，局部通过和历史同树观察不转成新候选的全套通过。

**完成判据：**存在绑定固定源码、原命令、完整原始日志/JUnit、原退出码和独立审计的完整回执；仍排队或未运行的步骤显式保持未验收。

涉及模块：[runtime.supervisor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json)、[runtime.codex](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/runtime.codex/IMPLEMENTATION_MAP.json)、[control.engineering](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/control.engineering/IMPLEMENTATION_MAP.json)。

## 2. 补齐独立授权、当前性与真实资源来源

为产品进程选择认证 caller、真实 Bao/provider endpoint、受保护的 frontier 和可信时钟，绑定撤销分发与密钥托管；把分配/推理接到真实容量、经济配额及模型/设备 grant。

**完成判据：**在实际 owner 和宿主上证明身份、当前授权、撤销收敛、租约到期与资源持有；内存槽数、接口存在或自签 fixture 不替代这些证据。

涉及模块：[kernel.authority](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/kernel.authority/IMPLEMENTATION_MAP.json)、[auth.authbus](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/auth.authbus/IMPLEMENTATION_MAP.json)、[secrets.heptabao](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json)、[runtime.fleet](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/runtime.fleet/IMPLEMENTATION_MAP.json)、[inference.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/inference.control/IMPLEMENTATION_MAP.json)、[inference.worker](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/inference.worker/IMPLEMENTATION_MAP.json)。

## 3. 贯通 Objective 到物理执行的进程生命周期

连接认证 Objective/RunStart、当前信任复核、Agentd、App Server turn/start/interrupt 和 provider 终态；让重启、Drain、接管、丢 ACK 与进程丢失在各自 owner 上完成对账。

**完成判据：**真实进程路径和精确代次/身份一致；可能已派发的运行保持不可自动重发，缺失终态或 usage 不被解释为成功、零消耗或可安全重试。

涉及模块：[objective.compiler](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/objective.compiler/IMPLEMENTATION_MAP.json)、[runtime.agentd](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json)、[runtime.codex](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/runtime.codex/IMPLEMENTATION_MAP.json)、[runtime.supervisor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json)、[inference.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/inference.control/IMPLEMENTATION_MAP.json)、[inference.worker](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/inference.worker/IMPLEMENTATION_MAP.json)。

## 4. 在真实请求边界闭合上下文与记忆最终使用

组合认证 V2 caller、准确的序列化/profile 和真实 retrieval provider，在物理发送前把当前 authority、owner cut、源 revision 与精确请求载荷绑定；验证删除、纠正、到期、回滚和旧代拒绝。

**完成判据：**回调后的复读、进程恢复和物理请求附加分别有证据；Vector 有真实 encoder/index owner；逻辑 tombstone、物理删除、派生产物撤回和模型遗忘的范围分别记录。

涉及模块：[context.compiler](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/context.compiler/IMPLEMENTATION_MAP.json)、[cognitive.store](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/cognitive.store/IMPLEMENTATION_MAP.json)、[cognitive.read](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/cognitive.read/IMPLEMENTATION_MAP.json)、[memory.retrieval](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json)、[memory.federation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/memory.federation/IMPLEMENTATION_MAP.json)、[knowledge.graph](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json)。

## 5. 闭合默认 D/O 账本和完整学习环

将默认 Decision/Outcome 与 pending-intent 恢复接到持久 owner，然后贯通冻结数据集、验证训练、独立评估、选定产物和新进程加载 shadow；选择真正独立的评估/trust/witness 来源。

**完成判据：**进程丢失后的精确 ACK 对账不追加新事件或续发过期授权；完整学习环和真实未来窗口证据成立后，才更新相应产品执行/选择声明。

涉及模块：[intelligence.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/intelligence.control/IMPLEMENTATION_MAP.json)、[learning.ledger](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/learning.ledger/IMPLEMENTATION_MAP.json)、[learning.operator](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/learning.operator/IMPLEMENTATION_MAP.json)、[learning.eval](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/learning.eval/IMPLEMENTATION_MAP.json)、[learning.artifacts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json)、[utility.ndu](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/utility.ndu/IMPLEMENTATION_MAP.json)。

## 6. 建立自迭代 coordinator 与可恢复控制闭环

由非测试 coordinator 通过命名 Agentd producer 提交冻结且独立评估的下一代参数/拓扑候选；贯通计划、grant 请求、final-use、writer handoff、当前代次/路由更新和恢复观察。

**完成判据：**anchor/fence 与提案 registry 的物理回滚域独立，目标宿主强制故障 canary、迁移恢复、独立 review/批准链可追溯；规划或观察回执本身不产生 apply 权限。

涉及模块：[control.runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/control.runtime/IMPLEMENTATION_MAP.json)、[control.engineering](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/control.engineering/IMPLEMENTATION_MAP.json)、[learning.plasticity](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json)、[neuron.runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/neuron.runtime/IMPLEMENTATION_MAP.json)、[runtime.supervisor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json)。

## 7. 按效果 owner 验收外部器官与交互

保留原 durable schedule/outbox/transaction identity，为每个真实 provider、Matrix homeserver 和 Servo driver 接入目的端去重、发送、终态与对账；让 UI 展示认证后端观察，并接入真实平台权限/更新 owner。

**完成判据：**HTTP 接收、本地 ACK、UI 状态变化或 App Server turn 结束不能代替目的端效果终态；实际二进制、网络/沙箱、身份与平台更新回滚均有宿主证据。

涉及模块：[kernel.operations](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/kernel.operations/IMPLEMENTATION_MAP.json)、[automation.taskflow](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json)、[channel.matrix](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/channel.matrix/IMPLEMENTATION_MAP.json)、[browser.servo](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/browser.servo/IMPLEMENTATION_MAP.json)、[ui.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/ui.control/IMPLEMENTATION_MAP.json)、[ui.native](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/ui.native/IMPLEMENTATION_MAP.json)。

## 8. 完成部署环境与独立接收方的最终验收

执行所选宿主的崩溃/断电/文件系统、Windows 私有状态与完整资格、容量/延迟/CPU/RSS、共享存储和恢复测量，并由独立 owner/selector/reviewer 接受证据和回滚演练结果。

**完成判据：**完整候选回执、外部不可变锚、独立 custody 与接收方结论共同成立；源码操作数和组件通过数不构成生产完成比例。

涉及模块：[kernel.evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json)、[cognitive.store](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/cognitive.store/IMPLEMENTATION_MAP.json)、[learning.ledger](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/learning.ledger/IMPLEMENTATION_MAP.json)、[learning.artifacts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json)、[learning.eval](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/learning.eval/IMPLEMENTATION_MAP.json)、[control.engineering](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bb55b0d7d263c396ec504c45393d938c3428dae5/docs/modules/control.engineering/IMPLEMENTATION_MAP.json)。
