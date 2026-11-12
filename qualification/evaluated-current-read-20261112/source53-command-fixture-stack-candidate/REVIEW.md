# exact53 evaluated command fixture：栈占用候选静态审查

状态：**STATIC_CANDIDATE / NOT_RUN / NOT_FMT**。基线 `53b3227a8dff5af9e39ecef6356cfce702d80b1c`，树 `10cb49cee9c3ca8ed280a680fb262c7e7ce549a1`。两源码候选树 `0d269cbdb9b9686ba46df9962f707e5bdb491b26`；未创建 commit、移动 ref 或派发执行。

## 实际失败与推断边界

原 native job `131459876749` 完整日志 3,842,011 B，SHA256 `2fa1c1754d8e5e3ff600915650bc17e09d7a71ce41795ffcf3f1b58f2c7b3529`。原执行 1,783 方法：1,768 PASS、10 FAIL、4 SIGABRT、1 TIMEOUT。四个 SIGABRT 的原 stderr 都明确说具名 Rust test thread 栈溢出，并以 signal 6 终止。连续原片段保存在 `ORIGINAL_STACK_FAILURES.log`，完整父日志和原行索引在 `OBSERVED.json`。

| 原方法尾名 | 原 elapsed | 本次范围 |
| --- | ---: | --- |
| evaluated_selection_command_lost_ack_recovers_only_exact_readback | 3.338 s | S fixture、恢复和清理 |
| evaluated_next_use_command_lost_ack_recovers_only_exact_readback | 0.380 s | C fixture、恢复和清理 |
| evaluated_next_use_command_once_reads_originals_and_readonly_evidence | 0.415 s | C fixture、清理 |
| evaluated_next_use_command_recovered_missing_cannot_claim | 0.552 s | C fixture、清理 |

这些时间不能定位具体溢出指令，原日志没有 backtrace、MIR 布局或 `sizeof` 测量。丢失 ACK 的实际 command handler/完成解码在原 `std::thread::spawn` peer 中；报错线程是具名 test thread，因此外层 async fixture 值是合理且可直接减小的切口，但这不能排除更深的 runtime 调用占用。候选不宣称已找出唯一根因或已修复四个 SIGABRT。

## 已由原源码证实的构造与持有关系

`ActualCommand::ready` 先完成原 `PublicationFixture::ready`，再由原 `published` 准备/签发/发布，并启动同一个 C Session；实际 T/B clients、task peer、原 S owner随后装入同一 fixture。旧测试虽然 `Box::pin(ActualCommand::ready(...))`，其返回仍是按值 `Self`，外层 test future 继续保存完整返回值。旧 `ActualCommand` 又按值包含 `PublicationFixture` 和 `support::Session`。

`PublicationFixture` 已将更底层 HostFixture 放入 Box，但自身仍持有原 T/B、配置、Source inputs 及 `Option<support::Admission>`。Admission 内含按值 AgentdConfig；Session 也内含 `Option<AgentdConfig>`。Option 的值即使已变为 None，也不把最大变体的静态存储变成堆指针。AgentdConfig 内有多个按值 runtime bootstrap 字段。这里只确认结构关系，未给出未实测的字节数。

`ActualNextCommand::ready` 内嵌整个 `ActualCommand`，还持有原 Material/Dataset、opaque S、原 S command client 和所有原 peer。它通过实际 S Execute/Readback、实际 C task 和原 owner factory 构造 C fixture。旧 C ready 也按值返回，finish 又将整个值捕获到下一层 async future。两个 lost-ACK 方法还按值拆开并重建完整 fixture。

这两个改动 helper 中没有自调用的递归边；本次不据此声称所有底层 runtime 都不存在递归。确切可证的优化对象是上述内嵌返回值和 consuming future，而不是执行轮数、数据量或线程栈配额。

## 两路径实际差异

1. S：`f` 改为 `Box<PublicationFixture>`，`c` 改为 `Box<Session>`；ready 返回 `Box<Self>`。依旧先 await 同一原构造/发布，再装箱原值。
2. C：`common` 改为 `Box<ActualCommand>`，ready 返回 `Box<Self>`；实际 Material/Dataset/S 与 transport 构造顺序不变。
3. 两个 private recover 和 finish 使用 `self: Box<Self>`，以 `*self` 解构原字段。恢复仍释放原 command owner，取得原 held channel，打开同一 journal 的 Readback owner，移动相同 clients/peers；没有复制 custody 或新增连接。
4. 底层 consuming publication/common cleanup future 显式 `Box::pin`，避免把该 future 再内嵌到上一层清理 future。
5. 单独叠加 repository agent 已审的 withdrawal 计数 hunk：同一 helper 的 expected task_reads `3 -> 4`，来源后像 `503a3e20f1ab9e83cf65ceafd5b2be444ef09479`。这不是栈修复；原 T/B `[7,6]` / `[7,7]` 和 S 两个实际 command frames 保持。

没有新 owner、fixture、线程、签名、Clone、I/O、deadline、cap、重试、skip 或栈大小配置。生产 runtime 与 transport 文件均未修改。

## 所有权与清理顺序

两个 private aggregate 没有自定义 Drop，Box 可以消费后解构；原字段仍线性移动。字段借用通过 Box 的 Deref/DerefMut 保持原函数参数类型，`c.stop()` 仍对同一 Session 操作。

C finish 原顺序完整保留：drop C host → join 原 C task peer 并核精确数 → drop C task host → join 原 S evidence peer 并核数 → drop S client → join 原 S command peer 并核数 → drop C files → 原 S finish。

S finish 原顺序完整保留：drop S host → join 原 task peer 并核数 → drop task host → drop T/B clients → join 原 T/B peers 并核数 → drop S files → 取消并 await 原 C Session worker → drop Session → 原 PublicationFixture/Host cleanup。Session 的原 Drop 未变；heap 分配/释放位置变化没有插入新的资源生命周期动作。

所有 `?`、原拒绝分支和显式清理语句保持顺序。恢复仍由原 Readback brand 限制权限，不改 Fresh/Recovered 判定、原 CURRENT/T/B/S 复验或原 deadline。

## 静态验证与验收

`SOURCE_PINS.json` 保存 18 份原输入的 Git blob/SHA256/bytes，以及 8 个原 tokio 方法的完整字节 pin。五个 S 方法和三个 C 方法的**完整方法正文逐字相等**；方法数量净增 0。S assert/assert_eq/assert_ne 数量仍 16/30/2，C 仍 13/31/3。所有签名、错误 variant、文件原 bytes、来源绑定和 peer 数断言均保留；唯一计数变化在独立 helper 中且有单独原调用证据。

逆变换实核：删除 Box/layout 差异后，S 逐字等于已审计数后像 `503a3e20...`；再逆转其单一数字，逐字等于 exact53 `bb93de64...`。C 逆转 layout 差异后逐字等于 exact53 `39709434...`。完整精确差异在 `CODE.diff`。

repository agent 独立检查未见 type/privacy/ownership blocker；其有限闭集扫描为 61 QA 与原 CALLERS：只有 `test_evaluated_retention_command_source_closure.py` 的 NATIVE_CASES 路径列表命中，原 5+3 方法保留；没有 ActualCommand/ActualNextCommand 字段或返回值的闭集约束，CALLERS 无命中。此静态扫描不能代替真实 source guard。

未运行 Rust、formatter、source closure、native、Bazel 或 actor。下一轮仍需原同源 native 路线，在原栈、超时、128-frame 等上限下实际执行全部 8 方法，保留 4 个旧 SIGABRT 原件。只有新原始日志证明原检查全部到达并成功后，才能关闭相应失败。其他 predecessor、deadline、frame budget 或科学资格没有因本候选而通过。
