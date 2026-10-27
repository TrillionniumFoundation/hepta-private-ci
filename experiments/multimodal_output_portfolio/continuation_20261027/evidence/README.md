# 联合证据：新的多说话人验证与独立 prior 检验

本轮修复了先前单说话人 paired likelihood 的估计方式与比较混杂，并完成
新的 AudioMNIST 来源测试。**联合 prior 在声明的相关目标任务中改善了实际
输出；联合 observation likelihood 的跨说话人优势仍未通过预定门槛。**
两种结论不能互相替代。

## 做了什么

- 保留原 FSDD observer 的精确参数；没有用新测试来源训练 observer。
- 新增官方 AudioMNIST 的 20 个 speaker、4,000 个真实 WAV。8 个拟合来源、
  4 个选择来源、8 个测试来源完全分开。
- 比较 pooled independence、paired shrinkage 和 speaker-mixture partial
  pooling；对联合表格做边际投影，使三者使用相同的校准边际。
- 测试前冻结选择，保留未知 target 列、重复事件去重和 alias 单因子更新。
- 分别拟合 cue 条件下的完整 joint prior 与 factorized prior；prior 不读
  音频或 CNN 观察，防止把同一观察再算成另一份独立信息。
- 实际写出 67,200 份 UTF-8 digit-pair 输出，读回后评分。

完整数学定义、受控 alias 机制和适用范围见 [METHOD.md](METHOD.md)。

## 观测 likelihood：改进有限，统计门槛未过

测试为 8 个 speaker、1,600 个物理 WAV，派生 16,000 个平衡目标 pair。
以下是 distinct-event 子集的 speaker 平均值：

| 模型 | 条件 observation NLL | posterior NLL | 实际 pair 准确率 |
| --- | ---: | ---: | ---: |
| 独立基线，校准边际 | 2.419049 | 2.802650 | 30.8681% |
| Paired shrinkage，同边际 | 2.416587 | 2.801213 | 30.9236% |
| Speaker mixture，同边际 | 2.417655 | 2.803739 | 30.8819% |

Paired 相对独立基线的条件 NLL 差为 `-0.002462`，配对 97.5% speaker 区间
`[-0.010331, 0.003682]`。Mixture 的差为 `-0.001394`，区间
`[-0.024828, 0.015343]`；其输出准确率差为 `+0.0139` 个百分点，区间
`[-0.0625, 0.0972]` 个百分点。

**条件 NLL 优势和实际输出优势两个预定门槛均未通过。** Mixture 的 posterior
NLL 点估计还略差。没有在测试后改选 paired、独立模型，或另外增加非劣阈值。
原 frozen CNN 在新来源的单数字准确率平均 `54.125%`，speaker 范围
`33.5%–64.5%`，存在明显的输入分布变化。

## 目标 prior：相关任务有收益，独立负对照无收益

这是单独设计的受控目标配对任务，真实波形按公开任务 cue 对应的目标分布
选取。它不宣称自然录音的数字序列本来就具有这种相关性。两种 prior 使用
相同的冻结 likelihood、真实观察和推断成本。

| 公开 cue | Factorized prior 输出准确率 | Joint prior 输出准确率 | 差值的配对 97.5% speaker 区间 |
| --- | ---: | ---: | ---: |
| uniform，独立负对照 | 32.2917% | 32.3333% | [-0.7083, 0.8333] 个百分点 |
| plus1 | 31.5417% | 53.1250% | [14.0417, 28.3333] 个百分点 |
| plus3 | 32.2083% | 48.1250% | [10.5000, 20.2917] 个百分点 |
| plus7 | 30.3750% | 50.6667% | [16.3333, 24.2505] 个百分点 |

三个相关任务的 joint-prior NLL 改善分别为 `-1.076819`、`-1.106477`、
`-1.123324`；均匀独立负对照为 `+0.001087`，区间包含零。

这个实验支持显式联合目标分布的必要性及其在指定任务中的输出作用。Prior
是目标计数估计器，**不是新训练的自然语音神经生成器**。相关任务的生成规律
是事前声明的，不能把其收益说成未知自然目标依赖被普遍学会。

## 开发修订与审计

初始 v1 的 fit/validation 暴露了边际平滑混杂：独立基线可以选择边际强度，
联合族却固定为 .5。v1 未运行测试，完整拟合与执行源码保留。v2 在新测试
特征计算前修复为共享边际与明确的 validation-only 独立选项；详见
[原协议](PROTOCOL.json)、[修订协议](PROTOCOL_V2.json)及
[v1 拟合结果](FIT_ONLY_V1_SELECTION.json)。

五项行为测试通过。独立审计完成：

- 4,000 个新 WAV 全量重哈希，与 3,000 个旧 FSDD WAV hash 比较，物理重复为零。
- 三个选定联合表格用另一组数组公式重建，最大概率差 `8.35e-13`。
- 67,200 个实际输出全部读回重算，逐 speaker 指标最大误差为零。
- 240 次真实 alias receipt 重复更新检查通过。
- 验证 fit → 冻结 → 测试 → 交付完成 → 评分的时间顺序。

来源身份为数据集局部 speaker 编号；没有解析跨数据集的人物身份。Bootstrap
单位是 8 个固定测试 speaker，数万 pair 和重复 WAV 使用不增加独立来源数。
没有声称说话人总体资格、生产 owner 准入、全模态生成或全局 portfolio 最优。

## 复现

完整原始包的位置与 SHA-256 见 `RAW_ARCHIVE.json`。解包后保留
`source/`、`observer.pt`、`study-001/`、`study-002/`。历史执行目录不可覆盖；
重新运行应使用新的空目录。

```bash
python -m experiments.multimodal_output_portfolio.continuation_20261027.evidence.run fit \
  --source /absolute/path/source --checkpoint /absolute/path/observer.pt \
  --output /absolute/path/new-run
python -m experiments.multimodal_output_portfolio.continuation_20261027.evidence.run evaluate \
  --source /absolute/path/source --checkpoint /absolute/path/observer.pt \
  --output /absolute/path/new-run
python -m experiments.multimodal_output_portfolio.continuation_20261027.evidence.audit \
  --source /absolute/path/source --output /absolute/path/new-run \
  --previous-archive /absolute/path/repair_20261026/evidence/raw_real_audio_001.tar.gz
```

[RESULTS.json](RESULTS.json) 保留全部逐来源指标；
[INDEPENDENT_AUDIT.json](INDEPENDENT_AUDIT.json) 给出重建与实际读回证据。
