# 已完成研究的集成决策清单：当前不新增 TRAIN

本轮只读已发布 TRAIN/手造报告、源码冻结和模型清单，没有载入权重、
构造数据、生成预测、性能计时或训练。当前结论是 **HOLD_NEW_TRAIN**：
现有 CV 实现和原 full/low 动态路线没有支持追加训练的新证据。
这不是权限/实现 blocker；等待新的架构/数据提案或父会话明确选择的研究问题。
原生12-way目标解析由内容组独立负责，本清单不另扫 LR/系数、不替它下结论。

## 1. 保留的有效强参照集合

下面是各自证据边界内的强参照，**不是跨数据划分、指标和预算程序的总排名**。
全部 seed11/23/47 都保留，不挑一个最好 seed。每个权重的路径、SHA256、
参数 digest（原记录具备时）、更新数、完整方法费用与出处见
[IDENTITIES.json](IDENTITIES.json)；记录哈希来自冻结清单，本轮未重新打开模型。

| 候选身份 | 固定源码/模型出处 | 可用于什么；边界 |
|---|---|---|
| `D1-N-stratified`，同时保留 `D1-N-iid` | source `5c030618599b`；`runs/codex-cloud-ndu-training-train-d1/final-N-{sampler}-{seed}.npz` | 原器、rho1.5/CE.2/LR.003；每 N 系统含3 seeds×2 samplers，共10s/12B。全3072 TRAIN上分层均值 raw U=.986513，是该匹配程序的连续指标 incumbent，不是全局最优证明。 |
| `D1-A-stratified` **和** `D1-A-iid` | 同一冻结，`final-A-{sampler}-{seed}.npz` | 匹配有效 A；分层均值 U=.982505，IID=.981121。必须同时保留；N分层相对 endpointwise 更好 A 的 greedy正确数为−2/−2/−1，不能声称改善 greedy。 |
| `content-dense-A`（配对 H 保留） | content source `fbaac5b926`；`content-control-train-r2-20261023/{A,H}-{seed}-0.01/model.npz` | 原始强 dense/.01/full，9个既有 LR/seed候选已付费；144 fit/48 inner物理源，2304/768行。A原完整5.409933441s/11.664059B；不是 refiner。 |
| `content-standard-joint-A` | source `356acf562431`，freeze `4693f47b30ee`；`content-block-train-v1-20261023/A_joint-{seed}-0.01/model.npz` | 标准 encoder+双头联合更新控制，完整6.131584913s/11.645004B；必须保留，不能借失败的 `A_alt` 作弱基线。这里 joint 不表示原生12-way头。 |
| `T11-static-N-full` | [H4绑定清单](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d858c66eec4c89d5f5d399154c2cc19e538209b/qualification/joint-generation/runs/codex-cloud-dynamic-train-headroom-h4/T11-binding.json)；archive内 `ndu-{seed}-0.01.npz` | 动态比较的有效强静态N；原完整8.307966292s/11.958840147B，513/514/514更新。H4使用固定3072 TRAIN行。它不是本轮匹配 A/N 训练效应的证明。 |

这些模型的训练/选择来源不同。不能用3072训练行的U、768 inner行的U、
或另一模型的 entropic CE相互排名，再称一个免费组合为“最强系统”。

## 2. 固定模型联合解码：保留一个候选，明确它没有证明什么

候选是内容组 **diagonal-support/log2**，source `33ced6062ebf`、freeze
`cfb61bc44148`，模型固定为上表原始 strong dense H/A六份权重。
[完整结果](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/60c09723f784a90c249874a95e5da50ee93219f3/qualification/joint-generation/content_reconcile/RESULTS.md)。
规则只看 p/q/原抽样pair，比较 D(c)=p(c)q(c)，严格比例>2才修复；
log2是唯一primary，0为已见secondary，∞是identity，不能事后互换。

- 固定模型下 CE和joint提高、两头真类概率也提高；同时 both-wrong和wrong-agreement上升。
  H/A greedy不变。既不能说成纯钻分，也不能称为普遍纠错或参数训练增益。
- `T_log2` 与 `Q_log2` 是同一推送联合律 `Q_x(z)=Σ p_t q_i 1[f_x(t,i)=z]`。
  必须按每请求Q评分，再跨请求平均；不能乘修复后边缘，也不能把请求mean移进log。
  该映射依赖输入p/q，不能假称一个全局144表免费适用于所有x。
- 编译静态采样器有同等机会实现该终态律；T相对慢Q的成本差不是动态质量优势。
  原greedy是“原两头argmax，再同规则修复”，不是joint MAP。
- 这个probe没有N模型、没有新训练/预算重分配比较。若以后启用，N/A/H都须获得
  同样合法且计费的解码机会；训练仍用p⊗q、服务改用Q时须明确目标/服务律差别。
  不能把此增益与另一实验的N−A正值相加，称联合胜出。
- 原服务只用一个64行FIT cohort，primary实际修复0个pair；计时遗漏profile级
  recurrent setup/guard/return分项。即使固定probe累计费用在帽内，也没有完整
  recurrent CPU-net或有效静态重新分配训练预算后的系统优越性证据。

## 3. 适用优化双方共有；排除项不回收费用

**可复用条件**：D1分层采样的整请求重要性权重必须同样作用于CE和效用，A/N同享，
不是NDU专属。低视图精确fold、原NativeAdam/clip5/各组clock、native服务和任何已验收
输出优化必须给所有适用比较器相同机会；真实准备/训练/搜索/验证/导出/服务全入账。
共享工作每个实际使用者全额承担；专用cache/哈希/pullback只归实际使用组。
不要为廉价方法执行padding；它应获得更多可用的真实更新。
`local-png-codebook-v1`目前只有源等价性，lifecycle试验未完成且bundle export不支持，
不能自动作为已证明的预算收益加入模型。条件AV接口不等于AV生成验收。

**已排除**：残差refiner、固定1:1 heads-only交替、同一full/low critic扩搜；
codec D1 slot0的10.022472113s真实超帽；CE-anchor CV d2的全部12个负效应；
NumPy融合CV d3（raw Adam数值FAIL保留，hybrid面板通过但CPU更慢）。
不删guards/观察步、不挑快波、不再跑这一CV实现。
原生12-way既有portfolio的S/H/N最终超帽，不能把单组A正值认证为合格配对胜出；
后续目标解析仍属于内容组的另一研究身份。
[d2边界更正](../../runs/codex-cloud-ndu-CV-TRAIN-d2/ERRATUM-20261023.md)保留CV-only哈希被plain
分摊及9.922830434s为before-receipt的事实，不追溯减费或重跑。

## 4. 前瞻确认：已有材料足以立假设，尚不足直接执行

1. **先固定声明/estimand**：固定模型解码效应，或随机完整训练程序效应，二者选定并分别命名。
   前者可以用上述模型SHA规划独立物理源检验；后者必须预定base/learner/sampler seed重复、
   每重复完整10s/12B预算与跨训练block推断。三seed/同sampler panel不等于独立程序复现。
2. **先固定一个公平whole-system比较表**：相同训练数据/划分、基础模型、候选/seed/sampler机会、
   共同优化和最终服务律；保留上述strong A与静态N的合法替代方法，不能免费合并其搜索。
   不把固定旧权重的decoder probe当成“静态方法已用尽训练预算”的对照。
3. **成本与功效缺口**：补入设计中的完整服务setup/return、真实会触发修复的预定分布、
   交错计时/隔离/漂移规则和全部费用。物理源是质量样本单位，四源共享计时则cohort为时序单位。
   旧32个三-tuple block/768源/192 cohort草案仅是敏感性方案，不保证足够功效；
   4540物理CPU秒/4840双方归因秒仅属NDU方案，不能冒充三组总预算。
4. **完整历史与一次性控制先行**：列r1窄匹配pass含padding、r2多次开发未胜静态且held-out未开、
   失败且封存的CORE c1、内容/codec/采样/CV/融合全部选择和失败。冻结独立物理源、一次性标记、
   完整比较/声明清单及停止规则。旧历史没有统一alpha账；新的前瞻.025分配仍是草案，
   不能追认整个程序总.05，不能换测试重试到显著。保留greedy .02与全部错误严重度/尾部指标。

**当前可执行决定**：保存以上身份与排除记录；不新增TRAIN、性能或正式测试。
H4只支持停止当前两动作扩搜，不是所有动态模型不可能的定理。
若将来有合法新信息动作、不同架构/数据或父会话选定的单一问题，单独定义新研究与预算；
它不能修复旧r2/CORE失败。目前没有经本次整理获得的新训练方向。
