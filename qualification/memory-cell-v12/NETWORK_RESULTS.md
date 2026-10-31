# V12：多类型源寻址、可学习路由与结构演化的实际结果

## 结论与范围

本轮完成了真实源码资料上的固定 typed 网络、参数化稀疏路由、实际 split/merge/sleep/wake、当前来源过滤、完整参数与 Adam 保存，以及跨阶段发布产物读回。实验也定位并修正了两个不同问题：600 类源地址的 BCE 训练严重不足；把公开 module 地址与共享章节意图分开，能够消除大量新地址读取失败。

**这些结果没有证明神经记忆优于强历史检索，也没有证明分裂产生净收益。** BCE 与 categorical 两轮分别有 12 个完整结构候选，全部拒绝。因子化寻址在后两个阶段取得 100% raw top-2，但接受正确率和未知请求拒绝仍随 seed 波动；同地址规则的历史 nearest 对照在这两个阶段都正确处理了全部测试请求。

所有内容来自固定提交 `527218f9b823540830907f861a309310b71d38c9` 的 40 个真实技术指南，切为 600 个实质章节。资料描述设计与接口，不能直接当作已部署行为。3,802 个问题是明确标注的 authored prompts；阶段是文档到达课程，不是仓库生产历史。三个 seed 共用同一语料与问题，不能算作三个独立数据集。语料身份为：

`cbad82b9e82da96a26e3f8382a68816367a43c1d5827d35afa53494c6c3cadc1`

编码器为固定 256 维词/字符 hash，MLP 的 hidden/head 确实被训练；没有预训练语言模型。这里的主要任务是 **query → 当前证据地址 → 实际来源读取**。原始来源保留，不能据此声称参数已经压缩了全部内容。真正字段内容学习与完整 document cell 生命周期属于其他独立报告。

## 1．首轮 BCE：必须保留的失败

[原始总结果](evidence/network/SUMMARY.json)保留三个 seed、三个阶段，以及完整 checkpoint/optimizer、校准和逐问题读出。每个基本模型预算是 hidden 32、240 个 batch、每 batch 32 次呈现；相同呈现次数不等于相同 FLOPs、参数量或逐地址曝光。

后两个阶段，single MLP、固定 typed、learned sparse 的已知请求“接受且全部所需证据正确”均为 0。拒绝所有请求可以正确拒绝未知例，但不能被报告为有用记忆。固定 typed 的实际 cell 调用数由 phase 1/2 的 832/834 降到 sparse 的 416/417，确实只执行了 top-1；这不是质量或完整净收益的证明。

| 首轮指标 | Phase 1 | Phase 2 |
|---|---:|---:|
| 已知请求数 | 403 | 403 |
| full-text BM25 已知接受正确 | 5.71% | 3.23% |
| dense source retrieval 已知接受正确 | 10.17% | 4.96% |
| single MLP 已知接受正确，三个 seed | 0 / 0 / 0 | 0 / 0 / 0 |
| single MLP first-relevant MRR，三 seed 均值 | 0.00541 | 0.00370 |

MRR 是第一条相关证据的排名，并不替代双证据必须全部到达的任务指标。

### 一个设计上的硬限制

原稀疏网络把 semantic/procedure 分成互斥输出分区，又只允许选择一个 cell。需要两种类型证据的请求在此配置下**结构上不可达**。三个阶段分别有 14、13、13 个这种已知测试请求。不能把它们的失败归因为神经模型容量或语义能力。后续因子化实验将证据读取预算改为 2，并明确验证 top-1 连续两次与一次 top-2 的同预算执行。四类型任务的真实消费与移除实验在独立 typed 工作包中报告。

## 2．先核对索引，再诊断训练目标

[索引与训练诊断](evidence/network-index-audit/SUMMARY.json)检查到：600 个不同 record ID、600 个不同 feature rows、没有缺失 target、没有相同问题文本对应冲突 target sets。canonical self-nearest 为 600/600。原 MLP 原始 logits 与网络包装层的 argmax 一致，没有发现输出索引错位。

诊断使用固定 ridge `λ=0.001` 的独立仿射拟合，以及 canonical prototype。诊断只读取训练/canonical 标签；没有用未来阶段测试选 λ。以下是原 BCE seed 31031 的结果：

| 阶段 | BCE canonical 全所需 top-3 | 闭式 linear canonical top-3 | BCE 已观察 query top-3 | 闭式 linear 已观察 query top-3 |
|---|---:|---:|---:|---:|
| 0 | 3.81% | 100% | 4.97% | 100% |
| 1 | 15.56% | 100% | 36.36% | 100% |
| 2 | 17.67% | 100% | 37.61% | 100% |

Phase 2 仿射 canonical first-relevant MRR 为 0.99583，历史 query 为 1.0。设计矩阵含 bias 的数值列秩为 257；phase 0 条件数很大，不能把数值满秩自动解释成稳健优化。独立正控表明这批已观察映射可被有效表达，不能把 BCE 失败直接写成容量耗尽。

## 3．Categorical 开发随访：训练明显改善，未来访问尚未解决

`categorical.py` 采用稳定 softmax cross-entropy，将每个非空单/双 source target 归一化成分布，实际训练 hidden/head 并保留 Adam。空 target 不被伪装成类别分布，其拒绝仍由独立历史校准处理。架构、240-step 基本预算和 strong controls 保持；类别损失与空行处理的改变应作为完整训练方案改变理解，不是纯粹的同梯度缩放实验。

这轮已经观察过同一语料的 BCE 结果，因此是**同语料方法开发**，不是新的独立确认。

| 阶段 | CE canonical top-3，三个 seed | CE 历史 query top-3，三个 seed | CE single 已知接受正确 |
|---|---|---|---|
| 0 | 98.10% / 96.67% / 98.57% | 100% / 100% / 100% | 8.76% / 0% / 2.07% |
| 1 | 70.37% / 71.85% / 73.09% | 100% / 100% / 100% | 0.248% / 0.248% / 0% |
| 2 | 72.00% / 73.33% / 67.00% | 99.81% / 99.66% / 99.37% | 0% / 0% / 0% |

这将优化问题和新地址/措辞读取问题分开：会拟合已观察内容，仍不等于可靠访问后来到达的 source ID。

### 空间中断、完整保留与补跑身份

原 categorical run 在共享磁盘剩余 0 bytes 时，经所属 session Ctrl-C 正常退出 130；7/9 阶段完成。没有删去、覆盖或补写原始结果。[中断凭据](evidence/network-categorical/INTERRUPTION.json)保留了完成阶段、所有已有产物及成本下界。

原 driver 只捕获 `Exception`，未捕获 `KeyboardInterrupt`，因此整次中断 run 的 wall/CPU footer 没有写出。已保存 39 个不同 fit receipts，累计 330,240 次呈现、5.70026 个 fit wall seconds。这是**下界**，不能声称所有在途工作都被完整计时。

第三 seed 在独立目录重新执行了完整三阶段，source 七项哈希及协议除 seed 列表外完全相同。[组合凭据](evidence/NETWORK_CATEGORICAL_COMBINED.json)固定最终九个阶段的路径与文件哈希：前两 seed 来自原 run，第三 seed 来自补跑。原第三 seed 的 phase 0 和未完成后缀仍保留，重复工作计入成本，而不增加试验样本数。

重复 phase 0 的所有神经参数、Adam 状态及神经 trace 逐位相同；BM25 因原版无序 `set` 累计而出现最大 `5.96e-8` 的 confidence 差异，决策和排名完全一致。没有把这种微小差异隐瞒为全部字节相等。新源码将该迭代排序，旧 raw evidence 不变。

补跑另有 18 个不同 fit receipts、153,600 次呈现、2.85721 个 fit wall seconds。因此两次 attempt 已记录的训练总量下界是 **483,840 次呈现、8.55747 fit seconds**；中断的完整端到端总成本仍未知。

## 4．因子化寻址：当前 module registry + 共享 heading 意图

[`FactorizedAddress`](factorized.py)把公开 module 名称解析、15 类共享章节意图、当前 source 绑定分开。四个策略得到同一个 literal module registry、完整可见来源和历史标签：

- learned：共享 heading-intent MLP。
- single：600 类 source classifier，随后使用同一个 module mask。
- BM25：相同 module 预过滤内的完整来源文本。
- history：相同 canonical/已观察 query，去掉公开 module 名称后 nearest，再把已知 heading 绑定到当前 module。

没有给任何 query 隐藏的正确 module、type、source ID 或目标条数。未知/歧义 module 返回零地址分数。读取从真实 record.text 取 bytes 并记录 body hash、source ID 与版本。

[完整九格结果](evidence/factorized/SUMMARY.json)如下。每个单元为**已知接受正确 / 未知拒绝**；raw 质量与可访问性分开保存。

| 阶段 / seed | learned | single | 同 registry BM25 | 同 registry history |
|---|---|---|---|---|
| 0 / 31031 | 25.81% / 0% | 12.21% / 71.43% | 22.58% / 64.29% | 0% / 100% |
| 0 / 41033 | 22.58% / 0% | 3.92% / 100% | 22.58% / 64.29% | 0% / 100% |
| 0 / 51047 | 22.58% / 0% | 4.61% / 92.86% | 22.58% / 64.29% | 0% / 100% |
| 1 / 31031 | 0% / 100% | 0% / 100% | 6.20% / 92.31% | 100% / 100% |
| 1 / 41033 | 100% / 0% | 0% / 100% | 6.20% / 92.31% | 100% / 100% |
| 1 / 51047 | 100% / 0% | 31.02% / 76.92% | 6.20% / 92.31% | 100% / 100% |
| 2 / 31031 | 96.77% / 7.14% | 11.17% / 92.86% | 2.48% / 92.86% | 100% / 100% |
| 2 / 41033 | 96.77% / 100% | 0% / 100% | 2.48% / 92.86% | 100% / 100% |
| 2 / 51047 | 100% / 7.14% | 15.63% / 78.57% | 2.48% / 92.86% | 100% / 100% |

Learned 在 phase 1/2 的 raw top-2 全为 100%，但只有先通过校准门槛才可返回。Phase 2 前两个 seed 的 13 个双证据请求被拒绝；这不是取不到两条证据，因为 raw top-2 已全部覆盖。这个结果不能替换稳定可访问性验收。

### 两读计划确实执行，但没有假称额外规划智能

每个策略都分别执行一次 top-2 和 top-1 连续两次，使用相同已冻结分数。选择集合、最终结果和实际来源读取次数逐问题一致。这个实验验证预算与执行一致性；第二步没有根据第一次文本重新学习或规划，不能称为自适应推理收益。

History 在后两个阶段正确回答 403 个已知请求（390 个单证据、13 个双证据），实际仅需 **416 次来源读取**，并拒绝未知请求。Learned 由于通常还取第二个无关候选或接收未知请求，实际读数可能更高。相同的“最多两读”预算不能掩盖实际调用差异。

### 对语言重复的事后核查

[NORMALIZED_QUERY_AUDIT.json](evidence/factorized/NORMALIZED_QUERY_AUDIT.json)显示：phase 1/2 各 403 个 known 请求，在移去公开 module 名称后仅有 31 种语言形态，**403/403 都与过去的已知问题形态完全相同**。它们的 module/source 地址是新的，语言形态不是新的。

因此，history 的满分证明了这批新地址绑定与重用；不证明陌生语言泛化。未知问题在归一化后也只有每阶段 1–2 种语言形态，不能把按 module 重复的请求当作独立的 OOD 样本。该发现保留为事后解释，不回写冻结协议或已有预测。

## 5．结构提案与独立状态维护

两轮各三个 seed，每个都实际执行 split、merge、sleep、wake：

- Split 复制父参数及 Adam，分别继续训练，并保留父模型完整依赖；没有把 routing 分区伪装成独立 clean-fit 来源。
- Merge 在已观察输入上真实蒸馏和训练，记录 teacher 调用与训练成本。
- Sleep 保存参数/optimizer 并释放该 cell 的模型对象；wake 从保留文件恢复，并核对输出逐位一致。
- 与 incumbent、真实继续训练的 parent、同宽度合计的单模型、相同数据分区固定 experts 比较。呈现次数有明确账本；不称相同 FLOPs。
- 每个候选保留 validation、所有对照、checkpoint、拒绝原因和探索成本。新阶段测试在选择之后执行，不参与选择。

**BCE 12/12、categorical 12/12 均被拒绝，保持 incumbent。** 正态近似下界门槛是小样本探索性判断，不是总体或连续多重检验保证。拒绝后的工作和字节没有从 ledger 删除；中断 attempt 的未记录成本缺口另外明示。

独立代码审查还找到了此前“所有候选均拒绝”未覆盖的实际选中路径：未分配 cell 被误当成重新训练、router 访问 sleeping cell、跨目录只重定位却未复制 sleep checkpoint。这些由新 `network_lifecycle.py` 和修订 `network.py` 处理：逐 cell 记录 continued/unassigned/sleeping，原地未训练状态保留完整 optimizer；只训练/读取 awake cell；复制并校验可移植依赖。

修后实际运行了 **12/12 行为回归**（9 个 network/lifecycle、3 个 factorized）。选中 split/sleep/wake 的测试用显式受控 admission 验证状态链，所有训练、存储、恢复都真实执行；这种功能测试不能冒称候选在科学门槛下获益。修后源码不是旧实验的受测 source，旧实验精确代码均保留在其 EXECUTED_SOURCE。

## 6．分层资源账

| 层次 | 实际计量与口径 |
|---|---|
| 原始研究来源 | 600 个章节文本共 834,524 bytes；完整语料 JSON 还包含 query/metadata，单独保留。 |
| BCE 完整研究运行 | 46.2733 s wall、66.8048 s CPU；共享 feature arrays 4,507,648 bytes；写 summary 前证据 61,406,521 bytes。 |
| CE 中断与补跑 | 中断端到端 wall/CPU 不完整；已记录训练总量下界 483,840 presentations、8.55747 fit wall s，另有完整第三 seed 总收据。 |
| Factorized 完整研究运行 | 69.2502 s wall、54.6698 s CPU、peak RSS 91,736 KiB；执行 footer 前保留 32,798,059 bytes。 |
| Shared-heading 参数 | 每个模型 34,876 FP32 bytes；Adam moments 69,752 bytes；每 fit 7,680 次呈现。 |
| 600-source single 参数 | 每个模型 112,096 FP32 bytes；Adam moments 224,192 bytes；每 fit 7,680 次呈现。 |
| Factorized phase-2 history index | 2,904,036 bytes 的 features + heading target arrays；没有做去重压缩。 |
| Factorized phase-2 public registry / BM25 index | 78,186 / 891,618 bytes；raw source bodies 另计。 |
| Factorized phase-2 完整对照 checkpoint | 三 seed 分别 1,085,892 / 1,085,958 / 1,087,123 实际 gzip bytes；含两个模型、Adam、历史 index 与恢复元数据。 |

共享 preparation、每个模型 fit、校准、逐请求实际 scoring、source 读取数量和 bytes 分别记录。Factorized 查询按单请求真实执行，而非只报 batch 除以样本数。计时发生在共享 host，不据此宣称细小差异是稳定速度优势。

完整实验 artifact 包含比较方法、历史证据及 audit 资料，不等于一个部署 cell 的内存。相反，模型参数小也不能抵消未计的 registry、replay、optimizer、原始来源和恢复历史。以上没有建立全系统压缩或全生命周期净收益优势。

## 7．归档边界与复核入口

`NETWORK_ARCHIVE_INVENTORY.json` 位于本目录，逐文件记录以下五个已经结束写入的目录及组合凭据的大小与 SHA-256：

| 目录 | 应完整保留的性质 |
|---|---|
| `evidence/network/` | 原始 BCE 完整负结果；其 EXECUTED_SOURCE 与哈希一致，源码副本是运行后补存，SOURCE_SNAPSHOT.json 明示这一点。 |
| `evidence/network-index-audit/` | 仅训练/索引诊断、独立 ridge coefficients；不是新的 held efficacy run。 |
| `evidence/network-categorical/` | 中断 attempt 全部 bytes，含完整前两 seed、第三 seed 已完成前缀与中断说明。 |
| `evidence/network-categorical-seed51047/` | 精确原 source 的第三 seed 完整补跑；其 phase-0 重复工作没有被隐藏。 |
| `evidence/factorized/` | 完整九阶段、两种两读计划、全部对照、恢复 checkpoint、执行 footer 和事后语言重复审计。 |

另须保留 `evidence/NETWORK_CATEGORICAL_COMBINED.json` 及当前行为测试记录。归档可以改变封装字节，但解包后的每个成员必须等于清单；不能以压缩后的包体大小替代模型、来源或执行成本。

后续应使用各完整训练 run 的 EXECUTED_SOURCE 重放原实验。独立 index audit 保留了诊断、系数与输入语料身份，没有另存一份当时临时调用脚本；不把这个事后诊断包装成同等级的预冻结试验。当前源码包含后来修复的状态转移路径，不能悄悄用于重写旧预测或给旧 run 加上未执行的保证。
