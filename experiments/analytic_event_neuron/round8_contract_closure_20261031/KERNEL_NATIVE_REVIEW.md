# Native 数值与 checkpoint 独立审查

## 结论

**审查通过，范围为声明的 `r7-finite-v1`。** Rust 的 OU 端点、有限上风
CTMC、tick 末恢复、状态逐个读出再按质量加权，与 R7 Python 所声明的有限
过程一致。审查发现一处真实的 checkpoint schema 分支缺口，native owner
已修复，并完成实际启动拒绝反例。当前没有尚未闭合的核实现缺陷。

这项结论不认证连续 OU 首达精度，也不表示新增的
`r8-brownian-images-v1` 已经移植到 Rust。两者保持独立版本。

本次独立工作包括逐段源码对照、Poisson 截断尾与小 leak 计算、现有测试和
实际执行记录检查、实际测试 binary 的 SHA256 核对；未重复运行全部 broker
资格实验。完整运行结果来自所检查的记录，不冒称本审查者另外生成了第二套。

## 审查身份

| 文件 | SHA256 |
| --- | --- |
| `native/kernels.rs` | `eb32c6929e7881a6b5798aec76ddddb2246b9a51ca696305c3090bbb8bfe5bee` |
| `native/model.rs` | `8cf5e09b22c825424c1c581cebd6f089c8edc7af99a61674b071a7d423472d3d` |
| build03 实际测试 binary | `eced6e01e3a1535b896485b9ca6b4bcc692c2fc903755c21a1094dbabc726558` |

上述源码身份与 `evidence/native_build/BUILD_ATTEMPT03.json` 一致。
`NEXTEST_FINAL.json` 指向 build03 测试 binary；本审查实际读回该 binary，
其 hash 与 build03 的 `tests_sha256` 一致，测试记录中的源码表也完全相同。
历史 `NEXTEST_ATTEMPT03.json` 指向 build02，是保留的开发过程记录，不能
用它替代最终测试身份。这个区别已经核清。

## 数值和因果合同

| 项目 | 检查结果与解释 |
| --- | --- |
| Gaussian 尾部 | `0.5*erfc(-z/sqrt(2))` 保留负极尾；正侧区间通过反射到小尾计算，避免两个接近 1 的 CDF 相减。比原 `ndtr` 更稳定，不能声称逐 bit 重现原取消误差 |
| OU 小 leak | 漂移积分与方差积分均使用 `expm1`。允许的 raw leak 最小为 -100，物理 leak 约 `7.44e-44`，仍为正；在 dt=1 时两积分都得到 1，不出现 0/0 |
| Clocked 后继 | 活跃部分逐 bin 积分截断 Gaussian；正负末端尾进入对应 refractory 状态。没有把未发放条件后继替换为无条件均值 |
| Continuous 后继 | 全 Gaussian 的两端尾折入边缘 bin，和 R7 一致；仍然不是无界 Gaussian 状态 |
| CTMC 生成元 | `drive - leak*x`、上风 rates、边界吸收方向、源行/目标列排列均匹配 R7 |
| Uniformization | 每个基步将 `rate*dt` 缩到不超过 16，递推计算 `power * J`；随后平方恢复完整期限。吸收状态在指数阶段不恢复 |
| Reset 与恢复 | reset Gaussian jitter 仍是标准差 `0.08*b` 的投影分布；旧 refractory 质量在 tick 末按固定 R7 q 释放，新事件不能在本 tick 释放或再次发放 |
| Readout 二阶量 | 活跃态使用 `x²`，refractory 态使用 reset 的真实离散 `E[X²]`；没有丢掉 reset 方差 |
| Mean 部署 | 先对每个内部状态独立计算非线性 Q，再按 mass 求和，等于 Python 的 `model.values`；没有改成对平均特征调用一次非线性 readout |
| Hard 部署 | 同一计数器和 SHA256 键生成抽样均匀数；归一化、累计概率选择及事件计数与 Python policy 对齐 |
| 校准版本 | readout 内容 encoder 可以变化；传播 drive 使用单独冻结的 `kernel_content`，与 Python `FixedCellCalibrator.encode` 一致 |

Uniformization 的停止条件是当前 Poisson 权重小于 `1e-18` 且已经过峰值。
在最大基步 lambda=16 的独立计算中，代码在 k=63 停止；遗漏尾满足

\[
\sum_{j>k}w_j\le w_k\frac{\lambda}{k+1-\lambda}
=1.36927\times10^{-19}.
\]

SciPy 独立 survival 计算为 `1.36013e-19`。这只约束该基步的级数截断；
平方和浮点累计仍会放大误差。代码最终检查有限、非负和 `2e-10` 行质量
误差门槛，实际路径另与 PyTorch 比较。此计算不构成整个参数包络的统一
浮点误差证明，更不能消除上风生成元自身的连续过程近似误差。

## 发现并闭合的问题

原 loader 通过 `kernel_content.0.weight` 是否存在决定是否检查校准 schema。
这允许一个声明为校准版本、但缺失该 tensor 的文件退回共享 encoder 路径，
也可能将未知 schema 静默视作 R7。

修复后的 loader 先分类 schema：无 schema 的历史 R7 格式，或准确匹配的
`round8-fixed-cell-calibrator-v1`。校准版本必须包含完整四个传播 encoder
tensors；未知 schema、未知 tensor、缺失 tensor、显式未来 kernel version
均拒绝。网格、边、generator basis、权重形状和数值范围继续验证。
整个 JSON 文件 hash 绑定实际加载的 checkpoint；恢复 identity 另绑定
kernel version、seed、head 和 deployment。这里不额外声称 Rust 重算了
Python metadata 内的训练期 frozen-cell digest。

实际 guard 记录中 `unknown_schema`、`future_kernel`、`unknown_tensor`、
`calibrated_missing_encoder` 全部通过；原有错误 seed/head/model、过期请求、
并发 owner、pair 篡改和 pending publication 拒绝检查也全部通过。

## 已观察的执行覆盖

`evidence/native_build/NEXTEST_FINAL.json` 记录 `just test` 的四项全部通过：
极尾、吸收概率与期限、tick 恢复、连续/clocked 端点对应。执行的是已编译的
独立 rustc test binary；这不是 fresh Cargo 依赖重建。

`evidence/native_validation01/REPORT.json` 记录 240 个案例、480 次实际
Broker 执行、705 个 native 进程。其中 225 对包含真实冷恢复，其余 15 对
在第一次动作即结束，没有可恢复的后续步骤。最大 Q 差 `9.44e-15`，mass
与 moments 差 `6.89e-15`，事件数量差 `5.56e-15`；检查过的动作与冷恢复
继续结果一致。240 对案例均完成终局文件实际读回。

覆盖四种 R7 主模式、5 个 fit、两种 greedy readout head、mean/hard 部署，
以及校准 checkpoint。温度模型、hard_soft、Q24、新 Brownian 核和新的
无界 Gaussian 对照不属于这次 native 资格范围。固定 q 的旧恢复合同被
忠实保留；它没有采用新 Python 核的 physical-rate 映射。

恢复资格限于已确认的策略决策边界，原 broker 保持存活。它不认证任意
时刻崩溃、broker 重启或外部动作 exactly-once 完成。构建使用可识别的
缓存依赖并链接原 NeuronRuntime，保留其来源限制；性能和能耗优势也不能
从数值一致性推出。生产 activation 保持 false。
