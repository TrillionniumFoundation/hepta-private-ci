# E1–E6 联合推进：实际执行与当前边界

观察时间：2026-11-20T03:30:10.772104-05:00 America/New_York。本页与 [CURRENT_PROGRESS.json](CURRENT_PROGRESS.json) 同步。上一个联合证据提交为 `238fc48402f786db3d7f2a80b0abad6c0e5322bb`；旧 CURRENT 的逐字原件另存于 [checkpoint-20261120/](checkpoint-20261120/)。原实验身份、预算、历史失败和 NoUpdate 继续保留。

**本轮已把 #6709 修复接入联合候选，完成原 56 次学生评估，并把公共项目材料补到 16 个。新未来任务仍没有学习收益，完整 E6 采用与 Chain 原业务活性尚未闭合。十项联合资格全部保持 false。**

## 当前实证

| 原工作 | 实际完成 | 当前判断 |
| --- | --- | --- |
| #6709 整合 | 两个原 blob 精准接入；原 114 项／18 模块控制全过，旧逻辑负控复现失败；实际 `just fmt` 与 `--check` 全过、diff 为 0 | 状态标签不再足以累计完成数；这项工程修复不授予 native 采用资格 |
| E1／E2 学习 | 两组原 32-update 权重完成全部原 56 次新生成；47 次 native，9 次准入拒绝 | 两学生 A 各 1/4；新未来面板 P、document、native 均 0/4，ResearchNoUpdate |
| E3 多教师 | 保留原 T2 的真实调用与负结果；不同家族 SmolLM2 的有界恢复已终止，唯一保留权重为 901,316,608／3,422,777,952 字节，完整 SHA 未通过 | 本轮没有新增模型调用、互补收益或共同学生证据 |
| E4 通信 | 保留原 PP／CC／PC／CP 各 5/6、强对照与消融，本轮没有新增模型调用 | Circuit 必要性仍未证明 |
| E5 来源 | 原 4 个项目之外新增 12 个，经 28 次真实修复前后 native 验证，合计 16 个去重公共项目材料 | 真实用户为 0，增长训练更新为 0；两种增长曲线仍为空 |
| E6 原 owner | 实际源码 `640bac3c` 的 native11、retirement16、delivery5 全过；原完整 NoUpdate6 仍在 C 回读时报 `Invalid(Unavailable)`，新证据已发布到 `02d5b32d` | 原完整 NoUpdate、Adopt、新 C、冷新 D、FinalUse 和结算按各自原门计数 |
| Chain | W1 延迟修复通过 6／3／4 项 native 控制和原 130-attempt mixed 测试；旧生产负控确实失败 | 全 repository 检查仍失败；原 F0 与完整成本没有被局部通过替代 |

## #6709 已落到明确联合候选

整合源为 `0bdf65445f9bbefba2c45dc3e611dd36386a1456`，原修复来自 `773f25e53504790c74364aa3b1606ed51853df32`。production 和 test 的 Git blob 分别为 `04c556c5831ba2a01341404f15882020a68ff956`、`3bd61299f923e1f3ce2f80d92780991dfab4434e`。

原生产配新回归测试得到 7 项测试中的 1 个预期失败，直接复现缺少 C 使用仍可计完成的问题。整合后的原 114 项控制全部通过，0 failure／error／skip；首次缺少原 fixture 的设置失败也完整保留。终态实验必须绑定经过验证的 C 使用和一致的冷进程回放，计数输出仍明确区分实验采用与 native 采用。

在精确 `e4b4eb50` 隔离 worktree 上实际执行原 `just fmt --base 325218ec...` 和 `--check`，退出均为 0，diff 为 0。锁定 Ruff 0.15.13，没有修改两份整合源码。缺 uv、下载超时和 offline cache 失败等 38 份原件均在 [整合验证说明](../cell-e6-metrics-integration-20261119/FINAL_VALIDATION.md) 中绑定，未用最终通过覆盖旧失败。

此前 e4 的工程 CI 原件继续保留。`238fc484` 对应的工程 CI 又实际执行了 216 项，44.500 秒通过，受测身份为 prospective merge `79210ce76fba767e5860b492ff35501140edc5db`，其 base parent 是 `061334747ce9d87690c40df48eeedf239156b57d`。这不等于每个新候选都执行了 native E6。238 的原字节门也真实通过，精确覆盖 e4→238 的 27 个增量文件，512,000 字节门槛不变；它不是联合 PR 的全差异验证。

238 的工程与 v8 检查通过，但不能称为全 CI 通过。architecture 的精确 head 检查通过，base 与 required job 失败；blocking 中原 contract、cargo-deny 及部分 Windows／Mac 检查失败。cargo-deny 日志读取三次出现 Transport closed，原因仍未知。contract 指出的四项历史外仓 workflow 引用继续保留，没有改检查器或豁免它们。

对 base 身份作了额外原 API 对照：PR 元数据报告 `2742bc37`，实际同名 base branch ref 为其直接后继 `06133474`，prospective merge 的两个 parent 是 `06133474` 与 `238fc484`。因此实际构建基于已经推进一步的分支；PR 元数据为何未同步仍未知。没有换 base branch、改分支或声称平台缓存故障。[完整 API 原件与对照](../cell-e6-metrics-integration-20261119/ci-base-reconciliation/)。

Mac 的两个具体 fixture 修改使用真实 canonical 临时目录，并让 reopen 的 fleet 路径与原 create_run 一致；产品拒绝检查和原断言不改。原 formatter 已通过，项目 native 尚未通过。前两次设置／缺依赖失败、第三次人工中断及其观测限制都保留。

第四次实际项目命令最终因 crossterm 依赖下载失败退出 101，命令 3,085.996 秒、外层 owner 3,087.346 秒，0 个 Rust 测试；它曾被工具标为 lost/target_reboot，但独立 OS 观察证实原 owner 当时仍活着，之后才真实终止。期间没有启动第二 Cargo，也没有按 PID 杀进程。不能把这段记录写成已经证明机器重启、死锁或零网络进展。

随后用独立目录取得锁定的 crossterm `45fecb95` 单提交浅对象，严格 fsck 通过，实际 22.897 秒；完整 54 成员归档已独立逐字回读。目标 cache 的本机 seed 成功，未改锁文件、配置或旧 partial pack。独立第五次原 `just test --locked --offline` 在 0.290 秒后因另一未缓存的精确 tokio-tungstenite revision 退出 101，仍是 0 个 native case。两次 seed 的真实 RESULT、第五次的完整 RESULT 和原错误日志均已独立读取并核对 SHA；它们继续表明 fixture 未通过 native 验证。[新增终态原件](../cell-e6-metrics-integration-20261119/mac-native5-readback/)。下一步先检查全部锁定 Git 依赖的材料缺口。[原始尝试与 fixture 说明](../cell-e6-metrics-integration-20261119/mac-fixtures-20261120/) · [精确依赖原件](../cell-e6-metrics-integration-20261119/mac-crossterm-shallow/)。


## E1／E2：真实学生能执行，但未来任务收益仍为零

原 [#6737](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6737) 的两组各 32 次更新权重保持不变。本轮完整结果在 [#6778](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6778)，证据提交 `ef096991a2632d04758d5a577ea9fbdf54209d31`；权重先于未来面板冻结，原 A 及 future 的两次调用全部执行，没有因首答成功而省掉第二次。

| 面板 | P | document 学生 | native-feedback 学生 |
| --- | ---: | ---: | ---: |
| A 最终成功 | 原记录 0/4 | 1/4 | 1/4 |
| A 共同 P 前缀 | 原真实前缀复用 | 1/4 | 1/4 |
| 新未来任务最终成功 | 0/4 | 0/4 | 0/4 |
| 新未来任务失败后恢复 | 0/4 | 0/4 | 0/4 |

两学生在 A 上都只成功完成 humanize。native 组没有超过同信息 document 组，在新未来面板上也没有超过 P，原严格晋级条件失败。没有成功的 P 未来任务可供检验保留，因此不能把“没有观察到退化”解释为旧能力得到保护。原 E1 完整 retrieval 成本对照仍未闭合。

原 56 次新增生成共使用 106,563 个输入 token、15,172 个输出 token。47 次真实 native 中有 5,485 个重复 XML case 实例，304 个失败，0 error／skip；这些实例不是 5,485 个独立任务。两个顺序 owner 窗口合计约 1,499.89 秒，不能与其嵌套 CPU 或能耗读数重复相加。

随后仅用 A 材料做静态诊断，没有再生成、再训练或再跑 native。[#6780](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6780) 的权重读回确认每组 112/112 个 FP32 LoRA tensor 都发生改变，保存字节和实际加载摘要一致，12 份 A 输出各绑定正确的学生适配器。没有发现 loss mask、target 截断、codec 或未加载训练权重的具体实现错误。未来输出没有回流为训练或调参输入，ResearchNoUpdate 保持。

## E3／E4：保留已有教师和消融的真实边界

原 E3 已有不同 checkpoint／架构的 T2 执行证据；不能用 desktop SFT 目录只发现一个 Qwen2.5 基座，推断全系统没有第二教师。原六题结果为 T1 0/6、T2 1/6、union 1/6；原十二次 T2 调用已用完，协议明确不在这些输出上训练。另一个四题维护采集的八次 T2 调用，最终 1/4、恢复 0/3，也继续保留。

新 [#6781](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6781) 已发布恢复终态，证据提交 `6cce823fcef62f3e65856d3a4ff2b428d3bd8c38`。SmolLM2-1.7B-Instruct 的 revision、模型卡和许可来源保持冻结。原 895 秒下载失败、只留 255,852,544 字节的原件不改；这次独立恢复在 895.187325511 秒后按原窗口终止，owner exit 1，四个 worker 都已进入确定终态。

95 个冻结且不重叠的范围中，实际尝试 22 个，18 个完整、4 个部分，没有范围重试或第三下载 owner。新增实际写入 645,464,064 字节，连同只读旧 prefix，唯一保留位置为 901,316,608／3,422,777,952 字节，仍缺 2,521,461,344 字节。稀疏文件显示完整逻辑大小，不能表示模型材料齐全。完整 LFS SHA 尚未验证，教师仍不 ready，新增模型加载、forward、生成、训练和 native 均为 0。

所有实际区段已单独逐字读回并通过，3.777683761 秒读回成本单列。90 份完整原件的归档也逐成员核验，原失败没有被成功区段覆盖。保守累计 HTTP body 上界为 998,538,253 字节，低于原 4 GiB；物理网络、能耗和完整系统成本仍未知。证据发布的 69 个新路径已在准确 ref 上逐字读取并检查大小，未声称在该 head 运行了原 blob CLI。已知 T2 权重的轻量 stat 与历史身份一致，MTP 文件没有获得独立基座及许可证明，均未重新运行模型。

协议复核还明确了两个后续接口问题：原 T2 HTTP runner 未执行声明的 4096 输入 token 准入，尽管实际旧记录最大只有 796、没有发现历史超限；desktop 当前基座准入硬绑定 Qwen2，不能直接把 Smol 的 Llama 配置换入。需要各自明确的 tokenizer、template、模型身份和新实验冻结，不能放松原身份检查。

E4 的原 PP／CC／PC／CP 各 5/6 没有超过强单模型。oracle 的 6/6 只表明理想组合覆盖范围；实际去答案是 4/6、去反馈是 5/6、retrieval 是 0/6，不能转成已实现的路由收益。本轮没有新增通信实验，也没有授予 Circuit 必要性或组织涌现资格。

## E5：16 个材料来源已经闭合，真实增长训练仍要通过输入准入

首批新增十项目的完整证据在 [#6777](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6777)，当前证据提交 `78eb0dfdb28563f2527aa1cfc27f9b40997f70ea`。四次顺序尝试共 24 个真实 native children；完整原件包含 10,408 个文件、113,148,963 字节，逐件路径、类型、mode、大小、SHA256 均核验。原下载失败、PyPI 元数据截断、缺少 simplejson／原 example fixture，以及 collector 临时目录前缀误计，都保留原结果。

修复后的身份读回只移除 pytest 引入的精确临时目录前缀，完整 module、class、function、parameter、顺序和数量仍一致。永久 collector 修复复核了原 24 个 children 和 30 个改变参数／外来路径／缺 case 的负控，没有新增 native。loguru 的原 skip 仍显示为 skip。

独立 [#6782](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6782) 又对 multimethod 和 natsort 执行四个原生 children，修复前各失败一次、修复后各通过一次。原四项目加十项目再加两项目，形成 16 个不同公共项目材料。项目、修复 PR、原 before／after 和完整测试身份都在 JSON 中列明。它们不是 16 名已认证用户，也不是每项目 32 条独立 agent 轨迹。

原 1／4／16／64 来源点、固定总预算与固定每来源预算、每来源 32 单位均保留。按照原大小写敏感 `source_id` 字典序，新 1-source prefix 是 loguru，4-source prefix 是 loguru、natsort、rich、multimethod；旧四项目权重不能冒充这些新 prefix 的训练结果。

独立 [#6783](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6783) 已发布 `63f494553a735bd55a3fef7cfe2e76604cd6db7d`：源 prefix 在适配构造前冻结，实际通过 16/16 材料正控、拒绝 22/22 篡改负控，并精确重建 17 个 runtime 文件。完整解包回读核验 1,645 个成员，包含 1,628 个字节对象。原每侧 290 个测试身份的结果为 before 35 个失败、after 289 passed／1 skip；这是旧 native 原件的回读，没有新增 native。

这个检查验证冻结可信原件内部的完整性，不能独立证明来源不可伪造或训练有用。新材料接口完整保留补丁、上下文、fixture、参数及许可；旧四题 SFT 程序和其摘要没有改写。

后续五个可独立审阅的 Draft 为 [#6786](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6786)、[#6787](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6787)、[#6788](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6788)、[#6789](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6789)、[#6790](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6790)。最终证据 head 为 `148e37c26586677e83f0e57e100def8805c1a020`。11 个 Python 模块实现有界的 source 输入、动作表达、回放边界及 token 测量；输入先于 target 冻结，16 项 after-poison 控制未改变输入选择。

实际结果：16/16 完整结构往返，17 个 runtime 文件逐字一致；11/16 的动作在受限解释器中可执行，只有 2/16 通过有限静态闭包检查。原 Qwen tokenizer 的 CPU-only 测量显示 15/16 输入超过 4096 token，15/16 完整序列超过 3584，5/16 target 超过 384，6/16 prompt 字节超过 65,536。只有原第 12 个 attrs 材料同时落入这些界限；它不在通过的固定 prefix 内，也还没有 optimizer 单位、完整预算和未来验收绑定。

因此原 1／4／16 prefix 均不获训练准入，没有调换来源、截断后再声称完整输入，或用 after 内容选择训练输入。原材料中的测试及 fixture 可能本来来自修复后的测试，故不声称所有上游材料都没有 after 字节。该控制验证的是这版输入选择的边界。

本轮模型权重加载、forward、生成、训练及新增 native replay 都为 0。token 测量 owner 为 8.432 秒，其 child 7.460 秒和 CPU 11.568 秒是不同且重叠的口径。最终 `63f49455→148e37c2` 的 58 个变化路径实际通过原 blob gate，512,000 字节及 allowlist 不变；该门不是训练收益验证。[最终原 gate 回读](../cell-e6-metrics-integration-20261119/e5-codec-final-readback/)。

原增长协议的 token、MAC、验证预算和 optimizer 单位映射必须单独冻结；新的未曝光 B/C 仍按原准入要求处理。原预算单位是对一个真实修复材料的一次计划更新。固定总 32 单位在 n=64 最多曝光 32 个来源，不能通过更改 batch 定义、追加更新或复用项目写成 64 个都参与训练。16 来源可用性与原 prefix 的实际训练准入分别记录，不因个别来源可执行而重选顺序。两种增长曲线仍为 null；64 来源还缺 48 个；本轮增长训练更新和已认证用户均为 0。

首批完整材料候选 `b6822f9a` 的原字节门实际覆盖 104 个变更文件并通过；加入回读证据后的最终 `78eb0dfd` 也实际通过相同原门，共覆盖 139 个变更文件，512,000 字节门槛和原 allowlist 均未改。最终外部验证原件另存于 [E5 最终发布回读](../cell-e6-metrics-integration-20261119/e5-final-publication-readback/)。

## E6：实际 drain 与原 owner 链路

[独立 #6776](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6776) 的此前已发布证据为 `ab5e792d1bceb583c246f44d01ee8e433d5c60e8`。实际执行源码为 `e4aeaa2cdd1a4aa884d09cafaeef96968feb7a90`，原 native 11/11 与 retirement／fault 16/16 全过。原完整 NoUpdate 仍失败：`historical_client.read_limit request_id=65 maximum=64`。该测试 case 约 69.972 秒，命令 70.808666 秒，外层 owner 121.382146 秒；这些是嵌套区间，不能相加。实际 A journal／witness 已由原 header-only 40／112 字节变为 93／224 字节；C journal 仍为 0 字节、witness 为 112 字节，因此不计新 C 成功。

原件 201 文件／55,918,596 字节封存在 [drain/read65 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/ab5e792d1bceb583c246f44d01ee8e433d5c60e8/evidence/e6-original-drain-read65-20261120-2e9b)。物理密钥仅记录 metadata，正文留在原 host。首个 b5 源的宏歧义编译失败、e4 两项显式 import 修正、compiler 退出 0 但 recorder 元数据假设失败的原记录均保留。完整 275 项 source／893 protected／1,138 caller 检查属于 `b5da8e70`，未改称在 e4 重跑；e4 的具体 native 和当前 protected／blob 门单独绑定。

新的 [已发布证据 `02d5b32d`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/02d5b32dd81c4fc820d8468c617908c8f2907a50/evidence/e6-c-identity-noupdate6-20261120) 同时保留 `2b8125e3` 与 `640bac3c` 两次原尝试。前者真实完成 415 项 source／47 模块、907 protected、320 targeted、1,159 full caller 检查，并通过 native11、retirement16 和 delivery5；原 NoUpdate5 随后在“signed ordinary request differs from the published Feature task”处失败，实际读到 request55，没有完成 C。此前 request65 的失败记录仍保留，64 上限没有提高；request65 是本地拒绝，不是第 65 次成功读取。

`640bac3c` 只修正 C fixture 的真实身份来源：runtime 来自解码 configuration，model tuple 来自其 semantic digest，artifact set 来自 bundle digest。原 issuer、签名、产品 guard、完整父流程及所有期限均不变。该精确源码重新通过完整 415／907／320／1,159 source 门、原 `just fix --locked --offline -p codex-hepta-agentd` 与 native11＋16＋5；源码前后字节一致。

完整原 NoUpdate6 的真实首错变为 `Invalid("Unavailable")`，仍是 1 case／1 fail。case 75.141 秒、项目命令 75.947 秒、owner 127.650 秒，不能叠加。C source journal／witness 已有 6,456／672 字节，Cell journal／witness 已有 654／224 字节，generation 仍为 40／112；这些写入不等于 C 完成。原件 229 文件、67,362,373 字节归档为 1,025,424 字节，密钥及可能包含密钥的 debug business image 正文未导出。

静态调用链显示，两秒 ACK 丢失后的 observer 在查看 Source publication 前会检查 CURRENT；该私有 Root 通道对并发 try_lock 失败会永久 fence。这是一条具体可修复的失效路径，但现有旧日志不能证明本次历史失败一定由它造成，也尚不能排除 transport、Artifact、FinalUse 或时钟路径。下一候选只前置同一 Source publication 观察：Missing／Pending 在原 deadline 内等待，Completed 后继续原 CURRENT、capture 和 expected admission 检查；没有把 Unavailable 改为继续等待。

真实 Root lane 机制控制、Feature ACK 组件控制和完整原父流程将分别报告，不冒称已经构造同一个完整 Root＋Feature ACK 正控。实际 Root observe_after 故障注入尚未完成。新发布 head 的原 7 项 blob 单测及原全 98 路径字节门通过，全部 15,750 个既有文件未变；这些仍不授予原父流程资格。[联合回读绑定](../cell-e6-metrics-integration-20261119/e6-640-publication-readback/)。

此前 `27d90883` 的首因修复让真正的 `GenerationFenced("original C predecessor or new witness history differs")` 显露出来，而不是被后续 delivery 错误遮盖。原 native11 通过，但完整 NoUpdate 仍失败。检查发现原 generation journal／witness 只有初始头部，既有 `drain_completed_task` 没有产品调用。

新的产品路径在原签名 Outcome 被接受、source 检查完成、原状态真实 Complete 且任务仍为 Active 时才执行 drain；随后核对完成时的 publication 和前后状态。Retained 和只读观察路径不触发写操作。实际故障控制包含 journal fsync 后 witness 写入失败、重开修复和重复 drain 不重复追加；没有合成一个“已 drain”状态绕过旧前驱检查。

原 64 次读取上限、500ms 及 240／300／600 秒条件保持。NoUpdate 使用的初始 Artifact head 真实有效期为 600 秒，静态上能覆盖原 480 秒完整冷父及旧 writer 的 300 秒真实退休等待。Adopt 新 head 则受原 240 秒学习 envelope 限制，因此它与 300 秒等待存在单独的有效期缺口。新的 D writer／selector 签名不能让旧过期 head 重新有效。

冷恢复分支当前完成的是观察性源码组合，保留全部原 cold 新增文件、原拒绝条件和独立 target；1,214 个边界、927 条 protected 记录还未在最终组合执行正式门。原 NoUpdate6 未完成 C，故暂停冷正式编译／父流程，等待具体修复后的新冻结源；不能继承独立普通分支的通过结果。三文件 D 身份修正也是源码草案，实际新 D、FinalUse 均为 0。

Adopt 的 240 秒 head 与 300 秒真实退休等待之间的缺口已有 [独立设计](../cell-e6-metrics-integration-20261119/adopt-head-use-design/)：专用历史内容读取、新目的 Selector、真实 C 完成与新 D 的绑定，以及相应 Root／恢复／live 检查。34 个拒绝控制只是计划，0 个已执行。独立复核指出，最后还需要依赖已确定 selection／intent 的原 controller authorization，以及旧 writer 退休后的真实 policy／撤销新鲜度来源；不变的 frontier 不能代替当前有效性。

另有 [三个 Rust 文件的默认关闭原语草案](../cell-e6-metrics-integration-20261119/adopt-head-use-primitive-draft/)，共 649 行、68 个固定字段、16 KiB 严格解码上限。私有相对验证结果拒绝所有产品授权；没有 module 接线、实际编译、签名、native 或生产 enrollment。首次 subject／policy 构造依赖问题已在源码自审修正，原草案 revision 仍保存。它提供可审阅的后续实现边界，不是已实现 Adopt 冷启动。

组件测试、原完整 NoUpdate、Adopt、新 C、冷恢复后的新 D、FinalUse 和结算仍是不同证据门，分别报告。

## Chain：局部有效修复尚未改变原 F0 结论

[原 Draft #970](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/970) 更新到 `de5f5766fe44fdc42507afe14b30873060c9e4d2`，继承 [#971](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/971) 的完整 F0 证据。修复仅让新完成的 native refusal 安排延迟，精确缓存的拒绝不再刷新 500ms 窗口。

原 W1 六项、body refusal 三项、Root delay 四项通过。原 mixed 测试记录 130 次尝试并达到 finite 目标，最大诚实 probe 间隔约 414.92ms；130 次包含预期拒绝，不能称为 130 个成功业务请求。原旧生产对照实际编译后触发预期断言失败。严格 Clippy、formatter、锁定图和精确 push 门通过。

全 repository 检查仍有三类真实失败：旧 observer source BASE 不一致、独立 policy reader 的 r21 与 Rust r22 不一致、PQ lifetime correspondence 不一致。原门未放宽。此修复没有取得足以重开 F0 的有效 W1／ROOT 图成本收益，因此没有重复原 F0。

原 F0 仍为：30 秒目标 1/6，4 秒目标 0/6，及时 ACK 21/42，原数值耗尽测试失败。ACK 不等于业务完成；此前 leaf 优化的 CPU 退步和 NoUpdate 也保留。完整系统存储、网络、能耗和费用仍未知，公开奖励没有扩大。

## 持续执行顺序

优先完成 E6 新源码的实际原 owner 父流程；同时使 16 个来源的训练输入和未曝光验收可执行。后续 E3／E4 仍须在新冻结协议下证明强单教师之外的真实收益和必要通信。全部历史负结果、未知成本、独立身份缺口和未完成门继续原样保留；没有合并或生产激活。
