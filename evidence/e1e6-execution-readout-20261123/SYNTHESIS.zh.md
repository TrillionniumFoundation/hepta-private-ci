# Hepta 去中心化训练与有用工作实验审计

## 首次跨用户里程碑的后续实测

**同一份 Hepta 自有候选已经从一段公开授权的真实历史会话学习，在冷进程复现成功动作、保住一项旧能力，并在原生开发账本完成一次可重算的历史评测结算。经核验的两位独立用户间，前瞻迁移案例仍为 0。** 已知来源和后续真实到达分别计数。未来首次评测以已发布的冻结版本和独立到达记录为准。

| 对象 | 原始观察 | 能够支持的结论 |
| --- | --- | --- |
| 历史用户任务 A | OpenHands 公开反馈第 52 行。用户三次提交相同的编程任务。前两次出现代理运行错误，后来 Qwen2 写出的脚本成功执行，原始输出中的 14 个整数与独立算术校验一致。整个会话获得好评。 | 数据集主动公开、删除个人标识，使用许可为 MIT。该记录支持研究历史任务失败和成功动作；逐项用户验收与入组人的独立身份仍需另外核实。 |
| 自有候选 | 本地初始化的两层 GPT-2 先学习一项旧能力。随后在固定的 240 步中，180 步监督成功动作产生的 59 字节脚本，60 步复习旧能力。冻结父模型在 A 上返回 `0`，候选逐字生成脚本。两者都在旧能力的另一种措辞上答对。 | 一次样本内学习和一道旧题保持。远端发布的 27 份文件经逐项回读，两个新进程用相同解码上限复现结果。监督集中在成功动作，整条失败恢复策略及未见任务迁移仍待检验。 |
| 同候选结算 | Chain 先为上述候选预留 2,000 个隔离开发账本单位，再启动两个新进程。两臂各实际调用两次，合计 16.205516 CPU 秒。托管借记与收款贷记均为 2,000，余款为 0。保留了签名交易、原始模型输出与两份已关闭的 SQLite 库。 | 重开节点后复算的付款回执与原件逐字段一致。付费标的是重评历史 A 与旧题。独立客户出资、后续新任务消费、学习提升奖励和共识链重尚无实测。 |
| 双 Cell Circuit | 在另一个人工构造共享特征的任务中，路由和两个实际持有权重的 Cell 从磁盘恢复，最终评分在全图输出后发生。模拟后到题父错子对，旧题均对。保持两次调用并移除两 Cell 之间的答案传递边，后到题变为失败。 | 同一边在这个案例中传输了有效信息。传递边还增加输入 token。学得的路由与固定连通图同分，拓扑自组织、同算力路由优势、跨域组合仍待验证。这份 Circuit 的独立开发链评测已另行结算。 |
| 直接编辑与反传 | 固定上述历史父模型的全部 28 个原始张量，给两臂同一组 8,288 个输出层可编辑坐标、62 个监督位置、同一损失。在一台 CPU 上交错运行六次，直接岭回归求解中位 0.401 毫秒，固定上限 240 步的梯度法中位 122.365 毫秒。 | 两种输出层编辑冷启动后在 A 和旧题都回答 `0`。仅旧题正确。该计时覆盖局部拟合；同等任务质量的训练总耗时尚无估计。 |

历史候选的规范化冻结摘要为 `447ace5cc8bc031cc772e63ccb90380f16fc81404003bc04057ec4f8b7470ef6`。Git 记录其在 2026-11-23 08:35:03 UTC 发布。候选 `6a094252772cd5bf440ecf9b8ef0009adf6b17ec8b3f7ac44fed11d3c67ab7ba` 同时出现在冻结清单与结算的模型承诺中。付款操作为 `a4b3af6ad86a510207b38067dd1846c7c92097adb1d9c0f0d478a27b1fd0c18d`。[数据集原始说明](https://huggingface.co/datasets/OpenHands/openhands-feedback/blob/facf45600d625510b98222ec584a8c9ac59272a2/README.md) · [冻结模型与历史复评](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7022) · [同候选原生结算原件](https://github.com/TrillionniumFoundation/Trillionnium-Chain/tree/bbf31291231f59c517c52273465643a8cc3913d9/evidence/cell-historical-funded-evaluation-20261123)

Circuit 的独立付款对应另一份候选 `32ee053d020918d0a694c8b9a3a3bcaec3dfd93eed5bb7f98e0b33e46352dac4`，其固定图、学习路由及断边对照均可复查。HIA 在已有实验中把有类型的路由决定编译为原生代码，并与解释器重放结果对齐；跨任务路由收益需要上述固定图基线及新任务验证。[Circuit 权重、图和冷启动](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7020) · [Circuit 原生结算](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/985) · [历史 A 同参数编辑对照](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7024) · [HIA 双后端验证](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7011)

同期的 StableEdit 研究把梯度的运行统计、白化和岭回归结合，用于在语言模型里连续更新事实。这给 Hepta 提供了一个可比较的编辑方法；能否加快代理技能训练，仍取决于在同等未见任务质量和旧能力保持下测得的端到端时间。[ICML 2026 原论文](https://proceedings.mlr.press/v306/ma26f.html)

四台登记主机在冻结后再次检查了约定的登记目录。ai395、ROG、Mac 和 desktop 的采样截止时间分别为 08:46:19、08:47:04、08:47:50 和 08:48:57 UTC，新增登记引用均为 0。检查范围是这些入口的文件名和时间；任务正文保留在各自私有通道。严格双用户判定仍需能够独立核实的 A、B 人际关系。公开 A 去除了身份信息。如来源方无法提供独立关系证明，须在另一个获授权的真实 A 失败上重新训练、冻结，并等待随后的独立 B。此前登记的两条规模曲线均有 0 个合格实测点。[双用户验收协议及两条规模曲线](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1df26bf88c32a7c61340f1c1a93ae88d7841509b/qualification/cell-cross-user-milestone-20261123/PROTOCOL.md) · [私有宿主入组验权入口](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7019)

普通权重模型现有两阶段入口已补上这份冻结候选的已见输入检查。它核对公开原题、旧练习和保持题的文本及实际分词结果，同时核对已知原件与有命名空间的原始记录标识。重新编号的旧题在原实现中曾进入请求，修正后被拒。答案相同或使用同一家模型提供方，本身不排除新任务。另一人身份、到达时间与语义新颖性仍由私有入场方提供证据。[未见任务入场检查与回归](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7025)

## 冻结候选、原生授权与评测结算的端到端复核

**本轮有两份独立候选。历史候选取得了一笔可复算的开发评测费，在研究者出的新题上与父模型同答错。后来从开发样例训练的候选学到了重复输出，并丢失旧能力，按预设规则保留父模型。经核实的真实跨用户提升、学习奖励和外部客户订单仍为 0。**

| 候选及用途 | 冷启动后的实际输出 | 账本与判定 |
| --- | --- | --- |
| #7022 历史候选 `6a094252…`，继续使用已发布的冻结版本。研究者另出一道未用于拟合的算术题，走完来源登记、请求发布、父子评测、付款。 | 新题期望答案为 `1`，父与子都答 `0`。固定旧题两者均正确。四次调用共用 11.318814 CPU 秒。 | 预充值的原生开发节点向评测方支付 2,000 个开发账本单位，托管余额归零，学习奖励为 0。这是新的一次评测，与上表重评历史 A 的付款分别记账。独立保留的发布承诺 `ffafe180…`、准入回执 `510ab2c3…` 与请求 `f06b71ca…` 对应同一作业。原始输出、签名交易与关闭后的两份数据库可复查。[Hepta 请求发布](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7027) · [Chain 实际评分与开发结算](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/987) |
| #7029 新训练候选 `a44f85e1…`，来源为明确标记的工程样例，保留失败和纠正两次写入的原件，使用 CPU LoRA 训练 64 步后冻结。 | 两个提示都生成 100 个 `1`，旧能力丢失。两个强制退出对照在恢复训练后重现了连续训练的可学习张量、AdamW 状态和 CPU 随机数状态。 | 保持能力检查给出 `NoUpdate`，留下该候选用于复核。Chain 用实际权重和原始冻结记录核对训练暴露指纹，替换输入的对照被拒绝。该候选的评测委托、资金预留与付款均为 0。[Hepta 权重、恢复和保持结果](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7029) · [Chain 输入检查](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/988) |

前瞻入场要求来源方先记录冻结版本与任务到达顺序，私有入口对这份请求核实用途授权后才读取任务。SQLite 记录同一任务的领用，发布进程意外退出后可恢复同一份请求。#7027 的完整数值回归通过 249/249，另以真实原生 CLI 和无效句柄运行，程序在读取任务前退出，库内新增领用为 0。开发样例走通发布与结算时，入组人和签发方由测试程序模拟。[前瞻入场、进程恢复与原始工程记录](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7027)

#7028 把训练和仅评测两种用途各冷启动两次。四份新签名的开发投递都在 SQLite 中得到确认并重新打开，产品 CLI 经真实 Unix 套接字及签发进程的 Linux pidfd 向原授权服务发出验签请求。运行环境无可验证的物理图形登录会话，服务四次返回 `Unavailable`，CLI 四次均退出 1、标准输出为空。普通 Cargo 构建产出了实测产品 CLI。测试驱动的全量 Cargo 重编在 `codex-core` 被系统终止，两轮使用相同源码和 Cargo 已构建的产品依赖完成链接与实测。开发签名所对应的训练或评测真人授权数为 0。[测试驱动、两轮原始记录和构建范围](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7028)

2026-11-23 UTC 的下一轮只读核对中，ai395、desktop、Mac 和 ROG 的采样时间分别为 09:14:31、09:15:58、09:17:24 和 09:18:49。四台约定入口均有正常回读，新增 A/B 登记引用和客户订单引用均为 0。核对覆盖这些私有入口的登记元数据，其他渠道的到达情况未知。完成首例仍需要真实 A 的用途授权、失败与纠正原件，以及冻结后独立用户 B 的来源、到达时间和评测授权。工程样例和历史记录均未增加这两条规模曲线的合格观测点。

## 同日较早的两仓目录与 E1–E6 审计

2026 年 11 月 23 日。对两个仓库固定的 main 提交，逐目录重新计算了全部 Git tree，包括每条路径、模式和对象标识。hepta-private-ci 有 8,665 条文件路径，Trillionnium-Chain 有 41,834 条，共 50,499 条。完整性范围是这两个目录树。对训练源码和原始输出的内容审计聚焦 E1–E6 的研究分支，另核查了 11 月 20 日以来更新的 243 个 Hepta PR 和 13 个链仓 PR。研究分支中的结果有各自的提交身份。[主干树清单与固定提交](MAIN_TREES.json)

**现有实现足以让一个 Cell 接收任务反馈、提出可回放的权重修改、核验结果并恢复原状态。完整的在线学习收益仍缺一条连续记录。** 同一固定预算下，自有学生须在按来源和时间隔离的任务上提高，保留旧能力，冷重启后实际采用同一候选，并改善随后到来的真实任务。当前证据分别落在这条链的不同位置。[联合原验收](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6703) · [真实 HIA/Cell 执行](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6613)

## 每项实验实际测到了什么

| 实验 | 观测与统计单位 | 尚缺的判定 |
|---|---|---|
| E6 完整生命周期 | Q24 解析 Cell 的 warm NoUpdate19 已完整通过，四项原生回归为同一次工程验证。旧 cold01 真正启动后，在首次发布的验证事实比对处失败。固定修复源码的两个原生 neuron 边界用例已通过。 | 新源码跑完原 cold 父、真正 Adopt、采用后下一任务，以及对应的生产采用或结算。 |
| E2 学生自身纠错 | 四条自身失败纠正记录来自三个项目，两个既有父学生各执行八次更新。新评测名单八项全部结案，六个来源实际扫描，两个在扫描前按原规则排除。十九次候选准入只有 sqlparse 一项合格，原汇总器以 1/4 正式拒绝面板。 | 本轮新面板上的学生生成、学生原生评分均为零。跨新来源的恢复率、保持率和置信区间无法估计。 |
| E1 轨迹与更新 | 已就八个录制来源、每来源四个窗口，在 19 个相同坐标和同一 L1 半径复算直接解与投影次梯度。当前 E2 编码中，全动作监督与最终动作监督所得目标相同。 | 对真实可观察中间动作有独立监督、各臂持有可比信息，完整对比 BP、WSP 与混合更新，并重复测量等质量端到端时间。 |
| E3 多教师 | 同仓同提交的六道开发题逐题比对。两教师都对 0 题，仅第一位对 0 题，仅第二位对 1 题，两者都错 5 题。原协议禁止用这批新的教师输出训练。 | 在未见任务上观察到双向独有成功，获得允许训练的输出，并验证学生继承、旧任务保持与负迁移。 |
| E4 Circuit | 核对两个已曝光六题面板上的 84 个历史节点。在首步验证器报告补丁格式无效时，第二个 Cell 只收原任务。B2 留存成功由 5/6 至 6/6。迁移面板为 0/6。 | 在前瞻独立来源上运行真实路由，与同预算单模型多步、固定图、随机图及去边、去消息、去 Cell 比较。 |
| E5 用户增长 | 原 16 个公开项目中，15 个有实际测量，一个在原位置拒绝。七个满足五项长度约束，0/16 通过完整静态准入，独立真实用户为 0。 | 可核的真实用户、授权轨迹及两次独立的预算实验。目前没有用户增长曲线的观测点。 |

[E6 原件](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6859) · [E2 权重与来源](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6833) · [E1 同半径复算](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7010) · [E3 原记录](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/5e027a1d0c49a2b1408e90491b4cc0bc1660725f/qualification/cell-e3-localteacher-20261118) · [E4 路由复算](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7011) · [E5 原始准入](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7f790fb2f907ef9e618c3c7d233d22135ab00580/qualification/cell-e5-prefix-integrity-20261120/READBACK_RESULT.json)

E6 的几次失败发生在不同位置。早期 NoUpdate15 在 completed-acceptance 内层丢失的错误无法从后来的成功倒推。NoUpdate17 留下实际的权限错误，原 cold01 留下 `actual first publication verification fact differs`。本轮在同一修复源码上恢复依赖，用空私有构建目录运行两个原生边界用例，计费 21.6045 秒。该源码的调用者验证通过，扫描 6,911 个 Rust 文件，B4 原集合为 1,014/1,014，零跳过。产品构建随后实际编译到 agentd 和 infer-worker-host，首组 Cargo 在返回完整清单前超时。本次构建计费 623.7560 秒，累计 1,798.0040/1,800 秒，三组完整构建通过 0/3，修复版发起完整 cold 父测试 0 次。两个单测和源码回归均不增加独立训练样本。[两项原生单测](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f3ef5f150b95342bb6757181e3ba5df67c317ac3/qualification/e6-lifecycle-20261123/native-neuron-boundaries) · [原源码验证](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/fae4819cf8bbc64acc881ea7f9923ffb6e4d008e/qualification/e6-lifecycle-20261123/source-validation) · [产品构建实录](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6859)

对 cold01 当时保留的 34 份原件，又离线重算了首次发布的 16 项条件。旧实现首先在第 12 项失败，它拿已经 drain 的最终摘要去比首次发布时保存的创世摘要。两者分别为 `4a7b04d6…` 与 `ce848407…`。第 13 项单独求值也失败，它要求已完成的那一端仍然是 genesis。修复版从同一份 93 字节日志重建创世摘要，再单独要求完成端已经 drain。在同一旧输入上，16 项和随后四个时间关系全部成立。这是对旧失败的具体解释和对修复方向的离线验证。它没有启动新进程或等待新的租约到期。[逐项复算和原捕获取得方式](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/4dd354f2a3320da157c2473110a9d1a2d45bd489/qualification/e6-lifecycle-20261123/first-publication-predicates)

E2 的 Tomlkit 四个候选都在读取原树内 gitlink 条目时拒绝，验证器和模型均未调用。第三个来源 sqlparse 按冻结顺序扫描前 31 个提交得到四个候选。第一个在原材料校验时拒绝。第二个的父版本和参考修复各跑 499 个用例，各剩一次失败。第三个 `group_functions` 在相同的 100 个用例中从一次失败变为全部通过。它通过了独立的六项容量诊断。两父的冻结与仅答案配置各用 734 个输入 token，检索配置各用 885 个，参考续写均为 230 个，零截断。已取回并核验完整原 PyTorch 分发，使用 Transformers 官方支持的仅分词模式，通过原有四项版本、基座和模板守卫。原准备程序唯一一次调用返回 QUALIFIED。此题来自公开仓库历史提交，五项内容指纹与项目冻结排除集没有交集，基础模型预训练暴露情况仍未知。学生尚未作答。默认张量导入仍因缺少 libcudnn.so.9 失败，生成端未获准。[首个正式准入新来源的原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/c62d42d9d492efa042820f7f570fbecd1399cade/qualification/e2-own-state-20261123/first-qualified-source)

E2 的原汇总器已封存全部八个登记来源，终态为 `PANEL_REFUSED`。六个实际扫描的来源共找到二十个静态候选，按序尝试十九个。sqlparse 首次合格后，依原规则跳过该来源的最后一个候选。colorama 的四项遇到测试目录约束，tomlkit 的四项遇到 gitlink，sqlparse 三项中有一项通过，python-dotenv 的四项均遇到同一条 15 字节文档符号链接。uiri/toml 的四项中，三项会漏跑原测试文件，另一项的父版本与参考修复均因同一语法错误无法导入。jd/tenacity 扫完五十个提交，零候选。另有 inflect 和 exceptiongroup 两个来源在扫描前即因原排除规则拒绝。原名单不替补，实际 1/4 来源合格，用于筛选题目的六个原生子进程均有终态，四个产生共 1,198 个 JUnit 用例实例，另外两个在导入阶段结束。冻结父与修正学生的新配对评分为零。对本轮能作出的结论是来源覆盖不足。下一批可在候选答案不可见时预审仓库的测试入口和文件类型，独立登记随后到达的任务与时间边界。[原名单、逐候选原件与终局](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/cf4e3f8eaf0862248fe3c4927e9eb7ad6886978d/qualification/e2-own-state-20261123/ordered-panel-terminal)

## 在线接入、Cell 通信与链上证明

外部 agent 可通过用户选择接入的本地适配器，输出可见的任务、工具调用、返回值、验证结果和纠正动作。适配器记录来源、会话、时间、训练许可和模型版本。原始轨迹可保留在本地。Hepta 自有学生重做任务，并从自己的失败状态取样。只要有可重放的环境反馈和可验证的纠正动作，这条路径不依赖他方模型的隐藏推理过程或权重访问。上述是基于已核组件提出的接口设计，真实多用户在线闭环仍待实验。

E4 还有一轮实际 GPU 对照。固定图、按任务随机路由、同一模型执行两步、去边与 Cell 替换等控制共执行 162 张图、306 次模型调用，路由搜索额外花费的 72 次调用包含于原研究成本记录。可学习图与 F/F 都在旧 A 保留 5/6。旧 B 上所有臂均为 0/3。在 A 上，两者各有五次首步正确、末步退步。此轮覆盖九道已曝光开发题。针对另一组六道真实上游题，去掉前答边保留 1/6，完整通信和两种同模型对照均为 0/6。[原生模型调用与完整消融](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6693) · [上游对照](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6704)

E4 中增加的一次成功揭示了具体的通信机制。Django 的一道题在转发无效补丁后重复失败，另一适配器单看原题时通过。另一道 Django 题却需要保留业务测试失败后的上下文才能修复。B2 上固定传完整消息的四条路径各为 5/6，即使事后为每题挑第二适配器也只有 5/6。新规则留存 6/6，单看末次答案为 3/6。迁移面板的两次清空均未救回任务，且备用适配器身份有变化。这个结果支持把错误类别、消息内容和保留先前成功一起纳入路由比较。设计规则时已经看过 B2，两个面板都是回放。[逐任务原件、规则与复算入口](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7011)

HIA 已能表达有类型的状态、操作和权限。原语义实验里，MEM 在 B 阶段从 2/8 升至 6/8，确定性基线为 8/8，最后保留原 Cell，新 D-cold 失败。PRED 从 2/8 到 2/8，同样保留原 Cell，新 D-cold 通过。合计两次完整 NoUpdate、零次 Adopt。该运行使用一次性本地操作环境。合成缺陷族存在重叠。HIA 的验收因此可具体落在消息语义、编辑重放和恢复正确性上。要证明 Circuit 自发形成，需要从可学习路由观察到边随训练改变，控制通信与总算力，并在删去特定边后重复观察到跨来源损失。[HIA 语义实验](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6613) · [链仓 HIA 源码审计](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/d5cba2bff83d9d42d372a2833a1f34bc8f4edfbe/hia/AUDIT.md)

链上可先绑定任务、候选和验证器身份及验证结果。学习贡献还需要可比较的冻结基线，以及未参与拟合的任务反馈。原链仓 W1 拒绝路径的六项原生回归通过，混合服务保留 130 条尝试，其中含预期拒绝。历史 F0 的 30 秒目标通过 1/6，4 秒目标通过 0/6，及时 ACK 为 21/42。若要将训练计入有用工作，建议在任务到达前锁定验证器、成本口径和旧能力保持门槛，在封存任务上对同一冻结父模型与候选配对评分。把任务承诺、候选权重摘要、验证结果、真实采用身份及下一任务回执绑定后，按可复核的边际收益记账。重复执行可用于验证一致性，每份任务贡献只计一次。当前缺少同一任务链上能同时证明增量、采用和结算的一组原件。[链仓 W1 与 F0 原记录](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/970)

这次还把 E4 规则写成两个真正的 HIA 入口。第一个只接收首步的验证原因，决定第二步发给谁及带上哪些上下文。第二个在两个验证结果都可用时决定保留哪一步。用固定的 Hepta 编译器生成 529 字节 x86-64 机器码，原解释器与原生 ELF 在全部 12 条轨迹、256 个原因值和四种成败组合上结果一致。解释执行分别耗 4 和 7 步，均无堆分配。这个实验证实了同一小段决策逻辑可以跨两个后端重放，任务结果仍来自原先那 12 道题。[HIA 源码和双后端执行结果](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d841a20332b78e9120baad3e61b41c848f4ecb9e/qualification/cell-verifier-routing-20261123/hia)

保持两个调用槽及清空上下文的次数固定后，B2 的六种随机放置中有一种保留 6/6，四种保留 5/6，一种只保留 4/6。上游面板的十五种放置均为 0/6。这些分配重用同一组任务。可学习 Circuit 的直接设计是让路由器只读取派发前已经可见的任务特征、上一步验证状态和可用预算，在少数 Cell 与消息类型之间选择。训练时用可观测的增量任务成功与通信成本给边分配信用。评估时冻结路由器，在独立来源随机分配完整图和消融图，共同报告每任务成功、调用、token、实际传输字节和尾部时延。若断开某条常用边后效用仍保持，就有证据支持删去这条边。[精确随机放置对照](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/5c2ed3fb01179a01e913770042cd97ee26d473b0/qualification/cell-verifier-routing-20261123/random-placement)

## 直接编辑能否取代反向传播

外部研究提供了两类相关实证。Petals 展示了不同参与方共享资源来推理和微调既有大模型的可行性。Weight-Space Programming 作者在 Qwen3.5-0.8B 的一个实例中报告，直接修改 0.016% 权重缓解了解码循环，在相同采样设置下提高了数学评测成绩。前者验证分布式执行，后者验证可定位行为的编辑。Hepta 自己的独立新任务和全程计时才直接回答本系统的训练收益。[Petals 原论文](https://aclanthology.org/2023.acl-demo.54/) · [WSP 作者的实验 8](https://rikiyat.github.io/blog/weight-space-programming/)

是否有闭式更新，取决于待改参数怎样进入损失。举例说，若 Cell 的特征矩阵 X 已冻结，只有读出 W 可变，目标是平方误差加权重位移惩罚，就可以解线性方程 (XᵀX + λI)ΔW = Xᵀ(Y − XW₀)。这一步能省下多次迭代。构造特征、因子分解、检查保持能力仍需计时。如果一次改动还会改变 X 或改变路由，下游访问哪些任务也随之变化，原方程便无法计算这部分收益。这个例子说明可以直接求解的条件。下方 E1 使用的是原研究自己的目标。

2026 年的两项研究进一步影响了基线选择。LocFT-BF 作者发现，在选好的参数位置用小批量遍历一组编辑样本，能显著改变微调的顺序干扰表现。KLOD 在 CounterFact 和 ZsRE 上用非目标输出分布约束局部微调，改善了与编辑无关的知识保持。对 Hepta 的具体启示是，把预算相同的局部 BP 放进对照，并用保留任务检验串行编辑产生的漂移。这两项研究的训练目标都是知识编辑，推广到 agent 的多步决策仍需实测。[LocFT-BF 原文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/74b8ccb5ad21871fd436867df19c35ac-Abstract-Conference.html) · [KLOD 原文](https://aclanthology.org/2026.findings-emnlp.1241/)

在 E1 的同坐标比较里，半径 0.25 时两法的 32 个决策完全相同，净效用均为 0.765625。半径 1 时，直接解的训练目标更优，测试效用为 0.696875，梯度法为 0.756250。梯度法多答对一个窗口、少购买三次，来源层面三胜五平。半径 4 重复了各自半径 1 的权重。半径 0.25 的单次求解计时为直接解 7.23 毫秒、投影次梯度 2.66 毫秒，只覆盖求解片段。八个来源均来自原研究，本轮没有新增训练重复。[逐来源比较](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7010)

更大范围的 HCSN 实验也给出了方法选择的依据。45 次运行覆盖三个 seed，条件读出的直接解相对未训练读出使开发 MSE 降低 70.08%，三个 seed 最终均选中含外层 BP 的方法。全 HCSN 与小型因果 Transformer 的测试 MSE 分别为 0.079779 和 0.033770，中位冷进程用时 114.48 秒和 3.98 秒，分类准确率分别为 91.2% 和 90.1%。另一个实验让直接法与梯度法共享 196 个坐标和同一信任域，五个检查点均触发原最坏情形门槛。可解析读出适合直接求解，定位清楚的故障适合定点编辑。需学习的表征、动力学或路由目前仍有保留 BP 的实证理由。[HCSN 固定比较](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6958) · [五检查点同坐标更新](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6984) · [WSP 盲修](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6987)

在同一预测任务的 15 次适配运行中，还可比较到达完全相同权重和质量的时间。直接解、Profile BP 和 Joint BP 在每个 seed 的首个更新候选状态摘要、开发 MSE 与保持 MSE 均相同。到达此处的内层实测时间在 6.1–6.8 秒。直接解的完整冷进程为 8.54–8.84 秒，两个 BP 臂分别继续评估八个候选，最终开发 MSE 在三个 seed 上都更低。六个直接解对 BP 的同状态首达冷时间比较中，五个区间重叠，一个 seed 的直接解比 Joint BP 至少早约 0.26 秒。开发集参与选模，测试集查询为零。这组数据支持按目标精度选择是否继续优化。[完整逐 seed 配对与时间界](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/797d16efff3c6e6f8547186fbca4d502c5d8f8c6/qualification/hcsn_blocker_followup/matched_radii/cold-paired)

E1 可以把两个问题交叉设计。先对同一批任务建立仅最终动作、完整可见轨迹两种监督，核对它们确实提供不同的目标。每个监督条件内让直接解、局部 BP、WSP 与混合方法访问相同的样本、工具反馈、父权重、参数范围和验证预算。所有学生在推理时只取得任务当时可见的输入。每个训练重复都记录达到同一预定效用和保持门槛的端到端时间，未达门槛的运行连同成本保留。这样能分别估计增加轨迹信息的收益、改变更新器的收益，以及两者的交互。

E3 对每个新任务按冻结的评分规则统计四种结果，包括两教师都对、仅第一位对、仅第二位对、都错。若同一批任务上确实有双向独有成功，再让等预算的双教师学生和两个单教师学生在另外封存的任务上比较，并分别报告各教师擅长任务族的保持和退化。知道每题哪个教师会成功的事后上界，可用于诊断互补性。上线选择教师的路由器只能读取派发当时可见的信息。

**科学验收以配对的新任务效用为准。** 按来源和时间隔离，冻结更新前的学生，分别记录首答、末答、保留的答案、旧能力损失和真实采用后下一任务。代价覆盖采集、教师调用、更新程序编写、求解、验证、失败重试与恢复。训练重复、来源、任务和任务内窗口分别报告。E5 固定总预算的曲线用来衡量来源多样性，固定每来源预算的曲线同时包含总投入增加的作用。两者应共用按时间封存的评测任务，并分别报告总算力、独立来源数、来源间差异及训练重复。当前没有适合画成实测曲线的数据。

若最终主张是形成新的 foundation model，还要把推理时的外部教师调用关闭。让同一套可保存、可重载的自有权重与 Circuit 在多个互补能力域独立作答，对照等预算的单教师学生、单模型多步和固定路由，并在训练后到达的新用户任务上复核。这样才能从单次工具调用成功，逐级检验学生继承、组织结构价值和跨任务可迁移能力。
