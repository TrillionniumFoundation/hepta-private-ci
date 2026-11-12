# PERC trained observation: Python owner and native Cell execution, task benefit remains HOLD

**实际训练得到的选区 MLP 已进入普通 Python owner 的真实选区、捕获和冷读。这个固定 CORD panel 的任务结果为负，保持 `HOLD / NoUpdate`。** 在 11 个可评分任务中，learned 为 **1/11**，full OCR、公共特征规则和固定选区等强控制为 **4/11**。全部 12 个任务及其中 1 个 quality unknown 都保留；没有把 unknown 删除后宣布总体均值或净收益。

本记录分别给出工程接入、合成边界验证和真实任务比较。机器可读结果、各阶段源码 pin 及原文件 SHA 见 [ENGINEERING_SUMMARY.json](ENGINEERING_SUMMARY.json)。来源冻结证据由 [CORD_SOURCE_SUMMARY.json](CORD_SOURCE_SUMMARY.json) 单独维护；本记录没有改写它。

## 1. 真实 CORD 任务比较

来源固定为 `naver-clova-ix/cord-v2` revision `7f0115a4b758a71d6473b8d085751692da2fef98`，共 **24 TRAIN / 8 DEV / 12 confirmation**。002 的 32 个 TRAIN/DEV 来源完成，形成 **72 TRAIN pairs / 24 DEV pairs**；现有 `mlp_head.train_head` 实际执行 **200 次 optimizer updates**，没有不完整训练观测。选区 head 学习的是 continuation gain/cost，内容解码仍由 OCR 和固定词法规则完成。

主任务不公开目标矩形。每个 arm 的 12 次 actor execution 均完成，共保留 **84 条 actor records**。每个 arm 都有同一个任务的 quality unknown；这表示评价目标不可用，不能混同为 actor execution 失败。下表 `correct/11` 只描述已知 quality 的子集；**12 项总体 quality mean 与含 unknown 的配对均值仍为 `null`**。

| Arm | 可评分项正确数 | Quality unknown（12 项中） | 12 项调用 wall 总和（s） | 相对 full OCR |
|---|---:|---:|---:|---:|
| `learned` | 1/11 | 1 | 9.200741 | 1.987058× |
| `full_ocr` | 4/11 | 1 | 4.630334 | 1.000000× |
| `public_feature_rule` | 4/11 | 1 | 6.504806 | 1.404824× |
| `fixed_region` | 4/11 | 1 | 6.209381 | 1.341022× |
| `random_region` | 1/11 | 1 | 5.863629 | 1.266351× |
| `zero_visual` | 4/11 | 1 | 9.265383 | 2.001018× |
| `fixed_selection` | 4/11 | 1 | 10.739021 | 2.319276× |

评分规则是去除标点及前导零后的 ASCII 数字串精确一致，不是货币语义等价判定。表中时间是实际调用封套，包含各 arm 的执行和保留原件冷读。learned 额外冷读 head decision；这些时间不等于完整物理成本，也不代表隔离的神经计算耗时。

### 视觉、选区与编码的贡献

- **视觉输入干预确实改变了动作。** `zero_visual` 保留实际编码，随后把 64 个视觉输入置零，使用同一 frozen head 并执行所得动作。两者在 **7/12** 的任务上选区不同；**learned 相对 zero_visual** 在已知 quality 的任务中有 **3 项损失、0 项提升**，另有 1 个 unknown pair。损失任务为 `cord-v2-test-00003`、`cord-v2-test-00005`、`cord-v2-test-00010`。这证明此 panel 上视觉输入对选择有因果影响，同时显示影响未带来任务收益。该干预不是重新训练一个无视觉模型。
- **固定选择控制保留神经编码与 OCR 解码。** `fixed_selection` 选择 lower band；**learned 相对 fixed_selection** 的可评分正确数为 **1/11 对 4/11**，三个已知任务的质量差为负。
- **编码路径控制保持观察与解码一致。** `fixed_selection` 和 `fixed_region` 的 12 项 observation、selection、answer equality 检查全部通过。前者调用 wall 总和为后者的 **1.729484×**。差异覆盖模型加载、latent/wire 保留及冷读等编码路径，不能解释成纯神经算子的耗时。
- **学习型解码及其消融尚未运行。** 七个 arm 都使用 OCR 和固定规则。动态环境与专门的遮挡协议也未在本次执行。

### 后置 ROI oracle：单独的上界

主 actor 冻结后，另行运行 annotation-assisted ROI OCR。它保留 12 项，11 项完成、1 项 UNKNOWN；可评分正确数为 **5/11**，总体 quality mean 为 `null`。目标 ROI 来自私有评价信息，`fair_comparator=false`，只能作为 **oracle upper bound**，不放入上述七 arm 的公平比较或收益结论。原主报告生成时尚未运行 oracle；后续的 `CORD_SYNTHESIS.json` 明确纳入这一独立阶段。

## 2. 真实训练 head 经普通 CLI 产生真实效果

使用 002 的 head 原字节与 profile，在固定 TRAIN `cord-v2-train-00000` owner 的**完整副本**上运行 `cli-trained-choice`。原 store 已有 initial / upper / middle / lower 四个受控训练观察；本诊断仍只把 frozen initial prefix 交给选择器，因此属于 TRAIN 复用。

| 证据 | 实际结果 |
|---|---|
| Head schema | `perc1.acquisition-mlp-head.v1` |
| Head 原文件大小 | **88,087 B** |
| Head canonical-model SHA256 | `dd12c8183f6bf1efa26f51e2a09bb93650e7b5c333d473c1e010a59814f08465` |
| Head raw-file SHA256 | `2a7aa2549d8102fc033e5026b959c804d07ad5f1ae41a0d5d887bffc66668f5e` |
| Profile canonical SHA256 | `1340eaad3459a2980b6827bdd8b6f36bfd88537d8455a1340592875247b733f9` |
| 输入 | first / dense / flatten64，真实 initial owner receipt |
| 独立 `source-active` | **ACQUIRE → lower** |
| 新效果 | 源捕获回调 **1** 次；encoder 实际加载并完成 **1** 次 |
| 额度 | 总额度仍为 **8**；reserved **4 → 5**，remaining **4 → 3** |
| 独立 `source-decision-read` | 移走副本原外部 head 路径后，同一决策、同一 owner 状态；零新捕获和编码 |
| 独立 `source-read` | 同一所选 receipt，原件/wire 验证通过；零新捕获和编码 |

配置只改变 `state_dir`，原 grant、binding、model、catalog 和 budget 不变。原 TRAIN store 全文件字节，以及 `HEAD.json`、`PROFILE.json`、`PUBLIC_TASKS.json`、`PLAN.json`、该 TRAIN config 与完成标记六个 metadata 文件前后相同。这里没有把该校验扩写成所有外部 source/model 文件的全量不可变证明。

| 独立命令 | 命令 wall（s） | waited CPU（s） |
|---|---:|---:|
| `source-active` | 6.261855288 | 5.432519 |
| `source-decision-read` | 0.375785176 | 0.358431 |
| `source-read` | 0.102702458 | 0.092213 |

含复制、核验和恢复的 driver wall envelope 为 **7.154502038 s**；上表是其嵌套命令，不重复加入 parent wall。该例模型预测 cost 为 `0.0`，不代表实际成本为零，也不能把 advisory gain 当作终态收益。

本诊断 **新增 TRAIN rows = 0，新增 confirmation rows = 0，fresh confirmation groups = 0**。没有打开 annotation，也没有执行 native Cell owner 或 production daemon。原始 argv、stdout/stderr、wait4 receipts 和 owner 原件由独立归档保留；Git 只记录派生状态和原文件 hash。

## 3. 显式 feature profile 接入与兼容范围

新增 `perc1.source-feature-profile.v1` 冻结 first/last、flatten/mean、representation、token 数/维度、任务特征宽度及 encoder/model/projection 身份。训练前的 profile/extractor 指纹绑定到实际 head 的 `training_receipt.feature_extractor_sha256`。运行时验证原 owner receipt、wire、源/OCR evidence 和有序 token 引用；不会把训练用的 initial dense flatten64 暗中改成旧 last mean16。

普通 CLI 使用 `perc1.profiled-source-active.v1`，严格限制请求字段，并以 `head_artifact` 引用模型文件。请求仍限制 **64 KiB**；profiled head 单独允许 **2 MiB**，同时核验 raw-file SHA 和 canonical-model SHA。新决策为 `perc1.active-capture-decision.v3`，head 与 profile 在 owner 中保留，支持重新核验选择的冷读。

该模型保持原有 acquisition MLP artifact schema，没有伪装成 Parameter V3，也没有默认采用或扩大权限。Profile 保证作用于显式 v3 入口；未提供 profile 的请求仍可使用 v2。精确历史 v2 代码 pin 仅在 v2、且其余要求的 pins 全匹配时获准冷读。`source_entry.py` 的 backend pin 已改变，旧 operator CLI config 不保证无需迁移即可接受；真实旧 journal 的直接 Owner/read_decision 兼容不能替代这一限制。

### 独立记录的合成工程实验

合成图像/latent/utility fixture 使用现有优化器实际训练 **4 TRAIN / 3 DEV、256 步**，参数 hash 确实改变。其保留 head 大小为 **102,889 B**。除 latent 外公共数值输入相同，正 latent 选择 ACQUIRE、负 latent 选择 STOP；另一 Python 进程从保留工件恢复相同结果，未构造新 capture adapter。

该实验没有执行真实视觉 backbone，没有真实来源确认，也没有 native Cell owner。冷读仍重新计算 head 选择，不能称为零 head inference。**这些 4/3 行、256 步和 102,889 B 模型与真实 CORD 的 72/24 pairs、200 步和 88,087 B 模型分开记账。**

## 4. 失败处理、来源与成本边界

001 在 TRAIN 阶段遇到真实 Tesseract deadline 失败，后续训练代码对 failed receipt 的 `result=None` 解引用而停止。原始失败、包含失败观测的 7 组 completed-attempt records、owner 原件及 **458.243153891 s** 进程封套保留；confirmation actor 数为 **0**。

002 使用相同固定 44 来源与新目录，修复失败记录/拟合准入并采用明确线程限制；Tesseract 原 **30 s** deadline 没有延长。每个 view 只尝试一次，initial 失败不构造该前缀/fit，extra 失败不生成成功 pair；状态、错误及实际 measurements 始终保留。002 本次实际记录不完整训练观察 **0**，其独立执行封套为 **236.864618835 s**。

来源冻结对已声明的 199 张历史 FUNSD 原图进行有界比较，44 个 CORD 候选没有发现 exact known reuse。固定抽取没有替换或跳过；TRAIN rows 0–4 的 preplan exposure 已记录。全局历史完整性、近重复、机构/模板相关性及独立来源 custodian 均未验证，因此 **fresh independent confirmation 仍为 0**。

七 arm 表没有包含所有下载、来源冻结、历史模型训练、原始图像捕获、共享准备或先前失败成本。Energy 与 provider billing 未知；child CPU 的计量范围见原记录。训练、actor、额外 CLI 与子阶段封套可能嵌套或时间重叠，不能相加后宣布完整端到端 wall 或净收益。`full_cost_qualified=false`，`measured_net_benefit=null`。

## 5. 已执行的工程测试与 CI 集成

| 记录 | 结果 | 验证范围 |
|---|---|---|
| 七模块 scoped run | **47/47，0 skip** | source freeze 15、profile 5、profiled CLI 2、terminal comparison 11、CORD task 2、source reuse 11、repeat training 1 |
| 本次失败回归 | **3/3，0 skip**，含 3 个阈值子案例 | 真实 Owner 接收受控 TimeoutExpired，保留 failed/result=None 收据与错误/成本，初始失败整组排除、分支失败单项排除、无重试 |

失败回归的有效 pair 数 **23 TRAIN / 6 DEV**、**24 TRAIN / 5 DEV**、**21 TRAIN / 6 DEV** 均在保留尝试原件后拒绝 fit，不写 HEAD/PROFILE。该组 prefix/text 使用工程 fixture，optimizer 只 stub 检查入参，没有真实 OCR、backbone 或 confirmation。各运行绑定自身记录的源码 SHA；较早的 30-case 和 2-case 运行与这些范围重叠，不相加成新样本或统一最新源码上的测试总数。

Workflow 保留候选浅克隆，另从 canonical repository 的精确 a558 提交 sparse checkout 历史 `active_capture.py`，先验证提交及原始字节 SHA，再导出 `PERC1_LEGACY_ACTIVE_CAPTURE`。旧代码真实生成 v2 journal 后由新 reader 冷读，没有 skip 或改 JSON 版本伪造历史。精确步骤的本地成功路径以及 commit/字节漂移拒绝路径均已执行，YAML、shell、内嵌 Python 和 whitespace 检查通过。普通单元 CI 自动发现 `test_perc1*.py`；CORD 联网 pilot 不在其中。

最终 workflow 已把 trained-native 精确源码构建放在 unittest discovery 之前，并显式要求失败回归与 native 合同模块实际出现、全局零 skip。[Draft PR #6179](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6179) 的最终 hosted 状态以该 PR 对应 head 的 Actions 为准；此处不声明 hosted PASS。

## 6. 最终源码的真实 trained-native 阶段

[最终原始报告](NATIVE_TRAINED_REPORT_FINAL.json)、[最终来源绑定](NATIVE_TRAINED_PROVENANCE_FINAL.json)、[分阶段构建与测试汇总](NATIVE_TRAINED_SUMMARY.json) 和 [完整机制说明](NATIVE_TRAINED_NOTES.md) 已记录真实执行。原库仍是精确 a558 的 115 个源文件，没有修改普通 Cell/inference 库。实际训练 head 的 FP64 normalization、tanh 两层矩阵运算和 DEV 校准在 Rust 的 `NeuronInferenceControlPort` 中执行，进入原 `infer_cell_with_clock` 与 Cell owner journal。

输入来自已使用的 TRAIN00000：先冷读原 owner receipt，验证 source/wire/profile、原图 document SHA 和冻结 head，再重建三组候选特征并逐值核对原 TRAIN pairs。无损 FP64 carrier 占 **432 个 scalar，低于原 512 上限**。输出使用显式的 FP64 budget/threshold/order → bounded ordinal drive 适配，避免 Q24 直接四舍五入吞掉小正值或改变近邻排序；ordinal 不是模型 logits。

| 最终格式化源码实测 | 结果 |
|---|---|
| Build | `build-006`，原库、新 probe、builder、manifest 前后不变 |
| 最终 binary SHA256 | `a8c9afb739a9bcf603d4f6096cbb8f7a89269e19edc9b9b0968870f2d09a2f8c` |
| 特征 | 3 个候选 × 73 维，其中 64 维为实际视觉 latent |
| Rust / NumPy 原始输出最大绝对误差 | **6.661338147750939e-16** |
| Python / Rust / Cell 选择 | 全部 `lower` |
| 独立调用 | start、cold read、lose ACK、recover、replay，全部退出 0 |
| 实际 MLP 执行数 | **[1, 0, 1, 0, 0]** |
| 原输出 readback | **1**，恢复未重复运行 MLP |
| 最终 driver wall envelope | **0.793392176 s**，子调用时间不重复相加 |

**11/11 合同、0 skip** 在 build004/005 的同字节 binary 上完成，覆盖实际训练、数值、视觉翻转、阈值、平分、预算、carrier 上限、改写拒绝与恢复。仓库最终 `just fmt` 只展开/重排三份 import，但文件与 binary 身份改变，因此没有将旧 binary 的测试记录冒充为最终 binary 的记录：另建 build006，并用最终 binary 重新执行上述真实 TRAIN 资格链。依照仓库规则没有因格式化重跑相同 unit tests；最终提交的全部 native 合同由新增 hosted gate 再执行。

早期 builder 存在“复制源码后、编译末尾才采样 stage hash”的竞态风险，已修为复制前冻结并在构建前后复核 stage/copied source/builder/manifest。追查早期 001–003 原件的实际 hash mismatch 为 **0**；原件、ERRATA、格式化 diff 与所有构建均留存。

这条证据的范围为 **PASS_TRAIN_NUMERIC_AND_DURABILITY_ONLY**。原 84 次 CORD actor 是普通 Python owner 执行；没有把它们追认为 native Cell 驱动。该桥没有采用 Parameter V3、没有普通 daemon 入驻，也没有新增确认来源或任务净收益。它补上了实际训练 head 的原生执行证据，不改变负的任务结果。

基线事实保持成立：[#6072 的真实原生诊断链](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a5583f0f4a12d9618a3a5bc5ed0e7062a7463f39/qualification/perc-real-observation-20261112/SOURCE_NATIVE_REPORT.json) 已真实执行，其旧 head 为 diagnostic Q24。本轮实际训练 head 的证据单独列于上面的最终报告。

Production daemon、来源独立性、完整成本、学习型解码、动态环境和终态任务净收益继续 HOLD；没有默认采用。

## 7. 原文件 hash 与发布边界

下列是用于派生本记录的**原文件 SHA256**。逻辑工件名指向独立保存的原件，不能仅凭本摘要取代原件；完整原件由 PRIVATE_ARCHIVE.json 绑定；源码阶段对应 SOURCE_COMMITS.json，最终 hosted 状态由 PR 的 exact-head Actions 提供。主要源码 pins、更多 CLI command/meter/log pins 及各范围的布尔限定在 `ENGINEERING_SUMMARY.json` 中。47-case 与 3-case 的摘要列出测试文件 pins；各阶段完整源码 pin 集合以该文件 hash 绑定的原始报告为准。

| 原件 | 逻辑工件名 | SHA256 |
|---|---|---|
| CORD source summary | `CORD_SOURCE_SUMMARY.json` | `4d7276ca0ee92075d58960f5deb6103be2822cdccc2bce7f69d4ba34fb88904c` |
| CORD pilot 002 report | `cord-pilot-002/REPORT.json` | `7c7215f7e64cf43db61ac7e6c88ff1c7a792a532e77ac54df1bd6eaee7fd93a4` |
| CORD public synthesis | `CORD_SYNTHESIS.json` | `09637f1d6bd07e10e80dea0dda6fa60c235caf4f684edab36ea54a12347ca1be` |
| Real TRAIN CLI report | `cord-cli-002/REPORT.json` | `fc728328f93d837d990e3c6110759e0804ecd9f3fbbf0fc9bad71fbf2c03bd2e` |
| CLI complete-byte manifest | `cord-cli-002/DELIVERY_MANIFEST.json` | `1a8ee06851669e2e1cb430d4b81859ee68f78825adc0882a984210171815f86c` |
| Synthetic profile experiment | `perc-profile-experiment/REPORT.json` | `43789ff5a9bfcb576678d0e9422cce9eb8870b3d8e4ae2fa5a11b018e7e38a57` |
| 47-case execution record | `perc-workflow-validation/REGRESSION.json` | `db2d091a96ab23445eb2d305e6ec13a011e39ed5f3e3aeb57a49e698e2870168` |
| 47-case original log | `perc-workflow-validation/regression.stderr.log` | `d91946c6977d6f4df891c6a35a92870a7eedb79adde83cb671a75466e2ed56e5` |
| 3-case failure regression record | `perc-cord-training-validation/RESULT.json` | `4d6d2b9c3fc3397ea91e82fe166a18401d2b922f5a87e787327ca532251cf8be` |
| 3-case original log | `perc-cord-training-validation/stderr.log` | `14cfd7cc436897a8697a5bbb323bb70bdce88c223845c7a554e268ea5e50fc59` |
| Prior failed 001 execution envelope | `cord-pilot-001-execution.json` | `553641f3903129e9c71729e431387b0f4cdbdef5537c32a38aac039d10a424aa` |
| Successful 002 execution envelope | `cord-pilot-002-execution.json` | `43810a218ad901e6a981e758aa32f97c8694b953e956439999aebd414f0a4ccc` |
| Post-freeze oracle report | `cord-oracle-002/REPORT.json` | `702ca11b6065976a179f1b13b643de2507d4a7bf5765bd18fadd47d853aba50c` |

完整证据包 `perc-trained-observation-20261112-evidence.zip` 为 **235,518,260 bytes**，SHA256 为 `b6f0248ea09fab3bbd98593ecb30ab817c88e5e5c73e153fdd397d270f13bc37`。它以 1,797 个内容寻址 blob 保留 4,205 个路径，逐 blob SHA 冷读全部通过；其中 native v2 子包另含 424 项已冷读原件。源数据的完整 Parquet shards、安装依赖和 Git 仓库未重复打入，选中的原始图片/annotation 及下载身份保留；精确范围见包内 MANIFEST 与本目录 [PRIVATE_ARCHIVE.json](PRIVATE_ARCHIVE.json)。

本目录新增的工程摘要与本 README 仅包含聚合指标、状态、布尔比较、源码 SHA 和原文件 SHA。没有把绝对 workspace 路径、OCR 文本、答案、annotation 字节、图像、wire 字节或 owner journal 内容写入 Git。
