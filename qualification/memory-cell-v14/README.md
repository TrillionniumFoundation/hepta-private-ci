# Memory Cell V14：独立服务、真实模型与完整结果

本目录实现并执行六项工作：依赖隔离、实际候选路由、完整成本实验、Transformer 参数记忆、结构分裂/合并评估，以及 Rust owner 的原生读取与冷迁移。研究分支是 `research/memory-cell-v14-20261031`，审查入口是 [PR #4541](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4541)。

这里区分三种结果：代码行为通过验证、实验观察到改善、研究假设获得支持。完成实现或 CI 成功，不代表所有研究假设都通过。候选模型失败、基线获胜、旧实现错误和失败探索成本均保留。

## 验收状态

| 工作项 | 已实现 | 当前证据与边界 |
|---|---|---|
| P0 依赖隔离与有效回退 | 稳定 skill cell、按项目独立更新、当前合法来源回退、原生多 cell 服务 | Python 三个项目训练种子均通过 7 项行为检查。项目更正/候选拒绝不使其他技能失效。被撤销的来源拒绝读取。skill parent 明确固定为已合格的 seed 713，并非三个独立技能模型均成功。 |
| P0 实际路由与评分 | 覆盖、专家内部预测、跨专家校准分开评估；14 个候选均有资格；选中 checkpoint 可恢复并执行 | 校准选中 centroid；新 72 条任务上三个种子均 68/72，continue 为 67/67/66。小幅实际改善成立于本次观察；跨专家校准仍有失败，不声称稳定的总体收益。 |
| P0 完整成本正收益 | 反复使用语义技能任务、14 个可实施模型、统一执行器、成本账及敏感性分析 | 原始语义试验未达到验收；MiniLM ridge 为最强对照。测试项目名携带类别编号的问题被保留并修复；配对复核仍是 MiniLM ridge 84/96、LoRA 35/39/58，未通过。不能把胜出的对照事后改称预先指定的成功方案。 |
| P1 真实语言参数记忆 | 固定真实预训练 BERT Tiny；attention Q/V LoRA；特征模型、快速权重、精确/词法检索；参数干预及恢复 | 参数确实承载新绑定知识；精确事实任务仍是 KV/BM25 更准且更便宜。组合由共同执行器完成，不能声称模型学会了执行算法或获得任意新实体的零样本事实。 |
| P1 有收益的分裂/合并 | 完整 router + 子模型 + 校准器成本；继续训练、等子模型容量、固定/随机分组及合并对照 | 21 个结构候选全部未获准。依赖隔离带来的可用性收益属于固定分组控制，不能归功于自发分裂。 |
| P1 原生闭环及节点迁移 | Rust owner、已有 inventory recall/control、SQLite、签名 artifact、独立发布与回退；双 OS 进程的 TCP 冷迁移测试 | 最终精确源码 CI 41262757641 的 16 项原生生命周期/回归测试通过，fix/fmt 后源码零变更。迁移使用同一主机的两个进程，不能等同于不同物理节点，也未把 Python BERT LoRA 服务接进 Rust 推理。 |

## 1. 依赖隔离与当前来源回退

`isolation.py` 复用 V13 的真实 Adapter 和 SQLite SourceOwner。技能参数从干净的 skill 来源训练，项目事实各自训练和发布，保留完整来源依赖。没有从混合祖先模型中删掉依赖标签来伪造隔离，也没有把旧参数中学过的事实宣称为已遗忘。

读取明确返回 `learned`、`fallback` 或 `refused`。项目模型缺失、过期或候选未通过时，回退读取 owner 当前仍合法的来源；撤销来源不能回退。更正一个项目后，其他项目及技能 artifact、输出和服务模式保持不变。技能没有精确事实回退来掩盖模型错误。

三组项目种子 713/971/1237 使用同一个合格技能 parent 713。校验期间技能正确数保持 59/72；项目事实为 12/12。更正/小更新被拒绝时，84 条合法请求中 80 条走模型、4 条走当前来源；全部 84 条得到服务不等于全部答对。撤销项目 amber 后，其 4 条请求拒绝，其余 80 条继续服务。完整更新与重启恢复都保留参数、Adam、RNG、sampler 和来源身份。

原始本地尝试曾让三个种子各自训练技能 parent，其中 seed 1237 的校准为 39/48，低于原有 40 的门槛。该失败没有被删掉。完整 56 个原始文件、失败 checkpoint、数据库和实际执行源码保存在 [local-isolation-initial](evidence/local-isolation-initial/README.md)。正式协议随后明确采用固定的已合格 skill parent；这些项目种子不构成三个独立技能泛化实验。

## 2. 真实路由结果与可调用的选中策略

原始路由实验在首次运行前冻结：[源码 b020a9b](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b020a9b1648513ed7cb4edfbca6893c2b9ec99d4)、`ROUTING_PROTOCOL.json` 和 `routing_holdout.json`。训练 120 条、校准 48 条使用旧集合；72 条新域内请求和 12 条 OOD 请求只用于最终评价。校准阶段通过分层交叉拟合选择，选定候选后才读取新测试结果。

| 实际系统 | seed 713 | seed 971 | seed 1237 |
|---|---:|---:|---:|
| 校准选中的 centroid | 68/72 | 68/72 | 68/72 |
| continue / merge_retrain | 67/72 | 67/72 | 66/72 |
| ridge | 67/72 | 67/72 | 67/72 |
| nearest | 65/72 | 65/72 | 65/72 |
| BM25 | 50/72 | 50/72 | 50/72 |
| fixed calibrated | 67/72 | 68/72 | 65/72 |
| gradient calibrated | 66/72 | 62/72 | 66/72 |
| random calibrated | 61/72 | 64/72 | 58/72 |
| 等子模型参数容量 wide | 63/72 | 65/72 | 64/72 |

这三个种子重复评价同一批 72 条请求，不是 216 个独立任务。centroid 相比 continue 仅多答对 1–2 条，不能据此宣称总体统计优势。novelty 门槛接受 71/72 域内请求，保留其中 68 条正确结果，拒绝 9/12 OOD；它不是已校准的正确率概率。

梯度分组的 oracle 为 72/71/72，但真实校准系统只得到 66/62/66。top-2 没找到本可答对的专家分别有 2/0/0 条；已经找到却跨专家排错的有 4/9/6 条。实际进步来自让普通强对照参与选择，不能把它表述为专家校准已成功。

`selected_routing_policy.py` 让选中的系统真正可调用。它验证原始 artifact inventory、编码器、训练来源版本、冻结 runtime 源码和 checkpoint 字节；不读取 held 结果，也不重新选择模型。全部 14 个候选族均可从保存状态恢复。数值数组使用 `allow_pickle=False`。`predict_text` 真实调用匹配的编码器；`predict_cached` 明确标为原始特征回放；执行器只接收预测操作和调用者的新 payload。该研究 API 不构成原生安装或当前授权证明。

实际新查询探针 [CI 41261014074](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41261014074) 已通过：加载原 centroid，真实编码 1 条预先固定的新措辞（19 tokens，无截断），处理新 payload，返回 `unique_stable` 和 `[iris, cedar, oak]`。编码 6.57 ms、策略决策 0.160 ms、执行器 0.031 ms；模型冷加载约 342 ms，整进程约 0.794 s，peak RSS 265,166,848 bytes。这是一条真实运行的集成探针，不计为额外泛化样本。

完整第一轮证据：[CI 41259326679](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41259326679) 和 [INDEX](evidence/ci-41259326679-1/INDEX.json)。所有候选、未选中的 checkpoint、校准探索及完整子模型都在分块归档中，未用 oracle 决定上线候选。

## 3. 真实 Transformer 参数记忆

`language_models.py` 使用固定的 `google/bert_uncased_L-2_H-128_A-2`，revision `30b0a37ccaaa32f332884b96992754e246e48c5f`，并验证实际 safetensors 文件身份。LoRA 在两个 Transformer 层的 Q/V projection 上训练，rank 4、alpha 8，冻结 backbone；没有用随机初始化模型替代预训练模型。

九个对照包含精确 KV、BM25、词法 ridge、冻结特征 nearest/ridge/fast weights/linear/MLP，以及真实 attention LoRA。新事实和新实体绑定在预训练结束后随机生成；第二写入阶段新增实体，评价未见措辞及组合调用。所有方法获得相同记忆信息，执行相同已知程序。未知实体在未写入前没有可推断的随机事实。

| 任务/干预 | seed 17 | seed 29 | seed 43 |
|---|---:|---:|---:|
| 事实绑定：LoRA | 164/192 | 161/192 | 174/192 |
| 事实绑定：关闭 LoRA，保留训练后的 head | 32/192 | 24/192 | 37/192 |
| 事实绑定：精确 KV / BM25 | 192/192 | 192/192 | 192/192 |
| 程序绑定及组合：LoRA | 95/96 | 95/96 | 96/96 |
| 程序绑定：关闭 LoRA，保留训练后的 head | 31/96 | 22/96 | 24/96 |
| 程序绑定及组合：精确 KV / BM25 / 词法 ridge | 96/96 | 96/96 | 96/96 |

关闭参数后表现明显降低、重置训练参数后接近低基线、恢复后参数及 optimizer hash 一致，支持“新知识确实进入训练参数”这一有限结论。它不支持“参数比原始事实存储更小或更便宜”：事实 LoRA 的独立持久化状态约 18.19 MB，精确 KV 约 10.99 KB；LoRA 读取约 2 ms，KV 约数微秒。本任务中强对照更准、开销更低。

第一轮语言运行遇到 Hugging Face `BatchEncoding` 不属于内置 `dict` 的实际错误，修复为 `collections.abc.Mapping` 后原协议原参数重跑。失败运行和成本保留。成功证据：[CI 41259642195](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41259642195)、[完整归档](evidence/ci-41259642195-1/INDEX.json)。

## 4. 反复使用的语义技能与完整成本

详见 [SEMANTIC_RESULTS.md](SEMANTIC_RESULTS.md)、`semantic_protocol.json`、`semantic_prior_costs.json`。本轮额外纳入强 MiniLM nearest/centroid/ridge，而不是只和弱检索比较。任务使用原 120 条训练、48 条校准、96 条新请求、12 条显式程序组合；相同 task executor 单独计费，候选用校准选择训练步数和超参数。

主设定为 1,000 次重复读取、1 小时保存，并列出 1/10/100/10,000 次读取的敏感性分析。下载、冷加载、训练、所有候选校准、恢复、查询、执行器、来源/回放及 checkpoint 占用均有记录。进程 wall/CPU/RSS 是实测；网络计数是 runner 所有接口变化，含其他流量，不伪装为精确模型传输成本。能源、实际云账单及未测的历史开发成本不能填零。

原始新语义试验的 MiniLM ridge 为 85/96；LoRA 为 31/33/55 of 96。项目名中类别编号的构造缺陷在分析时发现，原始数据和结果完整保留，修复只改变无关项目 ID。修复后 [CI 41261379136](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41261379136) 的 MiniLM ridge 为 84/96、词法 ridge 为 81/96；LoRA 为 35/39/58、MLP 为 64/60/67、fast weights 为 55/40/59（各96），仍未达到验收。

这次修复是同一 96 条文本的配对复核，不是额外独立留出集；模型源码、训练资料、候选选择、校准输出、训练步数和超参数均未改变。然而九个神经模型的参数/optimizer tensor hash 并非逐位相同，训练 loss 差异最大约 4.77e-7。跨 runner 浮点差异是解释假设，尚未独立证明。因此不能把成绩的变化全部归因为项目 ID 修复；可靠结论是两轮指定候选都明显落后强对照。

## 5. 分裂与合并的结果

`structural_gate.py` 对已有证据进行事后审计，保留校准选择，不使用测试结果重新选模型。报告要求结构候选相对继续训练、等子模型容量单模型、固定分组及普通强对照具有实际收益，并具备候选绑定的保留能力和完整成本证据。它是研究发布前置条件，不是 owner 的安全授权机制，也不是提前注册的新试验。

最终 [结构与依赖审计报告](evidence/structural-admission/REPORT-v4.json) 使用同一原始 CI 的逐字节证据，21 个结构候选全部拒绝。子模型总参数 23,052 与 wide 的 23,052 相匹配，但 router 与校准器还需要额外 1,162 个系数。不能把 child-only 容量称为整个系统的等容量。合并采用原来源合集重新训练，不进行不可靠的参数平均；此次与 continue 控制一致，没有独立收益。

固定 skill/project 隔离在来源更正后提高服务可用性，这个收益属于固定依赖边界，不能拿来证明学习到的梯度分裂更优。原 V13 在两个更正 frontier 上 84 条请求全部被阻断；新固定隔离结构能服务 84 条，其中 71 条正确。旧完整训练剂量与新小候选训练剂量不同，此比较仅证明可用性行为，不能声称训练效率的配对因果增益。

## 6. Rust owner 与冷迁移

主要实现：

- `codex-rs/hepta-agentd/src/memory_isolated_service_v14.rs`：有界独立 cell 集合、请求内按依赖选择、当前来源回退、发布与来源返回前校验。
- `memory_inventory_runtime.rs` / `memory_inventory_execution.rs`：接入原有 Agentd runtime/control/recall 路径，保留真实 model/source/mixed provenance。
- `codex-rs/hepta-cognitive-types/src/memory_inventory.rs`：显式 V14 readout schema 支持合法 source fallback，原 V1 规则不被放宽。
- 独立服务、来源更正、撤销、拒绝和返回前 fence 测试；双进程测试走真实 SQLite、签名 artifact owner 和 Agentd control client。

双进程测试在第一个进程执行来源写入、真实 f32 SGD MLP 训练、发布、读取、更正、回退及再训练。关闭并回收进程后，通过 loopback TCP 传输关闭状态的 SQLite、artifact 和 checkpoint，并验证长度与摘要；原路径随后不可用。第二个进程依赖完整 recovery anchor、原 manifest 身份和 fresh admission/selection 恢复，继续读取、执行、再更正及撤销。

自然语言 resolver 在此控制流程测试中明确使用 oracle 测试接口，不作为语言准确率证据。迁移为同主机的不同 OS 进程，不是两台物理机器；训练模型为原生 MLP，不是 Python Transformer。读取使用返回前校验，不宣称跨节点原子事务。现有 `finish_read` 仍绑定完整 owner cut：请求进行期间，无关来源的并发写入也可能使该次读取返回 Stale；完整 owner snapshot 和启动时 registry 探测仍是共享故障边界。隔离验收覆盖更正完成后的顺序读取和选中依赖的正确性，没有证明任意故障下都不影响其他请求。运行仍为显式选择的 research runtime，不构成生产激活。

专用 CI 先执行限定 crate 的 `just test`，再执行 `just fix` 和 `just fmt`。如果最后两步改动源码，保留完整 patch 并拒绝把旧测试结果归到新字节；新提交再进行一次完整验证。原始编译错误和后续修复的源码、日志均归档。首次完整 16/16 通过的 [run 41262098419](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41262098419) 在 `fix` 后没有源码变化，随后 `fmt` 产生了机械格式变更。变更经逐文件 Git blob 验证后提交为 `028dd43e78220ce2ea3a6836672d77678219a98b`，最终独立校验是 [run 41262757641](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41262757641)。**该最终运行已经通过**：16/16 要求的测试实际执行且全部通过；`just fix` 与 `just fmt` 均 exit 0，`after_fix_changed_tree=false`、`after_format_changed_tree=false`，`passed=true`。570 个其他测试被本次限定过滤器排除，验证范围是上述生命周期及回归案例。完整 [receipt](evidence/native-41262757641-1/readable/memory-v14-native-028dd43e78220ce2ea3a6836672d77678219a98b-41262757641-1/receipt.json)、[双进程实际结果](evidence/native-41262757641-1/readable/memory-v14-native-028dd43e78220ce2ea3a6836672d77678219a98b-41262757641-1/native-two-process.json) 和 [INDEX](evidence/native-41262757641-1/INDEX.json) 已保全于提交 `5718401f191ab41627b155a39a8cc8aea5ce91aa`。

## 复现与证据保存

轻量契约检查可分别运行：

```bash
python qualification/memory-cell-v14/isolation_tests.py
python qualification/memory-cell-v14/routing_tests.py
python qualification/memory-cell-v14/language_checks.py
python qualification/memory-cell-v14/semantic_checks.py
python qualification/memory-cell-v14/structural_gate_tests.py
python qualification/memory-cell-v14/selected_routing_policy_tests.py
python qualification/memory-cell-v14/dependency_receipt_audit_tests.py
```

本轮轻量契约检查合计 40 项：isolation 5、routing 6、language 5、semantic 7、structural 7、selected policy 7、真实依赖 receipt 审计 3。各自运行记录与真实模型实验分开保留；这些契约检查不计为泛化任务。

真实模型依赖、固定版本、完整训练命令、source freeze 和 always-preserve 行为定义在 `.github/workflows/memory-cell-v14-{research,semantic,native,selected-policy}.yml`。`.github/workflows/memory-cell-v14-reports.yml` 只从原归档中验证并提取字节，不重新训练或评价。

原 CI 隔离过程共用时 17.694 s、CPU 17.592 s；全部 30 个候选（包括 9 个拒绝候选）均保留，checkpoint 总计 7,510,599 bytes，其中拒绝候选 2,260,037 bytes。原始 routing command 用时 10.527 s、CPU 10.478 s；这不包含环境安装及此前模型下载，不能把它称为全部部署费用。组件计时不再重复加到整进程计时上。

每个分块归档的 INDEX 保存整包、每个分块及每个原文件的 SHA-256/字节数。先校验再提取；`readable` 只是相同原始字节的便于审查副本。新证据追加到独立 run 目录，不覆盖失败。结构审计、恢复回放和单条新查询探针不能替代原始效果实验。
