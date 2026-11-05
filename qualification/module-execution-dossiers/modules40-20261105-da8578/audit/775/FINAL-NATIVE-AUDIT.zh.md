# 固定候选原生执行独立审计

**结论：CLEAN_WITHIN_RECORDED_SCOPE。** 这是固定 Linux 原生范围的证据核对，不是生产完成或全平台通过。

- 源码提交：`775bf555b0a7faf6eed17627acb0d0433294b737`；tree：`e6f4644152d11a06457fdd92d8e5066675b26565`。
- 原生任务：`1a1ac9e9596-fc05-55ec`，authoritative succeeded / exit 0，输出完整持久，没有外层超时、取消或自动重试。
- 七包：1219 个唯一执行案例全部通过，78 个 runner 原配置跳过；JUnit 34 suites，1219 cases；失败、错误、超时、重试均为 0。
- 69 项关键要求逐项以完整 package/binary/test 身份匹配到唯一通过案例；原 59 项历史定义保留。
- 两库回归：319 passed / 0 skipped；AppServer process_exec：5 passed / 1016 skipped。
- 7 项严格检查、7 项 wrapper scope 检查均为 0；17 份执行 receipt 的 before/after 都绑定该候选，日志长度和 SHA256 一致。
- 原始 Codespell 2.4.3 CLI 通过，输出为空；没有新增 skip/ignore 参数。
- 归档：70 files / 69 manifest entries；SHA256 `1c59a87b3802c3a6d451907fcd2815ee49129234acfba8aae4868a7a8bb20a59`；所有 entry 和解压字节核对一致。

## 必须保留的范围限制

两个原始格式命令均返回 0，但 stable rustfmt 明确忽略 nightly 专用的 `imports_granularity=Item`。Clippy 使用三个原始 `-D` 策略，不等同于 `-D warnings`。

JUnit 仅序列化已执行案例，78 个 profile skip 来自原始 runner 日志。AppServer 的 5 个 process_exec 案例是记录命令选择的范围，不能代表其余 1,016 个案例。

source before/after 的干净固定 checkout 是被记录的边界，不是硬件、文件系统并发、真实 provider 或跨平台的独立证明。生产标记、DENY_ALL、真实端到端验收和激活门槛均不改变。
