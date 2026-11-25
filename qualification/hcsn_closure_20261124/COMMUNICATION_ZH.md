# 独立通信机制实验

本实验在 N32、QVI + value/risk、uniformized mixed 的相同物理核下，比较七种预先指定的通信合同。三个初始化 seed 为 18011、28011、38011，共 21 次训练。它与 63-fit 主因子实验分别封存、分别使用新 source，不修改主实验的任何冻结文件。

## 通信合同

| 臂 | 传递内容 | 输入控制语义 |
|---|---|---|
| signed_only | 仅 signed event rate | 原始观测帧 |
| unsigned_signed_raw | unsigned + signed event rate | 原始观测帧 |
| unsigned_signed_centered | 名义参考中心化的 unsigned + signed | 原始观测帧 |
| unsigned_signed_centered_bounded | 中心化且 tanh 有界的 unsigned + signed | 原始观测帧 |
| boundary_raw | 仅 boundary | 原始观测帧 |
| boundary_accumulate | 仅 boundary | 相邻慢控制更新之间累加 cue 脉冲，更新时清空 |
| boundary_hold | 仅 boundary | 保留最近已到达的两个 cue 值和到达标志 |

前四臂全部禁用 boundary 通道，因此 unsigned 对照不混入另一路 boundary 信息。signed_only 又通过持久化的 `synaptic_mask[:, N:2*N]=0` 硬禁用 unsigned 支路。Receiver 仍无 raw input；readout 仅取 receiver 特征。

缓存只改变 input-drive 支路。input-mark 始终读取当前原始帧；缓存不计算标签、不计算 A+B，不读取未来。Hold 会增加显式观测记忆，unsigned 会增加活跃参数；结果不能声称完全等有效容量。

Unsigned 参考率来自无数据的名义 stationary law：在 active + refractory recurrent class 解 πG=0、π1=1，取 j₀=πe。旧 interval 的 unsigned 分量可替换为 j−j₀ 或 tanh(j−j₀)，τ 固定为 1。初始 step0 的空消息保持 0。它不保证非平稳数据上的实际均值为 0。

## 时间与完整状态

原慢控制每 2 个观测更新一次。只出现于奇数观测的 late cue 可能被原 boundary-only 路径完全遗漏。构造权重的因果诊断验证：late=5 对原路径的全部 12 步输出影响严格为 0；累加/保持路径能够改变后续 receiver margin，且不能改变先前输出。该诊断只证明信息路径，不证明训练准确率。

流式状态包含原五张物理张量、pending/held 两张输入缓存、控制语义、unsigned 变换语义及绝对 step。`pack_state`/`unpack_state` 使用纯张量和基础类型，支持 `torch.load(..., weights_only=True)`。已测试奇数切分后的序列化 roundtrip 与连续执行精确一致；这是同进程序列化续算证据，未冒称跨机器/版本兼容。训练每个 minibatch 从声明的初态重新开始，所以模型 checkpoint 不伪装成保存了任意半途 minibatch。

## 预算和封存

Train source 13000–13011、dev 14000–14003、test 15000–15015；每个 test source 64 个样本。三个集合来自相同模拟器的不同 source 身份。它们没有复用旧公开 test300–307，也不等于新的真实传感器模态。

每臂 512 个实际 Adam 更新；900 training CPU 秒仅为安全上限，未完成 512 次的记录明确标为 censored。另保留累计 update CPU 不超过 180 秒时最后一个完成更新的 checkpoint。开发集每 64 更新评估一次，以 final cross-entropy 选择，初始 step0 同样是候选；180 秒快照不按 dev/test 再选择。

所有 21 个终态先验证并整体 seal，再创建唯一 test claim。每个 test worker 重验全部封存文件、模型完整性与自己的独占 claim 后才构造 test。失败保留在三 seed 分母；不按 test 重新训练、重选或挑选最好臂。

`communication.py` 文件头所说的“outside prospective training closure”指原 63-fit 主闭包；它明确包含在本通信实验的 24-file 闭包内。该闭包为原 14 个物理/训练依赖、6 个主实验模块、4 个通信模块，协议同时绑定原 protocol JSON 的 SHA。后处理脚本不进入训练闭包，其自身 SHA 随验证结果另记。

## 观测和费用

观察器记录原始/实际结构掩码后的每通道均值、RMS、时间均值的空间 RMS、各通道对 receiver/sender drive 的贡献，以及 `abs(tanh(preactivation)) >= 0.95` 的饱和比例。每次 backward 还记录全局 clipping 前的 recurrent 三支路梯度范数。所有统计均 detach，绝不回流到模型或归一化。

Training 阶段统计混合变化中的权重；test_selected 统计对应一次冻结的选定模型。两者分开。观察器的 CPU 计入每个臂的 update/body/worker 成本；这些不是未经观测器的部署速度基准。

Linux operator runner 使用 `resource` 和 Linux `ru_maxrss` 单位。正式任务以 systemd scope 500% CPU、4 GiB 内存上限、5 个 fresh workers 执行。更新 CPU、fit body、完整 worker、阶段 child CPU 与外层 wall 是嵌套视角，不相加。峰 RSS 是单进程峰值而非并发总量；能量未知。

## 复现命令

在包含绑定旧依赖和本目录的仓库根执行。正式输出目录必须尚不存在；不能把已有尝试目录作为重试覆盖。Torch/NumPy/Python 版本和单线程设置由 prepare 记录，后续每个 worker 都核对。

```bash
python -m qualification.hcsn_closure_20261124.communication_run prepare --root /absolute/new-communication-run
python -m qualification.hcsn_closure_20261124.communication_run run --root /absolute/new-communication-run --workers 5
```

预检在另一个输出目录进行，且不会打开正式 test：

```bash
python -m unittest qualification.hcsn_closure_20261124.communication_tests -v
python -m qualification.hcsn_closure_20261124.communication_run prepare --root /absolute/new-communication-smoke
python -m qualification.hcsn_closure_20261124.communication_run smoke --root /absolute/new-communication-smoke --workers 5
```

全部完成后，独立 NumPy 后处理验证封存/预测 SHA，重建 test 数据摘要并从全部 prefix logits 重算三份模型的概率、停止、source、cue parity 与初态分组指标。它不加载 Torch、模型或 checkpoint，也不执行第二次模型评估：

```bash
python -m qualification.hcsn_closure_20261124.communication_analysis --root /absolute/new-communication-run --output /absolute/new-communication-summary
```

正式因果/数值预检回执保存在 `evidence/communication_training_preflight/`。

## 已完成的确认结果

全部 21 个 fit 完成 512 更新、21 个 test worker 正常退出。独立 NumPy 对 selected / initial / 180CPU-prefix 共 63 份输出重算，最大指标误差 2.22e−16；验证了 24 个绑定源码及全部封存文件。完整表见 [RESULTS_COMMUNICATION.md](evidence/communication_training/summary/RESULTS_COMMUNICATION.md)，逐 source、初态与机制量见 [SUMMARY.json](evidence/communication_training/summary/SUMMARY.json)。

| 通信方式 | 最终正确率，3 seed mean ± SD | 通过学习和数值门的 seeds |
|---|---:|---:|
| signed only | 91.960% ± 0.665% | 3/3 |
| unsigned raw + signed | 86.751% ± 9.342% | 2/3 |
| unsigned centered + signed | 93.717% ± 0.589% | 3/3 |
| unsigned centered bounded + signed | 93.490% ± 0.343% | 3/3 |
| boundary raw | 50.293% ± 0.000% | 0/3 |
| boundary accumulate | 50.293% ± 0.000% | 0/3 |
| boundary hold | 65.169% ± 25.767% | 1/3 |

边界三臂的组门全部失败。因果路径修复能够让奇数时刻的 cue 进入物理控制，但没有自动解决本预算内的优化困难。Hold 只有一个 seed 学会，不能从其最好单次结果推出边界编码稳定有效。

与原始 unsigned 相比，centered 臂的实际 unsigned 均值/RMS 从 0.379/0.411 降至 0.0373/0.100；慢控制更新时的 tanh 饱和率从 42.95% 降至 6.15%。Signed-only 为 6.19%；boundary raw / accumulate / hold 分别为 44.01% / 42.05% / 34.70%。这些是 3 个冻结模型的 test 均值，说明有可测的偏置和饱和关联。它不是“unsigned 永远有害”的证明：raw 仍有 2/3 过门，centered 两臂均稳定学会；也不构成独立于参数容量的普遍因果结论。

尝试更新 CPU 共 8372.031 秒；fit body 9352.639 秒；完整 fit/test 子进程包含 import/shutdown 共 11019.126 秒；外层 run 为 2601.792 秒 wall / 11037.101 秒 subtree CPU。后两项包含前面的成本，不能相加。最大单进程峰 RSS 为 385,892,352 bytes；能量未测。

五份精确成员档案覆盖正式结果、冻结源、完整 smoke、独立分析源及最初因果诊断，含全部 checkpoint、预测、错误与费用；档案索引在 [ARCHIVES.json](evidence/communication_training/ARCHIVES.json)。这 7 臂不含无 unsigned 的 boundary+signed 联用臂，不能把原来的 full 通道结果代替该对照；该问题属于另一个独立登记实验。
