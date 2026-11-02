# 真实 emotion encoder CI 产物独立复核

**2,935/2,935 项检查通过。** 这关闭了本候选“尚无真实预训练情绪编码器执行”
的证据空白；强音频质量、原 v6 任务等价及新独立群体资格仍未通过。

本审查读取 run `41379044650` attempt 1 的原始产物，实际源头为
`2a374bd68342a10e62db2280b27b2802dca08832`，对应本地冻结源
`0f04d81fac4ae1fc3b1704a77595eb6aba21b1b8`。没有把后来当前工作树 HEAD
误当本次 CI 源头。原产物没有修改；新审核代码、协议、结果及费用另存。

## 来源、输入与真实执行链

- 72 份源码／输入快照逐字节 SHA、字节数及自身 Git blob 一致，隐藏 workflow
  快照存在。它们属于真实冻结 Git 树的核验由 root 的独立归属检查另做，
  本脚本不把产物自填的 blob 身份冒称成该步骤。
- 四份波形分片在内存恢复后与完整 NPZ／PCM 数组身份一致，288 个训练录制、
  24 位演员及每条实际共同源时钟波形均逐个对应。真实样本无短窗制造填充。
- 实际获取的是固定官方 revision 的 661,375,508 字节 safetensors，CI receipt
  记录的 SHA256 与固定官方值 `efa5ac1a13b2d2f42182738e44794b1eb4c0cdd221a8b4ae11304c3a5f5fae95`
  一致；三份实际元数据原字节和 seal 匹配。每文件一次公开 HTTPS 获取，无
  重试；记录 URL 没有 query、fragment 或用户名凭据。
- 实际 loader 记录 234 个完整 tensor、零 missing/unexpected、仅两项旧
  weight-normalization 键别名；无随机权重 fallback、无 remote code。
  Torch 2.6.0+cpu／Transformers 4.49.0／Safetensors 0.5.3／NumPy 2.3.5 一致。
- 288 个真实录制加首条的两个未来载荷对照，共 290 次实际前向；所有前缀
  输出与整份 pooled／regression 特征逐值对应，进度／文件／数组哈希一致。
  未来 NaN／有限后缀实测 bitwise 一致，窗内 NaN 和短窗在前向前拒绝。

## 独立数值与 OOF 重算

本地审阅不导入模型运行层、不下载官方大权重。实际首条隐藏序列的维度为
49×1024；从原波形重新计算前缀局部归一化，从原隐藏序列重新计算 FP64
均值池化，满足冻结 `rtol=1e-5, atol=1e-6`；最大绝对差 `6.363404e-8`。

官方分类头仅保留参数形状、SHA 和 CI 内存中独立 NumPy 方程核验凭证；
没有导出官方参数 tensor。产物不含旧 `HEAD_REFERENCE_WEIGHTS.npz` 或
模型 NPZ 中的官方 dense/out_proj 参数。本审阅核验其凭证及输出链，**没有
在本地重算无权重可用的官方分类头，也没有运行第二套完整 transformer**。

用户训练的全部 24 个留一演员头及一个 all-TRAIN 头保留完整原参数。生产者
使用线性 solve，本审阅另用对称特征分解重算 dual ridge；每折仅使用另外
23 个训练演员拟合均值、尺度和系数，lambda 固定为 10。全部 25 头、全部
288 个 OOF 原始分数／概率和逐演员指标一致，最大头参数差 `2.865764e-15`。

| 独立重算指标 | 结果 |
| --- | ---: |
| OOF 正确数 | 137 / 288 |
| OOF 六情绪准确率 | 47.569444% |
| 未校准 NLL | 1.5454047300030505 |
| 未校准 Brier | 0.7384568843860446 |

这些是已经暴露的历史 TRAIN 演员 OOF 开发结果，不是新确认。没有读取
validation／test，也没有用本轮 OOF 结果重选 lambda／checkpoint。原 ASR
三次前向 CPU 和其 36.46% OOF 保持独立原样，不能把新表当作原 v6 资格。
当前也未建立 semantic binding、强前端下解析核心净收益或完整采用经济性。

## 成本和判定范围

CI acquisition 外层 CPU 为 **1.696364 秒**，model＋readout 外层为
**78.479032 秒**，共 **80.175396 秒**；body 和逐前缀时钟均已包含，不能
再次相加。本次独立审阅另外一个完整 waited-worker 包络为 **0.899686 秒**，
见 `../receipts/emotion_ci001/RECEIPT.json`。静态开发、pip／准备、历史训练、
物理能量及完整进程族 RSS 不由这些值推定为零。

`RESULT.json` 明确保留无第二 encoder 实现、无本地 vendor checkpoint
重新哈希、无原强参考／新群体资格。实际 CI 成功是执行与开发证据；完整
科学和生产准入继续 HOLD。
