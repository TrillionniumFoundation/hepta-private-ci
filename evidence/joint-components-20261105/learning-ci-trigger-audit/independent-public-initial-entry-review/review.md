# H3 public-initial-v2 自动学习入口的独立静态复核

**结论：这条工作流在当前前置条件通过后，可以启动新的真实训练和评估。第一条 `hepta-neural-study-v1.yml` 因 v1 输入缺少快照而拒绝的结论，不能迁移到这里。** 本次只读复核没有运行模型、训练、Cargo、桌面任务或远端归档下载，也没有创建 PR 或改动工作流。

精确基线是 Hepta `6db78eca53a5acdda0d96873d3f4cd65863426f0`，tree `e91f5994017fc5d2cfe58d405a20ee6ad9376772`。本审查独立从该 SHA 读取下列六个文件，逐一计算原始 Git blob 与 SHA-256，并与 W1 先前取得的 H2 字节比较；六项均一致。完整原始 API 响应、字节副本和哈希在本目录的 `exact-h3-six-source-binding.json` 中，未依赖“分支大概没改”的推断。

| 精确文件 | Git blob |
|---|---|
| `.github/workflows/hepta-public-initial-v2.yml` | `3209f566da96507870e20485fe85ddde9e2f349d` |
| `codex-rs/hepta-infer-worker-host/src/smollm_public_initial_loop_tests.rs` | `2fed3bf8fe916f67c2608906c54e175a459d4a43` |
| `scripts/hepta_smollm_observed_execution_v1.py` | `26d33f9c4e314646abd874389075fe8bcfe4eed5` |
| `scripts/hepta_smollm_three_rounds_v2.py` | `d2524102e018af48e4e5b54e22f616581e070491` |
| `scripts/hepta_smollm_descendant_v2.py` | `f08a2229c53c0f88fb5422a9ab70f7de9970f8a4` |
| `scripts/hepta_smollm_answer_eos_research_v3.py` | `aa0a8b21da09a30cedf49406a7f93eb1236435e8` |

## 触发和输入边界

工作流注册 `pull_request` 和 `workflow_dispatch`，PR 路径包含 H3 实际修改的 `codex-rs/hepta-agentd/**`。文件内没有 draft 排除条件、job `if` 或批准 environment；本审查没有审计 GitHub 仓库级权限或外部批准规则，因此结论是**源码存在可达的自动入口**，不是断言每个 PR 必定执行成功。该 job 使用 `ubuntu-26.04` 和原 360 分钟总上限。其原配对仍是 `hepta-integrated-chain-execution-v11`、三个 Chain checkout 都固定到 `cfa57cd04751427451302b5c10539b3984d7f8db`，不能把它与本轮 C4 联合运行混成一个候选。[工作流触发和环境](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/.github/workflows/hepta-public-initial-v2.yml#L1-L60)

材料步骤明确写入 `schema="hepta-smollm-neural-native-check-v2"`、`runtime_snapshot` 和该文件的实际 SHA-256。此前还在新环境安装原锁定 wheel 闭包并调用现有 snapshot `record`。所以 Rust 的严格输入加载仍然有效，但“缺快照字段”这一确定拒绝不在此工作流发生。真实源、材料、运行时、父模型、sandbox 和普通入口仍可能拒绝；不能把可能发生的前置失败当成防止新试验的持久策略。[运行时和输入生成](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/.github/workflows/hepta-public-initial-v2.yml#L283-L331)

## 真实训练调用链

| 阶段 | 原条件及预算 | 源码实际动作 |
|---|---|---|
| 普通入口 | materials 成功；900 秒、至少 2 个测试 | 以 `--run-ignored only` 执行真实普通推理、撤销和重开控制。 |
| 三轮候选 | `!cancelled()` 且 ordinary 成功；11100 秒、至少 1 个测试 | Rust `for round in 1..=3` 调用 `train_round`，启动固定 observed 脚本；后者直接调用 `rounds.run(args)`，再进入 `trainer.run(operation="train")`。 |
| 后代诊断 | `!cancelled()` 且 ordinary 成功；9000 秒、minimum-tests 0 | 新建 campaign，从空 lineage 开始，循环三次调用同一个 `rounds.run`，后两轮使用本 campaign 刚生成的候选和训练回执。 |
| answer-EOS 研究 | 原 outcomes/lint 等成功，且 ordinary、proposal_rounds 成功；1800 秒、minimum-tests 0 | 验证原 gate、源和普通 readback 后，以新的 research profile、round 1、空诊断 lineage 再调用 `rounds.run`。 |

后代步骤的条件没有要求 proposal_rounds 成功，但它读取三轮普通入口生成的 `ordinary-0` 文件；缺少该文件仍会拒绝。这是实际数据前置，并非跨运行消耗额度检查。两条 Python 阶段的 minimum-tests 0 也不代表零模型工作。[原四阶段命令与条件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/.github/workflows/hepta-public-initial-v2.yml#L323-L394)

Rust 每轮的 owner guard 是 2700 秒，回执明确 `all_phase_worst_cases_covered=false`。observed 路径仍核原训练阶段 1800 秒 / 16 GiB、评估阶段 600 秒 / 8 GiB；不能把这些局部额度相加后声称整个 campaign 保证能完成。五个实际 artifact 中，candidate、fresh-budget-matched-lora 和 budget-matched-full-tune 必须匹配计划的训练步数与 token schedule；current-backbone 和 randomized-rank-matched-lora 要求零梯度步，不能把“五个角色”写成“五个梯度训练”。[Rust 进程与循环](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/codex-rs/hepta-infer-worker-host/src/smollm_public_initial_loop_tests.rs#L121-L300)、[observed 入口与预算](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/scripts/hepta_smollm_observed_execution_v1.py#L46-L170)、[实际 train 调用与角色核验](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/scripts/hepta_smollm_three_rounds_v2.py#L399-L555)

## 新试验与已有资格的区别

每次 CI 使用新的 `$RUNNER_TEMP` 输出根；每轮用 `output.mkdir(..., exist_ok=False)` 拒绝覆盖同一路径。所读六个入口没有导入或对账先前运行的 spent ledger。后代 lineage 是本次 campaign 内创建、逐回执核验的父子训练历史；它不是跨 campaign 的预算或 holdout 消耗账本。这里的结论限定在已读入口和参数，不虚称已审计全部外部 trainer 实现。[源、快照、父模型和新目录检查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/scripts/hepta_smollm_three_rounds_v2.py#L85-L240)、[新后代 campaign](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/scripts/hepta_smollm_descendant_v2.py#L25-L124)、[新 research 调用](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/scripts/hepta_smollm_answer_eos_research_v3.py#L210-L333)

原代码保持 `CURRENT`、不安装 child，并记录 `product_qualification=false`、`independent_future_quality=false`、仅 per-round budget matching 与累计预算未匹配。这些都是必须保留的资格边界；它们不阻止训练已经消费算力、材料或评估机会，也不能自动授权再开一轮。此处明确有**真实执行入口**，没有因此获得隐藏／未来任务、长期质量、完整模型或发布资格。[三轮结果的实际限定](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6db78eca53a5acdda0d96873d3f4cd65863426f0/scripts/hepta_smollm_three_rounds_v2.py#L680-L740)

父线程已决定保留 H3 冻结分支和 compare 供审阅，暂不打开 PR，不修改或跳过任何原 CI，不开启新学习试验。已授权的 H3 本地原生门禁是另一个运行边界，继续按冻结计划执行。历史 H2 的 skipped 记录只描述那一次历史运行，本报告不以其推断 H3 会跳过；本报告也没有声称上述学习阶段已经实际发生。
