# R13 前端、冻结、确认统计与成本的独立审查

## 审查结论

截至本次冻结数据，独立审查 414 项全部通过，没有发现应修改本轮已冻结运行源的阻断性错误。确认结果支持预注册的条件非劣及“唯一部署训练成本”口径下的节省；不支持解析编码器带来预注册的质量增益，也不支持超越 generic HMM 的独特效果。任何性能结论必须保留训练复用的归因。

实际执行程序为 [frontend_audit.py](frontend_audit.py)，源 SHA-256 为 `71031af359b3174a7b1bd0506e33b59938217dc917b4f5c72e19e38d3fc4605c`。先于确认结果的 [FRONTEND_AUDIT_PRE.json](evidence/FRONTEND_AUDIT_PRE.json) 通过 74 项；同一程序在确认结果完成后写入新的 [FRONTEND_AUDIT_FINAL.json](evidence/FRONTEND_AUDIT_FINAL.json)，通过 414 项，没有覆盖前一结果，也没有修改父实验源或产物。程序只重读分区原文来检查规范化与身份，不运行文本编码器或模型推断。

本次根冻结文件 SHA 为 `be3b72c8786724fc03f72a1abcf919e6d063a40a36697a8bdc4dab35a5ba610c`；确认结果 SHA 为 `aae98a044b40308ddd2fa16c18cea38316bfee7d5b25cf40f37809e2545f09c9`。40 个冻结源文件、50 个 fit/receipt/frontend 文件、动态库身份全部匹配。24 次拟合的 source map 相同，执行回执均成功，且当前训练源仍与拟合身份一致。新增审查文件不是本轮运行代码的一部分。

## 数据边界和实际 READ

对固定 UCI SMS archive 独立复算 NFKC、casefold、空白规范化、去重身份和分区：5,574 条原始行，5,159 个规范化唯一文本，0 个标签冲突身份，四个分区互不重叠。

| 分区 | ham | spam | 作用 |
|---|---:|---:|---|
| encoder_train | 2,233 | 338 | 学习共享文本编码器 |
| core_train | 737 | 91 | 核心训练与 nominal emission 计数 |
| validation | 420 | 53 | 选择 checkpoint 和普通核心 |
| confirmation | 1,127 | 160 | 冻结后的确认访问 |

共享前端使用 encoder_train 拟合固定 HashingVectorizer/LogisticRegression，六个 logit bin，加一个恢复态不可用 token。真实编码只在 active 状态的实际 READ 时发生。确认轨迹逐臂复核了 READ 总数、恢复态 READ 数、原始文本访问与 encoder 调用关系：`raw_text_reads = text_encoder_calls = READ - recovery_READ`，每集最多两次 READ，并有唯一终止回答。

完整 archive 在准备分区时已经被读取、解码和规范化，所以“确认文本从未被读取”不成立。正确限制是确认文本在冻结前没有被编码、评分或用于拟合；在线 actor 只有实际 READ 后的 token。世界模拟与最终评分可见的真实类别和恢复相位没有作为 actor 输入。监督训练标签及训练期 teacher 不是这一访问限制的例外漏洞；它们属于已声明的训练数据。

teacher 使用真物理 `Q` 与 core_train 计数加 0.5 的 nominal emission，并非使用确认集词频拟合的 oracle。研究问题是在一个受控、有限、再生的隐藏过程上读取真实文本；它不是自然到达的 SMS 时间序列。OOD 只改变时间间隔，不代表新语言、用户群体、来源或对抗分布。

前端完整子进程计时采用一次同权重 refit；审查发现它与权威前端 payload 只有 `frontend_cpu_seconds` 不同，权重、截距、迭代、计数和分区全部一致。此前输出文件已存在导致的失败保留为失败回执，没有冒充成功计时。

## 配对统计和 2×2 归因

八个独立训练 seed 在 IID 与 OOD time 两个域各产生 1,024 集确认任务，统计独立单位是八次拟合，不是把所有 episode 当作独立训练重复。八次 validation 均选择 GRU 作为普通核心。A/B 是普通编码器配固定读/规划，C/D 是解析分布编码器配固定读/规划；前端及共同规划模型固定共享。

独立程序从逐集 utility 重算每 seed 均值，再穷举 `2^8=256` 种 sign-flip，独立执行双域 Holm 校正并核对验收。以下 CI 为八个 seed 的 Student 95% 区间。

| 主对比 D−B | IID | OOD time |
|---|---:|---:|
| 平均 utility 差 | +0.000244140625 | −0.000190132619 |
| 95% CI | [−0.002771432, +0.003259714] | [−0.002591996, +0.002211731] |
| 原始双侧 sign-flip p | 0.9375 | 0.921875 |
| Holm p | 1.0 | 1.0 |
| 预注册质量增益通过 | 否 | 否 |
| −0.01 界的条件非劣通过 | 是 | 是 |

非劣只说明该固定确认协议内的误差下界满足预注册阈值，不等于证明严格等价。原始 D−B 值既有正也有负。程序中的双域同时单侧下界使用 t 的 0.975 分位；它在这里数值等于表中双侧 95% 区间的下端。

| 2×2 平均效应 | IID | OOD time |
|---|---:|---:|
| 普通编码器的规划效应 B−A | +0.030814 | +0.032602 |
| 解析编码器的规划效应 D−C | +0.030936 | +0.033144 |
| 固定读下的编码器效应 C−A | +0.000122 | −0.000732 |
| 交互 `(D−C)−(B−A)` | +0.000122 | +0.000542 |

最大的实测改变是是否使用规划。小的编码器差异与交互没有提供独特解析神经元质量增益的证据。不能用 SSM 在 OOD 较差来代替预先选定 GRU 的主比较，也不能把 posterior teacher loss 当作实际任务效用。

D 和 generic HMM 在两个域的全部记录动作一致，各 seed utility 差为零，序列 posterior 的最大差为 `2.220446049250313e-16`。HMM 参照使用相同 cached transition，因此它检验滤波/控制等价，不是对 transition 构造的独立验证；后者由原生 SciPy `expm` 检查提供。R12 的近 tie 舍入缺口在本轮预先固定了确定性容差策略，没有用确认后修补替换此次结果。

## 训练账本与成本口径

24 次拟合的完整子进程 user+system CPU 总计 **1,061.51464 秒**；共享前端完整子进程 CPU **2.48109 秒**。whole-child 回执包括各自进程启动、导入、准备、拟合和序列化，不能只引用内层训练计时。公共 service setup 与每 seed 模型加载另有测量，runtime 中也包括 sensor/world 构造。序列 benchmark 和最终序列化归全局评估回执，不混作每个部署 counterfactual 都重复发生的在线开销。

本轮预注册主成本是 **unique deployment**：普通候选需要自身训练与共同 HX 校准，解析候选复用校准模型，不把同一拟合重复计费。这是架构复用造成的部署成本差异。作为敏感性同时保留 equal calibration charge、全量 GRU/SSM 搜索成本和仅在线 runtime，避免把复用解释成原生算子更快。

| D/B 成本比 | IID | OOD time | 含义 |
|---|---:|---:|---|
| unique deployment，预注册主口径 | 0.531001 | 0.531017 | 一次复用校准，按每候选 1,000 次部署调用摊销 |
| equal calibration charge | 1.001775 | 1.001804 | 两侧均承担共同校准，用于检查重复/复用分配的影响 |
| 全量模型搜索 | 0.999895 | 0.999915 | 同时承担 HX、GRU、SSM 拟合搜索成本 |
| 在线 runtime | 0.906227 | 0.922560 | 当前单主机、完整 controller 路径的实测比例 |

预注册 unique 成本门槛因此通过；equal-charge 和搜索口径没有相同节省。在线 runtime 测量还会受执行次序及 CPU 抖动影响，不能把两个域的单次比值当作稳定微架构 speedup。原生独立微基准已经显示 dense 仍慢于 strong cached NumPy。此次条件成本结论也不是“数据集处理、24 次模型选择、所有研发和硬件能耗总计减少 47%”。

## 限制和后续可复现入口

审查没有另行训练模型或生成一轮新的确认集，也没有逐文本重新运行 encoder；它结合源审查、冻结哈希、数据分区、逐集访问/utility/cost 原始数组，以及独立统计复算。它不能排除所有实现错误或把观察性一致当作真实任务外部效度。

复现可在同一依赖环境运行 `frontend_audit.py --output <新路径>`。该程序拒绝覆盖已有回执。重复审查不构成新的确认实验。后续若改变 native core、模型、前端或 tie 策略，应使用新冻结身份和独立的确认计划。本次 `all_scientific_blockers_closed=false` 保持合理，生产默认核心仍不应因这轮结果而激活。
