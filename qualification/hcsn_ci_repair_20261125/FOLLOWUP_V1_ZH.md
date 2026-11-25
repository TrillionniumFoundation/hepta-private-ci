# HCSN 集成 CI 的后续证据 v1

这是精确源码 `a638030ee1f57a11c101d68f2537af17b38a5dcd` 的冻结记录。其托管合并树 `92b4e21db61532622d39a14f29e01bfe81a6e715` 与源码树相同；主 blocking run `45534615882` 已终态失败：46 个 job 中 33 成功、6 跳过、7 失败，无运行中或取消项。

7 个失败 job 对应三组根因及其聚合门禁：Windows shard 4 的三个原 Core elevated 阳性失败；musl Q24 原始 500 ms evidence 截止时间失败；learning 两条 lane 的严格 Clippy 因 cell-role WAL 大枚举失败。聚合门禁不是另外三个实现缺陷。旧 c4 blocking run 为 cancelled，原始记录也保留。

## 已有真实通过

- a638 的 Windows 路由目标已通过，证据在同级 `windows_route/`；整 shard 仍因 Core 三阳性失败。
- 原 Windows private-state 清单 36/36 与原 JUnit、逐项日志完全相符，0 选中失败/跳过、0 重试；独立重复的 signed-credit case 已包含在 36 中，没有重复计数。两个目录 guard 阳性通过，两个原 mutation 命中预期失败。它不构成 Core 进程隔离资格。
- Bazel Clippy 的既定配置通过；该配置仍有 warn 级别，不能等同所有 crate 的 `-D warnings`。完整日志与准确覆盖范围在 `ci_coverage/`。

## 正在闭合的严格门禁

私有 WAL `Prepare` 载荷的 Box 修复及两项等价测试 lint 修复通过原 119 个具名测试和 cell-roles 全目标严格 Clippy。源码候选提交为 `469f49a0685a2af72bda5e1e2334daf9f3fad6d3`；冻结时还未推进源码分支。

随后真实执行原 Bellman、Agentd、shadow 三包严格命令，得到 7 处 rmcp-client `ClientInfo` 弃用错误。该次完整失败、430.197 秒 wall / 710.922 秒子进程 CPU 及未漂移的源码身份保留在 `cell_roles/full_learning_v1/`。不能把前一局部通过写为整条 lane 通过。两个 RMCP 文件的精确别名迁移正在另外验证。

musl 原 trace 显示客户端约 501 ms 返回超时，而串行服务工作已能证明至少 562.824 ms；不能将其描述成只差 1 ms。保留原日志、逐阶段时间及源码审计。新的 witness 缓冲读取候选另有预先冻结的原生配对验证，本快照不声明其性能通过。

Windows Core 的三个原阳性仍失败。已发布的 `CORE_ELEVATED_BOUNDARY_REVIEW.json` 说明无条件生产拒绝发生在 fixture ACL 生效前；局部 fixture、删测试或撤安全 guard 不能关闭此阻塞。

本目录所有原日志、旧 verifier 失败和证据均保留。新增数据未改写原始研究的 177 次训练、失败 holdout 或任何阈值。后续修复及最终源/合并树资格会以新的记录追加。
