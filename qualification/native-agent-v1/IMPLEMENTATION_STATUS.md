# Native 执行候选：实现与验证状态

本候选完成了中立执行契约、有限 native agent 循环和真实 hepta-runtime 工具后端的组合，
并新增可注入的 ModelPort 与同一 ThreadStore owner 内的持久 checkpoint 切片。
正式 Codex 0.165.0 三路对照已运行。生产 Agentd owner 的完整组合仍未完成。
完整数据和解释见 [REPORT.md](REPORT.md)。

## 已实现的边界

- 原 Cell/runtime 执行契约移到 `hepta-types`，原 adapter 保留兼容重导出；中立测试随契约迁移。
- 复用固定 execution-core ABI；canonical converter 只作绑定和摘要投影，不创建执行授权。
- native loop 包含上下文字节预算、模型/工具调用预算、真实 Responses SSE、工具执行回填、最终回答、取消和超时。
- 精确请求和操作身份在效果前持久化。断流/丢回应保持 pending；仅观察原 model response 或 runtime request，不盲目重发。
- `ModelPort` 支持宿主包装真实模型入口与原 Response ID 查询；外部 HTTP peer 检验拒绝入口后零 POST。
- ThreadStore checkpoint 复用实际 live writer、epoch、生命周期锁及 durable SQLite pool，提供 CAS、hash chain、
  原 binding 检验、严格恢复和等待者取消后的 commit guard 持有。
- 三操作夹具 `sum / lines / digest` 复用真实 runtime jobs owner；工具 terminal 要求原物理绑定和完整持久输出。
- 比较常驻 Codex App Server、官方 in-process facade 和 native；V2 测量降低观察成本并显式保留覆盖缺口。

ThreadStore 切片和生产 ModelPort wrapper 尚未被 qualification runner 或 Agentd 消费。
runner 仍使用固定 generation 1 的隔离 `SessionOwner`。
详见 [契约收敛](CONTRACT_CONVERGENCE.md)、[README](README.md)和[owner 边界](OWNERSHIP_BOUNDARIES.md)。

## 实际运行的工程验证

各分组有重叠，不能相加为一个总数。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 初始 Python 协议、指标与评分 | 21 passed | `native-gates-20261028.tar.gz` |
| 初始 native、共享 HTTP、hepta-types、execution-core | 202 passed，0 skipped | 同上 |
| 独立真实 runtime runner | 14 passed，0 skipped；owner 组合 gate 后再次通过 | 初始和 owner gate archive |
| 原 adapter library 兼容编译 | `cargo check --locked` 成功 | 初始 archive |
| 最新 native + ThreadStore | 259 passed，0 skipped | `owner-port-gates-20261028.tar.gz` |
| scoped `just fix`、`just fmt`、strict Clippy | 最终通过 | 同上 |
| Corrected formal auditor | 13 passed | `measurement-gates-20261028.tar.gz` |
| V2 collector | 主机真实树 5 tests passed；本地 fixture 5 tests passed | 测量 archive 和 fixture test |
| 最新 0.165 三路 fault | 各自故障范围通过 | `fault-recovery-0165-final-v1.tar.gz` |
| Bazel lock 刷新 | 隔离内容缓存后通过，锁文件无新差异 | 初始 archive |

最终 owner gate 为 `1a180b9f562-96a-2bfd`。它在修正 map mutex 跨 await 的作用域后通过；
没有新增 lint 豁免。先前的组合 gate 在测试成功后因 Cargo.toml 末尾空行失败，随后严格
Clippy 检出 map guard 持有问题。两次失败及最终成功的完整日志都在 owner archive 中。

初始 Bazel gate 因既有内容缓存缺 BUILD 文件失败，仅隔离 output base 的尝试也失败。
独立 repo contents cache 后锁刷新成功，没有删除全局缓存或改变锁要求。原失败仍保留。

未运行原 adapter 留下的一项 adapter 专属单元测试；其库与完整依赖链编译通过。
这些 scoped gates 不等同于全仓库 CI 全绿。

## 发布后 CI 整理

官方原始构建记录改名为 `OFFICIAL_BUILD.json`，避免被现有 `BUILD.*` Starlark 规则误选，
保留原始字节。native crate 的两条未使用直接依赖及对应 lockfile 本地依赖边已删除；
外部依赖版本、native 与 ThreadStore 的 Rust 实现源码均未改变。
继承的 Python 测试文件格式问题使用锁定 Ruff 0.15.13 修正，完整安装文件哈希和 AST 一致性已核验。

job `1a180ffd6cc-96a-2dd5` 再次通过 259 项 native + ThreadStore 测试、14 项 runner 测试、
scoped fix、fmt、strict Clippy、Bazel 锁刷新和 release 构建。Bazel 锁文件无新增差异。
见 [整理记录](provenance/FINAL_CI_HYGIENE.json)、
[原始日志](evidence/ci-hygiene-gates-20261028.tar.gz)和
[构建身份](provenance/POST_CI_HYGIENE_BUILD.json)。这些结果不等同于全仓 CI 全绿。

正式测量绑定提交 `ea162dd819932d6b962863aebf49908c557b5e3f` 与 native SHA256
`0628b5ea8d919db59b581f66eba64ddc3a6674ee960b6f6b13790e61d27d9f08`。
整理后的构建为 `aa2bca08f38d1e7e44b33784bf419f9e7046421a9447ac528dfde5e0c06f75b5`，
不能将下文的性能数字直接记在这个新二进制名下。两轮冻结运行与原始失败均保持不变。

## 正式对照状态

两轮各有三条 replay 和三条 live 路径：每条 replay 9/9、live 6/6，warmup 1/1。
第二轮原始证据 1,377 文件，102 个模型请求逐一验证 effective body SHA 与预算，
51 个含 warmup 案例验证实际工具、原 call ID 回填和最终答案。
同一工具后端、fixture、模型 alias、任务文本、预算和每路 executor 身份已核对。
[独立审计](evidence/V2_AUDIT.md)

官方 Codex 固定 0.165.0 源码 `360319d8dee62d87e2d59fc0c21805d79519cfed`。
两个 Codex 构建用同一最小观测补丁及 Rust 1.95.0；上游 toolchain 声明 1.99.1。
本次不是官方未修改预编译二进制。native 也使用 1.95.0 和相同 release profile。
最新 release API 记录见 `provenance/UPSTREAM_LATEST_AT_PUBLICATION.json`。

| 第二轮路径 | Replay 中位延迟 | Live 中位延迟 | Replay / live 采样 PSS |
| --- | ---: | ---: | ---: |
| App Server | 2.356 s | 9.337 s | 234.54 / 228.65 MiB |
| in-process facade | 2.314 s | 7.311 s | 212.40 / 204.71 MiB |
| native | 2.101 s | 6.252 s | 39.45 / 40.05 MiB |

第一轮 sampler 耗约单核 87%—88%，其 CPU 不能用于执行器效率结论。
V2 的 100 ms 候选仍未过 5% 校准门；500 ms 候选先声明、校准通过再运行正式六路。
正式 observer CPU / elapsed 为 1.68%—4.02%，六条路径均过门；所有失败和原始源保持留档。

降低频率会漏掉更多短作业/短峰值。部分 detached cgroup 没有任何 CPU 读数，所有 detached
job 最终 CPU 端点缺失；计数只代表已观察下界。PSS complete 仅指所选 PID 在该样本可读。
远端模型和部分 SSH 控制工作未测，不能作全系统资源成本胜负。live 的上下文/请求选项也不同，
token 和延迟差不能全部归因于执行器。各限制与指标解释在 [REPORT.md](REPORT.md)。

第一版 post hoc summary 对 JSON key 排序的错误已用真实 gateway wire oracle 修正，原摘要与
修正审计同时保留，没有修改原运行记录。旧 0.164 smoke 和早期失败仅属于诊断 archive。

## 原操作恢复的准确范围

三路 fault 都验证了原 request/job、物理作业关联与回填，没有新建操作替代原效果。
native 杀整个 qualification runner；Codex 两路只杀 runtime helper，Codex 核心仍存活。
因此没有完成等价的三路 whole-agent 故障比较，未测不能计作 Codex 失败。

官方 Core 的 `recover_turn_if_idle` 确实存在，但会重启模型采样；当前 facade/App Server
未验证冷进程原 pending callback 续接。native live gateway 也未验证真实 provider 的
retained-response GET。详见 [CODEX_RECOVERY_BOUNDARY.md](CODEX_RECOVERY_BOUNDARY.md)。

## 生产切换仍未通过的门

需要用真实 Agentd/Fleet、run coordinator、LiveThread/QueueStore 组成 TurnOwner，
接入已实现的 checkpoint，并完成原 history/queue 的恢复映射。
模型和工具必须复用同一 production writer 的 receipt、外部 grant provider、
一次性 dispatch claim 与 FinalUse token，在真实效果入口重查 lease/generation/撤销/取消/期限。
泛型单结果 target 还需补齐 SSE 流的受检交接；测试 gate 不是生产 grant。

服务 startup、readiness、drain、AuthBus 及 supervisor 生命周期也未切换。
本轮没有迁移或重启生产 Agentd，保留原 Codex 后端及路由。
[完整边界](OWNERSHIP_BOUNDARIES.md) · [模块决策](ARCHITECTURE_DECISION.md)

## 关联交付

- runtime 修复及请求观察：[hepta-runtime #75](https://github.com/TrillionniumFoundation/hepta-runtime/pull/75)，固定 `d7d039458c8745bea1bafd24f03635e75a66a2f4`。
- native 实现及资格比较：[hepta-private-ci #4151](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4151)。
- 独立 Cell 语义及结构证据：[hepta-private-ci #4131](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4131)；不通过更换执行器制造结构收益。
