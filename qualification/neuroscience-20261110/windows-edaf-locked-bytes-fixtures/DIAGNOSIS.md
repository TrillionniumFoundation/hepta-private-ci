# Windows 非空 journal 字节检查：七个原失败方法的最小候选

状态：静态源码审查；未运行格式化、Rust 编译、Bazel、Windows 或 Linux 测试。原失败保持原样，候选不代表通过。

## 原证据和源码身份

原 Windows job 131310622783 的完整已读日志为 859,515 B，SHA256 76bc57cb5bbfeb8a57c74629779a10456cebf3b4e11dbabc6e90b20bd3a35d6d。实际 checkout 是 PR merge 6344842074357063c00dce9f2b67d789b2988c6f，不把它改写成 source-head 执行。FAILURES.json 保存本候选对应七个不同方法的首次原始失败片段和原日志字节偏移，重复日志展示不增加方法数。

候选父提交固定 edaf1d9a420dc99336f36b24515eb9c65a97b0da。六个被修改文件分别在原 merge、286c 和 edaf 读取，blob 和完整文本相等。此候选不覆盖 edaf 的实际格式修正，也不移动正在运行的分支。

## 根因与修改

| 原方法组 | 静态定位 | 修改 |
| --- | --- | --- |
| feature commit 撤销后恢复 | 最后一次 recovered owner 查询之后仍持有 journal 锁，随后 Files::bytes 重新打开同一路径 | 在原最后一次查询之后 drop(owner)，再执行同一完整 bytes 断言 |
| feature revoked admission | 热 owner 撤销前后都由 Files::bytes 打开第二个 File | 复用 cell_journal_tests 已有 journal_bytes 原句柄读取，提供仅 cfg(test) 内可见的 inherent 方法；相同两个时点仍比较完整 Vec |
| completed typed operation 与 compact intent 冲突 | serving 仍持锁时进行最终 fs::read，之后已没有新的 owner 工作 | 将既有 Serving.finish 提前到最终完整 bytes 检查之前；原 worker calls 断言保留 |
| 两个 episode 与两个 credit 方法 | 热 LedgerWriter 持锁时 LedgerFixture::bytes 重新打开 ledger/witness | 使用已启用 qualification-legacy-write 的原 LedgerWriter::qualification_file_bytes，读取同一 ledger/witness 完整原字节 |
| episode / credit 冷恢复两端 | 原 generation bytes 采样紧邻既定 shutdown/drop，但在其之前 | 只移动至原 shutdown/drop 之后；相同两端仍比较完整 generation Vec，无新生命周期 |

原 neuron journal_lock 明确不支持 cloned/inherited application handles。候选没有复制、重开或暂时释放持锁句柄，也不把任何非空文件替换为空 Vec。

原 CellOwnerJournal 测试 helper 使用持锁的原 file，保存游标、rewind、read_to_end、恢复游标。新调用只存在于原 cfg(test) 模块；运行时 public API 没有增加。

LedgerWriter 的原资格接口先要求 Durable backend，独占可变借用同步读取原 ledger 与 witness，每文件最多 8 MiB，始终恢复游标，读错误向外传播，不 clone/open/unlock/sync。现有 Cargo dev dependency 和 Bazel testonly 依赖已经启用此接口；本候选不改依赖或 feature。Fixture 原 writer() 的 from_durable 路径逐字保留。

原 neuron_generation_service 的 host cancellation 分支直接退出，明确只有 service retirement 才持久写入 Drain。原 host() 将同一个 cancellation token 交给 RuntimeTasks 和服务。移动终末检查没有插入 retirement、drain、重新 attach、重新执行模型或重开 journal。

## 保留的断言与仍待解决的范围

七个原方法全部保留，没有新增或删除 test 方法，没有 skip、平台排除、重试、timeout/cap 放宽。原 CURRENT 撤销、请求/签名/receipt、模型调用计数、错误 variant 和完整 Vec 比较均保留。热 ledger 和 feature 检查仍在原 owner 存活期间读取实际原文件；并未降级成长度、内存快照或 continuity digest 比较。

FAILURES.json 另列出七个仍含真正热 generation 跨 crate 路径的原方法。CellGenerationJournalV2 的现成持锁字节 helper 只在 neuron cfg(test) 中存在，不能假称 agentd 依赖也具有该方法。此批没有为它们新增生产接口或测试 feature，不声称这些失败已闭合。

另一个独立的源码观察是 infer-core durable_control.rs::replay_file 在原 try_lock 后使用 file.try_clone 构建 BufReader。它不是本候选改动，也不是仅凭源码即可认定的本次原 panic 精确栈；若后续验证出现非空 Control 冷恢复错误，应单独核同一 owner 读取方式，不用新增 clone 规避锁。

## 真实验证仍需执行

- 在发布后的 exact commit 上运行原 Windows Bazel roster，核七个原方法是否实际执行并通过，保留完整原日志和 source/tree。
- 在同源 neuron / agentd 原入口验证，没有删除原方法、没有平台 skip，热字节检查不改变原执行/恢复次数。
- 执行原格式门和 source/caller 检查；这些未由本次 Git 静态操作代替。
- 其他七个热 generation 方法、所有研究效益及 owner 决策继续开放。science=HOLD，owner_decision=null。
