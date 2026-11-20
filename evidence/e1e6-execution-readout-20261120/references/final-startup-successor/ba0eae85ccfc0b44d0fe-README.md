# NoUpdate14：Root 响应头写入失败的有限独立复核

## 结论

实际 `41a0fd9b` 父仍为 **FAIL**。现有原件能把首错收窄到 Observation lane 的四字节响应长度头写入，但不足以支持一个具体产品修复。不能把 `Unavailable` 改写成直接 deadline 错误，也不能通过忽略错误让 Root 成功退出。

A 的本地 Objective receipt、publish、observe、最终 RunStart 已完成；独立 observer 1 case PASS。父按原代码完成验收后请求 daemon 关闭，先成功等待 daemon，随后在 `root.wait_success_until` 报错。这个顺序不等于 Root 内部错误发生的时间。更早 `ready.exchange-returned` 的 62.705 ms 仅是那一次成功的 Initial exchange。

## 已确定的失败边界

`HostAuthorityPeerChannel::exchange_inner` 在 handler 返回成功、post-handler owner 检查通过、response 非空且有界之后，调用 `OwnerChannel::write_until` 发送长度头。`peer.response-header-write` 与 `observation.exchange` 共用 ThreadId(14)。原错误一直保留到 `io::Error::other`，没有在这条链路被统一重分类。

| 原分支 | 原错误 | 与本次最终错误关系 |
| --- | --- | --- |
| 原 deadline 到期或 poll 超时 | DeadlineElapsed | 不是本次直接错误 |
| 原 owner pidfd 就绪 | PeerDenied | 不是本次直接错误 |
| write 返回零字节 | Closed | 不是本次直接错误 |
| socket revents 包含 ERR 或 NVAL | Unavailable | 可能，原件未留实际 bits |
| poll 其他 I/O 错误 | Unavailable | 可能，原件未留 errno |
| write 其他 I/O 错误 | Unavailable | 可能，原件未留 errno |

对端关闭可以产生其中部分 I/O 条件，但目前没有证据选择具体 errno 或关闭原因。Control Objective ACK 的 read timeout 属于另一条 agentd 控制连接；其后恢复与独立观察成功，不能直接把它连成 Root socket 错误的因果链。

## 时限与生命周期

原 A fixture 配置 `timeout_ms=500`、`lifetime_ms=300000`。Root 服务先固定 lane lifetime，完成 accept 后为每个原 worker 传入余量。Peer 第一字节使用 owner end；收到首字节后创建 `min(now + timeout, owner.end)` 的单帧 deadline，覆盖请求余部、handler 前后检查和响应头/正文，不在写响应时重置。

客户端 `RootObservationStream::read` 使用自身原绝对 end 与最多 500 ms 的帧窗口，并同时观察原 Root pidfd。失败或取消时原 slot 不恢复、不自动连接。生产 launcher 在 `crate::run` 返回后 drop 原 attachment；最终 session Drop 会 fence cache 并 abort feed worker。取消一个正在 read 的 future 可以关闭其持有的 stream，因此这是与现有事实相容的生命周期假设，**尚不是本轮已证明根因**。实际产品没有 cfg(test) 的 drop 日志；本次 daemon 也没有 refresh-stream/worker-refresh 错误日志，不能靠日志缺席证明取消。

## 必要的最小下一步诊断

不建议无依据重跑相同源码。若 Root 决定继续真实诊断，只需补闭合这两个观察面：

1. 在原 `OwnerChannel::wait` 的失败分支保存实际 revents，或 poll 的 ErrorKind/raw errno；在原 `write_until` 的失败分支保存 write 的 ErrorKind/raw errno。通过私有局部数据带回现有 peer 错误路径，仍先 shutdown/fence 后打印，原 Err 原样返回。已有 phase/thread 足够保留同线程关联。
2. 在 `RootObservationStream::read` 原失败/未完成 Drop 路径区分 deadline、原 pidfd、I/O 失败与 future 取消；在 `AgentdRootAuthoritySession::drop` 原 fence/abort 点补固定生产生命周期标签。必须先保留原关闭/栅栏语义，再记录。

不需要 payload、nonce、私钥、owner 身份或全局计数器；也不需要为了诊断增加 clock 采样。header 写入进度可作为辅助，但不是决定生命周期因果必需的数据。仅取得一个 EPIPE 等 errno 仍不足以证明为何对端被关闭。

## 原件与范围

本目录只含新独立静态 readout 和逐 SHA 引用。`SOURCE_PINS.json` 对 14 个完整源正文逐字核实际 15,813 文件库存；`ORIGINAL_INPUTS.json` 绑定真实父 XML、结果、完整六 stdio 与上游 capture 清单。子进程原件均完整核 size/SHA。额外的 startup 因果审查保持独立来源：新 prepare-before-delivery 在 Post-A 入口，当前 `run_original_a` 未返回，不构成此 A 失败的直接执行路径。

本次复核新增 host/network/native/model/test/Git/产品源码操作均为 0。冷 readonly 草稿已冻结为未执行，ordinary_success 仍 null。没有新增资格，也没有修改任何旧失败、时限或原验收。
