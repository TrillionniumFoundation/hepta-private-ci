# Adopt 后独立使用授权：最小设计候选

**状态：设计稿，未改动产品源码，未签发授权，未编译或执行。** 本稿解决的对象是：已完成 C 所选的同一个 artifact，在旧学习／head 授权结束后，能否由真正 Artifact head authority 为一个新 D 给出独立、限用途的使用许可。它不延长旧学习窗口，不改写旧 CURRENT，不把原 240 秒改成 300 秒以上，也不把测试 key 当生产签发权限。

结论是：**可以定义可验证的新原语，但现有系统还缺少它的生产签发、目的授权政策与用途受限的消费接口。** 单加一个 JSON 或在 reader 上加 `allow_expired` 无法满足现有约束。最小正确方案要同时处理历史读取、独立选择、Root 冷 D、代际发布及持续运行检查；不能在初次选择时验票后恢复通用 CURRENT 权力。

## 1. 精确基线与已有接口

普通路径基线固定为 `2b8125e3f89e83aea90620c94cbc441317d4c3d0`，tree `9fd4268ef5ffd63661e067b6ee043f0e522e97ab`。冷 D 基线为独立保留的 `6733159bd974ae6558e138112d81ca2f6da830e2`；相关冷文件与原 504 审阅字节逐一匹配。673／504 尚未据本次工作建立公开 GitHub 对象，不能给它们伪造可访问的公开链接。26 份完整原文件、Git blob 和 SHA256 在 `SOURCE_BINDINGS.json`。

| 现有类型或边界 | 已有保证 | 新用途不能假设它已经提供的能力 |
|---|---|---|
| `ArtifactOwnerTrustV1.head_signers`、`TrustedArtifactSignerV1` | 区分 head 与 writer；绑定 key、epoch 范围、有效期、revoked_at；严格 Ed25519 验证 | 没有独立 use-grant 目的的部署政策、私钥 custody、签发服务或新的跨进程可信 policy 更新通道 |
| `ArtifactOwnerReadView::discover_current_head_unanchored` | 唯一完整 head 链、历史签名、单调 generation／epoch，随后核最新 signer 与 head 的当前有效性 | 不能在过期后返回可供通用消费者使用的 `VerifiedCurrentRegistryViewV1` |
| `LearningArtifactReadViewV1` | 目录身份、实际 head／registry 前后读取、未完成事务拒绝、withdrawal 前沿 | 只有当前授权读取，不是历史数据加新用途授权的 reader |
| `SignedArtifactSelectionV1` / `ArtifactSelectionVerifierV1` | 独立 Selector、完整 artifact 字段、当前 witness／trust 和 payload 绑定 | 签名字节没有 use-grant、D recipient、operation 或 nonce 字段；不能把 V1 silently 改成另一含义 |
| `LearningArtifactOwnerService::open` | 原 writer fence、writer lease、当前 registry、恢复／withdrawal 状态 | 自身也会因 expired CURRENT 拒绝；fresh writer 不能令旧 head 重新有效 |
| `RootFinalizedColdHistoryV1` / `RootFinalizedColdCReadV1` | 原完成记录、实际 Finalized phase、完整 C cut、原文件与 CURRENT 持有和重读 | 原普通 JSON、预期 cut、归档 PID 不是这些类型的替代构造参数 |
| `OriginalColdNextTaskContextV1` / `RootPreparedColdNextTaskGrantV1` | 新 Root 的真实 issuer＋writer、nonce Attempted、FinalUse、作用域和后观察 | 不是 Artifact head authority；其签名不能代签新的 Artifact 使用权 |
| `GenerationArtifactOwnerV1` / generation prepare、publish、recovery、live guard | 当前更新分支硬要求 writer；Root Initial 仅有专门的窄读取分支 | 新 use grant 不能通过 `.writer()` 或初始化分支取得一般更新／发布权 |

公开源锚点：[owner trust 与验证](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2b8125e3f89e83aea90620c94cbc441317d4c3d0/codex-rs/hepta-learning-artifacts/src/owner_host.rs)、[实际 head discovery](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2b8125e3f89e83aea90620c94cbc441317d4c3d0/codex-rs/hepta-learning-artifacts/src/owner_read_view.rs)、[Selector V1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2b8125e3f89e83aea90620c94cbc441317d4c3d0/codex-rs/hepta-learning-artifacts/src/selection.rs)、[代际更新 writer 门](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2b8125e3f89e83aea90620c94cbc441317d4c3d0/codex-rs/hepta-agentd/src/neuron_generation_update.rs)、[只读／writer 分支](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2b8125e3f89e83aea90620c94cbc441317d4c3d0/codex-rs/hepta-agentd/src/neuron_generation_artifact_readback.rs)。

## 2. 先分清三种权限与两个时钟范围

Artifact authority 决定这个既有 artifact 是否可在一个声明的新用途内被使用；Selector 独立选择这个完整模型；新 Root 依现有 D 事务控制真正的代际变更、ObjectiveStart 和 FinalUse。三者签名不能相互代替。Writer-only key 不满足 head 角色；D controller 和新 Root issuer 即使有效，也不因此得到 head 使用许可的签发权。

新用途应有独立签名域，例如 `hepta.learning-artifacts.cold-task-use-grant.v1`。它授权 **一个指定 artifact 在一个指定的新 D 中被读取、装入并执行**，不能授权训练、修改权重、Register 新 artifact、延长学习 receipt、改变原 C、推进 Artifact registry CURRENT 或一般任务重用。

旧学习的 240 秒和旧 writer 的真实 300 秒退休规则保持原义。新 grant 不修改这些字节，也不重建旧 live owner。新授权自己的期限来自真正 head authority 的新决策，并被新的 D 上限、实际新 Root issuer／writer、Selector、AuthBus request 和整个冷父的原截止共同约束。

使用时有效期取所有适用新授权和原父截止的最早值。新 grant 的上限**不取旧 head 的已过期时间**，因为它是明确另行授予的用途权限；与此同时，旧 head 仍然过期，通用接口仍然拒绝它。epoch 也必须分域：Artifact head epoch、Selector epoch、Root FinalUse authority epoch 不得因同为整数而互换。

`ArtifactManifest` 注册记录保留内容和 lineage 身份，没有把新用途变成一次新注册。原 `LearningArtifactManifestV2`／V3 publication admission 仍按原时间规则验证；不得重新调用其 publication admission 并把它标成“续期成功”。旧 provenance 验证为历史事实，当前 withdrawal 对内容继续有否决权。

## 3. 授权来源：角色验证是必要条件，生产启用还差一步

### A. 可实现的验证原语

复用 `ArtifactOwnerVerifierV1` 的**原始固定 trust**和严格 key／epoch 验证，新增只识别上述新目的域的签名验证函数。签名必须来自该 trust 中当前有效的 `head_signers`，不能只在 `writer_signers` 中，也不能来自 request 内附带的新 trust。

新增 `ArtifactColdUsePolicyV1` 的实际部署输入，至少绑定 policy ID／digest、原 owner trust digest、registry、storage binding、withdrawal scope、允许的新 purpose、head key／epoch、受许可 recipient／scope、单次用途、有效期上限以及 policy generation。**默认未配置／未知目的拒绝。** 这份政策的可信性来自真正 Artifact authority 的原 provisioning／custody 边界，不能由 D controller、新 Root writer 或任意 JSON 文件给自己设置。若生产侧没有这个真实安装通道，产品入口保持关闭。

### B. 本次仍不具备的生产能力

原源码只提供 head 验证角色，不提供已接通的新目的签发服务。现有 `ArtifactOwnerTrustV1` 是固定快照，也不能被表述成已经具有在线 revocation feed。生产启用必须补齐：真实 head 私钥 custody，允许新用途的原 authority 政策，当前 key／policy generation 和撤销状态的认证来源、持久签发账本、失败恢复及审计。测试中原 key 的存在只允许验证组件行为。

因此 `SignedArtifactColdUseGrantV1` 是**不可信传输数据**；验签成功是一个事实检查，尚未授予 Root、Cell 或 writer 任何权限。只有后续所有原 owner 检查合取成功，才在私有 operation 内构造消费能力。

## 4. 新签名字节必须覆盖的字段

完整字段和拒绝规则在 `WIRE_CONTRACT.json`。编码沿原模式采用固定目的前缀、定长 digest、明确长度的 StableId、固定字节序整数和严格版本；不以普通 JSON 排序约定代替签名字节定义。限制在原 16 KiB small-record 上限内，拒绝未知／重复字段、非 canonical 编码、空／零 binding、溢出、截断和不支持版本。

| 组 | 必须签入并独立核对的绑定 |
|---|---|
| 目的与权限 | schema、purpose、policy digest／generation；动作固定为既有同模型 artifact 的单次 cold D 使用 |
| 真正签发者 | head signer ID、key digest、head authority epoch；原 trust digest；issued_at／not_before／expires_at（Unix ms） |
| 原 Artifact 实体 | registry ID、storage binding、原完整 head 签名字节＋签名 digest、历史 chain tip、registry generation／head／snapshot receipt／file digest、唯一实际 transaction receipt |
| 内容与模型 | artifact ID／generation／kind／predecessor、内容 digest／size、完整 manifest digest、bundle digest；实际 payload 必须 canonical 且与完整 C 模型一致 |
| 当前撤回状态 | withdrawal scope、发行时实际 frontier digest／generation；第一版要求消费时仍是该精确 frontier，任何变化均重新拒绝处理 |
| 原 C 条件 | 原学习 operation、completed-history digest、C CURRENT head、Finalized successor record／完整 cut、原 source publication／完整模型身份；这些是权限生效条件，不是票据代替 Root 出具的完成证明 |
| 新 D 目的地 | agent、principal、recipient process-identity digest、spawn generation、new run ID、目标 owner binding／generation／genesis、完整 source／target／configuration digest |
| 新 D 请求 | 实际完整 AuthBus request 的 signing-bytes digest、issuer／key epoch／message ID／sequence／signature digest／expiry；runtime、Feature semantic、bundle 三种身份按原契约分别绑定 |
| 防重放 | registry 范围唯一 grant ID／nonce；new operation ID；recipient／generation／D run；consumer 类型及当前 consumer trust digest |

签名域必须包含上表全部安全相关字段，不允许用未经独立复算的 `derived_*` JSON 代替。`grant_digest = H(目的域 || 全签名字节 || signature)`。payload、C、D 和 trust 的 digest 只是精确绑定；其来源真实性仍分别由真实 owner、文件、原签名和 Root context 证明。

## 5. 消除签名循环与完成证明的偷换

先固定新 D 的**选择前描述**：recipient、run、operation、AuthBus 原请求、source／target 原任务文件、前驱 C 约束和完整模型身份。它不含新的 use grant、Selector 或最终 update intent digest。这里的文件清单是关闭的任务／runtime／data 清单；新 grant、随后 Selector、最后 Root intent 是单独声明的必需授权信封，仅为消除自引用而不进入这个早期摘要。Root 接纳前的完整输入清单仍绑定它们全部真实字节和之前所有任务文件。不能任意剥掉 source／configuration 字段来凑 hash，也不能把遗漏授权文件当成可选项。

Head authority 对该描述签发条件许可。若需要在 C 的 Finalized record 可用前准备它，签入的 C 内容必须明确为生效条件；它不是 C 完成 attestation。Root 只有在 `RootFinalizedColdHistoryV1` 与 `RootFinalizedColdCReadV1` 读取真实 Finalized C、原 cut 和原物理文件并全部匹配后，才可接纳。若部署政策要求签发者自己先独立观察 C，则签发服务必须有真实受保护读取或认证陈述接口；这是未实现的生产前提，不能用客户端 expected-C JSON 替代。

之后由独立 Selector 签 `SignedArtifactColdUseSelectionV1`：保留 V1 全部 artifact／selector 绑定，并增加 purpose、grant digest 和 D 描述 digest。不改变 V1 的 signing bytes，也不增加“V1 也可接受”的回退。最终 Root `ColdNextTaskProfile`／selection observation／update intent 绑定这个 V2 选择和 grant／nonce。因此顺序是 D 描述 → head grant → Selector → Root intent，没有互相引用的循环哈希。

获取新授权的外部 I/O 必须发生在 scoped Root callback 之外。若采用 late input，先预留并固定真实文件身份，等数据到达后重新进入原 owner 操作核验。不得把 `OriginalColdNextTaskContextV1<'op>` 或历史读取 borrow 跨外部 await 保留，也不得在等待后继续使用之前取得的“当前”结论。

## 6. 私有 typestate 与消费顺序

`API_CONTRACT.md` 给出具体新增接口草图。下面名字均为拟议新类型，并非当前源码已经存在。

1. **`SignedArtifactColdUseGrantV1`**：可编码／传输／保存的数据。没有权限构造器。
2. **`AuthenticatedColdUseGrantV1`**：模块私有验签事实，绑定实际原 policy／trust／current signer。不能导出为 CURRENT、selection、writer 或 FinalUse。
3. **`OriginalHistoricalArtifactForColdUseV1<'read>`**：在原目录 pin、完整唯一 head 历史、实际 transaction／registry／payload 和 withdrawal 前后读内得到。所有字段私有；无 Clone、Deserialize、Send；不能由 JSON 或独立 digest 构造。
4. **`OriginalColdUseOperationV1<'op>`**：Head policy＋上述内容事实＋真实 Root 完成 C／新 D context 的合取。用 HRTB callback 和 `PhantomData<Rc<()>>` 限定在一个同步自然 owner 操作内。
5. **`VerifiedColdUseSelectionV1<'op>`**：独立 Selector V2 成功，且其完整模型、grant、D 描述与上述 operation 完全相等。
6. **`PreparedColdUsePublicationV1`／实际 owner receipt**：独立持久 nonce 状态与原新 D 事务共同固定后，才进入原 Root FinalUse 的 Attempted→Issued 和 generation CAS。异步间隙只持数据、journal owner 与原始文件 owner；下一效应重新取得 scoped operation。

具体顺序如下，任一步失败都不能降级为通用 reader 或当前 writer：

1. 验证新 Root 的原 session／peer／process pin、issuer＋writer、authority epoch、consumer 和实际时钟；核真实 cold retirement，不从旧归档恢复 pidfd。
2. 用原 `RootFinalizedColdHistoryV1`／`RootFinalizedColdCReadV1` 检查真实 Finalized C、当前头、完整 cut、原物理文件、drained predecessor；拒绝 Registered／Incomplete C。
3. 读取已固定的新 D 原文件和签名请求；独立复算完整选择前描述、recipient、run、operation、target binding。验证原 AuthBus 签名及 exact-byte 关系。
4. 从独立可信 provisioning 取得当前 policy／trust／key epoch／撤销状态；核新 grant 的目的、当前 signer、全部 C/D/Artifact 绑定及新有效期。
5. 用专用历史 reader 读取原完整唯一 head 链：各历史签名按其真实 issue time 验证，最新物理 tip 必须等于 grant 指定的 tip，原 anchor／generation／epoch／registry receipt／事务完整性全保留。**只产出历史事实，不产出 `VerifiedCurrentRegistryViewV1`。** 第一版不接受新增 tip、fork、rollback 或未完成发布事务。
6. 在原固定描述符上读取完整 canonical manifest／payload，与 artifact、C、D 三方全模型身份比较；验证实际 withdrawal 精确前沿，任何当前撤回、quarantine 或 policy 撤销都否决。
7. 验证独立 Selector V2，检查原 role collision、key／epoch／expiry、完整模型及 grant／D 描述一致；复查步骤 1–6 的实际 owner 前后状态。
8. 在实际 Root cold operation store 原锁／witness 下固定 grant nonce＋operation＋D 绑定。nonce 只能在这个 recipient／generation／operation 使用一次；只读观察不消耗或制造新任务。
9. 通过专用 cold-same-model publication 分支保留原 predecessor 锁、drain、Root prepare、实际 FinalUse Attempted／Issued、target genesis／CAS／publish 和后观察。Head grant 不替代 `SignedFinalUseGrant`。
10. D 每次 live CURRENT／artifact revalidation 都通过这个专用原 owner 分支检查新 grant、withdrawal、原内容和 Root scope。D 的一次 ObjectiveStart、ACK-loss、原物理完成／FinalUse／C不变检查和截止保持原样。grant 到期／撤回后不得继续新效应或发送输出。

历史验证不能通过向普通公开方法传 `now = old_issued_at` 来实现；该接口若可被任意产品路径调用，会形成全局时间绕过。历史时间仅留在专门私有 head-chain 事实扫描中，消费时间来自实际原 authority clock，并在每个效应边界重新检查。

## 7. 新原语与可运行产品的最小差异范围

详细逐文件清单在 `PATCH_PLAN.json`。为了避免把设计写成虚假的“一行开关”，分两层列出。

### 原语层，可先独立实现和验证

- 新 `owner_cold_use_grant.rs`：固定签名域、canonical 数据、原 head-role／policy 验证、私有验签事实；不放私钥、不提供 fixture 默认 signer。
- 新 `owner_cold_use_reader.rs`：实际固定文件、历史 chain、内容和 withdrawal 的用途受限读取；复用现有算法的私有事实部分。
- `owner_host.rs`／`owner_read_view.rs`：只做私有 verifier／历史扫描复用，generic current 最后仍调用原 signer-current 与 CurrentHeadExpired 检查。不得增加公开 allow-expired 参数。
- 新 `cold_use_selection.rs`：新 Selector 签名域及新类型；V1 不改字节语义、不接受过期 CURRENT。
- 新数据／历史／签名／文件 mutation controls、完整 CALLERS closed set 和 protected rows。完成这些只能声称新原语组件结果。

### 产品层，接通 Adopt cold D 必不可少

- Artifact deployment／读取输入增加明确用途 enum：原 `CurrentV1` 路径与新 `ColdUseV1`，后一分支默认未注册。不能用几个 Option 字段拼成宽松回退。
- Root cold enrollment 从原 history、原 D 文件和真实 policy 构造 `OriginalColdUseOperationV1`；profile／request digest／journal key 加入 grant digest、nonce、D 描述、Selector V2；原 C／Root／consumer 约束全部保留。
- `production_cold_q24_artifacts.rs` 增加专用 readonly use reader。它**不打开会失败的通用 `LearningArtifactOwnerService`，也不授予新 Artifact writer**；新 Root 的 generation writer／FinalUse 仍必须存在。
- `GenerationArtifactOwnerV1` 可增 `RootColdUse` 私有具体分支，构造器只对真实 Root cold client 开放。`.writer()`、generic update／recovery、Root Initial 入口对它一律拒绝。
- generation prepare／publish／recovery／`LiveGenerationCurrent` 需要专用 cold-use 路径或私有 typed revalidation 核心；不得把现有 `writer()?` 改成宽泛 fallback。只接受 `OwnerDrainedSameModel`、相同完整 C model 和同一个新 D operation。
- 新 selection observation 的目的域包含 grant／policy／D 描述；不能复用 V1 observation digest 却遗漏新用途绑定。Root final intent 仍进入原 FinalUse 和 CAS。

这不是只有一个新 token 的补丁：现有 consumer 类型把当前授权和模型选择绑定得很紧。应先完成原语与其真实负控，产品接线另列审核；只有真正 whole-cold Adopt 父、原截止和新 D FinalUse 全部通过，才可声明这个具体路径闭合。

## 8. 防重放、持久错误与撤销

真实 head 签发服务需要自己的持久账本：`Reserved → SigningAttempted → Signed`，以原 registry／policy／grant nonce／D operation 为键。签名调用前写实际 Attempted 并落 witness；签名后做原 authority／policy／物理后观察，再保存完整签名字节及 receipt。外部签名失败或丢 ACK 时保持 Attempted／不确定，不自动重新签发、换 nonce 或扩期；只允许恢复已持久存在的完全相同结果。不存在真实签发账本时不能宣称 exactly-once issuance。

消费端优先把 grant nonce 的 reservation 合入现有 Root cold operation 的真实持久 profile／store，而非再写一个未经协调的小 JSON。它与原 `FinalUseAttempted` 绑定；并发 reservation 只能一个成功，已尝试而结果未知不能重新 IssueFinalUse。后检查失败时保留真实已写的 Attempted／Issued／Published 状态，不倒退成未尝试。只有按原精确只读恢复路径观察已发布结果，不再派发效应。

第一版要求原 head tip、policy generation、grant 指定 withdrawal frontier 在每个 scope 内稳定；任何变化先拒绝／fence。后续若要允许不相关 withdrawal 的单调扩展，应作为独立政策与完整验证改动，不能在此草稿隐含开放。实际 key／policy 撤销或源 dataset 撤回，即使发生在 grant 签发之后，也必须在新效应前使其失效。原信任快照缺少 live feed 的部署不得把“未观察到撤销”当“已证明未撤销”。

## 9. 必须拒绝的真实情形与验收等级

`REJECTION_CONTROLS.json` 明列 34 项拟议控制，包括真实文件替换、过期／撤销、错误 signer 角色、完整三类身份、C／D 换绑、并发 nonce、实际 witness 故障、签名未知结果、scope 跨 await、通用接口绕过与完整父验证。它们当前都是 **planned／not executed**。

需要区分三层结果：

1. 编码／签名／类型及源门控制能证明特定原语拒绝某类输入，不能证明真实签发服务存在。
2. 原生真实文件、journal／witness 和独立角色签名控制能证明本机组件行为，不能替代 whole-cold A/B/C→退休→新 D。
3. 完整 Adopt 冷父必须在原 480 秒整体内重新获得真实 A/B/C、actual retirement、实际新 Root／daemon、独立新 use grant／Selector、新 D 的一次普通请求、实际 FinalUse 和物理完成，并证明原 C 未变。原 240／300／120 秒规则不变。NoUpdate 600 秒原路径继续不需要这个新接口。

来源基线当前普通 NoUpdate5 仍失败，冷整合还在等待 C 身份修复的最终冻结；本设计没有改变那个事实。本次新源码门、编译、原生、模型、use grant 签发、D 执行、FinalUse 均为零，物理能耗与货币成本未测量。
