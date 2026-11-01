# R17 四阶段推进：新增资格与剩余阻塞

本轮完成四个独立研究候选及远端证据交付。**有限传播梯度、受限冷进程挂起恢复和多缺测处理获得新增通过证据；核心独立收益与采用成本门仍未通过。全部 blocker 尚未闭合，生产激活保持 false。**

主基线为 R16 `0fd894118c47f38c2acf2532b8242fd16df76c47`；内容前序为 `4c3244cf2061ee9bba4c776315ab7360558d902e`。执行前核对的 53 项继承来源身份全部匹配，见 `BASELINE_READBACK.json`。四项候选均保留其自身模型、协议与适用范围，没有将独立研究结果当作同一生产组合的资格。

| 阶段 | 本轮实际完成 | 仍未闭合 |
|---|---|---|
| 算子与传播 | 单独命名的 48 坐标有限法扩展；2,016 参数检查、288 多步前缀检查、10 拒绝契约通过。另有独立连续 GBM 停止问题的验证论证与 12 次 obstacle 网格求解。 | 完整有限期限 He–Xiong／神经任务自由边界、全参数域与所有分支梯度、生产实现资格。 |
| 连续动态任务 | 更正完整依赖冻结后，76/76 次真实 SIGKILL 恢复；164 冷解释器从空缓存重建；完整状态、费用与效果记录匹配不中断执行，后者匹配旧 R16。 | 一个 fit、两个有限世界之外的资格；生产 Rust、并发 fencing、外部有状态 RPC、断电／重启；核心收益。 |
| 内容任务 | 两／三个任意 token 缺测；已知有放回／不放回法下 288 新世界无目标支持丢失。实际 indexed READ、重试收据及给定别名查询映射完成。独立精确参照 5,226 检查。 | 任意未知生成器、残余不确定性回答可靠性、学习语义寻址、开放域长距离跨模态绑定与核心独立贡献。 |
| 全模态采用 | 精确对称路径完成 384 对／768 次执行，动作、答案、token、目标、费用与效用零差异；192 算子比较通过。 | 含分配准备的执行 CPU 比为 0.955852–1.007202，没有一组达到原 ≤0.90 门。全生命周期质量／时延／吞吐／能耗、GPU 和生产所有权仍开放。 |

## 逐项源码和证据

| 候选 | 固定交付提交 | 审阅入口 |
|---|---|---|
| 冷进程／挂起动作恢复 | `bf776c32f8d3be915fa0d83f550d4c9abff73926` | [PR #4566](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4566)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bf776c32f8d3be915fa0d83f550d4c9abff73926/tools/hcsn/cold_recovery_r17_20261101/REPORT_ZH.md) |
| 多缺测／生成器失配 | `b3c782f7bced4f975884c788a3a2e7f436515bb4` | [PR #4568](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4568)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b3c782f7bced4f975884c788a3a2e7f436515bb4/experiments/hcsn_multi_missing_r17_20261101/REPORT_ZH.md) |
| 有限全坐标梯度／连续停止参照 | `5760c2d268e3ec09c599c40a57d793edc8bc5390` | [PR #4569](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4569)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5760c2d268e3ec09c599c40a57d793edc8bc5390/tools/hcsn/parameter_flow_r17_20261101/REPORT_ZH.md) |
| 精确内容对称实现 | `cb405b0d08a6d87589294552fd292b02306135b5` | [PR #4570](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4570)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb405b0d08a6d87589294552fd292b02306135b5/tools/hcsn/symmetric_fastpath_r17_20261101/REPORT_ZH.md) |

远端四个 scoped tree 的 **270 个文件** Git blob 身份全部与本地最终字节对应的身份匹配，见 `REMOTE_READBACK.json`。大原始 JSON 使用确定性 gzip；恢复原始 SQLite／日志以 19 个切片保留，附完整重组哈希。所有发布文件低于 512,000 B。旧失败、异常退出及成本均保留。

## 科学解释与失败

在当前有限模型中，同 Q、prior、emission、公共干预、费用与控制规则的普通 HMM 和 HX 必须给出同一过滤及决策规律，证明见 `EQUIVALENCE.md`。结构先验、有限数据拟合和连续表示仍是可检验问题；有限同矩阵实现不能建立 HX 独占能力。前序 D−B 的注册门和未通过状态保持不变，本轮没有重新训练来替代该结论。

多缺测实验中，错误固定“不放回”先验在有放回数据上 **71/144** 次失效；其全体质量为 null，另有 16 次有效记录丢掉真实目标支持。受限两生成器策略接受 **891/1,152** 个查询、拒答 **261** 个，接受答案全部是后验点质量 1；零接受错误不证明对不确定答案或任意未知生成器的可靠性。实际选择性收益另有明确费用账，原全回答诊断不充作执行收益。

恢复测试中，首轮来源清单遗漏的传递依赖已补齐并完整重跑；两轮子进程 CPU 共 **123.091589 s**。最终有效 run02 为 **59.976592 s**，包含被杀进程；父进程参照和开发／审计未被冒称完全计量。实际 owner 是可重复的只读模拟器，外部有状态副作用的恰好一次语义仍开放。

参数梯度最大缩放 FD 差 **2.905e−7**，独立 tangent ODE 差 **2.078e−10**。ODE 接收 Q／dQ，参数到 Q 的链另由有限差分检查；这不是对完整金融模型的独立重新推导。最终两 worker 外层 CPU **18.96809 + 1.560494 s**；未计准的早期开发成本明确未知。GBM 参照的最细网格边界差 **0.13150**（strike 100），不是神经任务边界误差界或连续收敛率定理。

对称实现保留首次资格 guard 失败、磁盘满中断及同源码工程重放。非重叠已计量子进程 CPU 下界为 **34.410041 s**；重复档案不重复加账。独立审计核对 2,304 条查询比较及动作／费用；CPU 门仍失败。此优化同样适用于普通同矩阵 HMM。

## 验证与资源范围

原 R16 压缩／执行回归 **10/10** 通过，见 `REGRESSION.json`。新模块的工程检查、独立 ODE／精确枚举及原始记录审计见各候选固定提交。没有据此声明整仓 CI、完整 Rust 构建或统一生产组合通过。

当前环境未发现可用 CUDA 设备或 powercap 能耗文件，见 `ENVIRONMENT.json`。GPU 与焦耳结果为未测量。完整跨模态模型、生产通信和全生命周期采用资格仍需实际实现与独立执行证据。
