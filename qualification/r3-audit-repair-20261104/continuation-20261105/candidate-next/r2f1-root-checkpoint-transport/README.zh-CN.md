# B16 R2f1：原 Root checkpoint 通道

状态：源码候选，未编译、未格式化、未执行。此批只有 3 个路径、386 行新增；冻结 B payload、runner、native 工作树与 refs 均未改。

## 交付的实际代码

`AgentdRootCheckpointBootstrap::from_inherited` 消费已连接 UDS 与原 pidfd，在同步阶段恢复两个 FD 的 CLOEXEC，核对内核 SO_PEERCRED 的 UID 0 / 固定 PID、pidfd 原对象、boot ID 和进程启动 tick，并拒绝已就绪或错误的 pidfd。它不创建线程或 Tokio runtime，不发现替代路径，不转换凭据。调用方必须事先取得可信 launcher 的身份 pin；数字 UID/PID 与 proc 观察是 namespace-relative，这个 API 不独立证明 host namespace 或 Root 签发权。

`into_runtime` 是第二阶段，必须进入原正常且启用 I/O 的 Tokio runtime。它将同一 socket 设为 nonblocking，并将原 pidfd 注册到 reactor。O_NONBLOCK 作用于共享 open-file-description，持有旧 alias 的上游不能继续假定阻塞 I/O。

`AgentdRootCheckpointChannel::exchange(&mut self, request)` 在首个 await 前取走唯一内部 stream。它发送冻结 codec 的真实字节，读四字节大端长度与有界响应，核对原 request ID/ACK 结构，返回原响应字节。取消、超时、Root readiness、坏响应和拒绝都使 lane 永久不可复用；没有重连、重试或后备 socket。进程活性检查和本地 horizon 不是 lease expiry 或最终提交时的原子权限保证。

## 四项新控制的资格边界

四项定义都使用真实本地 Unix socket、真实 self pidfd、内核凭据和实际 EOF；没有 mocked transport。它们覆盖错误 UID/PID/boot/birth/非 pidfd 拒绝，公有 UID 0 入口对当前实际有效 UID 的行为，同步 FD custody，真实请求与原 ACK 字节，收到请求后的取消关闭，以及实际无响应的期限关闭。

测试内部的私有 `from_peer` 可使用当前测试 UID，公有构造始终固定 0。ACK JSON 来自已冻结 codec fixture，属于合成协议输入。即便测试进程恰为 root，也不等于独立 Root/issuer 接受。self pidfd 也不能证明独立 Root 死亡控制已运行。当前 CLOEXEC 观察从普通 CLOEXEC 描述符开始，不冒称单凭它已证明跨 exec 清 flag 后的恢复。四项控制全部待 sole native lane 真正运行。

## 基线与构建闭包

Agentd 基线为固定产品 `5b6331250ff459033bd44d1a95daec70131277cc` 的 `lib.rs`（3466e60a12138ae4816ace1531254312733e4175）与冻结最终 B 的 Memory codec/wire exports。最终 B 的所有增量路径均不触及 Agentd。没有假造最终 B 整树；实际应用必须再次比对最终 predecessor 的相应前像。

现有 `codex-hepta-agentd` Cargo 已依赖 Memory、Tokio、serde_json，以及 Linux-only libc；pretty_assertions 已为 dev dependency。原 `defs.bzl` 的 `src/**/*.rs` 将两个新源带入现有 library/unit target，无新增 include 数据或测试二进制。原 P4 完整 locked metadata 观察到 Tokio 1.53.3 含 net/io-util/macros/rt/time；这只绑定依赖 API，不代替新源码编译。没有 Cargo.toml、Cargo.lock、BUILD 或 MODULE 变更。

新测试模块名为 `root_checkpoint_transport::tests`。执行入口沿原 `just test -p codex-hepta-agentd --lib --locked --profile dev-small`，先精确四项，再原 owner scope；保原 local 预算、0 retry、原 JUnit 和 actual helper identity。不要再次传 `--no-fail-fast`，原 run-nextest.py 自带。最终原 fix/fmt、diff checks 由 sole native lane 执行；本作者只做了独占云目录下真实 Git patch roundtrip。

## 正常链逐接口剩余工作

| 接口 | 固定当前事实 | 必须接入的真实下一步 |
|---|---|---|
| Root checkpoint | 冻结 B 仅有 codec/完整 head CAS 校验；没有受信通道 | 本批提供两阶段 descriptor transport；还需真实 Root launcher/sealed handoff 与独立服务 |
| 私有 Current | codec `decode_against` 的 ReadHead 只校验身份/单调性，可返回 Dirty/Publishing/Fenced | 私有 constructor 必须核独立 live owner/lease/expiry/revocation、合法 Current、exact cut 与完整前后继，不能开放 Receipt→Current |
| Whole-pool binder | 最终 B 是真实 native custody 与单调 commit veto；尚无 Current/Dirty/Publishing 协调器 | 保三真实 SQLite pool 的 checkout/COMMIT/read barrier，取消单调 fence；实际原 owner lock不能由 Arc count 假定 |
| recovery→writer→sender | 当前 `production_composition.rs` 调原 `open_with_recovery`，保 bootstrap checkpoint 与 `attachment.original_sender` | 独立 Current 必须在 recovery 前验证，whole-pool bind 在 writer/read clone 发布前完成；保持原 read ACK/AlreadyRetained/原 sender |
| FinalUse/issuer | `AgentdFinalUseHostInputs` 与 pinned Unix issuer 为显式注入，原生产签名/target 核验存在 | 独立 Root 需供可信签名 registry、scope/generation、live frontier/撤销/clock、issuer 原 stream；无 self-minted grant 或 shadow-admit 替代 |
| listener 与正常 UI | 当前 ordinary peer 与显式 Desktop attachment 保留；donor 有 Root 父目录/原 inode cleanup 机制 | 后续真实 Root producer 与同 owner listener custody；普通 Desktop joint Notes/Calculator 仍是独立接线批，不全文件搬 donor |

Donor 14e2 的 `production_protected_host.rs` 暴露 transport+receipt DTO，且引用当前未有的 `verify_sender_process_binding`；`cognitive_checkpoint_bind.rs` 的强引用计数假设也不适用于最终 B 的物理连接 custody。它们只能提供具体协议/接口参考，不能直接覆盖当前 host/Memory。完整固定来源及 hash 在 `source-map.json`。

本批没有启动 Root、签发 FinalUse、进入 Current admission、执行数据库恢复或最终 effect。它补上一个能原样验证的小组件；上述正常调用链仍需继续实现和独立接受。
