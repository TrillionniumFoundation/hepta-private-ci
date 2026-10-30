# Execution06：有限终态归档清单与回读副本退役边界

这是一份冻结源码的只读审计与后续操作清单，不是完成声明。研究源码、参数、阈值、已封存结果与历史凭据均不修改。生产调用仍由 root 逐次执行。

## 1. 容量关键结论：已接受的旧 stage 大回读副本可以退役

**当原 supervisor 已经为该 stage 实际写出 `ACK_VERIFIED.json`，且状态确实推进离开该 REQUEST 后，后续 final_closure、最终科学 seal 和 postseal 不再要求该 stage 的大 `readback/part-*.tar.gz` 文件继续存在，也不会再核验它的当前 distinct inode。**

这一结论仅适用于已经接受的旧 stage。发布了 ACK、候选验证通过、root helper exit0 或等待中的 ACK 文件存在，都不能代替 supervisor 接受。

| 冻结消费者 | 实际访问边界 |
| --- | --- |
| `operational/parameter_field_recovery06/archive_io.py::make_ack` | 当前 stage 候选和发布时，重读真实回读字节、完整 transfer/WAIT4 证据，检查源与回读为不同 inode，并调用原 `verify_ack`。该时刻不能退役或硬链接回读。 |
| `operational/parameter_field_recovery04/durable_archive.py::verify_ack` | 每次实际调用都会重新 hash 回读文件并检查 distinct inode。日后主动重调此函数仍需要真实、独立回读文件。 |
| `operational/parameter_field_recovery06/supervisor.py::durable` | 只对当前待接受 ACK 调用 `verify_ack`；随后写 `ACK_VERIFIED`、加入 `self.acks`、清除 `pending_request`。后续 stage 用 `previous_ack` 元数据接续。 |
| `supervisor.py::finalize` | 科学最终 seal 验证 RAW/CAS 与原 30 个 seal。归档旧 durable stage 时只收六个小文件：`REQUEST.json`、`ACK.json`、`ACK_VERIFIED.json`、`MANIFEST.json`、`VERIFIED.json`、`ARCHIVE_COST.json`；不遍历旧 root readback 大文件。 |
| `postseal/prepare_pins.py::collect_primary` | 验证 17 条实际已接受的元数据链、remote identity/version 和最终 RAW 逻辑覆盖；不打开旧压缩回读路径。输出明确标记 `archive_binary_readbacks_rehashed: false`。 |
| `postseal/review.py::open_gate`、`run_supplement.py`、ProducerAdapter 和原 supplement | 重新核验上述元数据 gate 及冻结的科学输入；不会为了旧 archive ACK 再读取已退役大回读文件。 |

现有 `postseal/test_review.py::test_actual_17_ack_chain_does_not_reopen_retired_readback_payloads` 使用完整 17 条元数据链、故意缺失的大回读路径检查这一边界。它是本地合同测试，不能替代任何真实远端 ACK。

### 使用已有退役协议，不把当前科学输入当缓存

已有协议和候选实现位于旧恢复目录 `executor_recovery_20261030T1152/readback_retirement05/`，其中 `RUNBOOK.md`、`AUDIT.json` 和 `retire_readback_parts.py` 记录完整边界。**该脚本硬编码 execution05 的 episode、SOURCE 和 source pins，不能原样用于 execution06。** 如实际磁盘不足，需要在外部工程目录准备有明确06绑定的操作，保留冻结科学源码。

最小执行前提是：

1. 固定实际 stage 和 REQUEST SHA；实际 `ACK_VERIFIED` 与 REQUEST、ACK 完全绑定；同一个 supervisor 已推进离开该请求，或已有真实主完成与 outer wait4。
2. 只枚举该 ACK 中的**独立大回读 part 副本**，固定完整路径；源 part 仍在 `OPS/durable/STAGE` 且当前全字节匹配。
3. 当前源/副本 SHA、大小、完整 stat、nlink、原 remote identity xattrs 和独立 inode 均核对；fresh FD/mmap 检查无活跃引用；已有/部分退役不自动重试。
4. 先落独占 PLAN，后按实际选定 PLAN SHA 执行；每个 unlink 前有 fsynced INTENT，紧邻身份检查，之后有实际完成记录和目录 fsync；保留所有失败/部分成功证据及原 external_step 的 WAIT4/support。
5. 保留**全部源 part**、六个 durable 小文件、所有 readback 小元数据、BOUND_REQUEST、上传/完整 materialize 响应、transfer JSON、真实 helper WAIT4、身份、stdout/stderr、所有 RAW/CAS、注册与 source。远端项不变。
6. 将实际退役 PLAN、journal、RESULT/FAILED、实现 SHA 与真实计量纳入最终 terminal 包。历史 ACK 保持原字节，描述的是当时发生的独立回读；另一个退役收据描述现在的本地缺失。

全 SHA 检查会重新填充页缓存。若再做合法的只读 `POSIX_FADV_DONTNEED`，最后一次验证读取之后必须再对同一核验 FD 提示释放，并如实采样；不能用删除磁盘副本等同于释放了 cgroup 内存。

### 物理去重的边界

- 已接受后的**明确副本退役**是现有可审计协议；它不改变保留源文件的 inode/nlink。
- **把回读路径替换成源文件硬链接不是现有退役协议。** 它会改变源 nlink/ctime，并使日后 `verify_ack` 的 distinct-inode 门失败。不能保留一个同 inode 别名并继续称它是当前独立回读。
- 能保持独立 inode 的文件系统 extent/reflink 去重是否可用，尚无本次实际能力与行为验证；本清单不把它视为已授权实施或已通过的替代办法。
- 如要重新运行旧 `verify_ack`，应从精确已上传版本真实重新 materialize，保留新的实际收据；把本地源复制回原路径不能冒充新的远端回读。
- 退役只节省重复回读占用。保留的源归档会累计；它不证明余下全部 17 屏障的磁盘余量已足够。后续容量仍按原 gate 与实际采样判断。

## 2. 17 个屏障之后，先等真实进程终态

`root_barrier_ops.py` 专用于当前真实 awaiting 的 17 个 stage。它在 `OPS/COMPLETE.json` 出现后会拒绝再工作；**不要用它制造第18个科学 ACK。**

按顺序确认：

- `OPS/durable/17_final_closure/ACK_VERIFIED.json` 已被原 supervisor 实际写出。
- `OPS/COMPLETE.json` 为 `hepta.fullstudy.pipeline-completion.4`，episode06、14个逻辑 job、唯一导入 A17、13个新执行 job、30个最终 seal 和17个 durable stage 均匹配同一实际 pipeline config。
- `OPS/wait4_launcher/WAIT4_COMPLETE.json` 为实际 supervisor entry-to-exit WAIT4，exit0、config/primary descriptor 与 detached measuring-parent identity 一致；保留完整 `owned_supervisor` closure 与其各真实记录。
- `OPS/daemon_bootstrap/DAEMON_RETURNED.json` 已写，target exit0，并与原 READY/ACCEPTED 的同一 PID/start/PPID1/PGID/SID 绑定一致；没有 `DAEMON_FAILED.json` 或 `BOOTSTRAP_FAILED.json`。

READY、ACCEPTED、bridge WAIT4 都是启动凭据；不能代替上述实际 outer WAIT4。`DAEMON_RETURNED` 也不声称是 daemon 自己的 kernel wait4。已经结束的 daemon 不必继续在 `/proc` 存活才能做终态元数据审计。

## 3. 完成一次预登记 postseal 与一次 review

`postseal/prepare_pins.py --execute` 使用实际 pipeline/plan descriptor，通过原 gate 后才创建新的 `BASE/fullstudy_execution06_postseal_20261030/control`。准确 CLI 见冻结 `postseal/README.md`；不存在自动恢复或重复计算入口。

然后读取实际 `control/POSTSEAL_ARGUMENTS.json`，将其完整 `argv` 直接作为原04 external_step 的 child argv。计量目录必须是 `OPS/root_steps/postseal_supplement_01`、cwd 为 `OPS/empty_cwd`、stdin 为 None。不能再插一层 stdin launcher 改变已绑定 argv。

补充输出为 `WORK/supplement/COMPLETE.json` 加九个固定文件：

- `GATE.json`
- `BANK_SUMMARY.json`
- `EQUAL_DYNAMICS_GROUPS.jsonl`
- `SUCCESSOR_DIFFERENCES.jsonl`
- `GATED_CALIBRATION.json`
- `GATED_CALIBRATION_ROWS.jsonl`
- `W_SHARED_ACTION_REGRET.json`
- `INTEGRITY_ISSUES.json`
- `INPUTS.json`

等该子进程真实 WAIT4 后，再以实际 arguments SHA、supplement WAIT4 SHA 调用 `review.py --execute-review`，由另一个真实 external_step 计量到 `OPS/root_steps/postseal_review_01`。成功 review 新建：

- `WORK/review/A_INACTIVE_GLOBAL.json`
- `WORK/review/REVIEW.json`
- `WORK/review/COMMENTS.zh-CN.md`
- `WORK/review/COMPLETE.json`

加上 control 两文件，整个 postseal 固定成功输出是 **16个文件**。保留真实三个 root step（prepare、supplement、review）的完整 WAIT4/support，尤其 review 自己的 WAIT4；review COMPLETE 写出时它尚未存在。

Supplement/review exit0 表示无报告的 integrity issue；exit3 在完整收据一致时是“已完成但有明确完整性问题”，须保留并阻止无条件科学解释。不能把 exit3 改成0或为了得到正结论自动重跑。Exit2、未完成或 provenance 不一致是失败/阻塞，不能写完成声明。

## 4. 一个终态 payload 包的最小内容

等上述所有必要进程真实退出、文件稳定后，再建立一个**独立 terminal 包**。下表是必要信息集合；已有17次远端保存的大科学 payload 以精确外部引用接续，不需要再塞进一个越来越大的包。

| 集合 | 必须保留的内容 |
| --- | --- |
| 主完成与最终状态 | `OPS/COMPLETE.json`、最后稳定的 STATUS；实际 pipeline descriptor、C1/C2 source commit 与真实公开绑定；初始及各阶段注册、producer/import/freeze 描述符。 |
| 完整 outer 计量 | `OPS/wait4_launcher/` 下全部已闭合普通文件：INTENT、START、WAIT4_COMPLETE、supervisor stdout/stderr、`owned_supervisor` INTENT/START/WAIT4/CLOSURE。 |
| 完整 detached 启动与返回 | `OPS/daemon_bootstrap/{INTENT,FORKED,READY,BRIDGE_WAIT4,ACCEPTED,TARGET_STARTED,DAEMON_RETURNED}.json`、已关闭的 daemon stdout/stderr，以及 root 当时启动 bootstrap 的实际外部计量。 |
| 17 条持久化证据链 | 每个 stage 的六个 durable 小文件；当前 ACK里全部 actual remote item/version/bytes/SHA；root stage work 的 BOUND、上传请求/结果/验证、完整 materialize 响应、READBACK_PLAN、transfer metadata、候选/验证/发布 liveness，以及所有真实上传和回读 WAIT4/support。 |
| 最终科学索引与可读结果 | verification06 的 MANIFEST/VERIFIED、finalizer与aggregate freeze、REPORT_INPUTS、封存的 RESULTS/REPORT 及其已由17次归档覆盖的逻辑路径/bytes/SHA索引。大 RAW/CAS/part 继续由实际已接受远端引用覆盖，不伪称重复上传。 |
| Postseal 与评论 | 上节16个实际输出，prepare/supplement/review三个完整真实计量；保留 C2 中准确的 plan/implementation/contracts。 |
| 外部工程与容量变更 | 已完成的真实 root helper 计量索引（含 RECOVERY 中的启动前操作和 `_engineering`/`readback_steps`）、不重叠成本范围、所有实际退役/缓存提示 PLAN/journal/result与WAIT4；保留旧失败/unknown边界。 |
| C2之外实际执行的 glue | `root_barrier_ops.py` 的确切字节、runbook、验证/独立审阅及真实测试计量。它不在冻结C2里，不能假定从C2恢复。每个生产phase已绑定的glue/source/helper SHA应相同。 |

排除包本身、其正在写的 measurement、未来 delivery receipt 和大 duplicate readback part。排除不是删除：所有本地文件按其各自保留/退役规则处理。为不再内嵌的大既存 payload 写一份明确引用索引，使用真实原 manifest+ACK 已证实的 file_id/library_file_id/version/bytes/SHA；不把同名路径或“最新版本”替代原版本。

Root 工程成本单列：outer supervisor-inclusive CPU 不再加 worker/driver/archive 子项；supplement 自报区间不再加到其 inclusive WAIT4；review自报区间不再加到其未来inclusive WAIT4；root如再包一层phase计量，也不能加重复包含的helper子项。旧05缺失 outer 仍是未知，当前证据不能补造历史 kernel wait4。未计量的 root/远端服务范围保持明确未知，不能用它宣称完整 CPU 上界。

## 5. 有限的终态远端闭合，不形成 checkpoint 循环

冻结源码明确说明：最后17号 ACK 不可能包含后来才产生的 primary COMPLETE、outer WAIT4、postseal、review WAIT4。终态包正好补这一时间差。

执行一轮 terminal payload 的实际上传、精确版本独立回读、全字节验证，保存真实 helper WAIT4/support，生成一个 terminal closure 记录。该记录应列出本包 descriptor、实际远端身份/版本、实际回读验证、17条既存 payload 引用、已完成 postseal/review及解释状态，并明确包的截止点。

**再持久保存这个 terminal closure 记录本身一次**，保留其实际返回身份与已验证字节；root 最终公开清单或交付索引指向 terminal payload 和 closure 的确切版本。最后一轮实际服务响应与公开提交身份是外部观察锚点，不要求一个文件包含它自身未来的上传收据。不能因此递归制造“再归档上一轮验证的验证”。

终态结束条件是：

1. 实际主完成、17接受屏障、outer WAIT4和detached return一致。
2. 预登记postseal/review已按真实exit0或exit3状态闭合，五项评论完整，未改原科学门。
3. Terminal payload已实际远端保存并独立同版本字节回读通过；terminal closure记录本身也已持久保存且身份可引用。
4. 已授权公开清单中的代码、登记、报告及凭据实际发布，选择的远端内容/提交身份核对完成；私有完整服务响应保持私有，不公开签名下载URL。
5. 所有未知、历史失败、原资源契约未满足与能力外推限制准确披露。完成不等于参数场/Hepta获得正收益；不因负结果或有限外推再自动增加实验。

达到这些条件即可报告闭合。没有新增科学工作、没有新发现的字节不一致或新的真实失败时，不再启动可选重复hash、重复postseal或新的checkpoint系列。
