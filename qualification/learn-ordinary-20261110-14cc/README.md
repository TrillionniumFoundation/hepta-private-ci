# LEARN：原生训练、NoUpdate 与恢复整合验收

**工程组件验证通过；完整普通任务闭环仍为 `HOLD / NOT_ESTABLISHED`。** 本目录没有把夹具身份、历史模型实验或对象重开计为普通任务验收，也没有签发模型采用结论。

- PR：[hepta-private-ci #5735](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5735)。
- 行为验证固定源码：`1b49f8746ec48a333c34f8a00a693c18248709fb`。
- 对应树：`8489fdedce2b9e7dd4df9a3854b6056fbb6ee619`。
- 基线：用户给出的签名评价桥源码 `abf75d8e2097785b2ad01897c15a7531eebe6e44`。
- [机器可读结论](RESULT.json) · [输入与分支来源](INPUTS.json) · [普通入口的具体装配缺口](ASSEMBLY_GAPS.md) · [证据 SHA-256 清单](ARTIFACTS.json)。

## 本轮落地的行为

### 实际 Q24 训练与原始任务持久化

冻结的单个 Drive 或 Prediction 行现在由真实有界整数 SGD 更新；它使用 serving 的共享整数前向算术，并明确采用量化/裁剪的直通导数。原始 Dataset cut、父模型、目标行、批次和优化规则进入绑定；父模型及其他行不被修改。训练结果是实际候选，或明确的量化权重未变 `NoUpdate`。

`CellQ24TrainingOwnerV1` 在拟合前把原始操作记为 Pending、落盘并确认独立 witness；完成后保存准确候选字节/指标或 NoUpdate，再确认。取消、超时和丢确认不会产生另一次拟合许可。恢复读取原文件和原 witness；缺失、回滚、破损或替换绑定不能被转换成成功。

`read_learning_observation` 从该已锚定 Completed 结果读出不可变、无签名的阶段材料。Candidate 映射到已有 Training，权重未变映射到新 TrainingNoUpdateV2。适配器不产生时钟、签名、claim、训练、CURRENT 或采用权限。

### 训练 NoUpdate 保留独立来源

新协议使用独立签名 tag `8` 和 `TrainingNoUpdateV2`，记录准确的保留 bundle、Dataset、冻结 update rule、实际步数、耗时及 `QuantizedWeightsUnchanged` 原因。它没有 candidate，后续仍需要原始 Selection 和真实 RetainedModelNextUse。

训练角色仍为 Generator。没有候选时不伪造 Evaluation 或 Proposal；Selection 仍验证原始 trainer 与 selector 的分离，NextUse 仍验证原始 observer 的分离。只有持有原始 FrozenLearningScopeV2 的运行/检查点通路能接收这个结果，legacy unscoped 通路拒绝新增和恢复。

旧观察签名字节和 `HEPLCP02` 检查点编码保持原样；只有含新结果的快照使用 `HEPLCP03`。两个方向的 header 替换都拒绝。

### 普通 delivery 与恢复机制合到同一源码

显式 1–64 请求 registry、精确 ACK retirement、claim 前的队列容量保留，以及原 Objective/Circuit 在 claim 前后的重新鉴权已经组合。已 claim 且结果不确定时仅走原任务读回；已 ACK 的回收不联系阶段 owner，也不制造学习快照。

retirement 释放活动容量但保留原任务身份、请求摘要、ACK 和 Circuit 历史。历史存储仍累积。原始 Root handoff 仍绑定一个不可替换的操作/scope，64 请求 machinery 不会扩大这个权限。

完整恢复历史现在会先被验证，再重建其原 Training cut，准确匹配保留的 Evaluation，随后回读原始签名。过期任务的只读恢复拥有独立、固定 30 秒窗口；新提交的原始截止时间和训练期限不因此续期。

## 固定源码的实际验证

| 验证 | 结果 | 证据范围 |
| --- | ---: | --- |
| 四个 crate 的 learning/q24/Circuit 原生切片 | **161/161 通过** | agentd 138、automation 4、learning-artifacts 18、intelligence-eval 1；按 scope 排除 1067 项 |
| 原 CI 指定的 EUID 0 Root 父测试 | **6/6 通过** | 使用实际 sudo/UID、原始注册/传输和外部 UID 连接；按 scope 排除 888 项 |
| learning/Q24/训练 NoUpdate 源码变异测试 | **50/50 通过** | 41 + 6 + 3 |
| 全仓 privileged caller 闭集 | **通过** | 扫描 6193 个 Rust 文件；201 个边界、193 个保护检查项（150 个不同文件）；不授予 authority |

所有这些验证的 `SOURCE_SHA` 与 `TESTED_SHA` 都是上面的 `1b49f87…`，执行前后源码干净，JUnit 为本次运行新生成。Root 的首次尝试是 5 通过、1 超时：测试 UID 60001 无法穿越继承的 `/home/qq` 临时目录。保留原失败、实际 UID 权限诊断后，按原 CI 在 `env -i` 中省略 TMPDIR，原源码/原 helper 重跑六项后通过。

19/19 本地 protocol/eval 测试属于较早的 `a2b5208…`，仅作为独立中间记录保留，不冒充最终源码的验证。

### 维护后版本

行为验证完成后，按仓库要求执行 scoped `just fix`、`just fmt --base abf75…`，两项均退出 0；之后仅运行 `cargo check --tests --bins`，退出 0。准确的 20 个 Rust 文件 postimage 已逐个校验长度、SHA-256、Git blob 和路径集合，合入 `4afbcf04cf329cbcf984793c9d8d51941f072f48`。`fix` 仅移除测试中的三处最后一次使用的冗余 clone；独立静态复核未发现生产逻辑变化，其余为格式整理。

rustfmt 换行使六个精确源码标记失配；`afd8053f915f481c9273695b1853a78e4131c3c7` 同步八个 `CALLERS.toml` 字符串值和两个变异测试锚点。解析比较确认它们仅在空白上不同，否定条件、函数范围、顺序、`top_level`、禁用项与边界注册均保留。该源码的 **193 项保护文件静态检查通过**；这是针对维护后标记的静态核对，不是重跑原生测试、50 项变异测试或整个 caller 扫描。

维护后没有重复行为测试。最终交付明确保留“行为测试源码”“维护后的源码”“静态标记同步后的源码”三个身份；准确命令、日志哈希及 postimage 见 [MAINTENANCE.json](MAINTENANCE.json) 和 [静态检查记录](post-maintenance-static.json)。

## 六步普通任务验收的当前状态

| 用户要求 | 本次状态 |
| --- | --- |
| 普通 A 完成并形成真实 Experience/Dataset | 未建立；缺具体普通 Invocation/Input/result publisher 与 Experience/Dataset owner 装配 |
| 原始训练 owner 由 A 触发 Candidate 或 NoUpdate | 实际计算/持久化/无签名观察适配已验证；普通入口调用尚未建立 |
| 独立 B 与旧能力保留面板 | 原执行/资格/签名机制存在；缺实际产品 holdout provider、attestor、sink 和本次独立任务输入 |
| 原 selector/version owner 提交采用 | 原 CURRENT/FinalUse 机制可复用；本次没有普通链正向采用 |
| 不同输入、全新会话 C 消费选定版本 | 原生组件中的保留版本消费已验证；普通入口的完整 Published owner 装配尚未建立 |
| daemon 与 Root 真正退出后冷重启 | 六项 Root 组件和文件恢复通过；完整 daemon+Root 普通链进程冷重启尚未执行 |

**完整普通链、普通正向采用、普通 NoUpdate/回退链、完整 daemon+Root 冷重启链的本次计数均为 0。** 普通入口的 FeatureV1 与 Q24 GenerationV2 契约仍需真实适配；`main.rs` 尚无所有阶段 owner 的具体装配。不能通过移除 `require_root_learning_assembled`、生成代替原始 owner 的签名，或用测试端口冒充生产实现来改变这个结论。详细可复用 API、所缺代码和原始输入见装配审计。

## 原始证据和复现

- `native-final-1b49.tar.gz`：固定源码的 helper 构建、161 项测试、首次 Root 失败、UID 诊断、6 项 Root 重跑、实际执行 driver、源身份、工具版本/哈希、完整日志、JUnit 和目录完整性清单。
- `source-checks.tar.gz`：本轮所有源码检查记录和原始日志，包含早期失败与最终完整闭集 PASS。
- `earlier-native-attempts.tar.gz`：原始缓存迁移失败、宏编译错误、旧队列 claim 预期失败、43c 的 96/96 和本地 a2b 的 19/19。
- `maintenance-1b49.tar.gz`：实际 fix/fmt/compile-only driver、原始日志、前后状态、准确 patch 和 20 个完整 postimage。维护日志不计作行为测试。

先按 [ARTIFACTS.json](ARTIFACTS.json) 校验文件及档案 SHA-256，再解包核对 execution JSON 的 `log_file` 和 `log_sha256`；JUnit 的 SHA-256 在对应 summary JSON 中。

在原始 owner 测试环境复现普通切片时使用：

```bash
just test --locked --offline \
  -p codex-hepta-agentd -p codex-hepta-automation \
  -p codex-hepta-learning-artifacts -p codex-hepta-intelligence-eval \
  --lib -E 'test(q24) | test(learning) | test(circuit_learning)' \
  --test-threads 2 --retries 0 --success-output final --failure-output final
```

完整的原始环境、SOURCE_SHA/TESTED_SHA 约束、helper 校验和六个 Root 测试的准确名称/参数在档案 driver 与 execution JSON 中。Root 测试需要真实授权的 Root 环境；本地普通用户结果不会被当作 Root 结果。仓库要求测试先行，然后 scoped `just fix` 与 `just fmt`；维护后仅编译核对，不重复行为测试。

本轮没有重跑暴露过的 SmolLM 评价面板，没有把较差候选强制采用，也没有启动多个时间窗口的持续收益研究。
