# B11 八行物理观察的判定与真实修复门槛

原 V5 ledger 的 B11 退出条件保持原文：

> 在获准的修复范围内提供原生 helper 与原严格 token 契约，原攻击/权限/文件系统用例全部通过；需要超出已允许边界时明确升级审批。

来源为 `continuation-blocker-progress-v3.json` 的 B11 行（完整文件 Git blob `8c2c3dc39708fb6dcaf0004490fca67e784deaa4`，SHA256 `1ab45660bb0dfe59ee9cab41f1cc9c17c7ffa577e8dc7ccde88070670ca95b7e`）。其 `closure_class=OPEN` 未改。历史审批原件缺失不是新拒绝或永久禁止；实际产品接口或授权范围变化需按具体变更判断。

## 先判观察是否有效

必须绑定 #4884 实际 checkout/tree、Windows 平台、原六个名字、完整八行、实际 token IL/policy、effective thread token、对象身份、SD、恢复及物理 post-state。缺行、setup/readback/restore 错误、跳过、取消或只有缓存结果，均不能解释成新鲜物理通过。API 的 queued `started_at` 也不证明 runner 已执行。

新 probe 的 PASS 只说明 fixture/read/legitimate-inside/host 正控和清理条件满足。它允许原样报告外部操作成功。AccessCheck 是同 SD 的辅助观察，不能替代真实 I/O；判断删除必须同时看调用结果、DeletePending、观察句柄关闭后的名字结果，不能仅看某个 error code。

## 八行判定表（当前没有本 PR 的原生结果）

| 行 | 主体 / outside 对象 | 有效结果如何指导下一步 | 不能据此宣称 |
| --- | --- | --- | --- |
| 1 | host / Medium | outside 和 inside 的读、创建、覆盖、文件与目录删除都应实际成功；否则先排 fixture/对象访问问题，不能把 host 失败当 sandbox 拒绝 | 任何隔离效果 |
| 2 | host / Low 另一 cohort | 同样要求 host 正控成功，确认设置 Low 与保留 share-delete 句柄没有制造假拒绝 | Low 对象自动具备 cohort 隔离 |
| 3 | current strict / Medium | outside 删除若成功且读成功、覆盖/创建被拒，支持重现现有 parent DELETE_CHILD 缺口；若删除被拒，先比较实际 IL/policy、完整 SD、物理 endpoint 和旧例环境，生产源码并未因此改变 | 仅此一行改变已修复现有生产 token |
| 4 | current strict / Low 另一 cohort | 检查同一 cap 分离在不同对象 IL 下是否仍漏删除。所有具体操作结果均保留；不能预设当前 strict token 是 Medium，须读取实际 IL | Low 之间按 cap 自动隔离，或与旧 host 完全等价 |
| 5 | strict 降至 Low / Medium | 只有 outside 读取和 inside 合法 I/O仍通过，而 outside 创建/覆盖/文件及目录删除都真实拒绝时，才支持继续研究有限 MIC 路线；任何遗漏的操作继续开放 | 给生产 token 普遍降 IL 已足够，或 loader/IPC/所有 Medium 目录已验证 |
| 6 | strict 降至 Low / Low 另一 cohort | 用来判定 MIC 对同 IL 另一 cohort 是否缺乏区分力。若仍可删除，就必须增加实际对象/能力隔离，不能把第5行成功扩成跨 cohort 安全 | MIC 在同 IL 下必然能表达 writable-root 权限 |
| 7 | full restricting＋显式 read SID / Medium | 只有有限 outside read、inside 正控都成立且全部 outside 变更被拒，才支持设计明确 read-set/write-set 的真实 caller 接口；若失败，先依据实际操作和 SD 定位，不能删除 read 正控 | 当前 base-token＋capSID API 已能无缝保留任意 ambient read，或进程加载已通过 |
| 8 | full restricting＋显式 read SID / Low 另一 cohort | 与第7行共同判断能力路径是否不依赖 Medium/Low 差异；仍只覆盖本任务枚举的对象，不能从单次 AccessCheck 推导所有路径 | 任意新路径、重命名/替换、继承、IPC、loader 或跨进程 effect 已被授权/隔离 |

## 可立即推进的工程动作与保留的门

如果第5行成立而第6行仍允许删除，下一小片应设计明确 opt-in 的 owned writable cohort、label 设定/恢复/对象替换生命周期，并保持 Medium outside 的原合法读取。不能直接全局降低 token IL、修改未知系统 ACL 或删掉跨 Low 用例。

如果第7、8行成立，下一小片应把显式读取能力与写能力带到正常 caller，先明确 loader、配置、IPC 等必须读取的真实集合和新增对象规则。有限 fixture 的 read SID 不是给任意系统路径加 ACE 的授权，也不是当前 token-only 接口已经完整的证明。

若两路线都未满足合法读取/inside I/O与外部拒绝，保留原结果继续研究其它隔离机制；不得使用 blanket Err、跳过、放宽 exact 断言或换一个无同等攻击面的 backend 当闭合。

即使新 probe 八行全部有效，B11 仍要经过真实产品修复、正常 helper/backend 调用和原攻击/权限/文件系统门。原三项严格测试、两项四格控制与完整所属 target 必须在明确源码/平台上实际执行并保持原断言；本同步 probe 不启动子进程，不具有 Job 后代、loader 或完整 helper 资格。最终是否闭合仍按原 ledger，不能按 probe PASS 或一个 target 状态重分类。

本表是预先固定的解释规则，未预填 Windows 结果；不是对 #4884 尚未完成 CI 的结论。
