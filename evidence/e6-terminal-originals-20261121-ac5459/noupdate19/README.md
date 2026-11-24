# NoUpdate19：完整原生 NoUpdate 与终态原件

本包保全同一固定源码上的 NoUpdate19 实际执行、只读 collector77、完整原件和重新核验记录。原生 owner 成功结束，4 个当前 canonical 测试用例通过，13 个阶段及对应检查通过，原 ordinary complete NoUpdate parent 已执行完成。

这里的 4 是本次回归测试用例数，不能当作 4 个独立学习样本。完整 Root Feature ACK、真正 Adopt、cold/restart 后的 fresh D、训练收益、真实独立来源认证及结算资格都没有因此成立；SUMMARY 中相关标志保持 false。

## 最有用的证据

- 原源码 commit：`61503a7d3bc87a5584cd2f20b8b17ea3838fdcfd`，tree：`a2ead7f0d3a88549cd885862ad07e434b6379f81`。
- 原生 H job：`1a1fdc3f9c0-ffbe-1fe4`，真实终态 succeeded、exit 0；完整主结果为 99,983 B。
- collector77 H job：`1a1fdd0f0ef-ffbe-1fee`，真实终态 succeeded、exit 0；此次收证没有执行 native 测试或目标 ELF。
- 77 原归档为 2,270,958 B，SHA256 `38af0e2c925c218330bf0e683954dc49f7a54ab51695015d87a4b195e68482ae`；包含 146 份原件及原 READBACK_MANIFEST，共 147 个物理成员。
- 124 项原生结果清单逐项核对 path、长度和 SHA256，总计 13,493,731 B；core 的 104 份嵌入原件与归档逐字一致。
- 4 份 canonical XML 与对应 fresh 原件一致，并绑定 recorder、完整日志和实际执行 claim。3 份 prior XML 明确排除，claim 本身不充当测试成功证明。
- 全部源文件、受跟踪字节与编译输入的 before/after 保持一致。部署落地的 11 个文件与冻结候选及实际归档逐字一致。

## 证据边界

原生入口目标文件本次进入时已为 `0o555`。对应记录是 `verified_preexisting_entry_mode_noop`，chmod、写入、unlink、rename 均为 0，不是新的权限修复。历史 NoUpdate18 的 mode restoration skipped 仍原样保留。

77 在原生 H 终态之后独立观察到 13 个记录的命令进程组及 dispatch preflight PID 均已消失，没有剩余 owned bind mounts。这是指定范围、指定时点的观察；`snapshot_atomic=false`，不构成未来持续存活或全系统原子快照保证。

外部 physical `ordinary-whole-phase` 路径的元数据读取被权限拒绝，两份错误原文及原始定位线索在侧包中。该目录的内容未下载，child 是否存在未被独立观察，也不属于本包所称完整的 124 项 result inventory。归档内普通 stdout、recorders、XML 与此访问缺口分开陈述。

完整成本尚未闭合。helper/product/library 准备、保留缓存及先前失败 owner 均有成本；命令与 owner 时间存在嵌套，不能相加为总时间。物理能耗、网络、存储时间及收费仍未知。

## 原始错误与历史保持

两次部署 process_start 的 MCP timeout 原文均保留。随后只读身份核对得到实际 deployment job `1a1fdb70e12-ffbe-1fd5` 的完整成功终态，并核对固定 launcher 参数及 11 个落地文件；未观察到的其他副作用不能由此推断不存在。

原生主结果生成期间的一次不完整读取及 `source version changed` 拒绝保持原样；最终结果取自正确固定版本，未拼入旧片段。77 的 9 次 file_info 与 70 次 binary_read 均成功，两个空日志也实际读取过。每个完整 MCP 响应的原 content text/base64 都在侧包内，纳秒整数字节没有经 JavaScript Number 重写。

root 的 collector 预执行评审时间文字更正单独保存，原评审文件也保留。新评审标为 `RECONSTRUCTED_REVIEW_FROM_RETAINED_ORIGINALS`，不冒充此前已丢失的本地报告。

NoUpdate17 的失败主结果与 NoUpdate18 的失败主结果在侧包中另存原字节。完整历史包分别保留于已发布 commit `45cb05764454be5386488dc689d7dc65c182e629` 和 `5ab32bd6bb884851fd5d5dc14e5e2087d56cf063`。18 的四次 list 环境 guard 拒绝发生于目标 ELF 打开前，测试为 0/0、ordinary 未运行；19 成功不改写该事实。新 shell probe 不回填 18 的实际环境。

## 如何核对

`CONTAINERS.jsonl` 给出两个容器的完整长度、SHA256 和分片数。按照 `CHUNKS.jsonl` 的 numeric index 顺序连接对应 `.bin` 原字节，先核完整长度及 SHA256，再只读打开容器。每片最多 350,000 B。

`77-originals` 是原始 tar.gz 字节，不重新打包。`19-sidecar` 是新增 tar.xz，含完整 core、收证控制原件、部署/执行控制原件、全部恢复响应、冻结候选及原审查容器、独立复核和历史失败主结果。侧包中的所有成员均为普通数据文件、mode 0644；不会运行其中保留的旧脚本。

`MEMBERS.jsonl` 列出两个容器的每个物理成员、长度和 SHA256。侧包 `SIDECAR_MANIFEST.json` 还记录每份材料的实际本地来源及类别。原 77 展开文件不重复装入侧包；二进制传输片段及响应的派生重复副本不再重复装入，完整原响应仍保留。

侧包 `collector77_recovery_reviews/INDEPENDENT_ORIGINALS_REVIEW.json` 记录 124 清单、XML/recorders/claim、H → launch → capture → archive/core 与终态清理关系；`publication_review/PUBLICATION_CONTEXT_REVIEW.json` 记录冻结候选、部署超时与实际 job、历史失败、外部访问拒绝之间的对应关系。

本包未加入后续 cold/restart、Adopt 或下一任务候选，没有新的科学实例、额外原生重跑、权限更改或源文件修改。发布者仅创建不可变 Git blobs；实际 commit/ref 由 root 独占处理。
