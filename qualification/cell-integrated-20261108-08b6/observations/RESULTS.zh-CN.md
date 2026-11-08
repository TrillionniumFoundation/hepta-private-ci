# 本轮集成候选与独立实验结果

日期：2026-11-08。**本轮形成了共同冻结、在原生环境通过 74/74 工程测试且零跳过的源码候选；完成一次新 16-seed PRED-1 独立模拟运行和完整产物核验。普通任务的生产学习闭环与真实任务学习收益尚未建立；原 PRED-1 HOLD 保留，新实验同样未达到冻结的收益门槛。**

工程通过、归档完整、科学收益和生产采用分别判定。本轮没有把其他 PR 的通过记录、他会话的未冻结 overlay 或独立模拟结果拼接为一个已经运行的生产系统。机器结果见 [result.json](result.json)，原始工程记录见 [common-engineering-evidence.tar.gz](common-engineering-evidence.tar.gz)。

## 1. 源码、运行、归档和发布身份

| 对象 | 本轮身份与作用 |
|---|---|
| 实际受测源码 C | commit `b839558b26c2e5b667055ca4af4ad749ae41c043` |
| C 的完整 source tree | `e411d25b47c166f35783a27054adb6a3f6682594`；原生门禁前、测试后、门禁结束的 commit/tree/index-tree 一致 |
| 完整源码归档 | 原生 `git archive` 生成 `source.tar`，162,334,720 bytes；11,386 个 tracked files 完整核对通过 |
| 源码归档 SHA-256 | `d1e54cba3f206516725a53a33aed7aafd204003fd7997992878d3f4a7146cf32` |
| 工程运行配置 | Python 3.12.3、NumPy 1.26.4、Pillow 12.0.0、Torch 2.9.1+cpu；四项线程环境变量均为 1；详见 [VALIDATION_PROFILE.json](../VALIDATION_PROFILE.json) 与 `result.json` |
| PRED-1 实际研究源码 | 原归档 runner，`source_identity=a07f2eb7c06c5ddf98b632a205a1865e75a18cdc09c9e3085a88dd2f01a32583`；它是单独冻结的模拟研究，不是 C 的普通 Cell 入口执行 |
| PRED-1 成功运行环境 | 独立 Python 3.12 环境、NumPy 2.3.5；与上述共同工程门禁环境分别记录 |
| PRED-1 冻结协议与配置 | FREEZE SHA-256 `19e6d61565d7d8fadf695a9a5814819197ac98835c80ad19d162e61db846b724`；研究配置 SHA-256 `c3574166b2043e3e4b4ac167e35f81a1003ff8d916a4f446010bf6a94ec77667` |
| 完整 PRED-1 原始证据包 | [pred1-independent-002-evidence.tar.gz](pred1-independent-002-evidence.tar.gz)，10,621,681 bytes（10.621681 MB），474 个归档成员，包含原始 NPZ/checkpoint 与研究记录 |
| PRED-1 证据包 SHA-256 | `ab5bd9631074325c56620440aa42ef74a72dc1b1db84c11770e50478bb56329c` |

完整归档校验只证明受测源码与归档内容对应，不授予生产身份或科学资格。源码归档的字节身份、清单摘要和校验日志保留在工程证据中；不能以几个修改文件的打包替代完整 source tree。[result.json](result.json)

### 源码发布、PR 和 CI 的实际回读

| 字段 | 当前记录 |
|---|---|
| source_release_ref | `engineering/cell-integrated-20261108-08b6` |
| source_publication_status / observed_head | `PUBLISHED_EXACT_HEAD` / `b839558b26c2e5b667055ca4af4ad749ae41c043`；tree 同时匹配，见 [SOURCE_PUBLICATION.json](SOURCE_PUBLICATION.json) |
| source_CI_status / run | 2026-11-08 18:51 UTC 快照：精确 C 的 [native run 42511643474](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42511643474) 与三个 jobs 均为 `queued`；不能判绿，见 [SOURCE_CI.json](SOURCE_CI.json) |
| draft PR | [#5395](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5395)，head C、base `6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5`；compare 为 33 commits / 225 files，含此前 25 个 foundation 提交与其后 8 个候选链提交 |
| evidence_release_ref | `engineering/cell-integrated-20261108-08b6-evidence` |
| evidence_publication_status / observed_head | 本报告在证据提交形成前写定；最终证据 ref→HEAD 回读由 PR #5395 的交付回执记录，不能用该 HEAD 替代受测 C |

源码发布已经由原 Mac `gh` 回读；创建分支只使用 absent→C 的 CAS，没有移动其他分支。原始对象上传超时、一次显式同字节 blob 恢复、树创建后暂时 404 及有界只读重查均保留在 [source-publication-and-ci-001.tar.gz](source-publication-and-ci-001.tar.gz)。CI 快照中仅 v8-canary 已完成 success，其他必需门禁未完成，整体 CI 不能记为通过。新增报告或证据的 HEAD 不替代 C；冻结时“未执行门禁/未发布”的历史记录不回写。

## 2. 第一优先级：共同冻结与可复现工程候选

**已完成：**在同一个 C 上运行六组工程控制：共同配置约束、状态 codec、子进程监督、训练结果协议、完整源码归档、PRED-1 训练/开发诊断。最终原生结果为 **74 tests、74 passed、0 skipped、0 failures、0 errors**；测试进程窗口 14.368647 秒。不是不同 PR 的测试数相加。[result.json](result.json)

实际 `pipeline.run_training_job` 现在使用有界日志与监督：stdout/stderr 各 8 MiB 上限，保留原 660 秒外层预算，清理计入实际 wall；真实退出码与超时/超限分类分开，无法确认退出或清理的工作保持 unresolved。覆盖了正常退出、超限、超时、部分输出、持管后代、I/O 故障与真实 child 经过实际调用点的约束。现有 operation 不会因 ACK 丢失而隐式重跑；监督源码与政策单独绑定 admission，没有改写 trainer 模型内容 lineage。[common-engineering-evidence.tar.gz](common-engineering-evidence.tar.gz)

同时完成完整源码归档核对和训练/开发诊断再现：归档匹配全部 11,386 个 tracked files；最终诊断的科学字段与原冻结诊断一致。环境 profile、命令、日志摘要、前后源码身份均记录。**共同学习运行配置仍为 `null`，`scientific_qualified=false`、`production_qualified=false`。**[result.json](result.json)

**仍未完成：**生产普通入口到学习、独立评价、采用/NoUpdate 和下一任务消费的装配。C 相对 f2b 没有 Rust 变更；原生源码审查在其 Rust 相同的 c864 上只命中 test `LearningIterationOwnerPortsV1` 实现及已有配置接口，main 命中已有 plasticity/generation loader，没有学习或 Circuit task 装配命中。正则审查不排除宏、生成代码或仓库外 provider；它也不证明外部 owner 不存在。[PRODUCTION_GAPS.zh-CN.md](../PRODUCTION_GAPS.zh-CN.md)

## 3. 第二优先级：固定 Cell 图上的真实学习收益

**本轮没有完成这一科学与产品目标。** 工程测试检查协议与恢复行为；PRED-1 检查受控模拟中的时序记忆增量。两者都不能充当“真实普通任务产生经验→训练候选→独立评价→采用或 NoUpdate→另一个真实普通任务消费”的运行证明。

最短后续路径已定位：首先取得并装配原任务输入/result owner、固定 Circuit 的实际 native control/readback/encoder；随后把真实终局通过持久 operation intent 接到原学习 coordinator；最后经原 selector/publication owner 执行采用或保留，并从第二个不同普通任务读回 committed use。原 registered checkpoint 能力、当前签名 trust、真实 ledger/数据冻结、独立 holdout custody、durable native-job 和 FinalUse/采用能力仍需实际接入，不能由自签 fixture 或调用者提供的摘要替代。[PRODUCTION_GAPS.zh-CN.md](../PRODUCTION_GAPS.zh-CN.md)

真实学习实验仍应固定 Cell 图、基础执行器和终局检查器，优先组合记忆—决策—验证；保留 exact-key/语义 RAG、简单阈值控制器和确定性检查器。确认任务须来自独立真实来源，并核算学习、搜索、验证、失败、恢复及后续摊销成本。这些是下一项验收要求，本轮没有填写虚构收益或已采用状态。

## 4. 第三优先级：负面结果之后的独立实验

### PRED-1：诊断、新冻结、新运行、完整产物核验均已完成

先仅使用训练/开发材料诊断 seed 202：其 GRU 开发行为与其他旧 seed 不同，但原 seed 同时控制数据、初始化和 batch 顺序，不能据此作单因解释。诊断未使用原确认集继续调参。之后保留原模型/训练规则和所选 GRU 家族，冻结新 16 个 seed、主比较、阈值与执行 guard，再进行独立运行。旧五个评价 seed 没有混入新主检验。[PRED1_RESULT.zh-CN.md](PRED1_RESULT.zh-CN.md)

首次确认生成前的 guard 检查了 114 个 checkpoint，确认数据集数为 0；执行后完整审计核对了 **435 个 manifest 输出、114 个 checkpoint 字节 pin**，确认包包含全部原始 NPZ。审计是已存产物的完整性和计数核验，没有再训练、再生成确认、重选模型或生产采用。[PRED1_ARTIFACT_AUDIT.json](PRED1_ARTIFACT_AUDIT.json)

| 冻结主比较：GRU − single-step 平均净效用差 | 结果 |
|---|---:|
| 独立主统计单元 | 16 个训练 seed |
| 冻结最小平均增量 | +0.020000 |
| 实际平均增量 | +0.010938962595 |
| 冻结单侧 p 上限 | 0.050000 |
| 实际配对 seed 符号翻转 p | 0.081268310547 |
| 描述性 seed-bootstrap 95% 区间 | [-0.000362358364, 0.026517124162] |
| 双条件裁决 | 两项均未达到；`simulation_gain_not_established`，原 HOLD 保留 |

主 p 值经标准库枚举全部 65,536 个符号分配独立重算，尾部为 5,326，完全对应摘要。检验仍依赖独立 seed 和符号可交换性；小样本 bootstrap 区间只作描述。净效用沿用注册的模拟成本/时间定义，**不是成功率百分点或包含全部宿主成本的经济净收益**。[PRED1_RESULT.zh-CN.md](PRED1_RESULT.zh-CN.md)

16 个差值中 9 正、6 负、1 零；两个较大正值占净和约 95.89%，只作为事后集中度描述，所有 seed 均保留。当前确认结果不能用于改 epoch、阈值、家族或删选任务再宣称独立确认。[PRED1_RESULT.zh-CN.md](PRED1_RESULT.zh-CN.md)

| 已存产物核验后的工作量 | 数量与分母 |
|---|---:|
| 实际 fits | 114 = 18 个 selector fits + 96 个新 seed fits |
| 消费的 optimizer steps | 109,440 |
| 选中 checkpoint 的累计 steps | 51,808；不替代训练消费分母 |
| 训练样本呈现 | 14,008,320 次；不是独立样本数 |
| 确认 episode 单元 | 16,384 |
| 六模型/episode 评价 | 98,304 次；不是 98,304 个独立统计单位 |

早先摘要复核将详细工作量保留为计划分母；后来的完整产物审计提供了上述实际存储记录核验。两份记录的作用域与形成时间分别保留，不回写旧报告成“当时已经完成全部审计”。[PRED1_ARTIFACT_AUDIT.json](PRED1_ARTIFACT_AUDIT.json)

### MEM-1、VERIFY-1、NDU、HCSN：形成下一实验设计，尚未执行

| 方向 | 本轮形成的具体下一步 | 未完成与保留结论 |
|---|---|---|
| MEM-1 | 真实项目语义状态/修订任务；保留 exact-key RAG、普通状态表、uniform replay；先诊断覆盖度匹配 | 精确检索优势保留；不能把旧 structured 负面结果改称语义增益；新 roster、encoder、来源/预算尚未冻结 |
| VERIFY-1 | 分开检查器正确性、分数校准、付费检查策略；用真实代码/配置/产物任务匹配预算 | 旧 pilot 未证明模型增益；三层效果和终局成本不能互相替代；新独立任务与标签保管仍缺 |
| NDU / CTRL-1 | 接入确有继续、修复、验证、停止取舍的隔离真实任务；与强固定阈值/简单成本规则比较 | 额外计算是否被终局收益覆盖尚未证明；动作/检查器、费用单位与摊销 horizon 未冻结 |
| HCSN | 先在具体不规则时序任务上做冻结物理、充分训练、容量匹配的比较 | 既有接口 fits 不能充当正式比较；完整 trainer、数值范围、普通门控对照与实际预算仍需补齐 |

四项材料状态为 **DRAFT_FOR_REVIEW**，不是预注册、已运行实验或新获胜结果。数据 roster、样本量、资源额度与效应门槛须在开发材料盘点后具体冻结；不把原确认集改名为独立集。[NEXT_INDEPENDENT_DESIGNS.md](../NEXT_INDEPENDENT_DESIGNS.md)

## 5. 第四优先级：组织演化与改进器改善

本轮没有把 Cell 分裂合并、技能层级、学习规则更新或改进策略继承推进为已验证能力。固定图的一阶真实收益尚未成立；应先完成上一节的机制闭环和独立真实收益，再以单独变量、独立任务与总成本识别结构变化的增量。当前不授予更广采用资格。

## 6. 成本、失败和缺测

| 实际观测窗口 | wall 秒 | 计量作用域与包含关系 |
|---|---:|---|
| 最终工程环境准备 | 53.4240 | 工程证据包内 `validation-environment-001/RESULT.json`；不包含在下面 18.2334 秒门禁中 |
| 最终原生总门禁 | 18.233415 | 本验证进程与子进程；含测试、归档生成/校验及训练开发诊断 |
| 其中六组工程测试 | 14.368647 | 是总门禁的子窗口，不重复相加 |
| PRED 首次解释器不匹配失败 | 9.018604 | Python 3.14.4 在导入原 runner、创建 campaign 前被 guard 拒绝；没有科学输出 |
| PRED 环境修复及成功 host 窗口 | 214.958357 | 包含成功 wrapper/campaign；未改冻结参数或重放已生成的科学样本 |
| 上述两个 PRED host 窗口合计 | 223.976960 | 两段非重叠窗口；不再叠加下面训练时间 |
| PRED 全部 114 fits | 168.465172 | 包含重复的 18 个 selector fits，已在成功 campaign/host 窗口内 |
| PRED 执行后完整产物审计 | 0.036315 | 后续只读完整性审计；process CPU 0.035803 秒 |

PRED 训练 process CPU 为 167.808947 秒；成功 wrapper wall 208.210650 秒、process CPU 207.461323 秒，均属于上述成功 host 窗口的内部记录。工程门禁记录的 cgroup peak memory 为 563,838,976 bytes，只覆盖工程门禁，不能代替研究峰值内存。[result.json](result.json) [PRED1_RESULT.zh-CN.md](PRED1_RESULT.zh-CN.md) [PRED1_ARTIFACT_AUDIT.json](PRED1_ARTIFACT_AUDIT.json)

**完整物理或货币成本仍未建立。** 研究 peak memory、能量、货币、远程排队/转运以及全部人工/模型研究准备存在缺测；发布、审核等窗口也不属于原生门禁。缺测不能记零，嵌套计时不能相加。失败/修复窗口与 selector 重复训练保留在相应记录中，没有只报最后成功 fit。[PRED1_ARTIFACT_AUDIT.json](PRED1_ARTIFACT_AUDIT.json)

## 7. 复核材料与结论边界

| 材料 | 可复核内容 |
|---|---|
| [result.json](result.json) | C/tree、原生命令与退出码、74/74、前后源码身份、运行 profile、完整 source.tar 和成本范围 |
| [common-engineering-evidence.tar.gz](common-engineering-evidence.tar.gz) | 本轮工程原始日志、归档校验与相关回执；不能替代真实任务学习实验 |
| [PRED1_ARTIFACT_AUDIT.json](PRED1_ARTIFACT_AUDIT.json) | 435 输出/114 checkpoint 核验、实际工作量、证据包 hash 和成本边界 |
| [SOURCE_PUBLICATION.json](SOURCE_PUBLICATION.json)、[DRAFT_PR.json](DRAFT_PR.json)、[SOURCE_CI.json](SOURCE_CI.json) | 发布 C/tree、PR 基线比较与 CI 快照分别记录 |
| [source-publication-and-ci-001.tar.gz](source-publication-and-ci-001.tar.gz) | 原 Mac 的完整 source 发布 journal、失败/恢复、PR 与两次 CI 读取原件；不声称未来 CI 结果 |
| [local-control-evidence.tar.gz](local-control-evidence.tar.gz)、[readback-control-supplement.tar.gz](readback-control-supplement.tar.gz) | 发布/归档/诊断相关辅助程序及离线控制；补充包保留 readback 的原测试与 fake GH 程序；旧 control 包说明早期临时 fake GH 源码未保留的限制 |
| [PRED1_RESULT.zh-CN.md](PRED1_RESULT.zh-CN.md) | 冻结主检验的独立算术复核、16-seed 差值、HOLD 与摘要级范围 |
| [pred1-independent-002-evidence.tar.gz](pred1-independent-002-evidence.tar.gz) | 完整独立模拟研究产物，包含原始 NPZ，便于后续按原身份复核 |

本轮可确认的是：共同源码候选的工程门禁和归档一致性成立；独立 PRED-1 研究执行及产物可核验，所要求的增益未成立。生产学习闭环、固定 Cell 图真实后续任务收益和组织演化收益仍未完成；托管发布与 CI 以第 1 节的最终实际回执为准。
