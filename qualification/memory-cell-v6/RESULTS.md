# Hepta Memory Cell V6：实现与正式验收结果

## 结论

**六条研发路线都有可执行的研究实现与实验，六项验收没有全部通过。** 本轮完成了 typed request/readout、事件／语义／过程组合、实际参数训练与回放、干净重建、结构候选竞争、独立进程节点迁移、版本发布，以及固定类型语法内的分工迁移。代码、模型工件、失败记录、成本账本和复算入口均随分支交付。

正式结果同时否定了几项过强判断：自然语言寻址没有达到预设覆盖／误接门槛；参数读者没有优于同路由的精确读者；计入搜索成本后，结构竞争仍选择强固定结构；学得分工没有超过强 capability scheduler。生产 CognitiveStore、learning owner 和 organ／TaskFlow 调用链尚未接通，不能把 qualification caller 当成产品部署。

因此，本轮支持“类型化 memory cell 可以训练、读回、组合并受版本约束”，尚不支持“小模型已实现全成本记忆压缩”“自分裂带来净收益”或“通用记忆系统已经自发形成”。机器可读结论见 [MEASURED_SUMMARY.json](MEASURED_SUMMARY.json)。

## 1. 六项验收逐项状态

| 交付项 | 已实际实现与执行 | 验收结果与剩余边界 |
|---|---|---|
| 1. 类型与可靠语义寻址 | 严格 `MemoryRequest/Readout`、独立语义／词法／混合路由候选、拒绝与来源绑定；Rust native 类型和检索验证边界 | 类型边界可用；语言正确覆盖 **128/192，66.67%**，近域不支持请求误接 **13/96，13.54%**。未达到 ≥80%／≤5% 门槛，15 个案例均失败。实体、scope、时间仍由调用者提供。 |
| 2. 三类 cell 与组合 | 事件由源 owner 精确读取，semantic／procedure cell 由真实 MLP 训练；程序解释器组合三类值；可用 CLI 写入自己的 typed records | 给定正确路由时 **192/192** 已知模板成功；实际路由只有 128/192。证明有限 schema 内的新写入读回与组合，没有证明任意文本记忆或任意程序学习。 |
| 3. 训练、回放、校准、重建 | Adam 参数更新、同起点无回放对照、不可变训练／来源记录、撤销后 clean refit、阈值校准流程 | 旧值原始预测从无回放 **111/120** 到回放 **120/120**；回放使用 **4 倍样本呈现量**。5/5 干净重建参数与独立参考逐字节相同。校准仅用已训练地址，不构成独立风险保证。 |
| 4. 分裂、合并、休眠、预算竞争 | 实际训练 refit（K=1）、fixed-2/4、split、merge；另支持来源 frontier 不变时零训练 keep。sleep 释放数值数组并可重载，记录全部搜索候选成本 | 自然预算、同参数上限两条件均 **0/5** 获得正的全搜索成本净收益；最后均采用 `fixed_4`。强固定基线采用乐观成本口径；预算为测量后的准入判断，没有硬件计算实时抢占。 |
| 5. 多节点、迁移、一致发布 | 同机三独立进程／目录、真实 kill/restart、完整 bundle 迁移、SQLite CAS 发布、混代拒绝、最终源核验与通信计数 | **270/270** 生命周期检查通过。源更新依靠显式 replay，未收到更新的副本仍可返回旧值；没有跨主机共识、自动分布式撤销或生产 organ／TaskFlow 接入。 |
| 6. 新领域、新组合、分工迁移 | typed expression 自动编译 DAG，写入新域后训练专家，冻结结构路由器，测试未见组合 | 三类 test population 共 **400/400** 正确。学得专家工作量低于通用专家，但高于强固定能力调度器 **39.3%**，另有路由开销。类型、算子和专家能力范围预先声明，没有发明新类型。 |

上述“成功数”来自不同实验，存在重复地址和重复模板，不能相加成为一个独立泛化样本数。生产接线边界详见 [native/INTEGRATION.md](native/INTEGRATION.md)。

## 2. 实际实现是什么

`v6/contracts.py` 限制请求字段、文本大小、实体／scope、时间、跳数和 cell 数，并要求失败 readout 清空值、来源和模型声明。源 digest、参数 digest、bundle digest、generation 各有单独含义，模型预测不能借来源摘要变成已证明的事实。

`v6/store.py` 保存不可变 typed source、修订与撤销。当前 event 保留精确值，semantic／procedure 参数读者用不含答案的地址特征进行预测，然后核验支持来源和完整训练 lineage。被撤销的当前来源不会自动回退成旧的“有效答案”。读时必须匹配源 cut、frontier 和完整 bundle，最后使用前再次验证。

参数 cell 是 **NumPy tanh MLP 地址关联器**，使用实际 Adam 更新。值与程序 catalog 仍显式保存并计入工件成本；没有微调语言模型把自由文本完整压入参数。frozen MiniLM 用于语言路由，其分类头与 memory cell 是两套不同参数。

当前值域由 `typed-arithmetic-v1` 明确约束：event 是有界整数；semantic 是 `{factor, label}`；procedure 是 `{opcode, bias, limit}`。程序 opcode 为 identity、add_bias、multiply、affine、clamp，其中 clamp 的含义是将 `event * factor + bias` 截断到 `[-limit, limit]`。程序 cell 学习选择已写入程序，解释器执行其语义，不能将解释器内置计算能力归因成模型学会任意算法。

本地 CLI 提供 `write/train/read/revoke/inspect`，真实调用同一 store、训练器、router 与 runtime。`read` 没有 gold、答案或操作覆盖参数。可执行示例及修订／撤销说明见 [README.md](README.md)。

## 3. 正式实验身份与有效样本量

正式执行源码提交：`856c77f8f29e84e0fdcae43e1c2171aaaaac14ee`。

| 对象 | SHA-256 |
|---|---|
| `FREEZE.json` | `a3dc02766d061d9d3031fda5117889de84d53e2a2843edfa324001ee9432d477` |
| `evaluation/records.jsonl` | `29b82275adb010bbca2c466b51e399f7ae58927c56f8406a4dc21da3e14cbab7` |
| held queries | `c4ea9cdf79c9f768401b258188bde740fb0eeb376f5b90334d2972f4b7da03b3` |
| held seal | `1ad29249d97b7b91c23cb5383b3a3baa411fe17f8c90bd7d3a913862a1b62cae` |

实验覆盖 5 seeds × 3 domains × 6 arms × 288 templates，共 **25,920 条执行记录**。不同语言模板只有 **288 个**：192 个已知、96 个近域不支持请求，来自 36 个语言家族。五份 selected router 权重文件只有一个不同摘要；15 个 seed/domain 案例的语言决策及正确性完全一致。

因此，有效语言证据不能按 25,920 条独立样本计算，五个 seeds 也没有创造独立语言路由模型。三个域改变实体和写入值，不能因此增加语言模板的独立性。held 措辞作者与 router 作者不同，但参与同一实现团队，且 held 作者后来贡献了 transport、runner 和审计，不能称独立第三方评测。

主臂按来源家族做块 bootstrap 的 95% 描述区间为：已知正确覆盖 **54.6875%–77.6042%**，OOD 误接 **5.2083%–22.9167%**。这些是 assistant 合成家族的敏感性描述，不是现实用户总体风险保证。

正式 held 执行后，没有用这些结果重新训练、改阈值或改门槛。之后新增的文档、复算器和证据包装单独提交；正式 source commit 与原始记录保持不变。配置和实际工件见 [PROTOCOL.json](PROTOCOL.json)、[reports/FREEZE.json](reports/FREEZE.json)、[reports/PREPARED.json](reports/PREPARED.json)。

## 4. 语义寻址与真实读回

### 4.1 主结果

| 实验臂 | 已知请求正确 / 192 | OOD 被路由 / 96 |
|---|---:|---:|
| 参数读者，实际路由 | **128** | **13** |
| 精确读者，同一路由 | **128** | **13** |
| 参数读者，金标准操作／拒绝标签 | 192 | 0 |
| 去掉 semantic cell | 72 | 13 |
| 去掉 procedure cell | 85 | 13 |
| 打乱参数地址映射 | 59 | 13 |

实际路由的 192 个已知请求中，128 个正确，3 个错路由后给出答案，61 个被拒绝；正确路由后的下游失败为 0。96 个 OOD 中有 13 个被当成支持操作并给出答案，83 个拒绝。预声明主门槛是已知正确率 ≥80% 且 OOD 路由错误率 ≤5%；**0/15 案例通过**。

金标准路由臂用于定位下游能力，不能作为真实语言表现。移除 cell 和打乱地址后成绩下降，说明实际计算依赖 cell 与来源路径；这不等于参数读者胜过精确读者。OOD 指标始终采用 `router_accepted`，不能用下游失败掩盖错误准入。

### 4.2 错误集中在哪里

| 已注册操作 | 正确 / 32 |
|---|---:|
| current | 23 |
| history | 21 |
| semantic | 26 |
| procedure | **13** |
| change | **15** |
| apply | 30 |

主要合法覆盖缺口在“回忆过程”与“计算变化”。三次错路由分别为 current→history、procedure→apply、change→history。这意味着返回值即使有真实来源，也可能回答了错误的请求。

13 次 OOD 误接中，两个历史时点差值占 4 次，反事实 3 次，新算术如对数 2 次；另外 4 次为因果解释、跨实体比较、创造／优化程序、多输出各 1 次。这些能力有些能用更丰富 DAG 表达，但当前六操作语言合同没有授权其自动降级为相似的单一读取。

| 语言 | 已知正确 | OOD 误接 |
|---|---:|---:|
| English | 69/96，71.875% | 6/48，12.50% |
| 中文 | 59/96，61.458% | 7/48，14.583% |

在“新实体”方面，实验实体是新写入的 nonce 实体，路由器读取调用者提供的实体槽，不需要记住实体名称。但这不验证从自由文本识别真实实体、别名消歧或开放世界实体发现。

完整分组与成本复算见 [reports/LANGUAGE_ANALYSIS.json](reports/LANGUAGE_ANALYSIS.json)；逐条结果位于证据包的 `memory-run/evaluation/records.jsonl`。

## 5. 训练、回放、撤销与干净重建

| 读回阶段 | 五个 seeds 合计正确 |
|---|---:|
| 初始 semantic 写入 | 120/120 |
| 新增写入后的 replay | 160/160 |
| 纠正／撤销／重建后的存活记录 | 155/155 |
| procedure cell | 160/160 |
| event × semantic × procedure 组合 | 155/155 |
| learning 实验中的新领域关联 | 40/40 |

这些是写入后真实读回，不是只验证 fixture 中预置答案。各阶段重复使用部分地址，不能将各行合成独立的泛化准确率。

### 5.1 回放对遗忘的作用

| Seed | 无回放的旧值原始预测 | 回放的旧值原始预测 |
|---:|---:|---:|
| 1103 | 23/24 | 24/24 |
| 1109 | 24/24 | 24/24 |
| 1117 | 24/24 | 24/24 |
| 1123 | 21/24 | 24/24 |
| 1129 | 19/24 | 24/24 |
| 合计 | **111/120，92.5%** | **120/120，100%** |

两臂 catalog、起始参数与 400 optimizer steps 相同，但回放为 12,800 次 example presentations，无回放为 3,200 次。观察到 3 个 seed 改善、2 个持平，提升 7.5 个百分点；**不构成等计算预算的净收益证明**。无回放的 serving 支持范围也不同，所以这里使用绕过 support gate 的原始旧值预测衡量参数干扰。

### 5.2 纠正、删除与校准

每 seed 的 semantic 维护记录包含 33 次 write、1 次 revoke、4 次训练；训练行数依次为 24、32、32、31。四代参数 digest 均变化。纠正与删除后从头重训，`parent_parameters=null`，不继承隐藏单元；最后 lineage 排除被替代和被撤销 source。5/5 seed 最终 `A/a/B/b` 四组参数与独立干净参考逐字节相同。

撤销后旧快照因源版本变化不能继续成功服务；重建后删除地址不在支持表。这里证明确定性重建和服务拒绝，不证明统计遗忘或磁盘物理抹除：历史模型、源日志和审计记录仍保留。

每 seed 的 cell 校准只使用 3 个已经训练过的地址，所选 threshold 均为 0，报告明确 `population_risk_guarantee=false`。因此只有校准机制执行证据，没有独立验证集上的风险校准结论。

学习明细见 [reports/LEARNING_ANALYSIS.json](reports/LEARNING_ANALYSIS.json)，来源复算与逐 seed 校验见 [reports/LIFECYCLE_ANALYSIS.json](reports/LIFECYCLE_ANALYSIS.json) 及对应完整压缩报告。

## 6. 参数记忆的成本与压缩判断

### 6.1 同路由、相同三副本部署

| 指标 | 参数读者 | 精确读者 |
|---|---:|---:|
| 每案例三副本必要快照平均逻辑字节 | 506,009 B | 326,046.4 B |
| 15 案例、45 副本合计 | 7,590,135 B | 4,890,696 B |
| read + 最终 validation 平均延迟 | 4.845493 ms | 2.686299 ms |
| read + validation p95 | 19.142897 ms | 10.452319 ms |
| 请求尝试与收到响应的 JSON body 合计 | 5,479,207 B | 5,372,711 B |
| RPC 尝试 | 6,585 | 6,585 |

参数部署快照约为精确部署的 **1.551954 倍**，读取平均延迟约为 **1.803780 倍**。精确部署已移除参数对象，没有替它计入不必要模型负担。两臂都包含路由拒绝请求，不是只比较成功子集。

该字节口径为启动前复制的 source SQLite、owner SQLite、snapshot 与必要模型文件；不包含共同 encoder/router、日志、运行期 journal、文件系统分配开销。两者另分摊相同的 6.286830 ms/query 批量路由预算。这是缓存与批量编码后的摊销，不能当作未缓存端到端单请求延迟。RPC 字节不含 HTTP/TCP headers、重传或链路层。

### 6.2 共享模型与正式训练成本

最终 multilingual encoder 的选定源文件共 **127,538,960 B**；两种候选 encoder 的唯一文件共 **151,055,411 B**。selected router 工件每 seed **386,639 B**。原始公开 encoder 权重不随证据包重复分发，下载脚本按固定 revision、文件长度和 SHA-256 校验。

正式 router 训练共 120 次 fit，CPU 50.831157 s、wall 50.852534 s。prepare 的 15 个案例共 30 次 cell fit；纯 fit CPU 2.946135 s，prepare 父进程总 CPU 5.423936 s。30 个 cell 的参数数组合计 515,520 B，显式 catalog 31,911 B，support 映射 97,950 B；完整序列化 cell 工件为 899,813 B，已经包含上述内容及序列化开销，不能重复相加。

正式语言评估 parent CPU 26.465981 s，已回收 node child CPU 128.513538 s，wall 121.478221 s。没有按 reader 单独计量 CPU，不能从延迟比虚构出参数／精确读者 CPU 比。父进程 peak RSS 789,120 KiB 是进程高水位，不是稳态模型驻留量。

learning 实验每 seed 当前三个学习模型（semantic、procedure、新领域 semantic）约 54,840 B，完整 source ledger 的 zlib codec 约 1,252 B，前者约为后者 43.7–44.0 倍，且还需来源和维护日志。这不是主语言实验三种 cell 的系统总量比较，但再次表明本规模下没有压缩收益。

全部 extensions 外层 wall 27.855802 s、parent CPU 20.649293 s，加已记录 lifecycle child CPU 34.065516 s，共 54.714809 s。内部 fit／迁移数字用于归因，不能再次与外层总量相加。部分早期临时开发产物没有保留，历史逐 fit 成本不可恢复；正式账本不能被描述成整个研发过程的完整成本。

## 7. 结构塑性：候选能分裂，净收益门槛未通过

自然预算和同参数上限两种条件中，split 都是单个候选的最佳选择，强固定对照都是 fixed-4。但把全部候选训练、selection、保留工件和搜索开销计入预声明 **10,000 次未来查询**的目标后，5/5 seed 都保留 fixed-4。

这里有意给强固定基线乐观待遇：基线只计所选固定模型本身的 fit／eval／storage，豁免选出它的模型搜索成本；adaptive 计入全部候选搜索。源码明确记录 `fixed_model_selection_cost_waived_for_optimistic_baseline=true`。因此，这是对乐观强固定对照的保守准入结论，不是双方都承担相同搜索收费的实验。

| 条件 | 正全搜索净收益 seeds | 最终 proposal | 强固定 test 正确 | test 净收益投影均值 |
|---|---:|---|---:|---:|
| 自然预算 | **0/5** | fixed-4 × 5 | 95/95 | −0.0155141591 |
| 同参数上限 | **0/5** | fixed-4 × 5 | 95/95 | −0.0167958514 |

这些净收益单位来自冻结目标函数的系数，不是美元、实测 FLOPs 或能耗。selection 回本投影为自然预算约 60,228–65,642 次查询，同参数上限约 77,653–99,913 次；属于固定情景投影，不能替代长期在线实测。

sleep 确实释放数值数组，保留可重载的序列化模型；wake 再加载。拓扑变化是离线 successor proposal，不是在服务过程中任意改图。整个搜索预算在测量后判断是否准入，未提供中途硬件资源抢占保证。

原始同参数上限实验保存了模型、key、指标与成本，但没有保存 winner/baseline 两臂全部逐地址 test 预测。这项证据缺口被明确保留；事后使用已冻结模型补读的结果必须单独标记，不能冒充原始执行日志。

交付时另外执行一次只读补充核验：两臂各 95 次、合计 190 次读取，值和支持来源均正确；没有 fit／calibration，原 formal 输入哈希保持不变。独立重算的全部搜索成本和五个 test 净收益与原报告一致，最大浮点差 3.47×10⁻¹⁸，仍全部为负。新增推理工作代理为 199,394，推理 CPU 0.019974 s；核验函数总 CPU 0.756073 s、wall 0.182059 s，不含解释器启动及最后报告序列化。这些是额外成本与新物化证据，见 [supplement/structure-verification/SUMMARY.json](supplement/structure-verification/SUMMARY.json)。

## 8. 多节点、迁移与版本一致性

五个 seeds 各执行 54 项检查，共 **270/270** 通过。每项都比较实际 observed 与 expected，没有把 runner 的 `completed` 当成验收通过。

实际覆盖：发布前 failpoint 后旧 active pointer 保持且重开可恢复；成功 CAS 后过期 predecessor 被拒；节点真实 kill 后不返回部分答案；新 PID 重启后恢复；完整 bundle 迁移到独立 inode；混代网络拒绝；显式源更新后旧 bundle 拒绝；统一发布后新实体与纠正值正确；旧 client pin 被拒；所有子进程最终回收。

| 生命周期计量 | 五 seeds 合计／范围 |
|---|---|
| 真实 cell fit | 20 |
| 进程启动 | 40；最高同时 3 个 |
| 完整 bundle 复制 | 35 次，5,349,497 B |
| RPC | 250 次：150 read、100 validation |
| JSON 请求／响应 body | 192,982 B |
| 显式 source replay payload | 13,890 B |
| kill → 恢复 | 中位数 0.137798 s；范围 0.133355–0.323144 s |
| 发布代次／source cut | 每 seed 1→2→3／60→65 |

**五个 seed 均观测到：writer 已更新、但更新尚未送达时，旧副本仍可返回旧值。** 因为这是同机 loopback、各自独立 source 的显式复制系统，最终核验只能看到所在副本的当前 cut。它没有自动访问统一权威、网络分区协议或分布式共识，不能声称跨节点全局线性一致。

显式送达新 source 后，15/15 旧节点 bundle 被拒；统一发布后，15/15 旧 client pin 被拒。这证明已知更新下的版本一致性和恢复，不消除未观测更新的边界。生产 organ／TaskFlow、身份认证、租约和 learning release owner 仍需实际接线。

明细见 [reports/LIFECYCLE_ANALYSIS.json](reports/LIFECYCLE_ANALYSIS.json)。完整 1,735 项事后账本／哈希检查保存在 [reports/LIFECYCLE_ANALYSIS_FULL.json.gz](reports/LIFECYCLE_ANALYSIS_FULL.json.gz)。它们是证据复算，不是另外 1,735 项产品功能测试。

## 9. 新领域、组合与分工迁移

`v6/transfer.py` 将结构化 expression 编译为 typed DAG，注册 apply、difference、sum，并复用五种程序 opcode。任务之间共享依赖可去重，不必为每个新实体手写整张图。general、current、archive、revision 的能力范围预先声明；专家的 semantic/procedure cell 实际训练，ridge 路由器根据 selection 上真实正确性和工作量学习分配。

新域先写入再重训专家，结构路由器保持冻结，之后执行以下三类 test population：

| Test population | 各策略正确数 | 学得专家工作量 | 通用专家 | 强固定能力调度器 |
|---|---:|---:|---:|---:|
| 旧域，新组合 | 80/80 | 501,520 | 693,904 | 309,136 |
| 新域，已知组合 | 160/160 | 540,384 | 1,387,488 | 540,384 |
| 新域，新组合 | 160/160 | 1,003,040 | 1,387,808 | 618,272 |
| 合计 | **400/400** | **2,044,944** | **3,469,200** | **1,467,792** |

学得策略比通用专家少约 41.1% 的专家工作，比强固定能力调度器多约 39.3%，另有 17,600 次 router dot-work。这里是公开计算规则下的 work proxy，不是硬件能耗。路由器训练、80 次 cell fit 以及 selection 的全专家工作均另外记录；不能只引用推理阶段对通用专家的节省来宣称全成本获胜。

“旧域，已知组合”另有 160 条 selection 数据，没有独立 test population；不能把这第四格补算为测试。能力范围、类型与操作仍预定义，这一结果没有证明自主发现新专业化、新的自然语言意图或任意新领域知识。

## 10. 验证、可复算性与生产接线边界

主记录审计执行 **835,791 次检查，0 差异**。标准库附加审计直接读取 SQLite，独立重算来源 payload／metadata／frontier、操作答案、有序依赖及成本，执行 **253,893 次检查，0 差异**，不导入 executor 或 grader。两份审计覆盖相同 25,920 条 raw 记录，证明账本和合成源事实一致，**不使未通过的质量门槛变成通过**。

Python 在分阶段定向开发验证中通过 **50 个独立 test methods**，不是在最终完整产品 HEAD 上跑过一次全量 suite。Rust 使用原仓库 `just test` 入口完成六 crate leaf qualification：**127 passed、2 个已有 host probes ignored**，其中 7 个新 memory 测试。依赖版本与 checksum 受原 Cargo.lock 约束。随后执行 `just fix`、`just fmt`；格式化等价记录单独保留，没有把 leaf build 说成整个产品的构建通过。

native bridge 实际消费 Python 三类组合 readout，经 Rust 解码、fixture owner verifier 到现有 context compiler，得到值 290、`mixed`、一个 `UntrustedEvidence`、空 trusted instructions 和无 authority。revoked owner export 会失败。这证明 native 合同与 qualification 调用者；fixture JSON export 不代表经过认证的实时 CognitiveStore owner。

尚未完成的生产部分是明确的调用链：真实 `CognitiveStore` source ID／principal／scope 映射与最终新鲜度检查；生产 learning artifacts／ledger 的训练和发布授权；organ 调度与 TaskFlow 执行边；V2 context admission、真实 tokenization、序列化与 provider delivery。没有这些步骤，新增类型库和离线进程不能自动成为产品中的 neuron cell。

可接线的位置已经复核：`hepta-agentd::cognitive_context::read_with_retrieval_context_and_learning` 是已有真实读取路径；native `MemoryCellModelPortV1` 使用 pinned binary/Q12 表示，不能直接加载本轮 JSON float MLP，需要兼容 loader 或确定性导出。原仓库 `hepta-automation/src/taskflow_step.rs` 的 `TASKFLOW_STEP_OUTBOX_PRODUCTION_CALLER`、`TASKFLOW_STEP_OUTBOX_EFFECTS` 仍为 false；`taskflow_execution_boundary.rs` 对缺少 effect owner／terminal observer 明确返回 unavailable。只加一个 memory handler 无法补齐这些生产前提。

证据包包含 **1,971 个文件、156,471,571 B 原始逻辑字节**，压缩后 **23,993,596 B**，分成不超过 500,000 B 的 Git blobs。全部分片、整包及解压文件已按摘要恢复核验。原始公开 encoder 文件用固定来源下载，不在此包重复保存；明确缺失的早期开发临时工件仍列为未知。

入口：

- [DELIVERY.md](DELIVERY.md)：完整证据恢复、离线复算和源码身份说明。
- [README.md](README.md)：个人 typed memory 写入／训练／读取，以及重新执行实验的命令。
- [REPORTS_INDEX.json](REPORTS_INDEX.json)：报告字节数与 SHA-256。
- [evidence/ARCHIVE.json](evidence/ARCHIVE.json)：原始证据及每个分片／文件的清单。
- [reports/AUDIT_SUMMARY.json](reports/AUDIT_SUMMARY.json)、[reports/AUDIT_FULL.json.gz](reports/AUDIT_FULL.json.gz)、[reports/SOURCE_AUDIT.json](reports/SOURCE_AUDIT.json)：正式审计结果。

本轮的设计取舍由这些结果约束：保留精确事件和可撤销源记录作为事实依据；参数 cell 作为带来源和能力边界的预测器；结构变化必须经过强固定对照的全成本准入。当前证据不支持用参数模型替换精确存储，也不支持把分裂视为默认收益。可靠寻址、独立风险校准、生产 owner 调用和超过强基线的收益仍是未完成的验收项。
