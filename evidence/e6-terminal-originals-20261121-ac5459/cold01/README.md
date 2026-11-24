# E6 Cold01：完整失败原件与终态回读

本包保留 actual80 的一次原始 whole-cold EvaluatedNoUpdate 尝试：**已终态失败，1 个 case，0 通过、1 失败**。它不是成功 cold/restart 证明，也没有 Adopt、独立后续任务 D 或学习收益。NoUpdate19 的完整普通 NoUpdate 成功仍由此前独立原件支持，二者不合并成成功结果。

## 实际结果

| 层次 | 原始结果 |
|---|---|
| H job | `1a1fdeb7f2f-ffbe-2013`；failed，exit 1；complete / durable / confirmed |
| SSH / owner | exit 1；owner completed 且 successful=false |
| 原 nextest / recorder | exit 100；完整失败日志 45,552 字节 |
| 唯一 Rust case / canonical XML | exit 101；0 passed、1 failed |
| 内层错误 | `Error: actual first publication verification fact differs` |
| 更早的原 stderr | 保留 objective acknowledgement lost / control read timed out |

固定源为 `61503a7d3bc87a5584cd2f20b8b17ea3838fdcfd`。主结果 56,097 字节，SHA256 `f9a481ce70e1b84dc7354856e9d1e72496bf443760a52a928a516320ee8a21a6`。H 原 stdout 6,468 字节由两段连续 bytes_hex 重建，stderr 为 0；ROG transport、AI dispatch、主结果字段、recorder、collection 和 canonical XML 互相核对。当前 canonical XML 与 observed XML 是同一运行的两个保存位置，不能计成两个样本；旧排除 XML 也不计入本次通过数。

## 68 项库存全部保留

`owner_originals/` 恰好对应主结果的 68 项 log_inventory，共 12,897,009 字节，每项长度和完整 SHA256 均匹配。来源逐项写入 `OWNER_FULL_READBACK_MANIFEST.json`：

| 来源方式 | 项数 | 含义 |
|---|---:|---|
| 先前已经完整取回的本次原件 | 16 | 再核原 binary response、完整字节及 chunk SHA |
| 新固定版本完整读取 | 24 | 60 个成功分片，共 2,698,035 字节 |
| 当前路径 full SHA + 已保留相同字节 | 22 | 包括此前原件与本次 canonical XML；明确不称重新下载 |
| 当前路径 full SHA + 本包相同内容代表 | 6 | 每个路径都有自身当前 version / 完整 SHA，再复用已核代表字节 |

52 个待补路径全部有新 file_info。一次 SSH 255 元数据错误原文保留，并只对该缺项重读成功；二进制分片没有失败。本包还保存 peer 先前一次 stdout 元数据 SSH 255、随后实际完整读取，以及四个本地 wrapper 多出字面 `\n` 的原坏字节、修正 wrapper 和未改写的远端原 content.text。后三者不混成远端数据异常。

`INDEPENDENT_FULL_FAILURE_REVIEW.json` 是恢复后重新核验，明确标记 `RECONSTRUCTED_REVIEW_FROM_RETAINED_ORIGINALS`。两次本地审查初稿的 schema / stage-name 假设错误原 traceback 和修正说明也保留；它们发生在纯本地解析，不改变任何执行原件。

## 执行身份与执行前记录

四份 list claim 和一份 case claim 与执行 manifest、same-FD 身份、实际 shell 环境观测和原命令一致。claim 本身不证明测试通过；失败结论以原 recorder 和 canonical XML 为准。10 个 stage 中 9 个准备阶段成功，唯一 whole-cold 执行失败。

执行前实际格式 job `1a1fde6b4af-ffbe-200a` 成功。保留 5 份授权回读的 owner 原件、完整 H 284/0 和 39 条源文件 before/after 字节一致结果；其他格式 owner 命令只保留 RESULT 内的原 metadata，未声称完整下载它们的 stdout/stderr。原 `just fmt` 输出为没有变化的文件需要格式化，qualification 路径不在该 registry 范围，所以不称 Ruff 或全仓格式覆盖。实际 checkout / command base 为 7f790，4c55 是发布参考，未冒充完整 4c55 checkout。

执行前部署 job `1a1fde8fbea-ffbe-200c` 成功。完整 H 5,837/0、ROG transport、MATERIALIZATION、SEAL 以及 11 个 deployed 文件的独立 full SHA 都保留。部署本身 native attempts=0，随后 root 单次启动 actual80。原 candidate 的 8 个 Git blobs 和发布回执继续引用既有 e03c97a commit，不在本包改写。

## 仍未闭合的范围

两个受保护路径读取在共同根目录处收到 errno 13，本包保留原响应。它们不证明下级文件存在或不存在，也不提供实际 first-publication fact 的字段。本包未取得那些物理文件；68 项 inventory 的完整性仅适用于主结果明确列出的 owner 文件。

后续从固定 61503 源取得的 Rust 文件归类为只读诊断来源。即使源码显示 genesis / drained 期待之间存在矛盾，也不能写成已经逐字段定位实际 first-fact 的全部失败分支。新修复和受保护文件 collector 候选不作为已执行结果放入此包。

主结果记录两次 owner 清理命令 exit 0；这是当时的清理观察。本包没有新增独立 postterminal 进程组或挂载快照，也不声称当前所有组均不存在。ELF 模式是原已存在 0o555 的核验 no-op，chmod / writes / unlink / rename 全为 0；不重分类 NoUpdate18 的 mode restoration skipped。保留旧两 ELF 的完整 SHA 核验回执，但未重复下载数 GB ELF。

owner 118.236372653 秒、SSH 121.607171266 秒、recorder 98.070776956 秒属于嵌套区间，不能相加。准备编译、缓存、失败 owner 和历史成本仍存在；物理能耗、网络、存储时长及费用没有完整计量。本用例使用原 analytic Q24 fixture，不是 E2 LoRA 或独立真实用户任务收益，不能扩大成 foundation model 或 proof-of-useful-work 资格。

## 文件与校验

`CONTAINERS.json` 描述一个**本地新建**的 xz 容器，不冒称远端原 tar。`CHUNKS.json` 给出每个 350,000 字节以内分片的 offset、长度、SHA256 与 Git blob SHA1。按分片序号连接后应匹配容器完整 SHA256。

解包后的 `MEMBER_INDEX.json` 为全部 548 个源成员列出长度、SHA256 和分类；索引自身另在外层容器描述中绑定。容器含 549 个普通成员，每个都在封包后重新校验。`SUMMARY.json` 汇总关键结论；`REFERENCES.json` 绑定此前成功、失败及 candidate commit。

新增 Git 内容只有 5 个文本说明文件和二进制分片，文件模式均为 100644；没有新增可执行 verifier、allowlist 或 ignore 规则，不覆盖任何旧路径。收证阶段没有新 native、collector、格式或部署进程。创建 immutable blobs 不等于更新 branch；实际 commit / ref / PR 仍由 root 单独完成。
