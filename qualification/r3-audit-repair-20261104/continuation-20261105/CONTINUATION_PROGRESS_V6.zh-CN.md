# 全量审计与阻塞推进记录 V6

**当前正式状态：23项原blocker中，10项CLOSED_SCOPED、12项OPEN、1项SCIENTIFIC_HOLD。全量闭合与最终产品资格均未达到。** 本轮新增闭合为B22原Windows TUI十三例和B13原Windows Lease/Queue九例；原退出条件逐字保持。主候选已发布14路径修复，Windows ACL下一批也已发布并进入原工作流。

本页以主候选CI `0004` 的 **2026-11-05 16:39:47–48 UTC** 为固定快照；根审B13及B11发布、资源终态、16:40:42–16:45:44项目分支观察分别标明时间。后续运行不反写旧快照。完整逐项口径见[ledger V5](continuation-blocker-progress-v5.json)，方向与依赖计划见[计划 V4](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V4.zh-CN.md)。

## 1. 已发布的具体结果

| 交付 | 固定身份 | 当前资格 |
|---|---|---|
| 主产品Draft #4797 | head `eed4d6bb61b789b19f60facc79f9e031765fa4c9`；tree `ca1c4671ef6b2773280d01b5d76c6166252f5856` | 相对5b精确14路径，完整10,582叶已核；全量与原平台待终态 |
| 实际PR merge | `3476a8c535f7090c4c868ac85148491b3fdfd983`，parents `[63652be6,eed4d6bb]` | merge与head同ca1树，未合入目标分支 |
| B11 ACL Draft #4884 | head `7e0b2303ed0242d83bf56202e8ffb17f5c856186`；tree `3de59a6aa185b13c8758bff3e8fbc530edcef307` | 相对3a407精确4路径/15新增8删除，原Windows结果待取得 |
| B11实际merge | `582f5315f4f632444ae3782d9381f69ed1ae555d`；tree `1718e3e2235b875320f366d03cf796e2a4e92281` | parents `[eed4d6bb,7e0b2303]`，10,585叶精确等于两条已审来源组合 |

主候选的七个Rust路径分别处理：原tracing用例的进程隔离、GNU/musl文件系统类型的无损比较、五个批准/权限fixture的非login shell、本地Responses驱动的树恢复fixture、Windows八处宏歧义，以及Memory真实过期fixture的setup竞争。另七个路径修复大库存文件的无损包装与引用。Cargo/Bazel锁和原工作流保持。

tracing fixture保留原3,621字节业务体、三个span断言、原内层5秒，并在同一测试可执行文件的自有子进程内精确执行一次，父5秒并持有清理责任。五个shell fixture只设置已有`allow_login_shell=false`，其原命令、政策、输出断言与预算保持。恢复fixture通过真实ConfigBuilder接本地Responses，仍实际启动原turn并要求原5秒、持久化、删除后的NotFound和清理。

Memory失败位于原`append_intent`，四次事务争用`floor(now)+1`所剩的不足一秒setup窗口。新fixture明确使用真实**10秒**setup lease，随后每25ms观察真实系统时间并在**12秒**等待窗口内跨过实际到期点；原十条断言、调用顺序、错误store、RolledBack/replay、旧executor/admit拒绝和generation2不变。这里确实改变了fixture内部时间，不能宣称所有时间预算原样；生产过期判定和原目标外层预算保持。尚待新Windows原例执行。

原1,846,885字节库存JSON触发512,000字节blob门。新4,366字节索引和恢复器使用已有18个分片，严格重构gzip/TAR的117成员及原完整JSON；根已逐字核对1,103 PR和5,193 branch库存，不删记录、不增大小豁免。988条既有evidence索引行保持，更新原库存身份并增加两个恢复说明项。新CI该门的终态仍另验。

## 2. 本轮真实闭合的两个blocker

**B22：原Windows TUI中断/退出合同。** 原main Windows shard3 job `127339255966` 的20成员完整ZIP已由根逐CRC/hash验证，固定六份源码、十三个原名各一次PASS。真实stdout标记与canonical cwd、同turn的事件顺序、关闭前先await interrupt、损坏SQLite的实际拒绝均保留；历史旧predicate的有效失败/修后通过单独留存。完整TUI为3,775PASS/6原ignored，Queue36PASS；十三个B22原名没有ignore。原Bazel重试策略未改，不能把“没有目标attempt日志”写成retries=0。[根审原件](reviews/b22-original-windows-closure-root-verification-v1.json)

**B13：原Windows Lease/Queue合同。** 两个Windows GitQueue source/merge工件各含八个原名PASS；此前缺失的第九名`qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence`真实出现在main shard2的显式Bazel qualification目标中。该目标三名PASS、0FAIL、0ignored、172原filtered，30.56秒；默认Cargo不含feature不否定这次显式目标执行。根另取官方artifact列表核对ZIP大小/digest，核三个ZIP共74成员和七份固定源码，读完整九例及负控。真实30秒lease、过期后quarantine、panic guardian、release=0、单次发送与重开SQLite后不重放全部保持。原48失败中对应guardian的原平台是Windows-shard3；这不是五平台全部通过，也不借历史d12 native结果给5b。[根审原件](reviews/b13-original-windows-closure-root-verification-v1.json)

这两项关闭的是原固定源合同。新eed整合资格、完整B15与生产Root/Current/FinalUse仍分别验收。

## 3. Windows严格隔离：现在已知道什么

native4的原job `127352234293` 完整结果为**140PASS、13FAIL、2原ignored**，包含8个机制观察行、8个恢复行和8个完成行。根核14成员ZIP、全部原始JSON与源绑定，未修复两行被并行stdout交织的host JSON。六个restricted行完整；四个token共80个自有对象完成清理。

当前strict在medium和另一low对象上仍可删除外部文件/目录；仅Low MIC可拒绝medium对象写删，但仍允许对另一Low对象删除。full-restricting加独立RX SID在这些有限自有对象上保留读取与合法内部I/O，并拒绝外部四类写删。它尚未证明真实子进程loader、ambient read、正常caller和后代生命周期。

十三个失败准确分为：4个ACL API错误、1个严格令牌真实外删、1个token构造前普通host四格前提失败、1个旧错误叶文字断言、以及后续6个全局mutex poison。后两类不是新的独立安全结论。

已发布的ACL候选仅使同对象修补句柄请求`READ_CONTROL | WRITE_DAC`，保留原只读/no-op；原真实无WRITE_DAC负控同步保持。legacy断言仍要求精确外层路径和“未启动子进程”，错误叶改为typed PermissionDenied/OS5。工作流只补三个Rust路径触发，原目标、runner、预算与回传不变。两个独审接受其进入Windows验收；目录ReOpenFile错误5根因尚未实测解决。新run `42066891449` / job `127383345954` 初次观察为queued。[候选发布](reviews/b11-acl-four-path-publication-v1.json)

正常有限read路线的源码审查还发现：read ACL helper异步执行且已有mutex会被当作完成；SpawnRequest没有携带有限read根和每次grant所有者；runner会保留后代并`process::exit`，普通Drop无法证明全部后代已退出。因此完整token修复需要同步准备与可证明的资源寿命，不能把有限探针PASS直接当作生产能力。

## 4. Linux完整门：真实结果与资源阻塞

ROG上旧e78固定树的原owning范围为**3,962PASS/5FAIL/10ignored**，同进程Core parallel为**2,432PASS/1FAIL/1ignored**。它们是不同命令范围，不能相加成独立全库通过。完整29原文件共33,420,419字节已从70个严格分片恢复并逐字核验；25例实际早退保留（24remote，1无特权namespace能力），不能因JUnit显示PASS或captured为空便计业务执行。remaining54中38名实际PASS，和25早退交集为零；另16位于未执行的MCP/AppServer/feature范围。[完整根审](reviews/rog-complete29-root-verification-v2.json)

原生完整执行包已经完成：同源七helper、193工作区成员/1501依赖节点、原19,563目录项（19,506可执行/57原ignored）、无筛选原`just test`、零重试、完整JUnit/目录多重性对照和终态source/index/双锁/SDK守卫。原full之后才进入scoped fix→fmt，hygiene之后不再本地重测。

唯一firststart job `1a1ac90de70-fc05-5557`于16:35:47真正启动，磁盘139,231,227,904 B满足64,000,000,000 B门，可用内存25,061,957,632 B低于34,359,738,368 B原门。因此在源码切换前退出1：**0源码修改、0构建、0目录/测试、0hygiene**。原生工作树仍e78、普通HEAD仍5b、index仍b488；三份完整SDK回执（各151,134字节）除时间外一致，171文件/147链接保持。这不是ca1产品测试失败或通过。[完整原件运输](generated-evidence/ca1-full-resource-stop-v7/transport-manifest.json)

五台已配置Linux的不同时间实际观察中：desktop/ROG磁盘不足64GB；ai395本次内存不足32GiB；pocket4和x230的总内存都不足32GiB。目前没有已确认满足原门的主机。资源可能变化，但不会据此预测何时恢复，也未清缓存、杀未知进程或降低门槛。最小接续是ai395同一已准备目录重新满足原容量及全部身份守卫，再以明确新的续接请求执行；失败key与旧B16未知driver均不重放。

## 5. 原CI失败与新CI分别记录

旧5b在发布前0077快照为19runs、86jobs；发布后0078为92jobs：44S、9F、5skip、31cancel、3Q。24个旧queued job在新发布后转cancel，另有新派生job；旧两项更早取消的原因仍UNKNOWN。未手动取消或重跑。`cancel-in-progress:false`也不能证明旧pending一定保留，实际API为准。

旧main Windows完整四分片原件已取，140个ZIP成员的最终物理结果保留。最终Memory一例FAIL、Core四例FAIL；另两Core早attempt失败后通过，不能记为六个最终FAIL。shard2的宏歧义同时阻挡Clippy和release build，原八处E0659已原样保留。cargo-deny结果FAIL，但完整原原因尚未回收，不能编造依赖漏洞或策略原因。

新eed在固定0004快照有**19runs / 53jobs：9成功、2跳过、36排队、6运行中**。成功的job级状态不能代替具名原例/负控正文；新状态也不清除旧失败。Core生命周期、retained及GitQueue source/merge已API成功，继续读取原文和source/JUnit。后续0005及更晚观察单独追加。

## 6. 全项目新发展与下一步

原全量仓库库存属于03:16–03:24固定时点。16:29搜索发现18个更新中的open PR，16:40:42–16:45:44另读16个非本轮PR的固定head；这是bounded增量，不是重新计算全库当前总数。原文、完整元数据和观察时间已保留。Cell/Circuit、角色分化、40模块恢复、Memory V15、W0–W7和外部PQ效果都有新增源码，但多数仍为Draft，真实生产接受保持独立。

后续顺序为：取得并修复主候选原CI → 完成原Linux full与最终hygiene → 原Windows严格权限/正常loader接线 → 同源Root/Current/FinalUse及正常UI闭环 → 固定预算的共享计算、独立科学试验与外部真实消费者接受。每一项的具体动作、原退出标准和新并行分支关系见[计划V4](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V4.zh-CN.md)。B18不会因工程工作流变绿而转为采用；B19不会因本地签名或模拟接口而转为外部接受。

旧V6所称“最大祖先跨度211”在此更正为**ref名称层级/stack-depth指标211**，没有实际commit祖先跨度证明。旧观察和失败原件保留，不追改其当时时间。

### 主要来源

- [主Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)、[14路径精确发布](reviews/primary-14-path-publication-v1.json)
- [B11 Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)、[native4根审](reviews/b11-native4-root-original-verification-v1.json)
- [B13根审](reviews/b13-original-windows-closure-root-verification-v1.json)、[B22根审](reviews/b22-original-windows-closure-root-verification-v1.json)
- [全量原库存与审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)、[无损库存根审](reviews/inventory-packaging-root-verification-v1.json)
- [ledger V5](continuation-blocker-progress-v5.json)、[本批证据索引](evidence-index-v7-registered.json)

## 7. 固定快照之后的实际执行增量

本节追加16:39:48原cut之后取得的结果；上文和无损原件中的原观察时间不被改写。

### Windows ACL：原完整目标143通过、10失败

run `42066891449` / job `127383345954` 在16:52:59终态FAILURE，实际checkout `582f5315…`、tree `1718e3e2…`，具有主eed与7e两个已核父源。两个互不重叠的原harness合计**143PASS / 10FAIL / 2原ignored**，不是两次重试。partial-read修补、legacy capture和session的启动前拒绝原例均直接PASS。剩余失败为**2目录ReOpenFile错误5、1无WRITE_DAC控制的物理前提不成立、1strict外部删除、2普通host前提以及4个mutex poison后续失败**。最后四项不计作四个独立权限缺陷。

根独立核官方artifact digest、14个完整ZIP成员、八份源码身份、源码前后干净、完整失败块和两个原结果摘要。此次只有六个完整JSON机制行可解析；`host/medium`和`current_strict/medium`被并发输出交织，未补造。八个restore与八个finalized记录逐字一致，80个自有对象中54个survivor、26个deleted/pending，恢复错误0、所启后代0；不得把native4的行身份复制为这次结果。**B11继续OPEN**，下一源码修复针对实际目录句柄/权限前提，并继续保留原完整目标与真实严格令牌缺陷。[根审](reviews/b11-native5-root-original-verification-v1.json)

### 新主候选：完整Windows原件已验证的范围

新eed的五份完整成功ZIP均CRC和逐成员hash核验。Core八个shard/33个外层libtest调用严格核到**2,340PASS、3原ignored、2,343个不同外层名字**，原blocking-snapshot父测试及其精确一例子进程均通过；子进程不重复加进总数。原三库retained范围从完整Nextest raw/JUnit逐名多重性对照得到**532PASS（299＋209＋24）**，不是控制台截尾中的42个内嵌结果块；raw另列七个所选范围外skip，工件未给名字，不编造原因。GitQueue的source与merge分别**35个Git utils外层PASS＋36个Queue外层PASS**，子进程/重复保留文件不再加数。早期核验器中fork/resume文件标签倒置与计数勘误保留为历史原件。[五工件独审](reviews/eed-windows-success-review-v2.json)

17:07:23–24独立快照为**19runs / 53jobs：17成功、2跳过、31排队、2运行、1取消、0失败**。后增Windows recovery两个job和Intel V8两个build此时只证API成功，尚未借其关闭原用例。31个queued job的runner均未分配；两个新workflow仍pending且0job，旧5b同并发组workflow尚未终态，与workflow级concurrency等待一致，但REST没有直接waits-for字段，不能当作确定调度原因。没有手动取消或重跑。

### SQLx donor：真实原件支持机制复用

#4855两个已知x230 native job的完整status/stdout只读回收，按原导出身份还原142,236字节、20成员ZIP，全部CRC与18个原始流hash匹配。State原测试在tests-only源两次尝试均以`InvalidSavePointStatement`失败；同argv/profile在修复源同case实际PASS。另九包原catalog的1,312个身份与1,288PASS＋24原ignored逐名一致，原Memory取消gate也实际通过。包内无JUnit，不虚构XML。当前#4855三个相关文件与该通过源逐字相同，可直接复用其缺陷和丢弃连接的修复依据。

该证据不免除本候选的两独立pool构造器、TEMP marker物理换连接、精确SQLite 531/回调计数、autocommit和tracked-depth双观察、checkout次数及native owner custody原门；B16继续OPEN。未重新启动donor实验，旧GitHub-only缺原件回执保留。[SQLx原件独审](reviews/pr4855-refused-commit-reuse/REVIEW.zh-CN.md)

容量方面，#4843所指原Bazel任务已在15:49:30终态failed，早于16:35的资源拒绝，不能推断刚释放了内存。16:58:50一次只读硬件观察仍仅约25.01GB可用内存，未达到原32GiB门；未再次启动native full。
