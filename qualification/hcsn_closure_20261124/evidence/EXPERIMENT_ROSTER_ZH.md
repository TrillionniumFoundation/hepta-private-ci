# 本轮跨包终态名册

九个已冻结 campaign 共 **177 个正式训练槽**，全部已到达 fit `completed` 和 test `evaluated` 终态；`censored_cpu=0`、fit `failed=0`。实际更新分布为 **168 槽各 512 次、AV 的 9 槽各 256 次**。这些计数表示执行完成，不表示学习门、数值门或相对质量门全部通过；此前报告的失败结论继续保留。不同条件复用种子，177 也不能解释为 177 个独立随机种子的统计重复。

| Campaign | 冻结训练槽 | completed / censored / failed | test evaluated | 每槽实际更新 | fit + test 完整子进程 CPU 秒 |
|---|---:|---:|---:|---:|---:|
| closure-v1 | 63 | 63 / 0 / 0 | 63 | 512 | 26367.673122 |
| communication-training-v1 | 21 | 21 / 0 / 0 | 21 | 512 | 11019.126310 |
| dual-training-v1 | 12 | 12 / 0 / 0 | 12 | 512 | 3730.898462 |
| fast-training-v1 | 18 | 18 / 0 / 0 | 18 | 512 | 8051.559280 |
| baselines-v1 | 27 | 27 / 0 / 0 | 27 | 512 | 417.960092 |
| joint-training-v1 | 9 | 9 / 0 / 0 | 9 | 512 | 2713.910046 |
| precision-training-v1 | 6 | 6 / 0 / 0 | 6 | 512 | 2982.278526 |
| av-closure-v4 | 9 | 9 / 0 / 0 | 9 | 256 | 1580.181895 |
| boundary-center-v1 | 12 | 12 / 0 / 0 | 12 | 512 | 3662.191673 |
| **训练槽总数** | **177** | **177 / 0 / 0** | **177** | **168×512 + 9×256** | **不拼接为全项目总成本** |

每行 CPU 只加同一 campaign 内互不重叠的 fit / test 子进程成本，包含子进程冷启动和关闭。基线使用 54 个顺序启动回执的 `RUSAGE_CHILDREN` 差，其余使用两个阶段回执的差。没有再加嵌套的 worker、body、协调器、outer 或安装成本；表中也不含预检、程序编辑、长延迟 stress、解释和证据运输。因此不能将该表冒充完整研发或端到端项目总成本。

## 必须另列的工作

- **45 个程序候选 / 方法评价：**9 个已经训练的父模型 × 5 种 head 方法，包含 KEEP 和直接编译，不是 45 个新的 backbone 训练槽。
- **15 个冷进程成本重放：**3 个已有 N8 父模型 × 5 方法，只重放冻结 train / dev 候选用于成本与一致性验证，没有新增测试集评价。
- **72 个长延迟 stress 面板：**36 个已选模型 × 2 个延迟，仅评估，不训练或重选。
- 上一轮 `hcsn_smallnet_20261124/formal-v1` 的 72 槽与 `hcsn_signed_control_20261124/signed-control-v1` 的 9 槽均不混入本轮 177。

本次只读核对冻结协议、完整 seal 名册、原 fit / test 结果、worker / launch 终态及其 SHA256，并核对测试 claim 指向相同协议和 seal；没有读取 checkpoint 张量或预测数组，没有生成数据，也没有运行模型。完整逐槽证据与费用来源在 [EXPERIMENT_ROSTER.json](EXPERIMENT_ROSTER.json)，原始绝对路径 metadata 无损保存在 [EXPERIMENT_ROSTER_METADATA.json.gz](EXPERIMENT_ROSTER_METADATA.json.gz)，回读与执行身份见 [EXPERIMENT_ROSTER_PROVENANCE.json](EXPERIMENT_ROSTER_PROVENANCE.json)。最初 metadata 适配器因旧 schema 将协议身份放在 `TEST_WORKER_CLAIM.json` 而停止的原记录也保留；修正仅涉及读取该已有字段，不是科学实验重跑。
