# V10 独立结果审计

审计对象：[memory-v10-formal-01](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-formal-01/SUMMARY.md)。本报告只读原始结果、源清单、张量字节和训练／读取收据；没有重新训练、调用编码器、执行模型预测或运行任何旧 held。审计脚本和派生表位于独立目录，原始结果与研究源码未修改。

## 结论

**证据完整性与汇总计数通过；科学结论应保留明确的负结果。** 对 2,215 个文件、345 个 checkpoint 的字节／摘要、保存的逐条预测、训练日程、目标和来源核查，没有发现本次检查覆盖范围内的不一致。290,616 项检查只是本审计程序执行的条件检查次数，不是统计样本量或对科学假设的置信度。

这轮支持已知地址上的真实参数读出、固定类型分解的条件性优势，以及可审计的维护机制。它未显示可靠的直接未见表达泛化、学习型寻址、自动结构分化优势或完整生命周期成本优势。同信息 SQL planner 在本有限任务上仍然达到 100%。

原始 SUMMARY 的主要数字与保存证据相符，但最终解释应补充三点：直接未见表达的准确率很低；全部结构候选本身也没有通过质量门槛；最终维护两臂相同来自共同清洁重建，普通更新轮存在明显的新记录／旧记录取舍。

## 1. 完整性与冻结

| 项目 | 复核结果 |
| --- | --- |
| 原 ARTIFACTS 清单 | 2,214 个唯一路径，逐文件大小全部匹配 |
| 含 ARTIFACTS 自身的实际文件数 | 2,215 |
| 全部实际文件字节数 | 153,096,915 B |
| checkpoint | 345；各张量形状、字节数、SHA-256、有限 float32，以及组合参数摘要均匹配 |
| 冻结源码 | 32 个源文件匹配 SOURCE_MANIFEST；运行复制清单与当前冻结清单完全相同 |
| 冻结提交 | `dd727713ad8074a74f88b5782b2a86f26a1cc30b` |
| 发布清单 Git blob | `7649c85137709d4e1e2844f79d526e212f5e871f`；已与 GitHub 只读返回身份核对 |
| 源清单 SHA-256 | `38559a7e81e22b6742febb4fdca9b52e567495cb0233eabd28aae9979c6c24b7` |
| 协议 SHA-256 | `ecbf06ba74e51dae0f3d9d2eadde62aec97c4dbd05c32d3d520d2f1ff311b355` |
| 审计全文件哈希清单 SHA-256 | `09e1b0ec479a3ea36732e7d85e74539708f119ca3d4887dc526eb611640883ce` |

原 `ARTIFACTS.json` 只有路径与大小，没有文件哈希。因此“所有原始文件都匹配一个早于审计、带可信签名的全量哈希清单”并非现有证据。本审计新增 [FILE_HASHES.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/FILE_HASHES.json) 为这 2,215 个文件逐一计算 SHA-256，供归档后的完整性复核；原张量及源码中已有摘要则逐项独立重算匹配。

过程账本共 21 个成功退出阶段。9 个 fit 阶段均先于 `prepare-held-after-all-fits`，9 个 fresh read 均在其后。阈值来自已保存 calibration 候选统计，未发现 held 后改阈值。这里验证的是保存账本和冻结代码的一致性，不能把无独立签名的本地账本当成操作系统级不可篡改日志。

证据：[RUN_FREEZE.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-formal-01/RUN_FREEZE.json)、[SOURCE_MANIFEST.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-formal-01/SOURCE_MANIFEST.json)、[PROCESSES.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-formal-01/PROCESSES.json)、[AUDIT.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/AUDIT.json)。

## 2. 参数内容与未见表达必须分开

以下是先跨三个种子汇总正确数／总数再计算比例。容量表示每种记忆的已知地址数；三个种子是同一批人工生成任务的优化重复，不是三批独立现实世界任务。

| 容量 | 类型 | Residual：规范地址 | Residual：直接未见表达 | 独立 Linear：直接未见表达 |
| --- | --- | --- | --- | --- |
| 32 | semantic | 84/96 (87.50%) | 1/192 (0.52%) | 7/192 (3.65%) |
| 32 | procedure | 96/96 (100.00%) | 4/192 (2.08%) | 30/192 (15.62%) |
| 64 | semantic | 68/192 (35.42%) | 0/384 (0.00%) | 5/384 (1.30%) |
| 64 | procedure | 155/192 (80.73%) | 6/384 (1.56%) | 24/384 (6.25%) |
| 128 | semantic | 30/384 (7.81%) | 1/768 (0.13%) | 0/768 (0.00%) |
| 128 | procedure | 194/384 (50.52%) | 10/768 (1.30%) | 42/768 (5.47%) |

直接表达是将未见措辞的表示送入内容模型，不先替换成规范地址特征。因此规范地址下的 87.50%／100% 不能描述成对新表达的相同能力。训练参数带来的规范地址收益存在，且明显超过未训练内容臂；但在固定 rank 与训练预算下，容量增大时内容准确率迅速下降。

本轮模型为冻结 MiniLM 表示之上的仿射残差因子和输出头，未微调 Transformer。来源与例外由旁路证据维护；它们没有因参数记忆存在而被取消。

所有内容臂使用同一个实际行日程、特征和目标，训练臂各 1,200 × 32 = 38,400 次样本呈现。Linear 的参数更少，故其与 residual 对照用于识别结构／容量贡献，不能称为等参数实验。新进程读出结果绑定已验证的 checkpoint 参数摘要；本审计没有重复执行这些模型。

证据：各 `evaluation/capacity-*-seed-*/RESULTS.json` 的 `content` 逐条预测，以及相应 `models/.../FIT.json` 和参数 manifest；完整合并计数见 [AUDIT.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/AUDIT.json) 的 `content`。

## 3. 固定多类型组合：超过限定 joint 对照，未超过同信息 SQL

| 容量 | 臂 | 保留集内未触发 hold 的执行完全正确 | policy 与 program 均完全正确 |
| --- | --- | --- | --- |
| 32 | typed | 177/180 (98.33%) | 182/192 (94.79%) |
| 32 | joint | 7/180 (3.89%) | 2/192 (1.04%) |
| 32 | dense_joint | 3/180 (1.67%) | 0/192 (0.00%) |
| 32 | exact_sql | 180/180 (100.00%) | 192/192 (100.00%) |
| 64 | typed | 220/360 (61.11%) | 115/384 (29.95%) |
| 64 | joint | 14/360 (3.89%) | 1/384 (0.26%) |
| 64 | dense_joint | 12/360 (3.33%) | 0/384 (0.00%) |
| 64 | exact_sql | 360/360 (100.00%) | 384/384 (100.00%) |
| 128 | typed | 162/726 (22.31%) | 32/768 (4.17%) |
| 128 | joint | 11/726 (1.52%) | 0/768 (0.00%) |
| 128 | dense_joint | 9/726 (1.24%) | 0/768 (0.00%) |
| 128 | exact_sql | 726/726 (100.00%) | 768/768 (100.00%) |

原汇总的 `non-held` 指的是排除 `hold=true` 的业务例外，不是排除 held-out 测试集。上表均来自保留组合；建议保留“保留集内未触发 hold”的完整表述。

执行正确要求返回状态、值和逐步 trace 与来源解释器一致，但一个程序可能不使用 policy 的全部字段，因而执行正确率仍可高于两个参数值均正确率。不能用前者替代后者证明所有知识都被恢复。参数值完全正确列来自保留的 `policy_exact` 与 `program_exact` 逐行标志；由于结果未保留该列对应的完整解码 policy/program，本审计只能独立汇总标志，不能在不重跑模型的前提下重新评分这两个标志。

训练对照核查全部通过：三臂真实 pair features、40 维 targets、来源摘要和行日程一致；各 1,200 × 32 = 38,400 次呈现、每次 768 个输入坐标。Typed 与 block-head joint 各 21,544 个可训练／保存参数；dense joint 为 36,904 个。逐 checkpoint 实际标量数与收据一致。训练组合与保留组合没有交集。Typed 是预先规定的类型分解，结果支持其在这一数据构造中的归纳偏置；它不证明自动发现类型或一般任务上胜过单模型。

同信息 SQL planner 具有同一批政策、程序、情景、例外和有界解释器，全部组合达到 100%。这些结果不支持“已经超过强检索或同信息 planner”。

证据：各 `RESULTS.json` 的 `composition.rows`，`composition-training.npz`，`composition-schedule.npy`，`FIT.json`；[AUDIT.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/AUDIT.json) 的 `composition` 与 `fairness`。

## 4. 寻址：拒答率与精确率需同时呈现

学习型路由的重新合并计数如下：

| 容量 | 接受已知请求／已知总数 | 正确接受已知／已知总数 | 已接受且已知中的精确率 | 错误接受未知／未知总数 |
| --- | --- | --- | --- | --- |
| 32 | 2/768 (0.26%) | 1/768 (0.13%) | 1/2 (50.00%) | 0/384 (0.00%) |
| 64 | 11/1536 (0.72%) | 6/1536 (0.39%) | 6/11 (54.55%) | 6/768 (0.78%) |
| 128 | 3/3072 (0.10%) | 3/3072 (0.10%) | 3/3 (100.00%) | 2/1536 (0.13%) |

Deterministic 与 oracle 对所有已知请求的地址三元组完全正确，且没有接受未知请求；nearest 在三个容量上均未接受任何已知请求。Oracle 是诊断上界。Deterministic 在这个受控键名／措辞域表现强，但不能外推成任意自然语言寻址已解决。学习型路由的近零覆盖与内容读出失误是不同的失败来源。

原 SUMMARY 已正确将精确率标为 `Accepted-known precision`。例如容量 128 的 100% 是 3/3 个已接受且已知的请求，不包含 2 个错误接受的未知请求；对全部 5 个接受请求，正确地址占 3/5 = 60%。还应避免把大量未知拒答造成的总准确率描述成已知记忆可访问率。

重新核查了保留路由逐条预测的接受条件、score、margin、正确三元组与 pooled counts。Calibration 原始逐条路由预测没有保留；审计能根据已保存候选计数重新确定选中阈值并确认 held 使用同一阈值，无法独立重算 calibration 的候选计数。

证据：各 `RESULTS.json` 的 `routing.rows`、各 `FIT.json` 的 `routing.*_selection`；[AUDIT.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/AUDIT.json) 的 `routing` 与 `pipeline`。

## 5. 自动分化：质量门槛也未通过

校准集的规范地址内容准确率：

| 容量 | 动态两个子 adapter | 固定两个专家 | 单个 rank-8 |
| --- | --- | --- | --- |
| 32 | 69/96 (71.88%) | 77/96 (80.21%) | 96/96 (100.00%) |
| 64 | 66/192 (34.38%) | 76/192 (39.58%) | 132/192 (68.75%) |
| 128 | 37/384 (9.64%) | 53/384 (13.80%) | 87/384 (22.66%) |

9/9 个动态分裂候选的 `no_canonical_regression` 为 false；只有 2/9 在 worded 校准问题上严格超过两个对照，且每次仅多一个正确回答，并伴随规范地址退化。9/9 个 merge 的校准 `no_quality_regression` 也为 false。因此所有候选的质量门槛已经失败；成本完整性门关闭是另一项独立理由，不能把未晋升仅归因于成本尚未测全。

实际训练日程一致，各臂 600 × 32 = 19,200 次全局行呈现，6,144 个可训练 adapter 参数，head 字节与父模型完全相同且冻结。子模型只处理自己的路由行，其每参数更新次数记录在原收据中。结构 worded 评分用真实地址选择已有簇，是条件于 oracle 寻址的结果。本轮保存了分裂、合并和休眠候选机制，但没有证据说明动态分工胜过增 rank 或固定专家。

证据：各 `evaluation/.../STRUCTURE_CALIBRATION.json`、`STRUCTURE.json`，`models/.../structure/STRUCTURE.json`；[AUDIT.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/AUDIT.json) 的 `structure`。

## 6. 持续维护：最终重建会掩盖普通更新的取舍

每个种子共有 32 轮，其中 4 轮为删除后的共同清洁重建，其余 28 轮为普通更正／新版本插入。以下只汇总普通更新轮：

| 种子 | 维护臂 | 未改地址准确数／读取数 | 本轮改动地址正确数／轮数 |
| --- | --- | --- | --- |
| 1741 | full_replay | 852/1764 (48.30%) | 9/28 (32.14%) |
| 1741 | reservoir16 | 422/1764 (23.92%) | 27/28 (96.43%) |
| 1742 | full_replay | 967/1764 (54.82%) | 10/28 (35.71%) |
| 1742 | reservoir16 | 422/1764 (23.92%) | 28/28 (100.00%) |
| 1743 | full_replay | 903/1764 (51.19%) | 10/28 (35.71%) |
| 1743 | reservoir16 | 423/1764 (23.98%) | 28/28 (100.00%) |
| 合并计数 | full_replay | 2722/5292 (51.44%) | 29/84 (34.52%) |
| 合并计数 | reservoir16 | 1267/5292 (23.94%) | 83/84 (98.81%) |

小回放集强烈优先学习当前改动，代价是未改地址的整体准确率明显较低。这里的“未改地址准确率”并不是“以前正确且现在仍正确”的条件保留率，不应直接标成旧能力保留率。反复读取同一地址形成的分母也不是独立统计样本。

第 32 轮两臂从同一原始初始化、相同全部保留记录和相同行日程清洁重建，最终参数 SHA 完全相同，故最终准确率相同是设计结果。实际上每个删除重建节点的两臂参数 SHA 都相同，不能据此得出 16-record replay 与完整回放长期等效。`reservoir16` 是从完整活跃列表每轮重新采样 15 条并强制包含当前变更的一条，不是永久流式 reservoir。

删除与来源核查通过：所有普通更新保持参数连续性并累积真实历史训练来源；所有删除节点回到原始初始化；重新训练来源为当前保留记录；被删除地址的所有历史版本均不在重建模型 lineage 中。活跃来源元数据与实际活跃集合一致。删除及 stopped 守卫收据中模型读取为零，但这是 Python 研究守卫；真正 owner 的读取、停止、迁移和撤销证据在独立 native integration，本目录不能代替其验收。

删除重建维护的是服务拒绝与新活跃模型的来源边界。旧 checkpoint、来源和历史读出仍留在审计档案中，不构成所有历史副本的物理擦除或信息论删除保证。

证据：容量 64 的三个 `MAINTENANCE.json` 与 96 个 `CYCLE.json`，192 个维护 checkpoint；[AUDIT.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/AUDIT.json) 的 `maintenance`。

## 7. 成本：参数文件小不等于系统压缩优势

下表均为字节；规范特征覆盖 semantic 与 procedure 两种类型：

| 容量 | sources.json | exact.sqlite | 压缩 canonical.npz | 解码规范特征 | 两个活跃 residual 的参数 |
| --- | --- | --- | --- | --- | --- |
| 32 | 27865 | 40960 | 91409 | 98304 | 86176 |
| 64 | 55670 | 61440 | 182476 | 196608 | 86176 |
| 128 | 111449 | 98304 | 364466 | 393216 | 86176 |

共享冻结 encoder 文件为 127,536,988 B，须另外保留／部署并计入成本。整个审计结果目录 153,096,915 B 含候选、日程、历史和证据，不能当成单个活跃模型大小；反过来，也不能只报 86,176 B 参数而忽略 source、cache、router、head、encoder 和历史。原始 sources 与 SQL 保留准确值，模型并未在本实验中取代其审计职责。

完整 21 阶段账本的非重叠 child wall 合计 133.224451 s，child CPU 133.123904 s；Linux RUSAGE_CHILDREN 的累计 RSS 高水位为 524,976 KiB。原 SUMMARY 报的是生成 summary 之前 20 阶段的 132.978 s wall／132.878 s CPU，口径已明示，二者并不矛盾。不能把每个 fit 内嵌计时再次相加，也不能把累计高水位当作各阶段独立内存分配。

安装、上传、外部宿主／native 执行和能耗没有在这个账本内测量。Pipeline 计时还包括参考查找和证据序列化；三个 seed 对六个读臂只做部分顺序轮换，不能据此给出精确孤立服务延迟排名。本轮没有形成完整生命周期成本优越的证据。

证据：[PROCESSES.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-formal-01/PROCESSES.json)、[TRAIN_ENCODER.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-formal-01/data/TRAIN_ENCODER.json)、[HELD_ENCODER.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-formal-01/data/HELD_ENCODER.json)、[ARTIFACTS.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-formal-01/ARTIFACTS.json)。

## 8. 审计边界与推荐结果措辞

推荐把最终结果表述为：

> 已建立并实测有限任务上的参数记忆、显式多类型协作与可追溯维护流程。固定类型分解在等训练日程、等参数的限定 joint 对照上更强，但仍落后于同信息 SQL planner；直接未见表达和学习型寻址表现弱，动态分裂与合并没有通过质量门槛。小回放集改善最新更正的学习，却降低未改地址准确率。本轮提供可复核机制与负结果，没有证明通用记忆、自发网络形成或完整成本优势。

本审计独立计算原始字节摘要、目标／日程摘要、保存预测的评分、来源程序真值和结构门槛；没有重新运行模型，因而不能单凭本报告证明每个保存的模型预测都来自声明的实际参数执行。该真实性依赖冻结研究实现、进程隔离与独立 native parity／owner 证据的联合验证。组合两值完全正确标志及 calibration 候选计数的可独立复评分局限已在上文披露；没有用推断填补缺失逐条数据。

审计交付：[audit.py](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/audit.py)、[AUDIT.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/AUDIT.json)、[FILE_HASHES.json](sandbox:/workspace/scratch/76e2020e4b36/memory-v10-audit/FILE_HASHES.json)。
