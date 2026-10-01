# knowledge.graph 第二轮对抗审计与优化

日期：2026-10-01。仓库：`TrillionniumFoundation/hepta-private-ci`。
复核 main：`997e7beef8151160065df36b024bc8da5c989e93`；上一轮候选：
`ef72561919df90202bb10f42a7e9c816d4a32695`。
本轮继续修复同一个 [draft PR #1314](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1314)。
第一、第二修复阶段均已完成，已获得的定向执行结果如下。
最终组件源码观测：`b3b14c25821896eda3c27aaade20196d93b24aee`，
tree `b22babb0050f74e4b27d4ac6ef1518f38f98aee7`。
完整容量重试与最终修复/格式化门禁已完成；真实产品 E2E 的宿主阻塞如下。
局部执行结果不计为完整 HEAD/synthetic merge、目标宿主或发布资格。

## 1. 结论与完成边界

项目已有详细技术开发文档：模块指南、原生实现档案、结构化实现 profile、
SQLite 所有者说明、源码绑定和验证契约共同覆盖设计与开发步骤。
文档的主要不足是部分消费语义、来源种类和完成证据需要更精确区分，
并非缺少开发文档。

`knowledge.graph` 处于来源事实和产品消费者之间，拥有可重建图的语义、
generation/publication 摘要、支持谱系及单跳查询规则。
`cognitive.store` 保留 SQLite 和事实事务所有权；`prompt.registry` 保留
因子和关系所有权；optimizer 只产生 `DENY_ALL` 的选择建议。
本轮优先修复这三个边界之间可复现的绕过，再优化保持摘要不变的本地处理。

| 层次 | 完成判断 | 保留边界 |
| --- | --- | --- |
| 图内核 | 完整/增量参考构建、发布、查询已有实现与回归 | 一跳查询；增量算法仍未成为实际 durable writer |
| cognitive 存储 | 同事务发布、摘要恢复、scope 检索和历史校验已有实现 | 总验证工作随保留历史增长 |
| prompt 来源及消费 | 密封 owner 源、投影、治理关系和 canonical 消费已组合到源码 | 签名 utility 必须绑定实际模型及 realization；建议不授予效应权限 |
| 开发文档 | 详细且可导航；本轮补来源矩阵、两种 selector 和时效语义 | 设计目标不能代替产品接入或执行证明 |
| 生产完成度 | 当前无法宣称生产/验收完成 | 当前 HEAD/merge、目标宿主与独立验收门槛仍保留；本轮本地完整写/读/reopen 探针已通过 |

不提供没有权重依据的百分比。所有 production、product-execution、
activation、acceptance、release 声明继续为 false。

## 2. 新的对抗发现与修复

| 编号 | 真实反例 | 修复边界 |
| --- | --- | --- |
| R2-01 | 复制真实图的 source/vector，删除 Conflicts 边后重新构建合法裸图；selector 可签发选择双方的私有结果 | canonical 输入收窄为密封 `PromptFactorProjectionV1`，核对原 owner snapshot/revision/source/vector |
| R2-02 | 改 authentic enumeration 的实际 token cost 或 priced row 的 cost/net utility；旧签名和缓存摘要仍可被消费 | enumeration、pricing 分层完整私有 seal，实际 realization、行、会计、排序和身份都纳入验证 |
| R2-03 | objective B 的合法 enumeration 使用 objective A 的签名 verifier 和证明 | price/select 显式核对当前 verifier 与 enumeration objective |
| R2-04 | price 时有效的签名在过期或同一 trust snapshot 的定时撤销后仍被 select 复用；exercise 时钟可回退到选择之前 | 私有保留 ≤129 个 completeness/pricing 证明、canonical payload、admission time/trust digest；select 重验当前时间及 `valid_until - 1`。私有 `selected_at_unix_ms` 纳入 output seal，非空选集的回退 exercise 返回 `RejectStale` |
| R2-05 | 同一 signer 兼 Generator/Evaluator，或两个 key 属于同 controller，可自证候选与 utility | 使用既有独立角色校验；每个 Evaluator 与 completeness Generator 独立，不要求所有评估行互相独立 |
| R2-06 | 模型 A 的 pair utility 给模型 B 使用；同 factor 的旧 realization 价格给替换 realization 使用 | 正式 price/select 采用 `PromptPricingEvidenceV2` / `PromptPairUtilityEvidenceV2`：绑定完整候选 receipt、实际 realization digest，pair 另绑定 model tuple 与左右实际 bindings。V2 使用独立 signing domains；历史 V1 类型及 payload 字节保持，正式入口没有 V1 fallback |
| R2-07 | raw utility 扣成本后使用原始 confidence interval，区间可不包含净估计 | 在 `i128` 计算 `bound.raw - raw_utility.raw + net_utility.raw`，检查结果可表示为 `i64` Q32；两个端点与 utility 同成本平移，保留历史 confidence 准入规则 |
| R2-08 | 修改历史 revision 2 的 KG 有效区间为来源区间的子集，恢复触发器，reopen 仍接受 | 对全部保留实体/关系要求与不可变 memory revision 的 nullable 区间精确相等 |
| R2-09 | 128 行分页仍能解码单个无限长 source/memory ID | 在 KG 头和 shape 解码前用 SQL 标量预检 ≤128 UTF-8 字节，保留原生/历史 74 字节 ID |
| R2-10 | temporal 结果只需一个支持，仍复制并保留数万个过期支持的容量 | 先从借用支持过滤可见项，再复制；完整结构查询保持全部支持 |

源码、真实签名回归和独立复查分开记录。typed seal 是安全 Rust API 内的
构造与内容约束，不是远端认证凭据；裸 generation 摘要仍不能认证来源。

R2-06 的 individual V2 签名域为
`hepta.prompt-optimizer.pricing-evidence.v2`：`candidate_set_digest` 精确绑定
enumeration 的 `receipt.receipt_digest`，`binding_digest` 绑定被评估 factor
的实际 realization。pair V2 签名域为
`hepta.prompt-optimizer.pair-utility-evidence.v2`：除既有 graph generation、
state、edge validity 外，绑定 model-tuple digest 和按左右 factor 方向排列的
actual binding digests。历史 V1 域仍可解读原证明，不能作为 V2 的正式准入。

选集有效期取 request、completeness/pricing/pair 证明和已选 realization
期限的最小值，并对已知定时撤销在最后包含的毫秒再次验证。
`exercise_v1` 仍检查当前 registry owner、私有选集 seal 与 expiry，
只产生 typed `DENY_ALL` proposal；它没有 fresh learning verifier，
不能检测未知的后续 ledger trust rotation。最终 effect 仍需 fresh trust
与自身 final-use grant。

## 3. 与项目位置有关的优化

同一个 cognitive source cut 原先反复计算 entity kind/payload、relation kind、
以及每条边的两端 occurrence ID。现在只在该有界切面内复用这些纯计算，
每个物理事实的来源、修订和有效期摘要仍独立绑定。

产品 query-cut 使用同一加载 core 一次产生 canonical generation 和 compact
支持索引，复用已经计算的边 ID，移除第三次 selected-head 扫描。
generation-only 的 reopen/writer 不分配支持索引；legacy `kg_edges` fallback、
容量检查、重复 occurrence 拒绝及语义回执校验保持有效。
缓存仍只存在于同一检索事务，未引入全局缓存、第二个存储所有者或新索引服务。

历史验证仍为 O(retained history)。ID 预检约束 Rust-owned KG 行物化，
不声称约束 SQLite 内部所有分配或任意外部 raw SQL 并发修改。
完整重建改为 durable incremental writer 仍需目标宿主预算和完整等价资格。

## 4. 文档修正

- cognitive 的存储 relation label 映为稳定 `Custom`，不自动成为内核闭集关系。
- 密封 prompt owner 当前只生产 Complements、Substitutes、Conflicts；
  Requires、Dominates、Redundant、Supersedes 的算法测试不构成已登记 owner 来源。
- legacy graph wrapper 请求完整内核边容量，Substitutes 为硬排除；
  canonical selector 限制为 128 候选、16 选择、512 interactions，
  Complements/Substitutes 的 numeric utility 来自独立签名证据。
- 第一轮 read-capacity 绑定历史源码 `992c3a90`，不能作为本轮 HEAD/merge 证明。
- 正式 evaluator evidence 使用 V2 realization/model 绑定；V1 历史 payload
  不改语义，confidence 端点转换到与净 utility 相同的成本域。
- 第二轮 read-capacity 绑定 `8b459fae` 的已提交 KG/memory 源码，
  其原始观测与本轮最终 prompt/HEAD 资格分开记录。
- map 的“already-qualified incremental”修正为已实现等价参考路径。

## 5. 上一轮 CI 的归因与门禁修复

上一轮 blocking-ci 的 repo-checks 在特权 caller 闭集检查失败：
新增 `durable_relations.rs` 漏登记。这是本次引入的集成问题，已精确补登记。
同时校验原有清单揭示既有 `final_use` receiver、async method/FQ 调用漏扫、
独立清单错误转义、遗漏方法分类和过期路径。补充精确分类及未知 caller
负向回归；扫描器、根目录、忽略规则和 deny-all 规则未放宽。

architecture source-head 在 runtime executable 检查失败，原因是未接入的
测试模块使命令 exit 0 却运行 0 个测试。接入四个既有测试到私有 test-only
模块，保留 minimum-tests 门槛；没有由此声称该 helper 已生产接入。
vertical-slice 的旧 cleanup 名称断言也改为检查当前 `RuntimeTasks` 的真实
构建、运行、shutdown、取消和有界 join 路径，保留原 readiness 断言。

SDK Bazel 失败的已读取日志显示 `rules_autoconf-v0.0.14.tar.gz` 下载
HTTP 500，analysis 阶段中止；该失败没有提供本次 Rust 编译结果。
CI 的 base-merge 绿色作业跳过了 native steps，不能用作 native merge 证明。

## 6. 本轮验证与测量

第一阶段完成来源投影、input/output seals、objective/time/trust、角色独立性
和 cognitive 历史/资源边界修复；第二阶段完成 V2 evaluator evidence 与
净 confidence 平移。独立 kernel 对冻结实现的终审未发现新的可复现问题。

| 定向验证 | 已取得结果 | 证据边界 |
| --- | --- | --- |
| 第二阶段 prompt.optimizer + prompt.registry | 106/106 通过 | 包括真实 owner/model/realization、签名及 V2 replay 回归；属于本地定向执行 |
| knowledge.graph 内核 | 33/33 通过 | 内核语义与查询回归；不代替产品 E2E |
| memory 普通测试 | 278/278 通过，8 个默认跳过 | 默认跳过不计为容量或 crash qualification 成功 |
| CI 同款 Python 命令链 | caller 自检/闭集校验及 29 项 QA 通过 | 未放宽 scanner 或 deny-all；不代替 native HEAD/merge CI |
| Agentd + Intelligence 下游 library 验证 | 12/12 通过 | 不代替真实产品 E2E |
| 三项真实产品 E2E | 完成编译并实际执行：1 通过、2 失败，1.059 s | 存储不可用时拒绝启动通过；mutation/recall 和双 Agent 隔离在 readiness 前因 Unix 控制 socket `EPERM` 被宿主阻挡，未执行成功链 |
| 本轮完整 capacity | 首次 841.882 s 在写入阶段 disk full 失败；重试 1269.858 s 通过全部 256 writes、20 queries、5 reopen | 完整默认夹具的本地执行通过；不是目标宿主预算或最终 HEAD/merge 资格 |
| 最终修复/门禁 | 五个受影响 crate 的 `just fix`、限定差异的 `just fmt` 成功；KG/registry/optimizer all-target `-D warnings` 通过 | 宽 owner 范围仍有 memory/Agentd 既有 warnings；未放宽规则，不宣称全部仓库 lint 绿色 |

上述通过项是定向本地执行证据。组件执行源码观测为 `be4004a11e`；
最终格式化源码观测为 `856dbd4f5c`。Clippy fix 未自动修改源码，只有两个
测试中的 pair clone 改为借用及 Rustfmt 布局变化。按照仓库 AGENTS 规则，
最终 fix/fmt 后没有重新运行 Rust 测试；容量进程在此前已启动，使用既有
编译二进制完成，memory 算法与事实语义未改。完整当前 HEAD/synthetic merge
CI、目标宿主与独立验收仍保留门槛，具体结果见本地执行 JSON。

上述磁盘失败以及随后测试支持库的 `StableCrateId` 冲突、缺失 `rlib`
构建产物均保留在 [本地执行记录](knowledge.graph-local-validation-2026-10-01-round2.json)
中。主验证流程对相关 package 执行定向 Cargo cache 清理，未修改依赖或
源码以绕过这些构建错误。主验证流程已清理不活动的重复缓存，
释放约 2.7 GB，并把重试改为先真实 E2E、后完整容量的顺序执行；
资源清理和重试计划均不计为成功结果。E2E 最后完成了真实
编译与运行：存储不可用时拒绝启动通过；两个正向链在 Agentd 绑定 Unix
控制 socket 时收到 `EPERM`，于 readiness 前失败。保持测试与 sandbox
权限规则，未跳过用例或将此失败改记为通过；后续需允许该 socket 的宿主
与仓库原生 CI 给出独立执行结果。

本轮读探针复用同一个真实 256-write fixture，执行 20 产品查询和 5 ordinary
reopen，检查 source/generation/publication 及物理输出摘要一致。
仍是 4096/32768 物理支持出现次数投影为 16/128 canonical records 的
支持密集夹具；不把它写成 4096 个独立 canonical nodes 的容量证明。

第二轮 [read-capacity JSON](knowledge.graph-read-capacity-2026-10-01-round2.json)
绑定已提交 KG/memory source
`8b459faeaa2c772d56404425de4deeb07c46bc3c`，其 source/generation/publication/
physical 摘要及 20/5 样本数与
[第一轮 receipt](knowledge.graph-read-capacity-2026-10-01.json) 一致。
原始观测如下，单位为秒；两次 p99 均与各自 p95 相同。

| 测量源码 | query p50 | query p95 | ordinary reopen p50 | ordinary reopen p95 |
| --- | ---: | ---: | ---: | ---: |
| 第一轮 `992c3a90` | 5.482285356 | 5.744929233 | 14.173021219 | 15.982671923 |
| 第二轮 `8b459fae` | 3.508694118 | 4.107741552 | 11.088318591 | 11.780440358 |

这是同一 source cut 在共享且存在竞争的宿主上的原始观测，使用
unoptimized test profile（`debug = 0`、`opt-level = 0`）。没有受控的完整
前后实验，因此不宣称提速倍数或目标宿主预算接受。读探针不包含新写入，
不能证明完整 write-capacity 成功；其测量 source 之外的最终 prompt/doc
改动和完整 HEAD/merge 资格也不在该 receipt 的证明范围内。

本轮 [完整容量 receipt](knowledge.graph-full-capacity-2026-10-01-round2.json)
另外记录原始 mutation p50/p95 为 4.642611383/8.196905699 s，
256 次写入总计 1147.652705313 s；query p50/p95 为
3.377370820/3.717962550 s，reopen p50/p95 为
10.804119826/11.428328621 s。运行约 21.2 分钟，总过程计时包含全部写、查询
与 reopen。完整 receipt 没有输出 source-cut 摘要，不能据此推断与只读
receipt 的摘要一致；它保留的是同一 fixture 定义下的实际完整执行结果。
夹具、共享宿主及 unoptimized profile 限制仍适用，不宣称受控提速倍数。

## 7. 收敛与后续资格

本轮反例按来源认证、typed seal、签名上下文/时效/独立性、数值会计、
历史语义及资源展开多次独立复查。只在确认具体反例或可保持语义的局部
收益后改源码，不以“永远无漏洞”或“全局最优”作为可证明结论。
两阶段修复已完成，冻结源码的独立 kernel 终审和本轮限定攻击面的复查
没有留下新的可复现、可立即实施的问题。用户要求的“直到没有新的优化
意见”在本次审计中只能解释为该限定范围内的 **no-new actionable**，
不是永远无新漏洞、穷尽所有输入或全局最优的证明；后续执行门禁仍可能
揭示需要继续修复的问题。

第一轮完整写容量尝试完成 256 次写入后在 query 阶段触发 30 分钟 watchdog，
本轮首次完整容量在写入阶段因磁盘满失败；两次历史失败分别保留。
本轮独立重试实际通过完整默认夹具，不能将其倒写为旧尝试的成功。
目标宿主、产品正向 E2E、独立验收、
激活与发布仍需各自证明；本次不合并 main、不发布、不提升完成 flags。

宽 scope 的两个既有 memory `too_many_arguments` 与 Agentd 未接入的
learning/plasticity、旧测试 lint 仍属于各自 owner 的门禁；没有为刷绿增加
allow/ignore 或接入新的效应权限。全仓既有失效源码锚点也不能通过刷新
未审模块来洗成通过。本轮只重绑定五个直接涉及模块的真实源码观察。

最终源码候选观察为 `ca4f672c81e30aeaa8a89cdd267b40f0cae9fb4f`，
tree `c731cbba7d07844d5cc1aa268d639f4dddc15441`。原生 migrate 只检查上述
五个模块，实际更新四张需要刷新的 map，registry 的有效锚点保持不变。
五张 map 的严格源码身份及现有 sourceObjects 与 HEAD 核对全部通过；
KG 的 manifest 覆盖 70 个源码/见证对象。40 个模块的开发文档、档案和
开发模式 map 导航通过；全仓 qualification 模式仍明确失败于 21 个
其他 owner 的既有失效锚点。以上只证明源码身份和文档导航，不能代替
本候选的产品执行或验收资格。具体锚点、对象数和失败列表见本地执行 JSON。

最终 draft 推送 `a89e97a1` 后，新 CI 揭示一个本轮接入 test-only 模块
才暴露的 Rustfmt 差异：`runtime_executable.rs` 的一处换行。已在
`b3b14c25821896eda3c27aaade20196d93b24aee` 修正布局及可选尾逗号，
限定 `just fmt` 和 CI 同款全 workspace Rust format check 均通过；
没有重跑 Rust 测试或改变行为。此前 `856dbd` 的格式化观察保持为历史记录。

同一 CI 的 Python formatter 另报告 51 个旧文件，逐个核对与审阅 main
的 Git blob 完全相同；没有全仓刷格式。Python SDK 127 通过/4 失败/38
跳过，四失败来自旧 root formatter 断言和未安装 git 的 slim 容器；
相关测试、formatter、workflow 和依赖配置与 main 相同。Windows Bazel
Clippy 在 wrapper 报 `python3: Argument list too long`，尚无 Rust action
失败证据。其余 native 作业仍在运行，base-merge success 的作业跳过了
native 执行；此 CI 观察不构成修复后完整 HEAD/merge 或生产资格。
