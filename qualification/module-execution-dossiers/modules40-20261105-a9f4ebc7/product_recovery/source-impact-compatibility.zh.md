# 源码影响与兼容性说明

本次集成选取产品恢复分支中与原始 RunStart、Agentd bound lifecycle、worker 持久终态对账及完整消息输出有关的增量，并保留统一候选已有的更严格恢复校验。该集成不能表述为全量合入 #4846 或完整包含其 19 个提交。

Agentd 的 bound 操作在任何幂等返回之前核对完整原始 snapshot、context/compilation digest 和 revision，防止释放后的同名 run 重用将恢复写入导向另一份 admission。canonical 准备链在调用 provider 前校验当前 owner 与原始 RunStart，随后保留原始请求、目标、body、artifact、authority epoch、run generation、fence 和 deadline；body 的 spawn generation 与 run 的 admission generation 分开处理，准备时间受原始 deadline 约束。

worker 将归一化后的物理终态先写入 native journal，再以精确原始绑定和 Agentd 当前 revision 发布终态 ACK。worker 重开后的已存终态和保留的 App Server thread/read 路径重试的是对账；这些路径不再次启动 provider 请求。统一候选原有的 dispatch/turn/observation 身份核对、重复 turn 拒绝及 owner-loss 防线保持不变。较晚到达的 provider completion 不能抹去已记录的取消、超时或隔离边界。已观察并持久化的 usage 可以保留；仅从不含 usage 证据的 thread/read 恢复时，usage 保持未知，不填零。

针对统一基线继续推进到 `e65a53ddfc872ef66edc63dff8f28d4414817c60` 后的源码差异，已审查的融合方案还补齐 `turn/completed` 自带消息列表：验证精确终态 witness 后，在原累加器中按 item ID 合并完整文本，随后才设置终态字段。仅包含最后一条消息的 summary 不再丢失前面已观察到的消息；过大的终态文本不能授权完成。原有 1,024 条消息限制保留，metadata 同时计算每项结构和 ID 的总字节。基线新增的十个测试名称和三十个断言全部保留。该补充须与真实三方 merge、最终源码冻结和原四包执行证据对应，不能只靠父链元数据或源码存在判为通过。

兼容性变化需要明确标注：`run.lifecycle` 能力版本从 **1.1 升为 1.2**，`AGENTD_CONTROL_SCHEMA_VERSION` 仍为 **2**。`NativeIntelligenceRunBinding` 从单一 run ID 改为完整原始 snapshot；CLI 相应采用 `--intelligence-run-snapshot-json`，调用方需提供原始完整 admission，不能通过读取当前 daemon 为旧请求补造身份。

带 intelligence binding 的请求摘要域从 `hepta.native-intelligence-request.v2` 变为 `v3`，摘要纳入完整 snapshot。使用相同 request ID 重开旧 v2 intelligence journal 时，v3 请求身份不匹配会拒绝执行；本次没有透明 journal 升级、重写旧记录或自动重发物理请求的路径。无 intelligence binding 的普通 native 请求摘要分支仍使用 `hepta.native-request.v1`，但本次测试不能扩展为所有旧版本 journal 的迁移验收。

新增进程用例的范围是：**原 Agentd/App Server owner 持续存活、保留原 run，而 worker 进程退出后重新打开 durable journal，或根据精确保留的 thread/read 证据恢复，再向当前 Agentd revision 对账**。用例覆盖 spawn identity 与 lifecycle generation 不同、coordinator revision 已前进、终态写盘后 ACK 前丢失 worker，以及不重复 provider 请求。它们使用真实 Agentd/App Server 路径和受控 provider fixture。Agentd 自身进程退出后的 coordinator 持久恢复、跨 owner 接管、真实外部 provider/硬件配额以及完整默认生产 owner 组合仍需各自的原条件证据。

四包 `cargo build --locked --tests`、`just fix --locked` 和 `just fmt` 分别记录为测试目标构建、lint 修复和格式化阶段。只有随后原 `just test` 的实际执行日志、JUnit、退出码以及逐名完整性审计能够支持测试结论；构建或 lint 的 exit 0 不记为测试 PASS。
