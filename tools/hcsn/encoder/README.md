# 冻结 MiniLM 的真实文本 Head 实验

## 数据与 encoder

使用公开 `sentence-transformers/all-MiniLM-L6-v2`，固定 revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`，本地 ONNX CPU 执行。没有训练或调用外部推理服务。数据使用 Stanford NLP 官方 `stanfordnlp/sst` 的 PTB 树，固定转换 revision `8a7d55ee01d70b8ae53e0b3c66a83b2a6198c2a7`。原始官方 train/validation/test 分割保持不变；只取句子根标签，移除 neutral，构造平衡二分类。

选取 train 1600、validation 400、test 800；各 split 的选择种子固定，选中的规范化文本摘要跨 split 交集均为零。源行号、标签、文本摘要和六个下载文件摘要在 `feature_manifest.json` 中。预训练模型对 SST 的历史数据重叠没有审计；“样本外”仅针对本次 Head 训练。

每句最多 48 个 token。384 维 token 特征按四个 token 做局部 masked mean，得到 12 块，再追加全局 masked mean。训练集拟合 64 维 PCA 及方差归一化，后续全部冻结。每个 Head 获得相同的 13×64 输入；PCA 保留方差比例为 0.5780462。全局 mean 已含整句上下文，这也使 65 参数的线性参考成为有意义的强控制。

## 训练与选择

HCSN、同结构 sigmoid、GRU、单块 Transformer 各五种子，每次 300 个 Adam 更新，batch 32，学习率 0.003，梯度范数裁剪 1。验证集每 50 步评估一次，取最低验证 cross entropy 的 checkpoint；训练器不接收 test。HCSN/sigmoid 参数 5930，GRU 5854，Transformer 5959。线性参考是固定 C=1 的二分类 LogisticRegression，实际为 64 个系数加 1 个截距，共 65 参数；它不参与参数匹配。

| Head | Test 平均 ± 种子 SD | 特征扰动 Test |
| --- | ---: | ---: |
| HCSN v1 | 74.700% ± 1.127% | 74.450% |
| sigmoid v1 | 74.225% ± 1.710% | 74.550% |
| GRU | 75.175% ± 1.385% | 75.125% |
| Transformer | 74.525% ± 1.239% | 74.425% |
| 全局 mean 线性参考 | 77.250% | 未测 |

HCSN−sigmoid 配对差为 +0.475 个百分点，差值的种子 SD 为 0.899 个百分点。它没有建立稳定的 Put 形状优势。v2 Head 与传统 LIF-SNN 的追加对照记录在 `../benchmarks/`，复用同一冻结数据，因此应解读为探索性比较。

扰动协议在编码完成后给特征加入标准差 0.15 的 Gaussian noise，再丢弃 20% 局部块，全局 mean 块保留但同样受噪声影响。剩余 token 特征和全局块已经见过整句；不能把此结果称作原始缺字、未见信息恢复或缺失模态鲁棒性。

## 实测审查与修正

独立复核未发现直接 train/test 泄漏：PCA 只在训练集拟合，NPZ 标签与 manifest 逐项一致，原始树解析与规范化文本摘要一致，所有特征有限。训练前后特征文件 SHA 均为 `970c2c56442dc7deaa0e1db98f78b12ab0254a5fae2d45923852055252286a8a`。

`audit_heads.py` 从保存的 20 个 checkpoint 重放全部 test 预测，准确率与交付记录完全相同。它把线性参考参数数由 130 修正为 65，将 ECE 改为无交叠的整数分箱；重算最大 ECE 变化为 3.58e-8，未改变任何训练权重或准确率。原始记录在 `pre_audit_head_results.json`，修正后的主记录在 `head_results.json`，变化与 SHA 在 `audit_results.json`。

训练计时的首步剔除不足以移除 HCSN/sigmoid 的第二次 JIT 编译，原 `warm_training_seconds` 不可用于速度结论。保存的推理延迟测的是 JIT 预热后的纯 Head logits，排除 encoder；不等于完整系统成本或能效。原始峰值 RSS 属于整个共享进程，也不可按模型比较。

下载脚本新增固定 SHA 验证，六个实际缓存文件均通过；故意错误的缓存被拒绝且未尝试网络请求。此更改保护后续复现，没有改变本次 feature 文件。

## 重放

在项目根目录：

```bash
python encoder/prepare_features.py --cache /tmp/hcsn-encoder-assets
python encoder/run_heads.py --features /tmp/hcsn-encoder-assets/frozen_features.npz
```

只重放交付 checkpoint 的指标审计：

```bash
python encoder/audit_heads.py --features /tmp/hcsn-encoder-assets/frozen_features.npz
```

后三种脚本会写入对应结果文件。原始模型、文本和 feature cache 不再分发，小型已训练 Head 参数以 NPZ 保存；不使用 pickle。
