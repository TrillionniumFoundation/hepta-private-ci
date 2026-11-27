# 自由边界网络的受约束权重编辑

在原 RAVDESS 二选一检索任务中，三个已训练的八群体中心化 HCSN 都有 20 维最终接收端表征。本次在同一张 RTX 4060 上用它们检验一个具体问题：当编辑必须保持已有输出时，编辑器还剩几个能改变任务结果的方向？这是 AlphaEdit 零空间保护思路在冻结线性读出上的特例。完整 LLM 的层定位和目标向量优化属于另一项实验。

使用 80 个原训练查询拟合，32 个开发查询定义保护约束。三个父模型、四种方法的 12 份权重在打开本次确认阶段前全部封存，再从磁盘重载，通过原非线性网络计算六名历史测试演员的 48 个查询和原保留集的 32 个查询。各组沿用了原研究已评估的演员。本次属于追加分析。

| 每个种子均得到的结果 | 可写维数 | 测试正确 | 保留正确 |
|---|---:|---:|---:|
| 保持原权重 | 0 | 41/48 | 27/32 |
| 数值精确零空间 | 0 | 41/48 | 27/32 |
| 低特征值空间 | 17 | 41/48 | 27/32 |
| 无保护约束的原二次读出解 | 20 | 42/48 | 31/32 |

在以训练 RMS 规范化的 32×20 保护矩阵上，按双精度标准 SVD 容差，三个父模型均为满列秩。严格保持所记录开发分数差时，读出增量只能为零。半正定平均 Gram 的特征值小于 0.01 时，每个模型都可使用 17 个方向。物理验证中，开发查询的最大分数差变化为 0.00343 至 0.02344。测试 Brier 略有改善，正确查询数对于三个种子均无变化。秩判断与精度约定有关：以相同奇异值和 float32 的机器精度估计，有效秩依次为 15、15、16（种子 47、83、137）。缩放、保护集和容差均在本次测试结果前固定。

独立测量也覆盖一个真正的内层。把 32 个开发查询的六个时刻、两个选择送入原发送端，得到 384×9 的输入矩阵。NumPy 与 GPU 均测得秩 9，最大、最小奇异值分别为 50.59935 和 1.55915。若线性发送端保持偏置并逐键精确保留这批投影，九个输入方向均受约束。保持一层全部投影比保持外部标签更严格，这个结果限定于所测写入点。

解析求解在受限子空间仍成立。令 Z 为训练设计矩阵、r 为有监督的有符号残差、N 为所选子空间的正交基。在 lambda=0.5 下求解 (NᵀZᵀZN/n + lambda I)c = NᵀZᵀr/n，再把 Nc 依原参数尺度写回相反的两个输出权重行。以同一经过 BP 的非线性编码器评估全部候选。没有选择超参数或声称基础模型的训练加速。

## 复核

在仓库根目录运行，使用带 NumPy 的 Python。验证脚本在全部 12 个候选上逐个核对权重摘要，从预测重算正确数和 Brier，将两个对照组的逐条分数与上一轮原始记录比对。

```bash
repo="$PWD"
accel="$repo/qualification/hcsn_boundary_transfer_20261126/accel"
out="$(mktemp -d)"
python -m zipfile -e "$accel/projection/evidence.zip" "$out"
python "$accel/projection/verify.py" "$out/results-cu130" "$accel/readout_results.json"
python "$accel/projection/verify.py" "$out/results-cu121" "$accel/readout_results.json"
```

原始父模型使用 Torch 2.10.0+cu130。本次在相同的 Torch 2.10.0+cu130 上完成整组实验，并在同一张显卡上以 Torch 2.3.1+cu121 独立复跑。两个环境各封存 12 份权重。跨版本的 1,344 个物理分数差逐值相同，Brier 归约最大相差 2.99×10⁻⁸。两个对照组的测试及保留分数与上一轮原始记录也逐值相同，共 480 个比对值。

如需从头重做这项局部更新，先解出旧父模型，再用 CUDA 版 PyTorch 从真实输入生成全部候选。档案保存了运行前登记的方案、执行源码、四份哈希固定的前端输出、原前端回执、每个运行环境的 12 个候选权重，以及逐种子、逐查询结果。代码复用当前仓库的 qualification 模型。

```bash
python -m zipfile -e "$accel/selected_checkpoints.zip" "$out"
PYTHONPATH="$repo" python "$accel/projection/experiment.py" fit "$out" "$out/replay"
PYTHONPATH="$repo" python "$accel/projection/experiment.py" eval "$out" "$out/replay"
python "$accel/projection/verify.py" "$out/replay" "$accel/readout_results.json"
```

四份前端张量由已登记的 wav2vec2 语音前端、视觉分数及原采样程序生成，原始音视频可从数据作者获得。这些 RAVDESS 派生输入依据 CC BY-NC-SA 4.0 提供。Livingstone 与 Russo（2018），The Ryerson Audio-Visual Database of Emotional Speech and Song。[数据与许可](https://smartlaboratory.org/resources/speech-song-database-ravdess/) · [许可文本](https://creativecommons.org/licenses/by-nc-sa/4.0/) · [AlphaEdit 作者论文](https://openreview.net/forum?id=HvSytvg3Jh)
