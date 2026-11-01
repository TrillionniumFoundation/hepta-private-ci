# V14 semantic 原始运行审计：没有达到候选净收益验收

第1—7节保留已经冻结并完成的原始 semantic 运行审计，记录不可覆盖的负结果和数据构造缺陷。第8节另列已完成的**同一留出集 bug 修复配对复核**，不能替代原记录、算作新的独立留出样本，或用于重新选择超参数。

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

必要修复限定为：保留原始96条数据和本轮全部结果，只将项目ID改为由固定salt与原请求语义正文生成的独立短码；正文、payload、expected、标签、组合、train/calibration、模型与超参数均不得改变。新protocol和manifest先提交，再进行同一任务的配对复核。新运行必须标注为bug修复复核，不能新增独立样本数、替换原负结果或在复核结果上选择超参数。原审计阶段尚无修复后结果；现另列于第8节。

以下保留修复准备阶段的记录；当时尚未在修复后的文本上运行任何模型。`semantic_holdout_labelcue_original.json` 和 `semantic_protocol_labelcue_original.json` 保留原文件字节；`semantic_project_ids.py` 仅以固定 salt `hepta-semantic-v14-project-cue-repair-v1` 与原语义正文生成八位十六进制短码；`semantic_project_id_mapping.json` 固定96个正文到ID的映射，不接收类别、行号、fixture或其他gold字段。七项契约检查验证原正文与非项目字段完全相同、组合不变、ID不受oracle元数据或行序影响、实际推理调用只传文本、训练／校准及六个模型／执行源码文件未变。契约检查只运行fixture与spy，未评估模型质量。

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

## 8. 同一留出集的项目 ID 修复配对复核

### 8.1 执行身份与验收结论

修复协议／数据先提交为 [`c991ad02f1cba86471cbba59c9756a678a18ecf7`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/c991ad02f1cba86471cbba59c9756a678a18ecf7)，随后 [Actions run 41261379136](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41261379136) 的三个实验及 preserve job 全部成功。证据保全提交是 [`58f1037f3850c834f49052e755f880a192406dfd`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/58f1037f3850c834f49052e755f880a192406dfd)，对应 [INDEX.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58f1037f3850c834f49052e755f880a192406dfd/qualification/memory-cell-v14/evidence/semantic-41261379136-1/INDEX.json)。原始结果和本节结果并列保留。此处仍是相同96条请求、相同12个组合、相同3个优化器种子，新增独立语言样本数为0。

**修复后仍未通过 P0 质量或净效用验收。** MiniLM ridge 为84/96，词法 ridge 为81/96；指定候选 LoRA 为35/39/58，MLP 为64/60/67，fast weights 为55/40/59。没有任何指定候选在任一种子上超过最强实际对照；也没有在任一预注册读取次数上超过该种子的最佳对照效用。

- Seed 17：[semantic_run.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58f1037f3850c834f49052e755f880a192406dfd/qualification/memory-cell-v14/evidence/semantic-41261379136-1/readable/v14-semantic-17-41261379136-1/semantic_run.json)、[process.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58f1037f3850c834f49052e755f880a192406dfd/qualification/memory-cell-v14/evidence/semantic-41261379136-1/readable/v14-semantic-17-41261379136-1/process.json)。
- Seed 29：[semantic_run.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58f1037f3850c834f49052e755f880a192406dfd/qualification/memory-cell-v14/evidence/semantic-41261379136-1/readable/v14-semantic-29-41261379136-1/semantic_run.json)、[process.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58f1037f3850c834f49052e755f880a192406dfd/qualification/memory-cell-v14/evidence/semantic-41261379136-1/readable/v14-semantic-29-41261379136-1/process.json)。
- Seed 43：[semantic_run.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58f1037f3850c834f49052e755f880a192406dfd/qualification/memory-cell-v14/evidence/semantic-41261379136-1/readable/v14-semantic-43-41261379136-1/semantic_run.json)、[process.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/58f1037f3850c834f49052e755f880a192406dfd/qualification/memory-cell-v14/evidence/semantic-41261379136-1/readable/v14-semantic-43-41261379136-1/process.json)。

三个runner均通过全部7项契约，核对的holdout、protocol与ID映射哈希均为第6节预先冻结的值。全部六份JSON及六个原／配对checkpoint归档均按Git blob、归档分片SHA256及INDEX中的文件哈希核验；审计没有重训模型或在本地运行模型质量评估。

### 8.2 全部14臂：原始与修复后结果

单步列按种子17 / 29 / 43列出，每个分母都是96；组合列分母为12。相同种子下逐题比较，不能将两轮合计成192条独立请求。

| 方法 | 原始单步成功数 | 修复后单步成功数 | 修复后描述均值 | 修复后组合成功数 |
| --- | --- | --- | --- | --- |
| `exact_kv` | 2 / 2 / 2 | 2 / 2 / 2 | 2.08% | 0 / 0 / 0 |
| `bm25` | 67 / 67 / 67 | 67 / 67 / 67 | 69.79% | 9 / 9 / 9 |
| `kv_bm25` | 67 / 67 / 67 | 67 / 67 / 67 | 69.79% | 10 / 10 / 10 |
| `lexical_ridge` | 81 / 81 / 81 | 81 / 81 / 81 | 84.38% | 12 / 12 / 12 |
| `bert_nearest` | 53 / 53 / 53 | 56 / 56 / 56 | 58.33% | 7 / 7 / 7 |
| `bert_centroid` | 60 / 60 / 60 | 63 / 63 / 63 | 65.62% | 7 / 7 / 7 |
| `bert_ridge` | 62 / 62 / 62 | 62 / 62 / 62 | 64.58% | 6 / 6 / 6 |
| `bert_linear` | 63 / 58 / 54 | 68 / 60 / 59 | 64.93% | 6 / 6 / 5 |
| `bert_mlp` | 59 / 53 / 63 | 64 / 60 / 67 | 66.32% | 4 / 6 / 6 |
| `bert_fast_weights` | 50 / 42 / 60 | 55 / 40 / 59 | 53.47% | 5 / 3 / 6 |
| `bert_lora` | 31 / 33 / 55 | 35 / 39 / 58 | 45.83% | 6 / 5 / 5 |
| `minilm_nearest` | 82 / 82 / 82 | 80 / 80 / 80 | 83.33% | 8 / 8 / 8 |
| `minilm_centroid` | 83 / 83 / 83 | 81 / 81 / 81 | 84.38% | 12 / 12 / 12 |
| `minilm_ridge` | 85 / 85 / 85 | 84 / 84 / 84 | 87.50% | 12 / 12 / 12 |

所有42组“方法×种子”的组合输出与原轮完全相同，因为组合步骤文本没有项目ID修改。单步BERT方法对项目干扰词较敏感；例如LoRA分别有7/17/12题由错变对、3/11/9题由对变错。词法ridge的全部预测保持不变，MiniLM ridge每个种子都是1题由错变对、2题由对变错。下面的数值复现检查说明，这些差异不能被称为严格固定权重的ID因果效应。

### 8.3 训练选择相同，但跨runner权重不逐位相同

六个训练／模型／成本／数据源码文件、依赖版本、训练与校准数据、基础BERT tensor hash和全部神经初始化hash均与原轮一致。所有基线候选的校准历史与选择值一致；27个神经候选的完整校准预测和执行输出也一致。选中步骤如下，两轮相同：

| 方法 | Seed 17 | Seed 29 | Seed 43 |
| --- | --- | --- | --- |
| BERT linear | 160 | 80 | 160 |
| BERT MLP | 160 | 320 | 160 |
| BERT LoRA | 80 | 80 | 320 |

然而，9个已选神经模型的参数tensor hash和optimizer tensor hash都与原轮不同。这里比较的是tensor原始数值的hash，不是受protocol元数据影响的checkpoint文件hash。审计直接读取已保全的27对PyTorch checkpoint tensor payload，用NumPy重算hash并与运行receipt匹配；已选模型的真实数值差如下：

| 方法 | 已选参数最大绝对差：17 / 29 / 43 | 已选校准概率最大绝对差：17 / 29 / 43 |
| --- | --- | --- |
| `bert_linear` | 4.619e-07 / 2.310e-07 / 5.700e-07 | 5.364e-07 / 4.172e-07 / 7.749e-07 |
| `bert_mlp` | 5.886e-07 / 2.116e-06 / 1.356e-06 | 9.537e-07 / 2.235e-06 / 5.364e-07 |
| `bert_lora` | 1.490e-06 / 2.524e-07 / 6.706e-07 | 9.835e-07 / 1.073e-06 / 2.742e-06 |

全部记录训练loss的最大跨轮差为4.768×10⁻⁷；已选optimizer tensor最大绝对差为8.196×10⁻⁸。基线也出现微小数值变化：词法ridge≤2.113×10⁻¹⁴、BERT ridge≤3.622×10⁻⁷、MiniLM ridge≤8.830×10⁻⁹。跨runner浮点计算路径差异是与这些观测相容的解释，但没有记录CPU型号与底层kernel选择，不能宣称已定位唯一原因，也不能宣称跨机器逐位复现。

每个运行内部的42项checkpoint恢复验证仍全部通过。这建立了各自模型的准确恢复性，与两次独立训练之间逐位相同是不同的要求。因此，本轮是预先冻结的同任务配对重跑和cue修复敏感性复核；它没有通过“同一权重、仅替换ID”的严格因果隔离条件。质量与效用验收仍是明确的负结果，不能用很小的浮点差为大幅落后的候选制造成功声明。

修复后同一模型内部的LoRA干预结果为：开启35/39/58，关闭LoRA但保留训练reader为34/32/15，全部可训练参数重置为6/9/10。该干预证明LoRA更新实际参与了决策；与强对照的采用收益仍未建立。

### 8.4 修复后的服务账与Q敏感性

费用公式、独立部署的完整基础模型收费、共享模型只在实际共用时收取一次、所有训练候选与恢复成本、48次顺序query计时等边界与第4节相同。持久化总字节逐臂与原轮相同；下面只补充实际发生变化的时间项。

| 方法 | 启动、写入、候选选择、恢复合计秒：17 / 29 / 43 | 单query均值毫秒：17 / 29 / 43 |
| --- | --- | --- |
| `exact_kv` | 0.003687 / 0.002864 / 0.003491 | 0.039872 / 0.031117 / 0.037157 |
| `bm25` | 0.032898 / 0.024149 / 0.026756 | 0.563725 / 0.403319 / 0.439898 |
| `kv_bm25` | 0.032872 / 0.023977 / 0.026888 | 0.557446 / 0.404907 / 0.438716 |
| `lexical_ridge` | 0.155372 / 0.112759 / 0.131488 | 1.173436 / 0.836752 / 1.077584 |
| `bert_nearest` | 0.864826 / 1.054946 / 1.170442 | 1.514298 / 1.085996 / 1.233264 |
| `bert_centroid` | 0.859947 / 1.051789 / 1.160930 | 1.479048 / 1.077190 / 1.223633 |
| `bert_ridge` | 0.863234 / 1.054138 / 1.164154 | 1.488632 / 1.063397 / 1.238732 |
| `bert_linear` | 1.062806 / 1.191089 / 1.300385 | 1.466518 / 1.087551 / 1.196386 |
| `bert_mlp` | 1.130285 / 1.248392 / 1.373920 | 1.509105 / 1.094333 / 1.237054 |
| `bert_fast_weights` | 0.881834 / 1.066852 / 1.177841 | 1.499215 / 1.073192 / 1.237797 |
| `bert_lora` | 4.949135 / 5.036478 / 3.764589 | 1.809648 / 1.346158 / 1.468771 |
| `minilm_nearest` | 2.171712 / 2.656282 / 3.453126 | 5.429791 / 4.642322 / 3.716679 |
| `minilm_centroid` | 2.168659 / 2.651592 / 3.440302 | 5.277507 / 4.603923 / 3.684275 |
| `minilm_ridge` | 2.179692 / 2.665579 / 3.462508 | 5.242606 / 4.761362 / 4.002050 |

下表仍是同一96条请求下三个优化器种子的描述均值，不代表独立任务重采样。

| Q | MiniLM ridge 对照 | 词法 ridge 对照 | LoRA 候选 | MLP 候选 | Fast weights 候选 |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.84717597 | 0.84240697 | 0.41246688 | 0.65065601 | 0.52427094 |
| 10 | 0.87217558 | 0.84360643 | 0.45373281 | 0.66192908 | 0.53366566 |
| 100 | 0.87467554 | 0.84372638 | 0.45785941 | 0.66305639 | 0.53460514 |
| 1000 | 0.87492554 | 0.84373837 | 0.45827207 | 0.66316912 | 0.53469908 |
| 10000 | 0.87495054 | 0.84373957 | 0.45831333 | 0.66318039 | 0.53470848 |

单个种子中，Q=1时seed43由更便宜的词法ridge取得最高效用，其余种子／Q组合由MiniLM ridge取得最高效用。各指定候选在全部15个种子×Q场景中都低于最佳对照。LoRA相对MiniLM ridge的纯时间break-even约807、695、120次读取；它们不是质量或总效用的break-even。不同runner的时延与下载速度也不同，本表是已执行场景的服务账，不能据此推断普遍硬件性能排序。

### 8.5 新增进程成本及严格去重累计

| 种子 | exit | command wall秒 | child CPU秒 | peak RSS字节 | runner RX / TX字节 |
| --- | --- | --- | --- | --- | --- |
| 17 | 0 | 16.392281569 | 24.695844 | 672923648 | 223356374 / 737916 |
| 29 | 0 | 15.678920649 | 22.086679 | 675037184 | 223399082 / 823532 |
| 43 | 0 | 14.919196288 | 18.398725 | 670892032 | 223741556 / 1336488 |

本轮新增command wall **46.990398506秒**、child CPU **65.181248秒**。计入六个language进程、原始三个semantic进程及本次三个semantic进程，按run+seed去重后的这条实验轨道已知累计为wall **199.960275605秒**、CPU **299.247398秒**。每份paired结果嵌入的152.969877099秒prior只计一次。

新增runner接口观测合计RX 670,497,012字节、TX 2,897,936字节，仍包含其他runner流量。V13完整历史、安装／checkout／preserve外围时间、能耗和真实云账单继续保留为未知；此累计不是整个Hepta项目的所有历史成本。同期另一个language/routing workflow的科学任务全部skipped，不虚构重训成本，其changes/checkout外围开销也不在实验子进程receipt内。

冻结运行时使用的`semantic_prior_costs.json`没有在结果出来后回写，以免触发无必要的新实验，也避免改写本轮实际使用的输入账。完整去重条目、原／配对各项比对及真实权重差已保存于同目录`SEMANTIC_PAIRED_AUDIT.json`，其未知历史条目仍为null。

### 8.6 配对原始JSON身份

| 文件 | SHA256 |
| --- | --- |
| seed-17/semantic_run.json | `1a3e7cffadc4b6f78e520fa08d88379824366195794335254e262da864d257c8` |
| seed-17/process.json | `2d484108e5d191588c90832e931b6cf35d1c793e020795590b2651f9c61ae733` |
| seed-29/semantic_run.json | `2d4f8df185a6f2947a9709307071563ddc895c884dde7790631979f623837ad8` |
| seed-29/process.json | `ebca27440f743f0fd4ac0c848ff8abaa5dcb36aaf9e477131d3fcb7fb90f0e2f` |
| seed-43/semantic_run.json | `c62bf36a849a54c5698b76b9145ce8a671643f802b55bf9fbf62d0f7923751e8` |
| seed-43/process.json | `6516ed027f4c01b971b14155d029c9394685e37a18a36c8608a70a8bb72a419c` |

以上数据均来自保全的原始bytes；模型与优化器检查点保存在同一INDEX所列的六个原／配对归档中。修复消除了已知的显式编号cue，尚未建立新独立留出集上的泛化或候选正收益。
