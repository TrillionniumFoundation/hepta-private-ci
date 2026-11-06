# C2：独立有限成本审查

**本次 x64 原四-kernel采集与原 reader 通过；这不是全局最便宜合法工作、全部无效输入最坏成本或公开服务活性的证明。** C2 的 checks 仍因原 applicability 300 秒超时保持失败。

固定源码：`03521b2f32346a49cccde8ff72e8c7b886b31222`；tree `e0235248ecae2a67717c8b9ff2e3f25774ba63d7`。原采集保留的 ELF SHA256：`39a2d4f3e2cc62b799a8871846d3303537b67badc67f662dd5dadd9601e7b959`。所有数据来自已有 96 个 cohort、1,152 次计时验算与 96 个获胜完整 transcript 的独立读回；本审查没有新增运行、补采样或重建 ELF。

原 `/proc/cpuinfo` 记录：Intel(R) Xeon(R) CPU E5-2673 v3 @ 2.40GHz；观测起点 `2026-11-05T16:15:32.371009+00:00`。原 build 用时 30.659450293 秒（上限900秒），native用时 8.098942845 秒（上限180秒），原独立reader用时 19.531434002 秒且exit0；工具身份30秒上限及终止grace均未改变。[原采集manifest](C2-native-receipts/four-kernel-rejection/manifest.json)、[原reader记录](C2-native-receipts/collector/manifest.json)。

## 统计口径

每个矩阵类型 × target × kernel × variant 只有 12 个配对样本。中位数取中间两项的平均；p95 使用 nearest-rank `ceil(0.95*n)`，所以这里 p95 就是这 12 项中的最大值。它不估计总体尾延迟，也不提供置信保证。所有耗时都是 monotonic wall time，不是 CPU、能耗或网络服务延迟。

表中时间为 **中位数 / 样本 p95，单位 μs**；拒绝/合法比率为同一组配对案例的 `sum(拒绝耗时) / sum(合法耗时)`，不是中位数之比。完整 JSON 还保留每个配对比率的中位数与 p95、精确分子/分母、各 kernel 相对生产 FullLimb 的比率；CSV 共 96 行可直接复算。

## 本次样本直接支持的结论

生产 FullLimb 的8个分组，合法验算中位数为 **1.666793–1.697455 ms**，Transcript晚拒绝为 **1.500383–1.521604 ms**，Product最后一格拒绝为 **1.670701–1.707710 ms**。对应各分组样本p95的最大值分别是 **2.197303、2.479376、2.958098 ms**。数值是有限样本描述，不是服务deadline或最坏上界。

按每格中位数，全部32个 class/target/kernel 组合中，较便宜的已测invalid都是Transcript，较昂贵的都是Product最后一格。生产 FullLimb 的 `sum(Product)/sum(Transcript)` 为 **1.09845–1.15421**；所有kernel该比率范围为 **1.09485–1.19404**。Product与合法验算已经很接近，生产kernel的 `sum(Product)/sum(Legal)` 为 **0.97335–1.05722**。

同一批证明的合法验算总时间：scalar-reference约为生产 FullLimb 的 **2.04955–2.17506倍**，retained-transposed为 **1.08197–1.23284倍**，limb-transcript为 **0.98453–1.01995倍**。这支持当前x64输入上的验算比较，不证明哪个合法生产算法最便宜，也不把小差异当成稳定跨硬件排名。

## 四个 kernel 的验算成本

`legal` 返回 Accepted；`transcript` 在 transcript 重放后、进入 product correction 前返回 Transcript；`product-last-cell` 执行 product correction 到最后一格后返回 Product。这只比较两种明确的晚拒绝策略。

### dense

| Target | Kernel | Legal μs | Transcript μs | Transcript / Legal | Product μs | Product / Legal |
|---|---|---:|---:|---:|---:|---:|
| 7f… | retained-transposed | 1872.123 / 2357.170 | 1691.959 / 1906.070 | 0.8943 | 1861.206 / 2103.933 | 0.9830 |
| 7f… | scalar-reference | 3606.955 / 4480.782 | 3063.382 / 3432.597 | 0.8396 | 3629.613 / 4090.785 | 0.9881 |
| 7f… | limb-transcript | 1698.047 / 1985.598 | 1530.970 / 1703.882 | 0.8909 | 1707.722 / 1914.837 | 1.0003 |
| 7f… | production-full-limb | 1697.455 / 1905.981 | 1520.880 / 1698.514 | 0.8978 | 1703.447 / 1877.962 | 0.9997 |
| 07… | retained-transposed | 1862.550 / 3552.286 | 1682.691 / 1724.600 | 0.8069 | 1848.610 / 1886.980 | 0.8835 |
| 07… | scalar-reference | 3607.892 / 4110.972 | 3041.064 / 3620.885 | 0.8441 | 3619.035 / 4028.052 | 0.9984 |
| 07… | limb-transcript | 1684.694 / 1808.612 | 1500.914 / 2021.203 | 0.9113 | 1690.818 / 3078.552 | 1.0612 |
| 07… | production-full-limb | 1692.582 / 1764.600 | 1505.180 / 2479.376 | 0.9606 | 1690.953 / 2958.098 | 1.0572 |

### zero

| Target | Kernel | Legal μs | Transcript μs | Transcript / Legal | Product μs | Product / Legal |
|---|---|---:|---:|---:|---:|---:|
| 7f… | retained-transposed | 1863.069 / 1916.913 | 1685.422 / 1757.728 | 0.9064 | 1864.447 / 1923.368 | 1.0011 |
| 7f… | scalar-reference | 3528.919 / 3575.895 | 3050.624 / 3194.208 | 0.8694 | 3529.251 / 3647.813 | 1.0017 |
| 7f… | limb-transcript | 1681.237 / 1752.701 | 1518.162 / 1541.877 | 0.8930 | 1707.697 / 1737.904 | 1.0100 |
| 7f… | production-full-limb | 1675.174 / 2197.303 | 1509.594 / 1577.934 | 0.8824 | 1680.256 / 1735.412 | 0.9734 |
| 07… | retained-transposed | 1858.251 / 3350.813 | 1666.981 / 1728.171 | 0.8338 | 1863.572 / 1940.704 | 0.9356 |
| 07… | scalar-reference | 3537.669 / 4379.679 | 3045.811 / 3123.716 | 0.8508 | 3545.990 / 3638.082 | 0.9818 |
| 07… | limb-transcript | 1691.463 / 1773.991 | 1499.066 / 1541.400 | 0.8823 | 1696.767 / 2820.783 | 1.0476 |
| 07… | production-full-limb | 1666.793 / 1719.251 | 1514.686 / 1619.329 | 0.9145 | 1672.624 / 2940.481 | 1.0556 |

### rank-one

| Target | Kernel | Legal μs | Transcript μs | Transcript / Legal | Product μs | Product / Legal |
|---|---|---:|---:|---:|---:|---:|
| 7f… | retained-transposed | 1878.979 / 1929.645 | 1682.716 / 1741.007 | 0.8980 | 1876.824 / 1928.005 | 1.0020 |
| 7f… | scalar-reference | 3647.123 / 3706.530 | 3057.978 / 3109.404 | 0.8404 | 3630.311 / 3716.084 | 0.9972 |
| 7f… | limb-transcript | 1709.665 / 1738.508 | 1518.577 / 1585.460 | 0.8895 | 1709.521 / 1756.102 | 0.9964 |
| 7f… | production-full-limb | 1679.446 / 1718.704 | 1500.383 / 1570.100 | 0.9006 | 1707.709 / 1753.340 | 1.0182 |
| 07… | retained-transposed | 1858.051 / 1924.089 | 1699.542 / 1725.433 | 0.9096 | 1872.909 / 1915.898 | 1.0108 |
| 07… | scalar-reference | 3625.941 / 3725.475 | 3071.396 / 3188.150 | 0.8511 | 3655.258 / 3795.355 | 1.0131 |
| 07… | limb-transcript | 1688.613 / 1730.173 | 1510.322 / 1576.813 | 0.8922 | 1688.082 / 1740.601 | 0.9960 |
| 07… | production-full-limb | 1668.947 / 1709.727 | 1521.604 / 1578.812 | 0.9137 | 1670.700 / 1735.158 | 1.0037 |

### sparse

| Target | Kernel | Legal μs | Transcript μs | Transcript / Legal | Product μs | Product / Legal |
|---|---|---:|---:|---:|---:|---:|
| 7f… | retained-transposed | 1861.434 / 1920.415 | 1674.934 / 1691.716 | 0.8972 | 1869.746 / 1909.838 | 1.0012 |
| 7f… | scalar-reference | 3613.926 / 3742.854 | 3040.023 / 3098.570 | 0.8419 | 3618.269 / 3664.361 | 1.0000 |
| 7f… | limb-transcript | 1697.119 / 1734.714 | 1515.970 / 1537.541 | 0.8928 | 1690.739 / 1726.293 | 1.0012 |
| 7f… | production-full-limb | 1675.182 / 1712.023 | 1509.053 / 1586.726 | 0.9041 | 1678.387 / 1705.330 | 1.0020 |
| 07… | retained-transposed | 1857.102 / 2086.663 | 1672.329 / 1729.090 | 0.8856 | 1857.585 / 1902.007 | 0.9844 |
| 07… | scalar-reference | 3604.622 / 3776.886 | 3048.299 / 3106.809 | 0.8420 | 3637.716 / 3804.282 | 1.0054 |
| 07… | limb-transcript | 1695.706 / 1749.660 | 1512.054 / 1560.234 | 0.8914 | 1695.448 / 1764.572 | 0.9983 |
| 07… | production-full-limb | 1676.778 / 1720.469 | 1501.586 / 1564.094 | 0.8989 | 1677.826 / 1774.422 | 1.0011 |

## 合法生产、预处理与实际循环

本 collector **测到了一个合法生产实现**：每个 flow 生成材料、绑定 task、调用一次 `PreparedTask::new`，再用同一个 prepared task 搜索 nonce。它不是四个合法生产算法的比赛；四个 kernel 只是验算同一个完成证明。搜索总 wall 包括所有失败与成功尝试、挑战生成、证明构造、ticket 计算以及记录开销。

下表的每栏独立计算分位数，因此不能把各栏中位数相加当作总中位数；acquisition 是逐 flow 先加 setup + search wall，再求分位数。单位仍为 μs。

| Class | Target | Setup median/p95 | Reusable preprocessing median/p95 | Search wall median/p95 | Acquisition median/p95 | Attempts min / median / max |
|---|---|---:|---:|---:|---:|---:|
| dense | 7f… | 582.958 / 831.793 | 370.627 / 499.898 | 2697.594 / 14693.219 | 3402.332 / 15281.453 | 1 / 1.5 / 9 |
| dense | 07… | 587.777 / 1025.039 | 375.346 / 703.901 | 50488.134 / 175089.891 | 51093.985 / 175667.255 | 6 / 29.5 / 100 |
| zero | 7f… | 595.668 / 621.780 | 368.705 / 393.480 | 3290.032 / 8169.265 | 3874.776 / 8771.034 | 1 / 2 / 5 |
| zero | 07… | 596.246 / 723.650 | 364.274 / 428.601 | 14646.138 / 89720.674 | 15241.987 / 90444.324 | 4 / 9 / 53 |
| rank-one | 7f… | 610.085 / 631.279 | 374.542 / 399.320 | 2462.974 / 11566.398 | 3089.936 / 12189.911 | 1 / 1.5 / 7 |
| rank-one | 07… | 587.510 / 637.245 | 365.337 / 388.322 | 41658.987 / 86751.032 | 42246.497 / 87318.972 | 6 / 25.5 / 53 |
| sparse | 7f… | 614.722 / 636.564 | 373.801 / 389.214 | 2449.907 / 9795.729 | 3073.140 / 10416.183 | 1 / 1.5 / 6 |
| sparse | 07… | 610.668 / 652.777 | 370.964 / 395.124 | 34209.766 / 121379.374 | 34841.518 / 121962.468 | 1 / 21 / 75 |

96个flow实际共 **1434 次合法proof尝试**，含 **1338 次未通过ticket的尝试 + 96个winner**；单flow实际1–100次，4096上限未到达。伪trace另执行 **1731 次fake ticket尝试**，Product变造没有新ticket循环。不同class/target的acquisition中位数伴随不同的实际获胜nonce数，不能将例如强target下zero的较小总额归因成更便宜的矩阵算法。

JSON 另分列 material、task binding、全部 proof construction、获胜 proof construction、失败 proof construction 总量、challenge、ticket、诊断记录开销及实际尝试次数；这些是已实现程序在这批输入上的成本点。程序开销使它们不能直接充当算法固有下界。

## 变造成本与攻击成本边界

两种 invalid 都先克隆一个已经取得的完整合法 winner。Transcript 再搜索一个通过 target 的伪 trace ticket；Product 只改最后一个 canonical field cell，并沿用真实 winner 的 ticket。以下比率以生产 FullLimb 的拒绝耗时为分子；两个分母必须分开理解。

| Class | Target | Invalid strategy | Existing-winner mutation median/p95 μs | Fake ticket trials min/median/max | Reject / mutation total | Reject / (honest acquisition + mutation) total |
|---|---|---|---:|---:|---:|---:|
| dense | 7f… | transcript | 5.444 / 41.434 | 1 / 1 / 5 | 159.808 | 0.315163 |
| dense | 7f… | product-last-cell | 3.370 / 44.515 | 0 / 0 / 0 | 236.503 | 0.351129 |
| dense | 07… | transcript | 63.842 / 146.350 | 8 / 38 / 84 | 22.040 | 0.023628 |
| dense | 07… | product-last-cell | 25.035 / 50.293 | 0 / 0 / 0 | 67.792 | 0.026023 |
| zero | 7f… | transcript | 5.825 / 10.559 | 1 / 1.5 / 4 | 221.281 | 0.342546 |
| zero | 7f… | product-last-cell | 18.900 / 40.749 | 0 / 0 / 0 | 79.334 | 0.376655 |
| zero | 07… | transcript | 26.962 / 142.444 | 2 / 14 / 80 | 31.351 | 0.054680 |
| zero | 07… | product-last-cell | 23.783 / 52.344 | 0 / 0 / 0 | 68.431 | 0.063164 |
| rank-one | 7f… | transcript | 6.626 / 16.087 | 1 / 2 / 5 | 170.402 | 0.349719 |
| rank-one | 7f… | product-last-cell | 18.410 / 27.933 | 0 / 0 / 0 | 88.078 | 0.394436 |
| rank-one | 07… | transcript | 40.397 / 111.090 | 3 / 22.5 / 65 | 28.252 | 0.037473 |
| rank-one | 07… | product-last-cell | 29.822 / 43.738 | 0 / 0 / 0 | 56.634 | 0.041187 |
| sparse | 7f… | transcript | 5.663 / 12.242 | 1 / 1 / 5 | 224.564 | 0.312981 |
| sparse | 7f… | product-last-cell | 20.729 / 43.554 | 0 / 0 / 0 | 68.905 | 0.345630 |
| sparse | 07… | transcript | 44.357 / 211.290 | 2 / 23.5 / 128 | 23.658 | 0.032045 |
| sparse | 07… | product-last-cell | 30.837 / 54.320 | 0 / 0 / 0 | 51.245 | 0.035711 |

生产 FullLimb 的 `reject / existing-winner mutation` 总时间比：Transcript为 **22.03975–224.56429**，Product为 **51.24473–236.50316**。若把本次真实合法acquisition加进分母，则分别只有 **0.023628–0.349719** 和 **0.026023–0.394436**；改变分母会显著改变结论，所以必须保留两个场景。

已有 winner 的增量变造成本，不是从零构造无效请求的最低成本；把合法 acquisition 加回去，也不是攻击者必须支付的下界。攻击者可以尝试无需真实完整乘法证明的构造、算法捷径、专用硬件或跨请求复用。本次没有测到这些策略的最便宜成本。两种晚拒绝也没有覆盖 malformed 输入、签名/PQ 授权、解析、队列、存储、网络或整节点的全部路径。

## 摊销与复用

本次跨已接受证明的 horizon 是 H=1：每个 cohort 都重新 new PreparedTask 并收取全部 setup。实际 nonce 搜索内部会复用这一 prepared task，具体复用次数已经记录在 attempts，未重复收取 setup。四个 verifier 共用同一个证明，不能把生产成本除以 4 或把 12 个 arms 算成 12 个独立 producer 样本。

若另行研究同一个合法可复用 task 的 H 个已接受证明，模型可写成 `(S + Σ T_i) / H`；需要固定其合法复用条件、实际 horizon、持有成本和每次搜索。这里没有 H>1 的新测量，也没有套用旧 H=8/64 的历史成本。

## 仍未关闭的门禁

原公开服务门禁仍是独立要求：0.25 CPU、2 GiB、swap0、PIDs256、16 hostile、7 honest、depth6、4秒压力窗口，独立客户端2秒调用deadline与原public request最大30秒保持不变。本机 `--local` 采集没有执行这项 hosted-only 入口。

本审查于 **2026-11-05 16:34:53 UTC** 独立读取GitHub API：[原baseline 42051619772](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/42051619772) 与 [原W1 42051619900](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/42051619900) 均为 `queued / conclusion=null`，head均为C2，尚无可接受的原公开服务结果；不是通过，也未声称其已有Host-parent失败。4105历史、真实WAN、多独立管理方及长期运行也不在这96/1152样本中。[原状态记录](C2-hosted-gate-status.json)。

C2 原 Rust 三控制、严格 Clippy、fmt 及 CI contract 100 控制已真实通过，但 applicability 整套在原 300 秒停止，不能把它写成通过。此报告保留该失败，只审阅已完成成本证据。

## 可复算文件

- `C2-independent-cost-review.json`：精确分子/分母、每组分位数、实际生产/变造阶段和限定条件。
- `C2-verifier-costs.csv`：96 组 class/target/kernel/variant 完整表。
- `C2-native-receipts/four-kernel-rejection/`：原 manifest、native.stdout、summary、原 build/native 回执与保留 ELF；全部哈希见导出根 SHA256SUMS。
- `C2-native-receipts/collector/`：原 collector 与 reader 的 stdout/stderr、前后source guard及phase manifest。
- `C2-native-raw-verification.json`：真实字节导出、原 reader exit0、来源及本地完整性复核。
