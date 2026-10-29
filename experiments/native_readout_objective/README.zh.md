# 固定 Hepta sparse kernel 的读出训练目标实验

## 当前状态

**正式研究已完成：独立确认审计 PASS，唯一预注册收益门槛为 0/1。** `policy_regret − iterative_q_mse` 的平均净效用差为 **−0.005370044**，双侧 95% 配对 seed t 区间为 **[−0.114120162, 0.103380074]**，未满足下限严格大于 0.005 的门槛。稳定性失败为零；该区间不能证明两种目标等效，也不能证明策略目标更差。[完整中文报告](REPORT.zh.md)；[主比较精确数据](results/PRIMARY_COMPARISON.json)

本轮使用 16 个独立配对 seed，完成 16,384 个确认 episode、143,262 个学习臂真实原生 kernel/NDU 决策步骤。六例固定 owner 工程检查完成 84 步、6 次不同 PID 冷恢复与 66 个恢复后继续步骤，全部通过；这六例没有 STOP，相关探针实际覆盖为零。[独立审计摘要](results/AUDIT_SUMMARY.json)；[owner 结果](results/OWNER_SUMMARY.json)

源码与协议先发布于 [`7908860…`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/7908860cb959cbe1599379d4ecbfcc22fbccbe61)，开发选择随后发布于 [`87b03617…`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/87b03617077f9e5f275d291b7af06cd1418f87ce)，确认在选择发布后才启动。报告与派生结果均绑定完整审计 SHA-256。原始档案已从公开远端恢复并完成独立语义重审，实际收据入口见本文末节。准备期收据、正式科学结果、工程验证与 GitHub CI 状态分别保留。

旧 `continuous_boundary_flow` 的 0/3 与 `continuous_boundary_policy` 的 0/4 结论分别保留。本次没有扩充它们的样本、重选模型或修改验收门槛。历史结果与本次恢复范围见 [RECOVERY_STATUS.json](RECOVERY_STATUS.json)。

## 结果与证据入口

| 文件 | 内容 |
| --- | --- |
| [REPORT.zh.md](REPORT.zh.md) | 研究结论、对照设计、效用与风险、量化诊断、工程范围、完整成本口径 |
| [AUDIT_SUMMARY.json](results/AUDIT_SUMMARY.json) | 来源与确认审计覆盖、0/1 门槛、训练覆盖和 owner 概要 |
| [PRIMARY_COMPARISON.json](results/PRIMARY_COMPARISON.json) | 16 个 seed 的配对差、精确 95% 区间与分组描述 |
| [ARM_SUMMARIES.json](results/ARM_SUMMARIES.json) | 四臂 ID/OOD 净效用、风险校准 bins、动作及真实调用计数 |
| [COST_SUMMARY.json](results/COST_SUMMARY.json) | 科学阶段、外层命令、独立审计、owner 与通信成本，注明包含关系 |
| [COMMON_STATE_PANEL.json](results/COMMON_STATE_PANEL.json) | 同状态条件 regret、相同 native 激活与浮点/Q24 诊断 |
| [PROTOCOL.json](PROTOCOL.json) | 公开冻结的研究合同，确认后未修改 |

总体平均净效用分别为 A 3.022192、B 2.988547、C 2.983177、DP 3.596372。C−B 在 ID/OOD 的方向相反，但仅为描述性结果；唯一确认性比较仍是预注册总体差。共同 ID 状态面板每臂 6,144 行，teacher=STOP 只有 5 行；浮点与原生 Q24/NDU 动作差异均为零，不能用本面板把结果归因于读出量化。[完整报告与解释范围](REPORT.zh.md)

## 为什么先做这个对照

[上一轮报告](../continuous_boundary_policy/REPORT.zh.md)中，普通 GRU 的总体净效用为 3.679388，native sparse 为 3.118986。但前者全量训练 464 个参数并采用策略损失，后者冻结 420 个 encoder 参数、只用 ridge 拟合 42 个 head 参数。这个比较同时改变了容量、训练程序和模型家族，不能据此把差距归因于 neuron 动力学。

本研究固定原 sparse kernel、20 维状态、top-k=4、同一 encoder、42 个读出参数和原 NDU，比较读出训练程序。

| 臂 | 训练程序 | 解释范围 |
| --- | --- | --- |
| A：ridge reference | 旧闭式 ridge Q 回归，3 个既定正则候选 | 整个训练程序的工程参考 |
| B：iterative Q-MSE | 固定 Adam 拟合 Q/8 | 主对照 |
| C：policy regret | 相同 Adam，teacher-action CE 加归一化 DP regret | 主处理 |

**唯一主比较是 C−B。** A 与 C 的差异同时包含闭式求解和迭代优化的差异，不单独解释为 loss 效果。三臂都必须从真实原生执行导出同一激活矩阵，接收同样的 margin、续行值、风险、历史活动、成本和期限信息。

## 已实现的数学与边界

读出用 20 个原生激活加常数项，输出 keep/repair 两个 affine score；STOP 的全部系数固定为零。令设计矩阵为 X，42 个可训练系数组成 W，则分数是 `(XW, 0)`。

B 的损失是两个非 STOP 分数对物理 Q/8 的均方误差。C 使用温度为 1 的 softmax，损失为 teacher-action 交叉熵，加各动作 `gap/(1+max gap)` 的概率加权平均。两者都加 `1e-4 × mean(40 个非 bias 系数的平方)`；bias 不正则化。teacher 平局按 STOP、repair、keep 依次优先。

B/C 共享精确零初始化、full-batch Adam、120 次更新、学习率候选 0.005/0.02/0.05、梯度范数上限 5 和系数绝对值上限 7.5。相同预算不表示相同 CPU 成本；驱动器分别计时。42 是可训练系数分配量，实际激活列和非零梯度覆盖另记。

原生 head 逐项计算 Q24 乘积，每项采用 signed ties-to-even 舍入，然后与 bias 相加；head 分数不做 clamp。encoder 的 clamp 与 head 算术不能混淆。`q24_scores` 实现这一算术用于诊断，不运行 sparse kernel 或 NDU。梯度只经过浮点 affine head，不穿过 Q24；这不是端到端可微原生 neuron。

`head.fit` 返回全部系数及完整训练收据。它验证形状、有限性和数值域，但**不验证输入属于训练集或由真实 native host 产生**；收据明确标记这些限制。`study`、`source` 和独立 `audit` 模块负责验证数据阶段、实际激活来源、源封存、二进制身份和 profile 链。

## 准备期数值检查与实际原生预检

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

随后重建的原生 host 使用独立的新身份，SHA-256 为 `fa9dc78b129b0ec3b072e9fc8c8fdd49479515c79aeb2660f355e38f41e54dce`，原 Rust neuron/NDU 源码未改。原生执行的 6 项行为检查通过；本研究另通过 8 项阶段保护检查、11 项独立算术与证据篡改检查。诊断 seed 991 的 16 条闭环 episode、6 条开发轨迹、48 行训练激活和 72 行共同状态面板均经独立审核。三个选定诊断头各完成一次真实进程替换和完整任务状态恢复，36 个 owner 步骤与原快路径一致。诊断轨迹没有 STOP，因此新头诊断的 STOP 探针覆盖为零。

这些检查不增加正式研究样本。原始收据保存在 `preflight/`；原生构建身份见 `native/`，共用构建和二进制行为检查见 `../continuous_boundary_policy_reproduction/preflight/`。格式化后的源码与受测版本通过 AST 身份核对，原始测试收据保持原样。

## 固定研究方案

[PROTOCOL.json](PROTOCOL.json)锁定 16 个新 seed。每 seed 12 个训练 context、8 条公共探索路径/context；8 个开发 context、8 条路径/context；确认包含各 8 个 ID/OOD context、16 条路径/context。三臂和 DP 参考合计 16,384 条确认 episode，每臂 4,096 条。训练、开发、确认使用按 phase 分开的随机流；各臂共享同一环境创新。

探索轨迹固定沿用原 `behavior_data`：每窗口 80% keep、20% repair、不采样 STOP，并运行完整期限；训练窗口等权，不按目标函数重采样。原 `target_q` 已除以 8，驱动器先乘以 8 恢复物理 Q，再追加零 STOP 后传给 `head.fit`，避免二次缩放。所有臂共享同一实际原生激活矩阵。

主统计单位是 16 个配对的训练/环境 seed；C−B 的双侧 95% t 区间下限须大于 0.005，且稳定性失败为零。只有一项主比较，不能把描述性指标另算作通过的收益门槛。不得按确认结果继续加 seed。

本次报告同时覆盖：ID/OOD 净效用；共同解析风险预测器在各策略访问分布上的 Brier/ECE；同一独立诊断状态面板上按 teacher keep/repair/stop 条件分组的物理 action regret；float 与真实 Q24/NDU 的动作差异；训练、DP/模型构造、完整运行、序列化和实际通信成本。风险校准变化不能单独解释为风险预测器变强。

量化诊断保留有符号的 `regret(Q24/NDU action) − regret(float action)`；负值表示该状态上量化反而改善动作，不能把全部 action flip 解释为损失。

三臂采用相同 native 输入接口，每步 20 个 i64，即 160 个计价数值字节，按原口径扣每 byte `1e-6`。完整 JSON 请求和响应另测；共享 setup 与子进程 CPU 不重复累计。`head.fit` 内部时钟不含最初输入验证和数组分配，正式 runner 使用包围窗口核算完整阶段。科学窗口合计 130.174260 秒 wall、130.417129 秒 CPU；包含它们的外层完整命令以及独立审计和 owner 成本另列，不把内外层相加。没有硬件能耗测量，不作节能结论。[成本数据](results/COST_SUMMARY.json)

## 执行与证据门槛

驱动器按 `freeze → initialize → train → confirm` 执行。初始化和确认均核验指定公开 commit 是命名远端研究分支的祖先，并逐字节比较封存文件。已开始或部分完成的阶段不可覆盖或重新开始；所有候选参数、原始开发轨迹、训练激活、物理 DP teacher、确认轨迹、诊断状态面板和成本均保留。

独立审计分别在开发选择后与确认结束后执行。工程验证固定使用 seed 3301、三个学习臂、ID/OOD 各 context 0/path 0，共六个已有 episode；重新建立 `FeatureMap`、物理状态、因果历史及 native owner，验证不同 PID 冷恢复后的完整后缀。它不增加收益样本，也不证明任意期限的稳定性。遇到 STOP 才运行后续独特 tick 的拒绝探针，并如实报告实际覆盖次数。

确认审计核验了 1,048 个文件、64 个选定 checkpoint、144 个候选训练程序、9,216 条开发 episode 与全部 16,384 条确认 episode。独立复核包括 Bellman、因果物理轨迹、奖励、优化器和 Q24 算术；数值网格构造器为共享封存组件，原 sparse kernel 真实执行并核验收据，没有宣称另写了第二个独立 sparse 实现。[审计范围](results/AUDIT_SUMMARY.json)

用户已于 2026-10-29 明确授权将本项目研究源码、报告、检查点和原始证据公开到 `TrillionniumFoundation/hepta-private-ci`。旧补充实验的缺失原始档案不能由结果表重建；`continuous_boundary_policy_reproduction` 使用原种子和原算法另建明确标识的新复现记录。它不增加独立样本，也不替换历史 0/4 结论。

研究保持 `DENY_ALL`，不触发生产 admission 或主线合并。

## 公开恢复与重新审计

从公开提交 [b0907a0](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b0907a0eab889b9e1f346a452b7239661a96f9e3)重新获取完整归档，**1,484 个文件、610 个目录、136,972,435 bytes** 恢复核验通过；全部 278 个下载对象均首次成功。对恢复数据重新执行的完整审计为 **547,772 bytes**，与归档原审计逐字节一致，科学结论仍为 **0/1**，新增训练和样本数为零。

- [公开下载与恢复回执](results/PUBLIC_RETRIEVAL.json)及[逐文件校验名册](results/PUBLIC_FILE_VERIFY.jsonl.gz)。
- [独立重新审计结果](results/PUBLIC_ROUNDTRIP_AUDIT.json)、[完整审计身份](results/PUBLIC_ROUNDTRIP_FILES.json)及[额外复审成本](results/PUBLIC_ROUNDTRIP_COST.json)。
- [两套完整原始包的共同公开锚点](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8dc7defc17974d67766f35f340eb7bf6e692aefb)、[复现指南](REPRODUCE.md)与[中文总交付报告](../RESEARCH_DELIVERY_2026-10-29.zh.md)。

这些回执证明本包的公开恢复与科学复核，未把有限工程结果扩张为生产资格。研究继续保持 `DENY_ALL`、draft 和未合并状态；最终 head 的仓库 CI 见 [PR #4157](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4157)与 [Actions](https://github.com/TrillionniumFoundation/hepta-private-ci/actions)。
