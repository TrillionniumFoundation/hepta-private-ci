# 解析核消融后的内容读出器重新拟合

本补充完成的是**冻结解析 renewal 核上的内容读出器重拟合**，不是完整解析 AV 网络、物理参数或控制策略的重新训练。原 v8 的三种计数预测 `original`、`mean_two_point`、`single_transition` 保持相同定义；每种预测分别训练同容量的 30 参数 multinomial 读出器，并与完整模型权重直接用于消融特征的执行期消融比较。

训练标签来自独立 inverse-Gaussian 首达与复位事件模拟，再按公开五类 Markov 转移生成内容。所有模型获得相同的初始真实内容、gap、horizon、drift、sigma、reset 和 refractory 参数。真实事件数和未来内容标签只用于训练监督或评分，不作为输入。该任务具有已知公共动力学与完美初始传感器，仅使用固定观测和单个强制输出，不能回答闭环 READ 策略、开放域内容、跨模态绑定或核心采用问题。

## 实际运行与保留的失败

- 第一轮 `development001`：五个拟合种子、每种特征两项 L2、共 30 个候选中 25 个达到 120 步预算；验证选中的 15 个模型全部达到上限。全部数据、参数、30720 条预测、优化器状态和精确源码快照保留；不称为已全部正常终止。
- 第二轮 `development002`：仅依据优化器状态增加上限至 1200 步，并冻结新的拟合种子和新的 1024 个留出世界。训练 2048、验证 512，每项拟合的 L2 仅由验证 NLL 选择。30 个候选均返回 `optimizer_success=true`（SciPy 正常停止；包含 ftol 条件，不代表全部满足 gtol）；五个拟合种子与六个执行臂产生 30720 条预测。
- 数值梯度、独立 IG 生成与解析概率、精确 AST 提取、重新拟合实际改变参数等 5 项检查通过。早期测试路径错误及修正有记录。
- 两轮独立原始记录审核各复核 30720 行、存储权重回放及 NLL/accuracy/Brier；最大概率回放误差均为 `1.1102230246251565e-15`。

## 第二轮结果

下表为五个拟合种子在共同留出世界上的均值。NLL/Brier 越低越好，准确率越高越好。

| 执行臂 | NLL | 准确率 | Brier |
|---|---:|---:|---:|
| refit_original | 1.053633 | 0.549609 | 0.542554 |
| unfitted_analytic | 1.046792 | 0.541016 | 0.539748 |
| same_weight_mean_two_point | 1.159124 | 0.515625 | 0.562912 |
| refit_mean_two_point | 1.100907 | 0.525195 | 0.551588 |
| same_weight_single_transition | 2.366317 | 0.525977 | 0.600606 |
| refit_single_transition | 1.289141 | 0.526367 | 0.629195 |

消融模型重新拟合后，相对完整模型的 NLL 差分别为 `+0.047274`（跨拟合/世界 bootstrap 95% 区间 `[0.018392, 0.079464]`）与 `+0.235508`（`[0.196849, 0.272972]`）。相对同权重执行期消融，重新拟合降低 NLL 约 `0.058217` 和 `1.077176`。这说明只做执行期消融会明显放大一部分退化。

指标并非全向改善：单转移消融重新拟合后 NLL 改善，但 Brier 由 `0.600606` 升至 `0.629195`；完整模型重新拟合 NLL `1.053633` 也没有超过不拟合的已知解析参考 `1.046792`。这些结果只限定当前特征、读出器容量、任务分布和优化方法，不能证明完整机制的普遍必要性，也不能替代强普通核心或真实 AV 对照。

## 成本与复现

两轮实际 `execute` 均由外层进程族计量包裹。任务 CPU 合计 `30.172437` 秒；该合计包含第一轮预算失败，不再叠加内部计时。外层观察者 CPU 另列于 `REFIT_REPORT.json`。样本内存保持 `sampled_partial`，完整连续进程族内存峰值、设备能量和未计量准备/分析成本仍为未知。详见相邻 `economics/results/refit_execute001/RECEIPT.json` 和 `refit_execute002/RECEIPT.json`。

已有结果使用排他写入；复现时为新路径创建 PLAN 后执行，不覆盖原凭证：

```sh
python -m experiments.hcsn_v9_followup_20261101.refit_ablation.campaign prepare --output /tmp/hcsn-refit-reproduction
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v9_followup_20261101.refit_ablation.campaign execute --output /tmp/hcsn-refit-reproduction
python experiments/hcsn_v9_followup_20261101/refit_ablation/review/audit_refit.py /tmp/hcsn-refit-reproduction
```

当前顶层源码对应第二轮；第一轮对应其 `source_snapshot`。原 v2/v8 定义仅通过显式 AST 选择复制，未修改旧文件、未提供伪造 torch 模块。来源身份见 `SOURCE_EXTRACTION.json`。
