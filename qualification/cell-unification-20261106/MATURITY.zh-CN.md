# Cell 七类功能与历史后端成熟度核查

审计日期：2026-11-06。基线为 `caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b`。机器可读的提交、Git blob、模型修订、权重及证据范围见 [HISTORICAL_ASSETS.json](HISTORICAL_ASSETS.json)。

**撤回“七类都只是 enum”的判断。** 已有代码与历史执行记录覆盖七类功能的多个后端。当前要解决的是把具体后端按共同合约注册、执行、恢复和验收；历史资产存在、当前注册成立、科学收益通过是三个独立结论。本文只核查并绑定历史证据，不装载权重，不授予生产资格，也不把其他提交上的通过数记到本轮代码名下。[1][3][4][6][7]

## 两套七类必须分开

| 分类 | 定义与取值 | 合约含义 |
| --- | --- | --- |
| 功能职责 | `CellFunctionalRoleV1`：PerceptionEncoding、MemoryAssociation、PredictionSimulation、DecisionCoordination、ActionGeneration、VerificationMetacognition、LearningDevelopment | 描述承担的工作。不是 capability type、model、process 或 NDU subject；源码没有证明七是最优数量。 |
| 记忆组织 | `EngramPopulationV1`：SensoryTrace、EpisodicBinding、SemanticConcept、ProceduralSkill、PredictiveWorld、UtilitySalience、MetaMemory | 描述 HNMF 记忆组织。不能按枚举序号转换成功能职责，也不能由两者同为七项推导一一对应。 |

上述定义分别绑定 [角色源码][1] 与 [HNMF 源码][2]。一个后端可在不同合约下承担不同功能；某角色也可由不同家族的多个候选竞争。角色、能力版本、运行实例及物理进程应分别计数。

## 七类角色的证据与缺口

| 功能角色 | 已核查的真实资产 | 证据实际支持什么 | 进入统一系统仍需满足什么 |
| --- | --- | --- | --- |
| **感知编码** | Granite / EG2 真实编码调用；共享 FeatureBundle；多模态 slotizer。[3] | 固定修订的文本、图像、音频输入和共享表示实际执行；原始张量有 dtype、shape、bytes 绑定。 | 独立新来源的视频与联合 AV 验收；当前 owner / source 重校验；本轮 Q24 桥之外的张量、token、缺失模态与时空视图导入。 |
| **记忆关联** | V13 MiniLM + residual adapter；V14 内部 attention LoRA；V15 持久评价与当前来源约束。[4][5][6] | 真实训练、有限操作选择、续训状态恢复、来源变更与失效路径；不同版本证据范围明确。 | 稳定保留、校准可用性、强检索/精确 KV 对照下完整成本净收益；不能借用别的后端迁移资格。 |
| **预测仿真** | 有限状态/控制研究中的 belief、continuation-Q 与条件特征；多轮反馈 readout 训练。[8] | 有真实优化与执行预算记录；#4578 每 fit 的物理 dynamics 固定，训练 readout / belief / Q。 | 未见任务与动作条件泛化、实际标签校准、质量门槛和足够独立 fit；不得改写为已证明物理 dynamics 可学习或通用 World Model 优势。 |
| **决策协调** | 已训练路由、selected-only worker、生成 actor / critic、固定策略和候选池对照。[3][4][6][7] | 真实路由/停止行为存在；错误来源可由真实 trace 区分，但缺失 trace 不可补造。 | 跨任务、完整生命周期成本下优于强固定策略；当前 capability、scope、source frontier、operation ID 一致约束。 |
| **动作生成** | 实际 SmolLM2 causal LM + learned prefix；小型内容网络的完整 Rust 推理与媒体输出。[7] | 自由词表解码、真实可训练前缀；小模型 Torch–Rust 数值差分与输出读回。 | 自然质量、学得的流式跨模态一致性、统一产品 owner 接入。原生小模型差分通过不等于大 LM 或自然内容质量通过。 |
| **验证元认知** | critic、独立差分/媒体读回、输入干预、严格类型评分、来源/权限负向检查。[6][7][8] | 可检查结构、数值、输出类型与有限语义指标；实际保留失败结果。 | 自然语义评分可靠性、独立 freshness 信任和最终使用时重校验；自 critic 不能独立签发最终质量结论。 |
| **学习发育** | Head / Adapter 训练、候选 split、结构 gate、优化器恢复与多轮反馈。[3][4][5][8] | 参数与状态确实更新；V13 有严格续训证据；真实无收益与拒绝记录存在。 | 多代有效采用、保留、完整成本及学习策略自身改进；proposal、测试数量和训练更新数不等于有效进化。 |

## 后端家族应保留可替换性

| 家族 | 可复用资产 | 不应借用的结论 |
| --- | --- | --- |
| 冻结表示 + 私有 Head / residual adapter | Granite 384 维、EG2 768 维及共享特征/worker；V13 MiniLM 384 维与完整续训契约。 | 小型任务收益不能外推通用文本/多模态最优。V14 内部 encoder LoRA 会改变表示，需明确其额外训练状态。 |
| 生成模型 + 私有 Adapter / 解码状态 | #4442 的 SmolLM2 + learned state prefix，以及独立的小型 Rust 内容解码器。 | V14 八分类 encoder LoRA 不能充当生成模型的证据；强制执行的媒体序列不能证明学得流式策略。 |
| 可训练状态 / World Model | 有限模型的 recurrent state、readout、belief、Q 与控制实验。 | 本次核查的 #4578 训练 readout 而固定物理 dynamics，不能据此声称整体动态模型已学习并泛化。 |

Granite 97M 可继续承担低成本文本候选；EG2 保留真实多模态接口价值；V13 保留已验证的状态续训设计。选择应由具体任务、保留、校准、完整成本与对照决定。顶层七职责不要求恰好七个模型或七个实例。[3][4][7][8]

## 三个容易被误读的证据边界

### V13：完整续训是真实资产，科学收益仍未通过

V13 的私有可训练部分是 `h=x+tanh(xA)B` 和分类头，rank 8、10,764 个 float64 参数；冻结后端是官方 MiniLM ONNX。它不包含 Transformer 内部 LoRA，也不是开放生成式知识记忆。三种子初始技能得分为 59 / 61 / 61（每组 72）；加入新绑定后，回放旧技能为 52 / 55 / 48，新绑定均为 12 / 12。ridge 对照为 61 / 72，split 候选为 52 / 56 / 56，继续训练为 59 / 61 / 61。因此可报告学习与恢复机制执行，不能报告稳定保留或正的完整成本收益。[4]

跨 VM 成功 run 为 `41206138368`，科学提交为 `8ae2d91947203a868f880312df823004b7289f25`：三个独立 boot、13 项严格检查，在声明数值 profile 下，90 与 97 步的参数、Adam、RNG、sampler 和元数据 raw bytes 一致。首次严格失败 `41205095256` 被保留。资格仅属于该完整状态、数值 profile 和记录硬件；不扩展到任意硬件、V14 Transformer 或生成模型。[4]

### V14：内部 attention LoRA 是分类器

`language_models.py` 向 encoder attention 的 query/value 注入 rank-4 LoRA，并通过 CLS 表示与八分类 linear / MLP head 输出概率和 argmax。这是可训练 encoder 内部适配的真实实现，不是 causal LM 解码器。21 个结构提案全部拒绝，不能当作已采用有效分化。原生迁移记录是同一物理 host 的两进程小型 MLP 恢复，不是完整 Transformer 优化器的跨节点续训。[5]

### V15 与生成：治理修复不能抵消已知反例

#4892 把 `True == 1` 的错误评分修复为严格 JSON 类型语义，同一 256 案例探针由错误批准变为全部拒绝；历史 4,032 个单输出与 504 个组合重评没有变分。持久 ledger 依赖同一数据库与受信 callback；完整恢复旧 authority 数据库和原始 keys 的探针仍接受 stale-owner / revoked-source 请求，`guard_qualified=false`。150 个测试通过不能覆盖这一反例，缺失 trace 的 42 个路由组也仍不可归因。[6]

#4442 有真实自由词表 LM 和可训练前缀，但固定事实检查在 state / zero-state / shuffled-state 三臂均为 0 / 4，`open_domain_qualified=false`。另一个小型生成网络的原生差分通过，只证明该 checkpoint、数值 profile 与执行路径的实现一致性；真实 actor 起始动作是 STOP。自然语义质量与有用的生成/停止策略仍需独立验收。[7]

## 本轮 Rust 桥：只导入既有 Q24 conversion receipt

原始 `FeatureBundleV1` 把张量复制到私有 CPU 存储，保留 float32 / BF16 dtype，并对 shape、dtype、原始 bytes、完整 FeatureIdentity、ordered source digests 与模态缺失 mask 建立 manifest。读取返回副本。原始 bounds 为 batch ≤512、width ≤4096、token ≤4096，总元素 ≤2,097,152、总字节 ≤16 MiB。pooled-only 表示不会获得补造的 token、区域或时间。[9]

本轮桥直接读取已存在的 `hepta.feature-global-q24-conversion.v1`，不重新定义张量 schema。其原始 statement 包含：

| 字段 | 固定语义 |
| --- | --- |
| `numeric_profile` | `signed-q24-nearest-ties-even-v1` |
| `source_bundle_sha256`、`source_record_digest`、`row` | 原始 FeatureBundle 的 SHA、该有序行的来源 digest 和行号；不是 SharedFeatureBatch 的另一个 digest。 |
| `feature_vector_q24` | 原 exporter 先转 float32，再对每个值乘 2^24 并作 ties-to-even 舍入；原值必须处于 [-8,8]。 |
| `authority`、`legacy_head_parity_qualified` | 严格保持 `DENY_ALL`、`false`。 |
| `conversion_sha256` | 不含自身的 statement，经 sorted-key、紧凑 JSON UTF-8 编码后 SHA256；原 Python 使用默认 `ensure_ascii=True`。 |

Rust importer 的窄边界是 row 0..511、width 1..512、Q24 整数 [-134217728,134217728]；不执行浮点舍入，不隐式改变坐标顺序或 basis。**EG2 的 768 维输出必须拒绝**；任何降维需要独立版本、输入/输出维数、basis/权重、numeric profile、行为与保留验收，不得静默截断或改用未声明 pooling。[3][9]

独立 caller binding 必须固定预期的 bundle SHA、source digest、row、conversion digest，以及原生 encoder、scope、当前 source frontier。先匹配独立取得的 conversion pin，再重算 receipt 封条。只检查 receipt 自洽会允许修改向量后重新计算 SHA，因此 caller 仍须验证原始张量与当前 owner/source；本地 hash 不构成独立来源认证。原生 feature/wire digest 必须由原生 canonical encoder 另行计算，不能把 Python SHA256 复制进另一散列域。

receipt 不携带 dtype、完整 FeatureIdentity、modality mask 或时空视图：这些只由原始 bundle 身份与受信 caller 保管。完整 FeatureIdentity 包括 encoder SHA、checkpoint revision、preprocess SHA、generation、scope、purpose、revocation epoch。preprocess 身份须覆盖 tokenizer、task prefix、归一化、precision、truncation 和适用的 media sampling/cropping。[9]

事件 schema 仍为 `hepta.shared-event-features.v1`。`observed_at_ns` 是 owner 提供的 Unix 纳秒，source interval 是毫秒，原始 token time spans 是秒；缺失就保持缺失。原始文本定位单位是 Python codepoint。不能从全局向量推断 token 对齐、视频帧时间、区域位置或联合 AV 能力。此桥不声称完整张量迁移、原始 nonlinear Head parity、模型/优化器续训或 AV qualification。[10]

在 `4b3081c25af86f707a5c0d50c688c959a04af446` 的 next-stage evidence、真实特征/媒体 producer、Granite/EG2 smoke 与相关单测中，本次未定位到已留存的真实 Encoder `q24_global` receipt；已见该方法的直接调用是舍入单测。因此独立 Python canonical fixture 的兼容测试应明确标注 fixture，不能称为真实 Encoder receipt 导入。历史确有 [64×384 Granite float32 特征归档](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/evidence/20261022-procedural-native-export/heldout.batch.json)，但它属于另一套 native export；不得改名或补造原始 FeatureBundle receipt。该搜索结论限于列出的已审资产，不声称所有历史分支均不存在此类导出。

## 接入时的具体阻塞项

1. **注册与执行绑定**：每次具体实现注册需绑定家族、角色 capability contract、schema/状态/行为 digest、精确 artifact 与当前 owner。旧 operation ID 与变更后的角色/家族/注册快照必须冲突，不能因复用底层 Head 就重用旧执行资格。
2. **当前来源与 scope**：加载时通过不代表最终消费时通过；需要对当前 source frontier、scope、撤销和 owner 重新检查。旧 authority 整体回滚反例必须由独立 freshness 信任解决，不能只增添同库签名。
3. **未知执行恢复**：缺失/中断 receipt 的已派发操作要保留 unknown 状态；不能凭再次请求自动重跑、补报成功或重新占用预算。复用与恢复都需匹配原始登记身份。
4. **状态完整性**：所有适用的参数、优化器、RNG、sampler、decoder/transition state、数值与运行时 profile 纳入恢复；仅预测相同不能证明未来续训相同。
5. **独立验收**：保留强检索、精确 KV、linear/ridge、强固定策略、继续训练与不变更对照；分别报告训练合法性、收益、保留、校准、全部成本与采用。禁止把历史分支的测试数拼成当前提交的通过数。

这些是统一系统需要闭合的接口与证据条件，并不表示本文已执行或通过相应新验收。精确当前代码的验证须以同一提交的独立运行记录为准。

## 固定来源

[1]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b/codex-rs/hepta-neuron/src/cell_roles.rs
[2]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/codex-rs/hepta-cognitive-types/src/hnmf_learning.rs
[3]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3650
[4]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1/qualification/memory-cell-v13/QUALIFICATION.json
[5]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4541
[6]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4892
[7]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/18dac3ccd30317893ad922792c12400390522f00/experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/evidence/open_text_frozen_20261030/report.json
[8]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4578
[9]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/feature_bundle.py
[10]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/shared_feature_contract.py

- [共享 Encoder/Head 固定结果报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4b3081c25af86f707a5c0d50c688c959a04af446/qa/stem-bakeoff/evidence/20261023-cell-next-stage/README.md)
- [V14 实际内部 LoRA / 分类头代码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae63a79ee3aafb1c9e1e042cac2c04921a7a897d/qualification/memory-cell-v14/language_models.py)
- [V15 固定提交的续篇](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f18d8299c8d445d68576e1c81368ecb981817e30/qualification/memory-cell-v15/CONTINUATION_20261105.zh-CN.md)
- [原生小型生成器精确差分记录](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/18dac3ccd30317893ad922792c12400390522f00/experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/native_generation/evidence/frozen_trained_20261031/RESULTS.json)
- [固定物理 dynamics 的反馈研究定义](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/README.md)

PR 链接只用于阅读当时报告；不可把其后续变动当作本文证据。完整 immutable commit、blob 与模型 hash 以机器清单为准。本文列出的历史模型实验本轮未复训或复跑；#4890 冻结参考研究的本轮实际执行记录另见 [study-evidence/README.md](study-evidence/README.md)。
