# knowledge.graph 对抗审计与优化报告

审计日期：2026-10-01。仓库：`hepta-private-ci`。
审计基线：`997e7be`；本报告涵盖在该基线上开展的修复与跨模块集成复核。
内核修复提交：`2645829`。最终候选提交与执行日志由协调者在验证后补齐。
报告状态：可审阅草稿；最终验证和独立复核闭环状态见第 7、8 节。

## 1. 审计范围与判断方法

本次审计覆盖声明根 `codex-rs/hepta-kg`，并追踪其真实来源和消费者。
跨所有者检查包括 `hepta-memory` 的 SQLite 投影、恢复、检索，以及
`hepta-prompt-registry`、`hepta-prompt-optimizer` 的关系来源和选择路径。
检查依据为当前源码、原生回归、最新技术文档和规范登记表。
没有以模块目录存在、接口名称存在或文档篇幅推断生产验收完成。

审计按“首次检查—具体复现—修复—独立复查—候选验证”推进。
反例关注公开字段改写后重新计算摘要、来源撤销、过期图、截断与资源乘积。
代码修复保留来源事实和历史证据，不创建第二套事实写入者。
下文的“已修复”描述候选源码行为；执行是否通过以第 7 节记录为准。

## 2. 已有技术开发文档是否详细

结论：基线已经有详细技术开发文档，并非只有接口清单或占位说明。
主要材料为：

- [模块技术指南](../../../docs/modules/knowledge.graph/TECHNICAL.md)。
- [原生实现设计与完成边界](../detail/knowledge.graph.md)。
- `qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json`。
- `codex-rs/hepta-memory/LANE_C_SQLITE.md`。
- 模块登记、来源绑定、契约登记和共同执行语义文档。

技术指南覆盖职责、所有权、来源绑定、契约、持久化、事务、失败恢复、
性能、测试、工作包和激活边界；设计档案明确原生操作和真实调用者。
审计也核对了文档所指的源码及测试，避免只阅读设计目标。

发现的文档问题是部分结构化完成度材料滞后：仍将已有 SQLite 发布、
查询组合列为待实现工作，容易低估实际源码，也可能混淆剩余验收工作。
本候选同步实现资料，补充聚合上限、关系撤销、回执封装和信任边界。
全仓库文档检查中的其他模块漂移单列在第 7 节，未扩写为本模块完成证明。

## 3. 模块在项目中的位置与完成情况

`knowledge.graph` 是可重建投影和关系查询的语义所有者。
它绑定来源切面、generation vector、图配置、节点、边和支持谱系。
它不拥有 cognitive 源事实，不拥有 prompt 因子事实，也不生成写入权限。

| 层次 | 当前事实 | 所有者及边界 |
| --- | --- | --- |
| 确定性内核 | 完整构建、增量参考、发布和单跳查询已有实现 | `hepta-kg` |
| cognitive 来源 | 当前及不可变修订事实提供支持 | `cognitive.store` / `hepta-memory` |
| cognitive 持久化 | 同一 SQLite 事务写投影及语义回执，再推进当前指针 | 既有 cognitive 存储所有者 |
| cognitive 消费 | GraphOneHop 通过 V2 摘要绑定查询 | `cognitive_retrieval.rs` |
| prompt 来源 | registry 所有者提供密封的当前因子关系视图 | `prompt.registry` |
| prompt 消费 | 只读 optimizer 使用冲突、替代及互补关系 | `prompt.optimizer` |
| 产品宿主 | Agentd 默认选择受限 cognitive writer；普通 Codex 默认关闭 | 宿主配置及既有权限边界 |
| 生产与验收 | 尚不能由源码或本次普通测试直接推出完成 | 外部资格及独立验收门槛 |

实际选中的 cognitive writer 每次逻辑变更执行有界完整 generation 重建。
`apply_incremental_delta` 是独立等价 oracle / 参考路径，尚未替换运行时算法。
因此，本报告不将增量接口存在表述为产品正在执行增量更新。

恢复时当前发布回执检查覆盖当前 generation 及其精确前驱。
全部历史发布链回放属于资格验证或取证；历史修订事实仍接受完整摘要检查。
后者本候选采用有界分页，分配空间有界，但总工作仍随保留历史增长。

基线登记中的 `productionImplementation`、`productExecutionProved`、
`independentAcceptance`、`activation` 和 `release` 均为 `false`。
当前候选仍须取得当前 HEAD、确定性 synthetic merge、目标宿主及独立验收证据。
完成度应按上表分别判断；本报告不提供缺乏权重依据的百分比。

## 4. 对抗发现与候选修复

### 4.1 图内核：规范化、撤销、回执和资源

| 编号 | 原始问题及反例 | 候选修复 |
| --- | --- | --- |
| KG-A01 | 重排节点或边后重算 generation 摘要，`validate` 仍通过；有界查询前缀可随之改变 | 恢复/消费验证要求节点与边规范排序 |
| KG-A02 | 相同来源 ID 和修订号使用不同事实摘要，构建器拒绝但恢复验证接受 | 验证器与构建器统一拒绝重复支持身份 |
| KG-A03 | `maximum_edges=1` 仍先复制全部匹配边及支持，再截断 | 扫描统计可见遗漏，只复制保留结果 |
| KG-A04 | 每记录 50,000 支持与大图上限相乘，可产生数十亿支持 | 增加 generation / delta 聚合支持预算及入口检查 |
| KG-A05 | 删除每个节点都扫描全部边，最坏约 65,536 × 262,144 次判断 | 删除身份集合只过滤一次；只复制保留的前驱记录 |
| KG-A06 | 最后来源同时撤销节点和边时，已撤销边先检查端点而报错 | 先验证并移除撤销支持，再检查存活边端点 |
| KG-A07 | 无前驱的初始发布回执可改为 `Unchanged` 并重算摘要 | 初始发布必须为 `Published` |
| KG-A08 | 查询及 delta 身份列表缺少入口上限 | 在去重、排序和深复制之前检查声明上限 |

新的聚合支持预算为 327,680，等于既有最大单支持图的节点加边容量。
SQLite 所有者每 scope 最多 10,000 节点及 50,000 边出现次数，总支持不超过 60,000。
因此，此预算未收紧有效 cognitive 产品切面；prompt 投影每记录只有一个支持。
聚合计数使用溢出检查，完整输入、恢复验证、delta upsert 和最终合并均受约束。
delta 的最终预算检查发生在前驱支持向量复制之前。

时间查询继续保持起点包含、终点排除；遗漏计数只统计真正可见的关系。
存活边指向不存在节点仍失败，撤销处理没有放宽存活关系的完整性要求。
来源切面变化但图、generation vector 和 profile 相同，仍可标记 `Unchanged`。
新来源切面仍绑定在新 generation 及发布回执摘要中；该语义未改变。

### 4.2 cognitive 集成：作用域、重复工作和恢复分配

精确 scope 检索原先先混合授权 scope 排序、截断，再在结果末端过滤。
另一个授权 scope 可以耗尽有限候选预算，导致目标 scope 的有效记忆丢失。
候选修复将 scope 条件推到 FTS、实体和近期记忆通道的 SQL 排序及 LIMIT 之前。
它保留已有授权判断，只修正候选预算的归属。

同一 scope/generation 的 compact support 索引原先在多个 seed 和通道重复加载。
候选修复在同一只读事务内与 canonical generation 一起缓存，避免反复构建。
缓存不跨请求，不跨事务，也不使用过期 generation 替代当前事实。

历史事实恢复验证原先一次 `fetch_all` 全部事实集及全 scope 活跃 shape。
候选修复使用同一只读事务中的 128 条 keyset 分页，单事实集查询带上限。
活跃 shape 使用排序流检查相邻相同实体的 shape 一致性。
全部历史事实仍被验证；这不是将完整检查改成仅检查历史前缀。

### 4.3 prompt 关系生命周期与来源绑定

基线关系主要停留在内存 owner 来源，缺少完整 durable admission / withdrawal 路径。
候选在既有 durable registry 增加 operation-bound final-use 关系登记和持久化。
grant 绑定当前 registry 切面、操作者、scope、精确关系及证据摘要。
缺少、过期、重放或 payload 不匹配的 grant 不能据此登记关系。

关系撤销现保存不可变 withdrawal 谱系，绑定原关系、修订、原因和 grant。
即使两个因子仍 admitted，撤销关系也从后续来源与投影中消失。
已撤销关系 ID 不可重用；替换证据可以使用新的关系身份。
旧元数据缺少关系字段时按空集合读取；恢复继续核验关系与撤销谱系。

prompt 投影通过 V2 generation 摘要绑定 generation vector 与 graph profile。
canonical enumeration 保存 registry owner 发出的原始关系来源摘要。
selection 必须匹配来源切面与 vector，并拒绝图中缺失的候选因子。
exercise 重新检查选择时的 registry 切面，关系单独撤销不能绕过最终使用检查。
enumeration 同时私有保留原始 owner snapshot，拒绝 clone 公开快照重绑定。
完整 selected-output seal 在 exercise 前拒绝追加冲突因子、重算回执及实际 payload 改写。

### 4.4 optimizer 回执与查询入口

原图回执只验证内层已存摘要；改写 selected / decisions / totals 或拼入一个
合法的无图 portfolio，再重算外层摘要，可以逃过原验证。
候选在 portfolio 和图包装回执保留原始输出绑定，并执行嵌套验证。
它拒绝内容改写、内层替换，以及 graph/query 摘要重绑定。
该封装是类型来源和完整性检查，不是对外认证凭据或新增执行权限。

optimizer 候选数限制现先于建图集合和查询，避免超限请求消耗昂贵图处理。
conflict 继续是硬共选排除，substitute 是硬冗余排除。
complement 只绑定观测及回执，不凭关系标签制造未校准的数值收益。

## 5. 保留的信任边界与未声称完成的工作

裸 `KnowledgeGenerationV2` 的字段和内容摘要不能认证提交者或来源事实。
canonical selector 仍只接受登记的可信 owner adapter 提供的裸图。
仅把任意图的 source digest 改成匹配值，不会使它成为真实 registry 投影。
来源保证由密封 `PromptFactorGraphSourceV1` / `PromptFactorProjectionV1` 和
既有持久化所有者提供；本次没有把裸摘要包装成认证能力。

查询仍需验证 generation 并扫描有界边集合；本次未宣称建立新索引服务。
完整重建是否应改为持久化增量写入，需要目标宿主测量和等价资格证据。
PERF-LIBRARY 的 CI 延迟结果不等于目标宿主接受预算。
process-kill / SQLite-WAL 回归不等于物理断电恢复证明。
启动和恢复的新分页实现限制分配空间，不承诺固定的历史验证时间。

## 6. 主要源码与验证身份

- 内核：`hepta-kg/src/generation.rs`、`generation_limits.rs`。
- 对抗回归：`hepta-kg/src/generation_audit_tests.rs`，新增 10 个聚焦用例。
- 来源投影：`hepta-kg/src/prompt_factor.rs`、`prompt_factor_tests.rs`。
- 检索及 scope：`hepta-memory/src/cognitive_retrieval*.rs`。
- 恢复分页：`hepta-memory/src/cognitive_intelligence_writer*.rs`、`cognitive_store*.rs`。
- durable 关系：`hepta-prompt-registry/src/durable_relations*.rs`、`factor_relation.rs`。
- optimizer：`hepta-prompt-optimizer/src/graph*.rs`、`canonical*.rs`、`lib.rs`。
- 既有 oracle：`hepta-memory/src/cognitive_kg_oracle_tests.rs`。
- 崩溃窗口及容量：`cognitive_store_tests.rs`、`cognitive_kg_benchmark_tests.rs`。

以上 crate 路径均相对于 `codex-rs`；文档中的目标规格没有冒充原生 API。
旧迁移夹具版本期待值按基线已有 migration 0015 修正，未削弱撤销断言。
手工构造的旧 prompt enumeration 夹具改用真实 owner enumeration。

## 7. 候选验证记录

最终代码来源提交：`2eba06aef9ecd34e68b6fc3f2567134d8c5e4d43`；
对应 tree：`c926b0210f802ad65264627ff38ce3274ba9270d`。
本地验证发生在提交前的候选源码上；随后 Clippy 只自动修正了测试借用/闭包写法。
这不是完整 exact-head / synthetic-merge 资格回执。

| 检查 | 结果 | 证据与边界 |
| --- | --- | --- |
| 四 crate 联合普通测试 | 399 通过、0 失败、7 默认跳过 | `just test`，KG / memory / prompt registry / prompt optimizer；15.497 秒运行时间不含编译 |
| 对抗回归 | 通过 | canonical 用例包含真实签名旧枚举重绑定、追加冲突因子并重算回执、实际 realization 修改及撤销后顺序修改 |
| child-kill 崩溃窗口 | 通过 | 两个事务窗口恢复精确 predecessor；用例运行 0.545 秒 |
| PERF-LIBRARY 容量探针 | 进行中 | 256 写入、20 查询、5 reopen；单独测量配置，最终结果将在后继报告更新 |
| scoped `just fix` / `just fmt` | 成功 | 四个 crate；fix 自动修改仅涉及测试写法，保留基线 warning |
| strict all-target Clippy | KG、prompt registry、prompt optimizer 通过 | `--all-targets --no-deps -D warnings` |
| memory strict Clippy | 基线 lint 债务保留 | 两个已有 8 参数接口；普通 test lint 还有 schema/production writer 测试警告；未添加 allow 隐藏 |
| Agentd product E2E、exact HEAD / synthetic merge | 本地未执行完整资格 | 保留生产状态 false；交由独立候选资格流水线 |
| development map / module docs | 40 模块通过 | 导航与登记一致性，不证明执行或发布 |
| detailed-design 全局检查 | 失败 | 既有 `inference.control` design digest 漂移 |
| implementation contracts 全局检查 | 失败 | 既有 `kernel.operations` source/deployment closure 声明 |

普通测试使用仓库 `just test` 入口，没有直接 `cargo test`。
共享宿主曾因磁盘耗尽、会话中断及内存不足终止编译；这些尝试没有计为通过。
memory 测试在显式每 crate `codegen-units=8` 下重新构建后完成联合验证。
容量探针在通用 nextest 60 秒 watchdog 下超时，随后使用单独 30 分钟有限 watchdog；
它不是产品延迟接受阈值，也未降低 256 次真实写入的默认负载。

## 8. 独立复查与有界闭环结论

内核初轮修复后，独立复查再次发现最后来源同时撤销节点与边的反例，已修复并通过。
跨模块复查追踪当前 enumeration 与旧图、关系插入/撤销及 exercise 的组合。
后续发现公开 snapshot 重绑定和向 selected result 追加仍存活的冲突因子的反例。
两个反例已通过原始 snapshot/source 配对与完整私有输出 seal 封闭，真实签名回归通过。
最终独立只读复核未发现新的可操作来源切点或 KG 硬约束绕过。

有界结论：在本报告范围、声明的资源上限及可信 owner adapter 假设内，
修复后独立复查未发现新的可复现阻塞问题。
这不等于全局最优、永久没有漏洞、目标宿主验收、激活或发布完成。
容量测量及来源映射验证的最终记录会补入后继报告；生产资格门槛继续保留。
