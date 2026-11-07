# P0 统一候选的来源与冲突归并规格

状态：只读审查提案；`authority=DENY_ALL`；尚无已组装、已构建、已验证的统一候选。

本规格对应用户的产品 / Cell / resident / HCSN / 权限与恢复版本统一目标，不对应 hepta-runtime REA 的其他 P0–P5 编号。来源限定为下列固定提交；来源 PR 的成功测试只能作为各自工程进展，不能相加充当最终候选资格。

根任务报告：自动审核先拒绝 #4963 clone，后拒绝 #4938 实际 merge，理由是其他分支当前仅可只读 review、不得合并执行。此后没有进行这些跨分支采用。本文件使待批准对象具体化；它不是解除该限制的执行指令，也不是可直接应用的已验证 patch。

## 固定来源

| 部分 | PR / 固定 head | 归并价值 | 现有证据的边界 |
|---|---|---|---|
| 当前基底：Memory / Cell | [#4935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4935) `9f73f82ca7454d9d00e4fc71af43fdffba14c5e3` | 本次允许修改的基底；保留 Memory 运行及恢复事实 | 不能据此认定正向有收益采用已经完成 |
| resident / population / lifecycle | [#4938](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4938) `f09dea504916d551e13fe36752dd1e833bcaa51b` | 常驻 worker、真实 owner population、checkpoint / migration / cost comparison | 测试提交 `cb6f0a4a180677213988f6a4cc25c8431dfe5805`，原 JUnit 959 passed；不是统一候选实测 |
| portfolio / sealed observation | [#4944](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4944) `25fa6d6dd7e1c5c1827a4099f601aee49b2f1b58` | 基于 #4935 的 sealed observation 与 generation episode | 与 #4963 有逐字节重复模块；不要另造 owner |
| 普通 runtime / control / 恢复 | [#4963](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4963) `3b31842504121e8ae40909db1edc17e7790cf688` | 普通入口、当前 owner 回读、no-contact settlement 与身份保护 | PR 正文里旧 head / 旧 runner 不能转为当前 head 通过回执 |
| HCSN 工程父来源 | [#5001](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5001) `44e539313e0c54badb4b9b687425dd87ecba6e67` | 原 HCSN worker / recovery 工程 | 早期 cfg(test) 注册不等于普通产品接线 |
| HCSN 普通 PQ compose | [#5067](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5067) `bbe995c43e4eed4bb9c217b52447ba5a32ebb6ca` | 叠 #5001 的普通 PQ host compose | 根核实 run 42240138316、jobs 127967938963 / 127967939575 成功；仍需普通 daemon / AuthBus / 托管身份与最终候选绑定 |
| 产品 W0–W7 | [#4855](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4855) `a86267a0525448870c47a641fb54cd510543ba7a` | 实际产品入口及产品级接线来源 | 本地未发布 prepared tree / PR 描述不代替此已发布 head；不能直接把其他线的结果接到它名下 |

`P0-SOURCE-REVIEW.json` 保存读取时 PR 身份和已读取 Rust 文件的 Git blob / SHA256，供逐项复核。固定 commit 的源文件 URL 可由 `https://github.com/TrillionniumFoundation/hepta-private-ci/blob/<sha>/<path>` 构造。已读取文件快照只用于审查，没有装入生产树。

## 提交关系必须先保留

#4944 包含 #4935 完整祖先：相对 #4935 ahead 8 / behind 0。它是已叠加来源，不能把 #4935 部分再次按独立功能重复移植。

#4938 与 #4935 已分叉，共同祖先 `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75`，#4938 相对 #4935 ahead 11 / behind 29。#4963 与 #4944 相对同一祖先 ahead 26 / behind 37；与 #4938 相比 ahead 26 / behind 11。它们不是可以无损依次覆盖的同一条版本链。

#4855 产品线与这些 Cell 分支还有独立基底差异。批准后应先得到真实三方 diff 并逐路径决定，而不是把某个 PR 的整棵旧目录覆盖当前树。当前没有产生已合并的冲突文件列表，以下是来源阅读发现的必审语义冲突。

## 唯一 owner 与逐模块归并规则

### 已证实完全重复，应保留单份

| 模块 | #4944 与 #4963 相同 Git blob | 归并要求 |
|---|---|---|
| `codex-rs/hepta-neuron/src/cell_generation_observation.rs` | `47edaa34ddeaad7498bbfc4326bab58a228d2670` | 仅一个 sealed observation 定义；不得以第二个 projection owner 承接实际状态 |
| `codex-rs/hepta-intelligence/src/generation_episode.rs` | `b19ba6574f25fc9bad1ba947b671e05ff42a8ff4` | 仅一个 episode 过程；普通 runtime 与 portfolio 都调用同一 owner 事实 |

`AgentdNeuronGenerationOwnerV2` 仍是 journal / admission / settlement 的实际 owner。population observation 与 sealed observation 是不同投影，不是两个可以分别提交模型状态、输出或成本的 owner。

### #4938 适合独立审查的新增生产模块

下列路径相对共同祖先新增；“新文件”不表示可以跳过编译、声明、原 owner 的调用链或权限接线。

| crate | 路径（相对 crate） |
|---|---|
| `codex-rs/hepta-agentd` | `src/neuron_generation_population.rs`、`src/neuron_generation_runtime_population.rs` |
| `codex-rs/hepta-infer-worker-host` | `src/joint_generation/resident.rs` |
| `codex-rs/hepta-neuron` | `src/cell_cost_comparison.rs`、`src/cell_generation_lifecycle.rs`、`src/cell_generation_migration.rs`、`src/cell_joint_generation_support.rs`、`src/cell_joint_resident.rs`、`src/cell_joint_resident_io.rs`、`src/cell_owner_population.rs` |

`cell_population.rs` / `cell_roles.rs` 也来自这条新增设计线，但 #4935 / #4944 已有对应同源模块；须检查现存文件而不能追加重复定义。

### 必审重叠路径

| 路径 | 需要保留的两侧语义 | 接受条件 |
|---|---|---|
| `hepta-agentd/src/neuron_generation.rs` | #4938 population binding / `step_with_population_checked`；#4963 `settle_no_contact`、Admission / Dispatch / Settlement 三个检查点 | 同一个 owner 同时执行绑定和三阶段检查；不得增加能绕过 journal 的执行口 |
| `hepta-agentd/src/neuron_generation_runtime.rs`、`neuron_generation_service.rs` | `PopulationObservation` / `StepWithPopulation`，及 `ObserveGeneration` / control / intent 回读 | 命令枚举与 service exhaustive match 全部接到同一 owner；调用失败不能重开新请求 |
| `hepta-agentd/src/neuron_generation_runtime_population.rs` | `with_population`、`population_observation`、`step_with_population` | owner 自己核本地 manifest/generation/schema/role；peer 观测的 freshness 必须由原 scheduler 跨 gather 到 await 全程排他，不能从投影年龄猜测 |
| `hepta-neuron/src/cell_generation_state.rs` | #4938 checkpoint 所需 Serialize / Deserialize；#4963 `first_advance_input_digest` 与 `intents` | 完整持久化、恢复、校验和容量计数，不用空 defaults 丢掉 episode / replay 事实 |
| `hepta-neuron/src/cell_generation_journal.rs` | #4938 checkpoint / metrics；#4963 `receipt_for_intent` 与 replay 回读 | 恢复后同 intent 得到原 receipt；不得靠新执行补 receipt |
| `hepta-neuron/src/cell_generation_lifecycle.rs` | checkpoint 整体 state 与 witness CAS | 新 state 字段进入 checkpoint 校验，旧不兼容 checkpoint 要拒绝并保留可核原 journal，或执行显式有来源迁移；不能默默归零 |
| `hepta-neuron/src/cell_joint_generation.rs`、`cell_joint_process.rs` | resident 接口与 #4963 当前 artifact 校验 / 零时钟拒绝 | 单次 / resident 使用同一 manifest 契约，真实 worker、模型、块间 state 必须一致 |
| `hepta-neuron/src/cell_joint_assets.rs`（#4963 相关来源） | FD 打开后 pin 住 artifact、公开 `validate_manifest` | 不能被较旧路径字符串实现覆盖，路径替换不能改变已经允许的 artifact |
| 各 crate `lib.rs` 与关联 tests / Cargo 接线 | 新模块导出、已有观察和恢复路径的唯一声明 | 不重复 owner、type 或导出；以最终树编译结果确认，不能仅以 text merge clean 确认 |

### no-contact 恢复与 resident 的关键限制

#4963 的 `settle_no_contact` 只有当前 live 调用栈能够证明未接触 worker 时才可执行。Admission 后、Dispatch 前发生 drain 或 deadline，可以在 Settlement 再核边界后记录 Queue 的实际时间成本并终结；没有模型状态或输出。重启后没有 readback、worker error 或未知提交结果都不构成“未接触”证明，必须保留 pending / 预留容量与原恢复路径。

#4938 resident 首次绑定共享 immutable weights/public，后续串行 exchange 重用；已提交 frame 后发生不确定错误不能自动 respawn / retry。它没有证明 microbatch、pool scheduling、吞吐提升或显存收益。将 resident 接入普通 runtime 时必须保留此不重放约束，同时使用当前 artifact FD pin 与相同模型身份。

### checkpoint 和状态增长

原 journal header magic 为 `HPTACG02`；#4938 checkpoint 头使用 `HPTACG03`。checkpoint 最大 32 MiB，原事件 frame 最大 2 MiB，segment 128 MiB；checkpoint 的 `state` 是整个 `GenerationState`。compaction 不是扩大独立 receipt / prefix / cost / witness 容量的许可证，也不是 archive custody、跨 owner witness succession 或真实生产 migration verifier。

必须明确新增 `intents` 与 first-input digest 如何在 checkpoint 里保真、如何有界，以及旧格式无法重建时的拒绝行为。最终实现不能把未知 pending 归零，也不能把全量恢复后的 journal 结果与 checkpoint 恢复结果当作不同 episode。

## 最终候选身份清单

下面字段组是验收所需的候选台账设计，不表示当前仓库已存在这些同名 JSON 字段。组装后应由实际构建产物生成，空值、可变 branch 名和未发布本地 tree 都不能充当通过身份。

| 必需身份 | 必须实际绑定的对象 |
|---|---|
| 候选 source / tree | 唯一最终提交与 tree，donor 固定 SHA 与实际移植路径 / diff，构建配方和 lockfile |
| artifact | 实际 Agentd / 产品 binary、resident host、真实 worker executable / Python source manifest、模型权重和 public / schema / encoder / head 的 digest |
| role 与权限 | 当前 artifact compatibility bundle、实际功能 role、签名 permit / deployment 来源与各入口授予范围 |
| owner 与恢复 | journal owner identity、generation、witness / checkpoint、task 与 intent / request 的连续性、原 job / worker incarnation |
| 普通入口 | 产品真实调用路径 → Agentd 正常注册 → admitted control port → 真实 worker；不能只给测试 fixture 注册回执 |
| 质量与成本证据 | 同候选身份下完整任务 / 失败 / 超时 / 取消 / 重试分母，实际预算及门结果；不得拼接不同来源 commit 的通过数 |

## 获准后最有价值的必要验证

1. **唯一入口及 owner**：产品普通入口发请求，证明 sealed observation、population observation 和 episode 最终都来自同一 journal owner；换 artifact / role / owner / schema / encoder / head 任一身份都必须拒绝。
2. **checkpoint 与 replay**：带 first-input digest、多个 intents、已提交 receipt、pending 与未投递 outbox 的状态，checkpoint 后进程重开仍返回原 receipt / output / cost，不能重新执行；旧不兼容 checkpoint 拒绝且原 journal 保留。
3. **跨特性 pending**：admission 成功后在 Dispatch / Settlement 各边界注入 drain、deadline、时钟回退；只有有 live no-contact 证明的路径可终结，其余未知状态保留并读回原请求。
4. **resident 与模型身份**：两个块由真实常驻 worker 执行且 state 连续；已提交 frame 的未知结果不重发；artifact 路径替换、manifest / worker incarnation 不匹配被拒绝。
5. **population freshness**：并发 peer 改变时不能复用旧观测获取超限许可；Lost-response retry 仍持有原 scheduler 排他条件，不产生第二 owner 或重复执行。
6. **HCSN 普通接线和取消**：同最终 candidate 的普通权限路径使用原 job / nonce / worker 身份；有真实训练阶段证据后取消并恢复同一 job，不把 wrapper 启动当训练进入，不新建训练补结果。
7. **最终源码必要门**：按仓库 AGENTS 的 scoped `just test` / fix / fmt 工作流跑最终树必需门；结果绑定最终 source / binary。donor JUnit 的计数与当前候选分开保存。

上述仅是候选整合后的必要验证规格，本次未执行跨分支 merge、构建、真实训练或 worker 调用。P1 正向收益、P3 匹配强对照、P4 改进器代际收益和 P5 服务指标仍各需自身完整证据，不能由这份规格关闭。
