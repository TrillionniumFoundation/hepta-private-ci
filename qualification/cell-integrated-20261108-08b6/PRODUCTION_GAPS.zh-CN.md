# 普通任务学习闭环：生产接线差距与最短实施路径

日期：2026-11-08。性质：只读源码审查和实施建议，**不是生产执行、学习收益、独立评价、采用或下一任务消费的证明**。

## 1. 结论与证据分层

本轮已经做成的有效阶段是实际 Python `pipeline.run_training_job` 调用点的结果约束和有界子进程监督。本轮基线为 `f2b178bff6955647738d895450d97d229a816b24`；已收到完整 native 候选 `c8642c185209abc0c069414319ccc1b215221147` 的只读源码核查回执。按 root 确认的变更范围，f2b 后这 5 个提交只修改 Python，没有修改 Rust；不能因其他会话的 Rust 文件存在而将本轮候选描述为完整生产闭环。

在现有已核实输入上，我不能给出一个可信的“另加少于 800 行即可完成并实证普通任务全闭环”的承诺。缺口包括实际调用点、原始 owner 能力注入、训练与评价的持久作业、签名域、原始采用与下一任务读取；不是一个泛型接口包装器可以补齐。可以继续编码，但未取得实际能力和工作负载前，应把验收范围限定为具体工程阶段。

| 层级 | 实际证据 | 可以支持的结论 | 不能支持的结论 |
|---|---|---|---|
| 本轮基线 | `858e972109d9/evidence/training-result-bridge-exact-head-supplement.json`：f2b head，tree `a772e5d3f1a90958bad2f56f02a7e72523553652`；精确归档 Python 文件 | 实际 `run_training_job` 有 v2 admission、训练结果和计量校验；`native_owner_authentication=SEPARATE_REQUIRED` | Rust owner 已装配、当前阶段结果有原生 owner 签名、完整学习已执行 |
| 本轮 supervisor | 本目录 `DELIVERY.json`、`supervisor-f2b178.patch`、`qa/r3/run.json`；root 后续 native 最终字节验证另记 | 实际 Python 调用点有界日志、超时、清理、实际退出码与结果约束得到本地验证；没有更改 Rust | 18 个工程测试等同一次真实学习收益，或修补了 Rust 普通入口 |
| 历史 owner 审查 | `858e972109d9/evidence/production-owner-gaps.json` 明确审查的是 `6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5` | 原审查时只有 test ports，protected checkpoint / generation readback 机制存在 | 无条件把旧搜索结果提升为当前 f2b/c864 全仓负面证明 |
| 他会话源码线索 | `/workspace/scratch/fd69122ffc13/source` 是正在变化的选取源码 overlay；`owners-overlay-manifest.json` base 为 `1eb72a1131285f5de98beeb7c95a27eab72d647e` | 下述普通 Circuit 路由及相关机制在所读文件中的源码形态；可为下一阶段复用 | 它已合入 f2b/c864、全部文件共同编译受测、真实 daemon 已加载、生产能力已经提供 |
| 当前完整 native 工作树 | 原始回执 `native-source-audit.json`：HEAD `c8642c185209abc0c069414319ccc1b215221147`，tree `3435dc0f3aef876bc2059b6077eb3ff740e6a3ed`，status 为空；owner 查询 25 行、main 查询 36 行，均未截断 | 该实际候选的可见文本命中只有 test `LearningIterationOwnerPortsV1` 实现、学习 bootstrap 定义和 test 调用；main 命中已有 plasticity/generation 装配，没有学习/Circuit 装配命中 | 正则搜索证明宏展开、别名、代码生成或仓库外 provider 不存在；或他会话 overlay 已进入此候选 |

本审查没有远程操作、签名、注册、训练、评价、采用、提交或推送。负面搜索仅覆盖实际读取的源码集合，不能证明外部部署不存在任何 provider。

## 2. 普通任务的真实入口和已出现的路由

以下路径均相对于他会话 `/workspace/scratch/fd69122ffc13/source/codex-rs/hepta-agentd/src`，**不属于本轮已交付功能声明**。

1. `state_control.rs` 的 `AgentdMethod::ObjectiveStart { request }` 调用原 `ObjectiveRuntimeHost::submit`。
2. `objective_submission.rs` 的 `submit` 进入 `submit_for::<FullObjectiveExecution>`：验证当前 AuthBus issuer、签名、到期和源输入，发布原 durable `RunStartRecordV1`，在执行前重新核查当前信任。
3. `FullObjectiveExecution::execute` 对 compiled objective 调用 `AgentdState::execute_circuit_task_record`。若没有配置 Circuit profile，走原来的普通执行路径；不能把这个 fallback 算作 Circuit 已运行。
4. `state_circuit_task.rs` 要求 `CircuitTaskHandleV1` 与 `AgentdCircuitTaskInvocationProviderV1` 成对存在；provider 构建稳定请求；调用 `submit`。发生 CommitUncertain 只 `readback`，不能重新执行计算。
5. `circuit_task_driver.rs` 的 `CircuitTaskDriverV1::execute` 经原 `AutomationStore` 创建或恢复 bounded Circuit，调用原 `AgentdCircuitCellOwnerV1`，并从原 Cell state owner 重新读取提交记录以构造封闭的 `CircuitTaskReceiptV1`。
6. 只有 Circuit 终局且 unresolved 为零才调用 `provider.publish_result`。该函数契约明确要求持久、幂等发布；它本身**不授予 reward、训练、采用、签名或外部 effect 权限**。

对应启动接线在该 overlay 中已有 `config_circuit_task.rs::with_circuit_task_bootstrap` 与 `runtime.rs` 的 supervised owner / drain，但本地所读 `main.rs` 只有已有 plasticity 和 neuron-generation descriptor loader，没有 Circuit 或 learning-iteration loader / attach。选取源码搜索中，两种 Circuit provider 的具体实现只见 tests，`LearningIterationOwnerPortsV1` 也只见 `learning_iteration_runtime_tests.rs::IterationPorts`。当前 c864 的完整 native 查询另行确认了第 7 节列出的可见命中范围；它没有命中这套 Circuit task provider 或其 bootstrap，不能将上述 overlay 路由归入 c864。

此外存在不能省略的接口边界：Circuit owner 的底座要求 `CellStateOwnerV1`、`NeuronInferenceControlPort`、`CellInferenceReadbackPortV1`、`CellInputEncoderV1`；使用 `NeuronFeatureRequestV1`。已有 `main.rs` 的 Joint process loader 返回 `NeuronGenerationRuntimeHandleV2` / `NeuronGenerationRuntimeBootstrapV2`，采用 `CellGenerationControlPortV2` / `CellGenerationRequestV2`。这些不是同一类型或同一 journal 协议；不能把现有 generation CLI 开关称为 Circuit 的原生模型接线。所读 overlay 中尚未找到可直接用于该 Circuit 的生产 encoder/readback 实现；不能以这个局部搜索断言完整远端仓库也没有。

## 3. 训练、评价、采用和下一任务分别已有什么

| 环节 | 可复用的实际 API / 文件 | 缺少的生产连接或事实 |
|---|---|---|
| 真实经验 | `circuit_credit.rs::circuit_learning_run_id_v1`、`terminal_credit_support`、`append_terminal_credit`；`hepta-learning-ledger/src/production.rs::LedgerWriter` | 执行前把 run/episode 绑定到原 ledger；原 Generator decision 与独立 Observer outcome；完整 executed target 支持。Circuit success 本身不是 reward。不能事后重命名已有 run |
| 真实冻结数据 | `LedgerWriter::freeze_dataset`；`terminal_learning.rs::fit_native` 使用原 ledger snapshot、witness、source policy | 当前数据许可、withdrawal/deletion frontier、原已签 `DatasetFreezePlanV2` 证据和精确 snapshot；普通 JSON 摘要不能替代 |
| 真实训练 | Python `scripts/ndu_real_runtime/pipeline.py::run_training_job`、`training.py`；Rust `AgentdTerminalLearningOwnerV1::train/readback`、`AgentdSharedReplayHostV1::fit_from_source` | Python 缺 durable operation→native job owner 和 iteration-domain attestation。Rust terminal learner 真正拟合 tabular payload，但 job map 是进程内 BTreeMap，丢失后应 CommitUncertain；不是任意大模型/HCSN bundle 的替身 |
| 独立评价 | `neuron_cell_evaluation.rs::freeze_cell_evaluation_plan_v1`、`CellEvaluationRunnerV1::evaluate` / `qualification_bundle` / `qualify_and_persist`；Python `score_worker.py::main` | 原 final-holdout provider/CAS、冻结双方计划、实际两臂 journal、合法独立 evaluator 证据与 durable sink。单独 score_worker stdout 没有当前 iteration 签名 |
| 学习调度 | `learning_iteration.rs::learning_iteration_channel_v1` / handle `submit`；`learning_iteration_ports.rs` 的五个方法 | 实际 production composition 和 ordinary completion trigger；每阶段真实 owner readback。`restore / execute_stage / prepare_proposal / receipt_attestation / checkpoint` 缺一不可 |
| 持久协调 | `learning_iteration_checkpoint.rs::LearningIterationCheckpointOwnerV1::from_registered / restore / checkpoint` | 原已注册 `HostAuthorityFrontierStore<LearningIterationCheckpointRecordV1>` capability 的合法注入。构造 vacant 数据、普通 actor checkpoint、Device/Notes owner 都不等价 |
| 提议 | `learning_iteration_proposal.rs::submit_iteration_proposal_v1` → `state.submit_parameter_plasticity_v1` | 从真实 candidate/evaluation store 构造对应 iteration head 的 payload；当前 anchored ACK。最小固定图阶段只用 Parameter，不引入 Topology。提议成功本身不安装权重 |
| 采用或保留 | 原 generation publication / selector / FinalUse 链；`neuron_generation_learning_runtime.rs` 的 `read_learning_updated_selection` 或 `read_learning_selection` | 原 CURRENT、journal、witness、signed selection、合法 publication 与 previous manifest；不能自己创建第二个 owner 或用 candidate digest 代替实际采用 |
| 下一任务 | 同一 runtime handle 的 `read_learning_updated_next_use` 或 `read_learning_next_use` | 第二个真实普通任务的原 committed intent；更新分支实际采用候选，NoUpdate 分支保留 incumbent 并真实执行不同任务。`RetainedModelNextUse` 也是有效机制闭环，但不是学习收益 |

评价成本另有边界：`CellEvaluationCostScopeV1::TaskLedgersBeforeFinalHoldout` 明确不含随后 final-holdout estimator、签名验证和 publication 的未测成本。不能把这个 cut 的总数称为训练、搜索、验证、失败、恢复与交付全部成本。

## 4. 不能用代码虚构的外部 owner 输入

本地材料未提供下列实际对象；这不等于断言部署方没有它们。

- 原学习 trust root、合法 signed distribution 和前次 protected rollback floor；七个阶段 owner ID、正确 trust digest、当前角色与 controller 分离。`learning_iteration_auth.rs` 验证完整 observation 域，并重新验证恢复后的阶段。其他签名域或新 fixture key 不等价。
- 原 registered iteration Root CAS capability。`from_registered` 只接受既有能力，不注册新 owner、不打开任意 root pathname。
- 原 completed-task ledger、真实可测结果、source policy、当前删除/撤销前沿，以及冻结数据的合法证据。
- 原训练/评价作业 owner，create-once durable operation→job 绑定与 ACK-loss readback；真实签名端点必须读回 owner 的当前结果，不能给调用者提供的任意摘要签字。
- 原独立 holdout custody / CAS / publication sink；不能继续用已经看过的确认集调参，也不能用同一 actor/controller 伪装独立评价。
- 原采用 owner 的 FinalUse、CURRENT、journal/witness、signed selection，和第二个真实任务的 committed use。
- 冻结的图、candidate/baseline 全 bundle、任务族、预算分配和计量覆盖。子训练 660 秒外层限制与整个学习/评价/恢复总预算不是同一概念。

操作员可以执行命令的授权，不会自动生成这些数据面能力对象或合法签名。可以继续查找和接入真实 provider；不能通过删验证、改角色、fresh genesis、伪造签名或重放 operation 填空。

## 5. 最短诚实的实施顺序

完整目标必须依赖同一个冻结候选，按以下依赖顺序推进。

### 阶段 A：让一个真实普通任务进入固定 Circuit

前置：先在完整 native 候选核实是否已有实际 v1 feature control/readback/encoder，以及原任务输入/result owner；若只有 v2 generation owner，先设计并实现明确的协议适配，不得绕过 journal 或复用不对应的 receipt。

具体修改范围：把已审核、可共同编译的 Circuit ingress/driver 接线纳入同一候选；增加一个具体 durable `AgentdCircuitTaskInvocationProviderV1` 和 `CircuitTaskInputProviderV1`，保存原始 semantic input（包括时钟、mask 和 source frontier）供重启 readback；由可信 process bootstrap 装配原 AutomationStore、Cell owner、native control、encoder、fence；在 `main.rs` 选择该实际 profile。

验收：通过原 control socket 提交真实 AuthBus 签名的 `ObjectiveStart`，观察同一个 run 的原 RunStart、Circuit/Cell committed trace、真实模型输出与持久结果；重启或 ACK loss 只读回同一计算。不得直接调用测试 driver 或构造 sealed receipt。**此阶段还没有训练、评价或学习收益。**

若原 v1 native adapter、真实输入来源和能力交付已存在，阶段 A 的最后组装可以较小；目前本地证据不足以承诺其全部实现与真实验证小于 800 行。

### 阶段 B：把真实终局接到学习 owner

在 `publish_result` 的原持久事务/等价受保护 outbox 中发布稳定 completed-result→learning-operation intent；后台监督 lane 消费，调用既有 `LearningIterationHandleV1::submit`。不能在重试时重新生成 operation，也不能把异步训练隐式放进普通请求的成功 ACK。

新增具体 production ports 模块，持有原 checkpoint、ledger、trainer、independent evaluator、plasticity、generation owner 能力。先恢复/校验同一 op，再真实提交或读回；训练超时只 reconcile 原 job。签名由对应真实 owner 对 `learning_iteration_receipt_signing_bytes_v1` 的完整域产生；prepare_proposal 从实际受验证存储中读取。

该阶段不是“新增 StageBackend trait 然后等待别人实现”的工作。缺实际端点就返回明确 unavailable/uncertain，不能返回 canned success。仅完成 checkpoint 和 Selection/NextUse 委托仍是部分工程能力，不能申报闭环。

### 阶段 C：同一冻结候选上的第一次机制闭环

固定图、参数更新，保留真实独立评价产生的 Qualified 或 NoUpdate。按原 publication/selector 路径采用，随后从普通 `ObjectiveStart` 执行第二个不同任务，再用原 generation handle 读回 exact committed use。完整持久检查、签名、终局耗时、失败和恢复都纳入同一预算。一次 NoUpdate 闭环可以证明机制完整，但用户要求的真实增益还需后续独立真实任务对照。

**本轮建议：先完成并冻结已交付 supervisor 的 native 最终验证；只有阶段 A 的真实 native adapter 和输入/结果 owner 被核实存在时，才把新的实现预算投入阶段 A 的最后组装。若不存在，不应为了宣称全闭环追加一个自签泛型 ports 包装器。**

## 6. 证据入口

- 本轮完整 native 原始回执：[native-source-audit.json](native-source-audit.json)。qualification 归档时与本报告同目录保留；本地读取原件为 `/workspace/scratch/08b6dd5f2d10/native-source-audit.json`。
- `/workspace/scratch/858e972109d9/evidence/training-result-bridge-exact-head-supplement.json`
- `/workspace/scratch/858e972109d9/evidence/training-result-bridge-delivery.json`
- `/workspace/scratch/858e972109d9/evidence/production-owner-gaps.json`
- `/workspace/scratch/858e972109d9/evidence/next-production-stage-assessment.json`
- `/workspace/scratch/08b6dd5f2d10/lifecycle-fix/DELIVERY.json`
- `/workspace/scratch/08b6dd5f2d10/lifecycle-fix/supervisor-f2b178.patch`
- `/workspace/scratch/fd69122ffc13/owners-overlay-manifest.json`
- `/workspace/scratch/fd69122ffc13/source/codex-rs/hepta-agentd/src/{main.rs,state_control.rs,objective_submission.rs,state_circuit_task.rs,config_circuit_task.rs,circuit_task.rs,circuit_task_runtime.rs,circuit_task_driver.rs,circuit_cell.rs,circuit_credit.rs,learning_iteration.rs,learning_iteration_ports.rs,learning_iteration_checkpoint.rs,learning_iteration_auth.rs,learning_iteration_proposal.rs,terminal_learning.rs,neuron_cell_evaluation.rs,neuron_generation_process_bootstrap.rs,neuron_generation_learning_runtime.rs}`

## 7. 完整 native 工作树的有界只读核查

在 root 独立的完整 native worktree 根目录运行下列一条命令。它只执行 `git` 只读查询和 `rg`，不创建文件、不启动 daemon、不取得或输出凭证。结果包含实际 HEAD、工作树状态、各查询退出码、原始行数、截断标记和有界命中。搜索保留 test 文件，以便明确区分实现位置。多行 impl 也匹配；出现更多命中时必须继续针对相应路径审查，不能把截断输出当成完整否定证明。

```bash
python3 - <<'PY'
import json
import subprocess

pattern = r'(impl[^;{}]{0,500}(LearningIterationOwnerPortsV1|AgentdCircuitTaskInvocationProviderV1|CircuitTaskInputProviderV1|CellInputEncoderV1|CellInferenceReadbackPortV1|NeuronInferenceControlPort)[^;{}]{0,100}for\b|\b(learning_iteration_channel_v1|with_(learning_iteration|circuit_task|terminal_learning)_bootstrap)\s*\()'
queries = [
    ('head', ['git', 'rev-parse', 'HEAD'], 2),
    ('worktree', ['git', 'status', '--porcelain', '--untracked-files=no'], 20),
    ('implementations_and_calls', ['rg', '-n', '-U', '--glob', '*.rs', pattern, 'codex-rs'], 140),
    ('ordinary_main', ['rg', '-n', 'learning|circuit|plasticity|generation|bootstrap', 'codex-rs/hepta-agentd/src/main.rs'], 80),
]
for name, command, cap in queries:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    lines = result.stdout.splitlines()
    print(json.dumps({'section': name, 'exit': result.returncode,
                      'total_lines': len(lines), 'truncated': len(lines) > cap,
                      'lines': lines[:cap], 'stderr': result.stderr[:1500]},
                     ensure_ascii=False))
PY
```

### 已收到的 native 源码核查事实

原始证据为同目录的 [native-source-audit.json](native-source-audit.json)，由 root 从完整、独立 native 工作树取得。HEAD 为 `c8642c185209abc0c069414319ccc1b215221147`，tree 为 `3435dc0f3aef876bc2059b6077eb3ff740e6a3ed`，工作树 status 为空。owner 查询退出码 0、25 行，main 查询退出码 0、36 行；两组 `truncated=false`、stderr 为空。实际执行版本每文件使用 `--max-count 8`；root 另确认所有实际命中文件均少于 8 次命中，因此该上限没有隐藏本次匹配项。上面的复核命令移除此每文件上限，仅约束展示行数。

在这次文本搜索覆盖的实现和调用形态内：

- `LearningIterationOwnerPortsV1` 的唯一具体实现命中是 `learning_iteration_runtime_tests.rs::IterationPorts`。
- `learning_iteration_channel_v1` 命中其定义及 tests 调用；`with_learning_iteration_bootstrap`、`with_terminal_learning_bootstrap` 只命中 `config.rs` 的定义，没有生产调用命中。
- 两种 Circuit task provider 及 `with_circuit_task_bootstrap` 没有命中。它们在 fd69 overlay 中出现，不构成本轮 c864 的生产接线。
- `CellInputEncoderV1`、`CellInferenceReadbackPortV1` 的具体实现命中均来自 tests/test_support。非 test 的相关 control 命中为 `GuardedCellDispatchV1`、`ReceiptPort` 及 `InferenceControlModelPort` 包装；这些命中自身没有提供 concrete native encoder/readback 后端。
- `main.rs` 36 行命中展示了已有 plasticity 与 neuron-generation descriptor 参数、loader 和 config attach；没有 learning-iteration、terminal-learning 或 Circuit task 装配命中。

这使“本轮 Python 改动尚未提供所需生产 Rust composition / 普通入口学习接线”有了当前完整候选上的直接源码核查支持。它仍然是静态、基于给定正则与文件范围的证据：不能排除宏展开、类型别名、生成源码、间接注册或仓库外嵌入宿主提供实现，也不是运行时探针或任何外部 owner 不存在的证明。f2b 后 5 个提交只修改 Python、没有 Rust 变更的事实来自 root 的提交范围核查；本 JSON 的正则结果本身不充当提交 diff 证明。第 2 至 5 节的 overlay 定位与设计仍仅用于下一阶段实施参考。
