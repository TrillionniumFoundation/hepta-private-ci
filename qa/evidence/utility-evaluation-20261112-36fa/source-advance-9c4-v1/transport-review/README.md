# Source-advance 原传输记录同行核验

本核验只读取已保存的原 SDK 和文件，并执行离线解码与哈希比较。没有调用 H、重跑 producer、执行 Git/Cargo/formatter，或修改源码。

1. 两份完整原 read SDK 使用同一固定版本 `2050:50139276:111744:1794512618489189978:1794512618489189978`，覆盖区间 `[0, 65536)` 与 `[65536, 111744)`。base64 解码长度、各区段 SHA256、offset、next_offset、size、EOF 全部一致，无缺口或重叠。
2. 拼接后的 111,744 字节与已落盘 `RESULT.json` 逐字相同；SHA256 为 `fc41dfca19277e3e8ba70f98fc545a8ed3c4bf8d3548447b27a4d19857197ab9`，Git blob 为 `d91a27aeddcd10bc729792a565b2e8489e8b03ef`。这属于现有完整 SDK 的独立离线复核，未声称新增 native 读取。
3. normal、stdout 和 same-key reconciliation 都绑定作业 `1a1d1490a3b-2564-1c26`。原 normal 明确 exit 0、未超时、未取消、输出完整且持久化；stdout 的完整 630 字节同时与原 hex、原 UTF-8 text、原文件一致，stderr 为 0 字节。
4. reconciliation 的实际字段为 `reused=true`、`retried_launch=false`、`launch=null`。其 job 中的 key、argv、executable、cwd、host 均与原请求一致，normal 与 reconciliation status 除外层 audit 标志外逐字段相同。此结论不推断未观察的全局作业清单。
5. byte-verified 原 RESULT 报告本地 detached HEAD 从 `86dd56a930277e0d1aef3e475e35c2b5d60b43b7` 前进到 `9c4a11f61d30e9cc352bf44d56c98909d202a55d`，tree 从 `383ab85c39ef9d848252ef5c25922d13d9fae6c6` 到 `ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7`，保持 15,188 个 tracked entries，仅列出已批准的 ports 测试重导出一项变化。此同行核验不重复原源码或对象审计。
6. 原 RESULT 状态为 `SOURCE_ADVANCED_FOR_MAINTENANCE_ONLY`，明确 `qualification=false`、Cargo/formatter 未启动、test_commands_dispatched=0、未更新远端或 source branch refs。不能将它写作实际 fmt 成功、最终格式化源码、源码门禁通过或真实 A/B/C 证明。
7. 原 registry 读取错误仍按其原义保留：作业库存响应超过 1 MiB 返回预算，未返回部分库存。它独立于同一作业已观察到的正常终态，也不表明发起了另一次作业。此前维护的 UNKNOWN、compiler 101、fmt 未运行事实不变。

`REVIEW.json` 含全部输入精确 bytes/SHA256/Git blob 身份、区段元数据、原 normal 与派生结论。`verify_existing_transfer.py` 为本次实际执行的离线核验脚本；它不包含网络或 native 执行入口。placement 只新增这三个同行核验件，原输入作为引用保留，不重复登记为新采集。
