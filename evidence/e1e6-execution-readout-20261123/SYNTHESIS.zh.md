# Hepta 去中心化训练与有用工作实验审计

2026 年 11 月 23 日。对两个仓库固定的 main 提交，逐目录重新计算了全部 Git tree，包括每条路径、模式和对象标识。hepta-private-ci 有 8,665 条文件路径，Trillionnium-Chain 有 41,834 条，共 50,499 条。完整性范围是这两个目录树。对训练源码和原始输出的内容审计聚焦 E1–E6 的研究分支，另核查了 11 月 20 日以来更新的 243 个 Hepta PR 和 13 个链仓 PR。研究分支中的结果有各自的提交身份。[主干树清单与固定提交](MAIN_TREES.json)

**现有实现足以让一个 Cell 接收任务反馈、提出可回放的权重修改、核验结果并恢复原状态。完整的在线学习收益仍缺一条连续记录。** 同一固定预算下，自有学生须在按来源和时间隔离的任务上提高，保留旧能力，冷重启后实际采用同一候选，并改善随后到来的真实任务。当前证据分别落在这条链的不同位置。[联合原验收](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6703) · [真实 HIA/Cell 执行](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6613)

## 每项实验实际测到了什么

| 实验 | 观测与统计单位 | 尚缺的判定 |
|---|---|---|
| E6 完整生命周期 | Q24 解析 Cell 的 warm NoUpdate19 已完整通过，四项原生回归为同一次工程验证。旧 cold01 真正启动后，在首次发布的验证事实比对处失败。固定修复源码的两个原生 neuron 边界用例已通过。 | 新源码跑完原 cold 父、真正 Adopt、采用后下一任务，以及对应的生产采用或结算。 |
| E2 学生自身纠错 | 已保存的四条自身失败纠正记录来自三个项目。两个既有父学生各执行八次更新。新来源按冻结顺序收取，同一来源的多个候选只算一个来源。 | 四个符合原约束的新来源，随后在未曝光任务上配对比较冻结父与修正学生，并记录回归。 |
| E1 轨迹与更新 | 已就八个录制来源、每来源四个窗口，在 19 个相同坐标和同一 L1 半径复算直接解与投影次梯度。当前 E2 编码中，全动作监督与最终动作监督所得目标相同。 | 对真实可观察中间动作有独立监督、各臂持有可比信息，完整对比 BP、WSP 与混合更新，并重复测量等质量端到端时间。 |
| E3 多教师 | 同仓同提交的六道开发题逐题比对。两教师都对 0 题，仅第一位对 0 题，仅第二位对 1 题，两者都错 5 题。原协议禁止用这批新的教师输出训练。 | 在未见任务上观察到双向独有成功，获得允许训练的输出，并验证学生继承、旧任务保持与负迁移。 |
| E4 Circuit | 核对两个已曝光六题面板上的 84 个历史节点。在首步验证器报告补丁格式无效时，第二个 Cell 只收原任务。B2 留存成功由 5/6 至 6/6；迁移面板为 0/6。 | 在前瞻独立来源上运行真实路由，与同预算单模型多步、固定图、随机图及去边、去消息、去 Cell 比较。 |
| E5 用户增长 | 原 16 个公开项目中，15 个有实际测量，一个在原位置拒绝。七个满足五项长度约束，0/16 通过完整静态准入，独立真实用户为 0。 | 可核的真实用户、授权轨迹及两次独立的预算实验。目前没有用户增长曲线的观测点。 |

[E6 原件](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6859) · [E2 权重与来源](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6833) · [E1 同半径复算](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7010) · [E3 原记录](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/5e027a1d0c49a2b1408e90491b4cc0bc1660725f/qualification/cell-e3-localteacher-20261118) · [E4 路由复算](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7011) · [E5 原始准入](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7f790fb2f907ef9e618c3c7d233d22135ab00580/qualification/cell-e5-prefix-integrity-20261120/READBACK_RESULT.json)

E6 的几次失败发生在不同位置。早期 NoUpdate15 在 completed-acceptance 内层丢失的错误无法从后来的成功倒推。NoUpdate17 留下实际的权限错误，原 cold01 留下 `actual first publication verification fact differs`。本轮在同一修复源码上恢复依赖，用空私有构建目录运行两个原生边界用例，计费 21.6045 秒。该源码的调用者验证通过，扫描 6,911 个 Rust 文件，B4 原集合为 1,014/1,014，零跳过。产品构建随后实际编译到 agentd 和 infer-worker-host，首组 Cargo 在返回完整清单前超时。本次构建计费 623.7560 秒，累计 1,798.0040/1,800 秒，三组完整构建通过 0/3，修复版发起完整 cold 父测试 0 次。两个单测和源码回归均不增加独立训练样本。[两项原生单测](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f3ef5f150b95342bb6757181e3ba5df67c317ac3/qualification/e6-lifecycle-20261123/native-neuron-boundaries) · [原源码验证](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/fae4819cf8bbc64acc881ea7f9923ffb6e4d008e/qualification/e6-lifecycle-20261123/source-validation) · [产品构建实录](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6859)

E2 的 Tomlkit 四个候选都在读取原树内 gitlink 条目时拒绝，验证器和模型均未调用。第三个来源 sqlparse 按冻结顺序扫描前 31 个提交得到四个候选。第一个在原材料校验时拒绝。第二个的父版本和参考修复各跑 499 个用例，各剩一次失败。第三个 `group_functions` 在相同的 100 个用例中从一次失败变为全部通过。它通过了独立的六项容量诊断。两父的冻结与仅答案配置各用 734 个输入 token，检索配置各用 885 个，参考续写均为 230 个，零截断。正式准备要求原后端版本守卫，学生尚未作答。[按序来源与收据](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6833)

对 cold01 当时保留的 34 份原件，又离线重算了首次发布的 16 项条件。旧实现首先在第 12 项失败，它拿已经 drain 的最终摘要去比首次发布时保存的创世摘要。两者分别为 `4a7b04d6…` 与 `ce848407…`。第 13 项单独求值也失败，它要求已完成的那一端仍然是 genesis。修复版从同一份 93 字节日志重建创世摘要，再单独要求完成端已经 drain。在同一旧输入上，16 项和随后四个时间关系全部成立。这是对旧失败的具体解释和对修复方向的离线验证。它没有启动新进程或等待新的租约到期。[逐项复算和原捕获取得方式](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/4dd354f2a3320da157c2473110a9d1a2d45bd489/qualification/e6-lifecycle-20261123/first-publication-predicates)

## 在线接入、Cell 通信与链上证明

外部 agent 可通过用户选择接入的本地适配器，输出可见的任务、工具调用、返回值、验证结果和纠正动作。适配器记录来源、会话、时间、训练许可和模型版本。原始轨迹可保留在本地。Hepta 自有学生重做任务，并从自己的失败状态取样。只要有可重放的环境反馈和可验证的纠正动作，这条路径不依赖他方模型的隐藏推理过程或权重访问。上述是基于已核组件提出的接口设计，真实多用户在线闭环仍待实验。

E4 还有一轮实际 GPU 对照。固定图、按任务随机路由、同一模型执行两步、去边与 Cell 替换等控制共执行 162 张图、306 次模型调用，路由搜索额外花费的 72 次调用包含于原研究成本记录。可学习图与 F/F 都在旧 A 保留 5/6；旧 B 上所有臂均为 0/3。在 A 上，两者各有五次首步正确、末步退步。此轮覆盖九道已曝光开发题。针对另一组六道真实上游题，去掉前答边保留 1/6，完整通信和两种同模型对照均为 0/6。[原生模型调用与完整消融](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6693) · [上游对照](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6704)

E4 中增加的一次成功揭示了具体的通信机制。Django 的一道题在转发无效补丁后重复失败，另一适配器单看原题时通过。另一道 Django 题却需要保留业务测试失败后的上下文才能修复。B2 上固定传完整消息的四条路径各为 5/6，即使事后为每题挑第二适配器也只有 5/6。新规则留存 6/6，单看末次答案为 3/6。迁移面板的两次清空均未救回任务，且备用适配器身份有变化。这个结果支持把错误类别、消息内容和保留先前成功一起纳入路由比较。设计规则时已经看过 B2，两个面板都是回放。[逐任务原件、规则与复算入口](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7011)

HIA 已能表达有类型的状态、操作和权限。原语义实验里，MEM 在 B 阶段从 2/8 升至 6/8，确定性基线为 8/8，最后保留原 Cell，新 D-cold 失败。PRED 从 2/8 到 2/8，同样保留原 Cell，新 D-cold 通过。合计两次完整 NoUpdate、零次 Adopt。该运行使用一次性本地操作环境；合成缺陷族存在重叠。HIA 的验收因此可具体落在消息语义、编辑重放和恢复正确性上。要证明 Circuit 自发形成，需要从可学习路由观察到边随训练改变，控制通信与总算力，并在删去特定边后重复观察到跨来源损失。[HIA 语义实验](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6613) · [链仓 HIA 源码审计](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/d5cba2bff83d9d42d372a2833a1f34bc8f4edfbe/hia/AUDIT.md)

链上可先绑定任务、候选和验证器身份及验证结果。学习贡献还需要可比较的冻结基线，以及未参与拟合的任务反馈。原链仓 W1 拒绝路径的六项原生回归通过，混合服务保留 130 条尝试，其中含预期拒绝。历史 F0 的 30 秒目标通过 1/6，4 秒目标通过 0/6，及时 ACK 为 21/42。协议层工作凭据、模型效用增量和实际结算应分别记录。当前缺少同一任务链上能同时证明增量、采用和结算的一组原件。[链仓 W1 与 F0 原记录](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/970)

这次还把 E4 规则写成两个真正的 HIA 入口。第一个只接收首步的验证原因，决定第二步发给谁及带上哪些上下文。第二个在两个验证结果都可用时决定保留哪一步。用固定的 Hepta 编译器生成 529 字节 x86-64 机器码，原解释器与原生 ELF 在全部 12 条轨迹、256 个原因值和四种成败组合上结果一致。解释执行分别耗 4 和 7 步，均无堆分配。这个实验证实了同一小段决策逻辑可以跨两个后端重放，任务结果仍来自原先那 12 道题。[HIA 源码和双后端执行结果](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d841a20332b78e9120baad3e61b41c848f4ecb9e/qualification/cell-verifier-routing-20261123/hia)

保持两个调用槽及清空上下文的次数固定后，B2 的六种随机放置中有一种保留 6/6，四种保留 5/6，一种只保留 4/6。上游面板的十五种放置均为 0/6。这些分配重用同一组任务。可学习 Circuit 的直接设计是让路由器只读取派发前已经可见的任务特征、上一步验证状态和可用预算，在少数 Cell 与消息类型之间选择。训练时用可观测的增量任务成功与通信成本给边分配信用。评估时冻结路由器，在独立来源随机分配完整图和消融图，共同报告每任务成功、调用、token、实际传输字节和尾部时延。若断开某条常用边后效用仍保持，就有证据支持删去这条边。[精确随机放置对照](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/5c2ed3fb01179a01e913770042cd97ee26d473b0/qualification/cell-verifier-routing-20261123/random-placement)

## 直接编辑能否取代反向传播

外部研究提供了两类相关实证。Petals 展示了不同参与方共享资源来推理和微调既有大模型的可行性。Weight-Space Programming 作者在 Qwen3.5-0.8B 的一个实例中报告，直接修改 0.016% 权重缓解了解码循环，在相同采样设置下提高了数学评测成绩。前者验证分布式执行，后者验证可定位行为的编辑。Hepta 自己的独立新任务和全程计时才直接回答本系统的训练收益。[Petals 原论文](https://aclanthology.org/2023.acl-demo.54/) · [WSP 作者的实验 8](https://rikiyat.github.io/blog/weight-space-programming/)

在 E1 的同坐标比较里，半径 0.25 时两法的 32 个决策完全相同，净效用均为 0.765625。半径 1 时，直接解的训练目标更优，测试效用为 0.696875，梯度法为 0.756250。梯度法多答对一个窗口、少购买三次，来源层面三胜五平。半径 4 重复了各自半径 1 的权重。半径 0.25 的单次求解计时为直接解 7.23 毫秒、投影次梯度 2.66 毫秒，只覆盖求解片段。八个来源均来自原研究，本轮没有新增训练重复。[逐来源比较](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7010)

更大范围的 HCSN 实验也给出了方法选择的依据。45 次运行覆盖三个 seed，条件读出的直接解相对未训练读出使开发 MSE 降低 70.08%，三个 seed 最终均选中含外层 BP 的方法。全 HCSN 与小型因果 Transformer 的测试 MSE 分别为 0.079779 和 0.033770，中位冷进程用时 114.48 秒和 3.98 秒，分类准确率分别为 91.2% 和 90.1%。另一个实验让直接法与梯度法共享 196 个坐标和同一信任域，五个检查点均触发原最坏情形门槛。可解析读出适合直接求解，定位清楚的故障适合定点编辑；需学习的表征、动力学或路由目前仍有保留 BP 的实证理由。[HCSN 固定比较](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6958) · [五检查点同坐标更新](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6984) · [WSP 盲修](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6987)

在同一预测任务的 15 次适配运行中，还可比较到达完全相同权重和质量的时间。直接解、Profile BP 和 Joint BP 在每个 seed 的首个更新候选状态摘要、开发 MSE 与保持 MSE 均相同。到达此处的内层实测时间在 6.1–6.8 秒。直接解的完整冷进程为 8.54–8.84 秒，两个 BP 臂分别继续评估八个候选，最终开发 MSE 在三个 seed 上都更低。六个直接解对 BP 的同状态首达冷时间比较中，五个区间重叠，一个 seed 的直接解比 Joint BP 至少早约 0.26 秒。开发集参与选模，测试集查询为零。这组数据支持按目标精度选择是否继续优化。[完整逐 seed 配对与时间界](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/797d16efff3c6e6f8547186fbca4d502c5d8f8c6/qualification/hcsn_blocker_followup/matched_radii/cold-paired)

**科学验收以配对的新任务效用为准。** 按来源和时间隔离，冻结更新前的学生，分别记录首答、末答、保留的答案、旧能力损失和真实采用后下一任务。代价覆盖采集、教师调用、更新程序编写、求解、验证、失败重试与恢复。训练重复、来源、任务和任务内窗口分别报告。E5 固定总预算与固定每来源预算应各自保持任务分布和评测规则，真实观察到收益后才能画增长曲线。

若最终主张是形成新的 foundation model，还要把推理时的外部教师调用关闭。让同一套可保存、可重载的自有权重与 Circuit 在多个互补能力域独立作答，对照等预算的单教师学生、单模型多步和固定路由，并在训练后到达的新用户任务上复核。这样才能从单次工具调用成功，逐级检验学生继承、组织结构价值和跨任务可迁移能力。
