# 真实 WAV 联合观测实验：结构修复成立，单 speaker 联合估计未胜出

这次新实验用实际音频训练识别器、生成真实观测，再拟合联合观测 likelihood。它验证了同一 WAV 的重复位置只能使用一次识别似然，以及不同 WAV 的联合误差可以从实际 paired records 拟合。它同时给出一个明确的负结果：本次只有一个 likelihood-fit speaker，实测联合估计在另一个 speaker 上的 NLL 和 ECE 均比明示独立假设的基线更差。不能据此认证未知 speaker，不能宣称 joint 模型普遍优越。

本实验是新的十数字开发任务，不是旧 `advance_20261026` 音频 checkpoint 的恢复或重新资格确认，也不是开放词汇 ASR 或自然任务的替代。

## 冻结数据、模型与角色

- 来源：[Free Spoken Digit Dataset，固定 commit](https://github.com/Jakobovski/free-spoken-digit-dataset/tree/26eb9aaf76e81b692f806f9140c2d2777410d7a1)。项目作者为 Jakobovski 等贡献者，固定版本许可证为 CC BY-SA 4.0；保留上游 attribution 和许可证。源归档 SHA256 为 `9a68686ad29274bd0affde81b244953e677c9d7048dfb8acaf1168d7758bafab`。
- 完整数据是 6 speakers × 10 digits × 50 WAV。严格读取 mono PCM16、8 kHz，核对全部 3000 文件名与内容 SHA；角色之间没有相同 WAV 字节。
- `george, jackson, lucas, nicolas` 的 2000 WAV 训练观察器；`theo` 的 500 WAV 拟合 likelihood；`yweweler` 的 500 WAV 作为唯一开发测试 speaker。我们使用明确的 speaker 分离协议，**不是上游的按录音序号划分 benchmark 协议**。
- 固定小 CNN 读取真实 STFT，经 64×64 插值、逐录音归一化后，输出 10 类 logits。24 epochs、batch 64、Adam learning rate 0.001、weight decay 0.0001、seed 271831；总计 768 optimizer steps。没有 test 驱动的训练停止、模型选择或调参。
- 每个有序 target pair `(u,v)` 使用 50 对：左录音序号 `k`；若 `u=v`，右位置复用同一 WAV；否则右录音序号为 `(7k+11) mod 50`。因此每个 fit/test speaker 各产生 5000 pair rows，仍然只有各自 500 个物理 WAV。pair 数量不等于独立样本量。
- `alias iff targets equal` 是本次**明确构造的分配机制**，并非自然语音的普遍性质。事件身份只在真实观测到达后作为 opaque WAV SHA 的相等关系使用；预测接口不接收真实 target、文件名或未来身份。
- 所有 100 个 target pairs 恰好平衡，评价先验固定为 `1/100`。single 模型每个 target 的总 Dirichlet mass 为 0.5，均匀分到 10 个标签；distinct joint 模型同样总 mass 0.5，均匀分到 100 个标签对。未知格子的正概率来自这项已声明平滑，而不是它们已被观测。

`REGISTRATION.json` 在解包和训练前写入；CNN checkpoint 在 fit speaker 特征计算前冻结；两个 likelihood 模型在 test 特征计算前冻结。原始 WAV bytes 在完整源清单核验时已被提取和哈希，所以原元数据中的 `not opened` 仅表示**未计算该角色的模型特征/观测**，并非没有读取任何字节。审计明确保留了这一措辞修正。

## 实际结果

观察器在 likelihood-fit speaker 上的单数字准确率为 **73.2%**，在唯一 test speaker 上为 **74.0%**。下面全体 5000 pair rows 的结果来自独立标量复核；NLL 单位为 nat，ECE 使用 10 bins。

### 相同信息：只观察两个识别标签

| 模型 | 条件观测 NLL | target posterior NLL | pair accuracy | ECE |
|---|---:|---:|---:|---:|
| naive marginal Kronecker product | 3.569402 | 2.787344 | 56.08% | 0.168794 |
| alias 修复 + distinct 独立假设 | 3.390932 | 2.689168 | 56.08% | 0.168476 |
| alias 修复 + 实测 paired joint | 3.779360 | 3.069647 | 56.08% | 0.196345 |

这里先将 110 个“身份分区、标签”事件边缘化为 100 个标签对，避免修复模型凭额外的 alias 身份信息获得不公平优势。修复 same-WAV 结构降低了本次整体 NLL，但未改变 MAP pair accuracy。

### 相同信息：标签与实际到达的 alias 身份

| 模型 | 条件观测 NLL | target posterior NLL | pair accuracy | ECE |
|---|---:|---:|---:|---:|
| alias 修复 + distinct 独立假设 | 3.390932 | 2.546856 | 56.26% | 0.132861 |
| alias 修复 + 实测 paired joint | 3.779360 | 2.956352 | 56.26% | 0.160266 |

单看 4500 个 distinct-WAV pair rows，独立基线与实测 joint 的条件观测 NLL 分别为 **3.569402 / 4.000989**，posterior NLL 为 **2.674987 / 3.129983**，ECE 为 **0.139313 / 0.165023**。因此没有把“使用真实 joint 数据”写成“已经改善未知来源预测”。

后验 NLL 比较只在信息条件相同的行之间成立。收到同一个事件在第二个位置的 receipt 可以揭示“这两个位置 alias”，从而更新关于 target 相等关系的知识；这与重复乘第二份识别器 likelihood 是两件事。

## 物理支持集和重复观测

对 target `(u,u)`，同一确定性识别器读取同一 WAV 的两次结果必须一致。naive Kronecker product 对 `o_left != o_right` 的总概率为 `1 - sum_o C(o|u)^2`；实际拟合矩阵给出 **1.7734%–64.2770%** 的不可能概率。修复后的两个模型均严格为 **0**。

对 10 个测试数字的固定第一条真实 WAV，代码实际运行两份相同 CNN 输入，核对 logits 逐元素完全一致。两个位置的实际 receipt 到达并完成条件化后，再重复提交这些 receipt，后验逐项完全不变，10/10 通过。联合事件表示只使用同一事件的一次 likelihood。没有用合成音频或理想分类器替代这些观测。

拟合 joint 时，90 个 distinct targets 的 9000 个结构允许格子中，实际只有 **520** 个非零计数格子。4500 个 distinct 测试 pair rows 中，**1443** 个联合结果在 fit speaker 未见；其中 **1203** 个至少有一个单边识别结果也未见。未见 joint 格子的平滑概率为 `0.005/50.5`。这是事后描述性支持集清点；它说明本次转移面临稀疏估计和来源变化，但不单独证明哪一个因素造成全部 NLL 差距。

## 独立审计与明确计分修正

`audit_real_audio.py` 不调用训练脚本的拟合或评分函数：它重新核对 3000 个 WAV 哈希、角色隔离、100 个联合 likelihood 列的计数，以及 5 个模型 × 5000 pairs 的标量评分。最大拟合概率误差为 `3.33e-16`，除 ECE 边界外的最大指标差为 `8.88e-16`。审计没有再运行 CNN；原实验已运行 CNN，并保存所有预测、checkpoint 和实际重复输入检查。

第一次审计发现 alias 后验置信度在 0.9 附近的浮点求和差别会改变 ECE 分箱。因此本轮审计后明确修正为 `min(floor(10 * round(confidence, 12)), 9)`。这不是原冻结协议已有的规则。仅 `alias_corrected_product_identity` 和 `paired_joint_identity` 的 **aliased 分区** ECE 从 **0.1703974928** 修正为 **0.1710039714**；全体指标、NLL、accuracy、训练、likelihood、结论均不变。原结果和原冻结源码原字节均保留，未重训。

## 范围与后续接线

只有一个 fit speaker、一个 test speaker，不提供跨 speaker 的泛化置信区间或资格认证。`known_targets` 表示 fit 数据下该条件列已被估计，不表示新 speaker 的分布已知。独立假设基线本轮更好也不证明独立性为真。

可直接复用的是：真实 paired 训练记录接口、110 事件结构支持、opaque event receipt、实际 alias 幂等更新，以及可以供控制层显式组合 owner/cost law 的 `JointObservationLaw.forecast(prior)`。本轮没有把新 CNN 或本次经验 likelihood 接入 production native owner，也没有声称新 source group 的 future outcome law 已知。更多 speaker 的分离拟合和确认需要新数据与新冻结协议。

## 文件、哈希和复现

- `REAL_AUDIO_REGISTRATION.json`：原冻结协议，SHA256 `9c65680e4d63a3c5db386d2df2e55b4b8b377d54f788e411090c3a9b41ec837e`。
- `REAL_AUDIO_ORIGINAL_RESULTS.json`：原结果，SHA256 `2a496444d280227bbd213248f082ab601a0b6ed982098a59e244049bb241124d`。
- `REAL_AUDIO_RESULTS.json`：含明确 ECE 和元数据修正的复核结果，SHA256 `26dd4cbd9e97ae8d9d6576e4cf58fb46b961081c0cfdf29491efada42971b472`。
- `REAL_AUDIO_AUDIT.json`、`REAL_AUDIO_SUPPORT.json`：独立审计与事后支持集清点。
- 原始证据目录：`ndu-original-assets/evidence-real-audio-001/`，包含 actual WAV、原冻结源码、3000-file inventory、CNN checkpoint、fit/test 原始预测与两个 likelihood。原始训练墙钟约 12.39 s，CPU 12.26 s，峰值 RSS 401108 KiB；这些是本机测量，不是吞吐 benchmark。

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /path/to/torch-venv/bin/python -m experiments.multimodal_output_portfolio.repair_20261026.evidence.real_audio \
  --archive /path/to/fsdd-26eb9aaf.tar.gz --output /path/to/new-run-directory
```

当前源码已明确使用修正后的 ECE 边界与元数据措辞。原运行源码在原始证据目录的 `RUN_SOURCE_real_audio.py` 中，并由原协议的源码 SHA 绑定；不能把当前源码描述成未经改变的原运行源码。
