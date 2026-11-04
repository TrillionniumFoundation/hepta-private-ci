# B16-R0：正常入口源码证据增补

**结论：B16 同时存在仓库内接线缺口与后续真实接受门槛，不能归结为只缺外部凭据。** 本增补独立复核 architecture 的固定源码证据 `4272a55179316d39863378a53023944dfef1a8d8`；原闭合计划 `dddedf9b0e4662d2126f925c765c6ea73976f729` / `0b98a426215dd3b947389587379599bb936b15c5` 保持不变。

## 已查明的两个正常入口缺口

| 范围 | 当前固定源码事实 | 对后续工作的影响 |
|---|---|---|
| Root 正常 producer | Desktop `c42eccaf8b9b5a163d0c52b1a3c42466fe0f425b` 与旧 `c2c369836e87e9cf27b4dc9aa8b7446e85efdf90` 的 services 同为树 `247dfcc7a451b8bd6926fe2d5013120ace0c984d`。实际 hepta-desktop-root 仍生成 Notes seed/profile，传 `--root-production-profile notes`，启动 `--notes-root-bootstrap-stdin`，使用 Notes principal 与 TextRecovery issuer profile。 | 新 PR 编号没有补出正常 Notes+Calculator producer；需要在原 Root 权威链内实现真正 joint producer。 |
| 当前 UI consumer | c42/c2 已分叉：12 ahead、2 behind，合并基点 `fd8d56c52b971c2d5d0e6430f296803b43ef60a3`。c42 完整 UI 树缺旧 c2 的 desktop_startup、calculator、calculator_lifetime、desktop_bootstrap、calculator_organ 五个模块；实际 Session parser 无 DesktopReserved / `--desktop-root-bootstrap-stdin`。 | 不能假设 #293 继承旧 #281 全部联合接线。需冻结兼容的两仓版本并将真正 consumer 接入正常入口。 |

上述缺失结论限定于完整树中的五个指定模块和实际被审 producer/parser；不声称当前 Desktop 全部功能缺失，也不否定尚未提供的其他外部 embedding。

## 可以复用的严格组件，及必须保留的现有合同

Donor `14e2d89b3367232ec5dbe6187f09feed0f2b68d3` 已有严格联合 reservation consumer：`root_desktop_startup.rs` blob `4dc5fb941e4e082bb41447d4ec2faaf4cc412bd2` 要求 schema `hepta.root.desktop_launch_profile.v1`、profile `notes_calculator_v1`，且 `grant_lifetime_ms` 为 1–30,000；它消费原 Session release、保持原 issuer/pidfd 身份。这个 **30,000 ms 联合 grant 上限**与旧计划中整体 Root 生命周期的 300,000 ms 不是同一字段。旧 Notes recovery 与续租不能改名当作联合恢复已完成。

迁移必须同时保留下列当前产品合同：

- **原 writer/checkpoint/sender 所有权。** ff72 的 `production_composition.rs`（`1464029ba8643aa7a44f3835d0ab700bb3673156`）返回 `AgentdProductionHostAttachment<C>`，含绑定同一恢复 writer、同一 checkpoint Arc 的 original_sender；donor 同函数只返回 `Option<NotesTargetIdentity>`。不能整文件覆盖。UI 仍必须接收真实 attachment 与原已签名请求，校验 owner/generation/run/expiry/draft，保持一次发送和 recovered 不重发。
- **原普通 peer 边界。** ff72 AppServer UDS（`0cb230d72e799350eef0405deb2f34d4ef8d79ac`）在每次普通 WebSocket upgrade 前调用 `ensure_current_user_peer`；donor（`f419409fb1004e1e9e74e4ef0e033e4ba880756b`）所见门禁只在 Linux inherited 路径检查 current-user-or-root。整文件移植会遗漏当前普通连接门禁。现有 owner_local 导出与实现也须保留；任何显式继承 Root 路径须保持其原认证交接合同，不能变成普通连接的宽松例外。
- **原真实 daemon 绑定。** Objective client 当前在每次 I/O 校验 kernel UID/PID，保留窗口、帧边界、代际、checkpoint-before-send 等检查。新增正常 caller 不能在 UI 中新建 writer、签名器或替代信任源。

## 本轮源码资格与下一步

独立回读的 12 个主要 blob、18 段引文均逐字匹配且 Git/SHA256 校验一致；两 UI、services、两 Agentd 递归树均完整。另核对入口、Objective transport 与普通 UDS 源。ff72 到候选树 `a69b20c4c3cfee9cf483496742d6bea1469d847a` 的 Agentd 仅两个测试文件变化，全部生产 src/Cargo 不变；五个相关支持 crate 也同树。因此这些源码缺口在 a69 仍存在，**这不是运行接受资格，也不自动覆盖之后未检查的树。**

B16 建议保持 **REPOSITORY_INTEGRATION_AND_REAL_ACCEPTANCE_PENDING**。R0 中“实际正常 producer 是否已经联合”的子问题现已查明为 Notes-only；完整 R0 迁移和 B16 没有闭合。

下一步先冻结 Hepta/Desktop 兼容输入，将六组依赖合同与真实 Root producer、正常 UI caller 一起整合并做同源原资格验证；再使用真实 operator 配置的 Root/Session/issuer/provider 身份与已签名 objective 完成原 Core Notes+Calculator、到期/撤销/恢复/拒绝接受。未使用 helper、测试替身、自造签名或 donor 的另一 head PASS 均不能代替这两个门槛。

本增补仅做只读源码审计，没有启动 Root、修改权限生产源码、运行构建或改变 ref。Windows 既有生产边界审批问题没有被扩大为一般 Root 迁移禁令。
