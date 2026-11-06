# R29 Bedrock 响应等待：隔离诊断候选

这份补丁只增加观测点。原 R29 是自然 `failed 100`，唯一失败在第一次 `account/bedrock/setup` Profile 请求等待响应时发生；本候选没有证明或修复生产缺陷。尚未执行诊断、Rust 门、fix 或 fmt，也没有创建候选 Git commit/tree。执行必须由 root 另行决定，并由 native owner 使用独立诊断身份完成。

## 为什么需要这些观测点

原 `TestAppServer` 强制子进程 `RUST_LOG=warn`，随后才应用测试显式环境覆盖，且已把子进程 stderr 原样转发为 `[mcp stderr]`。因此只在父进程设置 `RUST_LOG` 不能打开本用例子进程的 INFO/DEBUG 事件。

原 app-server 已有 `FmtSpan::FULL` stderr 层、INFO `app_server.request` span 和 DEBUG serialized queue span。开启它们能区分请求尚未进入主循环、已经排队、进入处理，以及发送响应前后的边界。原 handler 内没有足够阶段事件，故还需要固定标签来区分其四个等待点。

初始化响应之后，原主循环仍依次等待初始化通知、remote-control 通知和 `connection_initialized`。后者实际只是 mutex 和 map 插入，但原失败日志中的 remote-control 通知不能证明这一步已完成，也不能证明 Bedrock handler 已进入。候选不修改这条顺序，而以原 request span 的出现与 handler 的进入事件区分该边界。

## 精确变更

| 文件 | 变更 |
|---|---|
| `codex-rs/app-server/tests/suite/v2/bedrock_setup.rs` | 仅在原失败用例的第一个 child 的既有环境数组中增加 `RUST_LOG`。父进程、第二个 managed-credentials child、其他用例均保持原配置。 |
| `codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs` | 增加 9 个 INFO 事件，字段只有固定 `stage` 字符串，围绕 handler 入口、config precedence、profile validation、active-login cancellation、provider config persistence。 |

日志过滤器是 `warn,codex_app_server::app_server_tracing=info,codex_app_server::request_serialization=debug,bedrock_setup_diagnostic=info`。保留原 WARN 基线，只打开上述窄目标。没有打开 AWS SDK debug 日志。新事件不记录 profile、region、凭证、路径、请求参数或环境值；原 request/queue span 的字段保持原样。

## 读回方法与界限

- 未出现 Profile 请求 ID 对应的原 request span：尚不能证明该消息已进入分发；结合初始化 span 与原通知顺序检查初始化后置边界。
- 已有 request/queue span，但没有 `handler_entered`：检查原 account-auth 排队或 admission 边界。
- 出现阶段 `*_start` 而未出现相应 `*_complete`：只能定位到该原始等待范围，不能进一步猜测 DNS、文件系统、锁或调度根因。
- 已有 `provider_config_complete`，但客户端仍超时：处理函数已完成配置路径，继续检查原响应 context/mpsc/传输边界。
- 诊断若 PASS：只说明这次带观测运行完成，不能证明原失败已修复，也不能代替原项目或完整工作区门。日志本身会改变时序，不能把未重现当作原因消失。

原请求、响应、全部 assertion、测试属性、10 秒 typed-request timeout 和 60 秒初始化/错误响应预算均保留。没有新增 await、RPC、重试、等待、权限调整或网络替身。

## 机械证明

`source-manifest.json` 固定两个文件的 before/after SHA256 和 Git blob；`edit-operations.json` 保存每个精确插入。撤销全部插入后，两个完整文件逐字回到 source52 原文。`verify_patch_roundtrip.py` 仅在临时隔离目录运行 `git apply --check`、正向、反向检查、反向四个命令，并分别验证完整结果字节。它不构建或运行任何 Rust。

原源码与失败证据见相邻 `app-server-bedrock-r29-investigation/`；初始化/分发独立审阅见相邻 `app-server-bedrock-dispatch-r29-independent/`。本目录不是正式发布组，也不授予任何工程或科学资格。
