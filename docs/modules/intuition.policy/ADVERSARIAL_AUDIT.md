# intuition.policy 本轮对抗审计

审计日期：2026-09-30。候选入口：[PR #1036](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1036)。本报告记录本轮源码审查、修正与有限本地验证，不签发生产完成、独立接受、部署或发布证明。当前源码事实以 [CURRENT_STATE.json](CURRENT_STATE.json) 为准；精确执行证明须来自绑定候选提交、树、命令、日志和运行身份的不可变工件。

## 文档与项目位置

模块已有详细技术文档：[TECHNICAL.md](TECHNICAL.md) 含 17 个编号章节，并配有 [CONTRACTS.md](CONTRACTS.md)、[OPERATIONS.md](OPERATIONS.md)、[CI_EVIDENCE.md](CI_EVIDENCE.md)、[IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json) 和 [执行 dossier](../../../qualification/module-execution-dossiers/detail/intuition.policy.md)。文档覆盖所有权、输入与版本、算法和容量、权限、失败恢复、运维及测试追踪；本轮已修正过时的 API、合同清单和源码映射。文档齐全、源码存在、执行通过和外部接受是不同事实。

| 所在层 | 责任与边界 |
| --- | --- |
| `hepta-intuition` 纯内核 | 完整合法候选集上的选择、弃权、慢路径、概率与确定性承诺；不调度模型或工具，不授予执行权限。 |
| `hepta-intelligence` 认证层 | 验证生成者、评估者和观察者的签名与控制者独立性，绑定资格和原始政策语义。 |
| Agentd 产品层 | 使用同一不可变产品 profile，保留准备材料，在唯一提交边界复验并绑定运行内回执。 |
| learning ledger | 唯一持久 Decision 写入者与独立 witness，维护根签发信任分布、租约、代际及精确重放。 |

优化应沿这些现有所有权边界推进。评分与校准工件生产仍属上游；本轮没有建立第二个政策状态库或第二条持久写入路径。

## 本轮发现与修正

以下严重度针对观察到的具体故障边界，不代表完整项目的漏洞评级。

| 级别 | 发现及影响 | 修正 |
| --- | --- | --- |
| P1 | 准备阶段丢弃原始三方签名材料，提交使用锁前时间；等待 writer 后可能继续消费已过期或已撤销资格。 | 保留原始请求、profile、承诺及签名；`commit_v4` 在唯一 writer 锁内取得新鲜 owner 时间，复验信任、签名、角色分离、有效期、完整 pins 和实际决策后再写入。 |
| P1 | 激活信任时检查分布有效期，后续使用可能继续消费过期分布或已到期的根撤销状态；评估路径也存在租约遗漏。 | 激活记录保留根签发分布租约和预定根撤销；ledger 使用及 Agentd 最终提交复验租约，评估使用边界同步复验。加入预定签名者撤销、分布到期及信任轮换回归。 |
| P1 | canonical owner 计算沿历史政策入口，而认证提交使用产品 V4 profile，合法产品请求可能因语义不一致被拒绝。 | 产品组合向纯计算传入认证调用使用的同一不可变 profile；显式开发兼容路径保留既有语义，新增产品路由回归。 |
| P2 | 纯内核允许 128 个真实候选，但产品学习记录还需一个 abstain 项，超过 ledger 的 128 项上限。 | Agentd 产品准备最多允许 127 个真实候选，提前返回稳定错误；内核仍允许 128，不截断完整集、不扩大 ledger 上限。覆盖 127 个候选加 abstain 的持久往返和 128 个产品候选的提前拒绝。 |
| P2 | 多个候选承诺入口在数量校验之前分配并哈希候选内容。 | 在承诺入口共享执行 1..128 预检，保持已接受历史字节与 digest 不变。 |
| P2 | V4 热路径反复复制整个候选向量，增加分配及尾延迟成本。 | 私有路由与 native helper 借用请求；保留公开调用签名、风险语义和历史 digest。128 候选的本地分配观测由 517 次降至 239 次。 |
| P2 | 严格 Clippy 被冗余闭包阻塞；旧源码修改工作流、编码运输及过时 finalizer 标记妨碍资格证据解释。 | 修复闭包，移除候选中的源码修改工作流和运输脚手架，更新只读 inventory；full／independent 计划检查规范状态并执行 canonical product 回归，三套计划强制执行信任分布测试。 |
| P2 | 最终独立复审发现最大候选 fixture 的标识生成顺序不满足协议要求的字典序。 | 修正 fixture 的候选标识编码，使顺序保持 canonical；没有放宽产品顺序校验。 |

版本兼容边界仍须保留：V2 评分与分配承诺分别编码，但历史生成者 completeness V1 签名仍绑定含 utility、confidence、OOD 和 assignment probability 的 V1 候选 digest。本轮明确记录这种耦合，未改写已有签名字节；彻底分离需要新版本及生产者、消费者迁移。

## 验证与证据限制

| 本轮本地观察 | 可证明范围 |
| --- | --- |
| kernel 37/37；intelligence／ledger 201/201，另有 1 个 ignored | 已执行的对应包测试；ignored 不计为通过，不能替代完整 Agentd 产品执行。 |
| 67 个 Python 回归通过；规范状态与只读源码 inventory 检查通过 | 证据脚本、拒绝规则、投影一致性及源码标记；部分测试使用明确标注的合成工件。 |
| 最终本地性能 gates 通过；曾发生并发执行失败并保留失败记录 | 对应环境下的 V4 内核 gate 观测；不代表组合请求、writer／witness、目标机容量或稳定 SLO。 |
| 256 次普通 fuzz smoke 与 1024 个 seeded cases | 有限输入烟测；不是 sanitizer 检测、长时间 fuzz 或完整覆盖证明。 |
| 完整 Agentd 本地执行遭 SIGKILL；磁盘 ENOSPC 后已释放空间 | 这些运行不能计为通过；清理空间不产生执行成功证据。 |
| 当前严格 CI 与 source／synthetic-merge／independent 工件协议 | 仍待完整精确候选结果；旧提交结果、本地测试和工作流定义不能替代新候选资格。 |

分配下降是局部实测优化；性能 gate 的成功与失败均应保留。不得把独立 CI 执行改称独立语义评估接受，也不得把干净关闭后重开改称进程崩溃恢复。

## 完成度与剩余工作

本轮修复了上述具体源码缺陷，并同步实现、文档和资格计划。模块尚未完成生产闭合；四个 completion 谓词均保持 `false`。

| 剩余项 | 可验收结果 |
| --- | --- |
| durable handoff | 通过 Agentd owner 持久记录准备、政策提交、run start、context attachment 和交付进度；与唯一 learning ledger 协作恢复。 |
| 版本化 outward receipt | 迁移对外 admission／ack 合同，绑定政策回执与实际交付结果；不静默改变现有 V1 含义。 |
| restart 与 typed domains | 当前权限复验、跨进程单调代际、明确的时间／序列／计数域，以及实际 kill、并发、磁盘与损坏恢复。 |
| legacy migration | 清点和迁移剩余 V1／V2 advisory 消费者，保留必要的显式兼容边界及版本验证。 |
| 目标机与外部接受 | 真实进程请求、组合 p50／p95／p99、容量、witness lag、审计与告警交付、备份恢复及轮换回滚；独立效果评估和操作员接受。 |

经过几轮修正和复审，最后一轮独立复审提出的具体 fixture 问题已修复；在本轮已检查边界内，尚未发现另一项新的具体缺陷。这不等于全局不存在优化空间，也不消除上述实现和证据缺口。下一轮应围绕耐久交接、真实恢复和精确候选资格继续收敛。
