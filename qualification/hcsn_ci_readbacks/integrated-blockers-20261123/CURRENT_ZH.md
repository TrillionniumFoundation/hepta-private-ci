# Hepta 研究与集成核验

## 2026-11-23 13:29 UTC #7032 精确双锁修补进入原 source CI（待终态）

- #7032 原科学 head `610f91087b598656f7f3913e600c705b95bf071f` 已用非强制 fast-forward 和原 head 租约推进至已独立资格的 `b1af67a38f8cf9cee700cc067da1e6001ce220a8`。GitHub commit compare 为 **ahead 2、behind 0**，修改文件 **只有** `codex-rs/Cargo.lock` 和 `MODULE.bazel.lock`；冻结研究输入、公开 V1、安全拒绝、原测试名单均不变。原科学 source 和原红 CI 历史保留。[精确双锁提交](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b1af67a38f8cf9cee700cc067da1e6001ce220a8) · [PR #7032 审计记录](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7032#issuecomment-7102629142)
- 相同 `b1af67a3` 在之前的原生资格 [45165787601](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165787601) 通过 cargo-deny advisories/bans/licenses/sources、locked Cargo 与 Bazel 生成锁三条原作业；该**独立候选**的依赖修复闭合，不等于联合仓库闭合。最新 push 已由 GitHub 自动启动 [原 blocking-ci 45184439037](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037) 和 [原 HCSN 科学复验 45184438921](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184438921)，首次读回为 queued；没有人为重复派作业。终局须读取原日志、JUnit、失败名录及 artifact 后方可认证。
- main 的另一依赖图 59 个 RustSec 告警不因上述变更而闭合；Windows 四项产品隔离正例、Agentd 严格原 101 及 Q24 500ms 尾延迟仍 HOLD。未合并任何受保护分支。

## 2026-11-23 12:23 UTC 双锁原安全资格更新（保留原 #7032 失败与 main HOLD）

- #7032 源 `610f9108` 的原 cargo-deny 仍 FAIL。两文件锁修复候选 `b1af67a38f8cf9cee700cc067da1e6001ce220a8` 在完全独立的原生作业 [45165787601](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165787601) 中，原 cargo-deny、正式 Cargo 重建与 locked check、Bazel 生成器与原锁核验 **3/3 全部成功**。其成功只归属精确候选，不意味着科学原 source / 全仓资格绿。[原件身份与双依赖图](cookie-7032-paired-security-20261123.md)
- main `732e934` 的两锁修补候选 `86d13925` 在原 [45165845066](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165845066) 里通过提交锁核验，但原 `cargo-deny` **FAIL**。原生逐条告警：**59 个 RUSTSEC 编号，26 个不同 crate，51 条漏洞类、8 条停止维护类**；另三项 yanked 警告。这个结果是不同依赖图，不能照搬 #7032 锁文件或压制安全门。[完整逐 ID/版本索引](default-cargo-deny-residual-20261123.md)
- Windows 四项正式隔离、Agentd 严格构建、Q24 长尾与所有联合产品门保持 HOLD；未擅自合并、未改冻结研究或重跑已完成实验。


## 当前可复核的结论

- **两细胞实验的原托管科学作业已通过。** 最终 #7032 源 `610f9108` 在 CPU Torch 2.10 冷检出，独立重算参照、全部新数值检验及原 12 项测试均通过。与 Torch 2.15 的四份输出共对照 1,011 个数值，最大绝对差 $1.49\times10^{-11}$，出现在独立有限差分。两源初态在释放前后拆分、概率与内容守恒、两条内生边界及 16 个参数的反传均按原误差线通过。[托管作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45162302799/job/137650500461) · [原 ZIP 与跨环境复核](../finite-marked-610f910/)
- **给定内部目标时，还能直接编辑放电成本。** 对一个预先指定的目标，将 A 边界下降 0.01，同时保持一个锚点上 B 的 49 个连续输出。直接调整成本和输入偏置的单线程整轮中位数 0.10950 秒；同初值联合 L-BFGS 反传 0.20087 秒、6 次优化器求值。两者均满足原 10⁻⁷ 误差线。三个额外初态下，直接编辑的输出最大仍变动 0.004372。实际检索任务需另外从收益学习目标并检验跨来源保持。[固定协议、直接反解与独立对照](../qvi-conditional-edit-20261123/README_ZH.md)

- **两个神经元的内生边界和有符号触及已接通。** A 在时刻 0.67 将最优边界和累计有符号触及传给 B 的起点。B 以自己的边界再推进 0.91。A 的释放成本增加 0.01 时，B 的终点不应期概率由 0.21714935 降至 0.21645758；A 的持续收益系数增加 0.01 时，该概率升至 0.21728455。16 个经济与物理参数的一阶导数与独立的中心差分最大相差 5.35×10⁻¹¹。此算例使用固定连接和两个点初态。[多次放电的连续空间算子](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/610f91087b598656f7f3913e600c705b95bf071f/qualification/hcsn_halfline_transport/FINITE_MARKED_ZH.md) · [双神经元原始结果与复算](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/610f91087b598656f7f3913e600c705b95bf071f/qualification/hcsn_halfline_transport/QVI_FINITE_BRIDGE_ZH.md)
- **已见到哪些查询值得补读。** 在价格 0.30 下，音频偏吉他、图库偏钢琴、音频边际不超过 0.65 的一组，TRAIN 和 DEV 每次补读视频的平均净收益分别为 +0.300 和 +0.155。整组一律补读仍有 3 个训练来源、2 个开发来源越过最差损失限额。仅用 TRAIN 冻结的 6 坐标编辑在 DEV 买 3 次，救回 2 个错误并新引入 1 个，最差来源为 −0.325。八分组上界和 18 连续特征两套编辑均已由只读 TRAIN、DEV 的第二份实现逐题复核。[独立复算](../purchase-attainability-20261123/independent/receipt.json)
- **新 12 个来源已经完成前瞻验证。** 冻结 24 套策略的 1,152 个动作后运行付费前端。上述错配组在 14 次购买中救回 7 个错误，净增 +0.20／次，但仍有 5 个来源跌破保持线。QVI 相对两种阈值均仅 +0.00278，单侧 p=0.75。全部 48 个窗口反序复跑得到完全相同的 288 个前缀后验。独立评分器复核 670 项。原 SVD 首时点策略效用 0.80625，最差来源 −0.075，仍未达到采纳标准。[新队列完整结果](../fresh-boundary-20261123/RESULTS_ZH.md)
- **读出层的编辑容量与训练迁移已分别核验。** 原 SVD 排序的 47 个阈值无一同时通过均值和最差来源。改动 9 个坐标、L1=0.96549 后，可在新 48 窗的已知结局上维持 0.10 判断裕度并使最差来源持平。首时点理想 17 买、31 停需要 L1 严格大于 1.94386。仅在 TRAIN 上重新求解的一个编辑虽在训练内过门，三个非训练面板 0/3 过门。旧训练中既有 27 个正确动作的可见矩阵精确满秩 19，要求每个连续分数不变的精确权重编辑维数为 0。[证书、开发对照与独立复算](../fresh-boundary-20261123/RESULTS_ZH.md)
- **25 文件组合源码的原三 crate 严格构建已实测。** 3b138733 相对 #7016 c12 跨四个问题净减 4 项，原命令仍以 101 退出，剩 111 项（68 参数过多、33 大枚举、10 未使用）。四项分别是私有 bootstrap、Feature 更新前驱、原记录提供器参数和既有 Artifact wire 状态。按文件、行、列、消息完整比较，另有一条原参数诊断从同一文件 227 行移到 228 行。c12 比对为 5 条旧坐标消失、1 条迁移到新坐标。两个独立原件分别证明真实 33/33 配对和 6/6 冷读撤销。组合源码另通过 11 组原源码测试 96/96。完整权限调用扫描涵盖 9,141 个 Rust 文件、826 个受保护文件、1,652 个边界，770,005 字节结果与 11e 的原回执完全相同。[组合完整源与原 strict ZIP](c12/combined-25.json) · [原始编译器输出](c12/combined-25-strict.zip) · [记录参数与守卫](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/756372f26d18ea1afe722b57c67738fbf91a0eef/qualification/hcsn_ci_readbacks/agentd-existing-arguments-20261123) · [私有枚举与 35 项原范围](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0eb846bfeaf225ed22cc0e5b642dcfae9be219b9/qualification/agentd_feature_publication/README_ZH.md)
- **Artifact Head 的两份原生二进制完成双向核验。** 在 11e16607 和 0652ab8f 各自编译的 musl ELF 上，原三个文件机制用例和九个源码检查各自全部通过。每侧枚举 256 个状态标签与空／非空载荷的 512 种组合，复核 16,384 字节上界。五种合法回复逐字相同，交换编码结果后，另一份 ELF 能读取并重编码全部五种回复。首次作业在候选的 Bazel 依赖分析阶段终止，执行的产品比较用例为零。修正后的作业复用固定工作目录，分开记录两个源码、二进制和原件。原文件测试使用仓库已有的同进程 socket 策略例外。[逐项结果](c12/combined-25-independent.json) · [离线复算程序](c12/verify_combined_25.py) · [配套原始归档](c12/combined-25-inputs.zip) · [双向原生作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45158841882/job/137638687597)
- **Q24 的 500 毫秒门有新的时间分解。** 原四片 379、393、384、396 项全过，171 项按原配置忽略。两条未撤销读取分别 319.303 与 471.152 毫秒。六次所有者调用中，登记表和存储检查耗时最多。主动撤销后的拒绝耗时 4.074 毫秒。前轮两次超时和未撤销时的连接关闭仍保留，单次通过不足以把历史故障归因。[四片原日志、CPU 和经过时间](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/253a22790d7e6756d55e16ab17d0b135224d0c12/qualification/q24_c12_clock_observation/owner_cpu/README_ZH.md)
- **Windows 的最终与中间失败已分开复核。** #7021 的四个最终红例与 c12 四个隔离用例同名。三个 elevated 各三次失败，一个 restricted-token 失败一次。此前 c12 超时的 detached-session 在这个子源码上 6/6 通过。子代理 plaintext replay 单次中间失败后同名重试通过。两个原归档共核对 46 对 log/XML。[两次全量原记录](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/55e8fbce4faf34b33a4128717efe8317464b2c2e/docs/learning/evidence/windows-detach-resume-20261123/original-7021-shard4.md)
- **#7016 的维护任务已在原源码闭合。** 第二次在原 40 分钟额度内完成，历时 36 分 45 秒，权限全集和全部后续维护步骤通过。全仓第二轮 33 成功、6 跳过、7 失败。另建的 21 文件组合在三种叠加顺序下给出相同 Git 树。[逐步回执与组合源树](c12/README_ZH.md)
- **#7021 原 46 作业已终结。** 34 成功、6 条件跳过、6 失败。真实 musl 整片、Intel macOS 全测和主仓库维护均成功，Windows 和严格构建未过。#7016 直接后继 fe38676f 读取和写入两道原固定基址格式命令均通过，两次全工作树干净，其完整原生 daemon 工作流已于 11:05 UTC 成功。普通身份 EUID 1001 通过 2,849/2,849，真实 EUID 0 通过 68/68。两个 JUnit 文件均无失败、错误或跳过。202 个原 owner 用例全部覆盖；11 个原阶段以 0 退出，格式化维护后文件变动为零，六份 59,144 文件的工作树快照完全相同。[#7021 原名册](7021-blocking.json) · [格式原门及补丁](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/ccf81fa929577ef1e0edc14a13e1262cc436db69/qualification/hcsn_ci_readbacks/daemon-fixed-base-format-20261123/format-followup/direct-c12) · [完整原生工作流](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45150994913) · [最终阶段与归档索引](c12/daemon-fe386-final.json) · [原始 ZIP 与逐题复核](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/8e0bb5ae7e7c91a6a94aabee3a162790d48c754f/qualification/hcsn_ci_readbacks/daemon-fixed-base-format-20261123/format-followup/direct-c12/official-native)
- **c12 与单文件 bootstrap 候选。** #7016 c12 的两个原 Rust 严格作业各有 115 项，与已资格源码 43e5 的诊断路径、行列和消息全部吻合。另一个单文件候选在自己的原三 crate 作业上减少 1 项到 114，新增零项。它已经过两臂的原普通／真实 UID0 测试、编码回放和完整权限调用审核。对 c12 应用该文件的预期树已独立重算；c12 原作业的计数仍是 115。[c12 双作业](c12/strict-jobs.json) · [单文件独立资格和 c12 物件对照](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cf46c20ca012fb65e49715e0a398bb5d35fcaeb1/qualification/agentd_bootstrap_wire/C12_ZH.md)
- **Windows 与 musl。** 六个原 Windows 桌面/令牌控制均通过，原单测目标 289 过、5 原忽略。第六次整 shard 的四项隔离正例仍失败，分离会话也再次超时。c12 的原 musl 构建唯一最终红例是 Q24 发布撤回前读到连接关闭；子草案 #7021 的完整同类 musl 原作业通过。两树的六份关键 Q24 源码完全相同，尚无因果归因。[Windows 原件](windows-capability/NATIVE.md) · [两次 musl 原件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e3fce928e4395868148da24c1d91e83a5765e37a/docs/learning/evidence/musl-child-completion-20261123/native-musl-comparison.md)

## 先前研究各自的冻结面板

| 问题 | 原始条件和结果 |
| --- | --- |
| 固定连续阈值能否作为可微算子 | #7015 已实现一维常系数、单吸收边界、点初态、最多一次不应期释放的算子。概率、重置后的存活质量、第二次触及、有符号跨层标记及梯度均有独立数值参照。两套 CPU Torch 环境各通过原 12 例，458 个输出逐项相同。[源码](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7015) · [两机原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/7906cc6b4a89ce1bca41d4ccf402a692390400b9/qualification/hcsn_ci_readbacks/halfline-67b04d5) |
| 什么查询值得花价钱 | 22 个新录制来源上的分区和价格均已冻结。实测梯度策略的测试效用为 0.765625，免费为 0.6875，最差来源损失 0.075 超过容许的 0.05。以往 22 个主策略均未达到采用条件。新复算表明即使知道每一题的两种答案，九个可救错误也只落在三个测试来源。全部 2³² 个首时点动作组合中满足原统计准则的有零个。训练、开发分组给出了音频头与图库分歧时的净购买收益，也重算了真实传感器上等待 0.48 秒的十二组结果。[效用与分组](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/63f88428b64033ff417a7f4af9ea985bc0d4ea92/qualification/hcsn_ci_readbacks/purchase-attainability-20261123/README.md) |
| 能否靠编辑取代 BP | 当前证据支持冻结非线性部分时直接求解条件线性读出。实际干预的来源保持门槛和双对照检验仍未达标。在同等新来源效用、检索质量和最坏保持下限下，尚无胜过 BP、传统 SNN 或 Transformer 的训练墙钟结果。[五种适配方法](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0307d62f4d4226a979692cb4420746e8c84af0d4/qualification/hcsn_flow_integration_v1/RESULTS.md) |

## 早期仓库级运行

#7013 的源 c6a3ed9c 和 prospective merge 14272605 具有相同 Git 树。原 blocking-ci 的 46 个作业包括 34 项成功、6 项按工作流条件跳过和 6 项失败。Linux GNU、musl、macOS ARM、Intel 的原 Bazel 测试，Linux、macOS、Windows 的原 Bazel Clippy，以及仓库 build-test 均成功。完整权限调用检查涵盖 9,141 个 Rust 源文件、1,652 个边界、826 个受保护文件，权限授予标志为 false。[46 个作业逐项状态](c6a-blocking.json) · [原运行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165932) · [完整权限回执](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/7c0e392f4f9348d587c366d145f94325c69fc002/docs/learning/evidence/agentd-private-migration-20261123)

六个红色作业中包括汇总门。底层失败有两个来源。

- 两个原始 Rust 严格构建在 source 和 prospective 各报 128 项。后续修复四项，在不同的两个 musl ELF 上各通过 51 个原测试，严格命令仍以 124 项诊断退出。这 124 项包含 71 个参数过多、40 个变体过大和 13 个未使用代码诊断。[四项修复及原件](strict-four/) · [双源严格作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45127907565)
- Windows shard 4 的最终 test.log 共有五个失败。其中四个原隔离正例在连续四次同源系的原生运行均失败。第五个是分离会话等候 WebSocket 事件超时，此前同名测试三次通过。另外两条在中间尝试中失败但最终通过。Windows 私有状态专项独立成功。[四次逐用例原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/8e7de7cc4b195df4bb588067ea1ea684c11b3ead/qualification/hcsn_ci_readbacks/integrated-blockers-20261123/windows-capability) · [私有状态专项](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165764)

## MemoryCell 启动的修复经过

原先缺两个测试子进程，随后一次运行又因冷编译用完 30 分钟而中止。将同源编译与正式执行分开后，原 c6a 全部 1,552 项得以运行，1,547 项通过，五项仍找不到同一个带连字符的子程序。增加 Rust 定位器原已支持的下划线环境变量后，独立托管机在同一套三个 ELF 上逐项通过全部 1,552 项。171 个原始忽略项及四个原控制组均核对通过。[未通过和通过的原 ZIP、独立复算](memory-startup/FULL.md)

#7016 已把四项 Rust 修复和便携子程序绑定放入同一源码。该 PR 的完整原 run 与上述同二进制实验分别记录。[新集成 PR](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7016) · [原启动作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787247)

## #7016 的仓库终局与后续源码

#7016 已完成原仓库级 CI。e3277e96 的 46 个作业中 33 项成功，6 项因条件跳过，7 项失败。失败项包含 Windows 汇总、learning.operator 汇总和 CI 总门。Linux GNU、macOS 两个平台、repo-checks / build-test 和 NDU v6 实际运行成功。两个 Rust 严格作业失败，Windows shard 4 和 Linux musl 作业失败。[46 项及失败步骤](e327-blocking.json) · [原终局](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787598)

- Windows 第五次原生运行的最终日志中，四个隔离正例仍失败。此前超时的分离会话这次成功，原目标 1.7 秒；另一次定位作业在三个完整原目标和三个只增上下文的完整目标上实际通过 36/36。[原生四项完整历史](windows-capability/NATIVE.md) · [会话复核](windows-detached-session/DETACHED.md)
- 两个严格作业在 e327 源和 prospective merge 各报 124 项。后续固定资格源码 43e5 将九项修复合到同一处，实测从 124 降到 115，新增零项。它在新 ELF 上通过原普通 62/62 和真实 UID0 30/30。基线普通 62/62、UID0 29/30，唯一红是取消后过早读取队列。用原条件观察十个独立 UID0 进程，五次实际返回队列仍满，五次返回原断言要求的不可用。归档保留两臂真实失败状态。[组合原 ZIP 及剩余 115 项](combined-43e5/) · [首次直接观测](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45134423798)
- Linux musl 的滚动升级夹具有一次未在原时限收到 drain ACK；原生 core 的最终失败涉及子代理通知写入父 rollout。已分开检查最终失败与各自中间重试。[原 musl 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787598/job/137546561415)

默认分支冻结点的全部 8,665 个 blob 已在第二台托管机重新从 Git 原对象散列，97,364,825 字节全部相符。[审计原报告、清单和第二次回执](../repository-inventory-732e934/)

在冻结的媒体价格和前端下，允许每题自由选择六个时点和免费或付费答案后，32 道 TEST 查询中只有 3 道值得等；它们来自 3 个来源。预知上界的平均等待增益 0.008722，低于原定 0.015，DEV 的 24 题等待增益全部为零。逐来源预知上界延伸到全部 12³² 种终止动作分配后，所能得到的相对立即免费最小单侧 p 为 1/16。首时点的两项 Holm 采用判据在这个延伸分析中仍不可能同时通过。[三个分区的效用与计算](../purchase-attainability-20261123/README.md)

e327 的仓库 build-test 原输出中另提取了 770,005 字节的权限调用回执。与 c6a 已归档回执逐字节一致，SHA-256 为 2de991230d84e60c8d440278ceb189e0f4111ce8b7c200a934ffc7a31257d6c3。实测相同的 9,141 个 Rust 文件数、1,652 个清单边界、826 个受保护文件与 authorityGranted=false。[e327 仓库原作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787598/job/137546560666)

e327 自身从冷检出重新编译的原始启动工作流也已成功。新 Agentd 二进制长 597,708,816 字节，对应 SHA-256 以 b0a412d13359 开头。不同于 c6a 的旧 ELF。新二进制在原正式套件中运行 265.528 秒，源与恢复名册 1,723 项完全相同，可执行项 1,552/1,552 逐名通过，原忽略 171 项。此前六项失败均有自己的通过行，另四个控制组分别 6/6、3/3、6/6、2/2。[两阶段冷构建和原生执行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787247) · [原始归档与逐项复核](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57263947fb62efda78071af3c85709c7af202200/qualification/hcsn_ci_readbacks/integrated-blockers-20261123/memory-startup/E327.md)

## 内生边界、重复释放与编码器的适用范围

#6739 已合并的一维再生 QVI 根据任务收益求出内生阈值。它在常系数、仿射存活收益、固定重置位置和确定不应期下支持八个物理参数的隐式梯度。三个任务、九个优化初值的阈值最大误差为 5.32e−9。仓内另有给定直线的解析首触、两段折线的独立核积分、有限格可微多次释放，以及固定连续边界的多次释放参考。它们的边界假设、是否带符号及能否反传分别列出。真实视听检索原研究有 51 个封存配置，达到全部任务采用门槛的有 0 个。[范围、原始源码及实验](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a77450f69f2da792bc65739adaefe3a438be8c05/qualification/hcsn_ci_readbacks/integrated-blockers-20261123/HCSN_SCOPE_ZH.md)

既有 CREMA-D 研究的确认集有 8 名新演员、192 个配对片段。在相同 60 秒训练 CPU 预算下，HCSN 融合准确率 30.9896%，Transformer 为 34.7005%；HCSN 相对 LIF 高 9.570 个百分点，是八项主要收益比较中唯一达到预设门槛的一项。音频检索视频的 R@1 分别为 HCSN 0.4557%、Transformer 7.8776%。这些数据将小任务的局部收益和端到端编码器的性能要求分开。[90 个配置及原始对照](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/980b8d0a1ccd672a2aa84d8c75610d67528ff70d/experiments/hcsn_blocker_closure_v1/av/RESULTS_ZH.md)

继续只用购买前的八个音频分组，TRAIN 和 DEV 的全部 256 张二值决策表产生 128 种不同动作。14 个来源都满足保持下限的只有两种，其中一种全免费，另一种只买一条训练查询。允许在每组输出任意连续购买概率后，约束同样 14 个来源的期望保持下限，DEV 相对一律购买的最大增益仍是 −487/10920（−0.04460）。这个上界有独立可验的有理数对偶证书，原逐题评分器复核两分区全部 512 次离散评分。一组查询的平均购买收益可为正，而仅凭这些购买前信息仍无法可靠部署。[精确证书、逐来源假设、原始评分复算](../purchase-attainability-20261123/README.md)

## 早期取消后的读回与草案沿革

十次真实 UID0 原进程把取消后的队列时序定位到工作线程归还信号量之前。旧程序五次实际返回 QueueFull，五次返回预期的 Unavailable。测试先保留 peer 读到 EOF 和通道槽为空的原断言，再显式等唯一的信号量许可返回，等待新增两秒上限，随后执行原精确读回断言。两套产品源码的 transport Git blob 完全相同。两枚不同原 libtest 各通过 10/10，二十次交替进程共 1.154459 秒。该数字限于这一个特权用例。[旧返回值与新测试的原生归档](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/942848ada99429f4cd1653f698b121e0f47767fb/qualification/hcsn_ci_readbacks/agentd-private-enums-20261123/queued-readback)

#7016 已按快进方式更新到 e1969bcf8dbb9e9e42cd718401a9df6d13f79d98，含九项组合及这四行测试修改，仍为未合并草案。原先整组 92 项的 91/92 对 92/92 结果保留；两个调整后源码已按先前两个 ELF 摘要核验，各通过全部 62 个普通和 30 个真实 UID0 原用例，两侧均为 92/92。[双侧终局与原始回执](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d67bdbe485c619addd6c8fe0379cb89650ec535a/qualification/hcsn_ci_readbacks/agentd-private-enums-20261123/queued-readback)。[整组配对](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138043396) · [本次包含的四行改动](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e1969bcf8dbb9e9e42cd718401a9df6d13f79d98)

Linux musl 的原失败中，fleet 收到了一个可完整解析、其类型并非 Drain 的响应；另一个响应类型未留在原日志。三次独立原目标均通过两例。原生 core 的七份失败尝试分属三个 shard，两组后续通过，最终保留的失败是父 rollout 没有收到子代理已结束通知。正常结束的事件时序与通知写入正在单独验证。[真实运行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45137315561)

HAPT 的 12 个已规定起始姿势／置信组能组成 4,096 种多等一个采样块的规则。对原 TRAIN 和 DEV 的两次独立穷举表明，共同能达到的受试者平均增益上限 0.008708，低于所需的 0.015。原记录的两种退出方式逐题复算共 8,192 个配置读数。此项仅讨论等一个 0.48 秒块。[全部配置及原数据身份](../purchase-attainability-20261123/README.md)

九项组合 43e5 的完整原权限调用检查已运行 1,505.985 秒并通过。对合法源文件范围和脚本逐项核验后，完整 770,005 字节的回执与旧 c6a、e327 两份正式托管输出均逐字相同。[完整 9,141 文件收据](combined-43e5/)

e196 的专项提交标题含跳过 CI 的标记；重开同一草案未产生仓库检查。随后保留完全相同的 Git 树 9554ddb1b5cca7502b58b7bacfc446671fe5289c，在其子提交 c12ee03f3185d5a13949faca54f066dfd634e509 启动正式资格。当前 #7016 固定在 c12，实际已收到 13 条工作流。e327 的已终结结果及各独立原始对照仍按原源码标记。[新仓库级原运行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408) · [新源码启动验证](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928118) · [新源码 daemon 原生验证](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928116)

e327 的 daemon 原生工作流也已终结。普通 2,849/2,849，Root 68/68，两份 JUnit 逐例无跳过，原名册中的 202 个学习用例覆盖完毕。后续固定基址 fmt 遇到历史证据快照缺可解析的所属工作区，退出 2，工作流最终失败。[原生两份 XML、格式化错误及独立复算](daemon-e327/)

对 musl 子通知的修复已放入 #7021 独立草案，基于当前 #7016，只改两个 core 源文件。在真实父回合结束所有者被保持的同一交错，旧源码真实丢失 0/1，候选正常结束后恰收一次 1/1。没有强制竞争时，两侧原六秒端到端用例各通过 3/3。原 GNU Clippy 通过。未确定类别的 fleet 回复属于另一条失败。[修复草案](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7021) · [原运行与受控对照](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f2d9a96fbff616596ef2c4c42addd1a0431a66c7/docs/learning/evidence/musl-child-completion-20261123)

更细的现有连续输入有一个可复验的正例。仍从原 SVD 出发，在 19 个读出坐标里改动 8 个，L1=0.9833757。用共同参与构造的 TRAIN 与 DEV 标签，分别买 11/4 题、救回 9/4 题、改错 0 题。两分区最差来源均与免费持平；DEV 相对免费／一律买增益 +0.11667／+0.04167。逐题阈值分差均大于 0.10，两批原符号检验都未通过。该编辑是现有 18 维表示能实现平均效用和保持约束的证书，尚无新来源泛化结论。[向量、搜索和原评分器复核](../purchase-attainability-20261123/README.md)

在相同原特征、价格和半径上，仅用 TRAIN 标签另外拟合一次，再封存权重后重放 DEV。六个编辑坐标、L1=0.9601562。TRAIN 两购两救、最差来源持平；DEV 三购两救一改错，效用仅高于免费 0.00417、低于一律购买 0.07083，最差来源损失 0.325。两批共同参与求解的容量正例不能作为此方法可迁移的证据。[训练封存及开发结果](../purchase-attainability-20261123/README.md)

在扩展检索前，两期 44 个既有来源已逐项排除。当时库内未用的六份视频中，两份吉他均无法在四个规定时段取得有效窗口；严格核实新来源与许可的钢琴有一份。已登记的 105 页即使包含尚待复核的线索，可提供的新吉他上传账号至多两个。这个清点未查看任何新预测。这批旧资源不足以组成 6 钢琴＋6 吉他的队列。随后扩展的来源已通过取证并完成前瞻比较，见页首的新 12 来源结果。[盲盘点](../purchase-attainability-20261123/SOURCE_INVENTORY.md)
