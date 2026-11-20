# Root completed acceptance：真实终态形态与最小兼容候选

## 状态与范围

基线为 `bfea526e1cb9a2da718d835cd617e87c67181fe9`。本目录的 `candidate_1/FULL_MANIFEST.json` 固定两份产品源码和一份新增 DATA 测试文件。该候选尚未格式化、编译或运行。三个新增用例只检查有界编解码与旧记录字节兼容，不证明真实 Root 认证成功。NoUpdate9 原整父仍为 FAIL；namespace、checkpoint DATA reader、observer/policy 分别由其他 owner 在独立候选中处理，本目录没有修改它们。

## 原协议允许的终态

以下是 exact bfea Coordinator 的合法 DATA 路由；合法 DATA 仍须经过原 Root 物理与签名认证。`Proposal` 按既有 verifier 规则不加入该签名摘要数组；freeze 的独立签名另行完整验证，也没有被改塞进数组补位。

| 原终态路径 | receipt 数 | 实际非 Proposal receipt 签名数 | LocalDecision journal 的记录数 | 末条 |
| --- | ---: | ---: | ---: | --- |
| Evaluation NoUpdate | 6 | 6 | 0 | RetainedModelNextUse |
| 旧 Proposal NoAdmissibleUpdate，无 LocalDecision | 7 | 6 | 0 | RetainedModelNextUse |
| 旧 Proposal UpdateCandidates，无 LocalDecision | 7 | 6 | 0 | NextUse |
| Proposal + LocalDecision AdoptCandidate | 8 | 7 | 1 | NextUse |
| Proposal + LocalDecision RetainParent | 8 | 7 | 1 | RetainedModelNextUse |
| Proposal + LocalDecision DeferCandidate | 8 | 7 | 1 | RetainedModelNextUse |
| TrainingNoUpdateV2 | 5 | 不进入本 completed-history 接受用途 | 不据此准入 | RetainedModelNextUse |

最后一行仍被原 `training_no_update_v2().is_some()` 条件拒绝。其 DATA Coordinator 可终止，不代表具备本用途要求的真实独立 B 评估与接受证据。

无 LocalDecision 的普通签名顺序为 Experience、Dataset、Training、Evaluation、Selection、NextUse；存在 LocalDecision 时，在 Evaluation 与实际 Selection 之间加入真实 LocalDecision 的签名。实际循环仍逐 receipt 获取其完整 signing payload，查找唯一匹配的原 journal completion，或取独立 B 的真实 Evaluation attestation。没有新增占位签名、常量摘要或从 freeze 补出的第七槽。

## 七组物理文件始终完整

| 固定槽 | 必须保留的真实 pair | 无 LocalDecision | 有 LocalDecision |
| --- | --- | ---: | ---: |
| 0 | freeze journal / witness | 1 Completed | 1 Completed |
| 1 | experience journal / witness | 1 Completed | 1 Completed |
| 2 | dataset journal / witness | 1 Completed | 1 Completed |
| 3 | training_receipt journal / witness | 2 Completed | 2 Completed |
| 4 | local_decision journal / witness | 恰 0 条记录 | 1 Completed |
| 5 | selection journal / witness | 1 Completed | 1 Completed |
| 6 | next_use journal / witness | 1 Completed | 1 Completed |

槽 4 的零记录要求是对**已经初始化、具有原 header/witness、在本次 Root operation 内实际读取的同一 pair**的要求。没有允许文件缺失、零字节、跨角色 alias、Pending、额外工作或初始化替代。`CompletedFiles::retain_original` 的七组去重以及 `with_rest` 的恰七组检查不变。

NoUpdate9 原件确实具有这种实体形态：local-decision journal 是 72 字节 HEPTEX01 header；witness 是 224 字节 HPTNWA01 header 加一条锚记录。已按 exact codec 静态核验 header/checksum、完整字节消费、journal sequence 0 / records 0，witness sequence 1，且其 checkpoint 等于该 journal 的完整 SHA256。witness objective 与原 retained checkpoint DATA 一致。原件与结果保存在 `LOCAL_DECISION_PHYSICAL_LAYOUT.json` 和 `LOCAL_DECISION_OBJECTIVE_BINDING.json`。

这些静态解码不替代产品对 expected scope、Generation、文件身份及原授权的认证；候选仍调用原 `CompletedJournalFiles::with_original_records`，保留实际前后图像、anchor、scope 和时间检查。

## 候选实际修改

`authority_host_completed_signatures.rs` 从私有 Root context 中已经完整 replay 的 terminal，读取实际 `local_decision_v2()` 是否存在。它只改变两个与路由有关的基数：槽 4 要求 0 或 1；签名要求 6 或 7。其余槽的数量不变，所有记录仍必须为 Completed。

摘要仍按原 receipt 顺序从真实签名 payload 计算。最终使用严格数组转换，构造私有 `CompletedSignatureDigests::Six([String; 6])` 或 `Seven([String; 7])`。转换失败继续报错。与已存 first fact 的比较仍是整个签名表示的严格相等，不允许将六签名当前路由与七签名原 fact 混用。

`authority_host_completed_record.rs` 将旧 `[String; 7]` 字段替换为上述 `#[serde(untagged)]` 有界枚举，并仅提供 `as_slice` 供原逐摘要 canonical 检查使用。它没有无界 Vec 成员、默认值、null padding 或新的权限入口。`journals` 仍是 `[String; 7]`。

## 兼容性与消费者

旧七签名 fact 的 schema、purpose、字段顺序、数组顺序、所有域和 12 KiB 上限不变；untagged 的 Seven variant 仍编码为原 JSON 数组。新增的旧型对照测试保留原字段结构，要求整条 record 的 JSON 字节及 `data_digest()` 域哈希均相等。该测试尚未执行，当前是明确的待验证兼容性契约。

新的六签名 fact 仍表达同一语义：实际完整终态中每条非 Proposal receipt 的签名摘要，顺序不变。新增长度是原合法路由的支持扩展，没有改变摘要含义，因此候选没有改 schema/purpose/domain，也不迁移或重写旧 fact。较旧、固定七签名的 reader 会拒绝新的六签名记录；本方案不声称旧二进制能够读取新事实。若改变签名槽含义、排序、冻结签名归属或历史时点语义，则应采用显式新协议版本；本候选未作这些变更。

exact bfea 的完整 agentd/QA 搜索由 hia 固定在 `e6_owner_work/completion_consumers_review/`：1,225 个 Rust 文件与 117 个 QA 文件，搜索无遗漏，十份完整匹配源逐 SHA/Git blob 对齐。直接消费者如下。

| 消费者 | 处理 |
| --- | --- |
| completed_record | 有界 Six/Seven；原 binding/canonical/profile/data digest 检查不变 |
| completed_signatures | 真实路由决定 6/7；七实体 cut、所有签名校验不变 |
| completed_observation | 原构造接收 typed `verified.signatures`；不需要修改 |
| historical_read / runtime / session | 仅原类型重导出；不需要扩接口 |
| cold_acceptance DATA observer | hia 独立候选将 journal 固定 7 与实际非 Proposal 签名数分开；完整 ACK 检查不变 |
| acceptance QA / CALLERS | hia 精确迁移旧固定数字保护，并保留所有实际验真顺序；不是扩大 ignored 或 product caller |
| completed-history / terminal-ACK 协议 | 携带原 acceptance digest 等绑定，不直接携带该私有签名数组；协议字段不变 |
| 原 cold36 | 独立复核中的七 cut 数组仍代表七实体，并非签名数；不据此删物理槽 |

## 仍保留的认证闭合

1. 外层 refusal 在实际操作前 Arm，失败不恢复 Ready；first immutable acceptance 只在完整 action 及其后检成功后 initialize。
2. 原 checkpoint 固定 owner 的物理 pin、完整记录及前后相等读保留。完整 Coordinator replay、scope/request/owners、非 TrainingNoUpdate、真实尾 NextUse 仍由原私有 context 的 reader 保证。
3. 当前 recipient identity、原 writer/pidfd/profile、SERVING 阶段、Root 当前 trust 与 activation pin 均保持原调用链；没有从 DATA 新造 owner 或授权。
4. 七 pair 的原描述符、去 alias、完整前后图像与 anchor 检查在成功或 action 错误后均执行。
5. 每条 receipt 的完整 signing bytes、唯一匹配、当前 signer、独立角色、签名真实性全部保留；Training 两条记录中恰一个非 Training 摘要仍须等于独立 B 的真实 plan attestation。
6. freeze 签名继续独立验证。first acceptance 仍以当前时刻验证，再以新的当前时刻重验；历史读取仅使用已经保存的 first verification time，同时继续当前 trust/signer 与物理检查。
7. 首次验证必须在原 work expiry 内；end、原 240/300/600/120/480 边界、64 历史请求预算都没有修改。
8. DATA observer 仍要求真实 daemon typed ACK，并在 ACK 后重新比较 acceptance 与 refusal；Root namespace 修复不将磁盘 Ready 当作 ACK。

独立 B 与 publication 入口的 exact bfea 源由 root 在 `e6_root_acceptance_outer_review/` 复核：按实际 Training/Evaluation 与实际完整 Coordinator/selected Generation/retained 或 adopted use 分支处理，没有额外固定八条终态条件。本候选没有修改这些入口。

## 验证清单与尚未取得的资格

三条新增 DATA 用例分别覆盖旧七签名整 record 字节/域哈希、六签名无填充并与旧 fact 区分，以及错误长度和元素类型/额外字段拒绝。三条均尚未编译或执行。

真实 Root retained 六签名接受必须在整合后的精确源码上，由原独占 owner 完成原物理读取、完整签名验证、delivery 后检查、Accept 和 daemon ACK，不能由 DATA 测试代替。错路由签名数、该有 LocalDecision 却为空、没有 LocalDecision 却有额外记录、Pending、换 scope、撤销 signer、过期、图像变更、错误 B plan 及重写 first fact 都必须仍拒绝；其中本候选以原代码与源门维持的检查不等同本轮已执行新的动态负控。

不改 old NoUpdate9 失败，不移动冷 32-overlay/36-originals 的冻结证据。冷组合仍需在普通整父真实成功后重新绑定最终源码并执行其原独立门与完整父。
