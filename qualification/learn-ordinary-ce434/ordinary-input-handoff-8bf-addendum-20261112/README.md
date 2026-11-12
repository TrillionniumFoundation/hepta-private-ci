# 8bf：原普通执行输入交接状态附录

**固定源码：** `8bf3881afa8cccff286fc58909995c96f3e0b260`  
**源码 tree：** `c8730bab75eabe47a3b0b3260a6203a0d86d1443`

原 [488 输入合同](../original-ordinary-input-handoff-20261112/input-contract.json)（blob `09d097abb75b7b2a8069e64cd5d2ab2f6e796e05`）完整保留。该合同中 Candidate Selection/NextUse 的 blanket-deny 描述仍准确记录 488 当时的源码；**8bf 已接回原私有路径的 dispatch 资格检查。普通入口装配、实际原 owner 输入及完整验收仍未证明。** 本附录更新当前解释，不回写历史结论。

完整边界、20 条原 factory 登记、源码与实际观察 pins 见 [current-status.json](current-status.json)。本文件只复用已核的 [453 普通装配审计](../private-original-adoption-dispatch-453-20261112/prior-ordinary-wiring-audit.json)及其 README、7dd/8bf 变更审查和既有 launcher 观察；没有扩大搜库/搜主机，也没有执行 H 或测试。

## 已完成的三处生产变更

| 文件 | 当前变化与限界 |
| --- | --- |
| `authority_host_learning_resident_stages.rs` | 原 Candidate 正向 S/C blanket denial 改为 concrete Candidate 私有资格检查。 |
| `cell_q24_candidate_stage_adoption.rs` | 新私有 helper 复用原 exact cut 5→Selection、cut 6→NextUse、Fresh origin、next-stage、完整 Model cut、期限，并要求已安装原 Root gate。它只决定能否 dispatch，不证明 gate 此刻 CURRENT、原服务已就绪或采用成功。 |
| `cell_q24_model_current_owner.rs` | 两处原 journal readback 显式使用原 trait UFCS，解决 453 实际 full-caller 的 receiver 歧义；journal、key、I/O、fresh 和 fence 原样，不增加部署能力。 |

generic Candidate 的 `execute_stage` / `receipt_attestation` 正向拒绝保持不变；既有 NoUpdate、recovery/read-only 边界未放宽。实际效果仍只能经过原 `gate.begin` CAS、`execute_original_evidence`、同 operation 的 opaque evidence 消费，以及原 Model/E、Version/S/C 的实际读回、完整 panel、独立 principals、peer/pidfd、期限、取消与撤销检查。没有新增 grant、key、UID、principal、连接或公共 owner 接口。参见 [7dd 审计](../private-original-adoption-dispatch-453-20261112/source-guard-audit.json)及 [8bf 修复审计](../model-current-readback-receiver-7dd-20261112/repair-audit.json)。

## 剩余生产装配与原部署输入

| 位置 | 已有接口 | 仍需完成的具体交接 |
| --- | --- | --- |
| 普通启动 | `AgentdProductionStartup::receive → run`；checkpoint 模式的 `with_root_learning_stage_owners`；resident 模式的实际 Q24 profile/enrollment | 当前 checkpoint-only handoff 不含实际 stage owners、B 执行或 C FinalUse。缺 owners 时 `require_root_learning_assembled` 仍拒绝。必须在真正持有 typed 输入的原 launcher 中接线；两种启动模式互斥。 |
| 原 Material / T host | pre-B PanelPolicyV2 → Material ConfigV2/create_v2 → Training Bootstrap ConfigV2/from_original_custody_v2 | 原 files/witness/key、同原 D/T streams、实际 A/B 前冻结 policy 的生产调用者尚未定位并装配。policy 元数据不产生执行权限。 |
| 原 Root / Candidate | 原 profile/intent/exact lease → register → actual stage runtime → 原 stream → enroll | 上游原 Root custody 与 T/E/Model/S/Version/C 初始连接需要由既有 owner/launcher 真实交付，不能从 checkpoint、DTO 或 OS root 推导。 |
| 原 Version / C | `from_original_owners`、ordinary 与各读服务、真正 publish 后的 C runtime | 普通 Version producer/service caller 及其 Model、Artifact、C task、held issuer transport 的实际映射仍未定位。Ready 或 S 签名不替代发布与 FinalUse。 |

上述接口已有实现，因此定位真实持参调用者后，可以继续完成现有生产调用点的接线。再加一个无人调用 wrapper 无法补齐交接。453 审计所列 **20 个空 factory boundary 的完整记录到 8bf 全部原字节保留**；这只是指定范围的声明与源码证据，不是新完成的全域 caller 扫描，也不能推出仓库外没有 launcher。

有三类输入不能靠源码拼出：

- **采用前 B 能力：** 原任务/推理 owner 必须已获准运行 exact candidate 和 baseline，并产生真实每臂 RunStart、Source/Cell/ledger、Outcome。现有 `read_original_v2` 只消费完成事实；普通 Q24 profile 要求 sealed PublishedTask，不能拿来绕过独立 B 的授权。
- **真实评价和独立 principals：** 完整 primary＋非空 retention、metrics/sources、Primary/NI roles、margins、时序/holdout 与比较规则须由原 owner 事前冻结；实际可达性及有效独立 T/E/S/C 身份仍待交付与核验。这里没有替部署选用 fixture profile，也不建议修改旧阈值。
- **C FinalUse 与重启：** 需要原 Version/Artifact 资源和既有 issuer 对真实 Prepared binding 的决定，以及 C 独立鉴权的新 session/RunStart；冷重启还需原 daemon/Root 生命周期与持久化恢复入口。LEARN、S、Ready、模型字节和 OS root 均不能补这些输入。

**issuer 拒绝前，Prepared 可能已经持久化。** 正确拒绝边界是不发布选定 CURRENT、不释放 C 执行 capability；不能表述为 Version 零写入。原 Prepared、Pending/Uncertain、journal/witness、CURRENT 和恢复证据必须保留并实读。

## 已知 launcher 检查的实际结论

唯一已观察的 `/data/hepta-service-root-01.py` 为 1,379 字节，固定 SHA256 为 `9919f15ae0ba3c58fa1630345b51adb566fc1ba18914c0d0051e50075246ef77`。只读、固定 hash、封闭 AST 分类器已实际终态退出 **0**；结果仍为 **`unknown_static_purpose`**。

原证据 commit：[c4234ba](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/c4234ba466b725580ff7797a23a4010c79b7a9ac)；完整 result blob `91410e3eee751cafb4a8b47134b6366726fb91e9`，execution blob `3374417354f753787b4c5f2e3b281e68774ab270`。成功的是分类器本身。目标脚本未执行、引用路径未读取；这一结果既不证明普通 owner 或 Root29 用途，也不证明 launcher 不存在。

## 最小下一步交接

提供 **一个真实既有的 launcher 源码、配置或服务入口 locator，加原 host/deployment 标识和对应 revision（如可取得）** 即可继续。可以只是非秘密路径、服务名或固定源码 URL；不用在聊天中上传私钥、token、完整环境或 custody 内容。

后续从该原入口只读追踪已持有的 owner、连接和 policy，判断哪里能直接消费现有 typed API。locator 只是定位线索，不是执行 capability。限定范围内“未定位”不等于“没有”。

## 当前验收状态

8bf 的 source QA、full caller、native 等实际检查仍 **pending**；主请求提交不等于已启动或通过。445 个 source 方法 / 62 个模块、201 个 native cases / 43 个 groups 和原 Root29 是预期库存，Root29 保留其原实际 201 全通过前置条件。旧候选的 PASS/FAIL 各归旧源码，不迁移给 8bf。

本次同固定源码普通入口的 A、真实 Training/NoUpdate、独立 B＋retention、正向采用、新会话 C、真 daemon/Root 冷重启验收计数仍为 **0**。这不抹除旧真实训练或机制实验。

最终仍要证明至少一个正向采用实例及一个正确 NoUpdate/回退实例。C 的“不同输入”须比较实际任务内容或模型 observation 的独立 digest，并分别证明新 session/RunStart；仅含 run/session/时间的整体摘要变化不够。这是验收证据要求，不新增生产永久禁止重复输入的规则。真冷重启还须同时记录 daemon 与 Root 的新进程/boot 身份、磁盘 CURRENT、私有状态和任何未决效果的原始读回。
