# 固定候选原生执行独立审计

**结论：CLEAN_WITHIN_RECORDED_SCOPE。** 这是固定 Linux 原生范围的证据核对，不是生产完成或全平台通过。

- 源码提交：`797116d61cf422c26274ffef31297dce84a53a80`；tree：`67ce024db1679aa6cd301856ba3a694ea18bc4b6`。
- 原生任务：`1a1ac84ead1-fc05-54ef`，authoritative succeeded / exit 0，输出完整持久，没有外层超时、取消或自动重试。
- 七包：1219 个唯一执行案例全部通过，78 个 runner 原配置跳过；JUnit 34 suites，1219 cases；失败、错误、超时、重试均为 0。
- 69 项关键要求逐项以完整 package/binary/test 身份匹配到唯一通过案例；原 59 项历史定义保留。
- 两库回归：319 passed / 0 skipped；AppServer process_exec：5 passed / 1016 skipped。
- 7 项严格检查、7 项 wrapper scope 检查均为 0；17 份执行 receipt 的 before/after 都绑定该候选，日志长度和 SHA256 一致。
- 原始 Codespell 2.4.3 CLI 通过，输出为空；没有新增 skip/ignore 参数。
- 归档：123 files / 122 manifest entries；SHA256 `6e95dfc4723db20a4bfa158bedae04e8fc537622bbd0a20abf59783552c7571a`；所有 entry 和解压字节核对一致。

## 必须保留的范围限制

两个原始格式命令均返回 0，但 stable rustfmt 明确忽略 nightly 专用的 `imports_granularity=Item`。Clippy 使用三个原始 `-D` 策略，不等同于 `-D warnings`。

JUnit 仅序列化已执行案例，78 个 profile skip 来自原始 runner 日志。AppServer 的 5 个 process_exec 案例是记录命令选择的范围，不能代表其余 1,016 个案例。

source before/after 的干净固定 checkout 是被记录的边界，不是硬件、文件系统并发、真实 provider 或跨平台的独立证明。生产标记、DENY_ALL、真实端到端验收和激活门槛均不改变。

## 文件读取 custody

72 个远程文件逐个经只读 API 的 version、完整 SHA256 或分块 SHA256 校验；这是非原子跨文件采集。单独的归档请求曾被协调者记录为 launch_unknown，本采集没有重放该请求，也没有把它当作测试失败。

## 历史 Codespell 配对

原 bb55 候选的原始 Codespell 返回 65；c486 代码候选返回 0；本候选再运行返回 0。各自保留自己的提交/tree/日志，未把历史结果移植到当前候选。
