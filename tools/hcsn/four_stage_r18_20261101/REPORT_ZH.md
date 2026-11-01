# R18：任务边界、可靠性、原生恢复与规划成本

本轮并发完成五项候选，并在同一源码组合中保留所有原始记录和失败。**新增通过的是受限连续任务数值门、声明生成器族内的非确定答案可靠性、原生有状态服务恢复，以及共享规划器的在线 CPU 门。核心独立 D−B、完整投资采用、真实多模态与完整生产资格仍未闭合。生产保持关闭。**

R18 基线 `3937a5f68aa455433ecfce6f8f045f57e7c07b4b` 已先收敛 R17 四项源码与证据的 270 个原始 blob，保留各分支真实父提交和原有适用范围。五项 R18 候选均固定最终交付提交；520 个本轮分项文件的远端 Git blob 身份全部与本地最终字节对应身份匹配，见 `REMOTE_READBACK.json`。

| 阶段 | 本轮新增实际验收 | 仍未闭合 |
|---|---|---|
| 算子与传播 | 有限期限连续质量／内容模式任务接入 STOP、WAIT、付费 RESET；保留完整恢复剩余时间。修正复位准入跳跃后，11 项数值门通过；最细主解／独立正 Gaussian 参照差至多 3.53e−4。 | 完整 He–Xiong 金融／神经任务边界、新 jump solver 全参数梯度、真实网络的统一训练与执行。 |
| 连续动态任务 | Rust 有状态 owner／provider V2：130 案例、408 个进程，780 查询／效果、260 持久租约回执通过。另以现有生产 journal／witness API 实际绑定六项账单收据并验证追加／确认窗口。 | 原生数值核仍是冻结 Python 状态的不透明重放；主路径模型准入、网络、机器断电及完整生产生命周期。 |
| 内容任务 | 1,024 个锁定世界、256 个未见参数生成器；148 项真正非确定接受、5 错误，按生成器分组的风险上界 5.97%，通过原 10% 目标。 | 未见生成规律、开放域语义／跨模态绑定、分析核心独立贡献。 |
| 模型采用成本 | 128 个共享世界、4,608 次执行中，行为、查询哈希与既有 query2 快照精确一致；六组价值规划 CPU＋准备成本比 0.638499–0.777147，通过 ≤0.90 门。 | 所测峰值分配增加 21.6%–23.5%；全部优化投资计入后的 1,000 次复用净优势未建立。GPU、焦耳、真实媒体和完整采用门仍开放。 |

## 固定源码及分项入口

| 候选 | 最终交付提交 | 入口 |
|---|---|---|
| 声明族内生成器不确定性 | `1cdfe662fa7029b453ec90371168ff40b3420a18` | [PR #4572](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4572)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1cdfe662fa7029b453ec90371168ff40b3420a18/experiments/hcsn_unknown_generator_r18_20261101/REPORT_ZH.md) |
| 原生有状态服务恢复 | `ed5f4928a6533c2d3b3352901617ceaf4cbe8d12` | [PR #4573](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4573)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ed5f4928a6533c2d3b3352901617ceaf4cbe8d12/tools/hcsn/native_owner_r18_20261101/REPORT_ZH.md) |
| 连续任务边界及恢复准入 | `25a3baf9462c5371653d93f016e57b837f4f978c` | [PR #4574](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4574)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/25a3baf9462c5371653d93f016e57b837f4f978c/tools/hcsn/continuous_task_r18_20261101/REPORT_ZH.md) |
| 实际生产 journal API 桥接 | `ce3a08da62cd3553959d7fd25907e7cbc19c9abf` | [PR #4575](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4575)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ce3a08da62cd3553959d7fd25907e7cbc19c9abf/tools/hcsn/production_bridge_r18_20261101/REPORT_ZH.md) |
| 精确 Bellman 规划加速 | `f5c5190104031616fddc53952f4e223d47477fe3` | [PR #4576](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4576)；[报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f5c5190104031616fddc53952f4e223d47477fe3/tools/hcsn/planner_fastpath_r18_20261101/REPORT_ZH.md) |

## 连续任务：修复真正的时间因果错误

新任务使用公开连续质量状态、两种可观测内容模式和实际 Bernoulli 内容奖励。RESET 支付费用，经历完整恢复时长，按给定模式转移返回并继续使用剩余期限。第一轮保留两项失败：主解／参照间差超过阈值，且一个 profile 的网格差没有下降。审查发现粗 DCT 投影的负权，以及原隐式步骤把刚准入的 RESET 障碍提前传播到此前时间。

后续在新的源码冻结下，先推进准入前左极限，再在恢复时刻施加新 RESET 值；独立正 Gaussian 图像／hat 积分参照不做裁剪或重归一化。11 项原数值门全部通过，且原两项失败未删除。两轮共 24,576 次实际 mesh 执行的状态、费用、恢复时间、收益与区间由独立审核器重放。

实际执行仅在注册 mesh 上观察／动作，不宣称连续首次触达执行。相对强普通同 law 参照的净收益区间在三个 profile 中均跨零；加强后的 81 个模式固定策略比较结果混合。任务控制机制有效不等于新核心独占优势。旧四坐标导数验证属于旧 active-branch solver，新 jump solver 的全参数梯度仍开放。

## 内容可靠性：接受真正的不确定答案，保留异族失败

模型只从公开训练流拟合，随后在确认前发布模型、OOD 阈值及选择阈值。校准对候选阈值进行同时控制，目标风险固定为 0.10；Markov 模型以 0.95 阈值通过，独立生成器校准中 283 项非确定接受有 11 错误，同时 CP 上界 0.08162。较低阈值的失败保留；普通 pooled IID 未通过非确定风险门，回退到近点质量接受。

锁定确认中，Markov 共接受 907 个查询，其中 148 个为真正非确定概率；5 个错误对应按生成器分组 bootstrap 上界 0.05970。相同初始公共前缀上的 Brier 改善 **0.04263 [0.03233, 0.05413]**，实际选择性收益改善 **0.10258 [0.07835, 0.12777]**；实际 READ 的信息价值和费用另有配对后继记录。独立审核重现校准、统计、1,184 个 owner 世界和 555 次 indexed READ。

新生成器是同一声明总体的新参数抽样。真实 rotor 异族上，Markov 收益 0.58906，弱于 pooled 的 0.81172；不能称跨未知规律稳健。词表面板是输入 schema 损坏拒绝检查，不是真正新类别世界。两模型均为普通统计方法，未提供解析首达核心 D−B 或学习语义寻址结论。

## 原生恢复：修正两个持久化缺陷并接通真实 API

原生服务有实际持久计费、请求去重与代次 fencing。审查推动修复两处缺陷：写盘不确定后返回缓存成功，以及先提交租约代次、后提交回复导致丢失回复时重复授予。V2 将 provider 候选状态与回复一起原子提交，并在存储不确定时 fail-stop；新增丢失 LEASE 回复的真实进程死亡案例。130 个最终案例及 408 个进程全部通过。

数值状态是冻结 Python oracle 的不透明受控重放；本地 socket 绑定不获当前环境支持，采用独立 Rust 进程之间的持久文件 mailbox。没有网络或断电资格声明。另一个 Rust 二进制调用未修改的生产 `SparseJournal`／`FileAnchorWitnessStore`，57 个生产源码 blob 与基线匹配，离线锁定构建及实际过程检查通过。收据哈希不认证远端 provider；`DENY_ALL` 与 `requires_calibration=true` 保留，生产主路径模型准入仍开放。

## 成本：在线省算与投资回收分别判断

规划器保留原矩阵操作形状与浮点顺序。早期矩阵拼接虽只有约 3.3e−16 数值差，却改变 53 个近平局动作，已作为失败保留；最终实现及 3,927 项验证器边界检查精确匹配。旧 V3 正式确认因一组 CPU 比 0.9094 未通过，随后源码修正和新命名空间确认全部保留。

最终六组 CPU＋准备比为 **0.6385–0.7771**；固定策略未普遍省 10%。价值策略的所测峰值分配增加 **21.6%–23.5%**。全部已记录开发／失败／确认／内存诊断投资下界 **141.098189 CPU 秒**；全部计入一个部署组时，1,000 次／fit 复用净优势未建立，盈亏平衡只是未实际执行的线性估计。此优化同样惠及强普通 HMM，原 D−B 和 anchored/full 压缩采用门未改判。

各阶段外层成本独立列示，嵌套计时不相加：内容准备／确认 22.891199 CPU 秒；原生两轮完整 campaign 36.998535 秒；连续两轮 47.294414 秒；生产 API 检查 0.184375 秒。范围不同，未冒称这些数据构成整个项目或统一生产生命周期的完整总账。

## 剩余阻塞

必须继续获得的证据包括：完整金融／神经模型自由边界与一致梯度；相同价值控制下对强普通核心的 D−B；超出声明生成器族的泛化及真实多模态绑定；完整投资、内存、质量、时延、吞吐与能耗下的采用收益；原生金融核、生产模型端口、真实通信和机器恢复。当前没有 GPU 或可归因设备能耗测量。

数值和行为验收均保持所声明的范围与门槛。`all_blockers_closed=false`，`production_activation=false`；没有完整仓库 CI 或生产部署通过声明。
