# 原 S Evidence 500 ms 失败：仅原交换的诊断候选

固定失败为 9fac 的真实 native job 131309678676。承接 tree 008f13b46caca4d2e7af73551ce1627dafc07e5e 的四项首次撤销断言修正，不含 bridge/Root bootstrap WIP。

## 实际计时契约

已完整读取 authority_host_peer.rs blob 36e4524baea04320b7610325579f0ff206690fab。exchange_inner 等待首字节使用 owner.end() 的原连接寿命；收到首字节后才创建 policy.timeout 期限，覆盖余下请求帧、原 handler 与整个响应。因而“服务先启动、空闲等待会耗尽 500 ms”是假设错误，现已排除。callback_wait 和 exchange elapsed 包含首字节前等待，不能当作 500 ms 帧预算消耗。

## 本次观察

每个原 exchange 内只采样 Instant、回调是否进入及实际 evidence_response 结果。成功仅保留原响应字节数；失败把原 Error 移到外部 Option。所有 stderr 输出均在同一原 exchange 返回之后，回调内没有新增诊断 I/O。实际 owner 调用仍恰一次，两端 500 ms、原绝对 300 s lifetime、128-frame 上界、原错误映射、原 Source 撤销 hook 全部保持。

输出可区分回调尚未进入、原回调失败、原回调成功但传输拒绝；不能仅从 exchange 总时长断定是哪段超时。callback_elapsed 仅在原 host 调用前后采样，不包括随后 stderr。即使原回调成功，也不能忽略原 exchange 的 DeadlineElapsed。

两个原 C 精确断言只增加实际 Error 输出；另一个正例只给原错误补调用阶段文本，匹配条件不变。原 Material helper 只在真实 exchange 错误或原 128 上限耗尽后输出 actor、已完成帧数与原错误；正常请求和 EOF 无新增日志。没有更换签名、Source、连接、提前读、重试或调大上限。

历史候选 S blob 5ee1579bf4bb07165156b4fa466a925939d26fbe 在回调中打印，现已替换；旧文档的 idle 推断也已纠正。格式、编译、source QA、native 执行均 NOT_RUN，三个 C 失败仍待真实定位；owner_decision=null。
