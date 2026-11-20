# E1–E6 联合推进：实际执行与当前边界

观察时间：2026-11-20T01:20:55-05:00 America/New_York。本页与 [CURRENT_PROGRESS.json](CURRENT_PROGRESS.json) 同步。上一个联合证据提交为 `e4b4eb5028578be87d5cad0829103632f2bff3a3`；旧 CURRENT 的逐字原件另存于 [checkpoint-20261120/](checkpoint-20261120/)。原实验身份、预算、历史失败和 NoUpdate 继续保留。

**本轮已把 #6709 修复接入联合候选，完成原 56 次学生评估，并把公共项目材料补到 16 个。新未来任务仍没有学习收益，完整 E6 采用与 Chain 原业务活性尚未闭合。十项联合资格全部保持 false。**

## 当前实证

| 原工作 | 实际完成 | 当前判断 |
| --- | --- | --- |
| #6709 整合 | 两个原 blob 精准接入；原 114 项／18 模块控制全过，旧逻辑负控复现失败；实际 `just fmt` 与 `--check` 全过、diff 为 0 | 状态标签不再足以累计完成数；这项工程修复不授予 native 采用资格 |
| E1／E2 学习 | 两组原 32-update 权重完成全部原 56 次新生成；47 次 native，9 次准入拒绝 | 两学生 A 各 1/4；新未来面板 P、document、native 均 0/4，ResearchNoUpdate |
| E3 多教师 | 保留原 T2 的真实调用与负结果；不同家族 SmolLM2 的独立有界 Range 恢复正在运行，完整权重尚未通过最终 SHA | 本轮没有新增模型调用、互补收益或共同学生证据 |
| E4 通信 | 保留原 PP／CC／PC／CP 各 5/6、强对照与消融，本轮没有新增模型调用 | Circuit 必要性仍未证明 |
| E5 来源 | 原 4 个项目之外新增 12 个，经 28 次真实修复前后 native 验证，合计 16 个去重公共项目材料 | 真实用户为 0，增长训练更新为 0；两种增长曲线仍为空 |
| E6 原 owner | 实际 drain 路径的原 11 项与 16 项故障／恢复控制通过；原 NoUpdate 在第 65／64 次读取失败；整条父流程预算修复仍在进行 | 原完整 NoUpdate、Adopt、新 C、冷新 D、FinalUse 和结算按各自原门计数 |
| Chain | W1 延迟修复通过 6／3／4 项 native 控制和原 130-attempt mixed 测试；旧生产负控确实失败 | 全 repository 检查仍失败；原 F0 与完整成本没有被局部通过替代 |

## #6709 已落到明确联合候选

整合源为 `0bdf65445f9bbefba2c45dc3e611dd36386a1456`，原修复来自 `773f25e53504790c74364aa3b1606ed51853df32`。production 和 test 的 Git blob 分别为 `04c556c5831ba2a01341404f15882020a68ff956`、`3bd61299f923e1f3ce2f80d92780991dfab4434e`。

原生产配新回归测试得到 7 项测试中的 1 个预期失败，直接复现缺少 C 使用仍可计完成的问题。整合后的原 114 项控制全部通过，0 failure／error／skip；首次缺少原 fixture 的设置失败也完整保留。终态实验必须绑定经过验证的 C 使用和一致的冷进程回放，计数输出仍明确区分实验采用与 native 采用。

在精确 `e4b4eb50` 隔离 worktree 上实际执行原 `just fmt --base 325218ec...` 和 `--check`，退出均为 0，diff 为 0。锁定 Ruff 0.15.13，没有修改两份整合源码。缺 uv、下载超时和 offline cache 失败等 38 份原件均在 [整合验证说明](../cell-e6-metrics-integration-20261119/FINAL_VALIDATION.md) 中绑定，未用最终通过覆盖旧失败。

工程 CI 的另 216 项通过实际运行在 PR prospective merge `fa730773d40130a59acb68fd08443717ba95ec04`。这不等于对每个分支或新联合 head 执行了 native E6。engineering 和 v8 canary 已成功，architecture 与 blocking 已失败。architecture 的 source-head 身份检查通过，但预期 base 已变为 `2742bc37`，实际受测 merge 的 base parent 仍为 `06133474`，所以 base-merge 身份门失败。原 contract 扫描还把 Chain API 原件中的工作流路径当作本仓库路径；cargo-deny 和 Bazel 等 blocking 失败尚未关闭。Windows hepta-paths 的 48 项 Python／9 项 native 通过，也不能代替原 FILE_DELETE_CHILD 业务用例。原日志保留，检查器未放宽。

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

新 [#6781](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6781) 冻结了 SmolLM2-1.7B-Instruct 的独立 revision、模型卡和许可来源。原 895 秒下载窗口实际失败，只保留 255,852,544／3,422,777,952 字节权重；该原失败和完整日志继续保留。本轮在独立目录冻结并启动一次恢复：4 个固定 worker、95 个不重叠范围，每段不重试，895 秒截止；原 partial 只读保留，总 HTTP 体上界 3,427,266,230 字节，低于原 4 GiB。9 个无网络协议控制通过，实际请求已观察到与各冻结范围匹配的 HTTP 206。观察时 owner `dpty-9c793d930ee32ba9d5e98dab865601b80aad62c8cade3c72d04e3b1fda709b67` 尚在运行，只有完整文件匹配原 LFS SHA 才能标为 ready；模型没有被加载。 已知 T2 权重的轻量 stat 与历史身份一致，旁边的 MTP 文件没有获得独立基座及许可证明，均未重新运行模型。

协议复核还明确了两个后续接口问题：原 T2 HTTP runner 未执行声明的 4096 输入 token 准入，尽管实际旧记录最大只有 796、没有发现历史超限；desktop 当前基座准入硬绑定 Qwen2，不能直接把 Smol 的 Llama 配置换入。需要各自明确的 tokenizer、template、模型身份和新实验冻结，不能放松原身份检查。

E4 的原 PP／CC／PC／CP 各 5/6 没有超过强单模型。oracle 的 6/6 只表明理想组合覆盖范围；实际去答案是 4/6、去反馈是 5/6、retrieval 是 0/6，不能转成已实现的路由收益。本轮没有新增通信实验，也没有授予 Circuit 必要性或组织涌现资格。

## E5：16 个材料来源已经闭合，真实增长训练仍要通过输入准入

首批新增十项目的完整证据在 [#6777](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6777)，当前证据提交 `78eb0dfdb28563f2527aa1cfc27f9b40997f70ea`。四次顺序尝试共 24 个真实 native children；完整原件包含 10,408 个文件、113,148,963 字节，逐件路径、类型、mode、大小、SHA256 均核验。原下载失败、PyPI 元数据截断、缺少 simplejson／原 example fixture，以及 collector 临时目录前缀误计，都保留原结果。

修复后的身份读回只移除 pytest 引入的精确临时目录前缀，完整 module、class、function、parameter、顺序和数量仍一致。永久 collector 修复复核了原 24 个 children 和 30 个改变参数／外来路径／缺 case 的负控，没有新增 native。loguru 的原 skip 仍显示为 skip。

独立 [#6782](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6782) 又对 multimethod 和 natsort 执行四个原生 children，修复前各失败一次、修复后各通过一次。原四项目加十项目再加两项目，形成 16 个不同公共项目材料。项目、修复 PR、原 before／after 和完整测试身份都在 JSON 中列明。它们不是 16 名已认证用户，也不是每项目 32 条独立 agent 轨迹。

原 1／4／16／64 来源点、固定总预算与固定每来源预算、每来源 32 单位均保留。按照原大小写敏感 `source_id` 字典序，新 1-source prefix 是 loguru，4-source prefix 是 loguru、natsort、rich、multimethod；旧四项目权重不能冒充这些新 prefix 的训练结果。

独立 [#6783](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6783) 已发布 `63f494553a735bd55a3fef7cfe2e76604cd6db7d`：源 prefix 在适配构造前冻结，实际通过 16/16 材料正控、拒绝 22/22 篡改负控，并精确重建 17 个 runtime 文件。完整解包回读核验 1,645 个成员，包含 1,628 个字节对象。原每侧 290 个测试身份的结果为 before 35 个失败、after 289 passed／1 skip；这是旧 native 原件的回读，没有新增 native。

这个检查验证冻结可信原件内部的完整性，不能独立证明来源不可伪造或训练有用。新材料接口完整保留补丁、上下文、fixture、参数及许可，但实际 SFT 程序仍固定绑定原四题和其摘要。原增长协议尚未冻结 token、MAC、验证预算及 optimizer 单位映射，新的未曝光 B/C 也未准入。若拟将一单位定义为单材料单 update，固定总 32 单位在 n=64 最多曝光 32 个来源；不能通过更改 batch 定义、追加更新或复用项目把它写成 64 个都参与了训练。旧程序、原预算和历史结果不改。两种增长曲线仍为 null；64 来源还缺 48 个；本轮增长训练更新和已认证用户均为 0。

首批完整材料候选 `b6822f9a` 的原字节门实际覆盖 104 个变更文件并通过；加入回读证据后的最终 `78eb0dfd` 也实际通过相同原门，共覆盖 139 个变更文件，512,000 字节门槛和原 allowlist 均未改。最终外部验证原件另存于 [E5 最终发布回读](../cell-e6-metrics-integration-20261119/e5-final-publication-readback/)。

## E6：实际 drain 与原 owner 链路

[独立 #6776](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6776) 的最新已发布证据为 `ab5e792d1bceb583c246f44d01ee8e433d5c60e8`。实际执行源码为 `e4aeaa2cdd1a4aa884d09cafaeef96968feb7a90`，原 native 11/11 与 retirement／fault 16/16 全过。原完整 NoUpdate 仍失败：`historical_client.read_limit request_id=65 maximum=64`。该测试 case 约 69.972 秒，命令 70.808666 秒，外层 owner 121.382146 秒；这些是嵌套区间，不能相加。实际 A journal／witness 已由原 header-only 40／112 字节变为 93／224 字节；C journal 仍为 0 字节、witness 为 112 字节，因此不计新 C 成功。

原件 201 文件／55,918,596 字节封存在 [drain/read65 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/ab5e792d1bceb583c246f44d01ee8e433d5c60e8/evidence/e6-original-drain-read65-20261120-2e9b)。物理密钥仅记录 metadata，正文留在原 host。首个 b5 源的宏歧义编译失败、e4 两项显式 import 修正、compiler 退出 0 但 recorder 元数据假设失败的原记录均保留。完整 275 项 source／893 protected／1,138 caller 检查属于 `b5da8e70`，未改称在 e4 重跑；e4 的具体 native 和当前 protected／blob 门单独绑定。

新的读取范围候选仍只在隔离本地源码中审查，尚未编译或跑新父。它把同一自然同步操作内的来源、material、selection 和实际动作纳入真实 before／after Root 观察；不得跨外部等待缓存授权。预算核对覆盖初始化、连接、C 发布、receipt owner 安装、Selection、NextUse，以及 delivery 完成与 terminal acceptance，不能只算到 Submit 返回。原 65 次失败仍是最新真实父结果；静态省读估计不算完整实验通过。

此前 `27d90883` 的首因修复让真正的 `GenerationFenced("original C predecessor or new witness history differs")` 显露出来，而不是被后续 delivery 错误遮盖。原 native11 通过，但完整 NoUpdate 仍失败。检查发现原 generation journal／witness 只有初始头部，既有 `drain_completed_task` 没有产品调用。

新的产品路径在原签名 Outcome 被接受、source 检查完成、原状态真实 Complete 且任务仍为 Active 时才执行 drain；随后核对完成时的 publication 和前后状态。Retained 和只读观察路径不触发写操作。实际故障控制包含 journal fsync 后 witness 写入失败、重开修复和重复 drain 不重复追加；没有合成一个“已 drain”状态绕过旧前驱检查。

原 64 次读取上限、500ms 及 240／300／600 秒条件保持。Adopt 的 CURRENT 240 秒与旧 writer 300 秒窗口冲突仍必须由原 owner 的有效授权路径解决，不能借新 D 签名盖过旧过期状态。组件测试、原完整 NoUpdate、Adopt、新 C、冷恢复后的新 D、FinalUse、结算是不同证据门，分别报告。

## Chain：局部有效修复尚未改变原 F0 结论

[原 Draft #970](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/970) 更新到 `de5f5766fe44fdc42507afe14b30873060c9e4d2`，继承 [#971](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/971) 的完整 F0 证据。修复仅让新完成的 native refusal 安排延迟，精确缓存的拒绝不再刷新 500ms 窗口。

原 W1 六项、body refusal 三项、Root delay 四项通过。原 mixed 测试记录 130 次尝试并达到 finite 目标，最大诚实 probe 间隔约 414.92ms；130 次包含预期拒绝，不能称为 130 个成功业务请求。原旧生产对照实际编译后触发预期断言失败。严格 Clippy、formatter、锁定图和精确 push 门通过。

全 repository 检查仍有三类真实失败：旧 observer source BASE 不一致、独立 policy reader 的 r21 与 Rust r22 不一致、PQ lifetime correspondence 不一致。原门未放宽。此修复没有取得足以重开 F0 的有效 W1／ROOT 图成本收益，因此没有重复原 F0。

原 F0 仍为：30 秒目标 1/6，4 秒目标 0/6，及时 ACK 21/42，原数值耗尽测试失败。ACK 不等于业务完成；此前 leaf 优化的 CPU 退步和 NoUpdate 也保留。完整系统存储、网络、能耗和费用仍未知，公开奖励没有扩大。

## 持续执行顺序

优先完成 E6 新源码的实际原 owner 父流程；同时使 16 个来源的训练输入和未曝光验收可执行。后续 E3／E4 仍须在新冻结协议下证明强单教师之外的真实收益和必要通信。全部历史负结果、未知成本、独立身份缺口和未完成门继续原样保留；没有合并或生产激活。
