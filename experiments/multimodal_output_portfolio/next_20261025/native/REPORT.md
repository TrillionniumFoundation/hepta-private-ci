# 原生 owner 执行真实 NDU 动作价值策略

## 结论与证据边界

这轮已经把原来只按 correctness 最大值选择动作的研究接口，接成了**原始 `AgentdNeuronOwner` 实际加载模型权重、执行条件 entropic NDU head、在原准入门允许的动作中选择、提交决策、真实生成、观察后写入原 NDU projection store，再继续决策和恢复**。`stop` 是已实际评价的新动作：保留当前真实草稿并输出；没有通过准入的空动作仍是拒绝，不计为成功停止。

原生正式实验使用冻结后首次开放的 96 对来源，来自 24 个独立 writer。三种策略各执行 192 个请求，共 **576 个真实请求、2,304 次 owner tick、247 份实际 PNG/text 输出**。其中 216 次执行了额外生成，31 次停止并输出已有草稿。50 项在线拒绝检查和 6 次恢复全部通过；三个策略各自三个原生进程的原资源门都通过。独立只读审计重新核对全部媒体 SHA、观察分数的组合公式、控制日志 hash chain、NDU projection 二进制日志、动作选择、配对来源及数值误差。[RESULTS.json](RESULTS.json) 保存完整结果，[analyze.py](analyze.py) 保存审计与预注册统计实现，[AUDIT.json](AUDIT.json) 保存已执行的独立审计结果。

**策略优越性没有得到证据。** 在相同新准入 head、相同动作空间、相同实际访问和成本记录下，NDU 相比 correctness argmax 的 CE 差为 **−0.019803，writer-cluster 95% 区间 [−0.090560, 0.014378]**。两者 joint correctness 都是 83/96。NDU 的平均请求阶段成本略高，区间跨零，不能宣称质量收益覆盖了控制开销。相对旧 legacy 的明显改善同时改变了准入 head 和动作支持；不能把它归因于 NDU 选择规则。

新准入 head 通过的是预注册的**五动作合并校准门**，不是每个动作、每个被选择子集都通过同一门槛。独立资格的总体 ID ECE 为 0.028905，紧贴 0.03；逐动作 ID ECE 中 text 为 0.045884、couple 为 0.040181。正式执行里选择后 ECE 为 NDU 0.039411、同准入 argmax 0.093951。上述差别都保留，未调整门槛、校准器或正式样本。

## 实际模型与原始 owner 的接口

原始 owner 源来自 product commit `985a52e84cdaed7c8d4c363f30bc8841c5e3730c`，SHA256 为 `4d56cc99d0edb1018734aebf70dc715de8df7846a2a9c4f2edb4230a0fc87faf`，编译副本未修改。依赖来自固定 commit `9595221c21f1fe0775295a9c8756a1ba4d69ea49`：恢复并逐 SHA 核对 428 个官方源文件，实际重新构建 22 个原生核心 crate。这里没有构建或运行整个 Agentd daemon。

使用原先已冻结的 seed-17 `output_ndu` generator、独立 reward observer、公共 semantic sensor，以及 `abc_next.value.Controller` 的 enriched、hidden=32 条件 moment 模型。其动作顺序保持 `stop / refine_semantic / refine_image / refine_text / couple`。NDU gamma 为 2，后续动作的 0.002 成本已经包含在 teacher 的条件 moment 标签里，native 不再重复扣除。

接口使用 511 个 Q24 公共坐标，在原最多 512 维接口以内：原公共前缀 478 维、当前 horizon 的 teacher hidden 32 维、horizon 标志 1 维。归一化及 teacher 第一层、draft CNN 和公共 sensor 由实际 Python encoder 执行；native 执行 frozen teacher 的最后一层及 softplus，并执行新 correctness head。这个拆分保留原 teacher 函数，所有 encoder 的实际成本计入请求计时，没有把额外 CNN 当成免费输入。[encoder.py](encoder.py)、[value_head.rs](value_head.rs)、[online_port.rs](online_port.rs) 定义实现。

本轮限定 H1：实际 `initialize → refine_image` 后的公共草稿。H2 请求明确拒绝；虽然模型包保留原 H1/H2 value 层，本次没有授予 H2 准入资格。H1 的 `refine_semantic` 对当前输出严格劣于停止，五个候选仍实际执行原 owner tick，但选择时排除该动作。

新 correctness head 是 teacher hidden 上的 32→5 sigmoid，共 165 个离线参数。其输出通过固定校准器成为原 owner 的 probability carrier；其余 32 个 receipt 坐标明确为零，不冒称未来状态预测。原 confidence/OOD 算法、模型校准门与资源门保持不变。在线进程每次启动只解码权重一次，没有在线训练步。`encoder.py` 开头沿用的“original correctness”措辞是早期拆分说明；正式包实际使用这里明确记录的新 165 参数 correctness head，冻结代码未为改说明而改写。

三种策略分别持有自己的真实 owner 和存储：

| 策略 | 选择规则 | 准入与动作支持 |
| --- | --- | --- |
| `ndu` | 原生计算的条件 entropic moment 最小值 | 新五动作 head；H1 排除 semantic |
| `correctness` | 校准概率最大；固定 tie 顺序 text、couple、image、stop | 与 NDU 完全相同的新 head 和候选集合 |
| `legacy_correctness` | 原先冻结的 correctness argmax | 原 executable、原 head 与原 text/couple 两动作 |

同准入 argmax 是隔离 NDU 选择贡献的主对照。它也执行同一公共 encoder 和 native value 层，确保相同信息访问；其测得成本是这次真实实现成本，不代表其经过单独极致优化后的最低成本。

## 新准入 head 的训练、校准、资格次序

训练仅使用旧 `forecast_fit` 的 256 对来源；旧 `forecast_calibration` 的 128 对只用于预先固定 cuts。输入与标签均为真实 `refine_image` 子节点的 H1 对齐，未把 root 的标签混称为同一决策。1200 个离线优化步训练 165 个参数；teacher NDU value 权重未改。旧 development selection BCE 为 0.258099，raw confidence≥0.75 的比例为 0.585826。这些旧来源不增加新统计样本数。

之后严格按三份冻结协议执行：

| 阶段 | 独立来源 | 实际工作 | 冻结依据 |
| --- | --- | --- | --- |
| 新校准 | QMNIST 96 对、12 个新 writer | 6 views × 2 futures × 5 actions，共 5,760 个实际输出 | [CALIBRATION_PROTOCOL.json](CALIBRATION_PROTOCOL.json) |
| 独立资格 | XNIST 1,000 对、1,000 个完全新 writer | 每个 writer 一个循环 ID view、一个 both_missing view，五动作共 10,000 个实际输出 | [QUALIFICATION_PROTOCOL.json](QUALIFICATION_PROTOCOL.json) |
| 原生正式执行 | QMNIST 96 对、24 个另行保留 writer | 2 views × 3 policies，共 576 个实际请求 | [NATIVE_PROTOCOL.json](NATIVE_PROTOCOL.json) |

QMNIST 本轮分配排除了原 70,000 MNIST 所有角色的 writer 与样本；XNIST 资格进一步排除了全部 QMNIST train/full test 的 1,074 个 writer。三阶段彼此无 writer 交叉。独立资格固定 1,000 writer 一次执行，没有根据结果增加样本。原生统计以 24 个 writer 为单位，不能把同一 writer 的四对来源当成四个独立 writer。根来源分配文件与加载器提供每个实际样本、writer、官方数据 SHA 的对应关系。

所有校准/资格 branch 先将公共预测、feature、moment、时间和身份提交到文件，再真实生成所有动作，保存 PNG/text、重新打开并核对，再用冻结 observer 评分。新校准只拟合三个预先固定 ID bin 的经验正确率及一个可见全缺失 bin，未重新拟合神经权重或选择 cuts。

### 原四门的实际结果

| 门 | 原阈值 | 独立资格结果 |
| --- | ---: | ---: |
| ID 与全样本 point ECE | ≤0.03 | ID 0.028905；全样本 0.014653 |
| OOD false acceptance | ≤0.004999 | 0/1,000 writer |
| ID 非空准入比例 | ≥0.25 | 0.9398 |
| OOD 单侧 95% 上界 | ≤0.004999 | 0.00299125 |

校准数据也满足对应 point ECE/FAR/非空门；仅独立资格的 writer 级零错误样本提供上述 OOD 上界。原生包核对 predictor、calibrator、verification 的真实 SHA 和数值，未把一个 `qualified=true` 布尔值当作全部资格证据。原门没有放宽。

**这个 ECE 是 point estimate，不是总体 ECE 的置信上界。** OOD 定义是公共输入中的 complete absence，不包括一般语义错误、对抗输入或其他分布偏移。逐动作 ID ECE 为 stop 0.025379、semantic 0.022744、image 0.026887、text 0.045884、couple 0.040181。事件中的 `all_actions_independently_qualified` 字段应按“全部动作在独立来源上实际评价并共同通过预注册合并门”理解，不能按字面解读成五个各自通过 0.03 的资格证书。新头的资格也不证明 NDU value calibration、全局最优或生产授权。

## 真正的决策、生成、反馈和恢复

[online.rs](online.rs) 使用原始 owner 对五个候选逐一执行真实 tick，候选只能读取同一动作前公共 prefix。控制器记录候选实际计算值、准入、选择、原生 sequence、此前 NDU modulator，并将 hash-chain 决策同步写盘后才返回选择。运行器收到自己的决策以后才为所选动作抽取未来分支随机数，并实际执行 generator。

实际输出保存为 PNG/text，重新读入，和生成的像素/文字逐项一致后才交给独立 observer。native 校验 pending request、decision digest、所选动作、observer 身份、真实媒体 SHA、时序和 utility 范围，再调用原 `NduProjectionStoreV1` 提交并选择 utility projection。下一次 tick 绑定的是已经提交的 modulator，不能读取未来 outcome。独立审计重算三个 control journal 的全部事件 digest，解析三个二进制 projection journal 的 sequence、predecessor、entry digest、utility/selection 对应关系及最终 frontier。

后验 NDU 被真实保存并进入下一 tick 的绑定，但这不意味着 teacher 因新反馈而在线学习。冻结 teacher 没有参数更新，也没有把跨请求的历史 utility 当成新增公共 encoder 坐标。本轮建立的是原生因果执行和状态延续，不是动态反馈导致独立策略增益的另一项实验。

正式每个策略都经历一次“决策已持久化、未来生成未开始”的 SIGKILL，恢复后继续该 pending 动作；中点另经历一次已提交观察后的正常关闭/重开。六次恢复比较完整 frontier、pending identity、NDU modulator、objective、请求数、outcome 数及 native sequence，均精确一致。新 owner 运行跨越 128 tick 分段边界。50 项非法请求/观察绑定检查均拒绝，拒绝前后 owner 状态不变。

## 正式输出与强对照

每个策略都面对完全相同的 96 个 ID 输入和 96 个 both_missing 输入，按预先固定的循环顺序交错执行；初始化与动作未来种子配对，但每个策略真实支付自己的 prefix、encoder、native、生成与观察工作。审计确认全部 192 个公共 prefix 配对一致；三策略之间 43 对选择了相同动作的输出，实际媒体字节及分数也完全一致。

| 策略，192 请求 | 拒绝 | stop 输出 | image | text | couple |
| --- | ---: | ---: | ---: | ---: | ---: |
| NDU | 100 | 29 | 34 | 8 | 21 |
| 同新准入 correctness | 100 | 2 | 11 | 72 | 7 |
| 旧 legacy | 129 | 0 | 0 | 27 | 36 |

96 个 both_missing 输入在三策略中全部拒绝；新头的 ID 准入为 92/96，旧头为 63/96。拒绝统一记 utility=−1、joint failure，这是预注册的报告约定，不是生成了内容；成功停止才保存已有实际草稿。

主指标为 ID 样本的 `CE = -log(mean(exp(-2 × (utility - 0.002 × continuation)))) / 2`。每个 writer 的四对来源一起重采样；4096 次配对 bootstrap，seed 261025909，报告描述性 95% percentile 区间。

| ID 指标 | NDU | 同新准入 correctness | 旧 legacy |
| --- | ---: | ---: | ---: |
| 平均 utility | 0.841354 | 0.852622 | 0.273939 |
| CE，gamma=2 | 0.360741 | 0.380544 | −0.487537 |
| joint correctness | 83/96 | 83/96 | 59/96 |
| 实际阶段成本，平均 ms | 25.759 | 25.286 | 16.703 |
| 含仪器记录的单请求 wall，平均 ms | 29.187 | 28.556 | 21.430 |

| 配对差：NDU − 同新准入 correctness | 点估计 | writer-cluster 95% 区间 |
| --- | ---: | --- |
| 平均 utility | −0.011268 | [−0.052956, 0.024506] |
| CE | −0.019803 | [−0.090560, 0.014378] |
| joint correctness | 0 | [−0.062500, 0.052083] |
| 阶段成本，ms | +0.472 | [−2.084, 3.479] |

NDU 相比旧 legacy 的 CE 差为 +0.848278 [0.521381, 1.281923]，ID 准入率增加 0.302083。这个比较同时改变了新 head、校准和动作支持，因此只能说明组合变化的效果；主对照没有支持把这些改善归于 NDU 的价值排序。区间跨零不是证明两策略等价，也不是通过非劣效检验。原生正式来源未重新训练或调参。

原 teacher 与 native 在 NDU 的全部 192 个请求上，使用相同准入集合时动作一致。native 相比 NumPy 最后一层的最大 moment 误差为 8.88e−16，相比原 float32 teacher 为 6.16e−7，低于预注册 3e−6；概率层误差为 2.22e−16。这证明数值接入保留函数，不证明函数作出的选择具有质量优势。

## 成本、资源门与保留的失败

原资源阈值保持 p95≤3000µs、p99≤8000µs、model transient≤512KiB、checkpoint≤1MiB、write amplification≤4,000,000ppm。正式各进程的原 `summarize_resource_samples` 都通过。

| 全部正式 tick，按策略汇总 | runtime p95 / p99，µs | whole owner p95 / p99，µs | model transient 最大 B | whole owner 新增堆峰值最大 B |
| --- | ---: | ---: | ---: | ---: |
| NDU，960 tick | 819 / 1844 | 1410 / 3002 | 1639 | 36236 |
| 同新准入 correctness，960 tick | 754 / 2369 | 1322 / 3765 | 1623 | 36244 |
| legacy，384 tick | 858 / 1654 | 1674 / 2749 | 13016 | 36075 |

所有 checkpoint 为 1568B，write amplification 为 530613ppm。共享主机有明显长尾：三个策略 runtime 最大值分别为 14.748ms、61.749ms、29.107ms；百分位门通过不表示没有延迟异常，更不构成部署主机的代表性性能保证。

| 精确 child PID 成本，完整进程 | wall s | user+system CPU s | peak RSS B |
| --- | ---: | ---: | ---: |
| 新校准，5,760 输出 | 40.771 | 38.086 | 349,995,008 |
| 独立资格，10,000 输出 | 111.025 | 94.954 | 1,075,101,696 |
| 原生正式，576 请求 | 15.983 | 13.267 | 377,909,248 |

资格进程加载完整 XNIST 时的内存峰值超过 1GB，应计入成本，不能使用小批生成阶段的内存代替。原生正式约 360MiB 的整进程 RSS 与几 KiB 的 model transient 是不同 scope。`wait4` 的 RSS 是被等待进程及其相应子进程所报告的最大峰值，不是所有同时驻留进程 RSS 的总和。单请求阶段计时排除了故意错误输入和恢复故障的一部分开销，整进程成本保留这些开销；上述单请求毫秒数不能替代整段生命周期成本。

早期 `smoke-001` 在 pending 恢复时真正失败，错误为 `Controller history digest or sequence mismatch`。原因是 JSON 数值中的 f64 在解析/再次序列化后可能差一个 ULP，从而改变 durable event hash。修复后，数学运算仍为 f64，但已提交日志中的 moment 和 raw probability 改为可往返十进制字符串。原失败源码、binary、日志和 2.846s 完整进程成本全部保留。

旧 development 的 `smoke-002` 完成全部闭环，但 legacy 首个进程原资源门失败：p95=7272µs>3000µs。其余 smoke 进程及正式进程通过不能消除这次失败。初始模型包把新增参数数目沿用为 0 的元数据也保留；正式 `model-002` 更正为 165，仅更正 metadata，没有改动数值函数。五次 native 增量构建全部保存源码、依赖 SHA、实际命令、输出与成本。

## 冻结字节和复现

最终 native binary SHA 为 `09fd64c226cff3c87f4b2e06a52e12cd0b819cb707667fb22c624846d963ff5a`；正式协议 SHA 为 `b8fcdfdcab8e39f7f00ab33b51c1a34a936d8ba10246343299631759367d508d`，冻结 42 个实际依赖。仓库原始 `just fmt` 已在最终 build-005 和正式协议冻结之前执行，避免把后来格式化的源码身份填回已执行结果。

校准协议有一项明确的历史路径映射：当时执行的 collector 源码在 `calibration-001/executed-source/collect_qualification.py` 中按原 SHA 保留；后来独立 XNIST loader 确定文件名后，仅将未执行分支的 import 从 `qualification_sources` 改为 `xnist_sources`。旧校准协议未改，资格和 native 协议都绑定当前正确源。审计使用原校准源码快照核对这一个历史 pin，不忽略任何其余身份不匹配。

当前本地原始证据在 `/workspace/scratch/87e43aa872f5/ndu-runs/next-native`；其中 `audit-001/audit.json` 是独立只读审计产物，模型实际执行与失败证据位于各独立目录。审计可以按以下命令复现，输出目录必须尚不存在：

```bash
/workspace/scratch/87e43aa872f5/ndu-next-env/bin/python -B -m experiments.multimodal_output_portfolio.next_20261025.native.analyze --runs /workspace/scratch/87e43aa872f5/ndu-runs/next-native --output /workspace/scratch/87e43aa872f5/ndu-runs/next-native/audit-replay-001
```

再次执行正式来源只能称为重放，不得增加独立 N。审计本身不启动 Torch/ASR、不访问新来源像素、不改变资格和执行记录；它核对已记录的独立 observer 预测，不冒称重新运行了另一套 observer。

## 尚未闭合的部分与代码分期

实际 NDU head 接入、H1 stop/action 准入资格、原 owner 的因果执行、媒体观察、NDU journal 和恢复已有证据。**NDU 选择带来的独立质量/净成本收益、逐动作及选择后校准**尚未通过；这是本轮真实结果，不能靠把失败改成布尔 PASS 解决。更长 horizon、真实 audio/video 原生接口，也没有从这个 H1 数字任务继承资格。

完整 Agentd daemon 与生产 Generator/Observer 服务 transport 尚未执行；当前 generator/encoder 由持久 Python 研究进程承载，native JSON transport 连接真实 owner。`authority=deny_all` 全程保持，没有伪造 Dataset/Generator/Observer/Evaluator 正式身份、签名或信任根，也没有 install、activation 或 applied-update。真实生产 resolver 准入和授权需要外部正式材料；此轮没有调用该生产 resolver，不虚构新的拒绝记录。

这组改动可分为三段审核：先审公共 teacher 拆分与五动作离线资格，再审 native value/admission port 与 durable 日志，最后审真实执行 runner、冻结协议、独立证据审计和负面结论。原产品 crate 和旧研究协议均未为这次实验改写。
