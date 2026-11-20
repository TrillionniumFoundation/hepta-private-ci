# NoUpdate12：实际 Training、独立 B 与首次 Root ACK 的物理 DATA 读回

## 结论与资格边界

原 `dbd6a00992b60f4b33e8f10c2defda031d123bcb` 的 NoUpdate12 确实产生了一个经过两步 Q24 SGD、改变两个权重坐标的候选；独立 B 的原业务阴性对照选择保留基线；六阶段 terminal、七组物理 journal cut、六个实际签名槽位和首次 Root acceptance / typed ACK 已有相互一致的留存 DATA。**原整体测试仍 FAIL**：其后检查 C 的原 Generation owner 时，`is_drained` 为 false。冷重启 D、完整退休后 acceptance、最终 FinalUse 的资格不能由本报告授予。

这是原 `EvaluatedNoUpdate` 测试场景。它用一个 28 参数的 Q24 控制模型和明确的文件存在/不存在业务契约检查拒用较差候选的路径；不是 E1/E2 的 LLM 泛化测量，也不是综合 foundation model 已形成的证明。

本审查只读取已经封存的原字节，执行独立 DATA 布局、SHA、字段和有限集合一致性检查。**新增模型 forward、optimizer、Rust/native、签名验证、host 访问均为 0。** 这不等于原父没有训练或推理。原父的完整模型调用数、全部 FLOPs、能源与货币成本在本审查中保持未计算。

## 1. 原件与来源

- 原源码：`dbd6a00992b60f4b33e8f10c2defda031d123bcb`；tree `fe037f5b6617fb647d416e0523685fa4ce08ef2f`。
- 原 15,812 文件 source inventory 的 canonical SHA：`20fe46de4b63f5a2bcce469113ebe27b7514f942c7f960a71e4dabaa4f643d0f`。
- 封存 archive：`e6_diagnostic_host_archive_readback_1/retained/original-evidence.tar.xz`，3,201,316 B，SHA `561f8f855db8776bdfb7feb7a13c52703df1492cf8355d83b7549519fc2f7e10`。
- 物理映射：`e6_diagnostic_host_archive_readback_1/verification-1/PHYSICAL_RESTORE_MAP.json`，SHA `0f657a2c990364cc151c11e044c36d1e2ae32d67d3b016d01594d74279f9b98d`。652 个原物理文件为 635 份新业务正文、5 份 C 原件和 12 份 stdio；12 个密钥只有另一层 metadata，未读正文。
- 本报告的 source-only 前置计划在 `../e6_noupdate12_training_business_review_1/`，原 manifest `6ac822f676578f470a49386a329314bb903a95badda9c56d3d46530c9a47b8e4` 未改。

每一实际读取均先核对映射中的长度和 SHA。`phase1/CONSUMED_INPUTS.json` 与 `phase2_v2/CONSUMED_INPUTS.json` 保留精确原路径和本云原字节映射。没有打开 SQLite，因此归档 DB/WAL/SHM 未因数据库读取而变化。未展开的环境子树、匿名 FD 报告不可回收及非原子整机快照的限制继续保留。

## 2. 真正变化的权重与 Training

三方实际一致：原 `training.journal` 完成记录内的 HQ24TRES heads、Root 留存的 `independent-b/original-candidate.data` 和 Training receipt 的 heads component SHA 均为 `db9b556b8f46d8f69667016ae9131afef5cba2a980038cb07b651f0c07116c90`，172 B。原 baseline heads 为 `77d98407da42e3a9ac90ec6c441843f9d9a74b188b3130c658df7fa9f1383763`。

| 实际项 | 留存结果 |
|---|---:|
| base / encoder | 各 2×2，原 bytes 不变 |
| heads | 10×2，20 个参数 |
| 三个矩阵总参数 | 28 |
| 真实变化的坐标 | 2 |
| head[0,0] | 1 → 1.734375（Q24：16777216 → 29097984） |
| head[0,1] | 0 → 0.18359375（Q24：0 → 3080192） |
| 原 optimizer steps | 2 |
| 原 Dataset receipt | 1 行，132 B |
| 原 fit metrics elapsed | 2,010 μs |
| 原 Training receipt | 2 steps，3 ms，172 B |
| 原平方误差总量，Q48 除以 2^48 | 1 → 0.048279762268066406 |

3 ms 是原代码对 2,010 μs 的 `div_ceil(1_000).max(1)`，并非重新计时。2,010 μs 是原 fit 记录的局部范围，不能当作完整训练服务、整个 E6 或能源成本。原预算仍为最多 8 行 / 65,536 B / 8 training steps / 2,000 ms / 1,048,576 artifact bytes；本审查未改变这些数值。

Training journal/witness 的完整帧消费、顺序和末 anchor 相等；HQ24TRES 的 binding、候选 bundle、batch/update 摘要与实际 receipt 的证据摘要一致。这证明留存字节中确有实际候选变化，不把匿名 Source report 重新拼出后冒称原件。细节见 [TRAINING_WEIGHTS.json](phase1/TRAINING_WEIGHTS.json)、[CHECKPOINT_TRAINING_RELATIONS.json](phase1/CHECKPOINT_TRAINING_RELATIONS.json) 和 [ACK_BINDING_READOUT.json](phase2_v2/ACK_BINDING_READOUT.json)。

## 3. B 为什么保留基线

B 的 Root 副本与独立业务目录 `original-source.data` 逐字相同。完整被捕获的 B 业务目录有 405 份文件：272 个 evidence、130 个实际 requested 文件，以及 source/policy/observer 三份文件。272 个 evidence 与所有存在的 requested payload 均逐件校验。`skip` 的缺件判断只在已完整捕获的原 B 目录范围内成立，不是对主机进行新观察。

| 原观察 | persist | skip |
|---|---:|---:|
| 较早的 B predictor/control 训练观察 | 8 | 8 |
| 独立 heldout 的 256 个原行为抽样 | 122 | 134 |

候选模型的原策略为 `persist`，基线为 `skip`，原行为概率各 1/2。这项 `EvaluatedNoUpdate` 阴性业务 fixture 的契约是“requested 文件不存在才成功”，因此所有 persist 原观察的 outcome 为 0，所有 skip 为 1。16 个较早 B 观察属于评估器的预测/控制训练材料，不能加到候选 SGD 的 1 行 Dataset 中。

| 原存量估计字段 | 候选 | 基线 |
|---|---:|---:|
| rows / clusters | 256 / 256 | 256 / 256 |
| IPS | 0 | 1.046875 |
| SNIPS | 0 | 1 |
| doubly robust | 0 | 1 |
| ESS | 122 | 134 |
| maximum observed weight | 2 | 2 |
| 原 IPS interval | [-0.2338535886, 0.2338535886] | [0.8130214114, 1.2807285886] |

IPS 是重要性加权估计，不是成功比例，故基线 1.046875 不应被改写成“104.7% 的实际成功率”。这些区间从封存的 HPEXR001 中解码，未重跑估计或重新发放统计资格。预注册的唯一 primary metric 为 maximize IPS、最低 improvement 为 0、safety floor 为 0、family alpha 为 50,000 ppm。候选未优于基线，与原实际 Evaluation `NoUpdate` 和后续选择原 bundle 一致。

实际 policy payload 不含 outcome 字段，其字节摘要可从冻结 policies 重新构造；policy `issued_at=1795183199`，所有 heldout outcome 与 Observer `issued_at=1795183200`。主体为 `ordinary-trainer` 与 `ordinary-independent-b-observer` 两个不同角色。这一段只校验留存 payload/hash/时序字段；原签名真实性、current trust 与角色权限属于原 native 路径，本审查没有重新验证它们。见 [B_SOURCE_BUSINESS_READOUT.json](phase2_v2/B_SOURCE_BUSINESS_READOUT.json)、[B_ALL_272_BUSINESS_ROWS.json](phase2_v2/B_ALL_272_BUSINESS_ROWS.json)、[B_STORED_EXECUTION_METRICS.json](phase2_v2/B_STORED_EXECUTION_METRICS.json)。

## 4. 六阶段、首次 acceptance 与 ACK

实际 terminal 顺序：Experience → Dataset → Training → Evaluation(NoUpdate) → Selection → RetainedModelNextUse。最后的 state partition 为 `ordinary-original-c`，保留 bundle 为 `9864e82c44d7add2b70595ab3539bf8a8b82723e1d13020f9524b97f1c71d6b7`；被评估候选 bundle 为 `6b6eb4249a9bbaf4063ae9be8b61f22979efd98ce4d20c0d14a013304a1cb40e`。

Root 首次 acceptance 留存 7 个 journal cut 和 6 个真实非 Proposal receipt 签名摘要。其 canonical DATA digest `e779ee5daa102696e65705ab42fe43b4517aaed5a0429dd09b8455272d99413c` 与实际 typed ACK 的 acceptance 字段相同；initial、frozen scope、terminal head、original task/data cut 亦逐字段相等。Completed-learning Refusal 留存 Ready / attempt 2。`root_verified_at_seconds=1795183232`，晚于全部 receipt（最晚 1795183225），早于原 envelope expiry 1795183435。

补充物理读回还逐个消费七对原 journal/witness：Completed record 数为 freeze 1、experience 1、dataset 1、training-receipt 2、local-decision 0、selection 1、next-use 1，七对末 anchor 均相等；delivery 的完成 payload 就是实际 terminal head。B publication 中候选 manifest 指向真实改变后的 heads，而 artifact-selection 指向的实际 payload SHA 与保留基线 heads/bundle 一致。见 [SUPPLEMENTAL_DATA_READOUT.json](SUPPLEMENTAL_DATA_READOUT.json)。这仍是静态物理 DATA 一致性，不是重新执行七 cut 的活体前后检查或签名验证。

接受的 checkpoint digest 为 `fa55673f89a6b423a4d85229df6d40b35b35ab87204268ef899af686a1f4fcf7`，按原代码是 domain + canonical checkpoint frontier JSON 的 SHA，**不是裸 snapshot 二进制 SHA**。phase1 探索性裸二进制比较的 false 原样保留；phase2_v2 使用确切契约得到相等，并单独解释差异。

原精确 parent 控制流在 C drain 断言之前已经返回：真实 Training / B 决策检查、terminal 观察、首次 acceptance 与 typed ACK 等待、原 daemon / Root 正常退出和 terminal 再读。这一控制流事实与物理 DATA 的字段吻合相互支持。它不替代原父失败后未执行的退休后 acceptance、cold D 或 FinalUse 验收。

## 5. 原失败、解析失败与未作推断

- 原 NoUpdate12 test 97.260 s，执行 98.31973223993555 s，1 FAIL / 0 skip；C drain 断言失败保留。没有将 trace request 64 单独当作接受成功。
- 本审查 `phase2/FAILURE.json` 是独立 DATA 解析器 v1 的错误：把 execution 签名 payload 误认为裸 body。精确 `product_execution.rs` 规定的是 domain + 4 B BE plan ID 长度 + ID + operation binding + SHA(body)。修正版为新 `decode_b_execution_data_v2.py` / `read_physical_phase2_v2.py`，完整 diff 和旧失败都在 [PHASE2_PARSER_CORRECTION.json](PHASE2_PARSER_CORRECTION.json)。没有更改原字节、重放 native 或伪造签名。
- 原 `local-decision.journal` 是已初始化的 72 B 空 journal，原 witness 仍在；它不是缺件，也不是伪造一个 LocalDecision 以凑七签名。原训练 receipt journal 还包含独立 B plan 的第二个完成项。
- FinalUse device claims 的 80 B 是两个 40 B epoch/nonce frame，notes 为 0 B；仅数量不能区分 A 与 C，更不能推导 D。A/C nonce/操作归属留给独立补充审查，不在本层冒称完整最终使用。
- 没有新模型执行；没有据 fixture 指标声称 LLM 泛化提升、自发神经组织或去中心化训练规模收益。完整模型调用数、MAC/FLOPs、电费和货币成本未重新测量。

## 原件索引

`READOUT_MANIFEST.json` 固定本层全部文件、源码/API 回读、两个解析阶段、原 v1 解析失败及修正。大业务正文不重复复制，依赖原 archive 和逐件映射。该 manifest 之外的后续 static Adopt 路线审查、FinalUse 归属补件或新 native 结果必须另建证据层。
