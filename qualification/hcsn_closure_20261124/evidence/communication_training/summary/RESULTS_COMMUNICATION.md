# 通信机制独立对照

7 个预先指定臂 × 3 seeds，均为 N32、QVI + value/risk、uniformized mixed。前三个 unsigned 对照均禁用 boundary 消息；后三个 boundary-only 对照只改变 input-drive 的因果缓存。

| Arm | Final accuracy mean ± SD | Brier | Pre-late | Final − pre-late | 512-step passes | Gate |
|---|---:|---:|---:|---:|---:|---|
| boundary_accumulate | 50.293% ± 0.000% | 0.510 | 50.293% | 0.000% | 0/3 | FAIL |
| boundary_hold | 65.169% ± 25.767% | 0.367 | 58.464% | 6.706% | 1/3 | FAIL |
| boundary_raw | 50.293% ± 0.000% | 0.510 | 50.293% | 0.000% | 0/3 | FAIL |
| signed_only | 91.960% ± 0.665% | 0.117 | 75.944% | 16.016% | 3/3 | PASS |
| unsigned_signed_centered | 93.717% ± 0.589% | 0.090 | 75.358% | 18.359% | 3/3 | PASS |
| unsigned_signed_centered_bounded | 93.490% ± 0.343% | 0.096 | 75.488% | 18.001% | 3/3 | PASS |
| unsigned_signed_raw | 86.751% ± 9.342% | 0.198 | 75.618% | 11.133% | 2/3 | PASS |

门槛逐 seed 同时要求 final≥0.8、比 initial 增益≥0.1、比 pre-late 增益≥0.1，并满足原数值门与完整512更新；至少2/3 seeds通过。失败/缺失不从分母删除。初始step0也属于开发集选择候选，180 CPU前缀独立保留且不按test选择。

## 预设配对差值

| Left − right | Accuracy difference mean ± SD | Brier difference |
|---|---:|---:|
| unsigned_signed_raw − signed_only | -5.208% ± 9.589% | 0.082 |
| unsigned_signed_centered − unsigned_signed_raw | 6.966% ± 9.276% | -0.108 |
| unsigned_signed_centered_bounded − unsigned_signed_centered | -0.228% ± 0.572% | 0.006 |
| boundary_accumulate − boundary_raw | 0.000% ± 0.000% | 0.000 |
| boundary_hold − boundary_raw | 14.876% ± 25.767% | -0.142 |

差值按相同seed配对，仅为描述统计。完整每source、cue奇偶、初态分组和逐通道均值/RMS、tanh饱和、preclip梯度记录保留在JSON及原始档案。中心化参考来自不读数据的名义stationary law，不能把它称为实测零均值。

## 费用与边界

尝试更新CPU合计 8372.031 秒；fit body CPU 9352.639 秒；全部fit/test worker到回执的CPU 10988.885 秒。这些是嵌套口径，不相加。阶段回执另含进程shutdown；峰RSS为单进程最大值。能量未测。

所有21训练终态与checkpoint先全局seal，之后才构造15000–15015测试source。测试数据和三份模型的全prefix概率指标以独立NumPy重算，不重新执行模型。新增source仍来自相同模拟器，不等于独立真实模态。Hold增加显式观测记忆，unsigned增加活跃参数；本实验没有把这些容量变化伪装成完全等容量。
