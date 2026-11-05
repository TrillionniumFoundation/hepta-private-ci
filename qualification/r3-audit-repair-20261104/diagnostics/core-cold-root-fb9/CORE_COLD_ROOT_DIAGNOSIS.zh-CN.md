# Core cold-root 新失败：只读诊断与最小观测提案

结论仍为 **原因未明（OPEN）**。固定源 `fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff` 的原全量中，此例实际 8.209 秒普通 Rust 测试失败（退出码 101）；旧 f825 同名例为 8.780 秒 PASS。新旧程序 SHA 不同，旧通过不转借为当前资格。

原完整日志第 73017–73031 行和完整 JUnit 都只有 `Error: thread 01a1a9fe-9432-7365-982c-7a0f11490eee not found`，没有阶段或回溯。不能从名称推断“冷恢复失败”。精确原件、字节区间和哈希均在同名 JSON 中。

## 已收窄的错误链

`ThreadManager::get_thread` 缺线程会显示 `no thread with id: …`；会话初始化映射会带 `Failed to initialize session:`。这两条直接传播的文字与实际裸错误不同。

原测试第 365–367 行依次 flush sibling、worker、root。`CodexThread::flush_rollout → Session::flush_rollout → LiveThread::flush` 使用 `io::Error::other` 保留底层 `ThreadStoreError` 的裸显示，因而是已确认兼容的传播链。该链先刷 live writer，再同步待提交 metadata；缺 recorder 与 metadata 错误尚未区分。原源码明确 shutdown/discard 会移除 recorder，晚写应失败，不能把这类错误吞掉。

实际初始任务发送在 manager 插入 runtime、交付 ACK 和 spawn reservation commit 之后，不能仅凭观测到子请求就归因“注册晚于实际初始任务”。另一方面，共用 ResponseMock 的 recorder 位于自定义 matcher 之前，而本测试只按 parent ID 选择 worker；这是可审的观测风险，但原失败没有请求正文，尚不能证明本次命中了它。原 residency 容量三及实际卸载路径均已读；没有卸载事件证据，未建议增加容量或重启掩盖失败。

## 可审的独立诊断补丁

仅在原两次 manager lookup、三个 flush、一次 root restart 的原 Result 上增加 `inspect_err`，出错时打印固定阶段、该测试线程 ID 与原错误 Debug。返回的 Err、原 `?`、所有原请求、断言、sleep、timeout、shutdown 顺序均保持。成功路径无新增读/写/请求/等待；不读取共享 home 或日志正文。

源码后像 `e2b3daac03d9e15b1641e11f23377bf56bf397db`；补丁 `525c4702fe3d2f8193e45d37fde977402cb7180b`。六处逆替换精确还原原文件；隔离 Git 的 apply/check 与反向恢复均逐字验证。**未 rustfmt、未编译、未执行、未应用到 native 或任何 ref。** 此提案只增加错误定位，不是根因修复。

后续只需在 root 批准的未来同源原 CI scope 选中此原 case、沿用原预算和零重试，保留 stderr/JUnit 与实际程序/源身份。如果仍没有新增阶段标记，说明错误来自其余传播路径，应继续定位；如果仅 PASS，也不能追认本次历史原因。当前 A Draft 发布不应等待这项诊断；23 项原退出条件及状态计数不变。
