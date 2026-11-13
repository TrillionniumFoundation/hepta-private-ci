## 当前状态：E1 源码候选已固定，历史材料解包正常，完整文件读回进行中

本 PR 处理“证据不足被误记成比较结论”、原 owner 到实际消费者的接线，以及恢复证据缺口。目标是让结果由真实任务、原权限和独立观察决定，而不能通过改目标、评价口径或奖励定义证明进步。

**真实合格任务链仍为 0，qualification=false；PR 保持 draft。** 三个源码状态明确分开：

| 源码 | 身份 | 当前用途和验证范围 |
| --- | --- | --- |
| 本 PR 源分支 | `cc57c7198db6293ccca562253c42fffbe2a04633` | 本轮保持原 head |
| 实际 H 隔离候选 | `b6084394a4a38ab495c16eaba09e879f04a96f8e` / tree `8ebb37e523ad3932a58cf016af0a9f4e0eeb6638` | 5a9 已完成实际 HEAD/index 对齐；原 source/native 资格仍未通过 |
| E1 新审阅候选 | [`99fada80470f175ba14004ea9fcb006853c7d98f`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/99fada80470f175ba14004ea9fcb006853c7d98f) / tree `3778225f2d49dcd4729d05c02ae9805b43df87d8` | 以 b608 为父提交，保存在独立 `codex/utility-root-assembly-proposal-20261113-36fa`；尚未格式化、编译或执行门禁 |

### 产品代码已推进到的边界

E1 现在把原 protected Host Session、issuer、Registry lease、Artifact 与 FinalUse owner 绑定到同一个 initial operation，保留完整签名、撤回/head/frontier 观察、一次消费、原 publication 和同 operation recovery。只读 binding 请求返回完整请求数据；实际授权仍由原 owner 提供。Ready 经原工厂进入同一 Task/Cell/Source custody；lease 前后观察不声称跨副作用的原子租约。

Root 已核 19 个实际源码 blob、8 个改变的 tree、精确 commit parent/tree 及审阅分支读回：11 个原文件修改、8 个新增、其余 15,232 个原文件及 mode 保持。独立审查发现的缺失 import 已以单独 70-byte 增量修正。原 633 boundaries / 442 protections 保留，仅九个旧边追加明确 caller，再增加 17 boundaries / 九项保护；原 48 个 Root parents 顺序完整保留，追加六个 E1 机制用例。**这些登记和用例均未作为已执行 PASS。**

E2 的 Config-free factory 接缝和两个机制用例已单独冻结、独立审查。一个过宽的错误断言另层收紧为精确 reconciliation 拒绝，并检查同 generation/journal。实际 IPC 仍在实现：daemon 保留原 driver、AutomationStore、opaque admission、CommittedTrace 和 private receipt；Root 持有实际 Cell 计算及同 Task/Cell/Source。wire JSON/完成 ACK 不得构造原 authority 对象。E3 正常 Root CLI、十个真实 role channels 与 V3 completed-A late enrollment 正在接线；这不是已经完成的普通产品链。

### 实际执行与失败保持原语义

- **41e / 50f / 5a9：** 原 scoped just fix / just fmt 正常 0，末次 fmt 无新变更；随后 29 个 typed Git objects、94 条命令和 33 项 mutation intent 完成实际 b608 对齐。完整 15,243 文件、raw index 与原 uid/gid/ns 元数据已核。旧 fix101 失败不被覆盖，这些维护结果不等于资格通过。
- **原 65a：** 唯一 source 请求在预检 failed / exit 1，driver_main_entered=false，三个 source gates 和 native phases 均 0。历史 3bb RESULT 路径与原成功 SDK 相符；该路径为何不可用保持 Unknown。finally 在 initial_git 尚为 None 时报告 SourceChanged，原错误保留，但不足以证明源码变化或欺诈。完整 94 文件失败窗口已归档。
- **当前历史材料 stage：** issued approval `75003db540da7000de0b350b5fa53ac0b61c6644` 仅允许冻结的 17 次 create-only 写入和唯一 stage 请求 `e944fa3dd289d28901cc216e4e05cce26e636a38`，原 900 秒预算不变。实际 job `1a1d52e0d88-392-784` 为 succeeded / exit 0，完整持久输出和 terminal publication 已确认，无 timeout/cancel/retry。原第八片 helper255 读失败保留，通过同 path/version/offset 缺块读回闭合，没有第二次 write。
- **当前读回界限：** Root 已独立核监督器、完整 streams、原 dispatch 和完整 STAGING_READBACK。清单精确列出 55 原件及五控制文件，加收据自身共 61 个必读文件；**全体逐文件读回尚未闭合**。admission 回显的完整程序、host、cwd、key 均匹配；stdin 文件仍在完整读回集合中。此 stage 没有启动新 source/native main。
- **下一 admission 修正：** `fd67cb043f7b6cb8cf042104ac202cb5f0842196` 只在原初始基线未建立时返回 Unknown，保留实际 after 观察；完整逆差恢复 299c，其他原 guard 与已知差异判定保留。它仅是已审后继，旧 65a 和 consumed approval 不变，新的 source/native 请求尚未获批。

### 仍须完成的验收

完成实际 transport 的 61 文件闭合后，再单独冻结与审查 b608 原 source/native 请求，保持原 14 phases、原 packages/filters/预算和 **48 个 exact Root FQN/JUnit 名称**。E1/E2/E3 的新源码需要自己的精确版本登记、格式化、编译和原门禁，不能承接 b608 的结果；skip 不算通过，同进程 reopen 不算进程冷恢复。

最终仍须证明 **真实授权 A → 原 Training owner → 独立 B → Adopt 或完整 NoUpdate → 实际新 C → daemon 与 Root 进程冷恢复**。完整部署组合、最强可部署对照、旧/稀有/必过任务和冻结的全成本账必须有实际证据。缺结果、材料、来源、独立性、成本或原 owner 授权保持 InsufficientEvidence/Unknown。完整不采用与可复现的确定性欺诈各保留自己的语义；有限 fraud 源码审查没有认证生产挑战/处置链，也不声称全仓不存在。工程审批不是 Hepta 运行时授权，内容根也不证明持续可用、合法授权或真实采用。

[当前证据索引](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4ada511b1a79417bee29eddc4f67d769ca1354d6/qa/evidence/utility-evaluation-20261112-36fa/README.md) · [E1 源码发布闭合](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4ada511b1a79417bee29eddc4f67d769ca1354d6/qa/evidence/utility-evaluation-20261112-36fa/e1-source-candidate-v1/PUBLICATION_CLOSURE.json) · [Root stage 核对](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4ada511b1a79417bee29eddc4f67d769ca1354d6/qa/evidence/utility-evaluation-20261112-36fa/root-history-stage-core-review-v1/REVIEW.json) · [完整 65a 失败重放](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4ada511b1a79417bee29eddc4f67d769ca1354d6/qa/evidence/utility-evaluation-20261112-36fa/root-source65a-complete-closure/ROOT_SOURCE65A_COMPLETE_FAILED_WINDOW_REVIEW.json)
