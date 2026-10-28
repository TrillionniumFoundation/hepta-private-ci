# Native 执行候选：实现与验证状态

本候选把中立执行契约、有限 native agent 循环和真实 hepta-runtime 工具后端接起来，供同源 Codex App Server／进程内 facade 对照。当前交付是可运行的资格验证实现；生产 agentd owner 的完整组合尚未完成。

## 已实现的边界

- 把原 Cell／runtime 执行契约移到 `hepta-types`，原 adapter 保留兼容重导出；中立测试随契约迁移。
- 复用固定提交的 execution-core ABI。canonical converter 只作绑定和摘要投影，不创建执行授权。
- native loop 支持上下文字节预算、模型／工具调用预算、真实 Responses SSE、工具执行与结果回填、最终回答、取消和超时。
- 精确请求与操作身份在效果之前持久化。断流／丢回应进入 pending；工具只观察同一个 runtime request，模型只观察原 provider response，不盲目重发 POST。
- 模型和工具进入边界前重新核对宿主 currentness；共享 HTTP client 显式关闭自动重试和重定向。
- 固定三操作夹具 `sum / lines / digest` 使用真实 runtime jobs owner。进程崩溃恢复保留原 job、request digest、物理子进程和 admission。
- 三路 benchmark 和故障注入工具已实现。大二进制指纹计算移出资源采样窗口；评分在模型证据收齐后进行，失败会产生非零退出码。

具体所有权和恢复语义见 [README.md](README.md)、[CONTRACT_CONVERGENCE.md](CONTRACT_CONVERGENCE.md) 和 [OWNERSHIP_BOUNDARIES.md](OWNERSHIP_BOUNDARIES.md)。

## 实际运行的验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| Python 协议、指标与评分门 | 21 passed | `native-final-gates.json` |
| native、共享 HTTP、hepta-types、execution-core | 202 passed，0 skipped | `native-final-gates.json` |
| 独立真实 runtime runner | 14 passed，0 skipped | `native-final-gates.json` |
| scoped `just fix`、`just fmt`、runner 格式 | 通过 | `native-final-gates.json` |
| 原 Codex adapter library 兼容编译 | `cargo check --locked` 通过 | `adapter-compatibility-check.json` |
| 最终 runner release | 构建通过 | `native-final-release.json` |
| 最终 native SIGKILL／恢复 | 通过；一次重启，原工具作业身份不变 | `native-final-kill-recovery.json` 和 diagnostic archive |
| Bazel lock 更新 | 使用隔离内容缓存后通过，锁文件无新增差异 | `bazel-isolated-contents-pass.json` |

原组合 gate job 在完成所有上述测试与格式检查后，因为既有 Bazel 内容缓存缺失 BUILD 文件而失败；仅隔离 output base 的尝试也失败。两次失败日志均保留。随后使用独立 repo contents cache 完成锁刷新，没有删除全局缓存或改变锁要求。不能把原组合 job 写成整体成功。

这些命令没有运行原 adapter 留下的那一项 adapter 专属单元测试；其库与完整依赖链已经编译通过。也没有宣称全仓库 CI 全绿。

六份原始 job 状态和完整 stdout／stderr 位于 [native-gates-20261028.tar.gz](evidence/native-gates-20261028.tar.gz)，归档 SHA256 为 `6cfb4b6e89ab857912ef065bba354d21ca12001ebcc3008036bbbbb7a77c878d`。

## 正式对照的状态与使用边界

正式比较将固定官方 Codex **0.165.0** 源码 `360319d8dee62d87e2d59fc0c21805d79519cfed`，分别构建 App Server 与真实 in-process facade。两个官方候选使用同一源码、同一最小初始化观测补丁、同一工具链；它们不是官方预编译发布二进制。上游声明 Rust 1.99.1，本次资格构建明确使用 Rust 1.95.0，与 native 构建保持一致。

本提交尚未填写正式六路结果。旧 0.164 smoke 和早期 live/fault 记录仅用于协议诊断，不用于性能胜负；其中有额外工具目录、初始化通知和资源采样边界的已知失败。它们及修复后的 smoke 被保存在 [diagnostic-runs-before-formal.tar.gz](evidence/diagnostic-runs-before-formal.tar.gz)，每个纳入文件的指纹在对应 MANIFEST 中。

正式 gate 要求真实工具 stdout、原 call ID 的结果回填、最终答案和实际模型请求中的相同工具目录均成立。资源需包含完整后代和独立 runtime jobs；已声明无法覆盖远端模型计算与 SSH 控制服务，因此不作全系统总资源胜负结论。内核 `memory.peak` 是 cgroup 生命周期值，不能当成单轮峰值。

## 生产切换仍未通过的门

本 qualification 的 `SessionOwner` 固定 generation 1，使用隔离文件锁和持久快照；它不等价于生产 Agentd／Fleet、ThreadStore／QueueStore 和 FinalUse 的组合。

生产接入需要在既有 owner 内完成真实 generation／lease currentness、原操作持久历史、严格恢复、模型与 runtime 的 checked physical entry，以及服务生命周期。未完成时应保留 Codex 后端和原生产路由。详见 [OWNERSHIP_BOUNDARIES.md](OWNERSHIP_BOUNDARIES.md)。

## 关联交付

- runtime 原生库修复与请求观察：[hepta-runtime #75](https://github.com/TrillionniumFoundation/hepta-runtime/pull/75)，runner 固定 `d7d039458c8745bea1bafd24f03635e75a66a2f4`。
- 契约基线：[hepta-private-ci #2963](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2963)，固定 `88a43bece9428b091479712b4c29084720d87123`。
- execution-core 复用来源：`77885b80b574d89f4dd7668d873348e0219cabb7`，完整指纹见 `EXECUTION_CORE_SOURCE.json`。
- 独立 Cell 语义与结构证据：[hepta-private-ci #4131](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4131)。其实验不改变本执行器以制造结构收益。
