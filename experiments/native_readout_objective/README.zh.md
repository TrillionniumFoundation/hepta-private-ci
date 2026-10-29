# 下一步实验准备：固定 Hepta sparse kernel，隔离读出训练目标

## 当前状态

本目录完成了两种匹配读出训练器、独立梯度检查及历史原生记录的 Q24 读出核对。**这是研究准备，尚未完成新研究驱动器、原生构建与新确认实验。** `PROTOCOL.json` 是待发布草案；不得将它称为已经公开预注册的协议。

旧 `continuous_boundary_flow` 的 0/3 与 `continuous_boundary_policy` 的 0/4 结论分别保留。本次没有扩充它们的样本、重选模型或修改验收门槛。历史结果与本次恢复范围见 [RECOVERY_STATUS.json](RECOVERY_STATUS.json)。

## 为什么先做这个对照

[上一轮报告](../continuous_boundary_policy/REPORT.zh.md)中，普通 GRU 的总体净效用为 3.679388，native sparse 为 3.118986。但前者全量训练 464 个参数并采用策略损失，后者冻结 420 个 encoder 参数、只用 ridge 拟合 42 个 head 参数。这个比较同时改变了容量、训练程序和模型家族，不能据此把差距归因于 neuron 动力学。

下一步将原 sparse kernel、20 维状态、top-k=4、同一 encoder、42 个读出参数和原 NDU 固定下来，只研究读出训练程序。

| 臂 | 训练程序 | 解释范围 |
| --- | --- | --- |
| A：ridge reference | 旧闭式 ridge Q 回归，3 个既定正则候选 | 整个训练程序的工程参考 |
| B：iterative Q-MSE | 固定 Adam 拟合 Q/8 | 主对照 |
| C：policy regret | 相同 Adam，teacher-action CE 加归一化 DP regret | 主处理 |

**唯一主比较是 C−B。** A 与 C 的差异同时包含闭式求解和迭代优化的差异，不单独解释为 loss 效果。三臂都必须从真实原生执行导出同一激活矩阵，接收同样的 margin、续行值、风险、历史活动、成本和期限信息。

## 已实现的数学与边界

读出用 20 个原生激活加常数项，输出 keep/repair 两个 affine score；STOP 的全部系数固定为零。令设计矩阵为 X，42 个可训练系数组成 W，则分数是 `(XW, 0)`。

B 的损失是两个非 STOP 分数对物理 Q/8 的均方误差。C 使用温度为 1 的 softmax，损失为 teacher-action 交叉熵，加各动作 `gap/(1+max gap)` 的概率加权平均。两者都加 `1e-4 × mean(40 个非 bias 系数的平方)`；bias 不正则化。teacher 平局按 STOP、repair、keep 依次优先。

B/C 共享精确零初始化、full-batch Adam、120 次更新、学习率候选 0.005/0.02/0.05、梯度范数上限 5 和系数绝对值上限 7.5。相同预算不表示相同 CPU 成本；正式研究将分别计时。42 是可训练系数分配量，实际激活列和非零梯度覆盖另记。

原生 head 逐项计算 Q24 乘积，每项采用 signed ties-to-even 舍入，然后与 bias 相加；head 分数不做 clamp。encoder 的 clamp 与 head 算术不能混淆。`q24_scores` 实现这一算术用于诊断，不运行 sparse kernel 或 NDU。梯度只经过浮点 affine head，不穿过 Q24；这不是端到端可微原生 neuron。

`head.fit` 返回全部系数及完整训练收据。它验证形状、有限性和数值域，但**不验证输入属于训练集或由真实 native host 产生**；收据明确标记这些限制。后续 study runner 必须验证数据阶段、激活来源、源封存、二进制身份和 profile 链，才能用于正式研究。

## 本次实际预检

[NUMERICAL_PREFLIGHT.json](NUMERICAL_PREFLIGHT.json)保留了实际执行收据：7 项检查通过；两种 loss 各自全部 42 个坐标通过中央有限差分；正则、bias、teacher tie、浮点训练确定性、无效域拒绝及独立有理数 Q24 参考均通过。

另从已恢复的旧研究读取 8 个 native checkpoint、16 个 shard、2,048 条 episode、22,883 个原生记录步骤。逐项重算 score 和注册的动作 tie rule，score 标量与 action 不一致均为 0。记录绑定原 profile、checkpoint 和 shard 的 SHA-256。这只是已公开旧记录上的算术核对，没有运行新的 native 进程，也没有把旧确认集用于训练或产生新收益证据。

本次预检 CPU 0.999433 秒、wall 0.999552 秒，只描述该数值检查窗口。代码格式化后的身份与受测版本的 AST 一致性另保留在 `FORMAT_VALIDATION.json`；格式化后没有重跑测试套件。

在另一个全新工作副本验证实现时，可运行以下命令，输出必须尚不存在：

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
python -m experiments.native_readout_objective.preflight \
  --old-evidence-root /absolute/recovered-old-evidence \
  --output /absolute/new-preflight-receipt.json
```

这不是新科学研究的启动命令。旧证据可由 `continuous_boundary_flow.evidence_bundle` 从已发布旧归档恢复。

## 待执行的固定研究方案

[PROTOCOL.json](PROTOCOL.json)锁定了拟采用的 16 个新 seed。每 seed 12 个训练 context、8 条公共探索路径/context；8 个开发 context、8 条路径/context；确认包含各 8 个 ID/OOD context、16 条路径/context。三臂和 DP 参考合计计划 16,384 条确认 episode，每臂 4,096 条。训练、开发、确认使用按 phase 分开的随机流；各臂共享同一环境创新。

探索轨迹固定沿用原 `behavior_data`：每窗口 80% keep、20% repair、不采样 STOP，并运行完整期限；训练窗口等权，不按目标函数重采样。原 `target_q` 已除以 8，驱动器必须先乘以 8 恢复物理 Q，再追加零 STOP 后传给 `head.fit`，避免二次缩放。所有臂共享同一实际原生激活矩阵。

主统计单位是 16 个配对的训练/环境 seed；C−B 的双侧 95% t 区间下限须大于 0.005，且稳定性失败为零。只有一项主比较，不能把描述性指标另算作通过的收益门槛。不得按确认结果继续加 seed。

正式报告同时覆盖：ID/OOD 净效用；共同解析风险预测器在各策略访问分布上的 Brier/ECE；同一独立诊断状态面板上按 teacher keep/repair/stop 条件分组的物理 action regret；float 与真实 Q24/NDU 的动作差异；训练、DP/模型构造、完整运行、序列化和实际通信成本。风险校准变化不能单独解释为风险预测器变强。

量化诊断保留有符号的 `regret(Q24/NDU action) − regret(float action)`；负值表示该状态上量化反而改善动作，不能把全部 action flip 解释为损失。

三臂采用相同 native 输入接口，每步 20 个 i64，即 160 个计价数值字节，按原口径扣每 byte `1e-6`。完整 JSON 请求和响应另测；共享 setup 与子进程 CPU 不重复累计。`head.fit` 内部时钟不含最初输入验证和数组分配，正式 runner 需用包围窗口核算完整阶段。没有硬件能耗测量，不作节能结论。

## 正式运行前尚缺的工作

需要接合 ridge 臂、新的 study runner 与严格数据阶段验证；重新构建并验证原生 host，封存实际的新二进制身份；完成诊断 seed 上的真实 native 集成预检。原二进制当前未恢复，不能把重建文件冒称为原文件。

之后依次发布完整新源码/协议/二进制封存、运行训练和开发选择、发布选择封存，再打开确认集。当前公开发布曾被自动审批拒绝，不能以更换工具、数据编码或目的地绕过。旧补充实验完整原始档案的恢复问题也要独立处理，重新运行只能形成新的复现记录。

研究保持 `DENY_ALL`，不触发生产 admission 或主线合并。
