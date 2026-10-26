# 联合四模态训练与实际输出：完整结果

本轮完成了六个模型的真实联合训练、独立来源上的 768 次四模态生成、全部物理输出的观察与评分，以及独立统计审计。**执行与证据链闭合，预注册的两项质量门均未通过。** 在这套固定配置中，entropic 训练相对 mean 训练的 CE 差值为 **−0.0068529661**，95% cluster interval 为 **[−0.0147229818, −0.0011904477]**；严格四模态共同成功率差值为 **−1.30208 个百分点**，区间为 **[−3.33333, +0.50505] 个百分点**。没有据此更换模型、阈值、样本、观察器或主端点。[主分析](RESULT.json)、[正式协议](PROTOCOL.json)、[独立审计](review/REPORT.md)

这一结果支持“已实际训练并执行一个有明确目标函数的有限四模态模型”，不支持“该 entropic 训练配置优于匹配的 mean 训练”，也不授予全局最优或开放域全模态大模型能力。此次联合实验的推理固定执行两个 continuation；动态动作组合的价值须由单独的控制与原生执行研究回答。

## 1. 训练了什么，以及比较回答什么

模型以一个公开输入模态启动，生成 text、image、audio、video 四种输出。公开输入依任务分别为受损数字图像、明确提供的两位数字文字、实际语音 PCM 的声学特征，或显示源图像的运动视频。生成器接收 `PublicTask`；非文字任务的私有目标没有作为输入字段传给模型。文字任务本身明确要求复述所给数字，因此其公开数字不构成隐藏答案泄漏。[模型实现](model.py)

共同状态依次执行固定的 `refine_semantic`、`couple`，随后产生七个 AR 新 token、两个离散语义数字、两块神经图像、两个 16,000-sample 波形事件和 20 帧视频。视频由生成的图像内容和训练过的运动 decoder 共同形成；语音由十个固定条件的 waveform student 产生。它们确实输出连续波形与时空像素，但任务仍限于构造的十类数字、有限语音条件和运动变换视频。

六个 arm 为 **seed 17、29、43 × mean、entropic**。每 arm 训练 **320 次更新、batch 4**；四条输入 route 固定轮换，各获得 80 次更新。总计 1,920 次优化器更新和 7,680 个训练样本槽位，槽位数不能理解为独立来源数。每个 seed 内两个 arm 的初始参数 SHA 和外生样本/噪声 schedule SHA 一致。训练只用旧 image `train` 角色和 speech `fit` 的 3,000 条录音；正式确认来源没有参与训练。[训练注册](TRAINING_REGISTRATION.json)、[训练结果](TRAINING_RESULTS.json)

| 可训练组件 | 作用 | 每个 arm 的实际证据 | 学习率 |
| --- | --- | --- | ---: |
| `core` | 共享状态、文字与图像生成 | 非零梯度记录，参数 hash 改变 | 0.0001 |
| `speech` | 由语义条件输出 waveform | 非零梯度记录，参数 hash 改变 | 0.000003 |
| `motion` | 生成视频的时序位移 | 非零梯度记录，参数 hash 改变 | 0.00003 |
| `audio_input` | 声学特征到公共语义分布 | 非零梯度记录，参数 hash 改变 | 0.00005 |
| `video_input` | 视频到公共语义分布 | 非零梯度记录，参数 hash 改变 | 0.00005 |

上述五项在全部六个 arm 中均成立，共 30 个组件/arm 检查；这不声称每一层、每个参数或每一步都收到非零梯度。声学前端是没有可训练参数的固定 mel/时间对齐变换，训练开始时缓存其结果；其后的可训练声学网络正常参与联合更新。优化器为 Adam，全模型梯度范数裁剪上限为 5。训练 reward observer 保持冻结，正式的图像/ASR 审计器不参与梯度。

这里**没有保持初始生成器完全不训练的 arm**。因而本比较识别的是两种匹配的继续训练方案之差，不能单独估计继续训练相对初始冻结模型的收益，也没有拆出每个组件更新的独立贡献。

## 2. 实际优化目标与梯度

令训练样本的四个 proxy reward 均值为 \(U\)，注册的 \(\gamma=2\)。两个基础 cost 为

\[
c_{\mathrm{mean}}=-U,\qquad
c_{\mathrm{entropic}}=\frac{\exp[-2(U-0.75)]}{2}.
\]

四个训练 proxy 分别是：冻结图像 reward 的目标类别概率；实际采样完整文字序列的严格正确性；生成波形相对固定训练波形的归一化 MSE 所形成的 \(\exp(-\mathrm{error})\)；以及视频帧语义概率与运动一致性的 0.8/0.2 加权分数。它们在 codec 前计算，属于明确登记的训练信号，不是正式物理输出的同一个评分函数。

连续图像、波形、视频部分使用 pathwise 梯度。离散 AR token 和语义数字实际采样，并保留其联合 `log_probability`。实现将

\[
\operatorname{stopgrad}(c-b)
\bigl(\log\pi-\operatorname{stopgrad}(\log\pi)\bigr)
\]

加到基础 loss，获得 score-function 项；该修正的前向值为零，固定 baseline 在 mean arm 为 −0.75、entropic arm 为 0.5。代码没有把离散选择替换为 straight-through 近似。二结果枚举的梯度合同检验中，两种 profile 的期望估计梯度都与直接枚举梯度相等，容差为 \(10^{-12}\)。这检验了该合同的公式实现，不意味着整个实际优化过程已经收敛。[梯度合同](TRAINING_GRADIENT_CONTRACT.json)、[训练源码](train.py)

两个 arm 都另外加上权重 **0.005** 的 waveform fidelity anchor：对全部十个 canonical 条件计算归一化波形 MSE。固定的指数 cost 尺度与共同 anchor 因此都是实际训练方案的一部分。不能将这个复合目标的有限步结果描述成无条件的纯 CE 最优解。

正式生成改用 greedy AR token 和 greedy 语义数字，经过真实量化、编码、文件写出与解码，并由独立观察器评分。训练的采样策略、连续 proxy 与正式 greedy/codec/ASR 路径存在明确差异。当前负结果没有单独消融这些差异，不能据它认定其中某一项是唯一失败原因。

## 3. 正式来源、配对结构和物理输出

协议在打开正式角色前固定六个 checkpoint、观察器、源分配和实际 codec 路径/字节，共 **181 个 SHA pins**。正式协议 SHA256 为 `6a305d92578da4d6e41ebc104101b7af58ebc02306ea6c54d9e73ae724222f08`。之前 V2 观察器资格未通过时，guard 以 exit 1 拒绝创建新源运行；原失败日志、执行源码 snapshot 和进程记录保留。V3.1 采用新独立资格后才放行本次正式角色。codec 和递归 import 依赖的补充绑定也都发生在正式源开放前。[资格与 preflight 历史](PREFLIGHT.json)、[静态依赖审查](CONTROL_REVIEW_ADDENDUM.md)

确认集含 **128 source pairs、256 个不同 digit ID、32 个 image writers、24 个 speech speakers**。每位 writer 提供四个不同 pair，各分配一条输入 route；image view 按 writer group 在八种 view 间循环，严重缺失 view 保留。三个固定 seed、两个 profile 全部执行每个 pair，得到 **768 个实际输出 bundle**。每 bundle 保存四个输出文件，总计 **3,072 个实际输出文件**。

音频是 8 kHz mono PCM，四秒内有两个两秒事件，共 32,000 samples。视频有 20 帧、5 fps，并与音频 presentation clock 绑定；实际 MP4 使用 H.264 RGB 图像与 ALAC 音频。PNG、caption、WAV、MP4 均实际写出并经过规定的读取/观察流程；此计数不是动作日志回放。图像/视频观察器及 ASR 接收实际媒体，目标只在其后的评分步骤使用。[执行实现](evaluate.py)、[完成摘要](COMPLETION_SUMMARY.json)

ASR 主端点是预先选定的 `consensus_or_single_v3`：两模型非空且相同则接受，仅一方非空则接受，否则 abstain；规则不读取 expected target 来修正文本。独立资格结果为 **259/300，86.3333%**，达到原 0.85 点估计门。两个单独模型分别为 249/300 与 243/300，没有各自获得这个门的资格；两模型也不是两个独立样本来源。该 300-recording 资格角色实际涉及 298 个不同 WAV、147 个 speaker；与同批 ingress 终点共用录音，并未被包装成 600 个独立样本。资格的具体边界保留在媒体证据中。

正式 768 个 bundle 的 1,536 个音频事件请求，实际执行 **60 次事件 ASR 观察**，另有 **1,476 次按精确 PCM 身份命中的缓存**。缓存减少重复观察计算，不能增加独立观测数，也不能用缓存命中的耗时替代全部冷启动成本。

writer 与复用 speaker 的实际连接图含 **24 个连通簇**：16 个簇各有一个 writer，8 个各有两个 writer。原 bootstrap 以这些簇为单位，配对保留全部 arm、seed 和 route，4,000 次 resample，seed 239001，95% percentile interval；不等簇大小完整保留。推断条件是这个固定的三 seed 训练面板，三个 seed 不是额外独立来源，也未推断所有可能训练 seed 的总体分布。

## 4. 主结果：原质量门均失败

正式效用为四个实际模态 correctness indicator 的均值，严格 joint 另要求四模态全部成功。CE 定义为 \(-\log\mathbb E[\exp(-2U)]/2\)。本联合训练比较的 action penalty 登记为 0；执行成本单独报告，未混入此 CE。

| 指标 | mean | entropic | entropic − mean | 95% cluster interval | 原门 |
| --- | ---: | ---: | ---: | --- | --- |
| Entropic CE | 0.6798279014 | 0.6729749353 | −0.0068529661 | [−0.0147229818, −0.0011904477] | 下界 > 0：**FAIL** |
| Strict joint success | 80.72917% | 79.42708% | −1.30208 pp | [−3.33333, +0.50505] pp | 下界 ≥ 0：**FAIL** |
| 平均 utility | 0.8470052083 | 0.8411458333 | −0.0058593750 | [−0.0110687934, −0.0012626263] | 描述性 |
| Image success | 84.37500% | 84.37500% | 0.00000 pp | [−1.11111, +0.98039] pp | 描述性 |
| Text success | 86.19792% | 85.15625% | −1.04167 pp | [−2.01149, −0.26042] pp | 描述性 |
| Audio success | 87.50000% | 87.23958% | −0.26042 pp | [−0.86207, 0.00000] pp | 描述性 |
| Video success | 80.72917% | 79.68750% | −1.04167 pp | [−3.05556, +0.61788] pp | 描述性 |

这里 pp 为百分点。主 CE 差值区间整体低于零；strict joint 的区间也不能满足原登记的零容差非劣门。`quality_claim_eligible=false` 完整保留。

以下 route 和 seed 数据仅解释结果分布，没有从中另选成功条件替换主比较。[全部主/描述性结果](RESULT.json)

| 输入 route，每 profile 96 个输出 | mean CE | entropic CE | mean strict joint | entropic strict joint |
| --- | ---: | ---: | ---: | ---: |
| Image | 0.4273114800 | 0.4230306743 | 52.08333% | 47.91667% |
| Text | 1.0000000000 | 1.0000000000 | 100.00000% | 100.00000% |
| Audio | 0.7175961716 | 0.6959866324 | 84.37500% | 83.33333% |
| Video | 0.7388801180 | 0.7388801180 | 86.45833% | 86.45833% |

| 固定 seed，每 profile 128 个输出 | mean CE | entropic CE | mean strict joint | entropic strict joint |
| --- | ---: | ---: | ---: | ---: |
| 17 | 0.6653156851 | 0.6670019871 | 80.46875% | 78.90625% |
| 29 | 0.6937138968 | 0.6864910719 | 82.81250% | 81.25000% |
| 43 | 0.6808588894 | 0.6657017727 | 78.90625% | 78.12500% |

## 5. 实测成本与口径

| 阶段 | Wall time | CPU time | Peak RSS | 边界 |
| --- | ---: | ---: | ---: | --- |
| 六 arm 训练记录 | 113.656009 s | 112.767942 s | 590,389,248 B | 包括训练 main 内数据准备与六 arm；不计 main 之前 import |
| 完整正式生成 child | **574.253795 s** | **661.772195 s** | **1,405,755,392 B** | 包括 import、初始化、codec/readback、观察与等待的 codec child |
| 主分析 child | 4.231607 s | 3.519267 s | 37,298,176 B | 读取既有证据与统计，不重新生成/ASR |
| 独立只读审计 | 5.367946 s | 未单独测量 | 未单独测量 | exec-tool wall；内部审计时钟为 5.269652 s |

正式运行内部时钟另记录 569.666583 s wall、352.162156 s Python CPU 和 304.017048 s codec-child CPU。这些范围包含在 whole-child 范围内，不能重复相加。RSS 是所记录的峰值，不是全部进程同时驻留内存的加总。上述成本来自共享研究主机，没有专用主机延迟或部署 SLA 含义。[分阶段成本](RUN_COSTS.json)、[whole-child 原始记录副本](evidence/CONFIRMATION_PROCESS.json)、[主分析 receipt](ANALYSIS_PROCESS_RECEIPT.json)、[审计执行 receipt](review/EXECUTION_RECEIPT.json)

另保留旧来源 preflight 的 7.894489 s whole-child，以及被拒绝 V2 guard 的 3.981812 s whole-child；它们不计入 768 次正式生成的成本。ASR 资格、先前模型训练和本次封包也不属于上表中的正式生成 child。

执行顺序固定为 seed 17、29、43，各 seed 内 mean 后 entropic，且跨请求保留实际 waveform cache。因此 profile 间时间差只能描述，不能用于推断某个训练目标因果地加速了执行。mean/entropic 的 generation+codec 平均分别为 242.479/248.195 ms，whole-request 平均为 732.647/736.698 ms；对应 whole-request p95 为 4,426.196/4,373.632 ms。观察开销、冷计算和缓存均保留，没有只报告便宜路径。

## 6. 独立审计与完整保全

审计脚本在本次中途质量未知时准备；完整 child exit 0 且主分析完成后，第一次执行即通过。它不 import 主分析的统计函数，也不重新运行模型、ASR 或 codec。独立检查包括：181 个 pins；六 arm 初始化/训练 schedule/checkpoint；官方 source 元数据与像素 SHA；240 条实际公共 speech 文件；768 个唯一 seed/profile/case 和完整 observation；3,072 个输出 SHA；真实 writer/speaker 连通图；PCM event 身份、原 transcript/parser/ensemble；四模态、严格 joint、utility 及全部注册 CI/gates。

统计从各簇的整数 utility histogram 和成功计数重建，用独立的 `math` 公式与线性分位数，仅复用原 seed 的随机 resample 序列以比较相同抽样。最大数值差为 **1.1102230246251565×10⁻¹⁶**。图像/视频神经分类与已保存解码观察通过文件身份绑定，没有把本次只读审计说成独立重新分类或重新解码。[审计准备](review/PREPARATION.json)、[审计结果](review/AUDIT.json)、[审计源码](review/audit_completed.py)

完整本地证据包由 [PACKAGE_DEFINITION.json](PACKAGE_DEFINITION.json) 明确枚举，最终状态和 archive SHA 见 [EVIDENCE_ARCHIVE.json](EVIDENCE_ARCHIVE.json)。它包含整个 joint 执行目录、六个模型、训练进度、旧来源 preflight、V2 真实失败、执行源码 snapshot、全部正式媒体/观察/日志，以及本目录的源代码、结果与独立审计；协议引用的 repo 内媒体/共享 helper 也以其原始字节进入包。

较大的既有输入通过 [INPUT_CUSTODY.json](INPUT_CUSTODY.json) 逐身份链接到已完整验证的 shared、source、旧 media、新 media 和 ASR 资产档案。映射覆盖训练初始权重、实际 speech fit/joint 录音和 V3.1 资格文件；不是仅列一个笼统资产目录。codec 可执行文件记录实际绝对路径和 SHA，运行环境的动态库/完整 OS 镜像不由这些研究档案声称覆盖。封包会验证链接档案的完整 SHA，并在关闭新档案后重新读取每个成员验证字节；原始文件保留，不上传。

[COMPLETION_SUMMARY.json](COMPLETION_SUMMARY.json) 是注明省略两个大字段的摘要投影；完整 1,038,137-byte `completion.json` 的 SHA 为 `047d3454c74c58830aed530241561b5f9ba52c8cca83baf2a0d5dc3ad32f33a3`，保存在包内 `runs/next-joint/confirmation-001/completion.json`。进程小 JSON 的副本则逐字相等，见 [复制 receipt](evidence/EXACT_COPY_RECEIPT.json)。归档闭合完成执行与证据保全，不把失败的科学门改写成通过。
