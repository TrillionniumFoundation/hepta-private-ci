# Blocker 闭合清单与当前证据（2026-11-12 18:52:55 UTC）

**整体 HOLD；12 个完整科学／权限门仍 OPEN，owner_decision=null，all_blockers_closed=false。**
本页区分源码修复、实际工程验证和完整研究资格。历史失败、UNKNOWN 与原研究 NoUpdate 均保留；缺件不转写成 owner 决定。

## 最新源码与整合状态

[#6213](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6213) 已发布 **872b1b68342285893abd4c09f9141bcc19d8f9ce**，tree **5a22d17b8d21f2b9843d508ec4ef21f8045a0c66**。相对edaf为46路径、901新增／214删除、4新文件，全部旧方法覆盖保留。18:35:16按准确head读取Actions集合，实际total_count=0；本提交没有可继承的格式、编译或测试PASS。

实际目标分支已到 **d3977d9a1bed3e89952c576c45660b04ea674faf**，tree **57558558841da4a3209164d0033b903a553205d6**。PR摘要仍返回旧base a96，当前使用真实branch ref核对。共同祖先a96之后，上游2提交改变140路径；双方31个同路径变化正在三方整合：8生产、8测试、13QA、2清单。另发现5个上游新retention文件需适配已有owning lease。13个生产后像已独立读回26个原blob，逐项正向与逆向还原一致；最终整合及CI尚未完成。

| 872b 已发布修复 | 已核查范围；执行边界 |
| --- | --- |
| Windows原文件观察 | 原独占File上有界读取、保存／恢复cursor，错误保持拒绝，保留真实owner队列与文件字节比较。测试功能默认关闭，4个新真实持有文件回归；新源码NOT_RUN。 |
| Model原执行包 | 两个原HPEXEV01标识符按producer的u16长度解码；其余u32标识与Qualification u64计数不变。原preimage畸形／截断反例保留；NOT_RUN。 |
| Legacy C同次读取 | 私有read set返还同一原读取的Selection／Observation／Sourcepublication；保留物理前后读取及独立Selection尾检查。显式读取70→42仅为静态计数，未包括完整递归Material，未证明500ms。 |
| C三种原前驱故障 | 原Trainer／Evaluator／Selector三case分成3个真实方法，断言／字节／T/B数量／清理不变。旧名称现在只覆盖Trainer，必须三方法全通过才覆盖原3case；不把拆分当加速。 |
| macOS helper | 仅4处Linux cfg与原Linux类型定义一致，函数体不变；NOT_RUN。 |
| Bazel | 现有全名分片器8分片，每进程2个test body，flaky=false，300秒限额不变；跨8分片最多16个body，非全局2。仅修改配置，未手动派发。 |
| Fence | 固定官方v0.13.0完整commit，保留audit/debug、allowlist和失败检查。原失败主机尚无新PASS，其他runner镜像上的官方成功不能代替。 |

[46路径原源码核验](../evaluated-current-read-20261112/repair-872b-review/ROOT_SOURCE_REVIEW.json) · [三方31原交集](../evaluated-current-read-20261112/merge-d397-review/ORIGINAL_THREE_WAY_OVERLAP.json) · [13生产独立审查](../evaluated-current-read-20261112/merge-d397-review/ROOT_PRODUCTION_REVIEW.json)。

## 原始执行的新增终态

| 准确源码／范围 | 实际终态 |
| --- | --- |
| edaf native / job131356096885 | 414 source、16 parser、同源helper通过；1,738普通方法=1,730PASS＋7FAIL＋1TIMEOUT；98在选择式之外，0重试。Root/fix/fmt未到达。完整原log3,746,884B已重组核SHA。 |
| edaf caller / job131356097229 | 18:13:57实际success；541边界／541清单／390保护／6,604Rust文件，authorityGranted=false；完整2,150,402B原log已归档。 |
| 286c native / job131353000746 | 独立原执行亦1,730PASS／7FAIL／1TIMEOUT；不与edaf互转结果。原格式失败仍保留。完整3,745,736B日志已核对。 |
| 286c caller / job131353001352 | 18:06:09实际success；同样541／541／390／6,604；完整2,149,098B日志已重组并与原job一致。 |
| edaf Windows私有状态专项 | 36/36所选方法PASS，597过滤、0失败／错误／XMLskip／重试；完整原log376,431B。非全Windows或Root资格。 |
| edaf Rustfmt／GNU Clippy | 完整原日志success；实际synthetic执行tree与edaf一致。Windows Clippy及两种release为原job元数据success，其完整日志未另取。 |
| edaf GNU／musl Bazel | 各300.1秒TIMEOUT；1190 announced，915显式PASS／15FAIL／87ignored／173无观察终态。两份规范化输出相同，不计独立重复。 |
| edaf Windows／macOS | 四Windows分片、Mac Intel实际失败；完整日志各自保存。Hepta原锁冲突与Mac6类型编译错误已提出修复；其他core/TUI/app-server/exec-server失败单独保留，未绕过隔离拒绝。 |
| edaf Fence | checkout前local_control_inventory_unavailable；checker_result=null。升级修复当前尚未执行。 |

edaf剩余8个非通过方法是4个evaluated C（其中1超时）、3个Model材料方法和1个旧NextUse方法。此前Candidate超时方法在edaf已实际PASS40.992秒，真实计数[1,76,76,76]；不再把它列为edaf当前失败，也不转为新完整桥接PASS。S/E返回真实PredecessorUnavailable，尚不能仅归因为外层deadline。

[edaf native](../evaluated-current-read-20261112/edaf-native-failure/MANIFEST.json) · [edaf caller](../evaluated-current-read-20261112/edaf-caller-success/MANIFEST.json) · [286c native](../evaluated-current-read-20261112/286c-native-failure/MANIFEST.json) · [286c caller](../evaluated-current-read-20261112/286c-caller-success/MANIFEST.json) · [Windows专项](../evaluated-current-read-20261112/edaf-windows-private-pass/MANIFEST.json) · [Windows／Mac原失败](../evaluated-current-read-20261112/edaf-bazel-windows123-mac-failures/MANIFEST.json)。

## 仍在推进的工程闭环

1. 完成d397三方整合，保留全部新桥接、原真实Source检查、旧回归及exact caller/protected守卫；复核最终tree后发布到原Draft PR。
2. 取得整合后准确source的受理、完整分母、caller、编译／格式、ordinary及Root原记录。旧源码PASS和静态预期均不填为新PASS。
3. 按真实端点重新核算递归Material与时限。d397局部事务将Trainer4读降为2读、Candidate每实际callback6读降为2读；完整Root链、Evaluator成员拓扑与去重尚未完成，不能直接断言满足128帧／500ms／300s。旧edaf下界616/P1仅保留为旧源码审计。
4. 继续追踪实际S/E拒绝、完整cold恢复和不同worker/boot原权限链。科学效益、来源／暴露认证与原owner决定必须由原始证据关闭。

[新预算进度与实际pins](../evaluated-current-read-20261112/d397-recursive-material-budget/IN_PROGRESS.json) · [旧预算审计](../evaluated-current-read-20261112/9fac-nested-material-budget/STATIC_REVIEW.json)。

## 1. 本轮已经闭合的具体缺口

| 子项 | 原件与已验证结果 | 范围 |
| --- | --- | --- |
| Q24 时间接口 | [#6192](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6192) exact 1ac802f4...；hosted 43173410889：106 Rust、119 Python 通过；11 个 Decimal90 边界向量最大 Q24 差 0、容差 1。 | 数值与前缀／路由机制；不认证真实时钟或证明学习效益。 |
| V wrapper 原 API 接通 | [#6198](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6198) implementation 52f936df...；hosted 43174070320：106 Rust、129 Python 通过；92 个上游文件的原 freeze/thaw/load/计划验证实际运行。 | 该版本的 fixture 机械检查；后续真实 freeze 与 B/C 四个固定宏执行均已完成、均为 STOP。后续证据提交不改变测试所属源码。 |
| wrapper 的真实 run-v2 资产入口 | 原job1a1cf673fde... exit0；固定wrapper实际load_native/validate_partitions完成6项检查，85项原source/driver/analysis记录及16个真实输入资产前后不变。root独立读回核对11个原文件。 | 只读、无文件写入/子进程/网络；原cold-load记录被验证，但本轮未新做cold-load。该只读探针本身没有freeze或actor；其后正式freeze与B受理另列。 |
| 正式 wrapper freeze 与 B/C 原执行 | freeze 原 job1a1cf9dcdb3...成功；两计划、四部署、96项输入不变，四个新ID与旧576无交集。B原job1a1cfb71a25...与C原job1a1cfd835b7...各2/2 COMPLETED。 | 完整 stdout/status、report、四组终态/REALIZATION均由root核验；四次均STOP、无READ、质量0。六份来源快照完整SHA一致；新独立来源0，calibration/full_cost仍false，owner=null。 |
| 原 run-v2 终态与全分母 | 原 key/session 读回，12/12 campaign stages exit 0；16 来源×3 context×12 arm，共 576/576 COMPLETED，FAILED/UNKNOWN/缺失均 0。 | 上游 development campaign；没有重派发，没有将其计为 wrapper B/C。 |
| 完整 REPORT／训练 receipt | REPORT 3,108,442 B；receipt 295,081 B。无损 gzip 归档后由 root 独立解压，CRC32、原字节数与完整 SHA256 一致。root 核对 576 唯一执行、全笛卡尔 roster、24 个来源等权均值及全部内容权重 pin。 | 完整原文已恢复；不是只读摘要替代原报告。未重新运行 native admission，未认证 source/clock owner。 |
| 原真实 fit 与模型 cold-load | frozen/adapted 各 126 pairs、UNKNOWN0，fit72/cal54；两个 checkpoint 的完整字节、pin 和独立子进程 cold-load 一致。 | 两份 calibration.complete=false；不是已选模型在普通 C／Root 重启后使用。 |
| 实际公开输入回归 | [#6221](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6221) exact 2d1f610f...：新的 ai395 原入口实际 19 policy＋7 checkpoint 全通过，原日志与 source-before/after 已归档。 | source inventory SHA256 ea34e33b...，执行环境与 hosted 不同。生产归一化修复来自上游 3c94，不冒充本 PR 新修复。 |
| 开发输出 HOLD 语义及完整合同回归 | [#6240](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6240) exact 24112612...：28 套件 **200/200 实际通过、0 失败、0 跳过**；format/lint exit0。root 从 GitHub 回读完整 96,284 B gzip，独立解压并校验全部 149 原文件、28 组原日志、原记录和源码前后384项。 | Python3.12.14、NumPy2.3.5、Pillow11.3.0；普通UID1000，不计 hosted CI。v1 199/200失败、v2/v3零套件的外部driver失败原件保留，产品与断言未改。原3c94的NoUpdate标签仍是历史原文。 |
| evaluated CURRENT 历史证据 | 原 edaf 的 source414/parser16/helper和完整caller通过，ordinary为1,730/1,738，7FAIL＋1TIMEOUT；Root未到达。 | 当前872b是静态已审修复，原结果不转移；详见本页最新状态与原件。 |
| MEM v3 原生成终态 | [#6201](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6201) 的7个原文件已独立核验；原execution fa3b624...返回exit0、1次model call。 | 原process registry仍UNKNOWN/job_id=null。新只读分页仅128/63578条，字段无key/digest，不能据此判断未登记或猜job。记忆效益0。 |

完整原件入口：[终态与 root 核验](evidence/terminal-20261112/README.md)、[无损 REPORT](evidence/report-lossless-archive-20261112/)、[content receipt](evidence/content-receipt-lossless-archive-20261112/)、[原只读分析](evidence/report-readonly-analysis-20261112/)、[19/26 实际验证清单](../runtime-validation-20261112/PR6240_PR6221_EVIDENCE_MANIFEST.json)、[MEM 原件](evidence/mem11-v3-reconciliation-20261112/)。

## 2. 已完成 development 实验的结果

以下为同一完整原报告的描述性来源等权质量；每格 48 次执行，全部完成。来源簇才是独立性讨论单位，seed 不扩充独立样本。

| 策略 | frozen READ/STOP | frozen 质量 | adapted READ/STOP | adapted 质量 |
| --- | ---: | ---: | ---: | ---: |
| STOP | 0/48 | 0.197917 | 0/48 | 0.187500 |
| light | 0/48 | 0.197917 | 24/24 | 0.218750 |
| tuned-fixed | 0/48 | 0.197917 | 0/48 | 0.187500 |
| point | 19/29 | 0.281250 | 19/29 | 0.270833 |
| unconditional | 0/48 | 0.197917 | 0/48 | 0.187500 |
| conditional | 0/48 | 0.197917 | 0/48 | 0.187500 |

conditional 的 96 次决策全部 STOP：94 次 insufficient_calibration、2 次 evaluation feature-envelope 拒绝。两分组各9来源、alpha=0.1、有限分位数秩1；最小来源数门已经满足，不能把失败归结为“还差一个 calibration source”。完整原 run-v2 EXPORT 已定位：frozen 45/54 域内、9条越界；adapted 47/54 域内、7条越界，各涉及7个来源。所有54条 paired gain均已知，每个来源仍有域内行。root独立取回两份原EXPORT并校验SHA，重算72×47训练边界与全部校准行，结果完全一致。evaluation的两条越界与这些calibration行分别登记。真实预算为READ30＋收尾5≤action40，episode wall60；预算不是拒绝原因。详见[完整域审计](evidence/v-calibration-domain-20261112/V_CALIBRATION_DOMAIN_AUDIT.md)与[root独立重算](evidence/v-calibration-domain-20261112/ROOT_RECOMPUTATION.json)。

conditional−STOP 的配对质量差在 frozen/adapted 均为0，质量交互为0。仅计已观察任务成本的净值交互约 −0.00028103645；完整生命周期成本交互为 null。此处微小净值差与实际任务计时相关，不构成学会检查或独立科学效益。point 的质量均值较高仅是该 development 面板描述，未经过来源认证、功效与确认检验。

content receipt 证明实际完成60 optimizer steps、12 epochs、每轮142 rows、24 fit sources，且参数 hash 与独立 cold-load 一致；使用 observed_auxiliary_losses，recursive_objective_applied=false、environment_unbiased_policy_gradient=false、control_gradient_into_content=null，历史暴露未清除。不能将“参数改变”改写成完整递归学习资格。

原 campaign 全阶段成功，而外层 launcher 因结尾错误读取 run-v1/COMPLETED.json 返回1。原 FAILED 记录保留；实际运行输出是 run-v2，不能因此重派原 campaign。先前部分 chunk 读取失败记录也保留，后续完整解压／SHA 核验已闭合原文读取缺口。

## 4. 原 scope 的12项完整资格门

| 门 | 当前状态／实际进展 | 尚需的关闭原件 |
| --- | --- | --- |
| 来源／暴露认证 | OPEN；字节／split／source ID 一致性已核对，REPORT 的24 fit、18 cal、16 eval来源名互斥。 | 原来源 owner 的 acquisition/receipt/exposure 链、历史隔离／quarantine；名字互斥不能证明真实来源独立。 |
| 真实时钟 | OPEN；四个时间量与 Q24 已分开。 | 真实动作、信息可用、结果与更新时刻的原 owner 记录；clock domain／boot、跨恢复锚点和误差界。 |
| 持久 cadence／CAS | OPEN；当前时间 gate 仍无状态／参考。 | 原 LearningOwnerJournal/CURRENT 权限上的跨进程、并发、崩溃和回滚验证；机会只消费一次，pending不重派发。 |
| 原 owner bridge | OPEN；原edaf普通方法1,730/1,738、caller通过；872b修复已发布但未受理CI。实际d397新桥与读事务正在三方整合，31交集加5接口适配。 | 同一准确tree的原StageOwner→verifier→S→FinalUse→CURRENT、真实独立custody、完整递归预算与普通Root/cold执行；源码或历史CI均不替代。 |
| T 时间教学效益 | OPEN；数值／路由机制已验。 | 同完整向量、可用时刻与预算下正确／打乱路由及 eligibility，真实训练、强普通基线、独立效益与旧能力门。 |
| R 独立情景／技能回放 | OPEN；ACT bb8 的 1＋5 方法、格式与完整原产物已过门；MEM 仍仅 1 次未评分生成。 | 同一真实任务 E/S 2×2 与另一个等总预算面板；统一池／普通基线、MEM 禁用后 ACT 独立路径、真实效果与成本。 |
| V 感知／检查效益 | OPEN；上游576次完整开发面板，conditional未READ；wrapper B/C四个固定宏执行均COMPLETED、均STOP、质量0。 | 校准覆盖问题解决后的独立冻结试验、强基线、同信息循环／付费观察／独立checker分别比较、真实净效益。 |
| L 长期可塑性／保留 | OPEN；统计语义已有机械检查。 | 长期真实模型阶段×任务矩阵、新任务样本／时间／成本、未达标删失；旧保留非劣效和新学习效率同时过门。 |
| 独立 B／不同 C | OPEN；当前B/C均development。 | 训练后未暴露的原B、独立evaluator、原owner真实决定，以及不同C／worker按该决定使用的原始效果。 |
| Power／完整分母 | OPEN；本次576计划分母已完整闭合。 | 按来源簇方差／缺失率冻结实用门槛、90% power、四线Holm／同时区间、确认来源与停止规则；不能用seed或本次完成数代替功效。 |
| 全生命周期成本 | OPEN；full_cost_observed_rows=0。 | 数据取得、历史训练／调参、采集／回放／checker、provider/energy、进程树、存储／失败／摊销原件或事先冻结保守界；嵌套耗时不双加。 |
| 普通真实冷恢复 | OPEN；真实两个模型子进程cold-load已完成，ACT受控GRU恢复已有局部证据。 | 已选模型在普通不同C／worker／boot的CURRENT/root version/journal/witness与真实效果，完整Root／daemon恢复；无重训、重签或重复效果。 |

## 证据与执行约束

完整f409旧索引、清单、manifest和README均按原blob保存在[evidence/history-20261112](evidence/history-20261112/)。更早失败和观察继续存在，历史文中的“当前”不代表本次状态。

本次重新核验的144个不可变条目包含133个资格证据文件与11个源代码后像；11个后像只核对原872b，不写入本证据分支。9份完整新增终态日志分别由原job字节、分片连续范围和SHA绑定。完整JUnit／artifact ZIP／source inventory未另取的项目仍明确未取。大整数原件保留原始UTF-8文本；派生摘要不冒充原件。

冻结B/C四宏已完成且均STOP；不重派actor。MEM原registry UNKNOWN不猜job、不换key。三次原Git准备失败保留，没有第四次fetch或本地repo重建。手工Rust验证只允许just test；本轮未手动派发Bazel。没有合并PR、部署、默认采用或代原owner签发决定。

[机器可读索引](TERMINAL_EVIDENCE.json) · [原件入口](evidence/terminal-20261112/README.md) · [本次不可变字节核验](evidence/terminal-20261112/ROOT_IMPORTED_BYTE_READBACK.json)。

[本次发布树与字节独立核验](evidence/terminal-20261112/GIT_READBACK_EDAF_TERMINAL.json)：暂存提交161个变更路径均限于qualification，32个Git树节点及10份新文本完整字节已读回匹配。最终提交另加入该核验记录并更新索引；不代表新source测试通过。
