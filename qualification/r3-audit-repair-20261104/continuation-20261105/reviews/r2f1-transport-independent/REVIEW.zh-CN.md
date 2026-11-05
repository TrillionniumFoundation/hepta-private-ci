# R2f1 Root checkpoint transport 独立静态审查

**结论：静态接受当前三个文件，未发现必须修改的生产行为问题；未编译、未运行，也未取得 Current 或真实 Root 接受资格。**

本次绑定作者 manifest `16e4c8e5ad178afe7e3351dbf7c3f5f99abd50c1`、patch `00e997f3ab4c1f5858121041ed1088adfd1f7a2c`。我完整读取了两个新源文件和原 lib 的八行增量，独立执行隔离 Git 的 check/apply/reverse check/reverse，三个后像逐字一致，逆向恢复原 lib 并删除两个新增文件。又独立 GET 三个后像及 V2 manifest，均与本地字节一致。详见 [结构化独审](independent-static-review.json)、[静态重建收据](static-verification.json) 和 [独立 GET 收据](independent-github-readback.json)。

## 已检查的实际合同

公有 `from_inherited` 固定要求 UID 0；可选 UID 的 `from_peer` 是私有方法，未作为测试后门导出。同步阶段持有原 Unix stream 和 pidfd，恢复 CLOEXEC、核对 peer PID、boot ID 和 start ticks，不创建线程、运行时或新凭据。进入实际 I/O-enabled Tokio 后才注册这两个原资源；固定 Tokio 1.53.3 的 unsafe 注册合同由内部 OwnedFd 所有权满足，注册失败也不会泄漏该资源。

`exchange` 在首个 await 前拿走 stream。开始 I/O 后的取消、超时、错误、非法 ACK 或已观察到的 Root 退出都会使 lane 永久不可复用；仅完整有效且未过时的 ACK 才把 stream 放回。它发送冻结 codec 的原字节，保留四字节长度与 32 KiB 上限，并返回真实收到的 ACK 原字节，不重连、不自动重试、不创建后台任务。截止时间始于同步构造，不因每次 exchange 被续期。

## 必须保留的边界

Linux v6.12 固定源码确认：SO_PEERCRED 的 PID/UID 使用调用方的命名空间，而 pidfd fdinfo 的 Pid 使用 procfs 实例的 PID 命名空间。因此数值一致仍不能证明初始宿主命名空间或独立 Root 权威。可信 launcher 必须提供这些真实前提。SO_PEERCRED 还是建立连接时的凭据；后来把 socket FD 转交给别的进程，不会被这里的 pidfd/proc 检查排除。这是 endpoint custody 合同的一部分。

ACK 内的 `head.peer_lifetime` 应按原 writer/lease owner 的语义由后续 binder 校验，不能简单要求它等于 Root server PID。本片只调用 `decode_ack`，没有执行完整 predecessor/successor、Current、活跃租约、撤销或最终使用授权。pidfd 的退出观察也不能与未来数据库 COMMIT 原子绑定。5 秒 / 300 秒是 transport 的上限，不是已验证的 lease expiry。

四个新控制确实使用真实 UDS、自身 pidfd、内核凭据和 EOF；取消控制先等对端实际收完请求，再取消。它们尚未执行，合成 ACK 不授予权限，自身 pidfd 不能证明独立 Root 死亡。CLOEXEC 正例从本来就有该 flag 的 FD 开始，不能外推为跨 exec 恢复已经过物理验证。

## 下一验收

在实际最终 B 前像上编译并按原 recipe 执行四个新 case、原 Agentd owning scope、零重试及既定 hygiene；再独立推进可信继承链、Root 退出、whole-owner 三池、Current/binder、issuer/listener 和普通 UI caller。现有 Foundation 的实际通过记录不转借给这个新片段，23 项原状态和退出条件不变。

[Linux pidfs 固定源](https://github.com/torvalds/linux/blob/v6.12/fs/pidfs.c) · [Linux peer credential 固定源](https://github.com/torvalds/linux/blob/v6.12/net/core/sock.c) · [Tokio 1.53.3 AsyncFd 固定源](https://github.com/tokio-rs/tokio/blob/tokio-1.53.3/tokio/src/io/async_fd.rs)
