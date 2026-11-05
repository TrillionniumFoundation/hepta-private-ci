# Chain sole-plan 文档 PR 的触发边界：独立只读审查

**仅改计划文档仍会执行原 CI。** 在精确源码 `0e1c25d42fff22bec6ec2a08c4fbdff240229858` 的 19 份工作流中，有 5 份对 `pull_request` 不设路径过滤。它们会进入原编译、协议／模型机制测试和成本采集，不能描述成“零 CI”或“没有任何模型计算”。本审查未执行其中任何命令。

本结论只适用于父线程已确认的 **stacked review PR**：从发布时刷新后的 `#688` head 建立新文档分支，base 为 `fix/chain-six-axis-performance-20261103`，完整 PR diff 只有 `docs/development/TRNM_AI_NATIVE_BLOCKCHAIN_DEVELOPMENT_PLAN.md` 这一文件的追加。不适用于把现有整条代码分支对 main 打开 PR，也不以“最后一次 commit 只改文档”替代完整 diff 核验。当前 0e1 是静态审查快照；发布前如 base/workflow 字节改变，需重新核这些条件。

## 19 份工作流的完整分类

| 类别 | 数量 | 对该单文件 PR 的结果 |
|---|---:|---|
| PR 无路径过滤 | 5 | 具备触发条件；各 job 的原条件和前置仍适用。 |
| PR 有路径过滤 | 12 | 所列路径均不匹配该 sole-plan 文件。没有为本审查修改任何过滤器。 |
| 仅指定分支 push | 2 | 新文档分支和该文档路径不匹配；其中一条为 SmolLM once。 |

5 份会具备 PR 触发条件的文件是：

| 原工作流 | 原动作及边界 |
|---|---|
| `codeql-analysis-export.yml` | 同仓 PR 读取已有 CodeQL 分析；exporter 的 HTTP 方法明确是 GET。 |
| `pon-original-large-state-cpu.yml` | 两架构、head/prospective-merge 的原 release 大状态和 reactor-exit 测试。 |
| `pon-original-workspace-large-state-cpu.yml` | 两架构完整 workspace test-profile 构建，随后指定状态／增长测试。 |
| `pon-priority-acceptance.yml` | 两架构、head/prospective-merge 的 service-model/state/history 三 campaign；包含原模型机制 fixture、服务和状态负载。 |
| `trnm-required-baseline.yml` | 仓库／协议／fuzz／完整 Rust shards、外部证据校验、两架构成本和 W1 reuse 原采集。 |

完整事件、路径、job 条件、runner、timeout、Git blob 和原始 SHA-256 在 `workflow-inventory.json`。所有 19 个文件均直接由 exact 0e1 获取并按目录清单逐项核对，共 335777 字节；不是只检索几个工作流名字。[精确工作流目录](https://github.com/TrillionniumFoundation/Trillionnium-Chain/tree/0e1c25d42fff22bec6ec2a08c4fbdff240229858/.github/workflows)

## 新的已登记模型试验和原单元控制应分别记录

明确的真实 SmolLM once 工作流 `pon-smollm-hosted-once.yml` **没有 PR 事件**。它只接受 `fix/chain-model-owner-hosted-once-20261105` 分支 push，并要求 `config/pon/hosted-model-intents-v1/*.json` 路径变化，再调用 `llm_hosted_once.py validate/execute`。上述新文档分支和 sole-plan 路径两项均不满足，不能因其文件存在就说文档 PR 会开启该已登记试验。[原 once 工作流](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/.github/workflows/pon-smollm-hosted-once.yml)

另一方面，无路径过滤的原基线确实执行 `test_llm_hosted_once.py`、`test_llm_runtime_pilot.py`、parent-step 和模型生命周期测试。本审查顺着调用查看了入口及相关控制，不能仅凭 test 文件名把它们当成无副作用：

- `test_llm_hosted_once.py` 的允许路径把 `hosted.command` 和材料下载替换为明确的 `no_execution`／mock；拒绝路径核它们未调用。其 Git 仓库与 ledger 是临时 fixture。[原控制](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/scripts/ci/test_llm_hosted_once.py#L31-L114)
- `PilotRunAdmissionTests` 在临时 SQLite 中测试 reserve/debit/失败保留，`runtime.supervise` 被明确替换；跨进程 replay 使用声明为 fixture 的模型回执。它们不加载本次真实已消费试验的 ledger 路径。[原 admission 控制](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/scripts/test_llm_runtime_trial_ledger.py#L221-L298)、[replay 范围](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/scripts/test_llm_runtime_trial_replay.py#L1-L90)
- 原 Rust `model_evidence_v3`／`model_composition_v4` 的正例会在 25 条已经公开的历史 policy rows 上执行确定性 perceptron 计算。该执行是真实机制测试，源码明确不主张未来质量；本报告绝不写成“没有训练算法运行”。[empirical fixture](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/trillionnium/crates/trnm-pon-node/tests/model_evidence_v3.rs#L1-L133)、[composition fixture](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/trillionnium/crates/trnm-pon-node/tests/model_composition_v4.rs#L1-L150)
- 某些 tensor 控制需要显式 `TRNM_ACTUAL_DECODER_TENSOR_TESTS=1`；当前工作流和主 `ci_job.sh` 未设置它。其源码仍是本地 tiny projection／tiny untrained Llama，没有预训练权重或新质量结论。不能把其存在与真实 public pilot 混同，也不能对本次未执行的控制记 PASS。[tiny 源码](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/scripts/test_llm_base_material_torch.py#L1-L88)

在这 19 份工作流和已核的主入口中，没有发现对 Hepta 的 repository/workflow dispatch、跨仓可复用 workflow 或新的 SmolLM pilot 直接调用。所有 workflow `uses` 为固定官方 Actions，CodeQL exporter 使用 GET。这里限定为已读源码入口：没有审计仓库外部 webhook、GitHub App 或全部依赖内部行为，因此不把它写成所有外部自动化的全局证明。[required 基线](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/.github/workflows/trnm-required-baseline.yml)、[原 ci_job 调用表](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/scripts/ci/ci_job.sh)、[GET exporter](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/0e1c25d42fff22bec6ec2a08c4fbdff240229858/scripts/export_codeql_analysis.py#L47-L92)

## 交付和未发生的动作

本目录保存 49 个精确源码文件、原始 API 响应和分组哈希清单。只做解析、源码阅读及报告生成，没有执行被审脚本、Cargo、模型、CI、native 或远端 bulk 下载，没有新增／修改源文件和 workflow，也没有打开 PR。H1 下载维持暂停。

早期对 main 的 compare 请求实际返回 GitHub 422（diff 生成过长），原响应保留；此请求没有证明任何完整 diff，且 main 已不在最终发布目标内。一个临时打印工具曾有 Python 括号 SyntaxError，修正后继续只读打印；它不是项目测试失败，也不计门禁。另一个按名字猜测的 `scripts/project_preflight.py` 取回 404，随后按实际 shell wrapper 读取正确的 `scripts/ci/project_boundary.py`。这些均不影响 19 份工作流的完整字节核验，也没有运行项目代码。
