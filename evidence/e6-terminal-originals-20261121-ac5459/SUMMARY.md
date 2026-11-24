# E6 原件恢复与终态复核

复核类型：**RECONSTRUCTED_REVIEW_FROM_RETAINED_ORIGINALS**。冻结时间：2026-11-21T09:40:18.975841+00:00。

## 核心结论

完整 NoUpdate17 尚未闭合。本包保留失败原件，并把源码资格、组件回归、CI 工作流和科学结论分别绑定到其实际来源。

| 证据范围 | 实际结果 | 解释范围 |
| --- | --- | --- |
| 61503 source gate | b4 1014 个用例通过 | 当前源码入口检查 |
| 61503 build | 构建关口与 2 个原 publication controls 通过 | 构建与保留控制 |
| 61503 lint/diagnostics | lint 与 4 个 canonical diagnostics 通过 | lint 与诊断组件 |
| 61503 original components | 7 组，共 65 个全局唯一 canonical 用例通过 | 原生组件回归 |
| 61503 NoUpdate17 | 3 个前置用例通过；ordinary 完整父用例失败 | 完整 NoUpdate 为 false |
| 61503 daemon-native CI | ordinary 2184 + Root 46 通过；工作流 failure | 后续 fmt/保留约束失败 |
| a3acdf daemon-native CI | ordinary 2184 + Root 46 通过；该工作流 success | 该源码分支独立证据 |
| a3acdf broader CI | failure；cargo-deny job 也 failure，原因 UNKNOWN | 全仓 CI 尚未通过 |
| Adopt、cold/restart、下一任务增益 | 此范围未执行或未建立 | 科学资格 flags 全部保持 false |

Canonical 计数排除了 prior/excluded JUnit、重复 fresh-observed 镜像和嵌套父子记录。不同源码版本重复执行相同用例，也不产生新的独立任务、来源、用户或训练重复。上述回归数据不能证明 E1–E5 的泛化、教师互补、Circuit 必要性、用户增长收益、foundation model 涌现或权重编辑取代 BP。

## NoUpdate17 失败

- Source：61503a7d3bc87a5584cd2f20b8b17ea3838fdcfd。
- Tree：a2ead7f0d3a88549cd885862ad07e434b6379f81。
- H job：1a1fcf04eb0-ffbe-1e4a；恢复的当前终态仍为 failed、exit 1、complete/durable/confirmed。
- 原 driver SHA-256：c569e78ab75d14cdb19e90c016ae7abcc8c384c4b31953313ce0d222552f03e0。
- 原 protocol SHA-256：31004578dbf3f14908a9fd6ccc467da8cd6eccff671e6ded4c2e92478f539152。
- 原 canonical ordinary JUnit：complete-noupdate-17/ordinary-post-a-no-update.xml，SHA-256 eb5526005cf816966250159865e865715054f0bf191d3c5efd1efa9b8d6ec246。
- 真实错误：Permission denied (os error 13)。
- 前置标记：ORDINARY_Q24_OBJECTIVE_ACKNOWLEDGEMENT_LOST=agentd protocol error: agentd control read timed out。
- 原结果明确 complete_native_NoUpdate=false、native_owner_adoption=false、fresh_C_and_cold_fresh_D=false。

17 的失败不能替代或重写既有 completed-acceptance 内层错误。此包保留原记录，不把拒绝/机制组件通过视作完整 Root Feature ACK 或 Adopt 通过。

## ELF 与失败解释边界

67/68/69 和 70 原件保留了源码上下文、fingerprints 和后来两个当前 ELF 的完整读取结果。70 的 stdout 为 4539 B，SHA-256 724d7df4b86f8fd8d198b855245704abe19a1085903de08e520146ae36e4381f。

这些观察与 source-keeper 打开执行文件后降权遇到 EACCES 的机制一致。17 实际执行时的 ELF 身份没有被同期捕获；把其失败确定归因于某个具体 ELF 仍超出证据。不能仅从 package 数量推断唯一原因。

## 成本与资格

57 构建关口记录累计编译 1152.6433783974499 / 1800 秒；59 记录累计 lint 811.7515116920695 / 1800 秒。对应关口的剩余额度分别为 647.3566216025501 与 988.2484883079305 秒。恢复原件不会重置既有预算；这些关口记录也不等于其后全部工作成本。

source gate owner 707.0471819508821 秒，build owner 585.5540396608412 秒，lint/diagnostics owner 409.6738702063449 秒，组件 scope 78.169421012979 秒，NoUpdate17 owner 549.8559124497697 秒。父层、子命令、SSH 与 nextest 的时间区间存在嵌套，不能直接相加为独立总成本。物理能耗、完整网络流量、存储字节秒和费用仍 UNKNOWN。

## 两个 CI 来源

61503 原件来自 [run 44871891107](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44871891107)，job 136748038942，attempt 1。ZIP 含 42 个成员；完整 job log 为 4770986 B，SHA-256 3c3dfb7a35ff08627b3b81313db4264155896e297362fc06b3e86c95a5384bb8。原 driver-error.json 记录 fmt 失败；retention-error.json 记录维护修改了 Rust owner 之外的历史 evidence 路径。

a3acdf 原件来自 [run 44874077290](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44874077290)，job 136754786924，attempt 1。ZIP 含 49 个成员；完整 job log 为 4862441 B，SHA-256 7dc7cd38bbccbd5d7b40d1669043f4524e2be206fb7e829179de4d37f6ec9385。维护结束后两个 Rust 文件有已记录的修改，final 状态并非 clean。

a3acdf 的 [broader run 44874077302](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44874077302) 失败。cargo-deny job 136754917183 失败原因保持 UNKNOWN。本次只保存当前 run/jobs 元数据，没有重新获取其失败日志。a3acdf 的原生 CI 成功不能转移成 61503 或两仓系统的联合资格。

## 恢复完整性与缺口

七个原容器共 537 个常规成员；五个 tar 的 441 个原件逐项匹配保留 manifest，两个 CI ZIP 的 91 个成员逐项核 SHA-256 与 ZIP CRC。sidecar 保存新的逐成员索引和复核。

新恢复传输共保留 8 个失败响应：{"INVALID_ARGUMENT": 1, "UNAVAILABLE": 7}。原始响应位于 sidecar 的 observations/new-read-errors.jsonl，明确补取与串行策略位于 observations/new-read-retry-notes.jsonl；最终缺块为 0，全部原容器整包 SHA-256 相符。新一轮已观察的 SSH/MCP 错误不能反推旧一轮两份丢失 metadata 响应的原因，旧原因仍 UNKNOWN。

固定 readback 目录未列出 65 postmortem 原件。66 保留文件确为 0 B；其旧失败 raw 未恢复，原因 UNKNOWN。重置前的本地 review 和 transfer report 没有被补造为旧原件。

62 原输入内保留的组件 H receipt 已按内嵌哈希解出：1731 B，SHA-256 b005edd298908466b8ef9ea515df1474a3d441fbc6fd11d5324e8bda92752be3。它记录原组件身份恢复 reused=true、retried_launch=false，与本次新读取的 17 终态观察分别标识。

## 容器清单

| 容器 | 压缩字节 | 常规成员 | SHA-256 |
| --- | ---: | ---: | --- |
| 54_source_gate_originals.tar.gz | 1822849 | 30 | ca541393bea3029fc43af5a20a7f2bd721513d747d614830db8eba3a26331ca6 |
| 57_build_originals.tar.gz | 22130069 | 43 | 84d793d84a0eb000ba415dc5824cb36a3eec38018119f2d5e859cbc11f393635 |
| 59_lint_diagnostics_originals.tar.gz | 1782763 | 23 | 3ec37897935939ed3678c59b7c432475c859018f10dcc7fd1b4c51e45f7c869b |
| 61_components_originals.tar.xz | 962520 | 250 | 589d14f81383d78882a4a2d3ea63894fd256ef8132e4869c36027da871fccfec |
| 64_noupdate17_originals.tar.gz | 2156692 | 100 | 00017aa44e364c95ef048a2ce969d31e6f3753a7f52dcec5c32f2c3df0a61e69 |
| 61503-daemon-native-original.zip | 5590119 | 42 | 69db87d835e66827ef28441883d16da8446f2a3daa64adc34dc5944bd9bdfe57 |
| a3acdf-daemon-native-original.zip | 8164777 | 49 | 9ca3b86de2a92d47346f97c36634c9fc7ee0a94ed77f9dd7719a699f66280988 |
| e6-terminal-sidecar-reconstructed-20261121.tar.gz | 1999322 | 111 | afcc829777153efa904b8ea3228c6c6708c8890b4e8921b9c2f92a7c49a3fc54 |

全部发布 payload 为实际二进制分片，每片最多 350000 B。旧 #6859 的 63 个路径保持原状；没有新增 ignore/allowlist 或可执行 verifier。NoUpdate18 候选与未执行计划不进入本包。
