# 研究 02 封存结果独立复核

## 结论与范围

研究 02 确实完成了四个 64 步 LoRA fit，保存并重新加载了四份不同的 adapter。六臂在旧 A 上的首次及最终成功数为 **parent 0/6、retrieval 0/6、final_answer 5/6、trajectory 4/6、shadow_correction 0/6、controlled_correction 1/6**；所有臂在旧 B 上均为 **0/3**。全部成功出现在第一尝试，第二尝试没有新增业务成功。[R1–R4]

这些结果支持“本次监督拟合改变了权重，并使部分训练任务的生成结果通过业务检查”。它们没有建立未见来源、未来任务、更多用户、多教师互补、Circuit、采用闭环或新 foundation model 的收益。这是失败后另行冻结的研究协议，科学确认、原生采用、PoUW、Circuit、new_C 资格继续为 false，candidate_selected=null；不修改原生资格门槛。[R1,R8]

本复核只读取已封存 Mac 原件，未启动模型、tokenizer、训练、测试或业务 verifier，未读取新 C，未修改任何研究源或输出。最终只读分析实际 exit 0，核对 1,248 个选定原件、完成 4,416 项检查。原诊断拒绝与两处 cold 输入差异仍被保留；“检查通过”不是所有观测逐位相同的声明。[R2,R7,R11]

## 1. 封存身份与核验方法

- 原封包 29,880,237 B、1,687 个成员；SHA256 a852fa6d9ce8317edd15bd7e6edeb3ee12e97e3d27c4ba179e5fe2c34846ad61。TRANSFER_MANIFEST SHA 4a6f4fae9a04d7afe86476d36fb55767388a15f4a3d98dfa2dcb1795163b3ec9，MEMBERS SHA 780f469367e460a917f66ecad5aee056b6deac9a05667e12ad3da59e2de2bc77。[R0]
- FREEZE SHA 50a6ad4c3e8088100cc84a047f0556b92294eb3e44dc644e62e2976137c2770a；RESULT SHA a47df3bcc247ab0b28e8d6299148a7b65a4a6719a4ab1150830613631cfa3fbe。四个运行模块、helper04 实际字节及 119 个源文件的冻结成员清单与记录一致。[R0–R2]
- 13 个计划 child 均有真实 exit 0、stdout/stderr SHA 和停止观测；owned wrapper 的真实 subprocess.Popen.wait=0 与原 child 身份、INTENT、STARTED、日志相连。最终 controller 也是 exit 0、output_complete=true。中途 lost/target_reboot 报告不能据此改写为真实训练主机重启；历史差异由原观测保留。[R6]
- 每次学生验证从 request、output、step、semantic receipt 追至原始/错误输出控制观察，再与 EVALUATION 核对。分析仅 AST 加载冻结源码中的五个纯回执读取/反馈构造函数，没有执行原 verifier。token 数从原输出和逐步日志累计，未重跑 tokenizer；optimizer.pt 只验大小与 SHA，未反序列化。[R2,R4]
- 哈希与摘要绑定已有字节，不能独立认证执行方诚实、第三方 validator、独立用户或未来时间切分。本报告不把同一执行方的完整回执升级为去中心化对手环境中的 PoUW 证明。[R2,R8]

## 2. 四个 fit 的实际训练量和参数

| 臂 | 步数 | 监督 turn 数 | 非 padding 输入 token | 监督 token | padding 后训练位置 | 训练段 wall 秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| final_answer | 64 | 6 | 23,813 | 5,390 | 98,304 | 106.163 |
| trajectory | 64 | 9 | 25,882 | 4,884 | 98,304 | 106.449 |
| shadow_correction | 64 | 6 | 44,011 | 5,390 | 98,304 | 100.937 |
| controlled_correction | 64 | 6 | 74,643 | 5,390 | 98,304 | 99.770 |

各 STEPS.jsonl 都有顺序 1–64 的完成记录。按原六记录和 turn 轮转重算后，task/record/turn、有限 loss/梯度范数、loss 列表及所有输入/监督/padding 汇总一致。合计 256 步、168,349 非 padding 输入 token、21,054 监督 token、393,216 padding 后位置。训练 wall 包含 reference、加载、编码、训练和保存，不是纯 optimizer 时间。[R2,R3]

四个保存 adapter 各有 112 个 F32 tensor、544,768 个有限参数、文件 2,193,720 B，q/v、rank=4 配置一致。按原参数名、次序、dtype/shape canonical 编码重建原始 tensor 字节哈希，四个 parameter_after 都精确命中各自 TRAINING；after 彼此不同，每份的 200,704 个 B 参数均非零。四份 optimizer 文件各 4,451,615 B，SHA/大小与训练回执一致。[R2,R3]

共同记录的 parameter_before 为 bd8d0e3cde37c3a6694bfc02b6a7b49a826e74f85d44f8ce9773f3d3bf9d02df。未保存独立初始化 tensor 快照，因此 before 仅能绑定原记录和冻结初始化实现，不能说重新测得初始张量。after 则直接由保存字节重建。全部 model/adapter/optimizer 完整身份见机器 readout.training。[R2,R3]

E1 匹配了底座、生成设置、可训练参数规模、rank、优化器、seed、64 步、1536 长度和同六个 A 的任务来源。它没有匹配监督 token、有效上下文、实际 FLOPs 或端到端费用：trajectory 监督量比 final_answer 少约 9.39%；controlled 非 padding 输入约是 final_answer 的 3.13 倍；selected-token loss 的输出头工作量也随监督位置变化。5/6 对 4/6 不能单独归因为“最终答案监督普遍优于完整轨迹”。[R1–R3,R8]

## 3. 学生业务结果和执行分类

| 臂 | A 首次 | A 最终 | B 首次 | B 最终 | primary 验证调用 | 实际进入 fixture |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| parent | 0/6 | 0/6 | 0/3 | 0/3 | 18 | 0 |
| retrieval | 0/6 | 0/6 | 0/3 | 0/3 | 18 | 0 |
| final_answer | 5/6 | 5/6 | 0/3 | 0/3 | 13 | 8 |
| trajectory | 4/6 | 4/6 | 0/3 | 0/3 | 14 | 9 |
| shadow_correction | 0/6 | 0/6 | 0/3 | 0/3 | 18 | 12 |
| controlled_correction | 1/6 | 1/6 | 0/3 | 0/3 | 17 | 7 |

primary 的 **98 次验证调用**中，**62 次 invalid_test_patch** 在业务执行前失败，**26 次业务执行失败，10 次业务执行通过**。含 cold 重复后，**196 次验证调用 = 124 次准入拒绝 + 52 次业务失败 + 20 次业务通过**；实际进入业务 fixture 是 **72 次**，不是 196 次。parent/retrieval primary 的 36 次验证全部在补丁准入阶段失败。[R2,R4]

| A 任务 | final_answer | trajectory | shadow_correction | controlled_correction |
| --- | --- | --- | --- | --- |
| A-counter | 首次成功 | 首次成功 | 失败 | 首次成功 |
| A-mse | 首次成功 | 失败 | 失败 | 失败 |
| A-readout-score | 首次成功 | 首次成功 | 失败 | 失败 |
| A-clipped-metrics | 首次成功 | 首次成功 | 失败 | 失败 |
| A-pair-map | 首次成功 | 首次成功 | 失败 | 失败 |
| A-colon-repair | 失败 | 失败 | 失败 | 失败 |

B-stable-frame、B-json-format、B-wire-digest 在全部臂和 cold 都失败。所有成功绑定真实生成答案、任务、输入、verifier 源与参数，并且原始测试通过、错误输出控制全被拒绝；它们不是“语法通过”代替业务通过。primary 10 次成功中 8 次生成答案字节与 authored A target 完全相同，另 2 次是通过同一业务检查的生成变体。[R2,R4]

这些任务仍是函数合同的 test-completion fixture；成功不声称 full_repository_integration 或 independent_user_evidence。九个 task/source_id 来自同一 hepta-private-ci 项目的九个模块，不能解释为九位用户或九个独立项目。A 六个任务既参与训练又被评估，B 三个任务也是已暴露开发集。[R2,R4,R8]

54 个 primary 臂×任务观测中有 44 个首次失败并重试，第二次新增成功为 0；这不是 44 个独立样本。原 parent03 A 成功数为 0，因此按“原成功任务”计算的 retention/forgetting 比率是 null，不能写成完全保持或零遗忘。[R2,R9]

本批 A 的成功集合相互嵌套：trajectory 四项都在 final_answer 五项内，controlled 的一项也在其中。固定三槽的纯描述性成功集合并集仍只有五项，不增加最佳单臂覆盖。这不是执行过 Circuit、路由或逐边/逐 Cell 消融的结果。[R2,R4]

## 4. E2 与 36 次 authored reference 的范围

collector 有 6 次新 shadow 预测，1727 输入/1764 输出 token，未执行补丁，因此没有学生业务成功标签。controlled cohort 精确复用 parent03 六个 A、12 个旧实际尝试；旧 request/output/step 与 readiness 附加的 task_digest 全部相符。复用新增模型/验证调用均为 0，旧 parent03 成本仍单列。[R2,R5,R9]

两类 correction 的学生 action 和环境 observation 都为 trainable=false，监督目标是已验证的 curator authored A correction。它们不是外部教师新示范；controlled 不是更新后的学生重新采集的 on-policy 经验。1/6 对 0/6 不能证明学生自身在线经验的必要性，也没有显示第二次反馈重试的恢复优势。[R2,R5,R8]

36 次 authored reference 包括 collector 的 12 次和四个 fit 各 6 次、合计 24 次。全部独立 REQUEST、REFERENCE、MEASUREMENT 与目标/源码身份核对成功，36 次业务通过，合计 54 次完成的原始 subject 调用及 84 条控制观察。REFERENCE_RECHECKS 仅是这些回执的汇总，没有再次计数。这证明目标可执行，不是 36 次学生成功或 36 个新经验样本。[R2,R5]

## 5. Cold：同候选和输出保持，存在两处输入历史差异

六臂 cold 都使用 primary 同一 manifest 路径、SHA、model digest，不同 worker PID；四个 adapter 原字节也已核对。所有 paired 生成答案、output token IDs、output token 数、首次/最终业务结果一致，无新训练或候选替换。[R2,R4]

不能声称所有请求及费用逐位一致。final_answer 和 trajectory 的 B-json-format 第二尝试收到前次 parser 反馈，反馈中带有 Python ast.Name 对象地址；不同进程地址导致不同 messages SHA 和输入长度：

| 臂 | primary 第二次 input_tokens | cold 第二次 input_tokens |
| --- | ---: | ---: |
| final_answer | 408 | 407 |
| trajectory | 399 | 398 |

原件为 workers/{final_answer,trajectory}-{primary,cold}/evaluation/B_exposed/1/{step-0,request-1,output-1}.json。完整地址、反馈、SHA 在机器 readout 的 cold.actual_request_differences 和 MISMATCH_INSPECTION_RECEIPT_02.json 中。另四臂未观察到这两个字段的差异。没有清洗原反馈或补跑实验。[R2,R4,R7]

cold 支持“同环境新进程加载同一保存候选，在旧任务获得相同输出/分数”。它未恢复 optimizer/RNG 后继续训练，未证明跨主机/版本逐位复现、崩溃未提交状态恢复、新 C 使用或真实采用。保存 optimizer 文件并验 SHA 不等于验证训练续接。[R2,R3,R8]

## 6. 计数、成本、未知值与 Run01 分列

| 本次新工作 | 模型调用 | 输入 token | 输出 token | 学生验证调用 |
| --- | ---: | ---: | ---: | ---: |
| shadow collection | 6 | 1,727 | 1,764 | 0 |
| 六臂 primary | 98 | 45,246 | 14,566 | 98 |
| 六臂 cold | 98 | 45,244 | 14,566 | 98 |
| 合计 | 202 | 92,217 | 30,896 | 196 |

另外有 36 次 reference 和 256 个训练更新。202 次生成低于 222 上限，30,896 输出 token 低于 85,248；256 步、393,216 padding 后位置、36 次 reference 恰好达到各自预算。旧 controlled 12 次调用没有重复加入，cold 也不增加独立样本数。[R1,R2]

| primary 评估 | wall 秒，含加载/关闭 | 输入 token | 输出 token | output cap 命中 |
| --- | ---: | ---: | ---: | ---: |
| parent | 325.350 | 8,666 | 5,355 | 9 |
| retrieval | 268.856 | 14,443 | 4,392 | 8 |
| final_answer | 121.284 | 4,457 | 1,271 | 0 |
| trajectory | 104.672 | 4,833 | 1,122 | 0 |
| shadow_correction | 121.683 | 6,636 | 1,324 | 0 |
| controlled_correction | 102.882 | 6,211 | 1,102 | 0 |

不同输出长度、反馈重试、格式拒绝、上下文和加载会改变时间与 token。baseline 经常达到输出上限、监督臂输出更短；不能从这些时间分离“学会输出格式”“记住训练答案”“广义推理改进”各自的贡献，也不能宣称实际成本匹配。[R2,R4]

**RESULT retained ledger** 将本次保存计数标为完整：202 生成、92217 输入、30896 输出、196 学生验证、36 reference、256 步，global_totals_unknown=false。逐文件覆盖独立核对一致，无同范围 request/output/step/reference 漏算、多算，参考汇总未重复计费。[R1,R2]

**原 DIAGNOSTIC ledger** 保留相同实测小计，但全局量为 null、global_totals_unknown=true、failed_attempt_measurement_complete=false。不能将其保守调用口径悄悄改写成 RESULT 标记。两个原 ledger 都完整保留，实测小计相符。[R2,R7]

**全系统成本仍未知。** Run02 coordinator wall=2720.283446 秒、own CPU=7.448896 秒、completed child CPU=2772.224186 秒；GPU active time、能耗、货币费用为 null，complete=false。generation 子段 wall 合计 1919.328989 秒、reference 子段 7.169666 秒；训练、评估、panel、child 与 coordinator 有嵌套，不能相加为总成本。下载/安装、发布、其他进程与未计尾部不能推断为零。[R1,R2]

每份 EVALUATION 的 completed_original_calls 总量仍为 null，保留已有小计和缺失尝试；subject_call_attempt_count 为 null。生成账本完整不等于所有 primitive subject 尝试次数或全系统资源测量完整，不能将异常/未观察到的调用归零。[R2,R4]

**Run01 单列保留：** 4 次训练入口、0 步、0 fit；6 次 shadow 保存 1727/1764 token，36 次 reference；其全局调用总量仍未知。coordinator wall=246.603093 秒、own CPU=2.591109 秒、child CPU=244.295266 秒。不能用 Run02 成功擦除这次资源失败或计成新样本。旧 parent03 wall=376.498398 秒及 CPU/验证成本在 RESULT 单独绑定，不计为本次新调用，也不视为免费。[R2,R9,R10]

## 7. 原诊断拒绝与分析自身修正

原 DIAGNOSTIC SHA 662f575d3f01705fb13cb6e168ad5d7069a8ddcc81e484f0c515b63afd65236b。fixed slots、baselines、shadow 均报 ValueError('evaluation task order or coverage differs')，顶层 binding_errors=[]。原文件和 null/UNAVAILABLE 不变。[R7]

本复核依照 worker 实际读入的冻结 INPUTS.json 顺序 A_retention、B_exposed 逐条核对全部任务、原始步骤、模型、执行结果，均匹配。消费者顺序接口由另一独立审计处理；本报告未替换或声称重跑原诊断，也不以其 UNAVAILABLE 推断模型/fit 不存在。[R2,R4,R7]

只读分析自己的历史也全部保留。第一次因 invalid_test_patch 缺少可选 scope 字段而 KeyError/exit 1；第二次实际 exit 2，留下首份完整 readout：六项是 raw parent RESULT 与 readiness 聚合多出的 task_digest 字段；另两项更严格 cold 比较捕获上文真实输入差异。最终程序验证附加 task_digest，并将同候选/输出与输入历史分别记录，真实输入差异仍为 false 和明细，没有修改研究准入或输出。[R7,R11]

最终 review_closed_02_v2.py 406 行，SHA 43b72f35c3c38bbc3df0b677c66bb0df95bcc994fc0adc445248ffd964190615；review_support_02.py 286 行，SHA fc8a0b1912ebb2f8e724d6a5085ac30cf3a8438590bc097934d498d644a42ad2。旧程序、失败终态、首份 readout、schema inspection 和最终 stdout 均保存，没有模型、测试或 reference 重跑。[R11]

## 引用与完整机器证据

全部路径以 /Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a 为根。R2 的 file_read_identities 提供逐文件完整 SHA/大小；花括号表示本次逐项核对的固定成员，不是待运行任务。

- [R0] research-final-export-02/{TRANSFER_MANIFEST.json,MEMBERS.jsonl,qwen-research-sft.zip}。
- [R1] research-final-evidence-02/research-sft-02/{FREEZE,INPUTS,RESULT}.json。
- [R2] research-results-review-02/CLOSED_RESULT_REVIEW_02_FINAL.json，586375 B，SHA 13a8d77f1221e37524352ec50bf4f95f0c15aa1d6b98ab9678a82fcd229b8450；SUMMARY_READOUT_02.json，39884 B，SHA 9ae37f954045a5d8a0ef8e105d20186d9eb977ebbb4c245f2fa079285c17628e。
- [R3] research-final-evidence-02/research-sft-02/workers/{arm}-primary/research-model/{STARTED.json,STEPS.jsonl,TRAINING.json,manifest.json,optimizer.pt,adapter/*}。
- [R4] 同一 workers/{arm}-{primary,cold} 的 RESULT.json、MODEL_IDENTITY.json、evaluation/EVALUATION.json、MODEL_LOADED.json 和 evaluation/{A_retention,B_exposed}/{index} 原始步骤。
- [R5] 同一 workers/corrections-collect 的 PLANS.json、CONTROLLED_REUSE.json、四份 records/plan、shadow、corrections 子目录；四个 research-model/references/{0..5} 和 REFERENCE_RECHECKS.json。
- [R6] research-final-evidence-02/operations/{RESEARCH_TERMINAL_INDEX_02,RESEARCH_TARGET_CLOSURE_READBACK_02,RESEARCH_ACTUAL_TERMINAL_02,RESEARCH_POSTRUN_TERMINAL_02}.json、两份 owned 目录与 research-sft-02/processes。
- [R7] research-final-evidence-02/research-diagnostic-02/DIAGNOSTIC.json；research-results-review-02/MISMATCH_INSPECTION_RECEIPT_02.json。
- [R8] research-sft-v1-source-working/RESEARCH_PROTOCOL_V1.md，SHA 1f3171699624a18f705728f495d81c51c4909d2e7c3a6950df14335b31cdc0ee；research-interpretation-review-01/REVIEW.md，SHA 1857e9037e1e1222f64934e6b3b5e6cbf3807580980b0683f911766dca893a2e。
- [R9] research-final-evidence-02/probe-qwen-parent-03 的 RESULT、FREEZE、PREPARED_A_RECORDS、repository/READINESS 与原始步骤；parent RESULT SHA 33d0d5359edf547afa6d5de36a9db5f691b14a5eca4387c0ebcdd36b6d6f550d。
- [R10] research-final-evidence-01/research-sft-01/RESULT.json，SHA bbb77cb25b2f7e28caa3a71f7112d549734b3ff8bbdd32b562fc2bbbf5bc0e33；research-results-review-01/RESULT_REVIEW_01.md。
- [R11] research-results-review-02/{REVIEW_EXECUTION_RECEIPT_02.json,REVIEW_STDOUT_02.log,ANALYSIS_ATTEMPT_01_FAILED.json,ANALYSIS_ATTEMPT_02_READOUT.json,CLOSED_RESULT_REVIEW_02.json,SCHEMA_INSPECTION_RECEIPT_02.json,SCHEMA_INSPECTION_STDOUT_02.log} 及各对应只读程序。
