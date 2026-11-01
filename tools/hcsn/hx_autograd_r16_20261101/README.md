# 实际 H–X 核的一阶 PyTorch 适配器

本目录将已冻结、已验证的实际 H–X C++ **FP64** 核接入 PyTorch。现已实际通过 168 组方向差分、32 项接口合同检查及独立的 48 通道复核，以及一个两层、28 参数、80 步的小训练 smoke。该结果关闭的是一阶 BP 的接口接线，不是完整脉冲动力学、泛化、金融机制有效性或模型优势。

原金融核、原数值门槛和已有原始证据均未修改。依赖二进制为 `a96fbe8ee36be2fdaa2a5894462f415f9724acf199ae31745c471092c26f6615`；原金融协议为 `76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0`。当前适配器协议为 `9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72`。

## API、维度与精度

`HXOperator` 只接受 **CPU、torch.float32、形状 [...,10]** 的非空张量。十列依次是：

```text
r, delta, sigma, alpha, tax, liquidity, maturity, coupon, principal, state
```

前九列保持原金融参数含义和受控域。最后一列按 coordinate 选择正资产 V 或独立 log-distance x。参数可以由 trainable tensor 拼接、广播构造；PyTorch 会把各行的参数梯度沿相应广播关系累积。

| 接口 | 返回形状 | 内容 |
|---|---|---|
| `operator(packed)` | `[...,5]` | `b,E,F,G,debt`，原字段 |
| `operator.features(packed)` | `[...,7]` | 原五字段加 `R,x`，用于诊断；整个七维向量**不是**跨 default 的 C1 读出 |
| `operator.readout(packed)` | `[...,3]` | 只返回 `E/b,R,x`，供条件联合 C1 的值通道候选使用 |

所有返回值为 **torch.float64**；内部始终调用原核的 FP64 模式。F 是至 maturity 的首达概率，G 是相应的贴现首达变换，原核贴现率为 `r+liquidity`。它们不是两份独立的 call/put 价值。debt 保留原核定义，原实现使用 `c=coupon/maturity`、`p=principal/maturity`。

反向保存完整 5×10 float64 Jacobian，计算 VJP 后返回与输入一致的 float32 梯度。每项保存的 Jacobian 本身占 400 字节，不具备稀疏事件计算的内存优势。这里和通常浮点 AD 一样，求的是已表示输入处连续实值公式的导数，不是对舍入映射作经典微分。禁止把 float64 输入静默降为 float32。

接口采用 [PyTorch 官方的自定义 autograd Function 扩展方式](https://docs.pytorch.org/docs/2.15/notes/extending.html)。backward 入口在任何 no-grad 包装之前检查梯度模式；`create_graph=True` 的首次金融 VJP 即明确拒绝。独立复核在原六例的 raw5/readout3 共 48 个通道上，全部确认首次拒绝，且普通一阶输出与 VJP 逐位保持。它不提供 Hessian、JVP、torch.compile、GPU 或高阶 force 的支持。

## 坐标与 default 约定

- `coordinate='asset'`：输入正 V。原核在 `V<=b` 使用 default 分支：E=0，F=G=1，debt=alpha*b/m，并返回该分支的参数导数。精确边界处不能把原 F/G 的默认侧导数当作经典双侧导数。
- `coordinate='log_distance'`：x 是独立输入，要求 x>=0。x=0 采用续行侧右导数；该接口并未默默扩展到负 x。
- 新观测量 `R=1-(1-F)^2=2F-F^2` 在连续模型的常规边界假设下有零边界梯度，可作 C1 观测候选，但不改变 F/G 的语义，也不构成 C2 force 证明。
- asset 的信息读出为 x=log(V/b)，所以参数导数含 `-b_theta/b`，状态导数为 `1/V`。即使 E/R 已在 default 区饱和，x 仍能区分其中的正资产状态。
- 独立 log-distance 接口中，x 对金融参数的导数严格为 0，对自身为 1，不能再次加入 `-b_theta/b`。

这些 C1 陈述属于理想连续公式及其正 maturity、正 sigma、可微正边界等常规条件。它们不是关于浮点舍入映射、整个参数盒、time=0 corner 或通用高阶微分的证明。

## 已运行的梯度检查

六个固定功能 fixture 覆盖 asset 续行、asset default、log-distance 续行、log-distance 边界右侧和短 maturity。它们是已知金融区域内的接口例子，不是另一个金融泛化 holdout。

每点用 10 个坐标方向和 4 个混合方向，以两个预设步长检查，共 **168/168 通过**。检查没有导入金融 MP80 oracle，而是直接对实际前向值作差分；记录实际 FP32 端点、有效方向、中点偏移和每个端点的分支。边界状态用实际可表示节点的三点右差分，不跨越原 F/G 的非光滑拼接。

| 检查 | 预先固定门槛 | 实际最大误差 |
|---|---:|---:|
| 原字段及派生读出值对应关系 | 1e-12 | 见完整逐点记录 |
| 完整七字段×十输入的链式导数 | 1e-6 | 5.270680520615516e-8 |
| 方向有限差分 | 5e-4 | 9.51369304901294e-5 |

方向差分步长为相对 1e-3 和 5e-4，故其门槛包含有限步长截断误差；它**不修改或替代**原金融 Jacobian 的 2e-5 门槛。最大方向差分误差出现在短 maturity 的 asset state 方向、较粗步长、debt 通道。

另有 **32/32 合同检查**（新增两个坐标全部 raw5/readout3 的首次高阶请求拒绝），包括 dtype/device、形状、非有限输入、原核域、上游非有限梯度、float32 梯度溢出、double backward 拒绝、非连续内存批量 VJP，以及 default 的 R 饱和但 x 信息仍保留。

完整记录：`GRADIENT_AUDIT_V3.json.gz`，SHA256 `b00099d2260a4b906ad13e7c8dfdc340d2069117dd8343cc1ac52b6f4b138c0d`。本体 wall 为 0.22445 秒、process CPU 为 0.11503 秒，369 个金融状态评估；不含 PyTorch 导入时间。这不是性能分布或生产吞吐 benchmark。

## 两层训练 smoke 与实际金融通道梯度

smoke 使用两层金融读出，每层仅把 **E/b、R、x** 传给下一层；原 F/G/debt 不作为网络通道。两层各有九个 trainable raw_theta，通过 `theta=base*(1+0.03*tanh(raw_theta))` 约束在基准附近，加上两层状态投影和最终线性 head，共 **28 个参数**。训练固定为 32 个合成点、80 步 Adam。

同一训练网格上的 MSE 从 **1.2916021347** 变为 **0.1068059132**。全部八个 named parameter tensors 都发生实际更新。两层金融 raw_theta 首步梯度范数分别为 **0.00103818、0.0133650**；最终有效 theta 最大相对变化分别为 **0.8575%、0.5452%**。完整每步 loss/梯度、初末参数及预测保存在 `TRAINING_SMOKE_V3.json.gz`。

`READOUT_VJP_EVIDENCE_V3.json` 还保留六个相同 fixture 上各通道独立执行的 PyTorch basis-VJP。在 log-distance 续行点，E/b 和 R 对九个金融参数的实际 VJP 范数分别为 **0.74410385、2.02200162**，x 对 theta 的导数严格为 0。因此金融通道确实连接到上游参数，不只是提供不可导常数。

这仍然不能把 loss 下降归因于金融机制：x 旁路和 head 可能解释任务拟合，没有通道消融或泛化测试。theta 的更新不等于学会最优自由边界策略；当前也没有跨时间状态、reset、refractory 或事件发放机制。

训练本体 wall **0.81198 秒**、process CPU **0.26384 秒**，共 164 次 backend batch 调用、5,248 个金融状态评估；包括初末前向，不含导入和 optimizer 构造。这里只证明小型真实 BP/update 在当前 CPU 环境能运行。

## 两个失败尝试与 V3 修复

首次 V1 审计在 JSON 写出时遇到 `numpy.int64` 布尔汇总类型，退出 1，没有宣称通过。`attempt_v1/` 保留完整原源、协议、fixture 和失败 receipt。V2 只把 receipt 布尔标志转换为 Python bool；适配器、金融核、输入、步长和门槛全部未变。相同功能例明确作为已打开例子重新运行，不冒充新的独立金融验证。

随后独立审阅发现 V2 的 `once_differentiable` 保护不完整：复合 readout 的高阶请求可能静默得到零或部分 Hessian。V2 源和完整一阶结果、高阶失败脚本与结果全部保留在 `attempt_v2/` 和 `independent_review/`，不能宣称其高阶合同通过。V3 移除遮蔽梯度模式的装饰器，在 backward 最外层直接拒绝高阶请求；正常一阶收缩不变。`FIRST_ORDER_IDENTITY_V3.json` 确认全部一阶矩阵、168 个方向记录、80 步每个梯度/loss、初末参数与预测均与 V2 规范 JSON 逐字相同。V3 独立复核实际退出 0；V2 另一份缺陷复现虽完整写出数据，但进程随后被中断为 130，原执行收据如实保留。

## 复现

依赖为 CPU PyTorch 2.15.0+cpu 和 NumPy 2.3.5。随附原金融 `.so` 针对 Linux x86_64；其他编译器/平台需要新的构建身份与相应回归，不能静默覆盖冻结库。

```sh
python -m pip install -r requirements.txt
python -B audit_gradients.py --frozen-root ../compiled_fp32_r16_20261101/recovery --protocol-sha256 9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72 --output local_gradient_audit.json.gz
python -B training_smoke.py --frozen-root ../compiled_fp32_r16_20261101/recovery --protocol-sha256 9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72 --output local_training_smoke.json.gz
```

审计脚本退出 0 要求所有预登记方向/链式/合同检查通过；训练脚本退出 0 只表示预登记 smoke 条件通过。输出 create-only。`readout_evidence.py` 读取本目录已发布的 `TRAINING_SMOKE_V3.json.gz`，用新的 output 路径重现逐通道 VJP 和有效 theta 更新记录。

```python
import torch
from hx_autograd import HXOperator

operator = HXOperator('../compiled_fp32_r16_20261101/recovery', coordinate='asset')
packed = torch.tensor([[.08, .02, .23, .6, .27, .01, 1., 6.39, 61.68, 100.]],
                      dtype=torch.float32, requires_grad=True)
observable = operator.readout(packed)  # float64 [E/b, R, x]
observable.square().sum().backward()
assert packed.grad.dtype == torch.float32
```
