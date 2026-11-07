# NDU 实验执行与有限学习决策：独立审阅结论

日期：2026-11-07。审阅者：`protocol_audit` 子任务。

**已确认本次发现的具体漏账和错误 NoUpdate 路径在当前源码中得到修复。**
此次确认范围是实验输入检查、统计与费用审计、原生纯合同及签名重验；
不构成五任务族真实实验通过、原生 owner 完整接入或模型采用许可。

## 审阅范围

- `scripts/ndu_portfolio/replication.py` 及其回归：完整 fit roster、失败与部分结果、费用覆盖、独立 fit/source 推断和 power 前置。
- `scripts/ndu_semantic_state/execution_gate.py` 及其回归：外部 pins、实际材料 bytes、16 个 provider、评价者声明、成本合同和 actor public 投影。
- `codex-rs/hepta-intelligence/src/learning_decision.rs`、`learning_decision_types.rs`、`learning_decision_tests.rs`：四种结果、预算边界、全部 attempt、retry 因果、现有签名与 qualification 重验。

## 发现与修复复核

| 发现 | 已复核的当前修复 |
| --- | --- |
| failed fit 保留已执行 episode，却可删去 evaluation research attempts 后仍报完整有限研究费用 | `_evaluation_coverage` 在处理完整或失败 fit 前检查全部已保留 episode；缺覆盖时总费用为未知，保留实际已知下界和原始部分结果。旧反例的 7 行 episode／仅 1 条 training attempt 已被覆盖。 |
| evaluation 费用覆盖不足只进入 unknowns，摊销 CI 仍可能用漏报费用计算 | coverage 同时更新受影响的 `incomplete_keys`；相应 profile 研究费用与相关摊销结果传播为 null。 |
| 计划 fit 未启动、原始任务未终态时，接口迫使调用者填写不存在的训练回执或结束时间 | `not_started` 明确保留空执行身份和空原始清单；unresolved attempt 允许 `finished_at=null`，继续阻断科学判断。 |
| shared attempt 失败不进入候选循环，可误报 NoUpdate；先前无关成功可掩盖后来失败 | 原生合同现在扫描全部 shared/candidate attempts，只有签名清单中显式 `retry_of` 的有效成功后继链能够闭合对应失败；禁止未决前驱、跨 candidate/phase、前向引用和重复子重试。 |
| 达到候选数量预算、全评估不合格时，合法预算停止被拒绝 | 候选 cap 纳入预算边界，并要求全部候选已有 qualification，避免仅填满候选清单而跳过评价。 |
| 同一终态在不同校验时钟重验可生成不同 receipt digest | digest 已移除校验时钟，保留冻结 payload、签名、trust 和派生结论；`now` 继续用于 current-use trust/expiry 核验。原 owner 仍必须按 cycle ID 与冻结 payload 幂等消费。 |

上述漏账反例中的金额是合成测试数值，不是实证研究支出。修复未删除失败尝试、
将未知费用改为零或把 episode seed 更名为训练重复。跨 fit frozen 模型身份约束、
全部 20 个 contrast、样本量不足与未完成 fit 的 HOLD 路径也在本轮范围内复核。

## 验证证据的范围

- 本审阅者实际运行 execution gate 的 16 项对抗回归，全部通过、零跳过；最后一次为 4.001 秒。检查使用真实临时文件读取和合成材料，不执行模型或真实实验。
- root 报告 replication 最终 19 项回归通过。本审阅者随后只读确认上述修复与对应测试已进入当前源码，遵循冻结要求未重复运行。
- 原生 owning-crate 执行结果由 native 子任务的原始记录单独提供；本审阅不以代码阅读替代该执行证据，也不将其继承为全仓、全平台或生产验收。

## 仍未关闭的实证与 owner 缺口

1. 五任务族、隔离 train/development/confirmation 来源及 retention panel 的独立真实材料与有效性证明，不能由当前合成 fixture 供给。
2. 16 个真实 provider 的执行、匹配训练调优机会、独立训练重复、输出质量与完整物理成本尚需原始运行证据。哈希固定实现不证明实现已被运行。
3. actor 投影仅输出当前文本和不可变 pixels；它不证明 OS／文件访问隔离、评价者真实独立性，也不能发现已隐蔽编码进输入的目标或未来信息。
4. `CandidateEvaluationAdmissionV1` 按 candidate ID 绑定资格；既有 artifact owner 仍须证明该 ID 对应实际被评价模型的 bytes。终态三方签名本身不能补足这个映射。
5. 必须由既有 Cell journal 与 LedgerWriter 收集并认证原始 starts、attempts、停止、交付、费用和独立 Outcome，完成持久化与下一任务实际消费。当前 Python gate 没有 native authenticator；原生 learning-decision 模块是纯合同，未自行接管这些 owner。

因此 execution gate 的完整静态检查仍返回 **Inconclusive**，科学 gate 仍为
**HOLD**。原生合同可表达 Adoptable／NoUpdate／Inconclusive／Failed；其回执保持
`DENY_ALL`，不生成 V5 零 delta，不放宽 no-op 拒绝或 positive-gain 奖励，也不选择、
安装模型或证明下一任务已经使用 incumbent。

参考基线：[固定 #5198 协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/006e744fbb10a6ee393166eed2e5d1e91f2fab1f/qualification/ndu-text-image-20261106/PROTOCOL.md)、
[#4944 原 owner 合同](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/25fa6d6dd7e1c5c1827a4099f601aee49b2f1b58/codex-rs/hepta-intelligence/src/generation_episode.rs)。
