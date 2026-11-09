# ACT-2：效果观察、恢复与技能学习资格协议

## 1. 固定基线与结论范围

- 开发基线：M6，`885dae0f3285267e9e9c49d8b43b0d009779f9e8`。
- 基线原件：[固定源码树](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/885dae0f3285267e9e9c49d8b43b0d009779f9e8)。
- 第一阶段：`ActionRuntimeStateV1` 通用观察投影与 Notes 实际产品接点。
- 第二阶段：五组技能组织对照；所有 learned hierarchy 训练和确认结果均为 **NOT_RUN**。
- 本文冻结语义、验收案例与评测边界，不声明尚未产生的测试通过数、真实样本或收益。
- 代码测试、真实服务调用和训练实验必须分别记录；一种证据不能代替另一种。

本阶段的目标是让调用者知道哪些事实已被确认，哪些仍缺少证据。
观察类型不会发放执行权限，也不会扩大原授权、重试范围或可用技能集合。
ACT-1 的有界矩阵不能证明 learned hierarchy 的收益，也不能给出未来错误率为零的保证。

## 2. 五态是事实投影，不是权限或效果凭据

底层必须分别保留 provider、process、goal 与 cancel 的观察事实。
每个事实携带其来源、操作绑定与可用性；未知不能被缺省值替换成肯定事实。
`terminal` 必须带 outcome；进程结束、provider 返回和目标满足不得互相替代。

| 顶层状态 | 支持它的事实 | 不允许的推断 |
|---|---|---|
| running | 已绑定的当前操作确实仍在执行 | 安静或暂时无回执不自动表示运行 |
| waiting-input | 当前操作明确等待其可接收的输入 | `receipt_pending`、网络等待和普通阻塞不是输入等待 |
| partial-effect | 独立目的地观察确认目标的一部分已发生 | 一条成功日志不能证明部分提交 |
| terminal | 操作具有已确认的终局，另列 outcome | terminal 不自动等于成功 |
| UNKNOWN | 必要证据缺失、失效、冲突或无法绑定 | 不能补写成功，也不能据此断言从未发生效果 |

这些事实可能同时存在。例如，部分写入后等待输入必须保留两项事实。
投影选出一个顶层状态时，不能抹去另一事实，也不能隐藏冲突原因。
取消请求、取消已确认和效果已提交必须分开；取消请求本身不能证明没有效果。
进程返回零而 goal 未确认时，不得产生成功 outcome。
学习器的完成概率、duration 预测和残差均不属于 authoritative evidence。

## 3. Notes 产品接点与当前可证明子集

接点为 `notes_thread_tool` 对原 operation 的 `status` / `read` 观察。
效果执行继续沿原 `ProductionDurableWriter`、`FinalUse`、target 与 nonce 约束。
新增观察路径不得创建替代 writer，不得绕过授权链，不得顺带重新执行写入。

Notes 当前采用原子操作 profile；它只能报告有证据支持的 **terminal / UNKNOWN 子集**。
通用类型能够表达另外三态，不表示 Notes 已采集到相应证据。
尤其，`receipt_pending` 表示目的地保留着待退役的回执，不等于进程等待用户输入；
它可以与已提交且仍满足目标的文档同时存在。

成功核对需要同时具备：

1. 原 operation 的既有 durable receipt，且 receipt 与 target、原 operation identity 和操作内容绑定一致。
2. 独立于写入返回值的本次 nonce 关联文档读取，取得当前 revision 与 text 摘要。
3. receipt 所绑定的结果与这次读取的 revision / text 按既有精确契约一致。
4. 原 owner 的保留状态不得与 receipt 矛盾。较早的非终局快照可以与后续合法 receipt 并存；Rejected / RolledBack 与 Applied 的组合不能发布成功。

原 receipt 证明原操作的历史结果，fresh readback 说明当前读取时的文档状态。
两者均需要：旧 receipt 不能证明文档现在仍保持原状；当前 text 匹配也不能独自证明原操作提交过。
如果当前 revision 或 text 已改变，应保留历史 receipt 事实，顶层 runtime 结论保持 UNKNOWN。
可验证的目标不匹配另记为 `current_goal=unsatisfied`；目标身份不符或旧 revision 则仍是 unknown。
这里的 fresh 指本次观察实际重新读取；不承诺读取后文档永远不变。
若服务的读取不具备所需一致性，记录该限制，不能将缓存读取提升为权威当前状态。
部分效果、等待输入或进程运行不能从 Notes 的原子 receipt 状态反向猜出。

当前 Notes profile 没有新增或采集 cancel / tombstone 事实。历史 NotApplied 响应不提供
durable absence proof，也不提供排除迟到提交的 fence。通用 ACT 继续沿用原 owner 的授权、
恢复和终局证据约束，这些通用约束不能替代 Notes 目的地自身的取消或 tombstone 证据。
Notes 的 tombstone 后迟到结果、cancel 与完成竞态专项验收仍为 **HOLD**；第 5 节的对应要求保留不变。

## 4. 身份、恢复与观察顺序

原 operation identity 是恢复的锚点；读取、恢复和重试观察不得换一个新 identity。
target、nonce、goal / 操作摘要和 provider 身份均沿用既有绑定规则。
观察请求没有新的 `FinalUse`，也不产生新的写入许可。

- 响应丢失：先读取原 operation；不得凭 UNKNOWN 再创建一次效果。
- 重启恢复：保留原 identity、receipt 与 tombstone；旧 checkpoint 不替代当前 readback。
- 迟到结果：可补充原操作的历史事实，不得解除 tombstone 或重新开放效果入口。
- 当前文档改变：同时保存“历史提交已确认”和“当前目标未确认”，不能覆盖其中任一项。
- 观察不可用：显式保留 UNKNOWN 与原因；不把连接失败当成没有效果。
- 观察冲突或过期：拒绝其提升成功；若 adapter 具有 revision / 序号契约，按该契约处理乱序。

本次观察不会证明所有外部参与方独立、所有远端读取线性一致，或所有状态无法共同回滚。
这些是独立资格条件，不能通过新增一个状态枚举关闭。

## 5. 第一阶段验收矩阵

下表是要求覆盖的案例，不是已经运行的结果。
结果记录必须包含源码身份、实际调用路径、目的地、原操作身份、观察证据和结论。
只能将确实运行过的案例标为 PASS；未运行、缺少原件和不适用必须分别说明。

| 案例 | 必须观察到的行为 | 范围 |
|---|---|---|
| 原写入完成，receipt 与当前 revision / text 一致 | terminal 成功有两类证据共同支持 | Notes |
| provider 返回成功，但当前 readback 不可用 | UNKNOWN，无新增效果 | Notes |
| 当前 text 匹配，但原 receipt 缺失 | 不得独自签发原操作成功 | Notes |
| 原 receipt 存在，但当前 text 已改变 | 保留历史事实，runtime 为 UNKNOWN，另记目标不匹配 | Notes |
| text 相同但 revision 与原契约不一致 | 不绕过 revision 绑定 | Notes |
| receipt / 观察指向另一 target、nonce 或 operation | 不得接受其完成证据 | Notes |
| 已提交但调用响应丢失 | 同 identity 重新观察，效果计数不增加 | Notes |
| 旧 checkpoint 恢复 | 重新读取当前文档，沿原 receipt / tombstone | Notes |
| 重复 status / read | 只观察，不产生第二次写入 | Notes |
| receipt pending | 不能推导 waiting-input；有原 receipt 且当前目标匹配时可 terminal | Notes |
| tombstone 后迟到结果 | 不重新授权，不重新执行 | Notes |
| cancel 与完成同时存在 | 分别保留 cancel 与提交事实，按原契约投影 | 通用 / Notes |
| 进程退出零，但目标尚未确认 | 不得发布成功 | 通用 |
| 部分效果后等待输入 | 两项事实均保留，目标尚未完成 | 通用 |
| 长计算或网络等待 | 不误判 waiting-input | 通用；需相应 adapter |
| 陈旧、乱序或互相矛盾的观察 | 不覆盖更新事实，不提升成功 | 通用；需序号契约 |

通用状态机测试只能证明被测事实组合的投影行为。
Notes 集成测试还必须经过真实产品 handler 与既有 writer 路径。
模拟 provider 的集成测试需明确标注；它不能冒充真实外部 Notes 服务的在线验收。
测试评价器应独立检查目的地与效果次数，不得仅重复被测成功判断函数。

## 6. 第二阶段技能学习计划（NOT_RUN）

学习输入限定为执行时已经可见的共享语义特征与有界历史。
候选为无状态小 head 或私有小 GRU；输出限定在原允许技能集合内。
可输出技能选择、下一步、交回控制、结束建议与持续时间分布。
训练目标可组合动作模仿、优势加权、duration / termination 预测和近期效果残差。
这是候选计划；本协议不声明已训练、已校准或优于固定策略。

| 编号 | 对照 | 必须保持一致的条件 |
|---|---|---|
| B0 | 原 workflow | 目的地、权限、observer、任务和预算 |
| B1 | 手写 macro | 同上；记录人工规则与调参资源 |
| B2 | flat primitive | 同上；开放相同 primitive 能力 |
| B3 | 无状态 learned hierarchy | 同上；记录训练和选择成本 |
| B4 | 带私有时序状态的 learned hierarchy | 同上；额外计入状态恢复与驻留成本 |

学习器的结束建议只触发交回控制或重新观察；成功仍由原授权链与确定性目标核对决定。
局部后果预测可用于选择重观察时机，但预测不能代替读回，残差小也不是完成凭据。
比较残差触发时，应与固定频率、同预算观察规则比较，避免用额外查询解释收益。
GRU 隐藏状态须按操作 / 会话契约保存或重置，不得携带隐藏评价标签跨越边界。

## 7. 冻结划分、UNKNOWN 与成本

确认集按 destination、tool schema 和组合结构分组冻结，不能随机拆相邻轨迹行。
组合泛化测试应明确哪些 primitive 已见、哪些组合未见。
模型、允许技能库、特征、阈值、成本换算与 evaluator 身份须在确认运行前固定。
评价器及隐藏终局标签不得进入运行时 policy、规划器或 observation 特征。

UNKNOWN 是证据缺失，不能默认当作失败或成功训练标签。
可由独立事后目的地检查补全研究标签，但必须记录补全来源与时间，并隔离在线路径。
未结束 episode 的 duration 保留右删失；未确定的终局保留 missing label。
报告真实成功、成功声明错误、UNKNOWN、partial-effect、重复效果和取消后的残留效果。
分别列出所有 episode 与成功声明的分母，不能只报告已确认成功的子集。

成本至少包含：实际工具调用、readback 查询、重试、推理、状态驻留、恢复、训练与调参。
报告完整完成时间分布及尾部，计入响应丢失、失败、取消和 UNKNOWN 的资源消耗。
若采用净收益，先固定成本换算并报告敏感性；否则比较同预算成功率或同质量总成本。
独立训练重复是学习方差的单位；episode seed 和同操作多次查询不能充当独立训练重复。
统计保留任务组内配对，按独立任务组和训练重复处理相关性。
多候选选择、重复查看确认集和多重比较需要在运行前确定处理规则。
本协议未预设样本量、未来成功率或显著性结果；正式确认前需另行冻结统计计划。

## 8. 晋级与保留条件

工程晋级要求：实际产品观察路径通过对应案例，原效果授权与恢复约束保持有效。
学习晋级要求：独立确认中真实目标成功率或质量—成本前沿达到预先规定的改善条件。
层级更整齐、分段指标更高或终止预测更准，只能作机制诊断。
若未改善实际目标和完整成本，继续保留固定 skill library，学习候选不晋级。

## 9. 研究依据及推断边界

1. Harvey et al., *Unsupervised Hierarchical Skill Discovery*, ICML 2026, PMLR 306。
   [正式页面](https://proceedings.mlr.press/v306/harvey26a.html)；[作者全文](https://www.raillab.org/publication/harvey-2026-unsupervised/harvey-2026-unsupervised.pdf)。
   Appendix C.2.1 明确 Minecraft 的终止分类器不可靠，采用固定时域或隐式子目标；C.3 说明下游 policy 需要动作标签。
   ACT 推断：结构发现和执行资格分开；learned termination 仅提议交回控制。
2. Yang et al., *RECEIPT*, arXiv:2611.01930v1，2026-11-01。
   [全文](https://arxiv.org/html/2611.01930v1)，§3.1–3.3 与 Appendix B.5；[版本元数据](https://arxiv.org/abs/2611.01930v1)。
   原文区分进程等待和任务效果；协议模型约束输入、打断、报告顺序，含单 reader 与原子 recheck/signal 假设。
   ACT 推断：独立保留过程与效果事实，另建目的地核对；不声称继承其全系统证明。
3. Perks et al., *Connectome analysis of a cerebellum-like circuit for sensory prediction*, Nature，2026-09-02。
   [出版社摘要及元数据](https://www.nature.com/articles/s41586-026-10690-6)，Abstract；DOI `10.1038/s41586-026-10690-6`。
   原文提供电鱼小脑样回路中多处可塑性协作进行感觉预测的机制证据。
   ACT 推断：研究局部效果预测与残差触发重观察；它不证明 Hepta 的小 head / GRU 有收益。
