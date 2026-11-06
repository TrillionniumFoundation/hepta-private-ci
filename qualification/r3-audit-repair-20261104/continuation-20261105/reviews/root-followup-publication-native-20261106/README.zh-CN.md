# 根复核、实际发布与新增原始 CI 证据

本包将四次已发布修订、B23 原验收条件闭合、实际 cargo-deny 失败及七个固定来源的完整 CI 切面放在一条可离线核验的证据链中。原始 API/工具返回、解码日志和官方 ZIP 保持原字节；JSON 汇总另有明确 schema。临时下载签名 URL 的工具返回不在归档内。

## 结论

- **B23 CLOSED_SCOPED**：原字面 exit 未改。独立审阅和根的两次离线重放逐字一致；真实诊断执行的 307 PASS / 1 IGNORE 与原 GNU CI 八分片缓存通过分属不同结果链，不能声称共享缓存键。原诊断 job 仍失败，两个 Fetch 重复事件和八份 XML 缺件仍保留。原始诊断与 main GNU 六 ZIP 已分别实际登记，解决此前审阅中的 custody pending；原审阅文字保留不改。完整项目、其它平台和 B15 不随此关闭。
- **#4902 / #4910**：共享 collector 新头分别为 `84cc73453eb926d6f2c5b0372c0287b0ab86ed53` 和 `2ac89eaf91306d410ef5e9b548ee9fabd12b71b7`。保留旧 PR body，完整 commit/ref/PR/merge/tree GET 可核。新的 XML 收件结果仍在执行。
- **#4913**：格式修订实际头 `18bbef4f61c6086f145bdb6f7acbf82127741a14`。仅按原 repo-check 原日志的两处 rustfmt diff 改布局，原日志完整保留。旧 `340fbc0` 的两新增用例原生通过不能转授到新头。
- **#4927**：PTY 候选 `8075eb367b6e97546af206b27bbf4a3a867497c8` 只消除已关闭接收端的分配/发送工作，原 2 秒、4 MiB、31 例、两后端和全部产品控制不变。根静态重放通过；未宣称旧超时根因已证明，B21 保持 OPEN。
- **#4922 原 cargo-deny**：run `42162085830` / job `127715564317` 的官方 artifact `13478122141` 原 ZIP、11 个成员和完整 12,397,460 字节原日志可恢复。原命令 exit 1，唯一 error 是 `pin-utils` 停止维护 `RUSTSEC-2026-0441`；advisories 失败，bans/licenses/sources 通过。四条直接依赖来自三个固定 AWS crate 与 Loom。旧 main cargo-deny 日志未取到，其历史原因继续 UNKNOWN。
- **#4923 原 GNU Clippy 已通过**：job `127717742578` 的 API success 与完整 863,099 字节日志均保留。实际 checkout 为原 publication 已绑定的 `65e1ec7164063b139db291562dd6093c3008b403`；日志记录构建成功和 clean check。该结论是原 CI 检查通过，不声明所有动作是新鲜无缓存执行。

## 最新完整切面

七个精确 head 的 46 个 run 及其全部 latest-attempt jobs 在 **2026-11-06 05:20:01–05:21:49 UTC** 读取，所有分页总数与实收数一致；这是时间窗口快照，不是原子事务。

| 固定来源 | run | job | 成功 | 失败 | 取消 | 跳过 | 排队 | 执行中 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 主修复 67cc5 | 19 | 93 | 68 | 9 | 10 | 6 | 0 | 0 |
| B21 collector 84cc7 | 4 | 9 | 3 | 0 | 0 | 2 | 2 | 2 |
| B23 collector 2ac89 | 4 | 9 | 4 | 0 | 0 | 2 | 1 | 2 |
| Windows format 18bbe | 5 | 7 | 3 | 0 | 0 | 2 | 1 | 1 |
| cargo 日志修复 47665 | 3 | 41 | 27 | 6 | 0 | 6 | 2 | 0 |
| arg0 修复 3c9e2 | 5 | 43 | 29 | 4 | 0 | 6 | 3 | 1 |
| PTY 候选 8075e | 6 | 12 | 2 | 0 | 0 | 2 | 4 | 4 |

Windows format 的一个 pending run 尚未物化 job，因此 run 与 job 的未完成数不能直接相等。主修复的九个失败为七个执行失败、Windows 汇总和最终 CI 汇总；汇总门禁不增加独立根因。较早 04:41–04:43 三分支切面也完整保留，不能与最新分母混算。

## 离线恢复

运行 `python verify_packet.py` 验证全部分片、完整 transport ZIP、46 个原件成员、每个实际发布对象、官方 cargo artifact、原命令失败、B23 原 exit 和两组完整 API 切面。`--extract /目标目录` 可恢复所有原件，内嵌官方 ZIP 不被重打包替代。验证不会访问网络、执行产品、改变 CI 或扩大任何 blocker 的资格。

根离线实际 stdout 和 exit/stderr 记录随包交付。源码级独审和完整原失败包分别由相关登记包承载；本包不是对所有未变更产品叶的重新语义审计。未来的 CI 变化需要新的有时间和来源边界的证据，不能回写本包历史。
