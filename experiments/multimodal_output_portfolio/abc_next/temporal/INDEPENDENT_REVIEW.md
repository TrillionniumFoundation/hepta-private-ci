# Temporal 原型：独立只读审查

## 1. 审阅范围与结论

本审阅由负责原生接入方向的另一 agent 完成，范围为 temporal 实现、冻结协议和静态来源元数据。**审阅期间没有读取正在运行的 evaluation outcomes、效应值或结果汇总，没有修改被冻结的代码、策略、参数或阈值，没有运行额外实验、测试或 global fmt。** 本文件是独立的非 CORE 审阅说明，不属于原冻结评估代码，也不补造新的预注册事实。

在所读代码范围内，**未发现私有 target、Whisper 终端评分或实际未来候选结果进入控制决策，未发现 fixed/initial-only 基线被剥夺动作权限，也未发现把策略重放行数当作独立自然来源的统计实现错误。** 可以继续执行原协议要求的完整 census。该结论是对信息流、动作权限、统计单位和成本实现的审查，不是对尚未观察的质量、收益、最终媒体或 timing 匹配结果的通过声明。

本轮所谓“独立”指由另一工作方向的 agent 进行只读核对，不是外部组织认证、生产 trust authority 或独立数据 owner 的资格签名。

## 2. 冻结身份与来源 census

实际读取的 [evaluation_protocol.json](freeze-v1/evaluation_protocol.json) SHA-256 为：

```text
9d74cc54fec42e9828b1b5bc110e861456d1d3bec1d0634507dd207cee038c2b
```

审阅时逐文件核算了协议指定的 11 个 CORE 文件，全部与冻结 SHA 匹配：`analysis.py`、`audit.py`、`episodes.py`、`external.py`、`facts.py`、`parallel_matrix.py`、`policy.py`、`registration.py`、`speech.py`、`stream.py`、`timing.py`。复用的 `abc_recovery/statistics.py` 与 source manifest 的 SHA 也匹配。该检查只读取代码和静态源元数据，没有打开 evaluation-run 的生成结果。

[sources.json](freeze-v1/sources.json) 将 128 个不同的 number/color/direction 组合划分为：

| 角色 | 组合数 |
| --- | ---: |
| Development | 16 |
| Fit | 32 |
| Qualification | 16 |
| Evaluation | 64 |

所有 128 个 source ID 与事实 tuple 均唯一，角色之间没有重复 tuple。这证明的是该构造任务的组合分工。它不把共享词表、模板和声音变成独立自然来源；本实验只有一个模板族和一个 voice。

## 3. Whisper 是否仅用于独立终端评分

[external.py](external.py) 的 `ExternalObserver.observe()` 只接收实际 WAV 路径。它没有 intended text、target fact、source ID、candidate list 或 grammar 参数；解码配置明确关闭 target prompt、prefix、hotwords 和 previous-text conditioning。识别对象是重新读取、重采样后的真实 PCM。

[episodes.py](episodes.py) 在候选的未来语音合成、输出提交与 `finish()` 完成后才调用外部 Whisper。此前的 initial/feedback 决策使用的是初始公开 cue、后续公开 cue、公开 posterior，以及实际内部草稿的 Vosk 解码。最终 Whisper observation 和 metrics 进入 outcome 记录，未回流到已完成的决策。

[policy.py](policy.py) 的 fit 路径只使用在线 Vosk 的 terminal net utility 构造 `exp(-2 × utility)` 标签，并明确拒绝含非空 `external_terminal_observation` 的 fit 数据。Best-fixed action 也只根据 fit 的 Vosk CE 选择。原有 qualification 可以使用 Whisper 检查冻结 observer；不能把这个测量角色与策略训练混淆。

因此，代码支持“分离的模型与观察者角色”。它不证明 Vosk 与 Whisper 的预训练语料完全分离，也不证明二者识别误差统计独立。ASR 解析的事实正确率仍不是人工听辨评价。现有文档已保留这些限制。

## 4. 非预知信息边界与延迟观测的真实含义

### 4.1 当前策略的实际依赖

[facts.py](facts.py) 的 policy feature adapter 只接受 `PublicFrame`。该类型没有 target、source identity、scenario identity、RNG state 或 future terminal output。Initial-only 特征读取 initial 与 initial quality；其代码不读取 fresh、posterior 或 probe。Feedback 特征增加公开的 fresh cue、quality、posterior 摘要，以及真实草稿解码的置信度、缺失和一致性统计。

`episodes.execute_case()` 在最初生成 draft 前计算 initial-only gate。随后生成并提交 neutral prefix、合成内部 draft、实际运行 Vosk，才计算 feedback gate。反馈决策经 [audit.py](audit.py) 的 create-only JSON 写入、flush 和 fsync 完成后，代码才进入未来候选 TTS 循环。终端质量评分位于该循环内部、候选输出完成之后。没有看到终端 scorer 值或 hindsight oracle 参与这些决策。

### 4.2 必须准确描述预采样 cue

`owner_public_frame()` 在 episode 开头已经采样了 initial 和 fresh 两组 cue，并构造 posterior。Initial-only adapter 不读取 fresh/probe 字段；executor 在 prefix/draft 阶段之后才允许 feedback 使用它们。

因此，本轮支持的是**受控环境中通过特征可测性实现的延迟释放**。不能把它描述为运行中从外界实时采集的新传感信号，也不能说初始 Python 对象物理上完全不含 fresh 字段。当前冻结函数实际忽略这些字段，因此没有发现策略利用该提前存在的数据。它是可审查的 Python 信息边界，不是对任意恶意代码的 OS 隔离保证。

Temporal agent 已确认将这个事实写入非 CORE 文档，不更改冻结代码。

### 4.3 延迟收益的范围

Neutral prefix 没有任务事实收益；共享语义修正在后续两块新文本和语音中体现。这里有真实输出提交、真实后续合成和真实观察，但只有一个在线 action gate。不能从中推导多次反馈决策、长时域条件价值递推、一般 Merton 型最优控制或全局 portfolio optimality。

## 5. 共享语义 clamp 与强基线是否公平

正常动作族固定为 `keep/fuse × normal/slow`。`action_fact()` 对所有 fuse policy 使用相同的公开 posterior-MAP operator；fixed 和 initial-only gate 选中 fuse 后，也能使用相同的合法后续 cue。Initial-only 限制的是动作 gate 的信息，而不是把已选 fusion operator 的后续条件输入删除。

Best-fixed 来自 fit 数据，且四个 fixed actions 均单独保留。另有 initial-only、feedback-no-probe、公开先验风险参考和事后 oracle。公开先验参考使用明确的 factorized posterior 与 gamma=2 风险目标，并声明假设完美声学可懂度；它不是实际 ASR 或有限测试子集的已证明最优解。事后 oracle 仅在实际执行全部候选后选取，代码中没有回到在线控制器的路径。

`fuse_clamp_normal` 是单独的机制干预。它与 `fuse_normal` 使用相同的已经提交 prefix、normal 语速、两次未来语音合成和相同 `.02` fuse proxy penalty；差别是将语义状态固定在 initial。它不会因免除 fuse 罚项得到人为优势。该干预不属于可学习控制器的四个常规 action outputs，解释时应继续称为机制 clamp，而不是第五种可任意选择的常规动作。

[stream.py](stream.py) 对文本与 PCM append 进行 flush/fsync，并记录连续 sample/text spans 和哈希链。候选重用共同 prefix 是同一已提交前缀的受控 fork；后续语音通过实际 TTS 调用新合成。源码还核对候选 prefix 的 PCM/text SHA 与原 prefix 一致。是否每个最终实例都通过这些检查，应由完成后的原始执行与 aggregate 证据说明，本审阅没有打开那些结果。

共享语义更新改变后续文本和语音是本任务的预定义机制；其正向净收益和反馈必要性仍必须由冻结对比与消融的实际结果支持。优于单个 best-fixed action 本身不足以证明实际草稿反馈不可替代。

## 6. 统计单位、seed 与效应解释

[analysis.py](analysis.py) 的质量 cube 结构为 `[5 critic seeds, 64 fact groups, 1, 4 scenarios]`。复用统计实现对 source/fact 与 seed 两轴进行交叉重采样，并对比较双方使用相同 indices；四个场景留在相同 fact group。CE 在每个 critic seed 内先计算，再跨 seed 算术平均，没有将训练 seed 当作额外生成结果放入同一风险分布。

固定策略、clamp 和 oracle 在 seed 轴重复，是为了与五个 critic 策略进行配对；重复本身没有产生额外信息。五个 seed 是 critic 参数拟合的随机种子，不是五个独立训练的声学模型、五个 voice 或五份自然数据来源。

完整 census 校验覆盖 source/scenario 唯一性、五个实际 candidate paths、每个冻结策略的重新计算结果、实际输出和 scorer 输入 SHA，以及所有 cube 的有限完整性。来源组合数是 64，不是 256 cases、1,280 candidate paths 或 seed 展开后的更多行。

仍然需要保持原协议的统计范围：一个模板族、一个 voice、有限组合域、少 seed 的 percentile 区间、有限场景 CE。它不提供跨模板、跨声音、自然开放域或未知来源 cluster 的总体覆盖保证。Realized-target positive-value MSE 包含实际 outcome 变化，不能冒充真实条件期望误差或 conditional-value oracle。

## 7. 双 worker 与成本口径

[parallel_matrix.py](parallel_matrix.py) 使用两个 spawned worker，按冻结 source index modulo 2 分片，同一 fact 的四个 scenario 均按序留在该 shard。Worker 在构造模型前设置单 CPU affinity。Piper ONNX intra/inter threads 为 1，Whisper CPU threads/workers 为 1。

Temporal agent 依据实际工具启动记录确认：正式命令显式设置了 `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`，worker 通过 spawn 继承。其补充的 [launch_receipt.json](freeze-v1/launch_receipt.json) 明确是**启动后从实际命令抄录**，不是当时自动采集的逐 worker environment attestation。本审阅没有读取 evaluation outcomes 来判断资源状态。

Parent 的 monotonic wall 测量覆盖 worker 启动与完整 matrix；parent `process_time` 加上已回收 child 的 CPU 增量构成 parent-plus-child CPU。两个 worker 的 per-case wall 总和是 worker occupancy，不能当作单一全局 elapsed wall。各候选的 `online_component_cost` 是已量测 common 与 selected branch 的组件和，common 包含本次 matrix 的所有 policy decision 开销，不是某单策略独立串行 latency。

[timing.py](timing.py) 另外执行 best-fixed 与 feedback/17 的实际选定路径，单 CPU、交替顺序，计时覆盖 prefix/draft TTS、Vosk、所选 gate、两块未来语音、持久化和 readback。其终点是 durable WAV/text，不是声音播放结束或网络交付。两策略均支付 common probe；未测量省略无用 probe 后的部署专用 fixed 优化。

`.02` fuse 与 `.01` slow 是声明的 proxy penalties，不是毫秒、CPU、金钱、能耗或已经验证的部署价格。实际收益是否覆盖真实成本，不能由这些罚项自动推出。

## 8. 三项必须由最终证据闭合的收尾审计

以下结论在本次审阅时尚未由最终运行证据验证。不能因源码合理或作者已安排检查就追溯写成“已经通过”。无需调整已冻结代码、参数或阈值；可以依据保留字段补充只读审计和准确的报告解释。

### A. Timing 波形与质量矩阵的一致性

`timing.py` 记录 `identical_wave_to_quality_matrix`，但值为 False 时不会拒绝该行。随后 compact analysis 从 timing report 删除逐行 rows。因此，最终必须另外汇总所有 256 次 timing 执行的匹配/不匹配数量，保留原始逐行身份。

如果存在不匹配，不能直接把主矩阵语音质量当成这些 timing 产物的质量。可用同一冻结 Whisper 对实际 timing WAV 做明确标注的描述性核查；该核查不能替换主评估、增加独立 N 或改变主阈值。Temporal agent 已安排独立 `TIMING_AUDIT`，本审阅没有读取其结果。

### B. Seed 展开后的 component cost sum

`analysis.py` 中 `component_cost_ms.sum` 与 `n_rows` 沿五 seed 轴展开。Fixed、clamp 等条件的同一物理测量会重复五次。其分布 mean/P50/P95 可以在明确口径下使用；`sum` 不能解释为 unique physical executions 的真实总 CPU 或总墙钟。

实际总成本应使用 `evaluation_run` 的 global wall/parent-plus-child CPU；`matrix_total_case_cost.wall_ns` 必须继续解释为 worker occupancy。不得把五次复制的 fixed 成本或全部策略 potential outcomes 的展开数量写成额外真实执行次数或独立样本数。

### C. 非预知顺序保证与时间戳审计的区分

Analysis 实际检查 `prefix_committed_ns < fresh_released_ns <= decision_done_ns`、decision digest 和冻结策略重算。它没有独立比较每个 candidate 的绝对创建时间。

Before-future 保证来自被冻结的 `execute_case()` 调用顺序，以及未来 candidate 循环之前完成的 decision JSON fsync。报告应准确写成这些保证；不能声称 analysis 还完成了未实施的“candidate 创建时点独立审计”。Temporal agent 已确认收窄这一非 CORE 文档表述。

## 9. 最终范围判断

本实现可以检验真实文字/语音 continuation、有限共享语义传播、外部终端测量和实际成本。它保留了强基线、实际草稿观察与独立 terminal observer，信息流和配对统计设计在所审范围内成立。

它仍是固定模板文本 decoder、固定 pretrained acoustic backend 与小型 critic 的受控任务。当前证据不自动支持端到端语义/声学生成器共同训练、多次在线反馈、自然来源泛化、人工感知质量、video/AV 同步、生产 native admission 或全球最优输出 portfolio。

本审阅没有把工程代码审查等同于 numerical gate 通过。最终正负结论必须来自完整冻结 census 与上述收尾审计；失败与不确定性均应原样保留。
