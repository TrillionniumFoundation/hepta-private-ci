# PRED 原生记录、跨语言重放与纯 shadow 闭合记录

日期：2026-11-12（UTC）。实现最终源码：`7214dfc7f093c5d5f63b87f553cb298b7aa5132c`。

## 当前结果

CI 身份传递已修复，原授权效果 host 与 native exporter 的 8 项定向 Rust 测试已实际通过；真实 Rust 测试产生的原始 slot 字节已被 Python ABI 导入，并由另一个进程完整重放。纯 shadow 现在能保留原 owner 动作与 policy，将独立效果接到独立的 calibration schema。

工程机制已有可复核结果。新增 live owner 历史、独立真实效果标签、真实策略比较仍各为 **0**；未部署新预测入口，生产资格仍为 **HOLD**，策略 **NoUpdate**。本轮测试中的模拟 checkpoint 和效果 fixture 不计入真实训练研究。

## 分阶段实现

全部为可单独审查的 Draft PR；未合并、未部署。

| PR | 精确源码 | 内容 |
| --- | --- | --- |
| [#6140](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6140) | `fbee6fb9bd4e5a847b830b475a02cb1849347ea5` | 修复 workflow 身份传递，新增实际 wrapper 控制测试，8 项 native 最小门槛；诊断 stderr 写入失败不再影响效果路径。 |
| [#6148](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6148) | `0582fc0b98561066dcb20d0039b833be86c4aaef` | 严格读取 native 原始字节，检查 JSON、哈希、字段顺序、身份和文件边界。 |
| [#6149](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6149) | `bf78a9218a6fd9d8b9c51d6505418b53ebc47f9b` | 区分意图、owner dispatch、settlement、reconciliation；保留原件并重建验证事件 ABI。 |
| [#6156](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6156) | `3d6a2501519873e007a187516e1692d9be70d622` | 留存实际 Rust slot，Python 导入和新进程重放；保留首次格式失败及其原始修复补丁。 |
| [#6181](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6181) | `0e4b3f45aa70d24c99c56246f83aa3408124f9e9` | empirical / MLP / GRU 纯 shadow panel，保留调用方声明的实际 owner 动作与策略。 |
| [#6186](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6186) | `7214dfc7f093c5d5f63b87f553cb298b7aa5132c` | 独立效果只校准原 owner 动作，未知与删失保留；与普通策略价值 schema 隔离。 |

## 1. 原生 CI 的证据链

原始 [job 130999723460](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43163443449/job/130999723460) 的 `source_sha`、`tested_sha` 为空；wrapper 在 Rust 测试启动前拒绝输入。修复把 `SOURCE_SHA`、`TESTED_SHA` 绑定到 `github.sha`，显式设置 `source-head` lane，并实际测试缺失、错配、非零退出及测试数量不足的拒绝路径。

首次修复源码 `fbee6fb9…` 在 [job 131012526264](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43167448134/job/131012526264) 通过 5 项 workflow 控制和 8 项 native 测试。它不替代后来新增跨语言测试源码的独立验证。

跨语言阶段初始源码 `1c009be6644148d9709251fd6048205f92ffedde` 在 [job 131016848006](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43168795968/job/131016848006) 因两处 Rustfmt 换行失败。该次 native 测试、Python 重放和 Clippy 均未运行。原失败日志、artifact 与格式补丁原样留存；后续提交只应用该原始格式补丁，没有改写历史结果。

最终原生源码 `3d6a2501…` 在 [job 131019885770](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43169731405/job/131019885770) 完整成功：

- 原始两份执行 receipt 的 `source_sha == tested_sha == 3d6a2501…`，tree 为 `c80b42d05503f81b5b4b3a6e926658d89b71db19`，前后源码均 clean。
- 5 项 workflow 身份控制通过；要求的 8 项 Rust 测试逐名出现一次且全部通过。另有 778 项被 selector 过滤，未声称整个 crate 全量通过。
- Rust 格式检查、配置的 Clippy 检查、最终源码未变检查和 artifact 上传通过。
- 原 native 测试使用普通效果 host 的原授权路径；其 provider、数据库和任务是测试 fixture，未因此取得生产采用或真实业务效果证据。

## 2. 实际原始字节到新进程的重放

Rust 原测试在原有断言与 provider 验证全部通过之后，将此前已读到的原始 slot 字节写入私有目录。Python 不能在缺少它时回退到合成 JSON。导入过程保留原件，新进程重新校验完整 ABI。

| 项目 | 核验结果 |
| --- | --- |
| 原生 job artifact | ID `13922297993`，28,347 bytes |
| artifact SHA256 | `66f8e9f77073037689877f0789305a6c0b89e3f5c016ba453562f800a169b3ce`，与 GitHub digest 相同 |
| native fact SHA256 | `9fbda326d83241ea9350832e239f475cf5393839d2209b49a03e2bd3458a3ca3` |
| ABI SHA256 | `f726d87e4f8c43ab6f2c0d04814a8317154f399a28346797c94773fa8a2d4fb8` |
| 进程独立性 | 导入 PID 22670；重放 PID 22671 |
| 原件一致性 | Rust slot 与 Python 保留原件逐字节相同；两份 command log 的 SHA256 均与各自 receipt 中记录值一致 |
| 完整重建 | 独立重算 canonical envelope、payload 与哈希；子进程 stdout 与报告 readback 相同 |

该报告明确为 `native_test_fixture`。ABI 的共享到达游标、共享时钟、效果标签仍为 null；授权、执行、独立效果没有因出现意图事实而被提升为已证实。哈希证明字节一致性，不认证实际来源。

## 3. 事件与 shadow 的语义

原 exporter 位于 host 对 intent/fence 的校验之后、实际 FinalUse 授权验证之前。它留下的是决策前意图事实，不能单独证明授权通过、实际执行或业务效果。两个 owner 读取也不构成原子一致快照。

新 ABI 保留 native wall time、局部 step 序号、collector 声明各自的含义。缺少 attempt 不被写成“确定没有联系 provider”；settlement 成功也不产生质量、耗时或成本标签。后续 reconciliation 保留在独立事件域中。

之前的 `predict_owner_history_choice` 会通过 `choose_fixed1` 选择模型 argmax；当它与原 owner 动作不同时，该接口不适合作为被动 shadow。本轮新增 `predict_owner_history_shadow`：

- 实际加载固定 checkpoint，预测合法动作 panel，始终保留外部固定的 owner action、owner policy，并单列模型 SHA。
- 外部固定 snapshot、模型、clock、cursor、预算、task group、split 和 source；验证时重算整个 panel 与 wrapper，协调重写内外哈希也不能绕过这些绑定。
- `decision_at` 仅指内部 shadow freeze 时刻，原 owner 实际选择时刻未被观察。
- 新 public schema 为 `pred1-owner-history-shadow-v1`，不进入普通 observed/model-row/policy-value 读取路径。

新增 `join_owner_shadow_effect` 额外固定完整 shadow 原件，复用原独立效果 join。witness 必须指向原内部 `owner_decision_sha256`；不会改写 witness 让它适配另一个动作或模型策略。输出 `pred1-owner-shadow-calibration-v1` 只对实际执行的 owner 动作给出 Brier / CRPS 分数；未执行、缺回执、等待、取消、右删失、缺失成本与未知完整 wall time 保留原义。完整结果经重建验证，不依赖单个 `policy_value_allowed=false` 自报字段。

这些是 Python 工程入口，尚未接入普通 native daemon 的实际预测调用。它们也不认证 caller 声明的 owner 动作、clock 或游标。

## 4. 验证范围

最终本地候选的 PRED 全集 **212/212 通过**，另有 **5/5 workflow 控制通过**；Python 3.12.14 / NumPy 2.3.5。70 份 Python 文件运行前后及格式检查后哈希不变，随后逐一确认与最终发布提交 `7214dfc7…` 相同。

独立 reviewer 对最终四文件执行 **7/7 shadow / calibration 测试**，并确认 12 份旧 checkpoint 源码闭包与 `3d6a2501…` 逐字节相同。新用例覆盖相反 argmax、效果错绑、bool 冒充 attempt、预算/成本拒绝、UNKNOWN/删失保留、create-only 输出和协调重算哈希后的篡改。

`3d6a2501…` 的 [PRED CPU run 43169740106](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43169740106) 原始日志确认：

| 平台 | 发现的测试 | 实际通过 | 跳过 |
| --- | ---: | ---: | ---: |
| Ubuntu | 205 | 205 | 0 |
| macOS | 205 | 199 | 6 |
| Windows | 205 | 195 | 10 |

最终实现 `7214dfc7…` 的 [PRED CPU run 43172039470](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43172039470) 也已从每个平台的完整原始日志核实：

| 平台 | 发现的测试 | 实际通过 | 跳过 |
| --- | ---: | ---: | ---: |
| Ubuntu | 212 | 212 | 0 |
| macOS | 212 | 206 | 6 |
| Windows | 212 | 202 | 10 |

3 项新 shadow 测试和 4 项新 calibration 测试在每个平台都逐名实际通过、各出现一次。跳过项仍计为跳过；macOS 的 6 项为 Linux wrapper 测试，Windows 另跳过 1 项 Unix source reader 和 3 项 Unix smoke refusal 测试。对应源码、run、job 与原始日志哈希见 `STATUS.json` 及证据包。

本地 `just fmt` 针对 changed files 成功，Ruff check / format check 成功。本地没有 cargo / rustfmt，故本地格式命令不增加 Rust 格式资格。Rust 实跑证据来自上述精确源码的 hosted job。最终实现与原生已测源码的 8 份相关文件字节相同；这是一项字节比对，未声称 `7214dfc7…` 自己有 native run。

## 5. 仍缺少的真实输入与验收

有界、只读环境检查在 pocket4 和 ai395 的所检查同 UID 进程及默认/观察到的 fleet 范围内未定位到 live owner 数据库；这不证明其他进程、路径或主机上不存在。desktop 原请求发生超时且没有返回 job identity，状态保留 **UNKNOWN**，未重新发起该执行。已按 host 过滤的任务目录超过 1 MiB；现有 result retention 不支持恢复 process_start 输出。

继续真实采集需要三类具体来源：

1. **原 owner 与部署身份**：实际 AgentId、run/step/attempt、原数据库位置、部署源码/二进制身份和原始记录保管链。
2. **共享到达顺序与 clock domain**：在事件到达时登记的耐久单调游标，明确 host/boot/epoch；覆盖并发、延迟到达和恢复。局部 step 序号和重放时临时编号都不满足这一要求。还需要 native operation/destination 到候选动作、数值特征与目标的映射。
3. **独立效果 observer**：实际执行身份绑定的质量、时间、成本与失败/未知语义，保留观察时点、删失界限及非发生 witness。provider ACK 与 owner settlement 不替代此来源。

取得这些来源后，先冻结新历史上的 shadow 预测，再接入新标签做 held-out 分布评估。连续 observed 模型目前给出质量概率及时间/成本边际；它们不是完整的质量、时间、成本、失败/未知联合后果模型，complete-case 训练也未解决缺失或删失偏差。

代码中已有离散有限支持的 `diag_ssm`；连续 observed-history runner 仍只支持 empirical、MLP、GRU。四模型真实比较、联合分布/观察机制、完整物理账本与前瞻策略试验仍需单独验收。分布拟合改善不自动成为策略收益；额外 rollout horizon 保持在其后。

原有 189/189 fits、181,440 次 optimizer 调用仍属于[此前训练与重放审计](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a3aa398580cbd052f9decbc08af36deea25c6155/qualification/pred-reexecution-20261110-4456/evidence/REPLAY_AUDIT.zh-CN.md)的模拟研究。本轮没有把测试执行数量、模拟 fixture 或 panel 扩大改记为独立真实任务。

## 6. 证据包

`evidence.tar.gz` 保留公开 CI 原始日志、原 artifact ZIP、原始失败及补丁、精确源码 readback、完整本地日志、独立审查和公开安全的来源检查摘要。原始日志仅作无损压缩，原 artifact ZIP 未重打包。私有 host 原始输出未公开。

`MANIFEST.json` 给出每个归档内文件的路径、字节数与 SHA256；`STATUS.json` 给出源码、任务、结果和资格的明确映射。该证据 PR 不改运行代码，也不把其文档提交冒充被测试的实现源码。
