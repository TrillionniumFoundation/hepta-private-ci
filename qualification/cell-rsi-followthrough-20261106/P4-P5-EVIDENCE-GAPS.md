# P4 / P5 既有证据与准确缺口

本附录只读取现有 PR、固定源码及原回执，没有启动实验、训练、服务压测或多机任务。这里的 P4 / P5 指用户要求的 Cell 递归效率与持续服务资格。

本文的 `evidence/` 与 `p3-audit/` 相对路径指完整交付包 `hepta-cell-rsi-20261106.zip` 内的 `qualification-review/` 目录；Git 附录保留结论和来源身份，完整原档案随交付包提供。

## P4：当前可审阅证据不能证明后代改进器更强

在本次读取的 Cell PR、RSI / recursive / improver 相关检索结果和关联资格材料中，没有取得一份同时具备“相同初始系统、旧/新改进器完整预算、多个种子、未见任务、后代改进质量对照”的原始实验回执。这是本次证据范围的结论，不是对整个私有仓库作穷尽不存在断言。读取结果索引在 `evidence/p4-bounded-review-index.json`。

[原 Cell differentiation #4890](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4890) 的 CPU 研究明确记录 `rsi_proven=false`、`production_authority=false`。原 2 场景 × 5 种子研究的 10/10 trial 都 HOLD；它研究一次专家分化，不是比较新旧改进器改进下一代的能力。本次对完整原 artifact 的审计见 `p3-audit/README.zh.md` 和 `p3-audit/AUDIT.json`，不能把那个研究的五种子当作 P4 的五种子。

要使 P4 可判定，仍缺少以下实际分母和结果：

| 必需对照 | 当前缺少的原始证据 |
|---|---|
| 相同初始系统 | 每个种子旧/新改进器分支的初始模型、环境、任务池、权限与 artifact digest；不能拿不同父代的后果相减 |
| 完整预算 | 两边搜索、训练、诊断、评估、被拒候选与失败重试的全部累计成本；不能只比较最终一次成功更新 |
| 改进器自身的区别 | 固定的新/旧改进器 artifact 与其实际执行轨迹，而不是仅换下游模型或增加容量 |
| 未见任务 | 改进器选择阶段不可见、评估前固定的任务集及全部请求结果；不能把多次查看的开发集当未见任务 |
| 全部种子与后代 | 预设种子和后代数、缺失/失败分母、每代输入与产出关系；不能仅保留胜出的后代 |
| 稳定超越 | 在前述同口径下，改进质量与成本的成对结果，以及事先规定的稳定性判据；当前没有可据以报告的效果量或置信结论 |

本次没有新增这个实验，也没有生成一个可误认为结果的成功标记。

## P5：有真实工程测试，尚无持续服务联合资格

读取的 [#4938](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4938) delivery head 为 `f09dea504916d551e13fe36752dd1e833bcaa51b`。原 native gate 执行 source 是 `cb6f0a4a180677213988f6a4cc25c8431dfe5805`，tree 是 `d28638c3c38228891b2016758d795b787bb8e6d3`。`evidence/resident-cb6f0a4a-status.json` 和 `evidence/resident-cb6f0a4a-independent-summary.json` 保存原结果的复制件。

实际读取并解析的原 JUnit 文件是 `evidence/resident-cb6f0a4a-junit.xml`：203,635 字节，SHA256 `6438071ad4e807aaadee50943f16041ef412ccce6fe08519d83984d33b19e35f`，959 个 testcase、0 failures、0 errors。测试范围是 agentd、neuron、infer-worker-host、infer-core 四个 package，原 gate 明确 `whole_workspace_tested=false`、`qualification_authority=DENY_ALL`。Runner 另外报告的 67 skipped 不能当成通过；XML 中的 959 也不能再叠加那些 skipped。

这些原测试确实包括 resident 模型资产共享、并发 Cell 状态独立、未知提交后禁止自动重放、population artifact/role 拒绝与 pending 容量保留，以及 checkpoint / migration / cost comparison 的行为。它们是应保留的工程进展。`evidence/resident-junit-review.json` 保存完整解析结果及选出的 78 个相关 testcase；这些 testcase 的秒数是测试方法的 wall time，**不是产品请求级 p99 样本，也不能用来计算吞吐提升**。

原源码还明确保留以下边界：resident 交换串行，无 microbatch / pool scheduling 结果；immutable weights/public 共享不代表已测 RAM / VRAM 下降；checkpoint 回收 segment 不解除 receipt / prefix / cost / witness 的独立容量限制；宿主仍负责 archive custody、恢复后的 pathname、peer scheduler 排他与生产 migration verifier。没有把这些边界补成已完成的服务指标。

### P5 尚缺的真实指标分母

| 指标 | 要与同一候选一起提供的分母 / 原记录 | 现有工程回执不能替代的原因 |
|---|---|---|
| 质量 | 多 Cell、多任务的所有请求，含失败、超时、取消与恢复后结果；旧能力与新任务同时报告 | JUnit passed 不等于产品任务质量 |
| p99 | 固定到达窗口和负载下的端到端 request latency，保留未完成请求、排队和 deadline 处理方式 | fixture duration 不是请求延迟分布 |
| 吞吐 | 同窗口、硬件、并发与质量门下完成的有效任务/时间；重试不能重复计成功 | resident 重用一次资产不能推出服务吞吐 |
| RAM / VRAM | 同硬件和模型身份的基线、稳态及峰值；CPU RSS/PSS 与设备内存口径明确 | 参数字节和共享 API 不等于实际进程/设备占用 |
| 恢复 | 全部故障点与原 pending 分母、恢复时间、状态和 output / receipt / cost 连续性 | 单次序列化或 file reopen 不代表持续服务故障恢复 |
| 状态增长 | journal、checkpoint、witness、receipt、prefix、cost、artifact 与归档在运行时长/任务数上的增长 | segment compaction 会把成本转到保留归档，不能只量当前 segment |
| 实际成本 | 同有效任务质量下 CPU/GPU/存储/网络和失败工作消耗，实际计费或可核计量 | 算法 FLOPs 与参数大小不等于成本节省 |
| 多机（确有必要时） | 共享模型与权限边界、跨机状态/owner 身份、网络与故障成本的同候选记录 | 单机常驻 worker 测试不证明多机共享正确或有收益 |

没有真实指标时应保持“尚未取得联合资格”，不能填零、用理论值代替实测，或把不同 donor 的质量、延迟与资源记录拼成一个成功结果。最终规格须先固定候选身份、负载、硬件、观测窗口和预设接受阈值；本次没有为获取漂亮结果而重跑预算。
