# automation.taskflow 对抗审计（2026-10-01）

审计基线为 PR #1278 的 `acf19851c5c7babbda0b1bfaad1bbad9f0a17559`；main 基线为
`a126987b84737dbc2ee2592442a314117bddb4a2`。沿既有候选继续修复，不授予生产或发布权限。

## 文档与模块位置

存在详细技术开发文档：TECHNICAL.md、IMPLEMENTATION_MAP.json、执行 dossier、
Calendar V2 故障矩阵和产品资格契约。文档已纠正版本、DST 策略与完成范围，并补充实际
HTTP host 配置、独立信任材料、私有文件权限、nonce 状态和恢复要求。

本模块持有每个 Agent 的 schedule/occurrence/TaskFlow 持久状态；Agentd 拥有调度与控制入口，
Core/App Server 拥有 turn 执行，FinalUse/provider/Fleet 各自保留权限与资源所有权。
Neural Circuit 编译及记录接口没有产品调用者，目前是静态 DAG 与持久元数据能力。

## 已实施修复

| 问题 | 修复 |
| --- | --- |
| Calendar 日程结束后长期停机，倒查耗尽扫描预算或要求日程外时区证据 | 从包含式结束时间倒查；覆盖迟到查询、coalesce 和最终完成 |
| Circuit 检查 fence 与写入分离，存在竞态 | BEGIN IMMEDIATE 包含当前 run、事件链、定义验证与 INSERT |
| activation 可引用非法节点/替换编译策略，choice 可选任意目标 | 校验已准入节点、策略摘要与合法出边 |
| Circuit 重放和重开仅信任已存摘要 | 重建 payload；一致快照按 128 行分页校验全部记录；覆盖跨页损坏 |
| provider key 的分隔符歧义和跨 Agent 碰撞 | schema 21 在接触前持久化 destination namespace 下按长度分帧的 owner Agent + run/step key，重试和重启复用精确存储值 |
| Unknown 后有合法 provider absence 证据仍无法领取 | claim 优先使用 append-only reconciliation，覆盖重开及换 fence 重试 |
| 同 revocation epoch/revision 的不同撤销集被忽略 | 接触 provider 前拒绝同 frontier 分歧 |
| 更换 provider endpoint 后借新服务 NotFound 推断旧 effect 不存在 | 持久化配置身份 pin；无 pin 的非空 authority 目录拒绝恢复 |
| u32::MAX successor 饱和导致版本重复 | checked_add 并拒绝溢出 |
| focused CI 未验证准确 source/merge，旧格式和 caller 清单错误阻断真实检查 | 修复格式、已有 caller 集合和 lexical guards；锁定依赖并复用现有 V8/test 入口 |
| caller scope 可被带 attribute 的 nested impl、别名/宏、Unicode、上下文或组合定义绕过 | 收紧源码解析和 receiver 范围验证；新增对抗回归，保留正常调用的 negative controls |
| Circuit 编译辅助函数更名遗漏及重复实现 | 修正真实调用名，复用统一编译路径 |
| migration 测试依赖回退最新 schema，未真实重现旧库 | 从真实 v1 SQLx migration fixture 升级，补齐 Bazel integration compile_data |
| retirement 检查遗漏 NegativeObservation 分支 | 恢复原有分支，覆盖停用/取消与重启后的行为 |

旧 dispatch 行和不可变触发器保留。旧 null key 不自动升级、查询或重发；恢复它需要独立的
owner/provider 隔离证据。已有 authority 缺配置 pin 时，也不能静默绑定新 provider。

## 验证范围

已通过限定范围的独立源码复审、SQLite 21 个 migration 及 20→21 原行保留/不可重写检查、
Rustfmt 和 diff 检查。独立复审中发现的 choice 重放错误与丢失 lock 后的 pin 缺口已修复；
后续 caller verifier 复审发现的 7 类绕过也已修复，本轮限定复审未发现新的可执行修复项。

本轮 runtime source 为 `117f7f5260600303e05bee3f877ded0c82a2aa23`，tree 为
`a1ab4cd4c6a3e81e23496edd85e6cb5a84215ce0`。实际本地 `codex-hepta-automation`
默认配置测试 **116/116 通过**，`taskflow-structural-qualification` 配置
**121/121 通过**；caller verifier **28 项回归、自检和完整 closure 通过**，
完整 closure 覆盖 **45 个 boundary、4365 个 Rust 文件**。
`kernel.operations` 本地测试 **44 项通过**；1 个默认忽略的子进程 worker 入口由父测试
实际执行。`just fix -p codex-hepta-automation` 退出 0。
选定模块严格 Clippy：`just clippy --locked --offline --no-deps -p codex-hepta-automation`
**退出 0**，没有 denied lint；保留 4 项既有 large-enum/argument-count advisory warning。
对应源码 owner 的 Rustfmt 检查通过；12 个 source follow-up 文件的远程内容与实际受测内容一致。
包含依赖的严格 Clippy 被既有 `kernel.operations` SQLite owner lint 债阻断：
`destination_dedupe.rs:49`、`durable_store.rs:93` 的直接 `connect_with`。该债保留在原 owner，
没有通过 automation 放宽生产边界绕过它。Agentd Rust 测试尚无本地通过结果。
首轮磁盘耗尽中断属于历史构建尝试，已不代表上述测试的当前结果。

最终 published source 及 main merge candidate 的 hosted focused CI 仍需对应提交的外部记录；
共享 runner 排队不构成检查通过，历史成功也不能证明本轮改动。上述本地结果只证明已测
源码边界，不能代替目标机/provider 执行、独立验收或发布。资格 JSON 保留历史源码观察，
本轮精确 runtime source 身份和检查范围另外记录；资格、激活和发布均不因此改变。
最终迭代复审限定于上述修复和回归边界，当前未发现新的可执行修复项；这不是对未接通
Circuit 产品链或外部 owner 资格的完成声明。

## 完成度与剩余工作

| 层次 | 结论 |
| --- | --- |
| Durable Calendar/occurrence/TaskFlow/provider recovery substrate | 已实现；当前本地默认/结构测试通过，对应提交的 hosted 验证仍需外部记录 |
| Agentd reference HTTP/final-use 源码组合 | 已实现，兼容路径 fail closed；没有真实选定 provider 执行证明 |
| Circuit DAG 编译及内部元数据一致性 | 已实现；不能认证外部 causal/Fleet/DecisionCell 引用 |
| 完整 Circuit 产品执行 | 未完成：无产品 caller、真实 DecisionCell/organ、通用 join/cycle、child/resource conservation 与整合恢复循环 |
| 目标机、真实 tzdb、provider/trust/live revocation、独立验收与运维资格 | 需要外部证据；资格、激活和发布保持 false |

历史 command digest 缺少对应 fence 元组，不能完整重算。内部摘要一致性也不能代替
DecisionCell issuer 或 live Fleet lease 的认证。后续应沿现有 Agentd/Fleet/FinalUse owner
接通真实产品链及其恢复验证，不能通过声明完成或复制新 owner 关闭这些缺口。
