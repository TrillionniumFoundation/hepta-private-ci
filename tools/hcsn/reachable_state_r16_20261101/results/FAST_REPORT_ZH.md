# R16：保持相同投影语义的快速实现

## 结论

新的矢量化实现减少了原分组压缩的工程开销。在预先冻结的 namespace 18
确认中，512 个新世界的旧／新压缩执行具有相同的查询动作、答案、费用和奖励。
新实现的在线 owner CPU 为旧实现的 **35.36%（IID）／35.95%（OOD）**。
然而，它仍需要完整分布 D 的 **1.571／1.555 倍**在线 CPU。因此，旧实现的
重复验证与逐组循环开销得到实质改善，压缩相对完整分布的净成本优势仍未通过。

本实验没有改变原主实验的 `D-B` 失败结论，也没有产生 HX 独占收益证据。
原 `compression.py`、原主实验代码、原始数据和原先 4–7 倍成本结果全部保留。

## 实现与冻结

`fast_compression.py` 使用一次输入边界校验、分组求和和索引 gather，代替原
encode/decode 路径的重复校验与 Python 逐组循环。group 定义、数学投影、
float64 精度、支持保持要求和 READ/REFRESH 当前似然合同均保持不变。对正支持
下溢仍显式抛出 `ProjectionPrecisionError`；没有加入 epsilon 或不校验的公开路径。
传播与规划仍 lift 到 40 个状态，没有实现降维传播。

新源码、协议及 `FAST_SOURCE_FREEZE.json` 在打开新确认之前发布并读回匹配：

```text
4a74cc79584da5302aa8d0bfcd7d01aa66ba0cd7
```

原主实验 source/model manifest 仍逐项校验。没有重新拟合模型、选择策略或改变
owner、转移矩阵、观察噪声及价格。

## 旧档工程回放

完整回放原 128 个档案中的 221,184 个地址 belief，对 block2、block4、block5
进行 663,552 组旧／新投影比较。最大差异为 `5.55e-17`，当前发射似然最大差异
为 `1.22e-15`。全部 6,144 个原 block2 首动作与 3,984 个 STOP 答案一致；
18 组非法输入／下溢拒绝比较一致。

五次串行微基准的 fast/old 中位 CPU 比：

| 投影 | batch 1 | batch 32 |
| --- | ---: | ---: |
| block2 | 0.2315 | 0.2895 |
| block4 | 0.1920 | 0.2666 |
| block5 | 0.1608 | 0.1829 |

这些数值是对旧状态的工程回放，不是新科学确认，也不是完整 owner 的时延。
完整记录见 [FAST_ENGINEERING_REPLAY_01.json](FAST_ENGINEERING_REPLAY_01.json)。

## 新世界的完整 owner 比较

固定 8 个原 fit，每 fit／域 32 个新世界，合计 512 个；独立统计单位仍为 fit。
同一世界执行 `D_full`、`old_block2`、`fast_block2`，每个世界的臂顺序固定随机化。
全部 16 个 worker、64 个原始档案完成，没有失败。每臂保存完整查询轨迹、6 个
因果 checkpoint 与 owner 世界路径。去除 `checkpoint_sha256` 摘要字符串后，
旧／新分组投影的全部查询字段相同；checkpoint belief 在注册的 `2e-11` 容差内相同。

| 成本比较：fast / 对照 | IID | OOD |
| --- | ---: | ---: |
| 在线 owner CPU / old block2 | 0.353609 | 0.359490 |
| 冷准备＋checkpoint＋1,000 次使用 CPU / old block2 | 0.367673 | 0.372532 |
| 在线 owner CPU / full D | 1.571268 | 1.555032 |
| 冷准备＋checkpoint＋1,000 次使用 CPU / full D | 1.564578 | 1.545647 |

此处 1,000 次使用估计针对本轮冷模型恢复和实际 owner／checkpoint 工作。
历史 R15 训练、模拟世界产生及证据归档没有混入逐臂部署估计；它们保留在单独
来源记录与整进程成本中。该估计不表示能耗、网络成本或生产吞吐率。

相对完整 D 的四个原注册质量非劣界（四重 Bonferroni，margin `-0.01`）均通过：

| fast − full D | IID 均值 | IID 同时下界 | OOD 均值 | OOD 同时下界 |
| --- | ---: | ---: | ---: | ---: |
| 合成任务净收益 | +0.00002637 | −0.00018816 | +0.00034609 | −0.00112287 |
| 正确率 | 0 | 0 | +0.00065104 | −0.00119873 |

这支持本次有限样本上的注册非劣判断，不证明正向质量增益。相对 old 的两个域
工程速度门通过；相对 full D 的完整状态收益门都失败。

## 整进程测量与复现

外部 `RUSAGE_CHILDREN` 监督记录完整子进程，包含解释器启动、import、所有 worker
及归档：user CPU `60.639126 s`，system CPU `3.474569 s`，合计
**64.113695 s**；wall `121.463214 s`；峰值 RSS `93,272 KiB`。这些是该主机
上的测量，不是能耗。函数体内部计时为 `59.185617 s`，两者不可相加。

结果、原始数据索引和发布记录位于 [fast_run_01](../fast_run_01/SUMMARY.json)。
整进程收据见 [FAST_PROCESS_RECEIPT.json](FAST_PROCESS_RECEIPT.json)。

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m tools.hcsn.reachable_state_r16_20261101.fast_checks --output NEW_ENGINEERING_REPORT.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m tools.hcsn.reachable_state_r16_20261101.fast_campaign --freeze-commit 4a74cc79584da5302aa8d0bfcd7d01aa66ba0cd7 --output NEW_FAST_RUN_DIRECTORY
```

相同 namespace 的重跑只是复现；不能累计为额外独立确认样本。
