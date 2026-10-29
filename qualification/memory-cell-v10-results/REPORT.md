# Hepta memory cells V10：交付、实测结论与实现边界

## 结论

**可以把 Hepta neuron 扩展为有类型、带来源和生命周期约束的参数记忆 cell；本轮没有证明它已经成为可靠、成本更低的通用 memory system。** 五个工作包已经落到实现、冻结实验和证据产物中。真实训练改变了可持久化的参数映射，固定类型分解在本轮组合任务中有效；未见措辞、learned 寻址、规模扩大、动态分裂和持续维护均出现实质性质量问题。完整结果包含失败，不以能够保存／加载权重代替记忆系统优势。

这是在固定基线 `0f41c4968eea63727c69e2b979491e94a99a9dbb` 上的新一轮工作。交付位于 [draft PR #4280](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4280)，以旧研究分支为 base；未合入 main，旧研究、旧协议和旧 held 结果保持原身份。

## 阅读入口

- [研究结果、指标定义与图表](research_results_zh.md)：参数、寻址、组合、结构、32 周期维护与成本的完整解释。
- [实现报告](IMPLEMENTATION.md)：Rust 合同、参数载体、owner、来源、控制流程和当前耦合。
- [每个 seed 的计数](analysis/COUNTS.md) 与 [机器可读计数](analysis/COUNTS.json)。
- [独立一致性审计](audit/AUDIT_REPORT.md)：审计范围、未保存的逐条 calibration 信息和其他证据边界。
- [原始证据运输清单](formal-01/TRANSPORT.json)、[逐文件 SHA-256](formal-01/RAW_FILES.json)、[恢复程序](formal-01/restore.py)。
- [原生实测结果与证据范围](NATIVE_RESULTS.md)；[CI 的身份验证与最终格式化流程](../memory-cell-v10-ci/README.md)。

## 1. 五个问题的答案

| 工作包 | 实际交付与观察 | 判断 |
|---|---|---|
| 真实参数记忆 | 固定 pretrained encoder；真正更新的 semantic／procedure 参数；独立训练与读取进程；来源、特征、参数摘要；独立 linear、untrained、SQL 对照 | 有有限参数记忆证据；直接未见措辞基本失败，不能称语言泛化已解决 |
| 可靠寻址 | Learned 约束输出、nearest、确定性 registry 与 oracle；校准阈值冻结后评估；接受率、精确率、unknown 错接同时计量 | Learned known coverage 只有 0.10%–0.72%；低错接不等于可用 |
| 固定多类型组合 | 显式事件与 hold，加 semantic 和 procedure 参数；已知事实的新配对；等输入／等呈现预算 joint 和同信息 SQL 对照 | Typed 优于所测 joint；没有超过 SQL，也没有测通用 LLM planner |
| 参数分化 | 训练梯度提出分裂；真实训练子 adapter；固定专家、等 adapter 参数 rank-8；合并候选与 sleep／wake | 九组 split 与九组 merge 的质量门槛全部失败，候选均未晋升 |
| 持续维护与真实执行 | 三 seed、两策略、各 32 周期；来源干净重建；另有 native owner、控制 socket、冷恢复、停止与撤销实现 | 研究中存在明显新旧知识权衡；native 实测状态见下节；未建立全生命周期优势 |

### Native 验证与最终源身份

<!-- NATIVE_STATUS_BEGIN -->
**原生验证已通过 [run 40909855139](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40909855139)。** 实际测试提交为 `4131172a07fdf5bf5fe84f0397800bf900248ab8`；11 项 Python 驱动检查、969 个普通 Rust 测试和唯一的 actual 生命周期 parent 全部成功。三阶段 16＋16＋15 个地址的 Rust 数值 parity 通过，五组共 79 次 socket 单值真值检查实际完成。四个服务 owner 正常停止，第五个冷启动因撤销见证明确拒绝读取；迁移为同宿主真实 TCP。

原始 GitHub ZIP 与全部 343 个归档成员已核对，保存为可恢复的 Git 分块；数值一致性、owner 源真值和组合读出的不同证据口径见 [原生结果](NATIVE_RESULTS.md)。前三轮失败均保留：前两次是测试编译问题，第三次普通测试已通过、但驱动 JUnit 路径错误导致 actual 未启动；没有修改断言或研究阈值来消除失败。

最终 `just fix`／`just fmt` 单独运行：[run 40912733051](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40912733051)。它认证成功验证产物与完整保护源后才允许修复、格式化，之后不重跑测试。最终补丁与发布身份待该阶段完成后核对。
<!-- NATIVE_STATUS_END -->

原生实际生命周期与 Python 研究是两条独立证据链。研究的 32 周期不能冒充 native owner 已运行 32 周期；原生小规模参数读出也不能替代容量 32／64／128 的研究比较。原生 runtime 目前没有自动采用研究中的 split／merge 候选。

## 2. 研究结果：有效机制与失败位置

### 参数确实发生学习，但访问泛化不足

Semantic 值是三个 0–15 整数，procedure 值是四个有界 opcode。容量表示每一种参数类型的地址数；三个 seed 是同一人工分布上的优化重复。下表是在已知 canonical 地址上的完整值 exact match，地址由 oracle 给定，不包含寻址错误；要求完整值全部正确，不能用逐 bit 准确率替代。

| 每类型容量 | Semantic residual | Procedure residual | Untrained | SQL |
|---:|---:|---:|---:|---:|
| 32 | 84/96，87.50% | 96/96，100% | 两类均 0/96 | 两类均 96/96 |
| 64 | 68/192，35.42% | 155/192，80.73% | 两类均 0/192 | 两类均 192/192 |
| 128 | 30/384，7.81% | 194/384，50.52% | 两类均 0/384 | 两类均 384/384 |

直接把未见措辞送入内容模型时，semantic residual 在三档容量分别只有 **1/192、0/384、1/768**，procedure residual 为 **4/192、6/384、10/768**。Canonical 参数读出与自然语言访问必须分别验收。[完整内容结果](research_results_zh.md#2-参数记忆参数中有知识容量与措辞访问仍受限)。

本轮训练的是 frozen MiniLM 表示上的 residual adapter 和 head，未微调 Transformer。可训练 head 下 `H(I+BA)x+b` 仍为 affine map；相对独立 linear 的优势不是函数族表达能力更强的证明。各容量总训练呈现预算相同，因此扩容曲线同时反映每地址训练曝光下降，不能作为理论容量上限。

### 类型分解帮助组合，但没有胜过同信息显式存储

| 容量 | Typed 完整执行 | 等参数 joint | 更大 dense joint | 同信息 SQL |
|---:|---:|---:|---:|---:|
| 32 | 177/180，98.33% | 7/180，3.89% | 3/180，1.67% | 180/180 |
| 64 | 220/360，61.11% | 14/360，3.89% | 12/360，3.33% | 360/360 |
| 128 | 162/726，22.31% | 11/726，1.52% | 9/726，1.24% | 726/726 |

这些分母都是 held-out 查询中 `hold=false` 的请求，衡量结果和完整 trace。不是排除 held-out 数据。Typed 与 joint 同为 21,544 个 float32 参数；dense joint 有 36,904 个。程序执行有时不依赖错误字段，因此完整执行正确不保证完整参数值正确。容量 128 时，typed 在全部 pair 中两类参数都精确仅为 **32/768，4.17%**。

SQL 对照实际执行逐条读取，使用同一来源信息和同一个有界解释器。这是本受控任务的强显式存储／规划对照；没有独立通用语言模型 planner、开放域 RAG 或未见事实归纳评测。[组合口径](research_results_zh.md#3-固定多类型组合结构偏置有效强-sql-对照仍领先)。

### Learned 寻址没有达到可用水平

| 容量 | Known 正确／接受／总数 | Known coverage | Unknown 误接受 |
|---:|---:|---:|---:|
| 32 | 1/2/768 | 0.26% | 0/384 |
| 64 | 6/11/1536 | 0.72% | 6/768 |
| 128 | 3/3/3072 | 0.10% | 2/1536 |

容量 128 虽有 3/3 的 accepted-known precision，计入 unknown 后实际所有接受请求为 **3/5 正确**。Nearest 在冻结校准规则下全部拒绝。确定性 registry 与 oracle 对本受控 closed registry 的 known／unknown 全部处理正确。不能把 native 的“learned operation + 确定性 key 绑定”混合 worker 成功，转述成研究中的三头 learned router 已解决地址泛化。[寻址口径](research_results_zh.md#4-寻址拒绝大多数请求不能算可靠可用)。

### 动态分裂应由证据阻止晋升

下表衡量预先声明的策略更正之后，canonical 地址上的完整 policy exact match；不是 held wording 的总体任务正确率。

| 容量 | Dynamic children | Fixed experts | 等 adapter 参数 rank-8 | Merge |
|---:|---:|---:|---:|---:|
| 32 | 69/96 | 77/96 | 96/96 | 54/96 |
| 64 | 66/192 | 76/192 | 132/192 | 41/192 |
| 128 | 37/384 | 53/384 | 87/384 | 26/384 |

Dynamic 的 canonical 正确数在九个 seed×容量配置都低于 rank-8。九个分裂、九个合并质量门槛均失败。这是质量上的负结果，不能仅解释为成本尚未测全。子 adapter 和 merge 候选已实际训练保存，九次 sleep／wake 的参数与 raw 输出身份一致；这些机械动作没有产生已获准使用的更优拓扑。结构实验的 child 选择依赖真 registry 地址，属于 oracle-address 条件。[结构证据](research_results_zh.md#5-参数分化当前候选没有胜过增-rank)。

### 持续维护仍有明显权衡

排除四个共同删除重建周期后，每个 seed 有 28 次普通更正／插入，共 84 次；每次有 63 个未改地址。

| 策略 | 未改地址正确 | 当前变化正确 |
|---|---:|---:|
| Full replay | 2722/5292，51.44% | 29/84，34.52% |
| Sampled replay (16) | 1267/5292，23.94% | 83/84，98.81% |

“未改地址准确率”包含此前可能已经错误的地址，不是以此前答对为条件的保留率。Sampled replay 从完整 active 集合每次重新抽样，并非持久流式 reservoir。24 次 arm 级 clean rebuild 的原初始化和删除来源排除均通过，但来源干净性没有保证重建后的回答质量。历史权重保留用于审计，不能声称物理抹除或一般机器遗忘。[逐周期结果](research_results_zh.md#6-持续维护当前变化与未改地址准确率的权衡)。

## 3. 当前实现距离独立局部 cell 的差距

已实现的核心分工是：显式 owner 日志负责情景、时间、来源和 hold；参数 cell 读出策略与程序；受预算约束的解释器组合这些值；发布、代际、撤销、停止和迁移复用现有 Hepta owner 与 artifact 生命周期。

当前 semantic／procedure 同时绑定同一 owner、同一精确 scope 的完整 Lane C cut。该 cut 在筛选 inventory schema 之前取得，因此 Event、Hold、普通 memory、source ledger 或 KG frontier 变化也可能使原有两模型 bundle 一并失效。512 个 owner head 的上限也在 schema 筛选之前检查。这里的范围来自源代码审阅；不能把所有连带失效情形都写成已新增的 actual 测试。

这是保守的来源时效机制，也带来跨记录的可用性和发布成本耦合。**旧 bundle 失效不等于权重在数学上必须重训。** 当训练来源未变时，权重可能复用，但独立的“只更新 cut 绑定并重新验收”路径尚未得到验证和成本计量。因此当前不能声称各 cell 的训练、版本和发布生命周期已完全独立。[详细绑定链条与边界](IMPLEMENTATION.md)。

真实执行还受到明确约束：有限 registry、确定性 key／alias 绑定、有限程序词表与固定解释器；原生 five-owner 设计包括四个提供服务的进程和一个冷启动撤销拒绝进程；迁移使用同一物理主机的真实 TCP 通道；sleep 释放解码缓存，原始签名 payload 仍保留。它们均不等于开放域自主网络或生产部署。

## 4. 成本与证据完整性

正式研究完成 300 次 fit、219,600 梯度步骤、7,027,200 样本呈现。21 个非重叠子进程 wall 合计 133.224451 秒，user＋system CPU 合计 133.123904 秒，累计 child peak RSS 为 524,976 KiB。内部 fit 时间已包含于进程成本，不能重复相加。这些数字不包含完整环境安装、全部 CI 编译、artifact 上传或能耗。[成本明细](research_results_zh.md#7-成本活动模型共享资产与研究证据分别计量)。

一个活动两类型 residual 权重为 86,176 字节；canonical 特征缓存随容量为 98,304／196,608／393,216 字节；learned router 为 120,088／218,648／415,768 字节。共享 encoder 另需 127,536,988 字节。对应 SQL 文件为 40,960／61,440／98,304 字节，已包含语义、程序、事件和 hold；模型方案仍需显式来源、例外和 owner 状态。**本轮没有整体压缩比或全生命周期成本优势的证据。**

完整研究 raw 包含 2,215 个文件、153,096,915 字节，压缩运输包为 35,255,252 字节，拆为 89 个小块。运输包 SHA-256 为 `dd24d42dd46f1a980c58da6530d6164e9b547fbab4a10de2c2e21f3d26c43d3c`。恢复程序已逐文件检查完整集合。独立审计执行 290,616 项一致性检查，没有发现其范围内的不一致；这些检查不是 290,616 个独立科学样本，也没有重新跑训练或 encoder。

Calibration router 只保存阈值候选聚合计数，未保存逐条 calibration 预测；composition 保存精确性标志、执行结果与 trace，未同时保存每个 pair 解码后的全部策略和程序值。重放可以利用已保存权重与特征，但不能将未保存的逐条预测冒称为已有原始日志。[审计边界](audit/AUDIT_REPORT.md)。

## 5. 下一步应验证的设计，而非本轮已取得的能力

下一轮首先应该改善可访问性和维护质量，再扩大自动拓扑变化：

1. **分开训练依赖与读请求依赖。** 每个参数 cell 以训练来源版本集合的 projected cut 绑定权重；每次读请求再绑定 Event／Hold 等当前依赖的 query cut。两个 cut 都必须处理撤销和授权，不能通过放松来源检查换取表面可用性。
2. **建立独立 per-cell 发布与原子组合。** 每类 cell 可独立训练、验收、休眠和更换；组合读必须证明所选版本在同一请求的依赖约束下兼容。当前单 bundle 共同发布不具备这项独立性。
3. **让寻址同时满足 coverage 与 precision。** 保留确定性 registry 和强检索；learned 方案需要面对别名、歧义、未知地址和中文未见表达。约束输出只能保证类型合法，不能保证语义选择正确。
4. **改善训练与 replay，再比较细胞分化。** 当前固定预算下的容量下降与新旧知识权衡需要先解决。新的分裂策略仍应与等参数增 rank、固定专家、相同训练呈现和完整路由成本比较；通过质量与成本门槛后才可晋升。
5. **把真实 owner 的运行周期和成本扩展到同一规模。** 将逐周期更正、撤销、冷恢复和来源重建接入真实 owner，并计量训练、索引、重绑定、存储、读取、拒绝和历史回收。需补条件化保留率、尾延迟及有效服务覆盖率，而不是只计活动 adapter 字节。

这些是可检验的后续假设。本轮证据支持继续研究有类型参数记忆，也明确要求暂缓“动态细胞自发形成更优通用 memory”的结论。
