# Hepta / Trillionnium：六组实验的实际结果与架构决策

## 结论

经授权的 Agent 可见轨迹 → 版本化经验 → 本地或分布式 Cell 学习 → 有成本约束的稀疏 Circuit，是值得继续实现和检验的研究路线。当前代码与本轮实验尚未证明用户越多就会自动产生更好的组织，也未证明可以综合所有大模型长处成为新 foundation model。

本轮已实际完成四次 64 步 Qwen LoRA 训练、六个分支的主评估和六个新进程冷复测。最终答案监督在六个已训练 A 任务上成功 5 个，轨迹监督成功 4 个；所有分支在三个已曝光 B 任务上均为 0。冷重载保持对应业务结果。上述结论是开发条件中的描述性结果；新独立用户、新外部教师、新 C 和新增独立样本均为 0。

原始资源门槛失败、早期负结果、原诊断的接口误拒绝和后续编号的修订分析全部保留。本报告不把原结果覆盖为成功，也不把事后修订分析称为事先注册的确认实验。

## 1. 审计覆盖与证据边界

审计固定 Hepta main 732e934ba496d90fbe042b8d41d479ef901643e5 与 Chain main 59bd6ae4223caff6695dc9cf2ee2cdcdc6df5e88，历史实验按各自精确提交核对。Hepta 枚举 9,843 个目录树项（8,665 blobs、1,178 trees），深读约 20 份关键实现/段落及相关报告，并核对 36 份 hepta_cells 对象身份。Chain 覆盖包/子树结构、关键资格文档与真实 issue 线索。目录枚举不是所有文件逐行审计；本报告也不是整个系统已无缺陷的证明。

来源审计找到了 SQLite 工作流需求、受控环境与历史轨迹，未核验到足以建立新来源/未来时间划分的外部真实用户 coding-agent 轨迹。H7 schema 的 observation-only 约束不能证明实际数据库中已有可训练动作与反馈；本轮未读取其实际数据库，行数保持未知。ACT-2 的 80 条脚本轨迹、448 个事件属于一个 SQLite 环境家族；3200 个 episode 来自任务×种子×分支，不能当作 3200 个独立经验。三个相关 Chain issue 的发布者为同一账户，不能视作三个独立用户。[来源审计][source-audit]

## 2. 本轮比较究竟是什么

本轮使用固定 Qwen2.5-Coder-1.5B-Instruct、同一 tokenizer/runtime 与受控 generation 参数，四个 SFT 分支均采用 rank 4、q/v LoRA、相同 AdamW/学习率/种子/数值策略，完成 64 步、batch 1、序列形状 1536。每个完整 fit 为 98,304 个 padded positions，四个共 393,216。

协议 research.authored-sft.v1 是在原 parent03 A=0/6 的失败被观察后另建的探索研究：监督来自经过业务检查的 authored A 标签。任务主要是取自仓库的局部代码/测试开发条件，不等于新取得的真实用户委托或开放式仓库修复。原 native positive-A admission 未降低，研究候选命名空间和原采用路径隔离。它不冒充外部教师示范，也不是六项原始科学问题已完成。

| 分支 | 实际训练步数 | A 首次成功 | A 最终成功 | B 首次/最终成功 | 冷进程 A / B |
| --- | ---: | ---: | ---: | ---: | ---: |
| 冻结 parent | 0 | 0/6 | 0/6 | 0/3 | 0/6；0/3 |
| parent + retrieval | 0 | 0/6 | 0/6 | 0/3 | 0/6；0/3 |
| final_answer SFT | 64 | 5/6 | 5/6 | 0/3 | 5/6；0/3 |
| trajectory SFT | 64 | 4/6 | 4/6 | 0/3 | 4/6；0/3 |
| shadow_correction SFT | 64 | 0/6 | 0/6 | 0/3 | 0/6；0/3 |
| controlled_correction SFT | 64 | 1/6 | 1/6 | 0/3 | 1/6；0/3 |

每项评估最多两次尝试。A 包含训练任务，B 已在先前开发中曝光；cold 只是同一任务集在新进程中的重复，独立样本增量为 0。A 的原成功集合为空，按原成功集合定义的保留率/遗忘率分母为零，应为 null。不能从 A 的绝对成功数计算零基线相对增长百分比。

| SFT 分支 | 实际训练输入 tokens | 实际监督 tokens | Padded positions | 训练 scope wall 秒 |
| --- | ---: | ---: | ---: | ---: |
| final_answer | 23,813 | 5,390 | 98,304 | 106.163 |
| trajectory | 25,882 | 4,884 | 98,304 | 106.449 |
| shadow_correction | 44,011 | 5,390 | 98,304 | 100.937 |
| controlled_correction | 74,643 | 5,390 | 98,304 | 99.770 |

训练 scope 包含验证、模型加载、编码、训练与保存，不是纯 optimizer 时间。相同形状和 64 步并不等于相同监督信息、端到端成本或实际 GPU 工作量；parent/retrieval 没有 SFT 成本。四臂的上下文、turn、mask 和监督数量不同，不能把结果差异全部归因于是否有轨迹。[解释边界][interpretation]

controlled 分支使用固定旧 parent03 的受控轨迹，不是更新后的学生再执行、纠正和更新的 on-policy 循环。六份新 shadow 输出没有实际执行，authored reference 检查的通过也不计入学生成功。

四个保存 adapter 各有 544,768 个有限参数，其实际 tensor 字节重建哈希均与各自训练回执一致，四份 after 身份不同。主评估 10 次成功中有 8 次答案字节与 authored A 标签完全相同，另 2 次是通过相同业务检查的生成变体；这些 A 结果仍不能提供来源外泛化证据。

冷复测确认新的实际 PID 使用同一候选文件和 manifest，复测旧 A/B 的推理行为。它不检验 optimizer、RNG、数据游标和中断步骤恢复，更不替代新 C、独立选择或生产采用。

## 3. 六组实验的实际状态

| 实验 | 当前获得的证据 | 仍不能回答的问题 |
| --- | --- | --- |
| E1 轨迹价值 | 四类主对照可实际运行，authored A 上答案监督 5/6、轨迹监督 4/6；B 均 0/3 | 未见来源和未来任务上的额外价值，尚无证据 |
| E2 自身经验 | 影子预测、旧学生受控经验与修正训练已有明确来源和运行回执 | 更新后学生偏离路径的恢复能力；本次并非学生迭代采样比较 |
| E3 多教师 | 来源/教师身份约束已明确；没有伪造额外教师 | 最佳单教师与真实多教师的互补和负迁移，未执行合格比较 |
| E4 Circuit | 固定专家池可作事后首试成功覆盖诊断 | 实际学习连接、匹配活动参数与全成本、逐 Cell/逐边消融收益，未成立 |
| E5 用户增长 | 来源去重和 1/4/16/64 两种预算制度的计量约束已实现 | 当前六个声明来源不是六个认证用户；16/64 来源档缺材料，未产生增长曲线 |
| E6 完整采用 | 同一候选保存、主评估与新进程推理重载可核对 | 独立 B 选择、全新 C、真实采用与生产 owner 冷恢复仍缺失 |

科学确认、Circuit、native adoption、PoUW、独立选择和 new_C 资格均保持 false；candidate_selected 为 null。没有把专家成功并集当成真实路由成功，没有把 NoUpdate 改称采用成功。

## 4. 原诊断异常与事后修订

原冻结诊断给六个分支全部标记 UNAVAILABLE，原因均为 evaluation task order or coverage differs。独立源码/原件复核发现：helper 在内存中创建 B_exposed→A_retention；INPUTS 写成 canonical JSON 时键排序为 A_retention→B_exposed，producer 从该原件读取并执行；diagnostic 却重建内存对象，用其顺序检查 rows。两者内容和 canonical digest 相等，遍历顺序不同。十二份主/冷 EVALUATION 原件覆盖完整、无重复任务，顺序均符合实际冻结 INPUTS。

最小修订保留原 context 内容、parent、readiness、runtime、admission 和输入 SHA 检查；通过后将下游 context 置为原冻结 INPUTS 的 recorded_context。原 rows 精确顺序、同 panel 顺序、任务覆盖、候选/cold 及全部资格门槛不变。没有将比较改成集合，也没有替换缺失专家。原 source/rules/DIAGNOSTIC 原字节保留；修订源码与真实离线读取以单独 posthoc 身份保存，不调用原 main，不覆盖原输出。

六项针对真实绑定块、evaluation 前缀和 cold guard 的 stdlib 回归实际通过。随后独立 outer runner 真实执行并 exit 0，未启动模型、业务 verifier 或新 C；原规则、source 和 DIAGNOSTIC 的固定身份保持。新 DIAGNOSTIC SHA-256 为 5aed01965e9d1cb6575bc97b8e760e13ffcd656ab15b8c4a88dd33674a5929b7，明确 posthoc=true。六个分支全部通过原件可用性检查、binding_errors 为空，全部科学/采用资格仍为 false。

首试成功集合显示 final_answer 五项包含 trajectory 的四项和 controlled 的一项。固定三槽的 A 并集为 5/6，最佳单槽也是 5/6，union_exceeds_best=false，routing_executions=0。按照原诊断规则，本批专家池停止在 union <= best single slot：没有额外成功覆盖供路由利用。这个结论只限于本批旧 A 的覆盖诊断；不能扩写成所有 Circuit 均无用，也不能冒称已经完成 E4 的匹配成本与消融实验。

原冻结诊断的 binding_errors=[] 只表示它没有记录 collection_binding 错误，各臂异常另存在 arm.reason，不能据此称全部验证通过。原“诊断完成”也不代表专家槽位可用。详情见[接口审查](../interface-review/REVIEW.md)及[事后修订说明](../posthoc/source/README_POSTHOC.md)与[实际只读结果回执](../posthoc/result/POSTHOC_RECEIPT.json)。

## 5. 实际执行、业务判定和成本

独立只读复核核对 1,248 个选定原件并完成 4,416 项检查，实际分析 exit 0。它从真实 request/output/step 和语义回执追到原始业务观察及错误输出控制，未重新运行模型或 verifier。主评估 98 次学生验证中，62 次在 invalid_test_patch 准入处拒绝，36 次进入业务 fixture（26 次失败、10 次成功）；cold 得到相同分类。合计 196 次验证 = 124 次准入拒绝 + 52 次业务失败 + 20 次业务成功，真正进入 fixture 的是 72 次。原始测试通过和错误输出控制被拒绝是正例的验收依据；并非语法通过，也未声称完整仓库集成测试通过。详情见[封存结果复核](../result-review/RESULT_REVIEW_02.md)。

RESULT retained ledger 对本次保存调用范围的总量完整，global_totals_unknown=false；原 DIAGNOSTIC 因专家槽拒绝仍保存全局 null/unknown=true，两份小计相同。新 posthoc 通过原件校验后，该范围的诊断总量为 202/196/36/256，与独立核对一致。三个版本均保留；这些调用计数完整不等于全系统资源成本完整。原 EVALUATION 的部分 primitive subject 尝试总数仍未知，不能补零。

| Run02 新增运行范围 | 已记录数量 | 解释 |
| --- | ---: | --- |
| 完整 fit / optimizer steps | 4 / 256 | 不是计划数量；有实际步骤和参数变化记录 |
| primary / cold / collector workers | 6 / 6 / 1 | 实际退出均为 0，cold 是新 PID 的推理重载 |
| 完成模型输出 | 202 | 196 个主/冷评估输出，加 6 个未执行的 shadow 输出 |
| 学生 verification 回执 | 196 | 包含解析拒绝与失败；不能全称实际业务测试执行 |
| authored reference 回执 | 36 | 验证监督目标；不计学生成功或新独立样本 |
| 推理输入 / 输出 tokens | 92,217 / 30,896 | 不包含训练 tokens、旧 parent03 调用或未知人工成本 |
| 训练 padded positions | 393,216 | 四个 fit 的固定形状总量，不等于有效监督 tokens |
| coordinator wall 秒 | 2,720.283 | 包含该研究流程，约 45.34 分钟；不能与嵌套 worker/fit wall 再累加 |

所有分支都保留零成功、失败尝试与其成本。coordinator 自身 CPU 为 7.448896 秒、已完成子进程 CPU 为 2,772.224186 秒，两者 scope 明确；worker/training/panel 又是嵌套明细，不能重复相加。四次训练各自 CUDA 峰值 allocated 3,753,495,552 bytes、reserved 4,150,263,808 bytes；这些不是全机同时峰值或 GPU 活跃秒。能耗、金额、完整 GPU 时间、人工标签成本和全系统净效用仍未知，full_system_cost 未补成零。

独立复核确认同候选、不同进程的 raw answers、output token IDs 和业务分数保持；同时发现 final_answer 与 trajectory 的 B-json-format 第二次请求反馈包含 Python ast.Name 对象地址。主/冷进程地址不同，messages SHA 不同，input_tokens 分别为 408→407、399→398。因而不能声称全部输入历史或费用逐位一致；后续版本应把错误反馈变为稳定的错误码与固定字段，原实验字节不回改。

研究01保留为资源 admission 失败：6 个新 shadow、36 次 reference 检查、4 个 fit 入口，但完成 fit 和 optimizer step 均为 0；6 个 primary 在原 4 GiB admission 拒绝，没有学生评估与 cold。该结果不是 OOM 证据，也不能改称零成本 NoUpdate。研究02是明确另行编号的资源重排，原模型、训练/生成参数与门槛未放宽。更早 parent02 的磁盘空间失败及部分尾部未知也继续保留。

控制端曾短暂上报 lost/target_reboot，但同一原 SSH、watcher 与目标进程仍被观察到存活、继续写原输出；最终原两个 PTY 都返回真实 exit 0 与完整输出。没有据此重启模型、发送信号终止其他任务，或声称已证明机器重启。中间失联观察与最终真实关闭记录并列保存。

原 Run02 ZIP 为 29,880,237 bytes、1,687 个成员，SHA-256 为 a852fa6d9ce8317edd15bd7e6edeb3ee12e97e3d27c4ba179e5fe2c34846ad61；Desktop/Mac 均核验分块、ZIP CRC 和成员摘要。完整原 RESULT 和原 DIAGNOSTIC 是归档内成员，按[恢复说明](../export/RESTORE.txt)及包内索引恢复，不能把归档目录冒称直接 JSON 链接。事后修订另存，没有替换这个归档。

## 6. 现有代码的真实基础

| 层 | 已有实现或原件 | 主要边界 |
| --- | --- | --- |
| Cell | 身份、预算、状态、可塑参数、候选、版本与 owner 接口 | 角色名称不等于学成该能力；逻辑 Cell 数不等于完整模型副本数 |
| Population | 同底座共享冻结表示、局部私有 head；受控塑性范围 | 没有自动细胞分裂、合并和形成组织的能力证明 |
| HIA | 原请求/pending 保存、native begin、真实 Cell.step、native resume、保留结果恢复 | 编译/continuation 不保证业务正确；结果丢失仍为 unknown |
| Circuit | Compute/Decide/Subcircuit/Join/Exit、条件边与有界反馈、显式 schema | 图可执行不等于连接已学习；尚未证明等成本连接收益 |
| Microbatch | runtime/bundle/state schema 兼容时合批；各 scope 单独提交状态 | 不能跨任意底座无条件合批，也没有线性扩展实测 |
| 链与资格 | 承诺、来源、候选及采用链可做版本/审计承载 | 链上记录与哈希不自动证明独立任务有用性或奖励公平 |

这些结论来自固定源码和原资格材料，具体文件、原执行闭包及身份见[架构研究][architecture]。旧 HIA campaign 的 722 次 continuation、208 次 compile、32 次 Adam 更新是限定执行事实；其原任务属于四个语法模板，不能升级为真实 coding 业务泛化。MEM B 从 2/8 到 6/8，规则控制为 8/8，相关 gate 仍为 NoUpdate。历史共享可塑性实验中，参数耦合既有正向也有负向变化，18 个学习结构未胜过强控制。系统没有因为采用生物学术语而自动获得跨任务共享能力。

## 7. 接入其他 Agent：最小可用训练闭环

建议把服务、采集和训练分开版本化。用户照常使用原 Agent；接入器只采集经授权的可见任务、消息、工具调用、真实返回、状态差异、用户纠正与最终业务结果。经验在本地去除凭据及无关私有内容，记录工具/模型版本、原事件时间、项目/用户/请求/lineage、允许用途和验收协议。不能补造隐藏推理、原本没有取得的 logits 或教师身份。

统一经验契约至少绑定 observation_before、action、tool_receipt、observation_after、outcome、cost_scope、parent_version、exposure 与授权来源。将教师示范、学生影子预测、学生实际执行、authored/reference 和失败/未知事件明确区分；只有真实执行才产生学生状态转换，只有语义验收才产生业务成功。

初期可以在同一精确底座下为项目/任务家族训练 LoRA 或小 head。训练只写候选快照，服务始终读不可变的已采用快照；请求开始后不得混入正在更新的权重。候选经 B 的固定规则选择后再在新 C 使用，胜出或 NoUpdate 都形成可核对的选择原件。采用由原 owner 以新 epoch 提交，过期 parent 的候选不得覆盖当前版本。

这条路线有文献先例：Agent Lightning 研究 Agent 执行与训练解耦、统一 transition 接口及 credit assignment；AgentTuning 研究高质量交互轨迹与一般指令混合训练。它们支持工程与算法方向，不证明 Hepta 已实现相同效果，也不保证持续在线模仿带来单调收益。[P7]、[P8]

要补原 E2，应在训练 A 内让当前学生实际访问状态，由教师/用户对其偏离状态纠正，然后聚合并更新。冻结的示范重放与固定旧 parent 经验不能替代这一过程。DAgger 的相关启发正是 student-visited states；评价 B/C 的答案和终局反馈则必须遵循固定的使用边界，不能事后回灌训练。[P1]

## 8. Cell 之间如何建立高效 Circuit

先把连接的兼容性和成本做好，再研究自组织。建议分两类组合：

1. **同底座组合。**固定 base、tokenizer、模块、表示和数值协议，共享冻结主干、使用各自 adapter/head；默认 top-1，需要组合才启用预注册 top-k。adapter 合并要在相同权重坐标下定义有效增量 ΔW=BA，分别平均 A/B 不等于平均 BA；符号与任务冲突必须独立评估。[P3]
2. **异构底座组合。**先交换可检查的结构化信息、候选动作、证据和工具结果，接收方自行编码。不同模型的 hidden state、KV cache、tokenizer logits 不因维度相同而兼容。latent bridge 应成为独立训练组件，固定两端版本、配对数据、目标和成本。

现有 Circuit binding 要求 Cell bundle 与整图 bundle 一致。支持异构 Cell 应新增 versioned node ABI、每节点 manifest 和显式转换契约，不能直接删掉旧一致性检查。节点契约应包含输入/输出 schema、参数/状态版本、effect 能力、预算、恢复规则、表示版本及 artifact 身份。

先在固定边集合上学习稀疏路由；输入只用动作前可见特征。路由不能偷看参考答案或终局 verifier 结果。边要有类型、最大消息尺寸、等待预算、循环次数上限与失败传播规则；跨设备优先在较粗任务边界通信，频繁 token 级数值交互留在兼容的可测设备域。Switch 的稀疏专家方法可启发容量/负载均衡，但其兼容内部专家假设不能直接移植为异构 Agent 网络保证。[P4]

连接训练目标可使用事先定义的质量、成本与遗忘约束，但分别报告原始指标，不用未校准的单个 reward 掩盖成本。E4 至少比较单模型、固定流程、随机稀疏图和学习稀疏图；固定活动参数、推理调用、训练/搜索预算与 verifier 机会，无法同时匹配的量明确分列。

逐边/逐 Cell 消融必须真实执行：同一输入与其他版本固定，比较完整图和移除该组件后的业务差异，同时报告成本差异；即时移除和重训练后适应分别报告。打乱消息、打乱边和无连接并行是有用对照。若多 Cell 的成功并集不超过最佳单 Cell，当前池连一个事后覆盖上界都没有显示额外空间；即使超过，也只是路由研究机会，实际路由仍可能失败。

只有某些连接在未见任务上稳定提供净增益，才有依据固化常用子图。split/merge、新增 Cell、淘汰和组织层级应各自形成版本化候选、预算和独立选择事件；不能把拓扑越来越复杂当作能力证据。

## 9. HIA 有用，但职责应明确

HIA 适合承载版本、状态、控制流、effect 引用、预算、pending/readback 与恢复契约。已有桥接能够把一次真实 Cell 调用与 native continuation 绑定；保留结果存在时读取原结果，缺失时保持 unknown，不能静默重新推理冒充恢复。

建议让 HIA 作为控制面，让模型 provider 承担张量计算与设备资源管理。大张量用带生命周期的 handle/artifact 传递，声明 shape、dtype、layout、device、owner、checksum 和释放条件；避免默认逐层 activation JSON 化。跨进程/设备复制量、同步等待和网络字节须实测。

HIA 不提供教师真实性、任务效用或学习泛化的判据，也不自动把离散工具调用变成可微神经连接。语言可以让这些执行契约更清楚、更可复核；成功学习仍依赖数据、模型、优化目标、信用分配和独立评价。现有 continuation 实测不证明跨设备可微训练图已完成。

## 10. 去中心化、用户增长与 PoUW

去中心化应分开讨论数据所在地、训练节点、参数协调、模型所有权、评价者与奖励结算。先让经验留在用户侧、能力单元局部训练、候选以内容身份传播，再测试共享模型的联邦/低通信方案。FedAvg 需要共同参数坐标，原方法有协调服务器；DiLoCo 在兼容模型副本之间低频同步；二者都不意味着任意异构大模型可以直接合并。[P2]、[P6]

E5 的固定总预算回答更多来源本身是否有价值；固定每来源预算回答来源和计算同时增加后的系统表现。1/4/16/64 是设置，不是增长预测。必须同时记录原始任务、去重 lineage、实际执行经验、成功经验、真实用户/项目、采用、成本和遗忘；换 ID、重放和 seed 不增加独立来源。当前只有声明来源组，没有满足原 E5 的认证用户群，因此不能画用户增长收益曲线。

PoUW 至少要求真实性、有用性和成本三项同时成立：实际做过受约束工作；相对可部署强控制在独立任务上有增益；全部投入没有被隐藏。哈希/签名可证明承诺和来源链的一部分，不能单独证明语义效用、数据代表性或反事实贡献。

奖励规则应事先定义任务效用、重复经验、成本归属、评价独立性和争议处理。训练步数、GPU 忙碌、tokens 或提交数量只能是工作量指标；不同资源单位不能直接相加成奖励。Cell/边的移除差异也依赖上下游和替代策略，贡献不一定可加，不应把路由概率当作公平奖励份额。

## 11. 从能力网络到 foundation model 的必要条件

可路由专家网络、同底座多 adapter、统一蒸馏模型是三个不同终点。前两个能够成为有用的产品形态；统一接口本身不构成新 foundation model。统一学生需要额外的表示学习或输出监督、足够覆盖的数据、容量、一般能力保留和跨领域/未来任务评估。

蒸馏只能在 transfer data 覆盖的范围内教学生；参数合并可能产生干扰；多教师可能共享错误。现存模型所有长处的无损并集不是可以从这些方法得到的保证。[P3]、[P5] 更可检验的目标是：若干清楚定义的任务家族上，系统在独立任务中接近或超过最佳可部署控制，并且代价、延迟和遗忘可接受。

下一轮应围绕真正缺失的证据推进：取得新真实任务及授权来源，按用户/项目/原事件时间和 lineage 先冻结 A/B/C；先验证单个学生的来源外收益，再验证更新学生的恢复；只有出现专家互补后再做等预算 Circuit 与逐边消融；最后才有意义增加来源规模和把收益纳入奖励。当前没有通过的 gate 保持未通过，不以重复旧任务补齐独立样本。

## 12. 可复核交付与使用范围

源码、实际运行、失败原件、训练/生成/业务回执、候选身份、修订前后诊断、独立复核、恢复索引与本报告均随分段 Draft PR 提供。大文件保留分块与无损恢复关系；每个实际 Git 对象保持大小限制，文本分段符合审查上限。发布本身不增加实验结果、不合并代码、不采用生产候选。

实验代码维护检查、数值工程测试和业务评估分别报告。局部测试通过不代表整个仓库 CI 全绿；历史失败和仍未闭合的全局检查不在本报告中豁免。最终远端 PR/commit 与 CI 的读回状态以发布收据为准。

### 固定引用

[source-audit]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6b8d8c44a183c48e761aff76e0570ab278b4f7da/qualification/cell-experiments-v3-20261116/SOURCE_AUDIT_V3.md
[architecture]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6b8d8c44a183c48e761aff76e0570ab278b4f7da/qualification/cell-experiments-v3-20261116/operations/research-static-architecture-and-control/architecture/ARCHITECTURE_RESEARCH.md
[interpretation]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6b8d8c44a183c48e761aff76e0570ab278b4f7da/qualification/cell-experiments-v3-20261116/operations/research-static-architecture-and-control/interpretation/REVIEW.md
[P1]: https://arxiv.org/abs/1011.0686
[P2]: https://arxiv.org/abs/2311.08105
[P3]: https://arxiv.org/abs/2306.01708
[P4]: https://arxiv.org/abs/2101.03961
[P5]: https://arxiv.org/abs/1503.02531
[P6]: https://arxiv.org/abs/1602.05629
[P7]: https://arxiv.org/abs/2508.03680
[P8]: https://arxiv.org/abs/2310.12823
