# M6 共同候选：工程资格与研究边界

**当前结论：同一冻结源码的选定工程验证已通过；真实学习收益仍为 HOLD，未建立生产采用。** 源码 M6 已通过原身份发布为 [draft PR #5433](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5433)，状态为 `PUBLISHED_DRAFT`。最后一次定向 CI 观测中 UI 5 项、Cell 3 项仍全部 queued，未核实 runner 实际 checkout 或浏览器执行。本文所在 Git 提交是独立证据快照，下列本地结果不替代托管 CI。

## 1. 源码、归档与运行输入

唯一共同源码 M6 为 `885dae0f3285267e9e9c49d8b43b0d009779f9e8`，tree 为 `293ece7ffdffa2332ccfdec4fbbc4b7dcb3363cb`，父提交为 M5 `953d548d25b1e050109b1b93e1ea474b2ac7c801`。H 与此前 S 系列已实际合并，包含 outbox、MDV、训练 admission、依赖、UI 与 CI 修复。完整提交链及两个前置提交的 bundle 身份见 [根侧原件包](raw/root/root-cloud-records-033.tar.gz)中的 SOURCE_M6_EXPORT_SUMMARY.json。

| 身份 | 本文采用的证据 |
|---|---|
| 候选源码 | M6 commit/tree；各执行线分别核对实际输入，未借用旧候选通过项 |
| 实际受测源码 | root 原生与 UI checkout 为 M6；Python 为逐项绑定 M6 的 93 文件子集；MDV 驱动为 M6，任务源码另列 |
| 完整归档源码 | source.tar，210,595,840 bytes；13,681 项＝13,680 普通文件＋1 symlink，核对字节、Git mode 与链接目标 |
| 运行配置 | 各线独立 runtime/profile、资源、缓存和工具版本；同一源码不等于同一运行环境 |
| 发布 head | PR #5433 的 head 已读回为 M6，固定 base 为 H `81da60b349e32d89d0e4c4674a517a66af7e5eee`；draft，尚未合并 |
| 证据 child | 本文件所在 Git 提交；唯一父提交为 M6，范围仅 observations 与精确 blob allowlist 追加；具体 commit/tree 由外部 finalization／发布回执绑定，避免自引用 |

完整源码 tar SHA256 为 `dfc9484fc2dab61b37801e8197774a67365fb185fedc620a9b970e2f0e9d284e`，依据 [完整源码指针](SOURCE_ARCHIVE_POINTER.json)。tar 独立保留，UI 包含完整校验 inventory；归档完整性不等于执行或生产资格。

根侧冻结 RPC 终态仍未知；独立 Git 读回确认 M6 与 clean，不能反写原请求为成功。此前 Mac 只读 fetch-H 超时、前置检查错误和 TCP GET 超时均保留；006 恢复已完成 source push、draft PR 创建及精确读回。原冻结请求的 UNKNOWN 不因后来发布成功而改写。[发布原始回执](raw/root/SOURCE_PUBLICATION.json)与[完整发布过程](raw/root/mac-source-publication-evidence-035.tar.gz)分别保留最终状态和失败／恢复记录。

## 2. 同 M6 的实际工程分母

| 验证范围 | 本次通过 | 未执行或范围限制 |
|---|---:|---|
| root 选定原生测试 | 567 | 各运行的 skipped/filter 见下表，不是全仓分母 |
| 原生 UI，Rust 1.96 | 33 | 0 skip、0 重试；与 MDV 历史 S 的 33 项分开 |
| Python 七组 | 91 | 0 skip，七进程 exit 0；含 fixture／控制回归 |
| JavaScript 控制 | 16 | 0 skip |
| Firefox 默认／fixtures | 2／3 | 0 skip、0 unexpected、0 flaky；Chromium/WebKit 未在本地执行 |

root 的 567 个选中执行分别为：infer-core 41（runner skipped 1），独立历史资格测量 1（其余 41 filtered），neuron perception 4（skipped 197），automation 163（skipped 2），agentd lifecycle 68（skipped 713），Matrix shared graph 289（skipped 2），真实旧 SDK 0.18 加密存储副本至新 0.19 consumer 1（skipped 2）。skipped/filter 按各次原日志报告，不相加成独立分母；历史测量独立执行，不改写默认忽略语义。自动测试重试为 0。fmt、限定范围 fix/严格 Clippy 同样 exit 0。[原生与依赖原件](raw/root/root-native-evidence.tar.gz)

M6 的 locked all-features **metadata**、Bazel lock error-mode、现有配置 cargo-deny 都真实 exit 0；metadata 不等于 all-features 全测试。cargo-deny 0.19.0 使用前后不变的 RustSec DB `7a40350e1b8ba5b656d909f88222a8059a83d88d`（tree `e206c84b629992c9f861e5336baed4136eda4216`）。既有忽略配置未改，没有新增 advisory 例外。旧 R/S 的 0451 失败保留为历史，不计作 M6 当前失败。

UI 七阶段都绑定 M6。Firefox 默认截图 20/20、检查 46/46；fixtures 截图 26/26、检查 146/146。**原完整三引擎检查器 `full_verifier_passed=false` 原样保留**；这里只承认 Firefox 子集，完整托管 UI CI 必须另看发布后回执。Rust 1.95 严格 UI Clippy 单独 exit 0，不混同原生 UI 的 Rust 1.96 测试环境。[UI 原件包](raw/ui/M6_UI_COMPLETE_EVIDENCE.tar.gz)中的 FINAL_VALIDATION.json

Python 91＝joint-config 23＋state-codec 6＋supervisor 8＋training-result 14＋source-archive 13＋PRED 诊断 14＋MDV 控制 13。93 文件子集前后相同；Python 3.12.14、Torch 2.9.1+cpu、NumPy 1.26.4、Pillow 12.0.0 真实可用。venv 17,139 文件／链接目标前后同指纹，不等于完整系统镜像。PRED 部分只有既有诊断单测，没有新确认训练。[Python 原件包](raw/python/M6_PYTHON_REGRESSION_EVIDENCE.tar.gz)

原生／UI／MDV 复用已完成旧运行的独占编译缓存，Python 复用已固定 venv 与字节码缓存，均不称冷启动。UI Makepad checkout 的完整 tracked 物理字节前后相同，Git 状态仅既有 `.cargo-ok`；29 件非 Rust 换行物化明确保留。字体期间只有两件受控 untracked，按 SHA 清理后 clean。WASM 使用受检 overlay，原生不应用该 overlay；Node 按 package-lock 安装，但未完整盘点所有 node_modules 物理字节。

## 3. 普通入口与固定 Cell 图：已经做到哪里

普通 ObjectiveStart Circuit 完成可形成持久学习投递意图；恢复、绑定核验和 coordinator adapter 已有实现及工程测试。outbox 不授予训练或采用权。具体 daemon main 的 provider、经验／训练／独立评价／采用与不同后继任务 NextUse 的 owner 后端及常驻 consumer 仍未装配；既有 owner 接口所需的注册信任根、签名与权限配置尚未装配，故没有生产闭环证明。

无 backend 在 claim 前保持 pending／Unavailable；claim 已提交、submit 前崩溃后只读 readback，无后端记录时保持 CommitUncertain，不自动释放、重发或 ACK。ACK 要求精确 request/owners 绑定及原 coordinator 完整终局（包含独立 NextUse）；正式 NoUpdate 也不能绕过这些门槛。[持久 outbox 原件](raw/root/lifecycle-outbox-native-evidence-007.tar.gz)

M6 的 MDV 驱动实际完成固定“记忆—决策—确定性验证”开发链：两个已曝光任务、一个 R/S 故障家族、一次已验证私有状态更新，第二个新进程真实读入该状态与原回执。Task1 在旧 R 重现 Clippy 红灯并使用已知 S 修复；Task2 的 33 项 UI 测试实际跑在旧 S。它们验证 M6 驱动行为，不能再加到 M6 UI 的 33 项分母。[MDV 完整原件](raw/mdv/M6-complete-evidence.tar.gz)

更新后的关联值为 0.07142857142857144，但排序和最终选中文档均未变；强 BM25 排序已记录，完整基线终局分支未执行（baseline_terminal_arms_executed=false）。这是有界词法状态开发工具，尚无真实语义记忆优势、完整同预算对照或独立任务收益。确认任务数为 0；状态为 HOLD／production_not_adopted，私有 marker 为 not_requested，正式 adoption receipt 为 null。直接研究 CLI 不等于普通 ObjectiveStart 的生产采用链。

## 4. 研究结论与下一轮冻结条件

原 PRED HOLD 与此前已完成的 16 个 fresh seed／114 fit 独立模拟确认 HOLD 均保留；原确认与新确认一律不用于后续调参、排除 seed 或重复确认。指标是模拟净效用差，不是成功率百分点。本轮没有新增确认样本，也没有重跑其训练。

[五项下一实验完整审阅稿（新整理副本）](raw/mdv/NEXT_EXPERIMENTS_M6_REVIEW_COPY.zh-CN.md)及[机器登记](raw/mdv/NEXT_EXPERIMENTS_M6_REVIEW_COPY.json)均为 **DRAFT_FOR_REVIEW，confirmation_admitted=false**。原 NEXT_EXPERIMENTS_M6 两文件目前无法恢复原字节；旧 SHA 仅保留为来源记录。**新整理稿，不是原字节恢复。** 新稿根据 M6 已提交完整设计、原 HCSN 规格和已读开发证据重新整理，范围见[恢复记录](raw/mdv/NEXT_EXPERIMENTS_M6_REVIEW_COPY_RECOVERY.json)。

| 方向 | 拟解决的问题与冻结前缺口 |
|---|---|
| MEM-1 | 保留 exact/BM25 优势，比较真实跨文档语义、时效／失效状态；缺独立任务保管、标签、合法共用 encoder pins 与预算 |
| PRED-1 | seed 202 仅用 train/dev 诊断；两次确认已使用，禁止再调或重跑；新确认尚未获准 |
| VERIFY-1 | 分开检查器正确性、评分校准、同预算策略终局收益；缺自然快照、独立标签与真实预算冻结 |
| NDU | 在真实修复／继续／验证／停止权衡中计入失败和恢复；缺自然多样任务、动作接口与独立任务保管 |
| HCSN | 先做具体因果时序任务及强模型对照；历史 protocol 原字节已核，仍缺正式 trainer、容量／算力与数据暴露冻结 |

HCSN 引用既有 Git 规格，不把不可执行接口当完成训练；原件 commit、SHA 与历史来源在草案附录。确认前须冻结任务选择、训练/dev/holdout 隔离、独立 custody、同预算强对照及完整成本口径。稳定一阶改善尚未建立，Cell 分裂合并、层级与改进器继承不进入本轮收益结论。

## 5. 成本、失败与未知值

| 本次观测窗口 | wall 秒 | 包含关系 |
|---|---:|---|
| root 原生 | 374.610666 | 包含其所有选定命令窗口 |
| root 依赖 | 6.221059 | 与原生顺序分开 |
| UI worker | 251.981393 | 包含七阶段及其所有子命令 |
| Python suite | 21.420149 | 包含七组；reaped child CPU 16.543231 秒 |
| MDV worker | 10.000318 | 包含 guard/setup/campaign/原始归档；self CPU 0.156327、child CPU 11.020041 秒 |
| MDV 最终完整封包 | 0.012271 | worker 后独立窗口 |

root 导出 0.269152 秒、封包 4.080701 秒；UI 封包 2.612796 秒另列。Python 准备 2.353572 秒（已含导入）、原生绑定 0.164969 秒、指纹前置／后置 7.951749／2.781150 秒、freeze 0.016104 秒；首次封包失败 0.062897 秒，修正封包范围后的完整封包 0.748581 秒，没有重跑测试。各原件保留精确值和嵌套明细。

各线可能并行，上表不相加成总等待时间；内层工具／训练／验证窗口不重复计费。MDV 已知 worker＋最终封包为 10.012589 秒，不包含此前准备／恢复与传输。child CPU 可因多核大于 wall。

只读 fetch-H 失败观测 300.006815 秒单独保留。原冻结 RPC、rog 安装 011、旧 34041 UI 构建等未决费用保持 UNKNOWN/null；root inventory 中缺失的 004/005/011 目录不反推为未执行。旧 a51/M3/M4/M5 失败、恢复与原包均保留，不能合并为 M6 通过项或用预热加速宣称学习收益。模型、控制面等待、缓存准备、峰值内存、能耗及收费未完整计量，**完整端到端费用尚未建立**。

## 6. 原件与后续发布

[QUALIFICATION.json](QUALIFICATION.json) 保存机器范围、分母、费用、归档 pins 和未决项；[ARTIFACT_MAP.json](ARTIFACT_MAP.json) 给出上述相对路径应映射的原件。四线原件分别保留，旧源码通过项不转移到 M6。本文件所在证据提交使用 `SELF_DESCRIBING_GIT_SNAPSHOT`：其唯一父提交为 M6，变更范围已核为 observations 与精确 blob allowlist 追加，具体 commit/tree 在外部 finalization 与证据发布回执中绑定。

源码发布的精确 head、tree、base、draft 身份及写入／读回终态见[发布回执](raw/root/SOURCE_PUBLICATION.json)。[初始托管 CI 原件](raw/ui/M6_HOSTED_CI_INITIAL_METADATA.tar.gz)记录 15 个已触发 workflow；[最后定向快照](raw/ui/M6_HOSTED_CI_PRE_FREEZE_TARGETED.tar.gz)与[回读摘要](raw/ui/FINAL_CI_READBACK_RECEIPT.json)记录截至 **2026-11-09 05:24:18.389009 UTC**，UI run `42565769665` 的 5 项、Cell run `42565757710` 的 3 项仍全部 queued，attempt 1。状态为 `QUEUED_NOT_EXECUTED_AT_OBSERVATION`；workflow 的 head SHA 不能证明 job 实际 checkout，尚无这些任务的终态日志或浏览器执行证据，不声称托管 CI 全绿。

[历史定向 CI 包](raw/ui/targeted-ci-safe-native-evidence.tar.gz)保留 S/H 已观察失败，[范围说明](raw/ui/HISTORICAL_TARGETED_CI_SCOPE.md)明确两份 deny 日志传输不完整；它们不计作 M6 当前结果。旧 SDK 迁移使用的[原始虚构测试 fixture](raw/root/old-sdk018-fixture-v3-original.tar.gz)独立保留，未复制升级后的数据。

发布 006 外层观测为 82.365281 秒；两次 CI GET 窗口分别为 34.731569 秒与 10.466975 秒，属于发布／观察费用，不是项目执行费用；失败尝试和其他准备费用仍按各原件独立列示，不相加为完整端到端总价。
