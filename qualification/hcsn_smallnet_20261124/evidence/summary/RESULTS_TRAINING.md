# HCSN 独立群体训练结果

实验：`HCSN-INDEPENDENT-POPULATIONS-20261124-v1`。

冻结协议 SHA256：`c259030b227f25bc72ccbab12402fbe62747df845c9dce965e795b85b1af176d`。已评测 **72/72** 个预定训练尝试，其中 **72** 个评测的独立回执与预测文件哈希已核验。

## 判定与统计口径

每个 seed 同时满足：最终准确率 ≥ 0.800；相对该 seed 初始模型提升 ≥ 0.100；相对各样本晚信息到达前提升 ≥ 0.100。

每个 N×arm 至少 2/3 个 seed 通过才通过组门槛。缺失或失败保留在预定 seed 分母中；判定使用未舍入原始值。

表中的 ± 是训练 seed 间样本标准差，n=1 时不估计标准差；不是置信区间。性能均值仅使用已评测 seed，覆盖数另列。预测或逐项测试回执缺失时保留报告值但标记 UNVERIFIED，所在组不会判为 PASS。选中 step 0 表示开发集选择保留初始模型，不能称为学习成功。

这些数据来自模拟的互不重叠来源族。按来源与同 seed 配对的结果仅作描述，不把样本、来源和重复训练 seed 混为独立观测，不输出 p 值。

## 按宽度与对照汇总

| N | arm | 已评测 | 准确率 ± SD (%) | Brier ± SD | pre-late (%) | final−pre-late (pp) | final−initial (pp) | step0/已评测 | 学习门槛 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 8 | qvi_full | 3/3 | 90.04 ± 1.88 | 0.149 ± 0.027 | 75.78 ± 0.39 | 14.26 ± 2.20 | 40.89 ± 2.86 | 0/3 | PASS (3/3) |
| 8 | qvi_boundary | 3/3 | 52.54 ± 0.00 | 0.502 ± 0.001 | 52.54 ± 0.00 | 0.00 ± 0.00 | 3.39 ± 2.93 | 0/3 | FAIL (0/3) |
| 8 | qvi_flow | 3/3 | 91.67 ± 0.74 | 0.125 ± 0.008 | 75.91 ± 0.41 | 15.76 ± 0.49 | 42.51 ± 3.67 | 0/3 | PASS (3/3) |
| 8 | fixed_full | 3/3 | 91.28 ± 0.88 | 0.125 ± 0.005 | 75.98 ± 0.52 | 15.30 ± 0.45 | 42.12 ± 3.70 | 0/3 | PASS (3/3) |
| 8 | learned_full | 3/3 | 92.84 ± 0.30 | 0.105 ± 0.009 | 75.72 ± 0.92 | 17.12 ± 1.19 | 43.68 ± 3.00 | 0/3 | PASS (3/3) |
| 8 | qvi_tanh | 3/3 | 91.41 ± 1.37 | 0.130 ± 0.027 | 75.20 ± 1.41 | 16.21 ± 1.22 | 42.25 ± 3.67 | 0/3 | PASS (3/3) |
| 8 | qvi_value_only | 3/3 | 91.15 ± 1.08 | 0.129 ± 0.020 | 75.72 ± 0.81 | 15.43 ± 1.88 | 41.99 ± 3.52 | 0/3 | PASS (3/3) |
| 8 | qvi_risk_only | 3/3 | 88.28 ± 4.84 | 0.169 ± 0.064 | 75.46 ± 0.11 | 12.83 ± 4.76 | 39.13 ± 3.62 | 0/3 | PASS (2/3) |
| 32 | qvi_full | 3/3 | 60.87 ± 14.43 | 0.446 ± 0.085 | 60.29 ± 13.42 | 0.59 ± 1.01 | 11.72 ± 16.10 | 0/3 | FAIL (0/3) |
| 32 | qvi_boundary | 3/3 | 52.54 ± 0.00 | 0.500 ± 0.002 | 52.54 ± 0.00 | 0.00 ± 0.00 | 3.39 ± 2.93 | 0/3 | FAIL (0/3) |
| 32 | qvi_flow | 3/3 | 67.19 ± 14.36 | 0.409 ± 0.127 | 66.73 ± 12.33 | 0.46 ± 5.78 | 18.03 ± 17.01 | 0/3 | FAIL (0/3) |
| 32 | fixed_full | 3/3 | 54.10 ± 2.71 | 0.498 ± 0.006 | 56.18 ± 6.31 | -2.08 ± 3.61 | 4.95 ± 0.23 | 0/3 | FAIL (0/3) |
| 32 | learned_full | 3/3 | 53.78 ± 2.14 | 0.499 ± 0.005 | 55.79 ± 5.47 | -2.02 ± 6.77 | 4.62 ± 0.79 | 0/3 | FAIL (0/3) |
| 32 | qvi_tanh | 3/3 | 65.49 ± 22.44 | 0.379 ± 0.212 | 59.77 ± 12.52 | 5.73 ± 9.92 | 14.65 ± 21.13 | 1/3 | FAIL (1/3) |
| 32 | qvi_value_only | 3/3 | 69.53 ± 14.75 | 0.400 ± 0.085 | 67.51 ± 12.97 | 2.02 ± 2.05 | 20.38 ± 13.73 | 0/3 | FAIL (0/3) |
| 32 | qvi_risk_only | 3/3 | 52.54 ± 0.00 | 0.500 ± 0.001 | 52.54 ± 0.00 | 0.00 ± 0.00 | 1.69 ± 2.93 | 2/3 | FAIL (0/3) |
| 64 | qvi_full | 3/3 | 52.54 ± 0.00 | 0.507 ± 0.009 | 52.54 ± 0.00 | 0.00 ± 0.00 | 1.69 ± 2.93 | 1/3 | FAIL (0/3) |
| 64 | qvi_boundary | 3/3 | 52.54 ± 0.00 | 0.501 ± 0.004 | 52.54 ± 0.00 | 0.00 ± 0.00 | 1.69 ± 2.93 | 1/3 | FAIL (0/3) |
| 64 | qvi_flow | 3/3 | 55.47 ± 9.81 | 0.491 ± 0.019 | 58.07 ± 10.62 | -2.60 ± 2.26 | 4.62 ± 8.01 | 1/3 | FAIL (0/3) |
| 64 | fixed_full | 3/3 | 52.54 ± 0.00 | 0.502 ± 0.003 | 52.54 ± 0.00 | 0.00 ± 0.00 | 1.69 ± 2.93 | 1/3 | FAIL (0/3) |
| 64 | learned_full | 3/3 | 52.54 ± 0.00 | 0.502 ± 0.003 | 52.54 ± 0.00 | 0.00 ± 0.00 | 1.69 ± 2.93 | 1/3 | FAIL (0/3) |
| 64 | qvi_tanh | 3/3 | 52.54 ± 0.00 | 0.503 ± 0.006 | 52.54 ± 0.00 | 0.00 ± 0.00 | 3.39 ± 2.93 | 1/3 | FAIL (0/3) |
| 64 | qvi_value_only | 3/3 | 52.54 ± 0.00 | 0.501 ± 0.002 | 52.54 ± 0.00 | 0.00 ± 0.00 | 1.69 ± 2.93 | 1/3 | FAIL (0/3) |
| 64 | qvi_risk_only | 3/3 | 50.72 ± 2.83 | 0.501 ± 0.001 | 50.85 ± 2.93 | -0.13 ± 0.23 | 1.56 ± 2.71 | 1/3 | FAIL (0/3) |

## 同 seed 配对：qvi_full 减去对照

准确率和提升差为正有利于 full；Brier 差为负有利于 full。缺失的一侧不会被填零，配对覆盖数明确列出。

| N | 对照 | 配对 seed | Δ准确率 (pp) | ΔBrier | Δ晚信息提升 (pp) | Δ相对初始提升 (pp) |
|---:|---|---:|---:|---:|---:|---:|
| 8 | qvi_boundary | 3/3 | 37.50 ± 1.88 | -0.353 ± 0.028 | 14.26 ± 2.20 | 37.50 ± 1.88 |
| 8 | qvi_flow | 3/3 | -1.63 ± 2.33 | 0.024 ± 0.031 | -1.50 ± 2.29 | -1.63 ± 2.33 |
| 8 | fixed_full | 3/3 | -1.24 ± 2.65 | 0.024 ± 0.031 | -1.04 ± 2.65 | -1.24 ± 2.65 |
| 8 | learned_full | 3/3 | -2.80 ± 1.64 | 0.044 ± 0.018 | -2.86 ± 1.11 | -2.80 ± 1.64 |
| 8 | qvi_tanh | 3/3 | -1.37 ± 3.22 | 0.019 ± 0.053 | -1.95 ± 2.76 | -1.37 ± 6.09 |
| 8 | qvi_value_only | 3/3 | -1.11 ± 1.37 | 0.020 ± 0.015 | -1.17 ± 1.70 | -1.11 ± 1.37 |
| 8 | qvi_risk_only | 3/3 | 1.76 ± 2.96 | -0.020 ± 0.037 | 1.43 ± 2.60 | 1.76 ± 5.25 |
| 32 | qvi_boundary | 3/3 | 8.33 ± 14.43 | -0.055 ± 0.086 | 0.59 ± 1.01 | 8.33 ± 14.43 |
| 32 | qvi_flow | 3/3 | -6.32 ± 20.00 | 0.037 ± 0.156 | 0.13 ± 6.64 | -6.32 ± 20.00 |
| 32 | fixed_full | 3/3 | 6.77 ± 15.96 | -0.052 ± 0.089 | 2.67 ± 3.22 | 6.77 ± 15.96 |
| 32 | learned_full | 3/3 | 7.10 ± 15.62 | -0.053 ± 0.087 | 2.60 ± 6.58 | 7.10 ± 15.62 |
| 32 | qvi_tanh | 3/3 | -4.62 ± 8.01 | 0.067 ± 0.127 | -5.14 ± 8.91 | -2.93 ± 5.07 |
| 32 | qvi_value_only | 3/3 | -8.66 ± 13.67 | 0.045 ± 0.077 | -1.43 ± 1.26 | -8.66 ± 13.67 |
| 32 | qvi_risk_only | 3/3 | 8.33 ± 14.43 | -0.055 ± 0.086 | 0.59 ± 1.01 | 10.03 ± 17.37 |
| 64 | qvi_boundary | 3/3 | 0.00 ± 0.00 | 0.006 ± 0.010 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| 64 | qvi_flow | 3/3 | -2.93 ± 9.81 | 0.016 ± 0.028 | 2.60 ± 2.26 | -2.93 ± 9.81 |
| 64 | fixed_full | 3/3 | 0.00 ± 0.00 | 0.005 ± 0.008 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| 64 | learned_full | 3/3 | 0.00 ± 0.00 | 0.004 ± 0.007 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| 64 | qvi_tanh | 3/3 | 0.00 ± 0.00 | 0.004 ± 0.012 | 0.00 ± 0.00 | -1.69 ± 5.86 |
| 64 | qvi_value_only | 3/3 | 0.00 ± 0.00 | 0.006 ± 0.008 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| 64 | qvi_risk_only | 3/3 | 1.82 ± 2.83 | 0.006 ± 0.009 | 0.13 ± 0.23 | 0.13 ± 4.88 |

## 来源层描述

先在每个来源内平均已评测 seed，再描述来源均值的分布；完整来源×seed 数字与配对来源差在 SUMMARY.json。

| N | arm | 来源数 | 来源均值均数 (%) | 来源均值 SD (pp) | 最低来源均值 (%) | 最高来源均值 (%) |
|---:|---|---:|---:|---:|---:|---:|
| 8 | qvi_full | 8 | 90.04 | 2.50 | 87.50 | 94.27 |
| 8 | qvi_boundary | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 8 | qvi_flow | 8 | 91.67 | 2.89 | 87.50 | 96.35 |
| 8 | fixed_full | 8 | 91.28 | 2.64 | 87.50 | 94.27 |
| 8 | learned_full | 8 | 92.84 | 2.74 | 88.02 | 95.83 |
| 8 | qvi_tanh | 8 | 91.41 | 1.91 | 88.02 | 93.75 |
| 8 | qvi_value_only | 8 | 91.15 | 2.51 | 86.98 | 94.27 |
| 8 | qvi_risk_only | 8 | 88.28 | 1.74 | 85.94 | 91.15 |
| 32 | qvi_full | 8 | 60.87 | 2.22 | 57.81 | 65.10 |
| 32 | qvi_boundary | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 32 | qvi_flow | 8 | 67.19 | 3.25 | 62.50 | 71.35 |
| 32 | fixed_full | 8 | 54.10 | 4.64 | 47.92 | 64.06 |
| 32 | learned_full | 8 | 53.78 | 4.90 | 46.88 | 64.06 |
| 32 | qvi_tanh | 8 | 65.49 | 3.63 | 61.46 | 73.96 |
| 32 | qvi_value_only | 8 | 69.53 | 2.74 | 67.19 | 73.44 |
| 32 | qvi_risk_only | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 64 | qvi_full | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 64 | qvi_boundary | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 64 | qvi_flow | 8 | 55.47 | 2.31 | 51.56 | 58.85 |
| 64 | fixed_full | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 64 | learned_full | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 64 | qvi_tanh | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 64 | qvi_value_only | 8 | 52.54 | 4.57 | 46.88 | 62.50 |
| 64 | qvi_risk_only | 8 | 50.72 | 1.82 | 48.96 | 53.12 |

## 成本与数值边界

下列时间账本相互包含，不能相加成总训练成本。training CPU 包含实际尝试的 minibatch/前向/反向/更新及失败；fit-body 另含设置、开发集选择与 checkpoint；worker CPU 再含解释器与导入至回执时刻；parent wall 包含启动到退出。

| 账本 | 值 | 有回执/预定尝试 |
|---|---:|---:|
| training_cpu_seconds | 12119.362 | 72/72 |
| fit_body_cpu_seconds | 13791.103 | 72/72 |
| fit_body_wall_seconds | 13808.586 | 72/72 |
| worker_cpu_seconds | 13938.111 | 72/72 |
| worker_wall_seconds | 13951.983 | 72/72 |
| parent_launch_exit_wall_seconds | 14015.006 | 72/72 |
| training_cpu_overrun_seconds | 21.361 | 72/72 |
| test_pair_cpu_seconds | 1422.211 | 72/72 |
| test_pair_wall_seconds | 1422.829 | 72/72 |
| worker_peak_rss_bytes | 471429120 | 72/72 |
| fit_process_peak_rss_bytes | 471429120 | 72/72 |
| maximum_chunk_state_tensor_bytes | 212992 | 72/72 |
| max_probability_balance_error | 2.354e-14 | 72/72 |

| N | 并发 workers | SHARD wall (s) | children CPU 含退出 (s) | driver CPU (s) |
|---:|---:|---:|---:|---:|
| 8 | 4 | 1027.599 | 3934.361 | 0.101 |
| 32 | 4 | 1248.131 | 4958.916 | 0.101 |
| 64 | 4 | 1280.117 | 5102.705 | 0.103 |

worker/parent/SHARD wall 的合计不代表可能并发运行的整个 campaign 历时；未凭这些数值推算 makespan。RSS 是单个 worker 进程峰值的最大值，不能当同时驻留内存合计。state bytes 仅包含评测 chunk 的完整五个动态张量，不含模型、输出和 AD tape。

**能耗未知。** 没有进程可归属的硬件读数；共享 package 计数即使存在也可能重叠，不相加，也不以 CPU 秒代替焦耳。最终测试与 seal 的独立账本保留在 SUMMARY.json，未混入训练 CPU。

## 每个尝试与失败保留

| 尝试 | 训练/评测状态 | 更新数 | 选中 step | 准确率 (%) | 相对初始 (pp) | 相对 pre-late (pp) | 学习 |
|---|---|---:|---:|---:|---:|---:|---|
| n8-qvi_full-s1101 | completed/evaluated | 512 | 512 | 91.41 | 43.95 | 15.62 | PASS |
| n8-qvi_full-s2202 | completed/evaluated | 512 | 512 | 87.89 | 40.43 | 11.72 | PASS |
| n8-qvi_full-s3303 | completed/evaluated | 512 | 448 | 90.82 | 38.28 | 15.43 | PASS |
| n8-qvi_boundary-s1101 | completed/evaluated | 512 | 128 | 52.54 | 5.08 | 0.00 | FAIL |
| n8-qvi_boundary-s2202 | completed/evaluated | 512 | 256 | 52.54 | 5.08 | 0.00 | FAIL |
| n8-qvi_boundary-s3303 | completed/evaluated | 512 | 384 | 52.54 | 0.00 | 0.00 | FAIL |
| n8-qvi_flow-s1101 | completed/evaluated | 512 | 192 | 91.99 | 44.53 | 16.21 | PASS |
| n8-qvi_flow-s2202 | completed/evaluated | 512 | 512 | 92.19 | 44.73 | 15.82 | PASS |
| n8-qvi_flow-s3303 | completed/evaluated | 512 | 192 | 90.82 | 38.28 | 15.23 | PASS |
| n8-fixed_full-s1101 | completed/evaluated | 512 | 512 | 91.21 | 43.75 | 15.04 | PASS |
| n8-fixed_full-s2202 | completed/evaluated | 512 | 512 | 92.19 | 44.73 | 15.82 | PASS |
| n8-fixed_full-s3303 | completed/evaluated | 512 | 448 | 90.43 | 37.89 | 15.04 | PASS |
| n8-learned_full-s1101 | completed/evaluated | 512 | 448 | 93.16 | 45.70 | 18.16 | PASS |
| n8-learned_full-s2202 | completed/evaluated | 512 | 512 | 92.58 | 45.12 | 15.82 | PASS |
| n8-learned_full-s3303 | completed/evaluated | 512 | 448 | 92.77 | 40.23 | 17.38 | PASS |
| n8-qvi_tanh-s1101 | completed/evaluated | 512 | 448 | 90.82 | 38.28 | 17.19 | PASS |
| n8-qvi_tanh-s2202 | completed/evaluated | 512 | 512 | 92.97 | 45.51 | 16.60 | PASS |
| n8-qvi_tanh-s3303 | completed/evaluated | 512 | 448 | 90.43 | 42.97 | 14.84 | PASS |
| n8-qvi_value_only-s1101 | completed/evaluated | 512 | 384 | 92.38 | 44.92 | 17.58 | PASS |
| n8-qvi_value_only-s2202 | completed/evaluated | 512 | 384 | 90.43 | 42.97 | 14.06 | PASS |
| n8-qvi_value_only-s3303 | completed/evaluated | 512 | 448 | 90.62 | 38.09 | 14.65 | PASS |
| n8-qvi_risk_only-s1101 | completed/evaluated | 512 | 512 | 91.99 | 39.45 | 16.41 | PASS |
| n8-qvi_risk_only-s2202 | completed/evaluated | 512 | 512 | 82.81 | 35.35 | 7.42 | FAIL |
| n8-qvi_risk_only-s3303 | completed/evaluated | 512 | 448 | 90.04 | 42.58 | 14.65 | PASS |
| n32-qvi_full-s1101 | completed/evaluated | 239 | 239 | 52.54 | 0.00 | 0.00 | FAIL |
| n32-qvi_full-s2202 | completed/evaluated | 238 | 192 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-qvi_full-s3303 | completed/evaluated | 238 | 192 | 77.54 | 30.08 | 1.76 | FAIL |
| n32-qvi_boundary-s1101 | completed/evaluated | 237 | 237 | 52.54 | 0.00 | 0.00 | FAIL |
| n32-qvi_boundary-s2202 | completed/evaluated | 226 | 64 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-qvi_boundary-s3303 | completed/evaluated | 228 | 128 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-qvi_flow-s1101 | completed/evaluated | 233 | 128 | 52.54 | 0.00 | 0.00 | FAIL |
| n32-qvi_flow-s2202 | completed/evaluated | 231 | 231 | 81.25 | 33.79 | 6.45 | FAIL |
| n32-qvi_flow-s3303 | completed/evaluated | 233 | 233 | 67.77 | 20.31 | -5.08 | FAIL |
| n32-fixed_full-s1101 | completed/evaluated | 274 | 256 | 57.23 | 4.69 | -6.25 | FAIL |
| n32-fixed_full-s2202 | completed/evaluated | 277 | 192 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-fixed_full-s3303 | completed/evaluated | 276 | 128 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-learned_full-s1101 | completed/evaluated | 278 | 256 | 56.25 | 3.71 | 3.52 | FAIL |
| n32-learned_full-s2202 | completed/evaluated | 276 | 256 | 52.54 | 5.08 | -9.57 | FAIL |
| n32-learned_full-s3303 | completed/evaluated | 272 | 128 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-qvi_tanh-s1101 | completed/evaluated | 317 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n32-qvi_tanh-s2202 | completed/evaluated | 329 | 192 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-qvi_tanh-s3303 | completed/evaluated | 330 | 330 | 91.41 | 38.87 | 17.19 | PASS |
| n32-qvi_value_only-s1101 | completed/evaluated | 327 | 320 | 76.95 | 24.41 | 1.95 | FAIL |
| n32-qvi_value_only-s2202 | completed/evaluated | 322 | 192 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-qvi_value_only-s3303 | completed/evaluated | 335 | 320 | 79.10 | 31.64 | 4.10 | FAIL |
| n32-qvi_risk_only-s1101 | completed/evaluated | 263 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n32-qvi_risk_only-s2202 | completed/evaluated | 266 | 256 | 52.54 | 5.08 | 0.00 | FAIL |
| n32-qvi_risk_only-s3303 | completed/evaluated | 263 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_full-s1101 | completed/evaluated | 179 | 64 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_full-s2202 | completed/evaluated | 187 | 128 | 52.54 | 5.08 | 0.00 | FAIL |
| n64-qvi_full-s3303 | completed/evaluated | 184 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_boundary-s1101 | completed/evaluated | 182 | 182 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_boundary-s2202 | completed/evaluated | 181 | 128 | 52.54 | 5.08 | 0.00 | FAIL |
| n64-qvi_boundary-s3303 | completed/evaluated | 181 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_flow-s1101 | completed/evaluated | 178 | 178 | 66.41 | 13.87 | -3.91 | FAIL |
| n64-qvi_flow-s2202 | completed/evaluated | 180 | 128 | 47.46 | 0.00 | -3.91 | FAIL |
| n64-qvi_flow-s3303 | completed/evaluated | 183 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-fixed_full-s1101 | completed/evaluated | 205 | 64 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-fixed_full-s2202 | completed/evaluated | 209 | 192 | 52.54 | 5.08 | 0.00 | FAIL |
| n64-fixed_full-s3303 | completed/evaluated | 209 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-learned_full-s1101 | completed/evaluated | 207 | 64 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-learned_full-s2202 | completed/evaluated | 206 | 192 | 52.54 | 5.08 | 0.00 | FAIL |
| n64-learned_full-s3303 | completed/evaluated | 208 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_tanh-s1101 | completed/evaluated | 241 | 64 | 52.54 | 5.08 | 0.00 | FAIL |
| n64-qvi_tanh-s2202 | completed/evaluated | 252 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_tanh-s3303 | completed/evaluated | 253 | 64 | 52.54 | 5.08 | 0.00 | FAIL |
| n64-qvi_value_only-s1101 | completed/evaluated | 242 | 64 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_value_only-s2202 | completed/evaluated | 243 | 192 | 52.54 | 5.08 | 0.00 | FAIL |
| n64-qvi_value_only-s3303 | completed/evaluated | 245 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_risk_only-s1101 | completed/evaluated | 200 | 192 | 47.46 | 0.00 | 0.00 | FAIL |
| n64-qvi_risk_only-s2202 | completed/evaluated | 200 | 0 | 52.54 | 0.00 | 0.00 | FAIL |
| n64-qvi_risk_only-s3303 | completed/evaluated | 195 | 128 | 52.15 | 4.69 | -0.39 | FAIL |

## 中断后的执行恢复

原 finalizer `1a20dbaee10-ffbe-398e` 为 timed_out / exit 124；含封存等待的 wall 为 1811.716 秒。完整原进程 CPU 未测到，保持 unknown。

原已完成 63 个评测的 result/prediction SHA 保持一致；仅恢复缺失的 9 个槽位，没有重新训练、选模或更改评测定义。

恢复 driver CPU（至回执）5.228 秒；恢复 children CPU（含退出）313.699 秒；恢复 driver wall（含导入）106.970 秒。

原已完成测试 pair CPU 之和为 1127.591 秒；新完成测试 pair CPU 之和为 294.620 秒。这些是相应 worker CPU 的子集，不再重复相加。

FINAL_RESULTS.cost 仅是恢复 driver body 的账本，不代表全部 72 项最终测试 CPU。原 timeout、原已完成行成本和本次恢复成本分列；适配测试成本也不与包含它的原 finalizer 时间重复相加。


## 可复核性

本汇总只读已写出的回执，不导入训练代码、Torch，不读取标签重新拟合模型，不更改选择或门槛。SEAL.json 必须存在且与 FINAL_RESULTS 哈希匹配；逐项校验冻结身份、source-hash 回执、统一测试数据身份、sealed result 哈希、test_result.json 等值及 test_predictions.json SHA256。此处没有独立重算 checkpoint 或预测指标。全部输入回执 SHA256 和分析源码 SHA256 在 SUMMARY.json。
