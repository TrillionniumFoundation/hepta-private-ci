# Joint 训练与正式评价的独立静态审查

本审查仅阅读 `next_20261025/joint/{model,train,evaluate,analyze,preflight}.py` 及实际调用的 public ingress、mel、空间运动、source loader、媒体 observer 函数；没有运行 Torch/ASR、访问新来源或修改训练字节。审查发生在训练已完成、evaluation 尚未冻结时。

## 梯度与声明目标

`policy_objective` 的数值 forward 为 cost 的均值，修正项 `stopgrad(cost-baseline) * (logp-stopgrad(logp))` 的数值恒为零，但导数贡献 `(cost-baseline)∂logp`。加上 cost 自身的 pathwise 导数，给出所声明采样目标的 score-function 与 pathwise 联合估计。固定常数 baseline 不改变期望梯度。

`log_probability` 包括七个自回归 token 条件概率与两个 semantic categorical 选择的联合 log-law。离散抽样已经 detach，未使用 straight-through；continuous image、speech 和 motion 路径保留导数。独立高斯噪声通过固定外源样本进入 state，符合 reparameterized pathwise 处理。预先计算的 mel front-end 只包含固定 buffer 与无参数变换，没有把 trainable audio CNN 错误冻结。

完整实际目标应写成：

- mean arm：`E[-U] + 0.005 × waveform_anchor`。
- entropic arm：`0.5 × E[exp(-2 × (U-0.75))] + 0.005 × waveform_anchor`。

去掉正则项时，第二个目标的最优点等价于最大化 entropic CE。加入固定 anchor、分组学习率、梯度裁剪和 Adam 后，不能称为直接求解了无正则 CE 的全局最优。0.75 中心在该点对齐了两种目标对 utility 的局部梯度尺度，但没有让正则相对强度在所有 utility 上相同。已执行的标量二分类枚举梯度契约正确覆盖此 score/pathwise 公式；它不是整个神经模型的全局收敛证明。

## 目标信息与媒体声明

`JointModel.encode` 只接收 `PublicTask`，不接收 `Target`。字面 text route 公开所要求的数字；audio route 用 label 配对实际可见 PCM；video route 从源像素构造可见运动输入。这些是明确的任务构造规则，不能解释为从完全隐藏真值直接生成自然声音或视频。image route 保留已有 observation 的遮挡、噪声、command 和可靠性提示语义。

训练 reward 的标签仅用于损失，独立 ASR 不进入梯度。evaluation 中 `observe_bundle` 只读已生成并经过 codec 的实际媒体，expected labels 在观察完成后的 scoring 才使用。没有发现 expected labels 传入生成或 observer 的隐蔽路径。

训练效用包含 soft image/video 识别概率、离散文本正确率、浮点 waveform fidelity 与 motion proxy；evaluation 使用 greedy 解码、物理 codec 后的四模态正确率，strict joint 另要求运动和非空声音。两者差异已在代码明确声明。只能说训练了这些代理目标并另行评价实际媒体，不能说对 codec 或 ASR 反向传播，或证明训练目标等于最终外部指标。wave decoder 仍是十个固定语义条件的有限声音模型，运动视频仍是源域数字的空间变换。

## 两个 arm 与 24 个 connected cluster

每个 seed 的两个 arm 从同一 deep-copied 初值出发，使用相同步数、route、数据来源、外源 task/noise/dropout seed、学习率与 anchor。所作比较是继续训练目标之间的比较；没有 unchanged-generator arm，因此不能据此单独估计“继续训练本身”的增益。

128 对来源来自 32 个 image writer，每人四个 route。24 个 audio speaker 通过 `writer_group % 24` 与 writer 相连：8 个 connected group 各有两个 image writer，16 个各有一个。`analyze.py` 以整个 connected group 重采样，保留其中所有 route、两个 arm 和三个 seed，也保留 8 对/4 对的不等组大小。这正确处理当前分配下 writer 与重复 speaker 的连接依赖。

统计结论条件于固定的三个训练 seed；三个 seed 不构成额外独立来源，也不支持训练随机性的总体推断。当前 CE 是固定 source×seed 混合面板的 CE，而非先算每 seed CE 再平均；报告应按实际 estimand 表述。固定 arm 顺序及实际 waveform SHA 缓存使执行成本只能作描述性比较。

## 在 evaluation 冻结前建议补强的身份检查

1. `freeze` 应逐 arm 校验 checkpoint 的当前 SHA 等于 training RESULTS 中记录的 SHA，确认确有 `17/29/43 × mean/entropic` 六个 arm，并校验每 seed 的 initial/schedule SHA 一致。当前 `preflight` 已逐 checkpoint 校验，但 `freeze` 尚不强制依赖 preflight 结果；仅检查 training completed 后把当前文件 pin 住不够紧。
2. 将 qualification 的 `observers.json` 中 manifest SHA 与实际传入 `audio_assets` 的 manifest 对应，避免资格校验的是登记路径，而运行时从另一个目录加载同名模型。`run` 对实际输入的 protocol SHA 检查已经存在；缺少的是在 freeze 阶段把实际 ASR 身份关联到既有资格证据。

以上建议不需要改训练冻结字节，也不需要新训练或重新查看来源结果。它们已直接发给 root；是否修复及最终版本由 root 的最终冻结记录说明，本文件记录的是审查时状态。
