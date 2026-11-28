# 冻结编码器后的直接读出与同几何优化器

使用 CREMA-D 的 4,984 / 1,147 / 1,311 个说话人互斥的训练、开发、留出片段。目标为 72 种台词与情绪组合。两层冻结算子仅层间传递带符号的安全裕量。前端、编码器与 72 类标注和上一项低带宽实验相同。3.75 是在看过上一项实验后给出的探索性门槛。每个种子同时要求开发、留出 NLL 达标。

|冻结双向切换编码器后的读出|留出 NLL，三种子平均|通过 3.75 门槛|每种子完整方案耗时|
|---|---:|---:|---:|
|一次在类别先验处的精确局部 Newton 写入|3.81806|0/3|约 0.74 秒|
|上述写入，再做四次带回溯的近似 Fisher 更新|3.67980|3/3|约 1.96 秒|
|普通 L-BFGS，最多 70 步|3.69451|2/3|约 5.85 秒|
|普通 L-BFGS，最多 350 步|3.66877|3/3|约 22.35 秒|
|相同初始 Hessian 预调节的 L-BFGS，最多 150 步|3.66803|3/3|8.10–9.35 秒|

困惑度与 NLL 衡量的是同一损失的不同尺度；本表始终用自然对数 NLL。完整方案按各自记录计入特征生成、求解、开发选择与最终评分。同几何优化器的开发首达 3.75 时刻只花费 0.66–0.82 秒，冻结这些首达权重后，留出为 2/3。五次写入只记录了完整方案耗时，两者的首次到达时间不能作配对比较。五次写入第三个种子的留出值约 3.74976，距门槛很近。光滑编码器的五次写入为 3.6723，原始输入基线也能在约 0.43 秒达到 3.7363；这项加速没有显示金融结构的专属性。

设中心化训练键的 Gram 矩阵为 G、先验为 π，则 softmax 交叉熵在先验处的权重 Hessian 为 G 与 diag(π)−ππᵀ 的 Kronecker 积。对两小矩阵分别对角化就能求解整个带正则的局部二次问题。独立 Hessian 向量差分误差为 2.15e−11，局部二次残差为 7.64e−17；真实非线性损失的更新后梯度仍达 0.00978。第二至第五步重估类别协方差并用梯度更新，编码器保持冻结。

复现协议见 [PROTOCOL.md](PROTOCOL.md) 与 [PRECONDITIONED.md](PRECONDITIONED.md)。[terminal.json](terminal.json) 保存逐种子得分与按说话人配对的区间，[precondition_terminal.json](precondition_terminal.json) 保存开发首达和全部留出端点。用以下命令在装有原数据和 Python 依赖的仓库工作副本重放 112 个读出（54 个直接/迭代方案、58 个预调节检查点），共 10,571,904 个分数。精确比较成绩与封存值的最大误差为 8.89e−16，54 个原始输出数组也通过 SHA-256 核对。[verified.json](verified.json)

```bash
cat archive/heads.tar.gz.part* > /tmp/hcsn-readouts.tar.gz
mkdir -p /tmp/hcsn-readouts
tar -xzf /tmp/hcsn-readouts.tar.gz -C /tmp/hcsn-readouts
OPENBLAS_NUM_THREADS=1 python verify_heads.py /tmp/hcsn-readouts/newton /tmp/hcsn-readouts/precondition
```

[archive/manifest.json](archive/manifest.json) 记录每一段、整体归档的字节数和 SHA-256。归档包括复算用权重、当时的开发封存表、全部 held 评分记录和逐片段损失。
