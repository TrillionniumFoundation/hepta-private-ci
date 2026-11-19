# ACT-2：真实 App 漂移、重复观察与读回丢失

**本轮专项通过；完整 ACT-2 与学习晋级保持 HOLD。**

[代码 PR #5567](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5567)
扩展了原有真实 Session/App 测试，并在精确源码
`4674a34528d0097949cc7d604f60de94585d0ba0` 上完成
[运行 42741060239](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42741060239)，attempt 1。
源码 tree 为 `3adccfc79246e1145123c59c17b93ddb48301dab`，父提交为原证据版本
`db3324c75cd4ef1e46ee4603a5fd8df240fe8722`。本报告是受测源码的证据后继，不替代其身份。

## 真实目的地的新证据

以下来自[实际读回 JSON](evidence/notes-actual.json)，属于同一次 App 生命周期。
效果继续经过原 writer、FinalUse、operation identity 与原恢复路径；观察使用既有
nonce 关联的独立应用通道和产品 status 组装函数。没有执行完整模型可见 tool handler。

| 场景 | 实际结果 |
|---|---|
| 第一原 operation 刚完成 | revision 1，历史 applied，当前 satisfied，terminal/succeeded |
| 随后两次真实编辑 | 当前 revision 3；第一 operation 的原 receipt 保留，历史 applied，当前 unsatisfied，runtime UNKNOWN |
| 第三原 operation 重复观察三次 | 每次重新读取原 owner 与应用；完整结果均与原成功观察相同；效果和 grant 计数不变 |
| 关闭并回收测试 App 后重新读回 | 实际返回 Connection refused；owner 仍 Committed，历史 applied 与 receipt 保留；当前文档缺失，goal/runtime 为 UNKNOWN |

整个测试仍是三个不同 operation、3 次 effect attempts、4 次 issuer requests；
其中包含既有的一次主动拒绝。丢回复恢复和新增观察均未增加效果或申请 grant。
三次重复读取不是三个独立实验；本轮不估计未来错误率或 learned hierarchy 收益。
关闭 App 是读回丢失故障，不能解释为 durable tombstone 或迟到提交排除证明。

## 精确执行结果

计数从完整 nextest 日志与命令记录交叉读取，skipped 不计作通过。

| 范围 | 结果 | 命令外层耗时 |
|---|---|---:|
| automation 全包 | 169 passed，2 skipped | 288.769 s |
| Notes projection / private observer / 原 owner | 8 passed，778 skipped | 524.746 s |
| 固定 Session/App locked build | exit 0 | 124.066 s |
| 真实 Session/App 单个显式选择的测试 | 1 passed，785 skipped | 9.825 s |
| 两个受影响 crate 的 scoped fix | exit 0，源码未改变 | 333.164 s |

真实 App nextest 测试阶段为 4.461 s；外层还包括 runner 开销。
这些不是策略性能对照，也不是多个独立样本的完成时间分布。
五份命令记录均未超时、未截断，完整日志 SHA-256 均已核对。
既有编译 warnings 保留在原件；没有宣称零 warning。

两份官方 formatter 输出的 patch 均为空。scoped fix 前后源码 clean、commit/tree 相同；
最终 status 和源码 patch 也为空。测试与最终审阅源码因此是同一个精确身份，
没有把旧运行的通过数转移到新代码，也没有在 fix / fmt 后重复执行测试。

真实 UI companion 固定为 `fd8d56c52b971c2d5d0e6430f296803b43ef60a3`，
tree 为 `347fbb7e9931006c749b5bef0e1550c54bc08f27`。
Session/App 在隔离的 Xvfb、D-Bus 与原测试 issuer 下运行。
锁文件和实际 session/app 二进制摘要在 [RESULT.json](RESULT.json) 及原件中保留。
artifact 未包含完整二进制和锁文件字节，本次复核仅核对记录摘要的一致性；
不能称为独立重算了这些文件的摘要。nextest 捕获成功测试的 stdout，实际目的地 JSON
通过专用输出文件保留，未另与成功 stdout 逐字核对。

## 原件与复核

- [native 原始 artifact ZIP](evidence/native-artifact.zip)：五份完整命令记录和日志、实际 Notes JSON、源码/锁/二进制身份、最终空 patch。
- [formatter 原始 artifact ZIP](evidence/formatter-artifact.zip)：独立格式化 job 的源码身份、formatter 日志、版本与空 patch。
- [GitHub 运行、artifact 和检查快照](evidence/github-metadata.zip)：source head 对应快照；不替代 broad job 的实际 checkout 身份。
- [独立结果复核](INDEPENDENT_REVIEW.json)：对身份、日志摘要、计数与真实场景的再次核对；这是另一位审阅 agent 的复核，不是独立外部验收机构。
- [依赖 CI 审计](DEPENDENCY_CI.md)与[完整原件 ZIP](evidence/dependency-ci-audit.zip)：已有失败记录、实际读取命令、annotations、完整可读日志与读取限制。

两个 Actions ZIP 的全部字节与下载 artifact 的 SHA-256 digest 一致，随报告保留。
本轮没有修改原 writer、observer 实现、effect 权限或固定 skill library。

## 保持的门禁

本轮专项成功不表示仓库 broad CI 已通过。当前 source head 的快照仍有 macOS / Windows
Bazel 与 cargo-deny 失败；依赖栈此前名为 CI required 的检查也为 failure。
旧 broad native job 已找到明确的 runner 磁盘耗尽 annotation，但不能据此把整个旧运行改记通过。
另有实际 Circuit/Agentd 失败，详见分项审计；不能全部归因为环境。

Notes durable tombstone、cancel/commit 竞态、旧 checkpoint 恢复、通用跨观察顺序、
真实长计算/网络等待适配器、生产权限、native kernel 与 pixels 均未由本轮完成资格验证。
共享特征 head/GRU、五组技能对照和组合泛化确认仍为 NOT_RUN。
继续保留固定 skill library；完整 ACT-2 和 learned hierarchy 晋级仍为 HOLD。
