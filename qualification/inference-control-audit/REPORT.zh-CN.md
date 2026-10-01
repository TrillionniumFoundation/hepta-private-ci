# inference.control 对抗审计与完成度报告

本报告归纳 [英文审计记录](REPORT-20261001.md)。审计对象是 V2 开发候选及本轮修复，不是生产验收报告。

## 审计基线与范围

- V2 基线：`0a8c7eea57fdafe36bf72eb59fb4916880a8e278`，开发分支 `codex/inference-control-boundary-capacity-20260929`，草稿 PR #1203。
- 当时 main 为 `a126987b84737dbc2ee2592442a314117bddb4a2`，实现较旧。main、另一条基于 main 的审计分支与 V2 候选不能互代；其源码与 CI 证据也不能混用。
- 修复在 `audit/inference-control-v2-20261001-recovered` 分支完成。首批生产逻辑加固头为 `33e47cfd2eee9f27a7d633bd0a18e7b9ce7fb699`，之后真实 fixture 又揭示完整消息输出遗漏，继续修复该生产行为、测试 fixture、CI／Bazel helper 接线及源码导航。最终验证候选记录在 `VALIDATION.json`。覆盖源码、测试、当前状态清单及投影、技术文档、操作手册、模块 dossier、项目集成边界和已观察的 CI 问题。
- 本轮未证明真实付费 provider 执行、目标设备行为或独立验收，也未授予激活、发布权限。

## 详细技术开发文档是否存在

**存在。** `TECHNICAL.md` 说明职责、契约、持久化、并发、恢复、验证与交付；`CURRENT_STATE_SOURCE.json` 及生成的 `CURRENT_STATE.json`、技术状态和映射记录实际实现；`OPERATIONS.md`、`WRITER_BOUNDARIES.md` 和模块 dossier 补充运维与边界。

但此前这些文档与源码不一致：短锁／并发多个 durable owner 的描述与单一生命周期 writer 不符，兼容实现与 V2 生产调用混写，archive 验证范围、CLI 输入、长期容量及未完成集成也有过度表述。本轮已纠正相关文档和索引。生成页面仍是源清单的投影，不能自己证明执行成功。 本轮共享 Agentd helper／readiness 源码变化也会使下游映射失效，已通过官方迁移刷新有合法祖先来源的相关 owner 映射，包括 cognitive.store、memory.retrieval、memory.federation 和 knowledge.graph；未提升其运行或生产资格。

## 模块位置与完成度

模块拥有 inference request、reservation、receipt；由 native worker／Codex adapter 执行 provider 效果，由唯一 writer actor 串行落账。authority、秘密保管、Neuron 状态、调度及 billing 继续属于各自 owner；provider 等待位于 writer 之外。

| 范围 | 源码／组合状态 | 尚未满足的资格或业务能力 |
| --- | --- | --- |
| 类型化请求、预留与回执 | 已实现 | 内存 ledger、兼容 journal 与 V2 exact-plan 路径须区分 |
| 四角色签名、exact binding、final-use | 已实现并组合到 native worker | 独立密钥保管、撤销传递及目标主机验收 |
| 单 writer、取消、崩溃恢复 | 已实现 | 不重放可能已派发请求；仍需候选故障验证和部署证据 |
| checkpoint／archive compaction | 已实现 | 释放字节空间，未解除累计身份数量上限 |
| provider terminal／usage 恢复 | 签名契约与消费路径已实现 | 可信 provider 事实需独立来源；不能恢复丢失的 Agentd authority |
| scheduler／Neuron／Agentd 接入 | 部分实现 | `inferd::plan` 是纯库；真实调度与 feature port／daemon 生命周期仍缺 |
| 经济与物理资源控制 | 声明、绑定与控制逻辑已实现 | 真实账单、设备压力、local weights 和资源观察证据 |
| 输出保护与保留 | 策略及元数据检查已实现 | vault 实际加密、保管、删除确认及 archive 保留流程 |
| 生产资格／激活／发布 | 未完成 | production、execution-proof、target-host、acceptance、activation、release 均为 false |

## 关键缺陷与修复类别

| 优先级 | 对抗路径或故障 | 本轮修复边界 |
| --- | --- | --- |
| P1 | compaction 换 inode、符号链接与长文件名破坏唯一 writer | 稳定短哈希 sidecar 生命周期锁；拒绝 dangling symlink；维护临时文件短名，保留旧引用 |
| P1 | rename 后异常仍保留过期 descriptor／state | 安装新代期间立即 poison；含非 I/O 错误，完成后才恢复可写 |
| P1 | 跨 owner／重开复用 pre-effect capability | 绑定 owner incarnation；不可从另一实例或重启恢复该能力 |
| P1 | 停止／retired 记录被观察复活，重复 receipt 内容漂移 | shared reducer 与实时消费均复验身份、绑定、状态、完整观察和释放依据 |
| P1 | 同一实际公钥用角色／人员别名满足“独立”签名 | 四 execution 角色实际公钥须不同；dual retirement 校验实际公钥并持久指纹 |
| P1 | 已验证 proof 排队至过期，仍按旧时间应用 | durable 消费重新检查窗口；normal 与 recovery actor 使用 writer 应用时钟 |
| P1 | 反序列化、历史 marker 或 checkpoint 绕过输出策略 | 校验保护字段、TTL、分类、storage、key、digest；audit 与输出 marker 精确绑定 |
| P1 | 超 quota 终态丢失或 worker 返回旧 success | exact binding 匹配且 current output policy 允许该观察时，保存真实 tokens／signed cost，已知终态释放 slot 并 quarantine；策略过期仍需 fresh authorized recovery；返回 durable 资格 |
| P1 | 空加密终态跳过 protector 导致无法落账 | 空 Completed／Failed／Interrupted 也按策略保护；不为未知非终态伪造输出 |
| P1 | signed receipt 伪造 ready 或抹去 authority loss | 保留历史 authority；缺失为 Unverified；不可由 provider 证据 mint ObservedReady |
| P1 | checkpoint 任意 Released／audit 不一致、旧快照虚假 ready | load 校验 state／observation／audit 语义；新写 schema 2，旧 schema 1 保守迁移 |
| P1 | 历史 retirement 只有 IDs，无法证明两实际密钥 | 保留 audit 并 hold Indeterminate；需 fresh revision-bound 审批，超容量重开 fail closed |
| P2 | late usage 倒退／把 denied 升级 success，poison 后幂等成功 | 序号及 tokens／cost 单调，资格只能降级；所有变更先检查 poison |
| P1 | 合法完整 assistant message 只有 completed snapshot、无 delta，worker 成功却输出为空 | 按有界 message identity 归并 started／delta／completed，保持开始顺序，快照补齐文本，重复终态幂等、冲突拒绝；正常与中断 grace 共用状态 |
| P2 | 每次单条状态变更复制所有历史 native 载荷，累计复制成本呈二次增长 | 改为共享完整 Reserve 校验与单 target 暂存；候选／返回值／key 在 append 前准备，sync 成功后仅发布目标及上限；保留有界历史扫描 |
| P2 | feature 失败结果漏 identity 校验，读取无界或 CI 类型不匹配 | 所有结果绑定 encoder/head；实际读取上限加一；修复 Option 引用类型断言 |

最后复审又落地两项增量：

- **重放消费补齐：** 在两处实际 replay 消费点调用 protected-output 结构验证；Observe 要求精确 marker 相等，reconciled checkpoint 的保留元数据也不能绕过验证。过期但结构合法的数据仍可用于删除记账，不能因此重新授权效果。
- **重用对象 fsync：** 遇到已存在且相同的 archive／checkpoint，不能因前次 sync 失败而直接返回成功；重新以可写方式打开并完成文件同步后才成功。

修复尽量保留历史身份与 wire 语义。旧 signed-reconciliation 的 unsupported ready 仅降资格，保留 terminal／usage；旧 retirement 缺独立密钥证明则保持占槽。不能删除 sidecar、手改 journal 或伪造零用量来消除这些不确定性。

## 尚需完成的业务集成与独立证据包

1. 真实 enrolled-worker scheduler、Neuron feature control port 与 Agentd daemon 组合，保留稳定 request identity 和消费者 dedup。
2. 将实际 usage、设备／local-weight 观察连接到独立经济及资源 owner，形成可验账单和资源接受证据。
3. 独立 issuer／final-use 服务的密钥保管、轮换、撤销与效果边界验证。
4. vault 加密与签名删除确认、archive retention／transfer、遥测导出及告警投递。
5. 目标主机真实 provider／设备、进程故障、存储故障、长期压力及容量资格，再完成独立接受、canary、激活和发布。

compaction 不是身份垃圾回收。默认最多保留 16384 个 distinct 请求身份，Released／retired 身份及 legacy events 仍占历史集合；延长寿命需可审计 retention／dedup 协议。重开验证 checkpoint 内容及记录的 archive bindings，不遍历重算整条历史 archive 链。

## 验证状态与结论边界

连续交叉审计的增量修复已落地。最新独立源码复审未发现新的已确认缺陷；这只描述本候选与本轮审计范围，真实业务集成和独立证据仍需后续完成，不能声称所有未来优化已穷尽。

- 最终四包回归及对应源码候选由下表与 `VALIDATION.json` 记录。此前 `ca855069f63ef239c0f15d7c744812aa8552f76e` 的 207 项已全部通过；之后继续落实单记录暂存、私有权限／dispatch 参数结构和测试夹具整理，并新增四项真实回归，最终结果不混用旧候选计数。
- 完整消息归并新增 8 项行为回归，覆盖 snapshot-only、流式补齐、先后顺序、重复／冲突、外来事件、文本／identity／数量上限及越界无部分修改。真实 Agentd fixture 运行实际 Agentd／App Server 和 loopback mock Responses，验证成功输出、final-use 失效及 durable dispatch 边界；该测试使用兼容 `driver.run`，未证明完整生产四签名 `run_authorized` 端到端路径或真实付费 provider。
- fixture 正常准备实际 evidence database、真实 helper 和 App Server initialize／home binding；120 秒冷启动、10 秒健康检查和精确 fixture 的 180 秒 nextest watchdog 与生产 worker RPC／provider 预算分别限定。启动异常／取消时回收所拥有任务。CI 的五条直接 worker-library 入口记录 prerequisite helper build，acceptor 要求该记录；Bazel 接线已审查及格式化，未在本机执行。
- 三组 Python 命令集分别通过 **31、52、41 项**，覆盖 inference artifact／容量／状态、CI scope／repository controls，以及 native feedback／命令记录／consolidated scope。
- ignored compaction soak 首次按旧 60 秒 watchdog 超时，第二次在 600 秒上限也未完成，推进到第 10 代／约 678 个身份；后续单独使用精确 600 秒、无 retry 的维护预算，保持 1024 身份、16 次真实 compaction／reopen 和 fsync 工作量。最终候选的 soak、`just fix`、不带自动修复的严格 Clippy 及文档门禁结果见下表与机器记录；这个预算不证明请求延迟或目标主机性能达标。
- 静态整理明确保留两个公开执行 API 的签名，使用有解释的方法级 arity 豁免；私有函数改用具名绑定结构，测试 fixture 只声明一次，并发测试先启动全部线程再 join。测试夹具初始化的 unwrap 仅在测试范围说明其故障应立即使测试失败，未改变生产错误处理。
- 全局 implementation maps／module docs 门禁保留其它模块的 Cargo 观察漂移与历史来源／祖先关系问题，包括 `cognitive.read` 的非祖先 anchor；本轮未修改 Cargo 清单或锁文件。`verify-bundle` 独立失败于 `kernel.operations: false source or deployment closure`，其状态值不符合该 gate 的允许枚举。未通过伪造其它模块来源或提升资格来消除这些阻塞。
- 当前状态、所有权、actor migration、索引和 40 模块 dossier 检查的最终实测结果分别保存；这些源码／文档检查不能替代 exact-source-head、deterministic base-merge、native-host 或独立验收。所有六项生产资格仍为 false。

冻结验证源码：`7795c04acbc840177508a02fe8d0fb9bac818de2`

| 最终检查 | 结果 |
| --- | --- |
| 四包 Rust 回归 | 211／211 通过；3 ignored；无 retry |
| 独立 compaction soak | 未通过，退出码 100；663.33 秒命令耗时；目标 1024 身份／16 代；无 retry |
| just fix＋独立严格 Clippy | 通过；四包 all-targets／all-features／deny warnings；源未变 |
| Python 三组 | 31／31、52／52、41／41 通过 |
| 格式与 diff 检查 | just fmt、scoped Rust fmt、diff check 通过 |
| 状态／ownership／actor／索引／40-module dossier | 五项通过 |
| 全局 bundle／maps／module docs | 三项失败，保留前述外部模块阻塞 |

两个 ignored pilot 未执行；最终长期 soak 本机未通过，不能声称长时间 compaction 资格完成。 原执行环境和旧失败尝试未混入最终通过计数。
