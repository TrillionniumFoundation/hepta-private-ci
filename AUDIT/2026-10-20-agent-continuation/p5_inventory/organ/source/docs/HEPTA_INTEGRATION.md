# Hepta 的实际宿主接合

版本0.3。固定上游 `f8c9419df6ddeb36ff8b522a50219981fb8d9345`；运行状态统一见 [STATUS](STATUS.md)。OS 层不复制第二套 Agent、Codex 主链或持久操作账本。

## 1. 已核查源码到产品入口

| 位置 / 符号 | 已有职责 | 本项目接合 / 待补 |
| --- | --- | --- |
| `codex-rs/hepta-agentd/src/intelligence_ingress.rs` / `AgentdIntelligenceInvocationProviderV1::build` | 宿主从真实身份与 RunStartRecordV1 构建七 owner 输入；validate 校验 run、objective digest、authority epoch、generation | OS 资源观测由可信适配器送入原 owner；禁止 wire 自报当前 owner 输入 |
| `codex-rs/hepta-agentd/src/config.rs` / `with_intelligence_invocation_provider` | 安装宿主 provider；单有 runner 不表示完整产品 profile | 配置真实 provider、runner 和原状态 owners；普通 CLI 启动不算完成 |
| `codex-rs/hepta-agentd/src/objective_runtime.rs` / authenticated ObjectiveStart 路径 | 接入现有运行生命周期 | 保持 canonical 与 compatibility RunStart 分开，不用后者冒充规范链 |
| `codex-rs/hepta-agentd/src/lane_b_runtime.rs` / `state_control.rs` / `client.rs` | 生命周期、现有认证控制入口和客户端 | OS 适配器通过现有 composition 接合 |
| `codex-rs/hepta-contracts/src/final_use.rs` | 最终效果授权契约 | 授权不可变 OS 操作内容，不直接驱动寄存器 |
| `codex-rs/hepta-agentd/src/production_writer_host.rs` | 显式 durable writer 宿主接缝 | 正常启动不自动安装；只在实际所需产品 profile 装配 |
| `hepta-infer-worker --profile native-app-server` | 使用 owner 的 App Server provider；不是新模型主链 | 可作为真实模型路径观测，不能代替工具执行/OS资源接口 |

以上是来源映射，不是本项目已编译/调用的证明。核对来源：[宿主入口与限制](SOURCES.md#hepta-modules)。新增适配器文件尚不存在，不伪造调用点已合并。每一运行要报告二进制、构建 features、启动参数、装配 owner 与实际宣告能力。

## 2. 依赖必须先于 Hepta 闭环

先在原 Linux 固定真实 `codex-hepta-agentd`/App Server 和必要 owner 的 ELF、rootfs、锁/SQLite、futex、epoll、AF_UNIX、证书/NSS及 provider 配置。由实际 trace 得到最小系统依赖集，再移植到新内核。错误分类为 OS 行为缺失、Hepta 宿主装配缺失、外部 provider/设备前提，不通过放宽权限修复错误类别。

不要求一次启用所有可选 organ。声明的 profile 只覆盖实际装配路径；--help、mock HTTP、仅启动 daemon 都不算端到端。上游 native-host 文档保留的真实 provider 重启核对、设备容量等缺口继续如实记录。

## 3. 原生控制链与信任边界

用户目标 -> 现有目标/策略 owner -> 现有 Codex 工具主链 -> 最终内容授权 -> 受限 hepta-os 执行适配器 -> 新内核控制会话 -> 实际资源变更 -> 结果观测 -> 原操作 owner。

桥是受信任适配器，只有本工作区/任务资源封套内的能力，没有全部设备权限。内核对所有访问入口执行 [ABI 的统一对象规则](NATIVE_ABI.md)。高层授权不自动变成宿主 root；模型本身不持根句柄。桥受损时其已授权 envelope 仍可能被滥用，应将这一 TCB 风险纳入故障/攻击测试，而非宣称“内核校验权限”证明了意图正确。

构造 final-use canonical bytes 后保持不变；进程不再从可变模型字符串重建命令。内核先复制再核验，撤销与准入在资源对象短临界区线性化。无需将授权数据库、签名链或模型放进调度快速路径。

## 4. 三种版本不能混用

Hepta topology/body generation 冻结执行主链与资源 envelope；authority epoch 管理授权/撤销；OS resource revision 表示 envelope 内的一次实际预算安装。在既有 envelope 内调整 cap 不触发整套 topology 重建或 Agentd 重启；扩大权限或资源上界才走现有相应 owner 规则。

## 5. 映射到实际持久操作结构

固定Hepta操作库同时导出参考OperationIntentV1和DurableOperationIntentV1。实际持久路径为codex-rs/hepta-operations/src/durable_model.rs；不要把同名参考模型当作持久宿主。

**固定持久 K 与摘要分离（已按固定 Hepta SQL/源码实核）：** 原 `kernel.operations` 的持久记录由 `(scope_id: StableId, operation_id: StableId)` 联合主键索引，见 `codex-rs/hepta-operations/migrations/0001_durable_operations.sql` 的 `PRIMARY KEY (scope_id, operation_id)`；目的端去重额外纳入 `destination`，见 `destination_migrations/0001_operation_dedupe.sql`。原 `OperationIntentV1` 同时持有另一个独立 `payload_digest: Digest32` 字段，`semantic_digest()` 绑定 scope、operation、predecessor、destination 和该摘要。参考态 `model.rs::OperationKey { id: StableId, payload_digest: Digest32 }` 是**另一套参考模型的类型**，不是这个持久账本的联合主键。故 A03 的 K 值传递应无损携带 **两个 StableId**，而 A07 在既有唯一 owner 中另外验证最终 `payload_digest`、`semantic_digest`、最终使用授权及代际；禁止把参考模型类型直接替换持久 K，或将内核 D 当成持久主键。

| 实际字段 | OS接合规则 |
| --- | --- |
| scope_id | 原owner从已认证主体和既有工作区scope解析，不由OS另建scope数据库 |
| operation_id | 原逻辑操作ID；进程/boot变化不自动换ID重放 |
| expected_predecessor | 原owner固定的操作前驱；未决前驱不能伪造Applied来绕过 |
| destination | 可信资源记录中的稳定object_id所对应的目的身份；不是PID或slot |
| payload_digest | 不可变语义操作摘要，覆盖目标、动作、cap、资源前提和授权范围 |
| owner_generation | writer fence，不属于逻辑操作查找键 |

semantic_digest与final_use_binding沿用原实现。D、request_id、CapSpace和句柄是另行核验的投递绑定，不因重启而偷偷改变同一逻辑意图。改变cap、目标或语义前提需要新意图及授权。OS资源revision、Hepta body generation、authority epoch和writer generation分别校验。

源码依据：[持久模型](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-operations/src/durable_model.rs)及[导出区分](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-operations/src/lib.rs)。本表是待接合映射，不是已合并接口；SQL目的端共提交不等于设备效果与SQLite在同一事务内。

## 6. 历史核对、持续运行和目标收敛

原owner在投递前持久记录逻辑身份、意图与D。HOS2用CapSpace内有序sequence防止已退役的旧请求再次执行；同D变内容冲突，已记录拒绝也不可变成后来的执行。结果持久确认后原owner用RetireThrough确认连续终局，释放内核结果但保留拒绝迟到请求的前沿。1024限制是未退役窗口，不是终身写配额。

只读QueryDelivery的DeliveryView与原管理句柄分开，由可信init授予同scope观察者。原manager退出后仍可保留历史；boot重启或历史确实丢失则保持未知，不凭ReadUsage当前cap相同证明原执行。历史查询不恢复manage权。

旧效果不可确定时，先fence旧执行者、观察稳定资源对象、取得新授权，再建立明确的新目标收敛操作；旧K继续indeterminate。新目标达成与旧操作终态分别记录。若原owner的前驱规则不能表达该分离，必须修改和验证原owner接缝后才使用，不能另建账本或伪造前驱终态。绝对CPU预算可以评估此策略，不可逆设备动作不可照搬。

进程退出、cap=0和管理租约到期由独立OS恢复职责处理；不是在受限桥内再启动一套模型。用户明确暂停从可信意图记录识别，不从cap数值推断。迟到旧管理者请求在新授权之前先被fence。

## 7. 观测与控制器

关联 run/K -> D -> 内核对象/资源域 -> queue/completion，但仅按 read/observe 能力公开。统计包含采样时间、事件序号、丢失计数、revision、排队与执行时间。独立进程读相同计数只能减少自报错误，还须用工作负载完成量/实际数据核对计数正确性。

第一控制器试验配置：每1秒最多提案一次，观测年龄超过2秒或丢事件未恢复则不增加cap；每次变更不超过授权最大cap的10%，连续两次同向压力才改变，失败使用固定上次可用预算。此为待测保守实验参数，不是效果定理或最终默认。推理/观测本身单独计费；有界非AI反应式控制器是同等对照。

首个真实路径顺序：非AI客户端验证ABI -> 必需Linux依赖 -> 原Hepta实际profile -> 预算生效 -> revoke/kill/reboot。远程provider可用于早期主链实验但不得记为本地推理；后续另测本地CPU/GPU。

### 提交时再验证观测

开始推理时样本有效不意味着提交时仍有效。提交前重新检查内核初始时钟域的样本年龄、当前授权/资源revision及目标身份；过时提案丢弃或重新观察，不在队列中累积。CAS仅检测版本竞争，不证明负载当前性。ReadUsage尚不表达祖先节流/I/O/锁等待，缺乏可信原因时不自动把低进度解释为CPU不足；需要对应观测实现后才启用相关调优。对齐周期quota也不是滑动窗口或交互延迟保证。

## 只读 organ 不是设备效果适配器

固定Hepta的TrustedReadOnlyOrganV1禁止I/O和能力持有，不能在handle中调用HOS控制ioctl。观测由既有owner采集后投影为有界快照；效果通过原有authority/operations执行边界。图路由、driver摘要和Ready状态不授予效果权。详见[后端边界与实测](ASTERINAS_ORGAN_BACKEND.md)。
