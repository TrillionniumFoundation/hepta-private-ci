# 完整 He–Xiong 金融算子的 JAX 自动微分验证

## 结论

**完整原文 Eq. (12)、A7、F/G 已实际接入纯 JAX 自动微分，float64 验证通过；当前 float32 实现没有通过同等精度验收。** 本次没有改动 NumPy/mpmath 全域参考，也没有改动原有 `validation_results.json`。

这补齐了“完整原式只有数值复现，训练只使用简化算子”的接口缺口：现在已有能够返回真实 AD 梯度的完整金融核。尚未用该核重新训练网络，不能将此前简化算子的训练结果归因于这套完整核。

## 新文件与运行

- `jax_hx.py`：纯 JAX 边界、完整 A7、F/G、ODE 推导的边界局部 Taylor 求值，以及明确标注的违约区延拓。
- `validate_jax.py`：前向、状态导数、9 参数总导数、边界条件、接缝、float32/64 与不支持参数拒绝测试。
- `jax_validation_results.json`：本次实际输出、全部比较值、导数矩阵、环境和新代码 SHA-256。

CPU 复现环境为 Python 3.12.14、JAX 0.4.38，验证程序显式启用 x64：

```bash
python -m pip install -r analytic/requirements.txt
python -m pip install 'jax[cpu]==0.4.38'
python analytic/validate_jax.py
```

当前受管理环境使用以下命令，无须重新安装：

```bash
PYTHONPATH=/tmp/hcsn-jax-20261029:/tmp/hcsn-encoder-20261029 \
  python -B analytic/validate_jax.py
```

最新运行退出码为 0，`all_float64_checks_passed=true`，包括编译的总耗时约 57.74 秒。这是 CPU 验证耗时，不是训练吞吐量。

## 接口与受控域

参数向量的固定顺序是 `r, delta, sigma, alpha, tax, liquidity, maturity, coupon, principal`。

| 参数 | 接受范围 |
| --- | --- |
| r | [0.04, 0.15] |
| delta | [0.01, 0.2] |
| sigma | [0.08, 0.8] |
| alpha | [0, 1] |
| tax | [0, 0.6] |
| liquidity = xi*k | [1e-4, 0.1] |
| maturity | [0.01, 20] |
| coupon | [0.5, 10] |
| principal | [20, 100] |

还要求解析边界为正且有限，连续区公式使用非负对数距离 `x=log(V/Vb)`。本次测试来自原 26 组中的 13 组受支持案例，另加 `liquidity=1e-4` 下界案例；这一矩形范围不是所有组合都已验证的声明。风险函数使用正 horizon，本次验证 horizon=maturity。

`validate_parameters` 在主机侧对不支持参数抛出 `ValueError`；在 JIT 核中，非法参数返回 NaN，避免默默套用其他公式。零流动性和极短期限仍应交给原 NumPy/mpmath 参考。本实现没有用 epsilon 替换分母，没有把 lambda=0 伪装成小正数。

示例：

```python
import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
from analytic import Parameters
from analytic import jax_hx

theta = jnp.asarray(jax_hx.validate_parameters(Parameters()), dtype=jnp.float64)
equity = jax_hx.equity_asset(100.0, theta)
parameter_gradient = jax.grad(lambda p: jax_hx.equity_asset(100.0, p))(theta)
```

`parameters_from_raw` 提供可选的有界可训练参数化。参数域之外的最优化、无效边界恢复策略和训练器集成均未在本轮验证。

## 真正求导的对象

边界是原式 (12)；股权是原式 A7 与 A5 的等价稳定组合；F/G 是原式 (9)。指数与正态尾用 `log_ndtr` 稳定求值。在非常接近边界处，股权使用原 ODE 导出的四阶 Taylor 数值求值，与已验证的 NumPy 实现相同。这里的 Taylor 是明确的局部求值近似。

JAX 对这些真实运算直接求导，**没有 custom JVP、custom VJP、straight-through estimator 或人为指定梯度**。参数导数在固定 V=100 下计算，因此自动包含 Vb 随参数变化的链式效应。

## 实际测量

| 项目 | float64 | float32 |
| --- | ---: | ---: |
| 14 组边界最大绝对误差 | 2.701e-13 | 1.395e-3 |
| 14 组股权最大绝对误差 | 4.524e-11 | 1.996e-2 |
| F/G 最大绝对误差 | 2.221e-16 | 1.118e-7 |
| 状态导数最大归一化误差 | 3.554e-7 | 0.1387 |
| 基准 9 参数 Jacobian 最大归一化误差 | 8.450e-9 | 2.130e-5 |
| Taylor/A7 接缝价值差 | 6.648e-11 | 1.422e-2 |
| Taylor/A7 接缝一阶导数差 | 7.961e-10 | 0.3562 |
| 通过同一科学精度验收的案例 | 14/14 | 0/14 |

“归一化误差”的分母为 `max(1, abs(reference_derivative))`。状态参考为原 NumPy 实现的五点有限差分；9 参数参考通过独立 Green 积分和自由边界求根，使用步长减半的中心差分。原始矩阵全部保留在 JSON。

float64 的最困难案例是 lambda=1e-4；仍通过状态和参数梯度阈值。float32 的问题集中在 A7 消差：m=0.01 的股权误差约 0.00825，lambda=1e-4 的股权误差约 0.01995，后者状态导数误差约 0.139。F/G 单独的浮点精度较好，不能据此认定整个双通道核适合低精度训练。

**当前建议将这套完整金融核限定为 float64 研究接口。** 批量混合精度训练、低精度稳定重写、GPU 性能和学习效果需要后续独立实验。本轮未尝试通过缩小误差表中的困难案例、改变验收门槛或扩大 Taylor 区域来宣称 float32 成功。

## 边界与跨边界一阶导数

所有受支持案例均显式验证 `E(x=0)=0`、`dE/dx(x=0)=0`。基准 Vb=67.44151539060373，股权在默认区延成 0：

| 相对位置 V/Vb - 1 | E | dE/dV |
| --- | ---: | ---: |
| -1e-6 | 0 | 0 |
| 0 | 0 | 0 |
| +1e-6 | 4.6372e-10 | 1.3752e-5 |
| +1e-4 | 4.6359e-6 | 1.3746e-3 |

这些结果与股权的 C1 贴合一致。Taylor/A7 数值接缝有上表量化的极小浮点/截断差；不能声称实现具有无限精度的全域光滑性。

**F/G 的默认区常数延拓不满足 C1。** 基准 F 的左侧 dF/dV=0，而右侧极限为 **-0.06138831140617**。JAX 在边界选中的单支导数不能消除这个数学跳跃。本文件故意将接口命名为 `risk_asset_constant_extension` 并保留这一事实：它不是原文的 smooth-pasting put，不能未经另行定义风险通道就作为“全域一阶连续神经算子”使用。

## 证据边界

本轮结论是：**受控范围内，完整金融解析解能够实际自动微分，且 float64 梯度与独立数值参考一致。** 这不等于完整 HCSN 已训练成功，也不等于原文为再生/恢复神经动力学或全模态模型提供了现成定理。

原有 `validation_results.json` 的 SHA-256 在运行前后保持一致，值为 `54c55d33331cc7bdc7a7147f9ffdba769806a8421821319ae0c3ddd89a7316a0`。新结果单独记录自己的代码哈希。理论与公式来源仍为 [He & Xiong (2012)](https://www.princeton.edu/~wxiong/papers/rollover.pdf)。
