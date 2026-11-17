# E1/E2 静态解释边界复核

## 范围与结论

本文件仅依据四个冻结研究模块、冻结研究协议和研究 01 的已封存复核，供最终结果报告使用。未读取活动研究 02 的输出，未运行模型、tokenizer、训练、tests 或 verifier，未读取新 C，未修改源码或设计。后续编号运行的真实部署身份、完成情况和数值须由封存原件另行核对。

**现有设计匹配的是四个拟训练臂的更新规则和训练张量形状预算，以及六臂评估的任务与最大尝试/生成预算。它没有建立六臂端到端等成本、等实际监督 token 或等真实 GPU 计算的比较。E2 使用固定 parent03 的旧受控经验；cold 检验新进程重新加载同一推理候选，不检验训练中断后的继续训练。**〔CT·TRAINING；TR·fit_steps；EX·collect/evaluate；PR·Exact budgets and numeric policy〕

## 1. E1：哪些匹配，哪些必须分别报告

| 维度 | 冻结设计实际约束 | 最终报告边界 |
| --- | --- | --- |
| 四个 SFT 臂的底座与参数策略 | 同一 parent manifest、LoRA rank 4、q/v 目标、相同优化器/学习率/种子/梯度裁剪/BF16/检查点设置 | 核对各臂 TRAINING 的实际参数量、参数身份与完成状态；不能用配置替代完成证据 |
| 更新数量与张量形状 | 每个完整 fit 64 步，每步 batch 1，1536 padded positions | 每个完整 fit 是 98,304 padded positions；四个均完成才是 393,216。失败分支只报已保存步骤及未知范围 |
| 原始 A 任务分配 | 六个固定任务按 step % 6 调度，再按各任务实际 turn 数轮转 | 完整 64 步的任务组更新为 11/11/11/11/10/10；各 turn 获得的更新量和监督信息仍可不同 |
| 实际监督与输入量 | 每步保存 input_tokens、supervised_tokens、turn、loss；完整 fit 汇总实际计数 | 四臂不保证等监督 token、等非 padding 输入或等目标复杂度；保留实际数值和 record_turn_updates |
| 六臂评估 | 同样六个 A、三个已暴露 B；最多两次尝试；相同冻结生成设置，单次最多 384 新 token、4096 输入 token | 实际调用次数、输入/输出 token、纠错反馈长度、输出触顶可不同；retrieval 的实际展示上下文也不同 |
| 端到端工作量 | parent/retrieval 不进行 SFT；correction 有采集/重验；controlled 使用已有 parent03 经验 | 六臂不等训练成本，也不等采集、推理或验证总成本；不能称为端到端等成本胜出 |

依据：CT 的 TRAINING、reference_admission 和 verify_model；TR 的 fit_steps、train；EX 的 collect、evaluate；PR 的 Six arms and four fits、Exact budgets and numeric policy、Diagnostics and universal unqualified scope。表中的 98,304 与任务组分配是冻结循环的算术结果，均以完整执行为条件。

最终建议每臂并列呈现：完成状态/实际步骤、input_tokens_consumed、supervised_tokens、padded positions、encoded_supervised_turns、record_turn_updates、参数变化、A/B 的 first-attempt 与 final-attempt 原始成功数、实际生成/验证调用及 token、费用 scope、cold 身份和结果。不存在的字段保持 unavailable；部分日志只能提供已测小计。〔TR·fit_steps/train；EX·evaluate；RU·raw_ledger/fit_counts〕

loss 降低、参数变化和达到 64 步证明不同层面的执行事实；业务能力仍须由真实原始实现/错误输出对照结果支持。各臂训练目标与 mask 不同，不能直接用较低训练 loss 排名能力。即使轨迹臂在旧 B 上更好，也应写成“该固定更新预算下的开发条件比较”；不同监督 token、turn 和上下文仍限制对轨迹本身净因果效应的归因。事后除以监督 token 不会把既有实验变成等 token 的因果实验。〔TR·fit_steps/train；EX·evaluate；PR·Question and limits/Diagnostics and universal unqualified scope〕

## 2. 成本列必须写明 scope

- **训练 receipt** 包含验证、模型加载、编码、训练和保存，其 wall 不是纯 optimizer 时间；self CPU 与完成 verifier-child CPU 分列。峰值 allocated/reserved bytes 是显存峰值，不是 GPU 活跃秒、FLOPs、能耗或金额。〔TR·train 的 cost〕
- **evaluation cost** 在初始设备检查之后、Predictor 加载之前开始，包含该次加载/关闭及完成 verifier 子进程；**panel cost** 从该 panel 开始，排除模型加载和关闭，仍包括该 panel 实际生成与验证工作。〔EX·evaluate〕
- coordinator、worker、training、evaluation、panel 范围相互包含。最终报告选清楚比较范围，保留其余作为明细，不把这些 wall/CPU 重复相加；也不把独立 scope 的峰值相加成实际内存占用。〔PR·Measurement and partial failures；TR·train；EX·evaluate〕
- 六次新 shadow 生成是 collector 的新增工作，controlled 原始调用是已保存 parent03 成本。完整设计另有 12 次 correction reference 与 24 次 fit reference。复用可节省本次新增调用，但既有生成与人工 authored-target 成本不因此成为零；当前没有完整人工/能耗/货币计量。共享采集成本若要分摊，须明确分摊口径，不能重复分摊或隐去。〔EX·collect；PR·Six arms and four fits/Measurement and partial failures〕
- 原 ledger 的全局 null、global_totals_unknown、errors/gaps 与已测 subtotal 均须保留。研究 01 的失败和成本不能被后续编号结果替代；重复同一任务不增加独立 N。〔RU·raw_ledger；R01·费用〕

## 3. E2：controlled 为何不是更新学生的 on-policy 经验

EX.collect 先用固定 parent 做六次新 shadow 预测，再直接读取 context["gate"]["controlled_observations"]，写入 CONTROLLED_REUSE；协议将其来源固定为完整 parent03。四个 cohort 与 plan 都在任何 fit 之前冻结，之后每臂训练一次，代码没有“更新学生—再采样学生执行—再纠正—再更新”的迭代。〔EX·collect；PR·Six arms and four fits〕

controlled 的“受控”指旧 parent 当时按上限执行补丁、接受真实环境反馈；它不意味着这批轨迹来自任一更新后 adapter 的当前策略。研究 01 已核对它们确为六个 A 任务的 12 个旧步骤，复用本身新增生成/验证调用为 0；此历史事实不能充当活动研究 02 的执行完成证据。〔R01·Shadow、controlled 复用与 E1/E2 解释〕

训练标签仍为已验证 authored correction。学生 action 的 trainable=False，学生输出/反馈作为上下文而非直接成功标签；“reference 通过”不能归给学生。〔EX·corrected；CT·reference_admission；PR·New admission and artifact contract〕

shadow 与 controlled 同时改变是否执行、实际尝试数、历史/反馈、上下文长度及经验采集时点。若它们出现差异，只能报告这两个冻结条件的差异；它不能单独回答“更新学生的自身经验是否必要”，也不能直接证明在线恢复能力。要回答原 E2 的强问题仍缺少更新学生自身执行的独立证据；本审查不改变现有实验。〔PR·Six arms and four fits/Diagnostics and universal unqualified scope〕

## 4. Cold：能证明到哪一层

| 可以在实际原件完整时支持 | 当前 cold 不能支持 |
| --- | --- |
| 另一实际 PID 加载同一 manifest 与完整 adapter 文件身份，维持同一 base/runtime/generation 绑定 | 新用户、新机器、异构节点或网络分区下的恢复 |
| 同一候选在新进程中完成重复旧 A/B 推理；可逐任务比较 first/final 结果是否保持 | 自动断言输出 bitwise 一致；源码明确未认证跨主机位级确定性 |
| 文件保存与推理重新加载路径实际可用 | optimizer/RNG/数据游标/中断步骤恢复以及继续训练数值一致 |
| 保留 primary 成功、cold 失败或业务退化的分别观测 | 失败 cold 用别的候选替换，或把重复运行计为新独立样本/真实采用 |

依据：TR.Predictor 通过 PeftModel.from_pretrained(is_trainable=False) 加载 adapter 并进入 eval；EX.run_job 绑定 primary receipt、manifest SHA 与 PID，要求 cold 使用不同 PID；CT.verify_model 核对 base/adapter inventory；PR.Measurement and partial failures。

optimizer.pt 在训练后保存并以路径/大小/SHA 写入训练 receipt，但 cold Predictor 没有加载 optimizer、继续 step 或恢复 RNG。存在 optimizer 文件不等于验证了训练恢复。primary 的训练后评估本身也通过保存的 manifest 重新构建 Predictor；cold 增加的是新进程边界。〔TR·train/Predictor；EX·run_job/evaluate〕

“cold 完成”“同候选身份核对通过”“业务结果保持”应分别报告。业务退化是观测结果，不能因为身份一致而遮蔽；cold 只复测同一旧面板，不能替代 E6 的独立 B 选择、新 C 使用和采用。〔EX·evaluate/run_job；RU·cold_comparison；PR·Measurement and partial failures/Diagnostics and universal unqualified scope〕

## 5. 最终报告必须明确的归因与分母

1. **A 是训练目标所在面板。**A 的改善属于已训练任务上的绝对表现；不能据此称为未见任务泛化。B 已暴露且协议是在观察 parent03 失败后新建的探索，改善最多先支持该旧开发面板的描述性结论。〔PR·Question and limits〕
2. **A 原成功集合为空。**完整 parent03 为 A=0/6；“原成功任务保留率”和按该集合定义的遗忘率分母为 0，应为 null，而不是 0% 或 100%。训练后绝对 A 成功数/6 是另一项可测指标。相对提升率以零基线作分母也未定义；有完整结果时可报原始计数与百分点差。〔PR·Status and provenance；R01·Shadow、controlled 复用与 E1/E2 解释〕
3. **业务失败与未测量不同。**真实完整执行后 verifier 判断失败可以记失败；资源拒绝、未进入评估、缺失或损坏回执应标 unavailable/unknown，不能补成 0 成功率。零成功时的“每次成功成本”也不能填 0，应并列报告总成本与成功数并标分母问题。〔EX·evaluate；RU·raw_ledger；R01·结论〕
4. **first 与 final 分开。**两次尝试中的最终成功不能归为首次成功；cold、种子、重放、子分支和 reference 重验均不增加独立样本。完整 reference 业务通过是标签有效性，不是模型任务成功。〔PR·Measurement and partial failures；R01·结论〕
5. **相同数据上观察到的“最佳臂”不是独立选择或采用。**不替换失败臂，不用只保留成功臂的平均数代表六臂；固定槽位缺失时 union 保持 unavailable，成功并集也不代表实际路由或 Circuit 收益。〔PR·Diagnostics and universal unqualified scope〕
6. **资格固定。**无论任务分数是否改善，scientific_confirmation_qualified、native_cell_adoption、proof_of_useful_work_eligible、circuit_qualified、independent_selection 和 new_C 均为 false；candidate_selected=null。E3–E6 的缺失证据不由本研究补足。〔CT·SCOPE；PR·Diagnostics and universal unqualified scope〕

## 引用身份与核验

以下六个文件于本次静态审查实际完整读取，路径均位于 /Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a。正文引用的函数、配置键与节标题均已在这些确切字节中核对；未把活动运行的状态推断为结果。

| 标记 | 相对路径 | SHA-256 |
| --- | --- | --- |
| CT | research-sft-v1-source-working/research_sft_contract_v1.py | 2ae7c2496ee58ce71cbda7a6d245e65550a76104cbc1359aca06d005f6b16f2c |
| TR | research-sft-v1-source-working/research_sft_train_v1.py | a95ccfde26ebb3f32ef1e3fb2df3f1b4d35ab27b4ae42edf8858dc315d2f9972 |
| EX | research-sft-v1-source-working/research_sft_execution_v1.py | 704e7a7e157412d9ce8a7523c31ed635269ead41d40f1720c591dccc4d67f2cd |
| RU | research-sft-v1-source-working/run_research_sft_v1.py | 0fba8d8800ba3012a55055d7a84c4bfa156d0f96c64e0bd488211f188cbe256c |
| PR | research-sft-v1-source-working/RESEARCH_PROTOCOL_V1.md | 1f3171699624a18f705728f495d81c51c4909d2e7c3a6950df14335b31cdc0ee |
| R01 | research-results-review-01/RESULT_REVIEW_01.md | c4e404ab6b791292b479cfc4b09ac0932af27e605bf7bc3a5e432e4ce9d12685 |

本次仅新建本 REVIEW.md，不创建实验结果或修改冻结规则。后续实际结果复核须以各编号的完整封存原件为准。
