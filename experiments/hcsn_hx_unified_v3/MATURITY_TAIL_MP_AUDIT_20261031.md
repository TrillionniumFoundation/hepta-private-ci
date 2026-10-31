# HCSN P0：HX 有限到期债券远端条件修复及 65 位独立复核（2026-10-31）

**范围：** 研究专用，继承草稿 #4496 的冻结 HEAD `5e676d7e91d0be9137eb12b2410d1dbada43f254`，生产仍为 `DENY_ALL / NO_GO`。不改上游 HX Eq.(8)/(12)/(A7)、既有研究源码、历史失败观测、原生 owner、模型权重或 CI 门禁。

## 发现并保留旧错误

第一版 `hx_obstacle_grid_independent.py` 在无限资产近似（有限网格上端）使用了 `coupon_per_bond/q`。然而固定剩余期限 `T` 的无违约存续债券仍要偿还本金，其正确无违约价为

`B_infty = c/q + exp(-q*T)*(P-c/q)`

其中 `c=coupon/T`，`P=principal/T`，`q=rate+shock_intensity*sale_fraction`。原远端 Dirichlet 误差为 `(c/q-B_infty)/rate`，并通过有限区间传导至自由停止区。此前 #4496 报告的 `sale_fraction=.2` 额外停止区至约 112 的宽度**必须撤回**；这部分显著受遗漏本金的远端近似影响。旧源码与历史数值仍保留，便于复核错误来源。

新增 `hx_obstacle_grid_tail_v2.py` 只修正上述固定到期债券远端常数，仍复用同一独立布朗首达密度数值积分、M 矩阵 Howard 求解器、障碍值和有限网格拒绝语义。并没有伪装成已解决金融耦合不动点或连续全域问题。

## 实际独立复算

Python 3.13.5、SciPy 1.17.0、mpmath / PyTorch CPU（无 CUDA）。旧 13 项 + 新 5 项 `unittest` 在本地参考副本 **18/18 PASS、0 skipped**。本地使用先前重建的 HX 子集；**不是全仓 checkout、Cargo CI 或生产执行**。

- `hx_bond_mp_reference.py` 使用 mpmath 65 位十进制精度，在物理时间 `t` 上直接积分布朗首次穿越密度，按密度模态拆分区间。与候选的 `u=v/(sigma*sqrt(t))` 变换 / SciPy 无限区间积分属于独立数值路径；测试覆盖 4 套参数 × 4 个资产倍率 = 16 组。观察最大绝对债券值差 `7.105427357601002e-15`。这不是对所有参数、所有输入编码或机器舍入的严格区间证明。
- `sale_fraction=.015`：代数候选边界 `64.6251766753`。无违约债券正确上端 `30.0937727454`，旧错误为 `30.7692307692`；相应远端权益 Dirichlet 改变量 `-13.5091604757`。三档网格均未检测出额外 STOP，**不能据此宣布全域最优**。
- `sale_fraction=.2`：代数候选边界 `101.324028609`；原始固定边界权益在 `1.01*b` 处为负 `-0.000489285571854`。正确无违约债券 `21.3436745137`，旧错误 `8`，远端权益 Dirichlet 改变量 `+266.873490274`。修正后网格的额外 STOP 上界依次为 `105.038146648` (101节点)、`103.164374548` (201节点)、`104.097044639` (401节点)，仍为 **有限网格反例信号**，不能解释为可认证的连续自由边界。
- 三档网格最大离散 Bellman 残差 `4.55e-13`；但这不是连续 QVI 残差上界，远端截断误差也仍未认证。

## 复现

依赖 Python、SciPy、NumPy、mpmath、PyTorch CPU。从仓库顶层运行：

```bash
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_hx_obstacle_grid_independent \
  experiments.hcsn_hx_unified_v3.test_hx_coupled_smoothfit_independent \
  experiments.hcsn_hx_unified_v3.test_hx_implicit_financial_gradient \
  experiments.hcsn_hx_unified_v3.test_scalar_precision_screen \
  experiments.hcsn_hx_unified_v3.test_hx_tail_and_mp_reference
```

新增三个文件的 SHA（git blob，与本地执行文件及远端 GitHub 回读逐字节一致）：

| 文件 | git blob SHA |
|---|---|
| `hx_obstacle_grid_tail_v2.py` | `71866f321981424fe05e3c1ffaca6b92c71f0e80` |
| `hx_bond_mp_reference.py` | `3e1fe137624b9c8c2a843b7eb6226eca695a8a5f` |
| `test_hx_tail_and_mp_reference.py` | `3a5658011e58ef587ba83865471fd11d792940a5` |

## 严格未关闭的 P0–P5

**P0 OPEN：** 原始完整金融自洽多边界/不动点与全域 obstacle，有限域截断和机器舍入严格包围，FP32/BF16 *金融* 原生核与可靠活动集梯度、间断参数/退化极限。现有观察仅是有限域有限样本对照。

**P1 OPEN：** 八组同信息/同斜率/同活动参数/同训练与推理预算 Call/Risk/Margin 因果消融，样本外净增益与负迁移控制。

**P2 OPEN：** 可训练内容记忆，Selective Copy/MQAR/覆盖写入/长距离检索/非均匀时间与真实持久恢复。

**P3 OPEN：** 真实文本/图像/音频/视频成对 Encoder 与 OOD 对齐。

**P4 OPEN：** Rust/GPU 训练/推理算子，64/256/1024/4096 Cell 的端到端吞吐、p95/p99/RSS、真实 Joules 和故障恢复。

**P5 BLOCKED：** 严格匹配数据、token、FLOPs、质量与总成本的净胜出未证明。

`production_activation=false`，`all_scientific_blockers_closed=false`；只提交叠加草稿研究 PR，不合并生产。
