# 84ee 同一连接预算独立复核

## 结论与范围

固定源码为 `84ee9c2ed0db8b20b792634d775f9b4f97a34578`，树 `6f1d7265ef1a58a0de1cc8da75ce142111743d85`。本审计独立展开实际函数调用、消费式构造和连接计数，不运行测试、实验、actor 或 CI，也不修改源码、超时、连接上限或权限。

在下述明确装配条件下，原公式成立：`b = 11 + 2R`、`Q = 70 + 10R`，同一 Bound B 宿主的 Trainer 连接成功路径需求为 `3(b + Q) + 1 = 244 + 36R`。没有发现重复计算同一次 Execute/Readback。生产客户端和服务端均明确限制原连接请求号为 `1..=128`，因此这些需求无法在该连接内全部成功完成。

**这是静态成功路径需求，不是已经发送或成功处理的帧数。** 实际执行可能更早被期限、撤回、错误或连接上限拒绝。它不能解释原 PublicationFixture 的 S 回调约 600 毫秒或 `PredecessorUnavailable`，也不证明任何研究效益或 owner 资格。

## 必须显式保留的装配条件

1. Root 走真实四 cut `Evaluation::NoUpdate` 的 evaluated-retention 分支，完成 B、S、C 和各自原 Root checkpoint。
2. Version 使用 `from_original_evaluated_owners` 和原 ordinary 服务；S/C 通过其 `bind_original_evaluated_selection_owner`、`bind_original_evaluated_next_use_owner` 构造。
3. Version 保留并复用原 T/B 客户端的同一对 `Arc`；没有重连、连接池或重新发放额度。
4. 被计数的 B 宿主通过 `into_host_from_original_training_readback` 消费真实原 Trainer readback 连接，采用 `Bound` composition。全部 panel 成员和 receipt owner 使用同一个 Trainer 客户端。
5. `244 + 36R` 还要求 Root 的直接 B 请求与 Version 的 B 请求落到同一 Bound B 宿主。四 cut 内容相同本身不能证明这个跨流装配关系。
6. `R` 是完成之后完整六 cut Root readback 的次数，既不是种子数，也不是重试次数。没有错误、取消、额外人工读取；这些只会改变实际终止位置或增加需求。

无需假设第 5 项，也能得到更弱而充分的约束：Version/S/C 的同一 evaluator Arc 单独需要 `Q` 次 B Readback，其 Bound 宿主单 Trainer 连接至少需要 `3Q = 210 + 30R > 128`。这个结论仍然依赖第 4 项的真实 Bound composition。

## Root 直接 B 请求：b

`continue_original` 每完成一个阶段都会调用 `original_attestations` 再 checkpoint。新 evaluated 分支使用一次具体 batch，不额外叠加旧的逐 receipt getter 路径。`evaluated_predecessors` 每次实际调用一个 `read_original_evaluation_with_originals`，其中只有一次 B command。

| 必需阶段 | B command 数 | 动作 |
|---|---:|---|
| B 阶段执行 | 1 | Execute |
| Root 四 cut checkpoint | 1 | Readback |
| S 执行前后 Evaluation | 2 | Readback |
| Root 五 cut checkpoint 的 S 读回 | 2 | Readback |
| C 执行前、Ready 后、结束后的 Evaluation | 3 | Readback |
| Root 六 cut checkpoint 的 C 读回 | 2 | Readback |
| 每次完成后的完整 Root 读回 | 2R | Readback |
| 合计 | 11 + 2R | 只有一个 Execute |

Root gate、watchdog 的本地 Root authority/store 校验没有额外算作 T/B 帧。没有再加旧的 106 次估计。

## Version/S/C 同一对 T/B 客户端：Q

一次 context `require_current` 各读 T/B 一次。Version `read_original` 前后各调用一次，故各两次。S Execute 或 Readback 的原远端后端前后读取 T/B，故各两次；S Evidence 服务仍调用同一个 owner 的真实 Readback。C Execute 或 Readback 前后各读一次 predecessors：每次直接 T/B 一次，再读 S Evidence 一次，所以合计每个 T/B 六次。

| S/C 阶段 | 同一 T/B 各自请求数 |
|---|---:|
| Root S Execute：实际 S Execute + 尾部 S Readback | 4 |
| Root 五 cut checkpoint：S Readback | 2 |
| Root C Execute：开始 S 读回、Ready 后 S 读回、C Execute、尾部 C Readback | 16 |
| Root 六 cut checkpoint：S Readback + C Readback | 8 |
| 每次完成后的完整 Root readback | 8R |
| Q_SC | 30 + 8R |

| Version / 装配工作 | 同一 T/B 各自请求数 |
|---|---:|
| 初次绑定原 predecessor | 1 |
| Prepare：外层当前性、实际 prepare 前后、尾部完整读取 | 5 |
| 原 FinalUse issuer：claim 读取与发请求前读取 | 4 |
| publish：之前读取、实际发布前后、之后读取 | 6 |
| Root 在 publication 后完整 Version 读回 | 2 |
| `run_original_c` 消费配置前完整 Version 读取 | 2 |
| S owner factory 前后完整 Version 读取 | 4 |
| C owner factory 前后 Version 读取及一次 S Evidence | 6 |
| readiness server 构造前后 Version 读取 | 4 |
| S checkpoint、C Execute、C checkpoint 各一次 Version 读取 | 6 |
| 每次完成后的完整 Root readback 的 Version 读取 | 2R |
| Q_V | 40 + 2R |

因此 `Q = Q_SC + Q_V = 70 + 10R`。实际 Task Source/CURRENT 服务以及 readiness 的单纯轮询不自动等于 T/B command；表中没有把这些物理读取重复算成 T/B。额外 Busy/progress 或人工 readback 不能用来减少表内必需成功路径。

## 别名与 128 次上限的源码依据

`prepare_original_circuit_evaluated_retention_v1` 消费原 T/B 客户端，`publish_and_retain_original_evidence` 返回同两个客户端；`publish_original_final_use` 将它们放入 `SharedEvaluatedReadbacks`。S/C factory 克隆这两个既有 Arc。没有在这些步骤创建新 T/B 连接。

Bound B factory 只绑定一次原 Trainer readback 连接，将同一个 Arc 安装到所有 primary/retention 成员。`OriginalPanelTrainingCallV1` 的一次性 proof 只允许 panel 第一、最后两个 slot 做实际 Trainer I/O，中间 slot 校验同一 Arc、完整 Training pin 与原签名。两个 panel 读取共享这次 proof，因此总计两次。内部 receipt owner 的 Readback 仍额外读取 Trainer 一次；Execute 在签发前后共两次。因此 B Readback = 3，B Execute = 4。

`cell_q24_training_command_readback.rs` 的客户端从 `next_request_id = 1` 开始；实际 readback 要求请求号处于 `1..=128`，在 I/O 前消费 peer 并递增。服务端 `cell_q24_training_command_readback_service.rs` 使用 `for request_id in 1..=128_u64`。这两个都是生产路径，未从测试 fixture 的额度推论生产额度。构造阶段不发送握手帧；总式中的 `+1` 是唯一 B Execute 相对 Readback 多读的一次。

原 command channel 还限制会话期限为至多 300 秒、单请求至多 30 秒。独立 S Evidence 的 500 毫秒限制不能错误地套到所有 Trainer readback purpose 上；本审计没有改变任何期限。

## 分母、拓扑与数值检查

| 范围 | R = 0 | R = 1 | 一般式 |
|---|---:|---:|---|
| 同一 Bound B host：Root + Version/S/C | 244 | 280 | 244 + 36R |
| 排除 Root b，仅 Version evaluator Arc 的 Bound host | 210 | 240 | 210 + 30R |
| 原保守子集：b + Q_SC + S factory 的 4 次 | 136 | 166 | 136 + 30R |

默认 `PublicationFixture::ready_for_publication` 经 `HostFixture::from_panel` 选择 `TrainingComposition::Fixture`，构造 `into_original_evaluation_host`，留下 `Individual` training source。其外层真实 SourceBound Trainer 与 B panel 成员的独立 Trainer 证据端点是不同拓扑。`TrainingComposition::Original` 才进入被审计的消费式 Bound factory。不能将两个拓扑的预算相加，也不能把当前静态下界作为旧 S 首次错误的已证根因。

## 最小可研究的同调用切点

最小切点是 **Bound B Host 的 Readback**：既有私有 panel proof 已经在整个 completion 的物理工作两端真实读 Trainer，receipt owner 中间的独立 Trainer 读取仍单独存在。可研究把这个 Readback 分支纳入同一私有、借用式、不可跨调用的 proof，保留实际首尾读取、同一 Arc、完整 Training/签名/时钟、所有 panel/receipt journal/CURRENT 读取及最终 journal 复核。Standalone/Individual 与 Execute 分支不能借此减少原 effect 前后门。

这尚未实现或验证；必须以缺尾读、不同 Arc、撤回、部分 proof、取消等反例验证无半结果返回。即使成功把 B Readback 从 3 减为 2、Execute 仍为 4，全式仍是 `164 + 24R > 128`；只算 Q 也有 `140 + 20R > 128`。所以它只是最小局部切点，不能宣称预算闭合。

第二个既有切点是 Version 的 S factory、C factory、readiness factory：同一个无 effect 调用在外层前后各做一个完整 `read_original`，每个又各读 T/B 前后两次。若能在单一私有调用范围保留每次物理 CURRENT/artifact 工作及全 pin 校验，仅合并同一调用内重复的 T/B窗口，这三处最多另省 Q 的 6 次。与前一项组合仍为 `152 + 24R > 128`。它也不是完整修复。

更大幅度降低需要跨嵌套 owner 调用的明确私有事务协议；现有公共 Evidence 或相同 receipt 内容不提供可跨请求缓存 CURRENT 的权限。本报告不提出增大 128、换端点、放宽 500 毫秒或 300 秒的办法。

## 原件与验证边界

`SOURCE_PINS.json` 列出本次读取的 43 个固定源码 blob、字节数与 SHA-256；所有原字节已与固定 src tree 的 Git blob SHA 重新核对。`AUDIT.json` 保存可复算分项、函数入口、装配假设和待验证边界。本文是静态独立复核，没有新增一次实际执行，没有关闭真实 full-chain/owner/科学资格门。
