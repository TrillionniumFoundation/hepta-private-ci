# Signed-only 补充对照

Exact signed-message-only control added after the main 72 results became public; no confirmatory or untouched-holdout claim.

Reuse the now-public main test family for descriptive comparison, explicitly departing from the main new-holdout policy. Seal all 9 terminal training records before constructing test data. No test-driven reselection, retries, or tuning.

保留全部9个预定槽位；沿用主试验80% / +10pp / +10pp、至少2/3种子的数值门槛，仅作描述。±为3个seed的样本标准差。

| N | 准确率±SD (%) | Brier | pre-late (%) | final−pre-late (pp) | final−initial (pp) | 更新数范围 | 门槛 |
|---:|---:|---:|---:|---:|---:|---:|---|
| 8 | 91.28 ± 0.92 | 0.126 | 75.85 | 15.43 | 42.12 | 512–512 | PASS 3/3 |
| 32 | 90.62 ± 1.92 | 0.136 | 75.78 | 14.84 | 41.47 | 255–265 | PASS 3/3 |
| 64 | 91.73 ± 1.44 | 0.126 | 75.91 | 15.82 | 40.89 | 194–197 | PASS 3/3 |

配对方向为 signed-only 减去原主试验的对应seed；使用相同数据、初始化seed和CPU预算，更新次数可能不同。

| N | 主试验对照 | Δ准确率±SD (pp) |
|---:|---|---:|
| 8 | qvi_flow | -0.39 ± 1.41 |
| 8 | qvi_full | 1.24 ± 0.96 |
| 32 | qvi_flow | 23.44 ± 13.02 |
| 32 | qvi_full | 29.75 ± 13.15 |
| 64 | qvi_flow | 36.26 ± 8.55 |
| 64 | qvi_full | 39.19 ± 1.44 |

独立 NumPy 指标复核最大误差：2.22e-16。

Training intervals are included in fit-body and worker CPU; test pairs are included in test-worker CPU. Do not add nested ledgers. Energy unknown.
