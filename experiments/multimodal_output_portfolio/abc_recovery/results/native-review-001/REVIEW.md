# 原生 Hepta owner 资格：独立只读审阅

## 1. 范围、当前文档身份与结论

本轮 Python A/B/C、媒体资格和成本证据**没有自动闭合原生 Hepta 的资格缺口**。旧 Neuron 的实测拒绝、空 journal 和缺少 acknowledged checkpoint 继续成立。成功执行研究清单、工程重放、拒绝路径或本地签名不等于获得生产 owner 权限。

本审阅未运行新的模型、校准、Rust 测试、owner 激活、proposal 或参数更新，未修改生产契约、旧证据或已封存的 A/B、C、成本证据目录。只读范围为既有 GATES/DESIGN、六份已知 owner 回执及关联说明，随后通过 GitHub connector GET 读取明确指定的三份当前文档。没有扩大到全仓审计。

GitHub 文档固定在仓库 `TrillionniumFoundation/hepta-private-ci` 的提交 **`73d0ae78e46a19cca7a6b616715cd91ecb9d9b8f`**，该提交来自 `research/ndu-abc-recovery-20261024`。没有依赖浮动分支名解释“当前”。原始返回正文已按原字节保存；请求 URL、ref、路径、SHA-256 和 Git blob SHA-1 见 [FETCH_METADATA.json](FETCH_METADATA.json)。

| 已核实的确切仓库路径 | 本地原文副本 | 原文 SHA-256 |
| --- | --- | --- |
| `codex-rs/hepta-infer-worker-host/GENERATION_NEURON.md` | [GENERATION_NEURON.md](contracts/GENERATION_NEURON.md) | `e4b1b3fc5e2cf0f978e988d5a07e86012738976497d7032007c9134935cdd3ab` |
| `codex-rs/hepta-infer-worker-host/GENERATION_EXECUTION.md` | [GENERATION_EXECUTION.md](contracts/GENERATION_EXECUTION.md) | `4838496ae5ecf43cb5a8fc139b830c4546a908cbc378ba6bfc46742b924085d2` |
| `codex-rs/hepta-intelligence-eval/PAIRED_FULL_INFORMATION.md` | [PAIRED_FULL_INFORMATION.md](contracts/PAIRED_FULL_INFORMATION.md) | `3089d67ee091ba74cf6c38f118bd729fdcad91234902ae9526e52c8ad49cb3dd` |

先前 shell 的 promisor fetch 因代理连接失败而不能读出这些正文；GitHub connector 随后成功读取，**三份文档的读取缺口已解决**。这不是重新执行 Rust 或重新认证 native qualification。正文计算出的 Git blob 身份分别为 `3b258b8dd7d4628828af2c3d7d7f9947f3048651`、`579d01989683d3ed7dd9a9e8e328bc8bc2d09563`、`b8faf7c3b9fb12df91da1b5493722c8ffd24d390`，与先前已知 blob 标识相同。

当前三份文档与旧回执的证据边界一致：Neuron 校准是 measured NO-GO；没有 admitted tick、合格 intuition 或生产 daemon activation；原生生成执行是受界定的 v6 text/image backend；初始 paired evaluation profile 永久属于已观察的工程证据，即使描述性门槛有利也不能授予 qualification/promotion。

## 2. 历史证据索引与时间边界

以下路径均相对 `experiments/multimodal_output_portfolio/`：

- [v6/GATES.md](../../../v6/GATES.md)：既有 owner 接入、生产前置条件和拒绝结果的总说明。
- [abc_recovery/DESIGN_AND_SCOPE.md](../../DESIGN_AND_SCOPE.md)：第 7 节明确新 Python 证据不授予原生生产权限。
- [v6/results/owners-001/manifest.json](../../../v6/results/owners-001/manifest.json)：六份 compact receipt 的来源与原始／提交字节身份。
- [calibration.json](../../../v6/results/owners-001/calibration.json)、[neuron-admission.json](../../../v6/results/owners-001/neuron-admission.json)、[plasticity-prerequisite.json](../../../v6/results/owners-001/plasticity-prerequisite.json)。
- [trained-owner-replay.json](../../../v6/results/owners-001/trained-owner-replay.json)、[terminal.json](../../../v6/results/owners-001/terminal.json)、[paired-evaluation.json](../../../v6/results/owners-001/paired-evaluation.json)。
- [v6/neuron_calibration_spec.json](../../../v6/neuron_calibration_spec.json)、[OWNER_TERMINAL.md](../../../v6/OWNER_TERMINAL.md)、[OWNER_PAIRED.md](../../../v6/OWNER_PAIRED.md) 和 [owners-001/README.md](../../../v6/results/owners-001/README.md)。

本次已核验六份 compact JSON 的实际字节均匹配 manifest 的 `committed_bytes_sha256`。没有声称重新展开全部历史归档、重新打开旧机器上的 journal 或重新验证全部原始 payload。历史回执绑定旧模型、旧协议和本地工程上下文；本次所读证据没有给出新 ABC 模型的替代 native qualification 成功回执。

spec 中 `status=preregistered_before_calibration_not_yet_executed` 和 draft implementation 文本是前置冻结时的状态，不能覆盖后续实际执行结果。实际状态应由后来绑定的 calibration/admission 回执解释为“执行过并被拒绝”，不能说校准一直未测试。

以下“最小下一步证据”是根据这些已知契约整理的实施验收要求，不是已经发生的执行，也不保证单个切片足以获得完整生产授权。

## 3. Neuron calibration/admission：历史实际失败

建议 gate 状态：**`measured_failed`**。不能把正确拒绝路径测试通过写成 predictor qualification 通过。

| 指标 | Calibration cohort | Verification cohort | 冻结门槛 |
| --- | ---: | ---: | ---: |
| ECE | 503,354 ppm | 612,707 ppm | ≤30,000 ppm |
| OOD false acceptance | 32/32 | 32/32 | FAR ≤4,999 ppm |
| OOD FAR | 1,000,000 ppm | 1,000,000 ppm | ≤4,999 ppm |

Admission 回执的关键字段为 `status=rejected`、`native_error=InvalidCalibration`、`model_executed=true`、`actual_inference_owner_terminal=Completed`、`neuron_checkpoint_committed=false`、`authority=deny_all`、`daemon_activated=false`。**模型执行成功与 Neuron 校准资格失败同时成立。**

当前 GENERATION_NEURON 文档确认同一测量和阈值，并明确 persistence residual 不天然等于语义置信度或 OOD 分数。两个 cohort 各 64 来源、其中 32 个预声明 OOD；OOD 只覆盖无视觉／无数字提示这一构造机制，不是由输出错误反向标注。实测值取两 cohort 的最大值进入 native profile，不能换成示意性合格常数。

新 Python 的图文评分器资格、CE、采样和媒体回读没有重新校准这个原生 predictor，也没有产生新的 admission 成功回执。

**最小下一步证据：** 明确绑定新的 predictor、模型和 feature profile，前置冻结 calibration、独立 verification 与 OOD 设计，保留完整实际结果和来源身份；在未放宽契约的前提下通过真实 `NeuronRuntime::bootstrap`，然后完成实际 admitted tick。不能使用已见结果改门槛、合成合格数值或重标旧失败。64 是旧 pilot 的设计，不是规范已经保证足够的统计认证样本数。

## 4. 完整 tick 资源、intuition 与 production activation：尚未建立

建议状态：**`not_qualified_on_target_host`**、**`admitted_tick_not_established`**、**`intuition_use_not_established`**。

历史记录中的 projection wall 约 51.338 微秒、冷子进程 wall 约 7.857 秒、driver 至 observation 约 9.877 秒、child RSS 361,455,616 bytes 是不同口径，不能相互替换。冻结规范引用的资源要求是 P95≤3ms、P99≤8ms、transient allocation≤512KiB、checkpoint≤1MiB、write amplification≤4×。

当前 GENERATION_NEURON 文档特别说明：V1 receipt 的 `transient_allocation_bytes` 数值槽在这个冷进程 profile 中装载的是 **child resident-byte charge**，不是 allocator peak live bytes 或累计 allocation 的测量；RSS 不能冒称分配上界。失败进程缺失的内存测量保留为 None，旧 numeric slot 的零占位不是实测零。3ms/8ms/512KiB envelope 没有因 Python 冷启动而放宽，也没有把快速投影冒称整个模型执行耗时。

由于 registration 失败，当前文档仍明确没有 admitted `AgentdNeuronOwner::tick`、合格 intuition 使用或 production daemon activation。测试 NDU context 是 **test-only, no NDU valuation owner**，不是在线 NDU 接入证据。

本轮 resident episode 的约 9.39ms 等数值属于另一套 encoder、策略、采样及媒体交付口径；既不能当作 native tick 达标证明，也不能不经口径核对就断言该 native tick 违反 3ms 门槛。

**最小下一步证据：** 在实际目标主机、生产匹配的完整 tick 与资源 profile 下，保留 latency 分布、allocator 计量、checkpoint 字节和 journal 写放大，由对应 resource/admission owner 消费证据；通过 admitted tick 后再实际核验 intuition 使用。生产配置和 daemon 激活需要其本身的真实授权与执行回执，不由研究状态 completed 推导。

## 5. Acknowledged checkpoint / journal anchor：历史真实缺失

建议状态：**`blocked_missing_acknowledged_checkpoint`**。

plasticity 前置回执记录 `neuron.actual_witness_anchor=null`、`neuron.original_journal_bytes=0`、`neuron.original_error=InvalidCalibration`。被绑定的原始 `neuron.journal` 为 0 字节，SHA 为标准空内容哈希 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。

**最小下一步证据：** 在真正通过 admission 的执行之后，产生实际提交并 acknowledged 的非零 journal anchor、匹配 checkpoint 和 eligibility，并进行恢复核对。不能手工制造 anchor，把普通研究状态摘要当作 acknowledgement，或用另一 owner 的成功记录填补。

## 6. 同上下文 plasticity proposal/update：未构造完整尝试

建议状态：**`not_attempted_due_to_prerequisite`**，不是 proposal owner 已返回拒绝。

回执明确 `dynamic_resolver_constructed=false`、`parameter_generator_called=false`、`proposal_admission_called=false`、`proposal_writer_created=false`、`eligibility_written=false`、`same_context_proposal_attempt=false`、`contexts_relabelled=false`、`updates_produced=0`。

`MissingAcknowledgedNeuronCheckpoint` 是前置条件检查的工程标签；`rejection_layer` 是 `AnchorWitnessStore::current()` 返回 None。**proposal admission 根本没有被调用，所以这不是 proposal owner 的错误码。**

已经通过的有限部分是：真实 terminal 值 −3504111200 Q32 经 `NduProjectionStoreV1` append/select/backup/reopen 后保持一致。这是一个已观察 terminal utility 的 identity projection，不是神经梯度，也不是一般 NDU 条件递推。

两种上下文始终不同：terminal objective 为 `0413644766e203b0c1e33e31d1ba5abb26070cf56edff0aa4ddf1c6c8f8d744c`，Neuron objective 为 `7472ac00a31a032d164101eb9e691622bdf3b52d5400b9f4ca525a32396c3e49`。不能把二者改标签拼接成同一 subject/objective 的成功链路。

**最小下一步证据：** 先满足 admitted checkpoint，再在真实匹配的 scope/objective/subject/model 上，将 checkpoint eligibility、同上下文 NDU modulator 和注册参数映射交给现有 resolver、parameter generator 与 proposal admission；实际产生 proposal/update，保存其 ownership、持久化及恢复证据。局部 eligibility 更新与生成器反向传播必须分别说明更新方法和梯度归属。

## 7. Inference owner：重放执行通过，不等于新 ABC 在线控制或原生 AV

建议分别记录 **`native_model_replay=passed_limited_engineering_scope`** 与 **`native_online_output_portfolio_control=not_established`**。

历史 trained-owner 回执实际执行旧 checkpoint，重放 `couple → refine_semantic → couple`，并确认 `raw_outputs_and_final_backend_state_identical=true`、`unique_original_row_membership_verified=true`。同时它明确 `online_native_control=false`、`new_scientific_samples=0`、`authority=deny_all`。这证明执行和身份／输出 custody，不证明 native owner 根据新草稿在线选择动作。

当前 GENERATION_EXECUTION 文档确认 `GenerationDriver` 是现有 ModelDriver 的 POSIX 研究 backend，不是另一个 owner、authority issuer、artifact selector 或 daemon。trusted host 的 immutable registration 绑定 executable、source root、checkpoint、model pins 和 timeout；请求不能任意选路径、shell command 或模型。

这个已审阅的契约接受 56×28 公共像素／mask、8 个公共 token、latent noise seed、content-control flag 和最多 8 个命名动作，**只接受已经实现的 text+image output set**，未实现模态会拒绝。它绑定 v6 的 `conditioned.py`、`data.py`、`neural.py`、`observer.py`、`owner_worker.py`、`plan_training.py` 等 source profile。文档没有声明已经接入新 ABC 的发射、critic/MPC 控制律或原生声音／视频生成。此结论只限被审阅的 GenerationDriver 契约，不是对仓库所有 AV 能力的泛化断言。

v6 GATES 还明确：现有 Rust evaluator 对完成候选的 V2 bridge 是事后 advisory；既有 `recursive.rs` 标量零噪声递归不是 Python 条件分布树。本次没有扩大读取 `recursive.rs`，不把 GATES 的范围说明伪称新的源码／运行核验。

**最小下一步证据：** 在生产匹配 host、artifact selection、resource grant 和生命周期中，明确注册新模型与实际发射／控制 source identity，由 native owner 根据当前 public history 实际在线决策，保存其信息边界、动作、输出、成本与恢复链路。若要声称原生全模态接入，需相应的真实模态执行契约、注册 backend、输出／时钟证据和 admission，Python MKV 交付或源时间线恢复不能自动补出。

## 8. Terminal learning：有限工程链路通过，外部 trust 与神经梯度接管未建立

建议分开记录 **`terminal_import_fit_recovery=passed_limited_engineering_scope`**、**`external_observer_trust=not_authenticated`**、**`generator_gradient_native_owner=not_established`**。

已执行的 terminal 切片有 7 对 Decision/Outcome、14 条 ledger 记录、7 个真实受支持 cell；完成 freeze、fit、artifact 保存／加载，loaded prediction 与实际 Q32 target 一致，恢复后重新拟合相同。未观察的 `abstain` 返回 unsupported，没有虚构第八个 outcome。

同时回执为 `production_authenticated=false`、`python_gradient_training=false`、`authority=deny_all`、`new_scientific_samples=0`、`scope=local_research_replay`。一状态、每动作一个样本的精确拟合不是神经梯度训练；本地确定性测试签名虽区分角色/controller，不构成外部组织独立性或生产授权。

当前生成执行文档也说明 local source/checkpoint/runtime hash 只证明注册 host 下的 custody；hash 本身不认证 principal，CPU platform tuple 不是远程主机 attestation。

**最小下一步证据：** 建立实际部署所需的外部 observer trust 和生产 artifact 选择；若主张生成器神经训练进入 native owner，则提交真实参数映射、更新方法／梯度来源、admitted 数据、更新归属与 owner 保存、加载、恢复证据。不能把本轮 PyTorch 更新或 terminal-cell artifact 改名为该资格。

## 9. Fenced evaluation：工程消费恢复通过，旧阈值失败且生产资格未授予

建议分别记录 **`paired_custody_recovery=passed_limited_engineering_scope`**、**`legacy_observed_thresholds=failed`**、**`production_qualification_or_promotion=false`**。

历史回执实际消费 60 来源 × 3 固定 seed × 2 arms 的 360 个旧观测，完成 fenced consumption、受控释放、角色签名、fsync 与 journal recovery，恢复后只有一条消费记录。但 `observed_thresholds_pass=false`、`qualification_or_promotion=false`、`external_observer_authenticated=false`、`previously_observed_engineering_only=true`、`authority=deny_all`。

旧 candidate−baseline 平均 joint loss 约 +0.00544652，工程区间 [−0.62700901, +0.63790205]；平均 factual error 约 +0.01666667，区间 [−0.61578887, +0.64912220]。这是 family=64 的工程 Q32 区间，不是旧科学试验 family=32，也不是新 A/B crossed bootstrap。其区间条件于冻结模型，不覆盖训练 seed 总体或经验 CVaR。

当前 PAIRED_FULL_INFORMATION 文档确认初始 paired profile **永久标记为 previously observed engineering evidence**；冻结已观察 bundle 不构成 preregistration，**即使描述性门槛有利也不能授予 qualification 或 promotion**。它没有伪造 propensity 或 cross-fit fold 来套用旧 OPE API。

当前文档还确认以下部署边界：

- 同一 fenced owner / locked CAS 先成功消费再 release；后续 provider/evaluation 失败不能抹去消费记录重试另一分析。
- `FinalHoldoutCasRecordV1.journal` 改为 `HoldoutJournalSnapshotV2`，直接消费者需要迁移；旧 reader 对混合 history 拒绝，不能当作完全 additive API 变化。
- 不同但重叠的 cohort 检测仍是 source owner 责任；journal 的 cohort commitments 不是全局逐来源分配索引。
- fixture 使用真实 fsync sink，但 **production host evidence adapter 没有提供**；本地 fixture 签名不认证外部 evaluator。
- 所需 text/image 缺失保留为 fulfillment failure，不补造 outcome，也不产生 passing quality interval；相同 modeled budget ceiling 不等于实际耗时、能耗或工作量相同。

**最小下一步证据：** 对下一轮尚未释放的新留出集，先完成适用 owner 的预注册、source/cohort 承诺、CAS 消费／释放、外部效用与 trust、版本迁移及生产 evidence sink 的实际执行；qualification/promotion 必须来自明确允许该权限的有效 owner 流程，不能给永久 engineering-only profile 改标签。现在再导入已经看过的 ABC 结果，只能增加工程重放证据，不能补成过去未发生的 prospective native qualification。

## 10. 建议保留在最终 GATES 的状态

| Native 项 | 当前证据状态 | 不应混淆的已通过切片 |
| --- | --- | --- |
| Neuron calibration/admission | 历史实际失败 InvalidCalibration；所审阅证据无替代通过回执 | 正确拒绝路径测试通过 |
| Admitted tick / intuition | 未建立 | 模型执行、有界投影与 receipt 验证 |
| 目标主机完整 tick 资源资格 | 未建立 | 冷进程成本、RSS 和 projection 耗时记录 |
| Acknowledged checkpoint / anchor | 历史 journal=0、anchor=null | witness 真实检查到缺失 |
| 同上下文 plasticity update | 因前置条件未尝试；updates=0 | terminal projection store 恢复一致 |
| Native 在线条件 NDU 控制 | 未建立 | 已选动作的 inference owner 重放一致 |
| 新 ABC／声音视频的该 driver 接入 | 已审阅契约未声明支持；当前 output set 为 text+image | Python 实际图文／媒体实验各自完成 |
| 外部 trust / production artifact selection | 未认证或尚需配置 | 本地角色签名与 artifact 加载 |
| 生成器神经梯度的 native owner 归属 | 未建立 | Python 更新和 native terminal-cell fit 各自存在 |
| Fenced production qualification/promotion | 未授予；旧 observed thresholds=false；初始 profile 永久 engineering-only | 旧数据消费、签名、持久化及恢复 |
| Production daemon activation | 历史回执 false，权限 DENY_ALL | 研究执行清单 completed |

当前 DESIGN_AND_SCOPE 第 7 节与三份固定 ref 文档、旧结构化回执一致。文档读取成功关闭的是访问与核对缺口，不是 calibration、journal、资源、trust、参数映射、梯度归属、全模态或生产授权 gate。既有文档记录的测试数是历史记录，本次没有重新执行，也没有核对待合并提交的远端 CI；编译、ignored/skipped 或正确拒绝不能替代相应实际通过记录。
