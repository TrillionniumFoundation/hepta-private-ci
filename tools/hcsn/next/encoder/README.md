# 新独立文本与图像冻结 encoder 验证

## 结论与范围

本轮实际完成 **40 次神经 Head 训练、2 个确定性线性参考拟合、42 个 checkpoint 复核，以及 500 次原始输入到 logits 的流水线计时与 100 次线性参考计时修正复测**。在此前 SST 实验之外，使用 AG News 与真实 CIFAR-10 图像；所有缺失测试均先修改原始输入，再完整运行冻结 encoder，重新生成局部与全局特征。

这补齐了“只有文本”“复用旧测试集”“扰动后仍保留干净全局表示”“只报 Head 成本”四项实验缺口。本轮结果**没有支持简化 HCSN v2 的稳定优势**：AG News 与同图 sigmoid 消融相近，CIFAR-10 的干净准确率低于 sigmoid、GRU、Transformer，并低于参数更少的全局线性参考。新的完整 He–Xiong 表核与因素消融由相邻实验目录独立记录，不混入这里的 v2 基线结果。

这是两套**独立单模态**冻结表示实验。它不构成配对多模态学习、跨模态对齐、连续时间真实事件流、完整 backbone 预训练或大模型扩展证据。两个 encoder 的预训练数据重叠未审计；“新 holdout”指相对于本项目此前 Head 训练与选择过程的新测试数据。

## 1. 先冻结协议，再生成特征与训练

`protocol.json` 在特征生成与 Head 测试评价前写入。公共数据下载的具体镜像、权重及数据的 SHA256、实际样本行号与内容 SHA256 记录在两个 manifest 中。`preparation_notes.json` 保留一次无效工程断言的修复：Bernoulli 遮词可能恰好不删任何词，不能要求每个样本特征都改变。修复前未进行 Head 训练或查看 Head 测试分数；选择与扰动 RNG 未变。

| 项目 | AG News | CIFAR-10 |
| --- | --- | --- |
| 标签数 | 4 | 10 |
| 训练 / 验证 / 测试 | 2,000 / 500 / 1,000 | 2,000 / 500 / 1,000 |
| 划分 | 原始 train 中选训练、验证；原始 test 中选测试 | 同左 |
| 类别平衡 | 各 split 分层等量 | 各 split 分层等量 |
| 冻结 encoder | all-MiniLM-L6-v2 | ImageNet 预训练 MobileNetV2 |
| 原始表示 | 64 个 token × 384 维 | 7 × 7 空间网格 × 1,280 通道 |
| 局部汇聚 | 每 4 个 token 一组，共 16 组 | 将两条空间轴各分 4 组，共 16 组 |
| 全局表示 | 有效 token 均值 | 空间均值 |
| PCA | 仅干净训练数据拟合，64 维，whiten | 同左 |
| 保留训练方差 | 51.896% | 61.759% |
| Head 输入 | 17 × 64；dt 均为 1 | 17 × 64；dt 均为 1 |

数据选择随机种子为 `2026102907`。训练、验证和测试选择时共同维护已见内容 SHA 集合：文本对空白及大小写规范化，图像对解码后的 RGB 字节取 SHA。三组之间的**精确内容**交集均为零；这不排除语义近重复。样本选择不依赖模型输出。

所有神经 Head 运行种子 0–4，300 次 Adam 更新，batch 32，学习率 0.003，梯度裁剪 1；每 50 次更新按验证交叉熵选择 checkpoint。测试集未传入训练器。候选模型与预算在测试前固定。HCSN v2 与 sigmoid 使用相同参数图和宽度；sigmoid 替换简化风险算子。GRU 与 Transformer 按最接近约 6,000 个可训练参数选择宽度。这里没有宣称等 FLOPs，也没有对每种模型另做超参数搜索。

线性参考直接使用同一 PCA 后的全局向量，`LogisticRegression(C=1,max_iter=1000,solver="lbfgs")`，固定一次拟合；它不属于相同 Adam 更新预算的四模型比较，用于检查复杂动态 Head 是否确有必要。

### 原始输入扰动

- **文本缺词：**对原始空白分词独立以 25% 概率删除，再运行 tokenizer、完整 MiniLM、局部/全局汇聚及固定 PCA。它不是精确删除每句 25% 的单词。1,000 条中有 1 条随机结果未删除单词；999 条全局特征改变。
- **图像遮挡：**原始 32 × 32 RGB 的中心 16 × 16 区域全部置为 128，再 resize 至 224、标准化、完整 MobileNet、局部/全局汇聚及固定 PCA。1,000 条全局特征全部改变。

扰动集仅改变同一测试样本的输入，标签与原测试一致。不在扰动集训练或选 checkpoint，不保留未扰动的全局向量。文本删除与图像遮挡严重度并不可直接比较；图像遮挡会移除对象信息，不能把其降分全部归因于 Head 动力学。

## 2. 实际测试结果

以下数值为准确率百分比，`±` 是 5 个训练种子的样本标准差，单位为百分点。训练种子重复共享同一个 1,000 条测试集，因此这些标准差不包括全部数据抽样不确定性。

### AG News：固定 MiniLM

| Head | 参数 | 干净测试 | 原始文本删词测试 |
| --- | ---: | ---: | ---: |
| HCSN v2 | 6,114 | 84.24 ± 0.71 | 83.46 ± 0.59 |
| 同图 sigmoid v2 | 6,114 | 84.02 ± 0.49 | 83.62 ± 0.65 |
| GRU | 5,900 | 84.14 ± 0.46 | 83.42 ± 0.52 |
| Transformer | 6,007 | 83.42 ± 0.89 | 83.40 ± 0.70 |
| 全局线性参考 | 260 | 83.80 | 83.50 |

配对 HCSN − sigmoid：干净测试 **+0.22 ± 0.86** 个百分点，删词测试 **−0.16 ± 0.88** 个百分点。方向随条件与种子变化；当前试验未把性能收益归因于简化风险函数。

### CIFAR-10：固定 MobileNetV2

| Head | 参数 | 干净测试 | 原始图像中心遮挡测试 |
| --- | ---: | ---: | ---: |
| HCSN v2 | 6,010 | 76.10 ± 1.06 | 42.36 ± 1.42 |
| 同图 sigmoid v2 | 6,010 | 76.64 ± 0.96 | 42.20 ± 0.53 |
| GRU | 6,038 | 77.12 ± 0.83 | 44.36 ± 1.54 |
| Transformer | 6,151 | 77.68 ± 1.35 | 41.66 ± 3.53 |
| 全局线性参考 | 650 | 81.30 | 40.70 |

配对 HCSN − sigmoid：干净测试 **−0.54 ± 0.31** 个百分点，遮挡测试 **+0.16 ± 1.71** 个百分点。干净测试中五个配对差为 −0.6、−0.7、0、−0.8、−0.6 个百分点；遮挡条件没有稳定的方向。全局线性参考的干净准确率高于所有动态 Head，说明这一固定 encoder、固定训练预算设置中，增加动态层没有自动改善图像分类。没有根据这个结果再调模型或改 holdout。

每个种子的交叉熵、Brier 分数、ECE、验证历史、编译与执行时间、checkpoint SHA 均保留在 `ag_news_baseline_results.json` 与 `cifar10_baseline_results.json`。这些小任务不能推导所有其他预算或任务上的排序，也不能作为大模型扩展规律。

## 3. 成本：特征准备、训练与在线流水线分开计量

### 一次共享特征准备及整个 Head 实验

| 阶段 | AG News 秒 | CIFAR-10 秒 |
| --- | ---: | ---: |
| 4,500 条输入的预处理、encoder 与汇聚 | 75.485 | 48.986 |
| 训练 PCA 并变换所有 split | 0.555 | 2.140 |
| 20 个神经 Head：训练、编译、评价、保存与 Head 延迟测量 | 35.610 | 36.252 |
| 线性参考拟合 | 0.011 | 0.019 |

4,500 条包括 2,000 训练、500 验证、1,000 测试及 1,000 扰动测试。特征准备开销由全部模型共享，不可在每次 Head 训练重复计入；也不可在整个系统成本中删去。该表不包含网络下载、Parquet 读取、encoder 模型加载或结果审计，因此不声称从空环境安装到完成实验的总耗时。

使用 `next/common.py` 的显式 AOT 训练器，区分编译、优化器执行、验证与主机开销；没有丢弃的“预热优化器更新”。训练参数为强 dtype，检查前后输入签名稳定。优化器执行总时间仍包含第一次编译后冷 dispatch，并单独记录前三次执行时间；不能把这部分称为纯 warm steady-state。结果中的 `logits_latency_batch1/32` 是特征已就绪的 Head 纯 logits 延迟，不含 encoder。

### 真正原始输入到 logits 的在线测量

流水线固定使用每类 Head 的 seed 0；同一组 50 条原始测试输入，每个模型 3 条预热，batch 1。计入 tokenization 或 PNG 解码/resize、encoder、汇聚、PCA、CPU 张量转换与 Head logits；文件读取、模型加载、JIT 和分类指标单列或排除。每个模型实际重新运行 encoder，未用缓存特征替代。

收尾审读发现原 `measure_pipeline.py` 的线性参考 closure 在每次预测时从 NPZ archive 读取系数，额外计入了解压/文件读取。神经 Head 已在计时前读出参数，不受此问题影响。保留原脚本与 `pipeline_latency.json` 原字节作为历史证据；新增 `measure_pipeline_corrected.py`，预先将所有 checkpoint 数组物化，再预热与计时。本次实际只用 `--linear-only` 重测两个线性参考，共 100 条输入，结果为 `pipeline_latency_linear_corrected.json`；没有重训或重测其他 Head。下表线性行采用修正测量，其他行保留原神经 Head 测量。

| Head | AG News 中位数 ms | CIFAR-10 中位数 ms |
| --- | ---: | ---: |
| HCSN v2 | 18.143 | 10.930 |
| sigmoid v2 | 18.686 | 11.631 |
| GRU | 18.142 | 11.916 |
| Transformer | 19.388 | 11.141 |
| 全局线性参考（修正后） | 16.904 | 10.595 |

HCSN 测量段内，encoder 自身中位数为文本 16.756 ms、图像 8.123 ms；系统成本主要在冻结 encoder。HCSN 总延迟 p95 分别为 21.841 ms、13.962 ms。原 JSON 保留各组件的均值、中位数、p95、p99、编译时间与加载时间；修正 JSON 的 `supersedes` 明确只替换原线性记录，`historical_artifacts` 记录原脚本和原 JSON 的路径与 SHA。

这是共享 CPU 上按模型分块测量的参考值，50 个样本不足以做稳健尾延迟估计。模型运行期间 CPU 争用、调度及缓存状态均可不同。不能从数十微秒或亚毫秒差异宣称显著加速、能效优势或同质量成本优势。也没有直接测量神经形态硬件或事件稀疏执行。

## 4. 可复核证据

`audit_baselines.py` 从保存的 checkpoint 独立加载并复算两个测试条件，无重新训练：

- **40/40 神经 checkpoint** 的准确率、交叉熵、Brier、ECE 与保存结果最大差为 **0**。
- 两个线性参考最大指标差分别为 `1.457e-16` 与 `0`。
- 特征 SHA、checkpoint SHA、已记录源码 SHA 全部匹配；数组有限；标签与 manifest 一致；扰动标签与干净标签一致。
- 三种 split 的精确内容交集均为零。
- 在线流水线最前 8 个样本的 batch1 特征与 batch16 特征缓存最大绝对差为 **0**，检查的是编码、池化及 PCA 路径一致性。

完整检查记录为 `baseline_audit.json`。特征 manifest 与原流水线 JSON 的 `source_sha256` 路径相对于此目录；基线结果与修正流水线 JSON 的同名字段路径相对于 `hcsn_research/` 根目录。修正 JSON 以 `source_sha256_base` 显式声明其基准；原测量的脚本仍在原路径，其哈希保持一致。源码哈希是对应运行时状态，不应把后续新加入脚本反向解释为先前运行的依赖。

### 特征缓存接口

默认缓存文件：

- `/tmp/hcsn-next-encoder-assets/ag_news_features.npz`
- `/tmp/hcsn-next-encoder-assets/cifar10_features.npz`

每个 `split` 属于 `train,validation,test,corrupted_test`，提供 `{split}_x` 为 float32 的 `N×17×64`，`{split}_dt` 为 float32 的 `N×17`，`{split}_y` 为 int32 标签；另保存 `projection,center,scale`。投影参数可供独立的完整 HX 算子训练复用，禁止在测试上重新拟合。

AG News 特征 SHA256：`df019257f7e8cbacac5f4a695f5ecbeafa735f37b811679c6b1a0049733ddbbe`。

CIFAR-10 特征 SHA256：`4aa81cf9f6c2dfe451f2f02fda0c389f2f155c5321606e0661db930de292f2d8`。

## 5. 复现

在 `hcsn_research/` 根目录，以 Python 3.12 安装 `requirements-cpu.txt` 与本目录 `requirements-extra.txt`。参考运行：JAX/JAXlib 0.4.38、NumPy 2.3.5、scikit-learn 1.8.0、ONNX Runtime 1.20.1、ONNX 1.17.0、tokenizers 0.21.4、DuckDB 1.2.2、Pillow 12.3.0。参考机器只使用 CPU，affinity 6–8，BLAS/OpenMP/encoder 均设 1 线程。

```bash
python -m pip install -r requirements-cpu.txt -r next/encoder/requirements-extra.txt
python next/encoder/download_assets.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 6-8 python -B next/encoder/prepare_text.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 6-8 python -B next/encoder/prepare_image.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 6-8 python -B next/encoder/run_baselines.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 6-8 python -B next/encoder/audit_baselines.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 6-8 python -B next/encoder/measure_pipeline_corrected.py
```

修正脚本默认完整测量所有模型并写入新的 `pipeline_latency_corrected.json`；仅复现本次修正时添加 `--linear-only`，写入 `pipeline_latency_linear_corrected.json`。前一文件在本次交付中不存在，因为本次没有再次测量未受影响的神经 Head。原错误脚本仅供追溯，不作为推荐复现入口。

若机器没有 CPU 6–8，选择本机有效 CPU；这会改变性能测量条件。下载器使用固定 revision，并验证数据与模型 SHA256。重新生成随机化 PCA 时，底层依赖或 CPU 数值路径改变可能造成字节哈希变化；应报告差异来源，不能忽略现有结果对应的原始哈希。

原始公共权重、数据、派生 ONNX、特征缓存不放入 Git。可发布本目录的代码、协议、manifest、结果 JSON、审计 JSON 与小型 Head checkpoint。manifest 只含来源行号、标签和内容哈希，不复制原始文本或图像。下载公共模型和数据后应遵循其原始条款。

## 6. 数据与模型来源

- [AG News 数据卡](https://huggingface.co/datasets/fancyzhx/ag_news)，固定 revision `eb185aade064a813bc0b7f42de02595523103ca4`。
- [MiniLM encoder 数据卡](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)，固定 revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`。
- [CIFAR 作者数据页](https://www.cs.toronto.edu/~kriz/cifar.html)；实际使用 [uoft-cs/cifar10 公共 Parquet 镜像](https://huggingface.co/datasets/uoft-cs/cifar10)，固定 revision `0b2714987fa478483af9968de7c934580d0bb9a2`。
- [ONNX Model Zoo MobileNetV2](https://huggingface.co/onnxmodelzoo/mobilenetv2-12)，固定 revision `23a2a25eaaa6fcd61865414c8a1acf13dda66b7a`；[MobileNetV2 论文](https://arxiv.org/abs/1801.04381)。

MobileNet 派生图仅将 `GlobalAveragePool` 的输入张量 `463` 暴露为输出，权重与中间激活计算不变；图合法性通过 ONNX checker。原始与派生图 SHA 均记入 manifest。图像实验因此使用真实公开预训练视觉模型与真实自然图像，而非把合成数据称为多模态证据。
