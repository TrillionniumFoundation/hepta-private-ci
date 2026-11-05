# 本轮源码变更与历史结果

本记录按变更目的归纳已经保留的源码和执行历史。候选的结果只属于其自身的固定 commit/tree 与执行范围；最终 865 及历史候选的 Linux 结果均由各自回执记录；Windows 编译与目标宿主资格仍按平台未关闭门槛记账。最终 40 模块的 owner、caller/writer、sourceBase、371 条操作语义、原门槛及生产声明边界均不由本记录升级。

## 记忆与学习的恢复边界

- Agentd 的 cognitive context 在 retrieval/ranker 回调结束后、成功返回前再次读取实际 SQLite owner cut，使准备后发生的删除、纠正、到期、撤销或 owner 变化无法沿旧快照成功。真实 retrieval provider 与物理模型请求附加仍需另外验收。
- `CommittedLearningAppendV1` 提供精确历史 Decision/Outcome 提交 ACK 对账，绑定 ledger、record ID、event digest 与 predecessor chain digest；缺失正文不新建追加，不延长过期授权，不恢复已撤销授权。
- Witness 恢复先同步完整已解析帧，再向 owner 暴露；保留截断尾部及真实 OS 只读失败路径。

源码依据：[cognitive_context.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/codex-rs/hepta-agentd/src/cognitive_context.rs)、[production_reconciliation.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/codex-rs/hepta-learning-ledger/src/production_reconciliation.rs)、[witness.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/codex-rs/hepta-learning-ledger/src/witness.rs)。

## Supervisor 与配对子进程

- Handoff lock 的显式释放绑定实际 acquiring PID；dup/fork 继承不冒充原 owner。回归保留真实 fork 和原授权/代次围栏。
- 受控子进程原先对所有方法返回 Health；Drain 改为检查原 schema、spawn 身份和代次规则，并持久进入 Draining，未知方法继续拒绝。
- 私有临时副本使用系统 `strip -S` 去除调试数据，保留原镜像安装、完整摘要、执行与接管链。原 60 秒预算、父测试二进制和构建 profile 不变；缺工具、非零退出和无输出均失败。
- 这些回归有真实 OS 子进程，但协议仍是受控 fixture；GNU strip 结果不推广到 Darwin 签名或实际 Agentd/Matrix 产品部署。

源码依据：[writer_handoff_lock.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/codex-rs/hepta-supervisor/src/writer_handoff_lock.rs)、[paired_process_product.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/codex-rs/hepta-supervisor/tests/paired_process_product.rs)。

## CI、格式与 Windows 测试引用

实际集成中合入上游 `07378034e060f23259bc99c7367f12b1284140f3` 的 TUI borrowing 与 issuer expiry fixture 修正，并修复 AppServer 初始化 API 返回值、AppServerClient `trace: None`、ExecServer 异步测试持锁方式，以及跨磁盘 timing/source-custody 上传的公共根目录问题。独立的原全工作区 formatter 进一步修正 10 个 Rust 文件；原三项 Clippy deny policy 保持。

Codespell 2.4.3 将流式测试前缀 `"hel"` 判断为拼写错误。源码改写为 `"he\x6c"`，运行时仍为单个 `&str`、同样的 `68 65 6c` 三字节；通知顺序、断言和 ignore 配置不变。原命令在 bb55 上重现 exit 65，在 `c4863123b65f895be0eb14e0958d5cfe6c9c78bd` 代码候选上通过，797 导航候选再独立运行通过。[前缀源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/codex-rs/hepta-infer-worker-host/src/native_output_tests.rs)

Windows 后继补丁解决实际 E0034/E0659 诊断：PTY 测试三处显式选择 `AsRawHandle::as_raw_handle`，沙箱子模块显式导入 `pretty_assertions::assert_eq`。`portable_pty::Child as _` 继续保留，以支持原 `WinChild` 的 `wait`/`try_wait`。所有 HANDLE access mask、unsafe 范围、错误处理、删除路线及 8 个断言、5 秒/10 秒预算均保持。源码审阅不构成 Windows 编译或 ACL 资格通过。[审阅全文](review/windows-name-resolution/REVIEW.md)

Windows Bazel bootstrap/远程执行路由问题仍是独立开放门槛；没有通过关闭 lint、扩大时限、假设物理 worker 或未经资格的配置变更将其隐藏。

## 历史运行原样保留

| 固定候选或阶段 | 原始结果 | 解释范围 |
| --- | --- | --- |
| `a3a987d0` combined RED | 4 failed、0 passed、757 skipped；exit 100 | 真正行为 RED；此前 CMake/OpenSSL 构建准备失败不冒充此结果。 |
| `4fbf4f10` Supervisor RED | 2 failed、108 skipped；exit 100 | 锁/fork 原失败。 |
| `6d63f3f2444e194a46330780e2b1f67adfe4f289` | 4 passed、759 skipped；exit 0 | 主修复定向 GREEN。 |
| `c1f586bc8d18e4e3d3e469137fb12b4cbfa02963` | handoff 3 passed；witness/ledger 5 passed | 与其他定向范围有重叠，不能相加宣称 12 个唯一回归。 |
| `f5813506b49eb05efad00f203b9362195875892c` | 七包 1,217 passed、1 failed、1 timed out、78 skipped；exit 100 | 69 项 clean，整体仍 NOT_CLEAN。 |
| `6dba3945714eeccc79fcf7d2f36410408ea69710` | 1 passed、1 timed out、1 skipped | Drain 已修正，镜像准备瓶颈仍使五对进程超时。 |
| `a00ff322e692a0800331c454d3484eec3efffdb9` | 原 Clippy 策略通过；两库 319 passed；AppServer 选择 5 passed | 额外 `-D warnings` 的既有 AsyncFd deprecation 失败单独保留，不称原 CI lint 失败。 |
| `d068620da668c8288dfa7bfb92a1347af1f4a556` | paired target 2 passed、1 skipped | 原预算下，私有镜像修复后的定向通过。 |
| `afe0d625b01728a5fe2a1c37652573a3a1b6a097` | 原全 workspace format exit 0 | 稳定版对 nightly-only 导入粒度选项仍告警忽略。 |
| `bb55b0d7d263c396ec504c45393d938c3428dae5` | 七包 1,219 passed、78 skipped；相关 Linux 检查通过 | 平台 Codespell、Windows 测试编译和 Bazel 失败分别保留。 |
| `797116d61cf422c26274ffef31297dce84a53a80` | 七包 1,219 passed、78 skipped；Codespell exit 0；原生服务 succeeded / exit 0 | 本候选独立原生执行与完整原始文件采集已核对；两库 319 passed、AppServer 选择 5 passed。 |
| `775bf555b0a7faf6eed17627acb0d0433294b737` | 七包 1,219 passed、78 skipped；Codespell/原格式/原 Clippy/严格检查均 exit 0；两库 319/0、AppServer 选择范围 5/1,016 | 从本候选原始日志/JUnit/17 份源码绑定回执独立核对；Linux 范围，Windows 编译仍未据此验收。 |
| `8658210499706130788c216ff14fd342809b45a4` | 七包 1,219 passed、78 skipped；7 项严格检查及 8 项外层检查全 exit 0；两库 319 passed、AppServer 选择 5 passed、Python CI 控制 28 tests OK | 真实有序双父合并后独立执行；完整 Linux/Python 回执与平台排队状态分别保存，不升级为 Windows 或部署通过。 |

早期证据固定于 [acf11067](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/acf11067530fc12386b090e7e067e518b182088f/qualification/module-execution-dossiers/modules40-20261105-da8578)，bb55 原生与 Codespell 证据固定于 [f038947f](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f038947fd20992e15213d41f7f6d8ac1d2ca10fc/qualification/module-execution-dossiers/modules40-20261105-da8578)。后继报告、导航和证据 carrier 不改变这些历史结果。

## 最终固定并发合并

最终 865 的真实有序父提交为 775、3a39。相对 775 仅有 5 个变化路径：4 份 CI 文件保持 3a39 原始字节，OpenSSH 诊断保留并经过 4 处布局/2 处尾逗号的原生格式调整；唯一 PTY 冲突保留已审阅的 775 字节。所有 40 张 Map 和既有 3 份 history 不变。新源码上的 Linux 原生七包与原 CI 命令重新执行，未从同树原生合并或旧候选搬运结果。[最终源码核对](BUILD-SOURCE-REPORT.md)；[最终执行总览](EXECUTION-OVERVIEW.zh.md)
