# Native agent 与 Codex 0.165.0：实现、对照与放行边界

## 结论

本轮交付了可运行的有限 native agent、共享执行契约、真实 runtime 工具桥、可注入模型端口，
以及同一 ThreadStore owner 内的持久 checkpoint 切片。三条常驻路径在两轮固定响应重放和实测中
均完成预定任务；正式第二轮每条路径重放 9/9、实测 6/6，另各有一次成功 warmup。
这证明指定的三操作工具闭环已工作，不等于完整 Codex 能力或生产迁移已完成。

在第二轮相同测量配置下，native 的所选进程范围采样 PSS 和有限任务延迟较低。
但模型服务及部分 SSH 控制工作未计入，短命 detached jobs 的 CPU 计数不完整，
模型上下文和部分请求选项也不同。因此不能据此宣布完整系统资源、模型效率或一般任务成功率领先。

架构上建议独立发展中立契约、native 库和薄 Codex adapter；是否独立进程、独立仓库应另行决定。
当前证据不要求长期 fork 整个 Codex，也不支持默认一个 Cell 一个完整执行进程。
Cell 语义入口和自适应结构的独立结果在 [#4131][cell-pr]；其未通过的科学门槛不能由本轮工程通过替代。

## 交付及身份

| 项目 | 固定身份与范围 |
| --- | --- |
| Hepta 契约基线 | `88a43bece9428b091479712b4c29084720d87123`，原 #2963 |
| execution-core 复用 | `77885b80b574d89f4dd7668d873348e0219cabb7`；原文件指纹在 `EXECUTION_CORE_SOURCE.json` |
| runtime native library | [#75][runtime-pr]，`d7d039458c8745bea1bafd24f03635e75a66a2f4` |
| 官方 Codex | [0.165.0][release]，`360319d8dee62d87e2d59fc0c21805d79519cfed` |
| 三路构建工具链 | Rust 1.95.0；官方源码声明 1.99.1，本次是明确记录的资格构建覆盖 |
| 模型 | 同一 Responses endpoint，alias `qwen38-flash-next-uc`；provider weights/deployment 未固定 |
| 测量对象 | native qualification runner、常驻 App Server、真实官方进程内 facade 包装器 |

发布前重新读取官方 release API，最新非预发布仍为 0.165.0，发布时间 2026-10-27 20:09:38 UTC。
记录见 [UPSTREAM_LATEST_AT_PUBLICATION.json](provenance/UPSTREAM_LATEST_AT_PUBLICATION.json)。
官方两条路径使用相同最小初始化观测补丁；workspace 本地 package 版本锁调整和 wrapper 均留档。
不能把它们称为未经修改的官方发布二进制。[官方构建记录](provenance/official-0165/BUILD.json)

最终 native release SHA256 为
`0628b5ea8d919db59b581f66eba64ddc3a6674ee960b6f6b13790e61d27d9f08`；
App Server 为 `7b9a74955391ef21e56a021cd119c0e934d42d4b24339bccf0af8c74abc331cc`；
facade 为 `4f96fb3aa150f7f182f4527da2e83ce836a7a77d08206ce69dee294a049563a8`。
native 与官方使用相同 release profile 设置。构建后仅测试文件发生 lint 修正，生产输入未变；
该调和核对位于 [POST_BUILD_SOURCE_RECONCILIATION.json](provenance/POST_BUILD_SOURCE_RECONCILIATION.json)。
ThreadStore checkpoint 切片没有链接进这个 runner，不能把其生产成本包含在本次数字中。

## 实现了什么

中立 Cell/runtime 契约移入 `hepta-types`，原 adapter 保留兼容重导出；execution-core 使用现成实现。
canonical converter 仅绑定关联数据，不成为新的授权或状态 owner。
线程、turn、根 operation 和 generation 由宿主提供；模型和工具各保留子操作及原请求关联。
runtime 的 job、物理启动、取消、输出和终态仍由原 jobs owner 管理。
[契约收敛](CONTRACT_CONVERGENCE.md)明确区分 admission、accepted、pending 与 terminal。

native loop 完成用户输入、上下文组装、真实 Responses SSE、固定真实工具、结果回填及最终回答。
它限制请求字节、模型和工具调用次数、输出 token 请求、工具输出及等待时间；上下文限制是字节，
不是 tokenizer context-window 保证。解析支持分片 UTF-8、CRLF 和跨帧事件，只有完成且身份一致的
模型响应才能产生工具意图。资格 JSONL 接口返回最终结果，没有宣称已做逐 token 的用户界面。

模型 POST 及工具提交前写入精确原请求和 pending 状态。丢回应后观察同一请求；
模型只能查询已有原 Response ID，不能用重新 POST 判断前次是否发生。
工具恢复使用 `observe_request(original_params)`，缺本地记录不代表未执行。
取消优先于新入口，已取消或已尝试的 admission 恢复后保持观察模式。
终态需要原 jobs owner 的物理绑定、退出结果和完整持久输出；accepted 不产生成功回答。

新 `ModelPort` 允许宿主包装 `open` 和 `reconcile`，保留原响应解析器和精确 pending body。
新增的真实 ThreadStore checkpoint API 复用原 live writer、写入 epoch、生命周期锁、CAS 和
SQLite durable pool；恢复拒绝缺失或损坏链，不继承 fork 的 pending，不把原 generation 改成新代次。
等待者取消后，owner task 继续持有 guard 至提交完成。它没有声称与另一 rollout 文件原子提交。

这两个切片已实现并测试，但 qualification runner 仍使用隔离的 `SessionOwner`，generation 固定为 1。
ModelPort wrapper 和 checkpoint API 尚未组合成生产 Agentd/Fleet、QueueStore、FinalUse 和
真实 lease verifier 下的 native `TurnOwner`。[所有权边界](OWNERSHIP_BOUNDARIES.md)

## 验证记录

以下分组有重叠，不应相加得到一个虚构总测试数。

| 检验 | 实际结果 | 原始证据 |
| --- | --- | --- |
| 初始 native / HTTP / neutral types / execution-core | 202 passed，0 skipped | `native-gates-20261028.tar.gz` |
| 真实 runtime runner | 14 passed，0 skipped | 同上；owner 切片后组合 gate 再次通过 |
| 初始 Python 协议、指标、评分 | 21 passed | 同上 |
| 原 adapter 兼容编译 | `cargo check --locked` 成功 | 同上；未运行留下的一项 adapter 专属测试 |
| 最新 native + ThreadStore | 259 passed，0 skipped | `owner-port-gates-20261028.tar.gz`，最终 job `1a180b9f562-96a-2bfd` |
| scoped `just fix` / `just fmt` / strict Clippy | 成功；未放宽 correctness、expect 或 await-lock 规则 | 同上 |
| Corrected formal auditor | 13 passed | `measurement-gates-20261028.tar.gz` |
| V2 scope collector | 真实受控树 5 tests passed；另有本地 fixture 5 tests passed | 测量 gate 与 `test_process_metrics_v2_fixture.py` |
| Bazel lock 刷新 | 隔离内容缓存后成功，锁文件无新差异 | 初始 gate archive |
| 最新 0.165 三路 fault | 各自声明的故障范围均通过 | `fault-recovery-0165-final-v1.tar.gz` |

初始 Bazel 内容缓存错误、首次 owner gate 的末尾空行、严格 Clippy 检出的跨 await 持有 map guard，
以及两次测量校准失败均保留。map guard 已通过缩小作用域修正，未增加 lint 豁免。
最终成功不能抹去此前失败，也不能替代全仓库 CI 状态。
[工程状态](IMPLEMENTATION_STATUS.md)与各 MANIFEST 绑定原始日志。

## 正式比较设计

三条路径都常驻，单个案例创建新线程/会话；没有用每次启动新 CLI 作为 Codex 对照。
同一个 runtime release 和三个只读操作 `sum / lines / digest` 服务全部路径。
native 在进程内调用 runtime；Codex 使用同一个常驻 helper，该 IPC 是实际组成的一部分。
facade 内部使用官方 `InProcessAppServerClient`，外面仍有资格 JSONL 包装，不是零序列化估计。

每路重放 3 轮共 9 个正式案例，实测 2 轮共 6 个；每路另有 1 个 warmup。
共同上限为模型请求 65,536 B、每响应 256 output tokens、4 次模型调用、3 次工具调用、
32,768 B 工具输出及 240 秒案例时限。每个成功案例实际上使用 2 次模型调用和 1 次工具调用。
计分要求真实 stdout、原 call ID 回填、最终 canonical JSON 和唯一共享工具目录同时正确。

六路顺序在执行前冻结：replay native / App Server / facade，然后 live facade / App Server / native。
各自新建资源组，申请 CPUQuota 400%、MemoryMax 8 GiB、nice 10；报告实读 CPU 和内存限额一致，
nice 和有效 cpuset 未被独立观测。构建与测试在正式执行前结束。
小样本、顺序、主机及 provider 缓存没有变成随机化控制；结果属于探索性验证。
[冻结计划](FORMAL_PLAN_V2.json) · [完整协议](BENCHMARK_PROTOCOL.md)

## 第二轮正式结果

延迟排除 warmup；采样 PSS 为同一轮采样中所有已选 PID 均成功读取 PSS 时的合计峰值。
这些读取并非原子同时发生。
它覆盖所选后代和显式 detached jobs，不只是主进程 RSS，也不等于全部系统或全部瞬时峰值。

| 常驻路径 | 重放成功 | 重放中位延迟 | 重放最大延迟 | 实测成功 | 实测中位延迟 | 实测最大延迟 | 重放 / 实测采样 PSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Codex App Server | 9/9 | 2.356 s | 2.621 s | 6/6 | 9.337 s | 11.754 s | 234.54 / 228.65 MiB |
| Codex in-process facade | 9/9 | 2.314 s | 2.614 s | 6/6 | 7.311 s | 9.717 s | 212.40 / 204.71 MiB |
| Hepta native | 9/9 | 2.101 s | 2.182 s | 6/6 | 6.252 s | 7.363 s | 39.45 / 40.05 MiB |

各路 warmup 均成功，但进入整路资源窗口。9 或 6 个样本的 nearest-rank p95 就是该组最大值，
不能包装成稳定的尾延迟估计。[正式摘要](evidence/FORMAL_V2_SUMMARY.md)
[逐请求审计](evidence/FORMAL_V2_SUMMARY.json)

| 实测路径 | 正式案例 input tokens | output tokens | total tokens |
| --- | ---: | ---: | ---: |
| App Server | 29,820 | 975 | 30,795 |
| facade | 30,158 | 801 | 30,959 |
| native | 16,986 | 780 | 17,766 |

用量来自完整 SSE 的 `response.completed.usage`，不把 replay 合成字段当实际消耗。
102 个正式及 warmup 模型请求的 effective body SHA 全部核对；预算、模型 alias、任务文本和工具后端一致。
Codex 原始请求未设置 `max_output_tokens` 的字段保持 unknown，gateway 实际转发上限 256 有原始字节证据。

两种 harness 的 model-visible protocol 并不完全相同：Codex 使用 `store=false`、
`parallel_tool_calls=true`、function `strict=false` 及 reasoning 字段；native 使用 `store=true`、
`parallel_tool_calls=false`、`strict=true`，上下文包装也更短。
因此 live token/延迟差包含上下文和请求策略差异，不能全部归因于执行器。
同一 alias 也不保证不可变模型权重或相同 provider 调度。[独立审计](evidence/V2_AUDIT.md)

## 采样器修正及资源缺口

第一轮使用全主机 `/proc` 扫描，观测器耗用约单核 87%—88%；该轮所有任务成功，
但 CPU 严重受测量扰动，不能据此比较执行器 CPU 效率。第一轮原始记录完整保留，未挑选或删除慢案例。
V2 改用所选 cgroup 和所有已选 task children 的枚举，保留 fresh PSS 读取和两次进程身份检查。

V2 的 100 ms 候选两轮校准仍耗 12.22% / 12.30% 单核，未通过预定 5% 门槛。
500 ms 候选在正式运行前声明，两轮受控树校准为 2.43% / 2.53%，身份集合一致，无 gap 或 fallback。
第一次 cadence 脚本在已运行完各臂后因缺省零计数键发生汇总 KeyError；没有完整 report，记录为失败。
修正脚本先保存原始结果，再用计数器缺省零语义评分。门槛没有放宽。

| mode / 路径 | 实际 observer CPU / 整路时间 | PSS 完整 / 不完整样本 | 已观察 cgroup CPU | 已观察 process CPU | 无 CPU 计数 cgroup / 已请求 cgroup |
| --- | ---: | ---: | ---: | ---: | ---: |
| replay App Server | 3.995% | 46 / 4 | 12.967 s | 10.290 s | 8 / 11 |
| replay facade | 4.019% | 48 / 0 | 12.601 s | 9.750 s | 6 / 11 |
| replay native | 1.973% | 42 / 2 | 8.554 s | 6.810 s | 8 / 11 |
| live App Server | 3.306% | 147 / 2 | 13.118 s | 10.920 s | 3 / 8 |
| live facade | 3.492% | 112 / 2 | 11.581 s | 8.900 s | 2 / 8 |
| live native | 1.683% | 93 / 1 | 6.923 s | 5.340 s | 4 / 8 |

observer CPU 是采样调用线程的活动 CPU，不是整个观测进程；分母是实际整路 elapsed，
不是采样函数累计活动 wall time。它没有从表中任何 CPU 总数中扣除。
process 与 cgroup 数字有重叠，不可相加，也不能除以正式案例数冒充稳态单例成本。

500 ms 采样更容易漏掉短进程和短峰值。所有 detached job 的最终 CPU 端点均未留存，
部分 cgroup 首次读取前就已消失；上述 CPU 是已观察下界，缺失从未当零。
更高的 complete PSS 样本比例只描述所选 PID 的可读性，不代表更充分的时间覆盖。
第一、第二轮 PSS 峰值也不能相减作为实现节省量，因为采样方式已变。

外部模型计算/内存、部分 localhost SSH 控制进程仍未测量，
`global_total_memory_or_cpu_claim_supported=false`。本实验不支持完整系统资源成本胜负。
[V2 独立审计](evidence/V2_AUDIT.md)记录遗漏、实际间隔、来源绑定和全部预算检查。

第一版 post hoc auditor 还发现一项独立错误：重构 gateway body 时错误排序 JSON keys，
使 Codex 请求产生假 SHA mismatch。修正版本遵照实际 wire 的插入顺序，并以真实 wire 为测试 oracle；
原脚本、原摘要和修正摘要都保留。修正不改变任何测量文件，也没有重跑模型来替换错误案例。
[第一轮修正审计](evidence/FORMAL_V1_AUDIT_V2.md)

## 恢复证据的范围

最新 0.165 的三条 fault 路径均验证同一 runtime request/job、原命令摘要和同一物理作业关联，
没有以新操作重发获得结果。但故障对象不同：native 杀掉整个 qualification runner，
App Server/facade 只杀掉 runtime helper，Codex 核心仍存活。因此不作 whole-agent 恢复胜负。
[故障归档索引](evidence/fault-recovery-0165-final-v1.MANIFEST.json)

官方 Core 存在 `recover_turn_if_idle`，可保持 turn ID，但会重新启动模型采样。
当前 App Server/facade pending callback 与 dynamic-tool waiter 的冷进程续接没有得到验证；
不能将保留 ID、追加历史或得到最终回答等同于原 pending call 的接续，也不能将未测计为失败。
当前 live gateway 亦未代理真实 provider retained-response GET，故 native 的真实 provider 断流恢复
还未通过该层集成验证。[Codex 恢复边界](CODEX_RECOVERY_BOUNDARY.md)

## 后续放行条件

生产替换需要把已实现的切片接入原 Agentd/Fleet、LiveThread/QueueStore 和同一个 production writer，
由真实外部 grant provider 供给 FinalUse，复用一次性 dispatch claim，
并在全部可等待准备后、紧邻模型/进程真实入口处消费原 token 与重查代次、租约、撤销、取消和期限。
现有泛型 target 的单结果接口不自动满足 SSE 流交接。不能用另一个布尔授权或复制 outbox 补齐。

还需验证旧会话、真实 provider 断流查询、服务 readiness/drain、generation 交替及撤销，
并扩展到有代表性的相同任务/预算对照。生产路由保持现状；本轮没有迁移或重启生产 Agentd。
[完整架构决策](ARCHITECTURE_DECISION.md) · [生产边界切片](PRODUCTION_BOUNDARY_REPORT_FRAGMENT.md)

## 原始证据

| 归档 | SHA256 | 内容 |
| --- | --- | --- |
| [formal-comparison-0165-v1.tar.gz](evidence/formal-comparison-0165-v1.tar.gz) | `584d3ae922e09b37129d5f14dd9c104494abeb34cc4e8bf957c2ae3adb44c616` | 第一轮 1,377 文件，保留测量扰动 |
| [formal-comparison-0165-v2.tar.gz](evidence/formal-comparison-0165-v2.tar.gz) | `ac1bd04a5c688fab250c161cf7dbfa0323a19a39f76cc706cbe87a2fd3ff9cab` | 第二轮 1,377 文件，每个请求、响应、状态与报告 |
| [fault-recovery-0165-final-v1.tar.gz](evidence/fault-recovery-0165-final-v1.tar.gz) | `6a3b2be4c8035c39871434e9343e57e84b53113bd54465c8153b65f36275ffae` | 最新三路声明范围的故障记录 |
| [measurement-gates-20261028.tar.gz](evidence/measurement-gates-20261028.tar.gz) | `0c3eab64ee2ac4d93d81b274ee5eb54623ebede5d84604260ff4f97a3c4665ba` | 100 ms 失败、profile、cadence 汇总失败、500 ms 通过与冻结日志 |

各归档的 MANIFEST 保留逐文件身份。运行目录中的 Codex home/cache/auth、传输临时文件和锁不作为源码交付。
早期失败、环境修复和旧版本 smoke 保存在诊断及工程 gate 归档，不混入正式性能分母。

[release]: https://github.com/openai/codex/releases/tag/rust-v0.165.0
[runtime-pr]: https://github.com/TrillionniumFoundation/hepta-runtime/pull/75
[cell-pr]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4131
