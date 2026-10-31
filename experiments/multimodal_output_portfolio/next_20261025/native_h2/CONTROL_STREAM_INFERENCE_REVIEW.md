# 独立复核：固定执行流与 writer bootstrap 的解释边界

复核者：`control_next`。本次仅阅读已执行源码，没有重新运行模型、owner 或实验，没有修改协议、CI 数值和门槛。

## 确认的状态生命周期

`run_v2.py` 在 `case` 循环外为每个 policy 创建一个 owner，并在所有 128 pairs × 2 views 完成后才关闭。中途的两种恢复使用同一个 state 目录并执行 `resume`，没有在 writer 或 episode 边界重新 bootstrap。每个生成 episode 的 Python 生成状态会重新 `initialize`；这不等于重置原生 owner。

`episodes.rs` 只管理 seen/pending/continuation 与 H2→H1 的因果绑定，完成 episode 不会清除神经元状态。`online_bootstrap.rs` 只在 `new` 建立零 prior；恢复继续原 journal、anchor 与所选 NDU projection。`online.rs` 在每个 candidate 上提交 `owner.tick`，实际公共观察到达后 append/select 新 projection 并更新 `history.modulator`。

保留的 `AgentdNeuronOwner` 源码只是 runtime 与 inference-control port 的组合和调用 adapter，本研究路径没有另行组合一个独立的 metabolism 组件。底层 `sparse.rs` 明确从 `previous` 读取 temporal、activation、activity、threshold 和 eligibility。`runtime_types::calibrate` 除当前 prediction error 外还检查 active fraction、projection count 和有效 sequence 范围，runtime 另检查实际资源上限。因此实现确实保留跨 episode 的状态与流位置，不能假定每个 writer 都执行在独立重置的策略实例上。

## 数值影响不能扩大解释

这套 adapter 的 `online_port.rs` 将 drive 固定为 `[Q24, 0, …, 0]`。当前 correctness 概率与五个 NDU moments 只由当前 103D 公共输入和冻结参数计算；instantaneous prediction error 是当前 drive 与 prediction 的最大绝对差。utility-derived modulator 在已审查路径中参与 projection、请求/状态身份和日志绑定，没有发现它的数值进入 value/correctness head 或在线参数更新的调用路径。记录的 `training_steps` 为零。

所以，状态持续存在这一事实不能单独证明上一 writer 的公共 utility 已改变下一 writer 的条件 Q 值；它也不能证明本次实际 admission 一定受到历史状态影响。若仅从现有日志复核 admission 是否等于公共概率门，那是对本次已实现流的描述，仍不是对其他顺序、其他流或反事实重置的实验。

## 应保留的统计表述

原 64-writer bootstrap 的全部点估计、区间和门槛保持不变，但应标为**条件于本次固定、已实现 ordered stream 的 nominal writer-bootstrap 区间**。它不是 64 次相互独立的、重新初始化完整策略运行所产生的区间，也没有重新模拟 resampling 后的神经元状态轨迹。该限定同样适用于依赖固定执行顺序和 host 情况的成本比较。

本记录不更改原负结果，不增加新实验，也不把实现层状态连续性当成已识别的策略因果收益。
