# ACT-2：实际效果观察的有界资格结果

## 结论

**受测范围通过；完整 ACT-2 与 learned hierarchy 晋级仍为 HOLD。**

本轮完成通用五态观察、Notes 原操作状态接线，以及一次真实 Session/App 的丢回复恢复与当前目标核对。
这不是 16 条验收要求全部通过，也不是学习收益结果。Notes 是原子替换 profile，仅报告有证据支持的 terminal / UNKNOWN。

- [固定受测源码](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/cada860abe458be96671b11b339abfb7d2052580)：`cada860abe458be96671b11b339abfb7d2052580`。
- 受测 tree：`8d98cf164ca52160a6c079506b6b8709218a2a13`。
- [资格运行 42613527940](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42613527940)，attempt 1，两个 job 均成功。
- [实际 native job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42613527940/job/129147647221)。
- 开发基线 M6：`885dae0f3285267e9e9c49d8b43b0d009779f9e8`，不是 main。

## 已交付的代码阶段

| 阶段 | PR | 行为 |
|---|---|---|
| A | [#5470](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5470) | running、waiting-input、partial-effect、terminal-with-outcome、UNKNOWN；保留底层执行、目标和取消事实 |
| B | [#5511](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5511) | Notes 原 receipt 与本次独立文档读回联合核对；接入既有 product status / replace 返回路径 |
| C | [#5512](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5512) | Completed provider 阳性控制及七种观察错误；Notes 身份、漂移与未知状态回归 |
| D | [#5514](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5514) | 固定真实 Session/App、实际 GUI 资格测试、验证 workflow 与学习协议 |

观察不授予 dispatch、settlement、cancel 或 retry 权限。原 FinalUse、冻结 wire bytes、operation identity、readback 与通用 tombstone 条件保持原路径。
`observe_pending_state` 出错时没有 runtime view；调用者应按 unresolved / UNKNOWN 处理，不能据此重发效果。

## 实际运行结果

以下分母直接来自保留日志，skipped 不计作通过。

| 执行范围 | 原始 nextest 结果 | 命令外层耗时 |
|---|---|---:|
| `codex-hepta-automation` 全包 | 169 passed，2 skipped | 276.069 s |
| Notes projection、既有 private observer、原 owner 定向范围 | 8 passed，778 skipped | 476.123 s |
| 固定 Session/App 的 `cargo build --locked` | exit 0 | 115.984 s |
| `notes_actual_ui_original_owner_roundtrip`，仅该 ignored 测试 | 1 passed，785 skipped | 4.422 s |
| 两个受影响 crate 的 `just fix --locked` | exit 0；before / after 源码均 clean 且身份相同 | 288.471 s |

五份命令记录均没有 timeout 或输出截断。耗时包含冷编译、链接或 runner 开销，不是学习策略的性能比较。
日志保留既有 lifetime、scoped-metadata 和 unused-patch warnings；本报告不声称零 warning。
测试之后运行官方 formatter；没有为了格式化再次执行测试。

## 真实目的地确认了什么

实际使用固定的 [trillionnium-os-desktop 源码](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/tree/fd8d56c52b971c2d5d0e6430f296803b43ef60a3)：
`fd8d56c52b971c2d5d0e6430f296803b43ef60a3`，tree `347fbb7e9931006c749b5bef0e1550c54bc08f27`。
Session/App 在独立 Xvfb、D-Bus session、软件 GL 与原测试 issuer 下运行；未接触用户桌面文档。

[实际观察原件](evidence/notes-actual.json) 记录：

- 原 operation：`notes-real-ui-fixture-lost-reply`。
- 写入完整 frame 后关闭 effect stream；故障夹具没有读取 effect reply。
- 原 source 从 `indeterminate` 经同 identity 恢复为 `committed`。
- 本次当前文档读回可用，target 与原目标一致，revision 为 3，原 expected revision 为 2。
- 当前 text SHA 与原目标 SHA 均为 `d742490feb42388586933f9e89646c2917a4c3f95f166e2235076c408a0f229d`。
- `historical_effect=applied`，`current_goal=satisfied`，runtime 为 `terminal/succeeded`。
- 整个真实 App 测试覆盖三个不同 operation，总计 3 次 effect dispatch attempts、4 次 issuer requests；其中包含预先主动拒绝的一次 issuer 请求。丢回复恢复未增加效果或申请新 grant。
- `recovery_effect_replay=false`，`recovery_requested_new_grant=false`。

这证明本次真实 App 原 owner 恢复与当前目标观察链路。原 receipt 证明历史效果，本次 nonce 关联查询提供当前文档；两者同时满足才报告当前成功。
这不是完整 live model / protected-sender handler 的端到端运行，也不是生产授权资格。
原件明确保持 `production_authority=false`、`native_kernel_qualified=false`、`pixels_qualified=false`。

## 16 条验收要求的覆盖边界

完整要求保留在 [PROTOCOL.md](PROTOCOL.md)。下表只描述本轮实际受测层级，不把某一层通过扩展为全部层级通过。

| # | 要求 | 本轮证据与剩余范围 |
|---:|---|---|
| 1 | 原 receipt 与当前目标一致 | 真实 Session/App、原 owner 模型和纯 projection 已覆盖此成功链路 |
| 2 | provider 成功但读回不可用 | 原 owner + socketpair 应用模型及 projection 已覆盖；真实 App 读回断链未运行 |
| 3 | text 匹配但 receipt 缺失 | projection 已覆盖；真实 App 故障注入未运行 |
| 4 | 历史 receipt 后 text 漂移 | projection 已覆盖；真实 App 后续编辑与 status 联合验收未运行 |
| 5 | text 相同但 revision 不符 | projection 已覆盖；不绕过精确 revision 契约 |
| 6 | target、nonce、operation 错配 | operation / receipt projection 与既有 nonce-correlated socketpair observer 测试已覆盖；不是所有真实 App 错配场景 |
| 7 | 已提交但 reply 丢失 | 真实 Session/App 与原 owner 模型覆盖，同 identity 恢复无新增效果 |
| 8 | 旧 checkpoint 恢复后 fresh read | 本轮不能证明过期 checkpoint 场景，专项 HOLD |
| 9 | 重复 status / read 不产生写入 | 本次真实观察未增加效果或 issuer 请求；重复完整 handler 场景尚未全部覆盖 |
| 10 | receipt pending 不是 input wait | projection 已覆盖；真实 App 本次当前读回发生在 receipt 退役之后 |
| 11 | tombstone 后迟到结果 | 通用受控 destination 覆盖；Notes 未提供 durable tombstone / late-commit exclusion，HOLD |
| 12 | cancel 与 commit 同时存在 | 通用事实保留有受控测试；Notes 无独立 cancel 事实及竞态验收，HOLD |
| 13 | exit 0 不能替代目标确认 | 受控 SQLite destination 的 execution / goal 组合覆盖；不是任意真实生产工具适配器证明 |
| 14 | partial 后 waiting-input | 受控 destination 的 SQLite 部分效果与真实 stdin 子进程等待均保留；Notes 原子 profile 不推测 partial |
| 15 | 长计算 / 网络等待 | 受控 running 状态有测试；真实长计算和网络等待检测 adapter 尚未资格通过 |
| 16 | 陈旧 / 乱序 / 冲突观察 | binding 错配与 Notes revision regression 保守拒绝；通用类型无 sequence / high-watermark，不提供跨观察顺序保证 |

## 格式化、最终审阅源码与原件绑定

本轮 Hepta 测试均在 `cada860` 执行；Session/App 由固定 companion 提交 `fd8d56c` 构建。没有把先前 M6 结果转贴到新代码。
scoped fix 未改源码。native job 最后产生的 formatter patch，与独立 format job 的 patch **逐字节相同**：

`0e8fc74e5191fe632c784dfc066f26102c7b9fdf1c88e75bb5e855f1d914cad5`。

逐文件校验并应用该 formatter 输出后，仅另行澄清 PROTOCOL 中 Notes cancel / tombstone 的 HOLD。
从受测 tree 应用这两类精确变化得到 `d58a6cff59ea966305fedce0bebb1e62f1853e85`，
与审阅源码 `0817910eb1889c1d341a1bd5122a69777d539cd8` 的完整 tree 相同。
本结果提交仅增加报告和原件；不能把测试称作在不同 commit 上重新执行。

- [完整 native artifact ZIP](evidence/native-artifact.zip)：原始命令记录、完整命令日志、当前目标原件、源码与二进制摘要、最终 formatter patch。
- [完整 formatter artifact ZIP](evidence/formatter-artifact.zip)：源码身份、rustfmt 版本、精确 patch 与格式化后完整文件内容。
- [机器可读结果](RESULT.json)：原件 SHA256、精确计数、运行身份及未关闭项。

两个 ZIP 与下载到的 Actions artifact **字节相同**，随此报告保留，读取证据不依赖 Actions artifact 的 14 天保留期。

## 未关闭的门禁与第二阶段

当前四个审阅 PR 的仓库 blocking CI 在记录快照时均为 queued；不能据此合并或宣称全部仓库门禁已通过。
旧首版 `da4e882dd6740ccb64ca9623fe5aa413bd9df675` 的广泛反向依赖 job `129139839821` 为 failure，日志下载返回 BlobNotFound；原因尚未确定，未被本轮 scoped 通过抹去。

原 HeptaRuntime 只读环境发现有响应不确定的请求，稳定 key 与原 host 保留在 RESULT；没有将它们改记为失败，也没有以新身份重发构建。
本轮最终使用 GitHub hosted CPU runner 完成验证，没有启动 Colab / Kaggle 训练。

五组技能学习对照、共享语义特征、小 head / 私有 GRU、duration / termination 与效果残差目标、目的地 / schema / 组合分组确认、UNKNOWN 缺失标签和完整成本要求均已写入协议。
**训练、确认收益与 learned hierarchy 晋级都是 NOT_RUN / HOLD。**
一个原子 Notes 恢复链路不能构成组合泛化或质量—成本改善证据；当前继续保留固定 skill library。
