# 两端 I/O 诊断候选：独立静态复核

**未发现具体静态阻断。** 结论只对应 Hia 冻结 candidate1（manifest `e3c86216…`），不等于已编译、通过原门或完成 NoUpdate。

已完整阅读四份 Rust 差异、全部政策迁移和执行依赖，并独立核 20 成员 size/SHA、六份 before 对实际41a库存、六份 after SHA/GitBlob，以及完整28,763B unified diff。CALLERS 的1,165条 boundary和其他root表完全保留；908 protected occurrence中只有183/554/555/630迁移，其余904原始块逐字不变，所有原required/forbidden数组原样。allowlist只更新CALLERS精确SHA。

## 关键语义

- 服务端旧poll/write判断、owner优先、deadline和原错误返回完整保留。新增数据只是每次调用的私有局部记录，捕获实际errno/revents；诊断写入仍发生于原peer shutdown之后。
- 客户端nested async持有原taken stream。普通返回错误（包括每条`?`）统一在外层成为`Failed(error)`；成功完成原slot restore后才标记`Restored`。未完成future被Drop时标记`unfinished-future-drop`，明确包括cancel或unwind。不会把普通错误误标取消，也没有第二次请求或连接。
- 该嵌套作用域在外层诊断Drop前释放其stream；原exchange permit仍覆盖完整frame。实际Rust借用/类型判断仍须由原编译完成，本次没有执行Rust。
- Session Drop仍先fence、请求abort、清理consumers；有限日志在这些原操作之后，且不持consumer锁。标签只称abort=requested。Worker Drop先fence再log，仅称cache=fenced，不声称join或全部资源关闭。

## 原控制与解释边界

已核原65个component完整名称及原结果pin、2个Root component和1个机制父的完整XML名称；原18恰等于原14peer/deadline+4owner集合。它们是保留的旧验收身份，不能继承给新源码，也不直接证明新增client日志正确。

跨线程日志顺序不能作为真实先后证明：请求abort后worker可能先打印Drop日志，session稍后才完成consumer clear并打印abort=requested。`unfinished`仍可能包含unwind。该候选能增加真实判别信息，不是已证明的transport修复。

未来仍需原fmt/compile/justfix、54模块474case、原453 IDs并集/full1165、7blob及fullPR512000门，再精确新source执行65+Root2+机制1+whole父1。64、retries0、全部原时限不变。当前41a整父FAIL和冷未执行事实保持。

详见`READOUT.json`的逐路径分类表及`INPUT_PINS.json`。本peer所有host/network/test/native/model/Git/作者源修改均0。
