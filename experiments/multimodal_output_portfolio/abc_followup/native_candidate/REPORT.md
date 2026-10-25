# Sequence 802 未来预测候选：构造来源之外的真实分支评价

## 结论

本补充已完成两个真实原生提案的构造来源外评价：固定原 future-correctness head 及其 sequence 802 的两项更新，在完整 1000 个来源对上重新执行 2000 个未来生成分支，比较 6000 次已提前提交的预测。**两项更新的 raw Brier 改善点估计很小，预定的两个 97.5% 来源对 bootstrap 区间均跨过零；没有证实正的预测收益。** 冻结校准后的概率、分组、分类和 0.75 概率阈值结果均为零行变化。因此，本轮补齐了候选的构造外评价证据，候选具有可利用收益这一科学问题仍未闭合。[完整结果](RESULTS.json)

本轮使用的全部来源已在项目的 training_repair 实验中被观察过。这里有 1000 个配对比较单位，**项目新增独立来源数为零**；不能把它与 repair 结果当作独立重复实验相加。候选在 repair 首次正式访问来源之前已经生成并完成历史评价，且本次新分支的全部预测均先于实际未来生成提交。这个更窄的来源与时间线范围见下文。[登记协议](PROTOCOL.json)、[复用登记](REUSE_ASSIGNMENT-v2.json)

## 1. 固定对象与实际执行范围

本轮接续 [原生未来预测及同上下文提案报告](../native/REPORT.md)。原 future-correctness head 的结构为 478→64→33，最后一维输出未来联合正确性的 raw 概率，另外 32 维输出未来公开状态。基线 weights SHA 为 `95d6fade17c609457cb6b978d6580a37fb3bdd02aafa125d964c60c48dd4cc0c`，候选文件 SHA 为 `409221dd6f892e3ccf0f317c4c4d86dc9cf9bcf68651c016349515094fa2dd24`。

两项更新来自同一个真实 admitted ID tick：sequence 802，pair 1768，anchor `e5e24dce4b89626b281def5f6c2af89a5df7e05c7d2c732b2a6bd1f98e5a46c4`。本轮保留基线以及两个候选的原始身份、参数、幅度和顺序，未重训、重新拟合、重新校准、放大更新或择优。候选只是局部确定性 typed 规则所产生的参数变化，不能据此称为未来任务损失的梯度或最优学习更新。[候选绑定与完整代码 pins](PROTOCOL.json)

| 固定对象 | ID 尾部的识别前缀 | 改动参数数 | 最大绝对 Q32 增量 |
| --- | --- | ---: | ---: |
| NoChange 基线 | `9058ec1051…` | 0 | 0 |
| 更新 A | `a37048291f…` | 26 | 369690 |
| 更新 B | `fdd02ddb19…` | 23 | 184845 |

两项更新仅允许修改 `w2[32][j]`、`0≤j<33`，保留整行其余列、其他状态行及全部 bias。实际前向验证确认，两候选改变 raw correctness 概率，但 32 维未来状态预测逐值不变。三个 head 观察同一对真实未来输出；生成器本身没有被候选修改，因此本实验不估计生成内容的因果改善，也没有把候选应用到原生部署。[边界检查](PREACCESS_CHECKS.json)、[实际结果](RESULTS.json)

## 2. 来源复用与前瞻时间线

原始 manifest 中 `unallocated_test` 的完整 2000 个个体来源，已合法登记为 repair 的 `repair_test`，按原顺序相邻两项组成 1000 个不放回来源对。本轮建立独立的 `native_candidate_reuse` 登记及 access-registration，仍要求原始分配、原 20 个模型的完整执行记录和模型身份检查通过；没有修改原 loader 或拿旧 access 冒充新实验授权。所有实际行逐项核对原 manifest 的来源 ID。[新增 guard](source_guard.py)、[复用登记](REUSE_ASSIGNMENT-v2.json)

来源与视图在本轮看到新分支结果之前全部冻结：pairs 0–499 为五种 ID 视图各 100 对，依次为 clean、noise、occlusion、missing_trusted、conflict_untrusted；pairs 500–999 为 both_missing。这个分配沿用原 native calibration 的均衡设计，未按 repair 的逐视图表现筛选来源或分配权重。全部 1000 对都进入主分析。[协议](PROTOCOL.json)

候选历史评价的进程在 **08:55:28.244689 UTC** 注册；其实际完成结果和整个 native 执行完成 receipt 已存在，后者本地文件 mtime 为 **08:55:33.124679 UTC**。repair 首次正式来源访问登记为 **09:01:46.858274 UTC**，相隔约 373.734 秒。固定 proposal/hook 只读取原 native test 上下文和冻结权重；历史 evaluator 只读 development。时间线记录绑定这些实际文件及冻结调用路径。[时间线 v2](TIMELINE-v2.json)

这些是本地过程登记、完成产物和文件系统时间，不是外部签署的可信时钟。旧 process registration 写入并关闭，但没有 fsync；它也不是“已经完成消费”的上界。本轮在新来源访问前保留 v1 字节并用 v2 修正这两处措辞，未改变候选、来源或统计方法。[v1 记录](TIMELINE.json)、[v2 记录](TIMELINE-v2.json)

全部 18 个冻结文件已在 GitHub commit `5f67ed90455e63cca697ff7f8fd9694fc42abccf` 发布并由 coordinator 核对完整 tree `f1029dc3d790ebe1f730978edb3c3cfceaba8aec` 后，本轮才开始采集。新 access-registration 为 **09:28:20.524040 UTC**，绑定 protocol SHA `36a8af4745be2523f22f49000f9d6813a8c09d075e1611573a81c59b7d38de3c`。发布后没有改动冻结代码、协议、候选、权重或校准。[冻结清单](FREEZE_READY.json)、[实际访问与执行 receipt](EXECUTION_RECEIPTS.json)

## 3. 实际未来生成、评分与统计单位

每个来源对先实际执行 `initialize → refine_image`，产生共同的公开 prefix。随后对 `refine_text` 和 `couple` 两个动作分别构造公开条件输入，计算三个 head 的预测，并把两份包含全部三头预测的 NPZ 文件写入、flush、fsync。两份文件都完成后，才为任一未来动作创建相应 RNG 并实际生成。记录中的 commit 时间在 fsync 返回之后获取。[collector](collect.py)

未来图像和文字被实际保存后重新打开，首先逐值核对 PNG 像素与渲染文本等于实际生成内容，再由冻结的独立 observer 对真实媒体和原任务目标评分。联合正确标签要求 caption 合法，文字事实、关系、图像事实和跨模态分歧四项均为零。分析还重新打开所有媒体，重新编码公开状态，核对全部 committed predictions 与冻结 head 的重新计算结果。[数据边界](boundaries.py)

实际审计结果为 1000 来源对、2000 个唯一来源 ID、2000 个实际未来输出、6000 个预测、72 份提交文件。每对保留两个动作与三个 head 的相关性；没有把重放行数或 head 数当作独立样本数。[结果审计](RESULTS.json)

主比较对每个来源对计算两动作平均 raw Brier 损失之差：

\[
d_{i,k}=\frac12\sum_{a\in\{\mathrm{refine\_text},\mathrm{couple}\}}
\left[(p_{i,a,0}-y_{i,a})^2-(p_{i,a,k}-y_{i,a})^2\right].
\]

两个固定比较共享 4000 次整来源对重采样。每个两侧 percentile 区间取 0.0125 与 0.9875 分位数，对这两个预定比较提供名义 Bonferroni family 95% 范围。这不是统一覆盖整个项目历轮探索的错误率保证；跨研究使用同一来源的依赖仍必须保留。[analysis](analysis.py)

## 4. 结果与实际影响

基线 raw Brier 为 **0.06985258066015955**。

| 候选 | 候选 raw Brier | 平均改善（基线减候选） | 预定 97.5% 来源对区间 | 区间下界为正 |
| --- | ---: | ---: | --- | --- |
| A | 0.06985234236498808 | +2.382951715×10⁻⁷ | [−1.404108721×10⁻⁷, +6.238100877×10⁻⁷] | 否 |
| B | 0.06985246150740282 | +1.191527567×10⁻⁷ | [−7.019601528×10⁻⁸, +3.119094979×10⁻⁷] | 否 |

两候选最大的单行 raw 概率变化分别为 **4.27420×10⁻⁵** 与 **2.13709×10⁻⁵**。对 2000 个实际分支，raw 分类变化为 0；冻结校准分组变化为 0；冻结校准概率变化为 0；校准后分类变化和 `p≥0.75` 阈值变化也都是 0。后一个指标只是冻结概率阈值，本轮没有重新执行 updated-head native tick，不能称为实际 native admission 的变化。[完整结果](RESULTS.json)

以下为预声明的描述性分层，不增加主检验或支持事后挑选候选：

| 来源分层 | 来源对 | 实际联合正确率 | A 的 raw Brier 改善 | B 的 raw Brier 改善 |
| --- | ---: | ---: | ---: | ---: |
| 五视图 ID 合计 | 500 | 83.0% | +4.76930×10⁻⁷ | +2.38475×10⁻⁷ |
| both_missing | 500 | 0.1% | −3.39953×10⁻¹⁰ | −1.69968×10⁻¹⁰ |
| clean | 100 | 84.5% | +2.83289×10⁻⁸ | +1.41748×10⁻⁸ |
| noise | 100 | 83.5% | +3.73253×10⁻⁷ | +1.86641×10⁻⁷ |
| occlusion | 100 | 76.0% | +2.02530×10⁻⁶ | +1.01266×10⁻⁶ |
| missing_trusted | 100 | 85.0% | +1.03234×10⁻⁷ | +5.16337×10⁻⁸ |
| conflict_untrusted | 100 | 86.0% | −1.45468×10⁻⁷ | −7.27297×10⁻⁸ |

这些正确率来自同一冻结独立 observer，不是人类评审或签署的生产 evaluator。三个 head 冻结校准后的 pooled ECE 完全相同：全体 0.00924493，ID 0.01824297，absence 0.00024688。五个 ID 单视图 ECE 约为 0.0429–0.0529，说明 pooled 数字不能扩展成每个子群均满足校准门槛的保证。[分层完整数据](RESULTS.json)

32 维未来状态预测在三个 head 中相同。其描述性 MSE 为 0.11064888，对应 persistence 0.18801514；ID MSE 为 0.02715669，对应 persistence 0.03162468；absence MSE 为 0.19414107，对应 persistence 0.34440559。这些是原状态预测器在本批实际未来上的观测，不是 correctness-only 更新带来的状态改善，也不是本轮另加的独立资格检验。[完整结果](RESULTS.json)

## 5. 验证与完整成本范围

冻结前实际通过 12 项 focused checks，包括错来源/动作/视图/标签拒绝、保留两动作相关性的 bootstrap 检查，以及 32 个已用 historical public inputs 上真实冻结候选的 forward。另有 4 个 source guard unittest，覆盖原 20-model 完成边界、新 access 必需性、role/census/协议拒绝及禁止覆盖。两组均由同一 exact-child wrapper 执行，未物化本轮来源。[检查](PREACCESS_CHECKS.json)、[检查 receipt](CHECK_PROCESS_RECEIPTS.json)

执行后，另一 agent 只读核对了 42 个代码 pins、12 个输入 pins、全部来源与行数、72 份实际提交文件和 4000 个 PNG/UTF-8 文件 hash，并独立重算每对 Brier 改善。两份提交全部完成到首个 future transition 记录之间的最小间距为 1562 ns。该 reviewer 参与了 source guard 与历史 candidate evaluator 的实现，未重跑本次生成或 bootstrap；这里的审阅是有明确作者参与范围的数据一致性检查，不能扩展为完全独立的端到端复现，也不增加 N。[只读审计记录](INDEPENDENT_AUDIT.json)

| 实际阶段 | wall 秒 | child CPU 秒 | exact-child peak RSS bytes |
| --- | ---: | ---: | ---: |
| 预访问数据与真实历史 forward 检查 | 1.934870 | 1.925215 | 305270784 |
| source guard 检查 | 0.110022 | 0.107002 | 21569536 |
| 完整采集、三头预测、实际生成与评分 | 8.989925 | 8.919399 | 356888576 |
| 完整媒体/提交审计与统计分析 | 3.794168 | 3.786655 | 282533888 |

采集与分析合计 **12.784094 wall 秒、12.706054 child CPU 秒**；加上预访问检查合计 **14.828986 wall 秒、14.738271 child CPU 秒**。全部退出码为零。每个子进程以 Linux `wait4` 精确采样，BLAS/OMP/MKL 与 torch 均限制为单线程。采集及分析期间同一宿主上的时序实验仍在运行，已通知并记录重叠，未删除或调整任何计时。[执行 receipt](EXECUTION_RECEIPTS.json)

本补充追加训练步数为零；成本不包含既有生成器/预测器训练、原 native proposal 构造、repair 研究、代码编写、元数据整理及独立只读审阅。表中 wall 总和不是端到端历时，也不是单个服务请求的 P50/P95。原生 admission、资源及生产 owner evidence 的边界仍以原报告为准，本轮没有绕过、弱化或重新宣称这些门槛通过。

## 6. 本轮闭合的证据与仍需解决的问题

本轮把“只在候选构造相关历史样本上看过 forward”推进到“候选先固定、构造之外的完整来源队列、真实未来分支、全量配对统计与媒体审计”。它也直接说明：当前两个局部更新即使改变 raw 概率，幅度仍不足以在这批分支上改变任何冻结校准后的行为；其平均 raw Brier 正改善也未获得预定区间的支持。

后续候选学习的检验目标应包括明确的未来预测/条件价值损失与实际校准后行为。新的幅度或学习规则须在历史训练/开发来源上形成，再单独冻结评价设计；不能借本轮结果调整候选、重选视图或宣称已经取得更新效用。生产接入仍需要真实签署的 owner/evaluator 材料，本轮没有生成这些材料或执行生产 acceptance。

原始 NPZ、逐行评分、媒体、日志、权重和既有 journal 留在本地执行目录；GitHub 保存本详细报告、协议、代码、精简聚合结果和过程身份，供其他 agent 核对。运行入口与 artifact 前提见 [REPRODUCE](REPRODUCE.md)。
