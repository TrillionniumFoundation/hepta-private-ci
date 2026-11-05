# fb9 ExecServer CONNECT 超时：固定源码复核

**结论：原失败保持开放。已经证实源码中存在 2 秒 DNS 截止时间与 2 秒客户端读响应截止时间的竞争，但原日志没有证明该次实际停在 DNS。此次只读复核没有修改产品、测试、权限或原生工作树。**

## 原始执行事实

精确用例为 `codex-exec-server::process_sandbox::tests::native_request_handles_remote_proxy_config_for_platform`。实际 fb9 树是 `fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff`。完整 JUnit 中该例为普通 exit 101，10.514 秒，在 `process_sandbox_tests.rs:338` 的原 2 秒响应读取发生 `Elapsed(())`。准备请求、TCP 连接和写入 CONNECT 已返回；该例没有启动子进程或执行 sandbox 命令。

原配置只允许 `allowed.example`，没有配置 explicit deny。请求 `blocked.example` 是隐式 allowlist 拒绝，decider 和审计 observer 都为 None。更早 f825 的完整 JUnit 有同名 PASS 0.501 秒；这条历史成功单独保留，不覆盖后来的真实失败。

## 源码路径与边界

| 环节 | 固定源码结论 | 对诊断的影响 |
| --- | --- | --- |
| managed proxy 启动 | builder 保留真实 loopback listener；run() spawn 后返回 handle | TCP connect 成功不等于 CONNECT 已解析 |
| ingress | 已使用 `HttpServer::http1()` | 不能复用旧 auto-sniffing 原因作为本次结论 |
| attribution | 首字节为 NUL 才进入 3 秒 frame 读取；普通 CONNECT 首字节为 C | 未收到首字节前仍可等待，收到 C 后不走 frame timeout |
| policy | explicit deny → local/private DNS → allowlist | 此 implicit deny 主机名在拒绝前仍会查询 DNS |
| DNS | 原 deadline 2 秒；失败、超时或私网解析均 fail closed | DNS 若持续 pending 到 deadline，403 无法可靠地赶上同样 2 秒的客户端截止时间 |
| override | 仅 NotAllowed 能交给 decider；NotAllowedLocal 不能被覆盖 | 不能把 allowlist 检查全局提前并声称权限合同不变 |

实际 fb9 整个 `codex-rs/network-proxy` subtree 为 `553134f61e34565be51840475a93f022b3b4dd0c`，与 cabc 完全相同。14 份相关源码的全字节、Git blob 和 SHA-256 身份在 JSON 中逐项保存；ExecServer 两份源码另与实际 fb9 typed read 对齐。

## 为什么暂不提交提前拒绝的生产修改

在没有 decider 的特例中，提前返回 NotAllowed 仍会拒绝请求。但对于解析失败或解析到私网的主机名，原结果是 NotAllowedLocal，提前返回会改变原拒绝优先级、响应正文与 audit/blocked telemetry reason。有 decider 时直接前移还可能让原不可覆盖的私网拒绝进入可覆盖分支。当前没有证明一种绕开 DNS 又保留这些原合同的修改。

修正此前一处口头描述：两个 reason 的 `x-proxy-error` 都是 `blocked-by-allowlist`，这个 header 不变；不同的是正文与具体 reason。也不能用 10.514 秒总耗时推断 DNS 时长、宿主负载、runtime shutdown 或特定 ingress 停顿。

## 最小后续观察

如后续批准一次受保护的临时诊断，仅保留同一个原用例、原 host、原 2 秒与全部断言：记录 prepare/connect/write/read 的真实单调时间；CONNECT accept 与原策略结果；原 DNS await 前后的固定阶段和结果；record_blocked 后构造原 403 的时点。不要替换 DNS、追加 deny、改成 IP、增加重试或放宽超时。临时源必须精确恢复。

这些观察可区分尚未进入 CONNECT、已进入 DNS 但客户端先到截止时间、以及策略完成后响应交付迟滞。即使一次诊断成功，也不能追认原失败已解释或全平台已通过。本报告中的诊断仅为方案，未应用、未运行。

完整原 JUnit 身份、两次精确 case XML、14 个源码 blob、实际树链及所有限域见 `static-diagnosis.json`。本项不会阻止 A 以明确 WIP 状态发布原 CI，也不改变 B16 或原 blocker 的验收条件。
