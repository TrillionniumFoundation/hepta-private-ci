# NDU 独立确认候选方案 v1 — 仅供审阅，不执行

状态：只做保存证据分析、预算和样本规模规划。没有新物理源、正式 seed、
opening marker 或 evaluator。父会话须合并三组设计后另行批准最终冻结版本。
本草稿不修改已执行 d1 的源码/预算，也不把 TRAIN 正值当成最终证明。
本轮修订改正cohort功效/成本口径并细化排程；父会话当前决定继续有根据的
TRAIN机制研究，**不执行**这份大重复确认。共享错误额度不要求各路研发
串行、共同停工或等待本确认。本分支的低成本已存证据分析继续独立开展。

## 1. 已知历史与选择清单

以下是本分支能够核实的历史；正式结论来自已给定的封存边界和根 README，
没有重新打开历史正式数组或重跑它们。提交元数据仅用于定位来源。

| 阶段 | 选择/执行与结论 | 定位 |
|---|---|---|
| r1 | seeds11/23/47；LR=.001/.003/.01；固定 rho1.5、anchor.2；TRAIN/validation 搜索后一次正式窄门通过；含空耗对照，不证明有效完整预算优势；正式集封存 | source57d2c7aa5880dd761b4c43f79d0f6f16b26b72e7；receipt6216793b32；runs/codex-cloud-20261023-r1 |
| r2 t1 | TRAIN/validation 未通过；正式集未开 | f8b15aea9e |
| r2 t2 | 未通过，含实际 CPU 超限 | f762b921e0 |
| r2 t3 | balanced 未通过有效动态比较 | c59ca98776 |
| r2 t4 | cost-aligned 未通过 | d9e188e012 |
| r2 t5 | 未通过；保留 TRAIN decision-regret 诊断 | 4efd6e23fa |
| r2 t6 | affine 质量增益未满足完整动态门 | ced2b9674b |
| r2 t7 | shared preparation/admission 失败 | f28bc2c51b |
| r2 shared-profile d1 | 单独 profiling，不能替换 t7 | d6796364ef |
| r2 t8 | shared CPU 超限，未有候选完成 | 2394633fff |
| r2 shared-timing d2 | 未复现 slowdown，不擦除 t8 | 97f2954104 |
| r2 launch-paired p1 | 保留所有启动样本，不挑最快波次 | 8050c19bcb |
| r2 t9 | 有效动态门失败 | c5397bd85a |
| r2 t10 | folded adaptation 未通过 | 278f3bed09 |
| r2 t11 | native Adam 后仍失败 | a7db854f2d |
| r2 decision q1 | 单次 TRAIN regret 诊断，非正式确认 | 9db623a8b5 |
| CORE c1 t1 | calibration 构造失败，无正式测试 | source893a13fd165ae530531687933133fbbe2f9f58b4；freezea80b6b6e23 |
| CORE c1 t2 | TRAIN/validation 就绪；唯一正式确认失败；A-H 与 N-A 六个均值正但六个区间均跨零；不可重跑/调参追通过 | sourcecff9562102a21eb2a852daa61810e2e0b576ed9d；freeze8ca460b29d；failure237ad34c51 |
| codec | 手造/source 验证，不是训练优势或 AV 验收 | 起点0aca16714390ca045a53cece9644992b7990fc9c |
| NDU d1 | 只用 r2 TRAIN；两 sampler×三 seeds，LR唯一.003，rho/CE/效用未变；一次运行；128步配对及626/623步全预算结果全部保留；没有 validation/正式选择 | code7dc5718f30、5c03061859；freeze456ef38b3b；resultsaa8e500b7a；metadatafc652aa783 |
| d1 后审阅 | 讨论后优先提出 N-stratified；这是已见 TRAIN 证据引导的下一候选选择，不能称未选择；保留 IID N 和全部 A 结果 | 本目录；REVIEW_RESPONSE.md |

r2 t1–t11 目录统一为 `runs/codex-cloud-efficient-r2-tN`；所有正式 r2 仍未开。
旧计时、OOF、微基准和实现失败的完整子清单、实际历史 R&D CPU、另两组
此后候选/看数/失败仍须由父会话合并其 receipts；本分支无法凭空补齐。
**这份已知历史不是完整跨线程 alpha 账本；缺少父会话合并即禁止正式执行。**

## 2. 要估计的训练程序效应

不是三个已保存模型的固定权重效果。目标是在一个预先冻结的新 TRAIN 集 T、
固定模型/效用/软件/主机配置下，对**随机三-tuple完整预算block**及独立物理
cohort分布的平均程序差值。每block内先平均三个共同预算模型；预算admission
使模型间有依赖，estimand不是96个独立单模型系统。结论条件于 T 和所测
主机/执行窗口，不声称跨任意
训练数据、开放世界、设备或 AV 的泛化。

每个 tuple 明确包含 base/decoder 初始化、base learner minibatch、adaptation
sampler 和 full/low view stream。由一次批准后的 seed root 及 block/tuple/role
索引作域分离推导；先冻结全表，检查冲突，不选有利 seed。A/N 在同 tuple
共用相同 base、输入和各 sampler 的 draw prefix，Adam reset 规则一致。
不同 tuple 的随机流独立；同 block 内预算分配和计时仍可能使结果相关。

唯一拟优先确认的是固定 N-stratified。有效 A 比较器为 A-stratified 和 A-IID
两个真实有用候选，要求 N-stratified **同时**超过它们，不在正式集挑较弱者。
原 N-IID 继续作为预声明的 sampler×objective 对照；同等两候选机会、真实
更新和实际输出全部计费，不训练闲置 critic、不跑丢弃的 scorer 来配算量。
“最佳A”在此明确限定为这两个全局固定sampler的有效静态类：同时超过
两者的总体均值，比只胜过validation从这两者全局选出的一个更强。
它不等于胜过在正式集逐seed/逐源挑选的oracle。若另一路已有更强可部署A，
父会话须先把它加入最终比较/完整预算，再重新审核样本和错误额度，不能
继续用当前两候选类冒称整个仓库的最优A。
原始 reward/decoded observer 不变；rho=1.5、CE anchor=.2、LR=.003、hidden32、
batch64、decoder300、base500、view概率.5、always-full 服务固定。
不以自由重标度评分、rho 搜索、不同 CE anchor 或临时效用语义制造优势。
这里的A保留原强dense/joint additive梯度训练；父会话已报告内容组新的
交替方案失败，不能以该失败交替模型替换强A。N_s对A_s/A_i双比较继续保留。

## 3. 固定样本与预算提案

拟固定 **32 个完整预算 block，每 block 三个独立 tuple，共96个训练 seeds**。
每 block 的 A 和 N 均含三 base 对应的两 sampler、六个候选模型。
**旧10秒/12B上限属于这样一个完整系统，绝不是每个单独模型10秒。**
每 block 每组继续同一10 process-CPU秒、12B原价算子单位双上限；不提高
N 的帽、候选数、结构、LR或迭代机会。较便宜 A 可用余量做更多真实更新。
实际各模型更新次数受共享成本及原 admission 规则影响，并非保证固定626/623；
不能把“保持完整 block 上限”写成“实测每模型耗时完全相同”。

新 TRAIN=192物理源、validation=72物理源；拟正式集 **768物理源，64/源类**。
每源八 instructions×两 variants，共12288相关请求，独立 n 不是12288。
同一 TRAIN/validation/formal 源集跨训练 repeats 共享；它们在三个 split 间及
所有历史源间须独立且哈希不重叠。生成和存储各一份，不重复构造以挑样本。
随机物理源按源类分层取样；正式集内按每源16行打包，四源组成一个64行
服务 cohort，共192 cohorts、每源类16 cohorts。整源及 cohort 不拆开。

新增 validation 与四波计时的实际成本可能压缩训练量，故不能假设 d1 的
TRAIN 效应原样迁移。所有准备、三个 base、两候选搜索、TRAIN 诊断、
validation、负对照、reference calibration、导出、调度及加载都列账；静态
controller成本为零。编译/数据只准备一次，对每 block/每组完整归因共同
receipt，不用物理共享成本返还为 N 的额外预算。模型/随机流各自保存。

| 拟新增阶段 | A帽 | N帽 | 两组/共享总帽 |
|---|---:|---:|---:|
| 32个完整 build repeats | 320 CPU秒 / 384B units | 同左 | 640 CPU秒 / 768B units |
| 正式服务，四波且所有候选 | 1800 CPU秒 | 1800 CPU秒 | 3600 CPU秒 |
| 源清单/统计/结果与补充 replay 分析 | 共同300秒全归因 | 共同300秒全归因 | **物理300 CPU秒**，归因合计600；不可当训练抵扣 |
| prospective total | **2420归因秒** | **2420归因秒** | **4840归因秒；物理阶段帽上界4540秒**；另定2小时wall/4GiB RAM/2GiB留存帽 |

本表**只属于本NDU A/N确认方案**，不含内容控制/动态调度两组预算，也不含
已花历史R&D。先前“4540 attributed秒”口径不准确：共享统计300物理秒
若完整计入双方，归因总量为4840，物理上界仍为640+3600+300=4540。
build中的共同准备也有重复归因，物理实际可更低；任何差额不是N预算信用。
统计300秒帽按进程入口起算，含导入、子进程、源/模型哈希、ground-truth
observer/负对照、bootstrap、replay分析和最终序列化，不把这些放到未计成本
的“管理”区间。它是物理共享一次、双方完整归因各300秒的研究成本。

96 tuples×四候选×四波×12288请求=**18,874,368** 次实际输出。
现有单full服务库存19236 units/request，单full总363,067,342,848 units；
保留原每请求2 full-equivalent cap后主服务上界726,134,685,696 units。
模型build加主服务算子上界约1.494T；另给固定12码replay小库存，模型/服务
总帽1.50T。统计特殊函数和resampling不冒称统一硬件FLOPs，按共享CPU帽
单列全部成本。不得用本表偷偷授权更多总研究资源；父会话需批准此显式扩额。

这将原独立系统的**总研究重复预算增至32倍**，不是把每个模型预算增32倍。
按 d1 的71.946–121.075微秒/request机械外推，主服务约1358–2285 CPU秒，
仅是尺寸预测；不是新测量，也不承诺主机速度。真实超帽则失败，不能删慢样本。
相比之下16 blocks=48 seeds、build320CPU秒；64 blocks=192 seeds、build1280CPU秒。
这些只作规划敏感性展示，**不**是根据结果自动从16增到32再增到64的序列。

## 4. TRAIN 能支持和不能支持的检验能力

保存的三 seed N-strat−A-strat raw差值均值 .004007769、样本SD .000889332；
joint均值 .004140971、SD .000921258。单波 CPU-net 差值SD .005343217，
不能当作独立波次方差。sampler×objective 增量只有 .000211998，SD .001073697；
不为“NDU独享分层收益”设确认目标。

即使额外假设三差值 iid 正态，seed SD 的示意95%区间约[.000463,.005589]，
上限是点估计6.285倍；这些假设未验证，而且三 seed 共用一个预算 block。
区间只展示规划不确定性，不构成新的显著性证据。源方差/seed×源交互方差
无法由保存的 TRAIN 均值辨认；不能从3072行或3个正号虚构更大有效 n。
诊断还共用同一panel和97013抽样流，每个方差点仅十二 minibatches。

修订计算见 `power_cohort_v3.py` / `power-plan-v3.json`。旧power-plan与v2保留，
但**旧CPU-net的σ_source²/768项未反映共享计时，不再采用**。
统一敏感性为 `SE²=σ_block²/32+σ_cohort²/192+σ_interaction²/(32*192)`。
σ_block针对三-tuple完整预算block，σ_cohort包含共享batch计时噪声；交互项
另列，不当零的经验事实。现有一个block不能估这些分量。
只有在四源效应独立且没有额外共享计时噪声时，才可设σ_cohort=σ_source/2；
**不对CPU自动作此假设**。raw效用的旧seed-SD可在给定block内相关假设下
示意映射σ_block=σ_seed*sqrt((1+2相关)/3)，也不是实际block方差估计。
用 t(31)的单侧.012临界值近似，不把正态功效公式冒充最终bootstrap检验功效。
六个 superiority 条件的80%联合功效在无相关性假设下可由每项至少96.667%
功效作 union-bound 规划；单项80%不保证六项同时80%，retention/admission
失败及bootstrap/studentization条件还会进一步降低总体功效。

| raw效用假设（全非新观测） | σ_block | σ_cohort | σ_interaction | 单项80% MDE | 六项80%规划MDE |
|---|---:|---:|---:|---:|---:|
| seed-SD×2、相关.5映射 | .001452 | .005 | 0 | .001424 | .001863 |
| seed-SD×4、相关1映射 | .003557 | .005 | 0 | .002331 | .003050 |
| cohort/交互较大 | .001452 | .01 | .01 | .002497 | .003267 |
| block/cohort/交互均较大 | .003557 | .01 | .02 | .003185 | .004168 |

本表以raw效用SD为锚；“六项”列是假设每项都有所列效应/变异时的规划阈值，
不是由六个真实端点联合分布计算的实验成功率。joint的SD略大，另一A比较、
CPU-net、源交互及其相关结构仍须各自审阅；不能用raw表替这些未知项背书。

cohort方差不会随训练block增加而消失。若真实外部效应只有.0002或为零，
本预算不适合“保证通过”，不得凑结论或临时扩样。

对CPU-net，固定σ_cohort=.01、交互0，block SD=.003/.006/.01时六项80%
规划MDE改为 **.003768/.005398/.008034**。例如blockSD=.006、cohortSD=.01、
交互SD=.02时为.005503。σ_cohort=.005给出的更乐观.002699只是另一假设，
不能拿768源数替代192计时cohort再降低误差。四波不保证噪声恰好除二。
**所有表仅敏感性；不承诺32blocks或96tuples足够，CPU-net可能仍是瓶颈。**

## 5. 完整CPU-net与公平计时

每 tuple 的四候选记为 A_i、A_s、N_i、N_s。固定四波 Williams 顺序：
`[A_i,A_s,N_s,N_i]`、`[A_s,N_i,A_i,N_s]`、
`[N_i,N_s,A_s,A_i]`、`[N_s,A_i,N_i,A_s]`；按block/tuple索引轮换行和标签。
四行使每候选占每位置一次、各相邻有向候选对一次。以零起始索引b、s、w，
使用第(w+b+s) mod 4行，标签再按b mod 4循环置换；四波均完成。
cohort由每源类的物理源哈希排序、连续四源成组，再按一次冻结的cohort
哈希排序决定请求顺序，不按已见分数/计时排程。每 cohort 内按该顺序
交错真实服务，固定64 batch，不先跑完全部A再跑N，不用最快样本。
每个波次使用预定独立 common-uniform stream，A/N各自按自己的p×q采样；
质量端点仍精确求12×12期望，服务计时包括真实抽样、decoder、PNG/hash/
base64/JSON、ledger、分配等。一次load/prepare单独完整计入，不隐藏cold work。

所有四波都保留，主成本用算术平均，不去极值、不因慢波重测。CPU和wall、
generation/encoding/JSON/字节数/抽到的codes/PNG哈希、资源与GC/线程信息
一并记录。单独的固定12码同输出replay仅用于拆看输出编码与时序，固定
96 tuples×四候选×四波×12码=18432行，计入上面300CPU秒/1.50T总帽；
它不替代真实输出成本，也不用于修正主端点或获得训练预算信用。
不同模型采到不同PNG/长度导致的真实成本差保留；只观察同架构不作归因。

共同reference R_b在候选前，用TRAIN上每目标类最前八行的同一个96行panel，
对三个base均执行四波；先取每base四波每请求CPU的算术平均，再取三base
均值的中位数。记录所有值，不选最快者。每 block B_arm 是该组包含
两个候选/三个seed的完整build成本，H=100000不变。每候选/seed/源cohort的
完整净值为 U - .02*(c + prepare/H + B_arm/(3H))/R_b。
两候选都承担整个搜索build归因，不能把 B 除以六来淡化候选成本。
把正式服务测量总CPU、实际每请求成本及H生命周期价格都报告，不能把
生命周期amortization说成实际已经执行了H个请求。所有测量成本另计上述研究帽。

声明范围：固定主机、批量、样本策略及四波窗口分布，不是单请求p99、跨
设备/任意负载/后续所有时间的CPU优势。外界系统性漂移不能凭重测洗掉；
若预先冻结的环境完整性条件失效，保留全部并判该确认未完成/失败，不挑快波。
拟执行排程为本NDU专用单进程、单模型调用串行执行：block按冻结索引序，
build的A/N次序按block和round奇偶交替；全部build/validation先完成，正式
测量按block/tuple/cohort/四波顺序执行上述Williams四候选序。窗口内不启动
本任务其他编译、分析或模型作业。其他云环境/实验研发无须暂停。线程配置
固定1且记录实际BLAS线程/库哈希、进程affinity，不改权限或CPU配额。

可判失效的范围仅为本NDU尝试：源码/库/线程/affinity偏离冻结值、进程重启
或模型缺失损坏、实际CPU/单位/wall帽超限。慢样本、GC、context-switch或
可观测邻居负载本身不被删除；保留遥测并限定结论到观测窗口。外部共享
主机背景无法完全隔离，Williams仅平衡位置/一阶相邻顺序，**不自动消除
时间漂移或保证block可交换**。若统计假设不能支持则不作CPU确认，不重测
挑快窗。这是测量解释限制，不新增按结果停掉其他研发的全局门。

## 6. 多seed与源分组推断候选

对每端点/比较，先在物理源内平均16相关请求，再在四源cohort内平均。
每 block 内三 tuple 与四计时波平均，得到32×192的配对差值矩阵 D_b,c。
CPU共享同batch计时，故整cohort必须绑定；raw/joint也采用同cohort主分组，
附加单物理源分析仅是敏感性，不据其更窄区间改主结论。

θ_hat=所有block与12个固定源类等权平均；estimand涵盖随机三-tuple完整block，
不是固定三个权重的源均值。主重复单位保守取32个完整block，不能把96
seed或12288请求当作互不相关的CPU重复。全部seed均保留，不筛异常seed。

供统计审阅的固定候选方法：分别重抽完整block和每源类的16个完整cohort，
保留block内三个tuple、全部波次、各源变体与六项比较的配对关系，做99999次
crossed pigeonhole bootstrap。行均值r_b跨全部192 cohorts平均；列均值m_c
跨全部32 blocks平均。定义 V_plus=s²(r)/32 + sum_h[(1/12)²*s²(m_h)/16]，
其中h为源类。这重复计算部分交互贡献，作为非负的保守渐近候选。
各bootstrap矩阵同样重算V*，T*=(θ*−θ_hat)/sqrt(V*)。

NDU claim的.0125名义额度拟拆成统计尾部a=.012与MC容错β=.0005。
对每项六个比较/端点，q=1−a，M=99999，取最小整数k满足
P[Binomial(M,q)≤k−1]≥1−β/6；使用按升序排列的第k个T*作保守分位数。
本提案的数值k=98927，前一阶不满足该尾界，保留复算依据后才冻结实现。
L_boot=θ_hat−T*_(k)*sqrt(V_plus)，六项下界均须大于零。
旧草稿额外t门已移除：增加一个t门不能证明bootstrap已经校准，t临界值
仅保留在规划敏感性里。不存在合适k、任何原始/重抽方差为零或
非有限、统计CPU超帽，均不确认，不塞epsilon、不丢坏replicate或换检验。
MC只运行这一固定次数和预先独立固定的RNG流，不重抽直到显著。

**bootstrap MC分位数误差不等于检验size误差**。若理想bootstrap条件下
每项尾部size≤.012，IUT的统计错误≤.012；六个MC
保守分位数失效概率并集≤.0005，合计才是.0125。这个推导没有把近似
bootstrap自动提升成有限样本精确size证明。统计实现、阶次数值和有限样本
手造校准仍须源测试与独立统计审阅；现在没有可运行的正式evaluator。

此方法是有条件的渐近推断提案，不是分布无关的有限样本保证；若退化、
时间相关或异质性使理论条件不适用，就不能声称名义α已经得到实证保证。
更多seed也不消除有限源和系统波次不确定性。该统计决策是正式执行前的
明确待办，不借当前TRAIN正值跳过它。

## 7. 一次最终声明清单、前瞻错误控制与终止

提议父会话登记一次固定的联合声明清单/错误额度，预定联合清单如下。它
不要求三路物理同时或串行执行，不要求其他TRAIN研发等待本分支。分配只是
请求父会话审阅的方案，尚未替另外两组决定最终比较器/样本/成本。

| 可单独对外声明的 claim | 固定成功要求候选 | 拟名义α |
|---|---|---:|
| NDU训练贡献 | N_s分别胜A_s和A_i；每比较raw utility、joint success、完整CPU-net三项均正，六项conjunction | .0125单侧 |
| 内容控制贡献 | 父会话固定有效A−H及全部端点；不得用本分支代替其设计 | .00625 |
| 动态调度贡献 | 父会话固定NC−有效最佳静态NDU及完整净值/质量保留；不得挑弱静态 | .00625 |

三个claim名义α和=.025；若各claim检验有效，Bonferroni为这一次**前瞻**
声明集合控制≤.025，不宣称三个边缘区间同时覆盖。NDU内部是单一IUT：
六项都通过才可声明，无端点替代；不是六个可各自挑出的独立成功声明。
最终总体“几个目标均成立”还必须三路全部满足各自冻结门。

历史 r1/c1 从未预设一个贯穿所有研究的统一α账。c1的名义95%区间与已经
消耗的正式机会不能追认进新账，也不能把失败改名通过。仅在“旧相关机会
总size≤.05且完整、未来新检验有效”的额外条件下，旧.05加新.025才给
≤.075的union上界；有r1或其他未汇总看数时，连这个完整程序界也未建立。
**本方案不声称整个历史+未来程序仍是.05，也不无条件声称全历史≤.075。**
原冻结PROTOCOL.md里的几何序列只是一段早期草案，本方案不采用它来
重复尝试本候选；保留旧文字作历史，而非偷偷改掉先前方案。

只允许一次当前固定候选/样本/比较/计时确认。没有中途效应看数、提前成功、
增加seed/源直到显著、挑subset、重抽bootstrap直到通过或重跑快波。
本NDU的validation readiness具体为：全部32完整block/384候选齐备且各组
build≤10秒且≤12B，无缺失；在完整72源/1152行V上，对两个A的 pooled
raw utility与joint success差均严格>0。另用每候选TRAIN固定96行四波服务
成本校准V的CPU-net proxy（同R_b、H与完整build归因），两个差亦严格>0；
它只是开启前proxy，不能代替正式集真实计时CPU-net。逐96tuple的N_s−A_s、
N_s−A_i greedy joint退化均≤.02。负对照范围为全部384 final候选在全V上
将decoder行循环移位一次、bias不变，原raw均值减损坏raw均值每项严格>0；
正式评分时同范围在全正式集再次报告并要求>0。

负的单block效果只是保留的随机结果，**不**单独删该block；readiness均值
用全部32block，不能要求“好block才留下”。任何block真正构建/预算/模型
完整性失败则终止**本NDU确认尝试**并保留全部已成部分，不打开正式源；
pooled readiness失败亦如此。均不停止其他实验或本分支的只读机制研发。
已打开后的缺失、
失败或区间跨零均终止本候选，不自动开启第二批正式样本；未决结果不叫通过。
未用完的某组alpha不因另一组失败而事后转移。以后想继续同一科学程序，
须在已消耗的未来.025之内有预先保留额度；本表没有自动重试余额，改名
new family不能恢复旧的全程序错误率声明。

greedy只设原.02保留界，绝不宣称改善。全部正式源的哈希清单、完整训练
tuple表、模型/Adam/RNG、原始成本与失败都留存；PNG存储可按哈希去重，
但计时内仍实际编码每次输出，不切换尚未验收的codebook服务profile。

## 8. 执行前父会话必须决定的事项

1. 合并三路最终claim、有效比较器、源/seed、预算与全部历史看数清单，
   明确这只是本NDU A/N提案，是否接受其4540物理CPU秒上界、4840完整归因
   秒与1.50T模型/服务单位规模；不是三组总预算。当前决定仍是不执行。
2. 接受上述有条件检验能力，或先另行批准只用已有TRAIN的源方差/独立
   时序估计；本次没有执行此新增诊断，不能把假设σ写成已观测。
3. 完成推断算法、MC阶次/误差分配和非正式手造校准的统计审阅；正式
   opening前冻结唯一方法，不能在正式结果后从多方法中选通过者。
4. 建立全局一次性、实验与run级marker约定；批准后才一次派生新物理源
   salts/seeds并封存。与既有封存源仅比较受信哈希manifest，不重开旧输入。
   首次新正式构造前原子取marker；碰撞/失败不换salt另跑，永久保留marker。

**当前终态：方案可审阅，确认未授权/未执行；需要父会话合并三路设计，
并非运行时权限阻塞。** 当前有限两模态/十二码任务的旧所有失败继续有效。

## 原始方法来源

[Colas等：随机seed与检验能力](https://arxiv.org/abs/1806.08295)说明少seed
功效/假设敏感性；[NIST标准差区间](https://www.itl.nist.gov/div898/handbook/prc/section2/prc231.htm)
给出正态假设下chi-square区间依据；[Owen的pigeonhole bootstrap](https://arxiv.org/abs/0712.1111)
研究交叉依赖的行列重抽；[Davezies等多路聚类渐近结果](https://arxiv.org/abs/1807.07925)
给出适用条件而非本实验的有限样本认证；[Berger与Hsu的IUT论文](https://projecteuclid.org/journals/statistical-science/volume-11/issue-4/Bioequivalence-trials-intersection-union-tests-and-equivalence-confidence-sets/10.1214/ss/1032280304.pdf)
支持单一conjunction的逻辑。这里的具体样本数、预算与功效数值来自本目录
对保存TRAIN聚合量的规划计算，不是这些文献对本生成器的优势背书。
