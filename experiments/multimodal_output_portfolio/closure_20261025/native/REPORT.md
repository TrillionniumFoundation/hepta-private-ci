# 原生 owner 在动作前决策、真实生成、后验 NDU 与恢复

## 本轮达到的边界

这次把原来的“已经有 future outcome，再把它送入 native tick”的研究回放，接成了真正先后发生的执行链：**公共 prefix → 原始 `AgentdNeuronOwner` 执行冻结 head → 按原门槛选择或拒绝动作 → 实际 generator 生成 → 独立 observer 读取真实输出 → 原生 NDU journal 提交 → 下一次 tick/恢复**。运行中没有训练参数，也没有提前生成被选择动作的未来结果。

冻结后首次开放的 64 对来源上，原始 owner 实际执行 128 个候选 tick，37 对获准后生成了 PNG 与文本，并完成 37 个后验观察/NDU 提交；27 对在原门槛下拒绝，没有执行后续生成。10 对 `both_missing` 全部拒绝。20 项在线非法输入或错误观察绑定检查全部拒绝且 owner 状态不变。pending decision 后的 SIGKILL 恢复、已提交 outcome 后的恢复均保持精确 frontier。

这里的动作选择仍是**已冻结、原先有资格证据的 correctness head，在当前原生门准入动作中取概率最大值**。NDU 保存实际后验 utility，并被下一 tick 的 objective/subject/context 绑定及恢复使用；它尚未作为 action-value 优化器改变动作选择。这个结果完成的是原始 owner 的因果执行整合，不证明一般 NDU 最优控制，也不构成新策略的生产资格或完整 daemon 部署。

全部事实、原始失败记录、构建命令与成本在 [RESULTS.json](RESULTS.json)。[PROTOCOL.json](PROTOCOL.json) 是新来源开放前冻结的 41 项文件身份。[RAW_EVIDENCE.tar.gz](RAW_EVIDENCE.tar.gz) 保存完整运行证据和实际 binary；[RAW_MANIFEST.json](RAW_MANIFEST.json) 列出每个归档文件的字节数与 SHA256。

### 执行字节与发布格式化版本

本轮64对主结果绑定的是格式化前真正编译执行的Rust字节；旧 `PROTOCOL.json`、`RESULTS.json`、`RAW_EVIDENCE.tar.gz` 保持原字节及SHA。收尾时先把10个实际编译Rust源另存为 [SOURCE.tar](frozen-execution-001/SOURCE.tar) 和 [MANIFEST.json](frozen-execution-001/MANIFEST.json)，然后才为当前3个活动Rust文件添加edition2024配置、运行仓库原始 `just fmt`。当前活动源是这一纯格式化版本；不能把它的SHA填回历史protocol。旧protocol中的活动Rust路径在当前格式化工作树中自然不再等SHA，要重现历史身份应使用所保留的原始快照。

[FORMAT_ONLY.diff](FORMAT_ONLY.diff) 记录全部自动格式化差异；[FORMAT_ONLY_VALIDATION.json](FORMAT_ONLY_VALIDATION.json) 与 [FORMAT_ONLY_VALIDATION.tar.gz](FORMAT_ONLY_VALIDATION.tar.gz) 单独保存格式化命令、原工具身份、新构建及旧dev验证。新binary SHA为 `522f6376f8934199d9a72f8308bc1ec2b00062edb251ab1999437dd211b9afc9`，仅在原来已用的12对train输入上执行：24个候选prediction/confidence/OOD/admission字段与原开发运行逐项相同，12个选择相同，6份实际媒体SHA和observer分数完全相同，20项反例及两种恢复通过。这里没有新增独立来源，也没有重新打开64对主结果来源。

完成该旧dev验证后再次运行原 `just fmt` 及 `just fmt --check`，两者exit0且三个活动源SHA不变；此后不再运行实验或测试。原source archive作为历史证据保存在二进制tar内，不作为另一套需要编译的活动实现。

## 使用了哪些真正的产品部件

`AgentdNeuronOwner` 源文件来自固定 product commit `985a52e84cdaed7c8d4c363f30bc8841c5e3730c`，SHA256 为 `4d56cc99d0edb1018734aebf70dc715de8df7846a2a9c4f2edb4230a0fc87faf`，编译时直接复制，未改动。它持有原生 runtime 和 `NeuronInferenceControlPort`，每个 tick 实际走原 `InferenceControlModelPort`、feature receipt 验证、calibration、sparse journal 与 witness。原生依赖沿用 `9595221c21f1fe0775295a9c8756a1ba4d69ea49` 的 22-crate 构建产物；本轮没有重新编译整个 Agentd crate。

新增的 [online_port.rs](online_port.rs) 是真正的 inference-control 实现，加载冻结权重一次，然后在常驻进程内执行 head forward。不是把预计算 prediction 当成模型返回。Python 侧同时按原 predictor/calibrator 计算，逐候选验证 Rust 的 33 个 Q24 输出完全一致。每个原生进程权重只解码一次；三个进程是预定故障恢复造成的，没有每 tick 重载模型。

原 forecast ABI 收 510 维，但已冻结 head 仅读取前 478 维。新接口只接受 478 个公共的动作前特征，内部兼容 padding 的后 32 维恒为零。原来携带已观察 future 的两个状态副本，改成显式的两个 **predicted** 状态副本：reference 为 `[1, forecast32]`，prediction 为 `[p, forecast32]`。因此 32 个预测坐标相消，既有 probability carrier 的置信度语义保持清楚；没有把预测坐标称为观察。模型/normalization 身份另行登记。原头仍只覆盖 `refine_text` 和 `couple` 两种动作；新 577 维 action-value actor 没有被偷偷塞进原生最多 512 维的输入接口。

控制器 [online.rs](online.rs) 校验 generation、权重、objective、公共 prefix、两个动作编码和维度。两个候选使用相同公共 prefix，owner tick 只绑定此前已提交的 NDU。控制器把候选、选择和前序锚写入 hash-chain history 并 `sync_all`，才向实际 generator 返回决策。未获准时返回空动作。

generator 收到决策后，才用事先登记但尚未抽取的后续随机分支执行真正的 transition；随后保存 PNG/text，重新读入验证媒体一致，再用冻结、独立训练的识别器及观察侧 target 评分。native 接收 outcome 时检验 pending decision、选中动作、observer 身份、媒体实际文件 SHA、时序和 utility 范围，然后调用原 `NduProjectionStoreV1::append_projection/select_projection`。这里是研究 observer；它不是已经认证的生产 Observer 服务。

## 冻结与来源

新来源来自原 `unallocated_train` 中 pair `[512,576)`，通过根研究分配器映射为 `closure_native` 的 64 对。分配文件 SHA 为 `fcee8983689b78e6f7bb131130dbc075d0c745d7e3e560acdf64f2a26da729e8`。原训练/验证角色的读取限制保持不变。分配审计覆盖可用的代码与执行元数据，不能证明未知外部实验从未使用这些样本。

最终 protocol SHA 为 `cc9e4f47fedcb26577ab7815a20c32109c782b3ce83f6f74853ebcc2dabbb0bf`；binary SHA 为 `bd10a370c91d85fb6732d8de960d709959b63518163257c0a0e6c3812915db88`。模型、observer、head、calibrator、原资格证据、运行器、源分配器、生成/抽样代码、公共特征构造及实际编译源均在来源访问前冻结。加载器先校验这些实际字节，再返回本研究获分配的来源。新 64 对只执行一次，没有按结果调节策略、门槛或重新训练。

先前的开发运行只使用已用过的 train 来源：12 对烟测，随后 72 对完整闭环及跨段恢复验证。它们不增加新统计 N。首次 12 对烟测的第二个进程发生了 **p95=3847µs，超过 3000µs 原门槛**，原始结果完整保留；后续通过不消除这一失败。早期编译括号错误、旧模块 wrapper 的范围拒绝、只涉及路径/冻结清单的 pre-access 修正也记录在 RESULTS 中。

## 新 64 对的完整计数

| 输入视图 | 来源对数 | 获准后实际生成 | 拒绝且不生成 |
| --- | ---: | ---: | ---: |
| clean | 11 | 8 | 3 |
| noise | 11 | 6 | 5 |
| occlusion | 11 | 5 | 6 |
| missing_trusted | 11 | 10 | 1 |
| conflict_untrusted | 10 | 8 | 2 |
| both_missing | 10 | 0 | 10 |
| 总计 | 64 | 37 | 27 |

37/64 是这套冻结门和选择规则的实际生成覆盖率，不是“37 个成功答案”。媒体质量分数保留在原始 outcome；没有仅用获准子集报告全体质量，也没有把缺失输入拒绝视为完成了生成任务。10 个缺失样本全部拒绝只能说明本次观察，不能据此宣称 FAR 已经达到原资格要求的统计上界。

## 恢复和反例

新来源的首个获准 decision 已同步写盘、但尚未生成 future 时，运行器主动 SIGKILL 原生进程。新进程从同一 descriptor、binary、native anchor、controller chain 和 NDU projection 精确恢复 pending decision；接着实际生成并提交它的 outcome。第 32 对完成后另一次正常关闭/重开，恢复了已提交 outcome 的状态。每次比较 sequence、native anchor、controller history digest、objective、NDU modulator、pending identity、request 数及 outcome 数，全部相等。

20 项在线检查覆盖错误 generation、权重、objective、夹带 future target 字段、候选缺失、不同 prefix、错误 action one-hot、错误维度、重复 decision、pending 时发新 decision/关闭、错误 outcome binding/hash、错误 observer/action、倒置生成/观察时间、媒体 hash 不符、utility 越界、重复 outcome。拒绝前后完整状态相等。

开发运行72对实际执行144个tick，经过128tick分段边界。对其完整存储副本另做10项 recovery/evidence probe：完整有序链精确恢复到144；binary identity改变、控制日志截断、日志digest改变、缺段、段顺序交换、NDU/controller frontier不一致均真实拒绝；缺 verification、缺 observer、权重字节替换也在 bootstrap 前真实拒绝。原始 stderr 和全部输入副本在归档中。

这些检查建立了研究控制器的因果与恢复性质。controller history 和 native witness 仍在本地研究存储中，没有独立部署回滚域；跨 NDU/controller 两个存储中断若形成不一致会拒绝恢复，当前没有自动跨存储事务修复。不能将本地 hash chain 说成生产的反回滚授权。

## 门槛与实际成本

准入门保持 min confidence 750000ppm、max OOD 500000ppm；冻结资格保留 ECE≤30000ppm 和 FAR≤4999ppm。原生资源门仍为 p95≤3000µs、p99≤8000µs、transient≤512KiB、checkpoint≤1MiB、write amplification≤4000000ppm。head 本身由原 native runtime 检查；外层另外拒绝超过同一 transient 上限的 owner tick，没有放宽任何原门槛。

| 新64对、128tick | p95 | p99 | 最大值 |
| --- | ---: | ---: | ---: |
| 原 runtime receipt 执行时间 | 818µs | 1150µs | 1317µs |
| 整个 owner.tick 外层时间 | 1422µs | 1662µs | 1730µs |
| owner 窗口新增堆峰值 | 24140B | 24140B | 36057B |
| native model transient | 13016B | 13016B | 13016B |
| checkpoint | 1568B | 1568B | 1568B |
| write amplification | 530613ppm | 530613ppm | 530613ppm |

三个原生进程各自的原 `summarize_resource_samples` 结果均通过。表中总体分位数由全部128条原始 receipt 计算。这里的性能是本次共享主机上的供给样本，不是部署主机代表性资格；首次烟测的超时失败仍需纳入运行评估。

精确 child PID 的 `wait4` 成本记录得到整个新来源研究 wall **3.588s**、用户/系统 CPU **3.689s / 0.378s**、peak RSS **399777792B**。它包括 Python/Torch、模型载入、源读取、真实生成、observer、原生子进程及恢复。内部计时的研究循环为1.764s，不能替代全进程成本。约381.3MiB的整进程 RSS 与512KiB的原生 transient gate 是不同度量；本轮没有把前者说成满足后者。

新工作没有训练步，也没有整个22-crate依赖重编译。增量 `rustc` 构建命令、wall时间、原库SHA和所有失败尝试均保留；这不足以反推从空机器构建完整 daemon 的成本。

## 仍未获得的证据

- 本轮没有将 NDU action-value 策略纳入原生产模型执行链。当前策略是冻结 correctness 的 argmax；actor 的线上公共输入契约、重新校准与独立效用比较须另行建立。
- 64 对证明这次独立来源上的因果执行事实，不重新授予整套 calibration/FAR 或新策略资格，也不能证明全局最优。
- 原始 owner 已编译执行，整个 Agentd daemon 没有构建、运行或部署；实际 generator 仍由 Python研究进程持有，尚未替换为生产模型服务 transport。
- `authority=deny_all` 全程不变。没有创建 Dataset owner、Generator/Observer/Evaluator 的正式签名或信任根，没有 install/activation/applied-update。本轮没有调用 production resolver，因此不把缺少正式材料描述为本轮已经逐个执行到该 resolver 的失败；上一轮 resolver 的实际 Dataset owner 拒绝见既有 [AUTHENTIC_HANDOFF.md](../../abc_followup/native/AUTHENTIC_HANDOFF.md)。

这些未闭合项是明确的后续产品输入和资格工作，不是可以通过改一个布尔值或补写非零 digest 完成的配置项。

## 执行入口

在此次固定工作区，依次运行本目录 `build`、`run --mode smoke`、`boundaries`、`freeze`、`run --mode fresh`；运行器由本目录 `process` 包裹以保留精确PID成本。每一步输出目录采用 `exist_ok=False`，避免覆盖旧证据。实际命令完整保留在 RESULTS 的 process/build receipts；frozen protocol 中列出所有绝对输入路径及SHA。

重现实验需要恢复这些固定模型、权重、原生依赖和来源文件，或对新的环境重新登记文件身份。再次打开这64对只能称为重放，不能重新计为独立新来源。归档包含真实编译 binary、所有编译源、每次native命令响应、PNG/text、观察、NDU/native/controller日志、恢复副本、过程成本和开发失败，不含生产身份或凭据。
