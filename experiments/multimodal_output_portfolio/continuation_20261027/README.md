# Hepta NDU output portfolio：六项工作继续验证

本轮从 `63f198ad85cfa2aa579032256355f446cfe793a0` 的精确代码与原始证据恢复，
继续推进六个工作项。最实质的进展是：**未来备份与真实原 owner/研究 host 执行
接通；交付后的数值反馈改变后续实际动作与收益；生成模型更新获得新的实际输出
收益并保留原能力。** 同时，新的联合 likelihood、风险加权生成器目标以及自然
任务的动态分配器没有通过各自的优势门槛。这些失败保留为结果。

本目录新增独立研究代码和可审计记录，原生产 owner、runtime、journal、witness
与权限代码保持原样。旧失败记录不重写，生产语义准入没有通过。四个研究模块
目前仍不是一个已完成的全模态基础模型训练与推理系统。

## 对照用户的六项要求

| 优先级 / 工作 | 本轮取得的结果 | 当前边界 |
| --- | --- | --- |
| P0 联合证据 | 物理事件/alias 去重；目标 joint prior 与 observation likelihood 分别验证；4,000 个新真实 WAV，20 个 speaker 分组 | 相关目标 prior 有实际输出收益；新 8-speaker likelihood 优势门槛未通过 |
| P0 未来备份与真实执行 | 原 `AgentdNeuronOwner` 上 240 个实际 episode，3,840 次 owner API，9,600 次含恢复验证的 kernel 执行；未来拒绝、状态、最终结果和完整任务费用一致 | 已知有限环境中的研究 host 组合；native 信号仍 DENY_ALL；生产语义 calibration 未通过 |
| P0 风险可识别任务 | 实际动作具有不同目标损失、运输尾部损害、价格与修复成本；mean 与 entropic-risk 在 3/16 个公开 context 选不同初始动作 | 证明偏好能改变真实动作与尾部取舍；不等于平均收益或准确率必定提高 |
| P0 交付后反馈 | 真实媒体读回 → 数值反馈 → 原 neuron eligibility → hold → 后续决策 → 实际 repair/拒绝；相对 zero intervention 收益 +0.036375 | 收益来自避免多余修复/拒绝费；同信息 history 对照完全追平；无语义准确率提升 |
| P1 联合训练 | 新测试 CE +0.117276，保留能力通过；超过原生成器 16 种动作的特权 oracle +0.054343；23,040 个实际图片/文字 bundle | 同预算风险加权 proxy 比均匀 proxy 差 −0.017195；两者使用相同 NDU 控制器；尚未接入自然大模型或原 owner |
| P1 自然任务与控制成本 | 新自然语音、复杂票据图文、真实视频缺帧生成已执行；缓存机制在开发样本上节省实际 CPU 且输出相同 | 新语音/文档/视频分配器的联合质量成本门槛未通过；不能以简单 tone/AVI 当作自然语音视频生成 |

完整的逐项状态和可复核来源在 [ACCEPTANCE.json](ACCEPTANCE.json)。研究方向
仍可实现，但现有证据支持的是其中若干已封闭的模块，而不是全部理论主张。

## 1. 联合目标与联合观察分开建模

[evidence/README.md](evidence/README.md) 和 [METHOD.md](evidence/METHOD.md)
给出模型、数据分组、真实输出和独立审计。

新 AudioMNIST 20 个 speaker 被事先拆成 8 fit / 4 validation / 8 test；
4,000 个真实波形与原 3,000 个 FSDD 波形 hash 无物理重叠。冻结的原 observer
不在新来源上训练。所有 likelihood 比较共享校准边际，避免把边际平滑优势
误记为 joint dependence 优势。

- Paired 相对 independent 的 conditional NLL 差为 −0.002462，配对 97.5%
  speaker 区间 [−0.010331, +0.003682]。
- Speaker mixture 的差为 −0.001394，区间 [−0.024828, +0.015343]。
- 两个预定 coupling 优势门槛均未通过；没有看完测试后改选模型或放宽阈值。

单独的 joint target prior 不读取音频或 CNN 观察。三个事先构造的相关目标任务
中，实际 pair 准确率分别从 31.54%/32.21%/30.38% 提升至
53.13%/48.13%/50.67%；独立负对照没有明确收益。这个结果不能替代 observation
likelihood 的检验，也不宣称自然录音本身服从这些人工指定的目标相关性。

67,200 份 UTF-8 输出全部实际写出并读回，240 次 alias 重复更新检验通过。
独立单位仍是 8 个测试 speaker；派生 pair 和重复录音使用不扩大独立来源数。

## 2. 真实 owner 的未来备份、风险与反馈

[control/README.md](control/README.md) 详细说明研究许可、native 门槛、实际
媒体、费用、持久化身份与完整审计。

备份分支复制原 journal、独立 witness 与事件账本，再通过原 runtime 恢复；
随后运行实际部署会采用的同一段三 tick continuation。执行计入未来 owner
到期、媒体预算、被拒绝修复费、保留已有输出及不可逆损害。预测的是完整实际
策略最后留下的结果，没有把不获准的未来修复计成已交付成功。

Run002 的 240 个实际 episode 中，有 120 个到期 decision abstention、132 个
host 拒绝修复尝试和 44 个真正的后续修复交付。有限环境全枚举中，最终
exponential moment、success probability、任务费用的预测误差均为零，真实
分支的 neuron 状态与备份一致。独立审计重读 1,136 个媒体文件，重放全部
3,840 次 owner API，并核对完整 checkpoint 身份及 host 暴露的语义字段。

正确计算是

\[
M(a\mid c)=\sum_{f,y}p(f\mid a)p(y\mid c)
\exp[-\gamma U(y,f,a,\pi,owner,budget)] .
\]

指数保留在联合期望内部。本任务动作的损失和尾部不同，风险偏好确实能改变
选择。风险策略的平均收益比 mean 策略低，但条件 CE 更高；这就是实际取舍，
不能把 risk-sensitive 直接翻译为所有指标都更好。

对 future-aware 与 blind-future 的配对比较，9/16 个初始动作发生改变，平均
外部收益增加 +0.070996875。Blind-future 是故意保留旧错误的消融对照，
不是最强同信息基线。

对反馈的因果干预固定初始动作。真实初次交付之后，tick 5 接收反馈、tick 6
不增加新驱动、tick 7 的训练 readout 只读取历史 eligibility，然后仍能实际
修复。48 个配对 context-fault 情形中有 16 个后续 proposal 改变，其中 4 个
实际 repair 改变、12 个无必要的拒绝请求被避免，得到 +0.036375 的外部收益。
同信息 history policy 完全追平，严格目标准确率没有改善。

新的持久化 guard 将注册 event ID 与 receipt digest 绑定到原 checkpoint。
同一已确认事件在 live、冷进程恢复和 forecast fork 中重复到达，都返回原回执，
不重复驱动 neuron。冲突 payload 与不完整/篡改账本在状态变更前被拒绝。
这是单 writer、已注册事件身份的机制，不是对任意别名的物理同一性识别，
也没有宣称外部媒体写入具备 exactly-once 保证。

费用审计还找到旧 run001 的遗漏：每 episode 的 16 次 owner API 之外，原本
已有 12 次 journal kernel replay。Run002 又增加 12 次去重账本验证，共
40 次 kernel 执行全部收费。相对旧记录的 −0.0024 收益变化，一半来自补计
旧恢复费用，一半来自新 guard。旧 run001 结果保留，说明见
[COST_ACCOUNTING_ADDENDUM.json](control/evidence/COST_ACCOUNTING_ADDENDUM.json)。

所有 native 输出仍为 DENY_ALL。实际实验媒体写入由另一个只限研究目录的
用户授权 host permit 管理，同时要求 native non-abstention 和预算满足。
新的 calibration 仅验证有限公开 encoder domain 的计算一致性，绝不能替代
旧的 selected-action semantic ECE 失败。生产权限与生产语义资格没有因此获得。

## 3. 生成器收益现在可归因，但风险 proxy 仍失败

[joint/README.md](joint/README.md) 与 [METHOD.md](joint/METHOD.md) 给出完整
目标、训练计数、选择规则、实际媒体、oracle 和独立审计。

| 新测试比较 | CE 差 | 配对 97.5% source-pair 区间 |
| --- | ---: | --- |
| Risk-weighted update − original | +0.117276 | [+0.098386, +0.136516] |
| Uniform update − original | +0.134471 | [+0.115402, +0.153328] |
| Risk-weighted update − uniform update | −0.017195 | [−0.026919, −0.008027] |
| Risk-weighted update − original 16-plan oracle | +0.054343 | [+0.036804, +0.072227] |
| Risk-weighted update − original，clean retention | +0.031772 | [+0.008442, +0.056121] |

两种更新使用相同的 actual exponential-moment NDU 控制器，只改变生成器
supervised proxy 的样本权重。每 seed 各运行 600 次更新、相同 batch/noise、
所有四计划的 codec/observer/teacher 调用和相同 validation grid。均匀权重
对照不是 risk-neutral controller；原 frozen 模型也不是同训练预算对照。

512 个新测试 pair × 4 个条件、另外 512 个保留能力 pair，均排除原恢复语料
中的像素来源。所有模型选择在新预测与 audit observer 加载前冻结。三个固定
seed 都获得真实输出收益、都超过原 16-plan oracle，也都落后于 uniform proxy。
23,040 个交付 bundle 和 98,304 个 oracle candidate bundle 被逐个读回审计；
另用独立公式重建 CE、bootstrap 区间及门槛。

Oracle 在同一噪声、两步深度和旧 decoder 下遍历所有 16 种动作，允许额外
搜索和真实目标选择。它是归因上界，不是同信息/同计算预算的部署竞争者。
新模型超过这个有限上界，说明收益不能全由旧生成器的更好路由解释。
它不证明任意生成空间、任意噪声搜索或长时域的全局最优。

生成器仍使用 reconstruction/caption/semantic proxy，风险权重是 detached
小批次归一化项。它不是离散实际收益的无偏梯度。当前负结果要求修正或替换
该训练目标，不能用“总收益比旧模型高”宣称 NDU 风险加权训练已胜过强基线。

## 4. 自然任务与实际控制成本

[natural/README.md](natural/README.md) 保留完整来源、预冻结协议、失败尝试、
实际媒体与审计。新研究包括自然语音转写、真实票据图文输出和真实视频缺帧
像素生成；其范围均在各自协议中明确。

- 新语音测试中，cheap→strong cascade 比固定 strong model 的 WER 差
  +0.024276，95% speaker 区间 [+0.00554, +0.04526]。Validation 选择零
  continuation；与固定 tiny 相比输出完全相同，却多耗 +0.07967 CPU 秒/条。
- 明确强制 continuation 的开发集缓存检验，48 份输出完全相同，平均节省
  0.4559 CPU 秒/条，区间 [0.41447, 0.49925]。这是机制验证，不是新资格
  测试的动态分配优势。
- 新票据 held-out 输出中，原规则 41/96 个字段精确正确；learned base
  31/96，全部 refine 33/96 且成本约 3.1 倍。Selective 选择不 refine，
  未获得质量成本联合改善。它生成答案 JSON 与标注图，不是新自然图像合成器。
- 视频完成 432 份实际生成 PNG，覆盖 3 个新源 clip、36 个目标帧及 6 个
  arm × 2 次重复。训练后的四参数像素 mixer 比 pure-flow 高 +0.147685 dB，
  但相对 zero-initialized mixer 的训练归因区间跨零。动态分配选择全部
  motion，输出相同却增加 +0.004893 CPU 秒/帧，成本门槛失败。

视频在预处理和生成前修正了同 batch target↔endpoint 重叠，不能让某个样本
的私有目标通过另一个样本的公开端点进入 allocator。统计单位是 3 个源 clip，
不是数百帧或重复运行；该结果不支持广泛视频总体推断。

## 5. 对完整训练与推理系统的含义

当前可复用的实现是：事件级联合证据、含资源与 owner 的实际 continuation、
可识别尾部效用、交付后状态反馈，以及 actual-output moment controller 加
生成器训练/保留能力约束。它们使下一阶段实验有明确接口与反事实对照。

还没有被本轮建立的主张包括：自然全模态生成器的共同训练、生成网络内部与
原 Hepta owner 的端到端接通、一般未知环境概率的校准、production semantic
qualification，以及不受限 Merton/HJB/NDU 问题的全局最优解。

[ARCHITECTURE.md](ARCHITECTURE.md) 写清了从原想法到系统接口的数学形式、
已实现部分与下一阶段应替换的 proxy。下一阶段优先修正风险生成梯度与
强基线下的自然控制开销；不应扩大到大模型训练后才发现这些问题。

## 证据与复现

四个原始证据包的位置、SHA-256、成员验证与依赖见
[EVIDENCE_INDEX.json](EVIDENCE_INDEX.json)。包中保留失败、开发修订、预冻结
记录和实际输出。逐项测试、独立审计及最后格式化结果见
[VALIDATION.md](VALIDATION.md)。代码按研究依赖拆分提交，审阅顺序见
[REVIEW_STAGES.md](REVIEW_STAGES.md)。

本轮正结果、负结果和未覆盖范围共同决定状态；没有用改名、换 baseline、
放宽门槛或把模拟输出当真实媒体的方法将未通过项目标为完成。
