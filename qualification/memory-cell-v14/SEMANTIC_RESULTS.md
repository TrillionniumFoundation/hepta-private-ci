# V14 semantic 原始运行审计：没有达到候选净收益验收

本报告只审计已经冻结并完成的原始 semantic 运行，记录不可覆盖的负结果和数据构造缺陷。后续去除项目名显式标签线索的运行必须作为**同一留出集的 bug 修复配对复核**另列，不能替代本记录、算作新的独立留出样本，或用于重新选择超参数。

## 1. 结论和证据身份

三个事先指定候选 `bert_lora`、`bert_mlp`、`bert_fast_weights` 均未在任何一个种子上超过最强实际对照 `minilm_ridge`；在预注册的 Q=1、10、100、1000、10000 读取场景中，也均未超过最强对照的净效用。较便宜的 `lexical_ridge` 同样在三个种子上超过全部三个候选。**本轮 P0 质量路线和净效用路线均未通过。** 最强对照保持对照身份，没有在看过结果后被重命名成成功的研究候选。

- 实验源码提交：[完整 `5e2561adeeae4237542e39e57f36e0096536df75`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/5e2561adeeae4237542e39e57f36e0096536df75)。
- Actions：[run 41260194939](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41260194939)，三个 semantic job 和 preserve job 均为 success；实验子进程均 exit 0。
- 证据保全提交：[完整 `cb32b3b290b894ded7d8f63e7da0262c70f6692e`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/cb32b3b290b894ded7d8f63e7da0262c70f6692e)。
- [预注册协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5e2561adeeae4237542e39e57f36e0096536df75/qualification/memory-cell-v14/semantic_protocol.json)、[原始 holdout](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5e2561adeeae4237542e39e57f36e0096536df75/qualification/memory-cell-v14/semantic_holdout.json)、[数据清单](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5e2561adeeae4237542e39e57f36e0096536df75/qualification/memory-cell-v14/semantic_manifest.json)、[归档 INDEX](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb32b3b290b894ded7d8f63e7da0262c70f6692e/qualification/memory-cell-v14/evidence/semantic-41260194939-1/INDEX.json)。
- 协议 canonical SHA256：`ca780c0444e116b1bdfcfdb237b29cff3ae52f14c4ee2e8415e477361bf7791f`。
- 原始 holdout canonical SHA256：`36d87fb2f4dc05967fe5868f52dfbd0ce208be0173e8fb17783e4e3f167edea1`。

- Seed 17: [semantic_run.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb32b3b290b894ded7d8f63e7da0262c70f6692e/qualification/memory-cell-v14/evidence/semantic-41260194939-1/readable/v14-semantic-17-41260194939-1/semantic_run.json); [process.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb32b3b290b894ded7d8f63e7da0262c70f6692e/qualification/memory-cell-v14/evidence/semantic-41260194939-1/readable/v14-semantic-17-41260194939-1/process.json).
- Seed 29: [semantic_run.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb32b3b290b894ded7d8f63e7da0262c70f6692e/qualification/memory-cell-v14/evidence/semantic-41260194939-1/readable/v14-semantic-29-41260194939-1/semantic_run.json); [process.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb32b3b290b894ded7d8f63e7da0262c70f6692e/qualification/memory-cell-v14/evidence/semantic-41260194939-1/readable/v14-semantic-29-41260194939-1/process.json).
- Seed 43: [semantic_run.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb32b3b290b894ded7d8f63e7da0262c70f6692e/qualification/memory-cell-v14/evidence/semantic-41260194939-1/readable/v14-semantic-43-41260194939-1/semantic_run.json); [process.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb32b3b290b894ded7d8f63e7da0262c70f6692e/qualification/memory-cell-v14/evidence/semantic-41260194939-1/readable/v14-semantic-43-41260194939-1/process.json).

独立审计从 GitHub connector 获取原始 base64 内容，直接解码写入字节，没有追加 newline。六个 JSON 的 Git blob SHA 和归档 INDEX 中的 SHA256 均通过核验。运行记录的源码哈希也逐项与本地同版本文件一致。以下数字来自这些原始 JSON，未重跑模型、未调参。

## 2. 同信息比较范围与完整结果

训练仅使用 V13 冻结的 120 条 train；候选选择仅使用已有 48 条 calibration。新任务包含 12 种注册技能的 96 条手工请求及 12 个公开步骤分解的组合。选择器只取得 raw text；实际 payload 交给共同执行器。执行器执行 CSV/JSON、Unicode、序列处理等既有算法；测量的是技能选择和组合利用，不是算法学习、代码合成或自主发现计划。

三个种子为 17、29、43，使用**相同的96条请求**。表中的均值是初始化／优化器种子的描述性均值，不能当作288条独立语言样本或三个独立任务数据集。统计推断必须保留请求及技能分组的配对关系。

| 方法 | 角色 | 单步成功数：17 / 29 / 43（各96） | 三种子描述均值 | 组合成功数：17 / 29 / 43（各12） |
| --- | --- | --- | --- | --- |
| `exact_kv` | 对照 | 2 / 2 / 2 | 2.08% | 0 / 0 / 0 |
| `bm25` | 对照 | 67 / 67 / 67 | 69.79% | 9 / 9 / 9 |
| `kv_bm25` | 对照 | 67 / 67 / 67 | 69.79% | 10 / 10 / 10 |
| `lexical_ridge` | 对照 | 81 / 81 / 81 | 84.38% | 12 / 12 / 12 |
| `bert_nearest` | 对照 | 53 / 53 / 53 | 55.21% | 7 / 7 / 7 |
| `bert_centroid` | 对照 | 60 / 60 / 60 | 62.50% | 7 / 7 / 7 |
| `bert_ridge` | 对照 | 62 / 62 / 62 | 64.58% | 6 / 6 / 6 |
| `bert_linear` | 对照 | 63 / 58 / 54 | 60.76% | 6 / 6 / 5 |
| `bert_mlp` | 事先指定候选 | 59 / 53 / 63 | 60.76% | 4 / 6 / 6 |
| `bert_fast_weights` | 事先指定候选 | 50 / 42 / 60 | 52.78% | 5 / 3 / 6 |
| `bert_lora` | 事先指定候选 | 31 / 33 / 55 | 41.32% | 6 / 5 / 5 |
| `minilm_nearest` | 对照 | 82 / 82 / 82 | 85.42% | 8 / 8 / 8 |
| `minilm_centroid` | 对照 | 83 / 83 / 83 | 86.46% | 12 / 12 / 12 |
| `minilm_ridge` | 对照 | 85 / 85 / 85 | 88.54% | 12 / 12 / 12 |

本轮实际执行成功率与标签准确率在每个臂上相同。显式组合只有12例；词法 ridge、MiniLM centroid/ridge 全部完成12/12，LoRA 为6/12、5/12、5/12，不能以单步参数学习替代组合验收。

同 BERT 比较也没有稳定增益：BERT ridge 固定为62/96，LoRA 为31/96、33/96、55/96；MLP 只有种子43比 ridge 多1题，另两个种子更差；fast weights 三次都低于 ridge。因而结论并不只依赖更大的 MiniLM 编码器。

MiniLM ridge 自身也有监督拟合的参数分类头。因此，本轮结果不能概括为“所有参数记忆都输给检索”；它准确支持的是：本轮预先指定的 LoRA、MLP 和 fast-weight 候选没有超过已纳入比较的最强实际实现。

针对 MiniLM ridge，LoRA 在三个配对请求集上分别出现「候选对、对照错」2/3/2题，而「候选错、对照对」56/55/32题。当前候选未达到正收益验收；这不构成所有参数记忆架构不可行的证明。

## 3. LoRA 真实性、因果干预与恢复

BERT 来源是固定的 `google/bert_uncased_L-2_H-128_A-2`，revision `30b0a37ccaaa32f332884b96992754e246e48c5f`，safetensors SHA256 `7fb69ad9f6866d8983183c930e33828f326470bf6ad8bbb2ad4ed957a92e9414`。全部 BERT feature 控制使用同一冻结模型的 CLS 特征。LoRA 在两层 attention 的 query/value 投影上更新真实 rank-4 增量，alpha=8；其训练参数5644个，MLP 4524个，线性 reader 1548个。LoRA 与线性控制使用相同初始线性 reader；完整模型并未随机初始化。

| 干预 | Seed 17 / 96 | Seed 29 / 96 | Seed 43 / 96 |
| --- | --- | --- | --- |
| LoRA 开启，已训练 reader | 31 | 33 | 55 |
| LoRA 关闭，保留同一个已训练 reader | 34 | 34 | 13 |
| 全部可训练参数重置到初始值 | 8 | 8 | 9 |

这表明可训练参数实际影响了行为，但没有给出稳定净收益：前两个种子启用 LoRA 比禁用分别少3题、1题，第三个种子多42题。不能把“参数被使用”直接等同于“参数记忆比强对照更好”。全部可训练参数重置会同时移除 reader 的学习，故该干预并不单独定位 LoRA 内部储存的知识量。

旧 calibration 选择 LoRA 的累计步骤为80、80、320；选择规则未读取新 holdout。三条训练轨迹的最后 minibatch 损失均降至约0.004–0.005，但 calibration 成功率没有随训练持续下降的损失稳定提高。所有80/160/320候选的参数、优化器与校准输出均已保存，而非只保留赢家。42个“方法×种子”恢复检查全部报告逐位预测一致；LoRA 基础模型冻结哈希检查没有失败。优化器 tensor hash 与实际 checkpoint 一同保留。

这些检查建立真实训练、固定基础模型和可恢复执行的工程证据；尚未验收的是采用收益。

## 4. 服务成本、共享模型与读取次数敏感性

下表是各方法独立部署时的预注册本地CPU服务账。`startup_write_seconds` 包括模型获取／缓存检查与加载、真实训练及校准编码、全部搜索候选、序列化、选择与恢复核验。持久化字节包括基础模型文件、source、该臂保留的 checkpoint；神经臂保留全部三个候选，基线保存选中状态和全部候选的校准记录。单query计时为48个顺序请求，包含必要的 tokenizer/encoder、读取以及共同执行器；错误调用也计时。

| 方法 | 获取、写入、校准、恢复合计秒：17 / 29 / 43 | 持久化总MB（十进制） | 单query均值毫秒：17 / 29 / 43 |
| --- | --- | --- | --- |
| `exact_kv` | 0.0027 / 0.0037 / 0.0022 | 0.084203 | 0.024 / 0.039 / 0.031 |
| `bm25` | 0.0178 / 0.0318 / 0.0183 | 0.103173 | 0.303 / 0.558 / 0.305 |
| `kv_bm25` | 0.0179 / 0.0311 / 0.0177 | 0.103176 | 0.310 / 0.561 / 0.295 |
| `lexical_ridge` | 0.0807 / 0.1510 / 0.0820 | 0.722940 | 0.534 / 1.162 / 0.533 |
| `bert_nearest` | 0.9173 / 0.8687 / 0.9910 | 18.178195 | 0.710 / 1.452 / 0.700 |
| `bert_centroid` | 0.9137 / 0.8652 / 0.9886 | 18.067595 | 0.688 / 1.434 / 0.774 |
| `bert_ridge` | 0.9156 / 0.8685 / 0.9902 | 18.067913 | 0.712 / 1.456 / 0.709 |
| `bert_linear` | 1.0131 / 1.0673 / 1.0771 | 18.113686 | 0.674 / 1.460 / 0.680 |
| `bert_mlp` | 1.0456 / 1.1425 / 1.1153 | 18.226526 | 0.710 / 1.522 / 0.682 |
| `bert_fast_weights` | 0.9254 / 0.8880 / 0.9989 | 18.067855 | 0.711 / 1.485 / 0.692 |
| `bert_lora` | 3.5048 / 4.8667 / 3.9997 | 18.287461 | 0.861 / 1.797 / 0.923 |
| `minilm_nearest` | 3.7019 / 3.0790 / 3.2713 | 91.326049 | 2.573 / 4.934 / 2.735 |
| `minilm_centroid` | 3.7365 / 3.0759 / 3.2540 | 90.994265 | 2.550 / 4.950 / 2.712 |
| `minilm_ridge` | 3.7063 / 3.0861 / 3.2494 | 90.994583 | 2.673 / 4.923 / 2.726 |

BERT 臂按自身部署计入约17.97MB的基础模型文件；MiniLM 臂计入约90.87MB模型与tokenizer等文件，未把90MB编码器隐藏在免费共享特征后面。不同方法使用同一基础模型时，表中独立部署账各自完整收费；若实际共同部署，基础模型可以共享一次，不能再把这些独立部署账相加并称为物理开销。已经驻留的编码器可产生另一种边际成本口径，但本轮主要验收使用表中的完整启动口径。

计时记录的模型获取项是本次实际 download/cache-check；不能推广成每个部署都必定发生的冷网络成本。持久化文件字节也不等于独立服务RAM驻留；本轮 peak RSS是整个实验进程的测量，未逐臂隔离测量RAM机会成本。保留未选中检查点属于本研究的审计／版本保留策略，不能冒称已经优化到最小推理部署包。

预注册效用为每次请求的正确收益减去时间与存储价格：

`U(Q) = task_success - 0.01 * (startup_write_seconds / Q + mean_query_seconds) - 0.001 * (retained_bytes / 2^30) / Q`。

时间价格和GiB-hour价格是预先固定的研究权重，不是实测电费或云账单；存储窗口为一小时。下表为三个优化器种子的描述性均值：

| 读取次数 Q | MiniLM ridge 对照 | 词法 ridge 对照 | BERT LoRA 候选 | BERT MLP 候选 | BERT fast weights 候选 |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.85182473 | 0.84269627 | 0.37192777 | 0.59660095 | 0.51837679 |
| 10 | 0.88202651 | 0.84363794 | 0.40905703 | 0.60652635 | 0.52682902 |
| 100 | 0.88504669 | 0.84373211 | 0.41276996 | 0.60751889 | 0.52767424 |
| 1000 | 0.88534870 | 0.84374152 | 0.41314125 | 0.60761815 | 0.52775876 |
| 10000 | 0.88537890 | 0.84374246 | 0.41317838 | 0.60762807 | 0.52776721 |

不仅均值如此，每个种子、每个预注册Q的赢家都是 MiniLM ridge 对照。LoRA 相对 MiniLM ridge 的纯时间 break-even 为0、约570、约417次读取，但时间 break-even不满足质量条件；LoRA大量多出的错误使上述净效用在所有Q上仍更低。不能挑选“读取更快”替代任务收益验收。

## 5. 真实进程账与既往探索成本

| 种子 | exit | command wall秒 | child CPU秒 | child peak RSS字节 | runner RX / TX字节 |
| --- | --- | --- | --- | --- | --- |
| 17 | 0 | 12.688593096 | 14.317223 | 675467264 | 224100278 / 1908512 |
| 29 | 0 | 16.868021103 | 24.025280 | 674742272 | 223463030 / 939602 |
| 43 | 0 | 13.485409759 | 15.820344 | 671391744 | 224095812 / 1955212 |

本轮三个command receipt合计：wall **43.042023958秒**，child CPU **54.162847秒**。这些是三个执行实例消耗之和，不是并行workflow从开始到结束的日历时长。所有网络接口观测合计RX **671,659,120字节**、TX **4,803,326字节**；receipt明确说明它包含同runner的其他流量，不能视作模型下载的独占网络字节。

旧的三个失败language运行和三个修复后运行已在cost-only ledger保留，合计wall **109.927853141秒**、CPU **179.903303秒**。和本轮三个command receipt合并、对旧账去重后，已知探索总量为wall **152.969877099秒**、CPU **234.066150秒**。不能把每个semantic JSON中重复出现的109.93秒旧账再次累计三遍，也不能只收费最终选中种子的实验。

| 既往运行 | 种子 | exit | command wall秒 | child CPU秒 |
| --- | --- | --- | --- | --- |
| [失败的 language run 41259326679](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41259326679) | 17 | 1 | 8.384919903 | 9.990632 |
| 同上 | 29 | 1 | 7.769580040 | 9.687413 |
| 同上 | 43 | 1 | 7.065135175 | 7.619121 |
| [修复后的 language run 41259642195](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41259642195) | 17 | 0 | 26.786047290 | 46.456317 |
| 同上 | 29 | 0 | 30.202923006 | 53.138807 |
| 同上 | 43 | 0 | 29.719247727 | 53.011013 |

V13完整历史探索总量仍缺失，保留为null。package安装、checkout和preserve job不在实验子进程receipt的计时边界内；energy/cloud_bill也为null。不能把已知子进程成本冒称该项目所有历史或所有云账单成本。缺失项不改变当前候选连质量路线也没有通过的观察。

## 6. 本轮发现的数据构造错误与修复边界

原始96条请求含 `For project Aurora-{label:02d}-{index:02d}:` 前缀。项目名显式编码了类别号，属于目标相关的构造线索，不能把它称作严格独立于标签的陌生实体分配。训练／校准中没有这种前缀，当前选择器源码也没有解析该映射；这仍是应修复的评估缺陷，尤其不允许将将来对这一编号的利用解读为语义泛化。

已检查实际推理边界：选择器得到 `[row["text"] ...]`；label、skill、expected、fixture_id均不进入feature构造或路由函数。组合选择器只接收step文字，`oracle_skills`用于独立fixture核对；实际组合执行并不把它传给选择器。此次显式cue来自query文本内部，因而仅剥离metadata并不能发现它。

必要修复限定为：保留原始96条数据和本轮全部结果，只将项目ID改为由固定salt与原请求语义正文生成的独立短码；正文、payload、expected、标签、组合、train/calibration、模型与超参数均不得改变。新protocol和manifest先提交，再进行同一任务的配对复核。新运行必须标注为bug修复复核，不能新增独立样本数、替换原负结果或在复核结果上选择超参数。修复后的结果尚不属于本报告。

这项修复已准备完成，尚未在修复后的文本上运行任何模型。`semantic_holdout_labelcue_original.json` 和 `semantic_protocol_labelcue_original.json` 保留原文件字节；`semantic_project_ids.py` 仅以固定 salt `hepta-semantic-v14-project-cue-repair-v1` 与原语义正文生成八位十六进制短码；`semantic_project_id_mapping.json` 固定96个正文到ID的映射，不接收类别、行号、fixture或其他gold字段。七项契约检查验证原正文与非项目字段完全相同、组合不变、ID不受oracle元数据或行序影响、实际推理调用只传文本、训练／校准及六个模型／执行源码文件未变。契约检查只运行fixture与spy，未评估模型质量。

- 修复后的 holdout canonical SHA256：`dae2bbc83c954a4dc8ebb1efceed95ed63eb5629390aae29cbd2983ae430d1a6`。
- 配对复核 protocol canonical SHA256：`1bdeb2425e6f72dd12a5614386ffd8171f1f5dce39465861830847c5d1739060`。
- ID映射 canonical SHA256：`f2efd392f9de411266e1aeea1f237d873e541b092e672bae71a4f53e8becd2c6`。

复核的prior-cost ledger另加入本轮三个原始semantic进程receipt，仅带成本与出处，不带预测或调参信号；已知prior总量因此为152.969877099 wall秒、234.066150 CPU秒。V13未知历史条目继续保留。须先提交这组协议与数据，再执行固定三个种子的原runner；本报告原始结果保持不可覆盖。

## 7. 字节级证据校验

| 文件 | SHA256 |
| --- | --- |
| seed-17/semantic_run.json | `0fa1685feb33887f1a6fe0e2b12814b955709a1a04aab8fff4eceac9dba66bf4` |
| seed-17/process.json | `7797a00fd737875a7461ff64dd23a503c818fb109ad4c69c8adb664383a22ff0` |
| seed-29/semantic_run.json | `3fdd9becb3e8973b4c9427f7e5956a4e5cf0dfdb0b93eef9825d1bae45d335f1` |
| seed-29/process.json | `bca7470c88f97517c6795fe4a738aeec2a884f1257b4b7361280d3a9857f6a8e` |
| seed-43/semantic_run.json | `a3ed474a1ed9e953ac8e21a77480a8ca89c027a56188aaf7bd693d02457f2b61` |
| seed-43/process.json | `2561848136e40c0442a276a6a878a8d1a4ed287124f3c8e319b4f4c3f8afef42` |

INDEX来源记录的source commit与运行记录一致。上述六个文件既匹配Git blob身份，也匹配归档清单的SHA256和字节数；本审计没有从结果重建或重新格式化原始JSON。
