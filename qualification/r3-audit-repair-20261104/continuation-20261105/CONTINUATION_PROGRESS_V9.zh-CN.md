# 本轮续审、实际修补与剩余阻塞 V9

**当前原23项为16项限定范围闭合、6项开放、1项科学验证保留；全部blocker尚未闭合。** 相对续审父提交46fd74d98c1cef42e1439920f9ca83361481b3d8，仅B23按原退出条件新增CLOSED_SCOPED。既有B07/B09/B10/B20等已接受范围保留；原ID和字面退出条件逐项不变。

报告整理时间：2026-11-06 05:32:07 UTC。每个API与原生证据各有自己的观察窗口；本时间不将全部窗口合成为原子快照。

完整方向、40模块/91工作包、全部原退出条件和分阶段计划见[项目方向与执行计划V7](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V7.zh-CN.md)。[机器台账V8](continuation-blocker-progress-v8.json)的current_v10为当前事实，历史字段保留原值；[实际证据索引V10](evidence-index-v10-registered.json)列出可重取对象和每包范围。

## 1. 已落实的工作

| 工作 | 实际交付 | 接受边界 |
|---|---|---|
| 重新全量清点 | 3555开放PR、5333分支；连续分页、空终页、锚点和完整机器清单 | 有界非原子元数据；没有声称逐行审阅3555个PR源码 |
| Intel完整上下文 | 原ebd31 native2及main67完整上下文均实际PTY30P/1F；新收件器head84cc7345已发[PR4902](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4902) | 原2秒/5秒、drain/child/FD不变；两个partial drain观察分别保留，充分因果未明 |
| GNU原完整AppServer | fresh e63的8shard307P/1I与main原GNU cached成功各自完整绑定；原5例/stdio/disabled保持 | B23独审与根重放接受；诊断collector失败保留，新head2ac89eaf只修收件，B15未关闭 |
| Windows错误原因链 | [Draft #4913](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4913) 原340源两cause用例PASS、整体141P/13F/2I；当前head18bbef4f只按原formatter补两hunk | 旧340资格不转授新18；整体失败保持，不是ACL语义修复 |
| arg0原Clippy失败修补 | [Draft #4923](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4923) 两处expect_used修补；原GNU Clippy与repo-checks已成功 | 实际source3c9e/merge65e1，原失败和完整日志保留；不转成整库或全平台通过 |
| PTY关闭接收端候选 | [Draft #4927](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4927) 单文件跳过无效分配/发送，head8075eb36 | 已静态独审；原31例、2秒/5秒与两backend保持；新原生和旧超时因果仍待验 |
| Windows原失败归档 | 完整原job日志、官方5,410,721B ZIP/47成员、21次实际Core测试启动与全部重试 | 原Bazel退出3；持续3例失败仍保留 |
| Objective与UI核验 | Objective52成员ZIP、完整源/锁/前后guard、全部PASS集合；UI两份完整日志及8份gateway JSON | 仅原组件与入口夹具；不签发Root/Current/独立FinalUse |
| B11 native13因果复核 | 宿主Neither前提已修正；strict与legacy ParentOnly/Both仍物理删除，whole147P/7F/2I | 有真实产品权限缺口，维持OPEN；未用诊断通过替代权限接受 |
| 方向与台账修订 | 保原23项退出原文，仅B23按两条同源接受链闭合；主93job最终切面、七head窗口和历史main92分别记录 | 其它22项分类不变，旧历史原件不改写，全部blocker仍未闭合 |

cargo-deny留存修补#4922已产生完整失败原件：新job127715564317唯一unmaintained错误是pin-utils0.1.1 / RUSTSEC-2026-0441，原命令exit1，留存与source/clean成功。原job127679861307的具体原因仍UNKNOWN，不以新日志回填。

## 2. 固定来源与实际发布关系

| 角色 | 实际head | tree | base / parent与状态 |
|---|---|---|---|
| 默认main | 732e934ba496d90fbe042b8d41d479ef901643e5 | 75dc1c1f65375c97da259d947c465a04f030461d | parent f8c9419df6ddeb36ff8b522a50219981fb8d9345 |
| 主修复PR4797 | 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed | 3982ba56dc5a3f1da0c1de7ea57992f88125c359 | 实际base integration/ui-objective-20261103-product /63652be6；Draft |
| Windows权限诊断PR4884 | daa21e7a6a9b19e74b61c6bbdc2c813f9fd35a42 | fbaf12d56a9702d927ae6f71cb9f3abc0cf31cae | base fix/r3-original-product-contracts-20261104 /67cc；Draft |
| Intel PR4902 | 84cc73453eb926d6f2c5b0372c0287b0ab86ed53 | 45858bc96c0edbc366ec77991646b15971129975 | parent ebd31e2b；merge285d5727；base67cc；Draft |
| GNU PR4910 | 2ac89eaf91306d410ef5e9b548ee9fabd12b71b7 | 9a6fd02aa18b2421f6aaec8a5db6ecf82b710c89 | parent e63ed76c；merge652ff4a8；base67cc；Draft |
| 原因链/格式PR4913 | 18bbef4f61c6086f145bdb6f7acbf82127741a14 | d611fe969ecada41618b8feb19f688565b301063 | parent340fbc06；mergeeefd4467；base67cc；Draft |
| cargo留存PR4922 | 476653f8fe5874849e864ab3fd49c792913450ab | 06c4e2f80884b169e31d8a5edf04438486a9ee81 | merge825779c5；parent/base67cc；Draft |
| arg0 clippy PR4923 | 3c9e2bba4e7e84616509d6320a9ae013a274532c | e60df9b57046df73cc1af53d8773cff48eafd311 | merge65e1ec71；parent/base67cc；Draft |
| PTY排空候选PR4927 | 8075eb367b6e97546af206b27bbf4a3a867497c8 | c1249a173ac346d0f1230fe56451b97d4e13c601 | mergeb88f625a；parent/base67cc；Draft |

这些支线未合入主产品或默认main。主修复的实际merge preview b7a57dbb与source67同tree3982；原产品完整10582叶固定。Intel/GNU只改变各自诊断工作流，Windows原因链保持10580个其它叶不变。audit分支只发布证据、报告和入口指针，不将产品代码更改并入审计树。

## 3. 全量元数据口径修正

03:31:39–03:35:10 UTC直接REST连续36数据页加第37空页，共3555不同开放PR：3506 Draft、49非Draft，360个以main为base、3195个非main，共2220不同base ref，全部head来自同仓。首末成员和次序稳定，但#4907末锚的head、merge和updated_at变化，第一次观察与后来值同时保留。

03:42:06–03:43:26 UTC分支完整遍历前53页各100、第54页33、第55–58页为空，共5333名称/4946 commit SHA，API仅main标protected。首、末、空页锚原正文相等；没有重新检查每个中间ref，保护flag也不等于ruleset审计。名称前缀88类不是commit祖先跨度。此窗口之后创建的分支另见发布回执。

旧1103 PR全部在新3555清单中，但2452差额中2364条的更新时间已早于旧上界，仅88条创建于其后。旧actual摘要已完整读回，声明相同查询参数、连续页与空终页；未重开旧原始分页归档，来源差异原因仍UNKNOWN。旧1103/5193作为历史观察保留，不解释为当天新增2452个PR。当前B01接受这两份完整新清单的限定范围，不把元数据当成产品完成率。

## 4. 当前CI与原生证据

### 4.1 最新主候选完整93 job切点

05:20:01–05:21:49 UTC为最新完整主67观察窗：19runs=11success/6failure/2skipped；93个不同job=68success/9failure/10cancelled/6skipped，无排队或执行中。逐run的jobs实取数与total_count相等。Rust required127704207208现已success；新增失败仅总汇CI required127712699481。9个failed job是原7个执行失败加Windows汇总与总CI汇总，不是9个独立根因；原失败和历史切点均不改写，也不按68/93计算项目完成度。[最新七head切点与原件](reviews/root-followup-publication-native-20261106/registry.actual.json)。

### 4.1A 历史92 job与六份官方ZIP

04:10:12–04:13:40 UTC完整19runs/92jobs：runs为11成功、5失败、2跳过、1排队；jobs为67成功、8失败、10取消、6跳过、1排队，0执行中。各run jobs的total_count与实取数相等；唯一排队job为Rust required127704207208。blocking run-list的queued与其36个job内真实失败同时保留，窗口不是原子快照。8个failed job包含Windows汇总127691446306，只有7个执行失败job，不能当8个独立根因或按67/92估算项目完成率。

五个新失败的完整原log和官方ZIP已经取得：Intel PTY30P/1F，Core第一次startup delivery timeout后原默认retry通过；Windows Queue35P/1F在等待queue_blocking_prompt_hook.entered时到deadline；Windows sandbox两段总139P/13F/2I，保SetSecurityInfo/ReOpenFile error5、token边界、错误链和6个poison后续错误；GNU clippy两处expect_used造成3个Clippy action失败；MacARM holdout114P/1F（Busy≠Rollback）和HTTP84P/1F（WouldBlock35/ConnectionReset54）。这些观察没有被改成更深层根因。主67 sandbox与B11 native13 daa的147P/7F/2I是不同source/前提，不混为一次执行。

第六份ZIP与完整原日志是成功的主GNU job127679861926，供B23最终原CI独立接受链。六ZIP共377原成员，归档155成员恢复后共532文件，全部199payload及registry已实际GET相等；5离线重放stdout精确等于冻结原件。临时签名下载URL响应不进入Git。新增选定失败目标14实际启动与14辅助XML分开计；本次Intel retry XML还有一处与compact复用旧digest不匹配，原ZIP保留真实字节，不声称全部XML与compact相等，也未声称收齐全605目标所有case。

### 4.1B 历史85 job与Windows Core失败包


03:18:59.703–03:19:29.458 UTC为19 runs/85 jobs，逐个total_count与实取数一致。job状态为55成功、2失败、9取消、5跳过、10排队、4执行中；run状态为10成功、5失败、2排队、2跳过。blocking run尚queued而子job已有失败，两个层次各保原值。相对历史58 job新增27个，无删除，12个既有job转成功；02:44的23 job只覆盖四个run。

两个原失败为cargo-deny127679861307与Windows shard4/4 127679861687。Windows实际checkout b7a57dbb/tree3982，原Bazel退出3、clean通过。Core的16shard包含21次实际tw.exe测试，另有21次XML生成；全部测试local/noncache、900000ms，6失败尝试和15成功。第7shard三次各70P/3F/5I；第4/6/13首次helper program not found后原重试成功。五个后续XML与compact复用digest不等，已明确披露；官方ZIP及完整manifest保留所有原42个log/XML。包中PTY为cached，不是新执行证据。

deny-read报告仅给apply deny-read ACLs；状态读取/解析/写入与实际ACL调用仍不能区分。read-grant mutex发生在该错误之后，没有证据将它认作本次根因。protected metadata测试在允许文件readback时先因os error2失败，三组受保护目录断言未到达；hardlink原例先遭helper启动失败，不能宣称物理逃逸。

cargo-deny安装前置与clean步骤成功，但原Run步骤失败；whole-job日志三次分别返回Transport closed，现有6项artifact没有deny报告。实际退出码、该job完整checkout和依赖问题类别均UNKNOWN。已知的是原工具0.19.0、toolchain1.95.0、原单次命令与30分钟预算，不能借用Windows checkout或随意调整依赖规则。

### 4.2 Objective与UI新增接受

Objective原GitHub任务完成Memory327P/8skip、Agentd242P/1skip、desktop-feature247P/1skip。全部实际名字、JUnit与原日志可对账，后两组重复242个定义，不能称816个独立用例；JUnit缺skip名字不等于0skip。52成员原ZIP、官方摘要、完整10582叶、17锁及12命令前后守卫均核实；根异目录只读重放116203字节一致。

UI source/base-merge两个job各nextest88P，gateway四组9/5/12/2P并保31/35/28/38过滤或跳过，其余libtest/browser/TAP按组保存，不累计独立总数。八份gateway JSON有source/base/tested-source与前后clean，无timeout或output-limit。这些是GitHub jobs1/dev-small或指定UI夹具；不能替代私有主机32GiB/jobs4默认full、真实Root/Current/FinalUse或独立目标效果。

### 4.3 权限与平台诊断边界

B11 native13：宿主Rust/CMD的Neither拒绝、其余三格允许；strict Rust与legacy CMD的ParentOnly/Both仍实际删除，原断言失败。whole147P/7F/2I包括两个矩阵、一项broad strict与四个poison后续错误。四个原正控、物理负控、精确还原、21helper/11pins保持。当前token工厂没有对象路径/操作参数，现证据未找到同时保全ambient read、inside I/O与全部outside拒绝的局部产品修复；不推广成Windows所有机制均不可能。

Intel单target native1在真实Intel原平台31P，原30名均在，darwin-sandbox/noncache已核。旧4MiB drain用2.023066511秒超原2秒，reader字节/errno/充分因果未知。完整上下文native2 job127685180579实际30P/1F，portable wait2.01948407秒、read=discard1,827,840字节；main原Intel job127679861660另一次30P/1F，wait2.228741523秒、read=discard3,358,720字节、6,549次read、errno35、child仍python_started且未退出。两组观察分开；不由partial drain推断FD泄漏或松动原2/5秒。B21继续OPEN。

旧收件器在B21拒绝一次合法重复Fetch并缺131XML，在B23拒绝两次重复Fetch并缺8XML，全部保留。新共享collector ee1b8287已静态独审并实际发布到两个诊断支线，原36+9新增控制和11privacy检查通过；18个原函数/类逐字节保持，无产品叶变化。它要求原log/XML物化，未合成XML或豁免缺件；新源实际物化接受仍待自动CI。发布不回填旧139份缺件，也不等于原测试通过。

Windows原因链PR4913仅修可观测性：分类错误保持code/message，未分类输出保全原因链，原sanitizer/ACL/断言/预算不变。两项新测试源码有真实文件写入读回；本机just fmt、just test实际均exit127，无cargo/rustfmt，不能称Rust通过。历史03:55首切尚无Windows构建/测试job；04:41:40–04:43:11切面已观察到原Windows clippy/release成功，不能继续称没有编译观察。两个新cause用例在340源原log/XML各一次PASS，tw.exe实际local/noncache、300000ms；库整体141P/13F/2I。完整43+93成员官方ZIP与两原日志已实际登记，20个测试/20个XML动作中17份首次或单次digest匹配，3份重试compact复用旧digest，限制明确；Core19次中4次失败。EOF只在一attempt被打印为日志与返回错误两行，不扩成两个原因；SetSecurityInfo error5另列。该结果不转授后续18格式源。[固定340原生包](ci-audit/windows-setup-causes-native-20261106/registry.actual.json)。随后实际发布18bbef4f/treed611fe96/mergeeefd4467，parent340，仅落实原formatter给出的setup_error.rs两hunk（一个leaf）；其它10581叶不变。旧340的两PASS、clippy/release与任何其它native结果均不转授新18。隐私结论限定于既有错误输出通道，不宣称任意错误信息绝无敏感内容。

### 4.4 B23原范围闭合：fresh与最终原CI两链分开接受

原baseline丢信号窗口及修复5例的历史接受继续保留，本轮没有重新取得旧raw。fresh GNU诊断run42155150876/job127687422035的source e63ed76c/treea6831e26剥唯一workflow后精确等于原3982，14pin与前后完整tree/clean成立。8个实际remote/noncache测试分片在Linux/amd64完成307P/0F/1I；3个first_sigterm/sighup/sigint父例和2个drain均PASS。唯一ignored retained_signal_child由父例启动，不转成独立缺失验收；stdio/disabled与非Unix原语义保留。

最终原CI来自main67 job127679861926：完整605目标原GNU任务success，其AppServer unit 8分片cached，不称该job新鲜执行。两链逐分片argv/env/platform、规范化输入/工具图及同一457,661,280字节程序SHA256相等；16个原log分别与自身compact的输入digest精确绑定。但8组log与action-cache digest均不同，main先完成，不称main缓存源自这次fresh诊断。

诊断原Bazel exit0，而job仍因重复Fetch及8缺XML为failure。原B23退出没有XML上传、cache=false或后来collector全绿要求，因此不追加新门阻止其原产品scope闭合。独审2dd76784和根逐字重放两checker（108,070/13,052字节）均通过，仅B23改为CLOSED_SCOPED；B15/其它平台/收件器缺件各自保留。此前独审标PENDING的原件持久化已由main92 d59627c4和三诊断ZIP registry411b8e48连上，旧回执不改写。

### 4.5 最新七head与历史三修补分支切面

05:20:01–05:21:49七个head共46个run各自完整jobs原件已登记。除主93外，cargo为41jobs=27S/6F/6skip/2Q；arg0为43jobs=29S/4F/6skip/3Q/1running；B21 collector为9jobs=3S/2skip/2Q/2running，B23 collector为9jobs=4S/2skip/1Q/2running；Windows格式18源为7jobs=3S/2skip/1Q/1running；PTY新修补8075源为12jobs=2S/2skip/4Q/4running。这些是按head分开的非原子API观察，不相加为独立产品用例或替代原生资格。

GNU clippy原两处expect_used的最小修补已发布Draft PR4923：head3c9e2bba、treee60df9b5、merge65e1ec71、parent67。原成功/错误分支与断言合同保持；最新原GNU Clippy job127717742578已success，完整863,099字节日志绑定该merge，报告26,119 actions成功且check-clean通过，repo-checks127717742170亦success。该原门已接受修补；没有据此声称所有动作新鲜非缓存或整库通过，其余平台失败仍保留。[源码独审与实际出版](ci-audit/arg0-clippy-independent-20261106/registry.actual.json)、[原Clippy日志与最新切点](reviews/root-followup-publication-native-20261106/registry.actual.json)。

针对实际drain失败，独立产品修补Draft PR4927已发布head8075eb36/treec1249a17/mergeb88f625a，parent/base67；原期限、断言与失败历史保持。05:20–05:21其12jobs仍有4queued/4running，尚无新源终态资格，B21继续OPEN。实际发布原件已收入[root补充包](reviews/root-followup-publication-native-20261106/registry.actual.json)。

以下04:41切面是历史原值：

04:41:40–04:43:11 UTC完整分页：cargo留存head476为3runs/34jobs=5S/1F/5skip/20Q/3running；arg0 head3c9为5runs/10jobs=2S/2skip/6Q；Windows原因链head340为5runs/42jobs=25S/6F/6skip/4Q/1running。它们不替代main67的92job分母，三分支也尚未整合。cargo新原件已经指向pin-utils unmaintained，arg0修补只去掉实际两处expect_used，Windows原生cause测试按自己的原件核验；不能从API数量推出测试case数或整库资格。

## 5. 剩余6项开放与1项科学保留的下一门

| ID | 还缺什么 | 已准备或下一项实际交付 | 何时可以关闭 |
|---|---|---|---|
| B02 | 固定整合候选的全部原始必需CI与逐路径整合接受 | 按main93终态与历史原失败及已发布支线逐路径收口；source/base/merge/锁绑定 | 原required全部成功，最终单一候选固定 |
| B11 | strict/legacy在ParentOnly/Both真实拒绝外部删除 | 可审的对象/操作授权机制，保ambient read/inside I/O、四outside变更及后代寿命 | 原攻击/权限/文件系统用例全过，合法I/O不退化 |
| B15 | 最终required、原Linux full及实际发布树资格 | 修复cargo新advisory、clippy及平台失败；保原全部失败与有效负控 | 原CI终态全成功，发布/merge同树；不以支线、queued或单scope替代 |
| B16 | 旧driver确定身份及真实Root/Current/issuer/普通UI到provider/target接受 | 原key归属与终态；按R1–R6依赖整合authority材料及caller | 同源任务、取消、丢ACK、重启与物理效果/Memory回执全实得 |
| B19 | Bao/Chain/HIA各自真实consumer；Chain精确paired native/binary来源 | 固定Hepta09de43ba×Chain254033da双端49,508B路径，执行原配对验收 | 版本/兼容/故障/安全和真实调用者全部接受，development fixture不转production |
| B21 | 原Intel完整drain/child/FD在原期限通过及失败因果 | 利用两个partial drain原件定位边界，原2秒/5秒与默认retry不变 | 原30例及相关原CI通过，并解释实际失败原因 |
| B18 HOLD | 新预注册2×2、D−B独立未来数据、充分精度和全部失败成本 | 独立科学计划，保持强普通默认 | 原科学采用门实得，不能由移植/复用确认集改绿 |

B23已经按原退出完成限定闭合，不再列成待验blocker；相关源码变动按影响重验，whole B15与新收件器原件要求另管。原Linux默认full清单19563（19506eligible/57ignored）和准备入口已有，唯一首次尝试在编译前被原32GiB RAM门拒绝。原64GB磁盘/32GiB RAM/jobs4不降；没有新容量依据不重复查询或发起。B16第三次同key超时后仍无job身份，2463份五字段metadata不足归属，不作第四次或改key重放。

## 6. 发展方向与推进次序

1. **先取得可交付的跨平台候选。** 按新cargo unmaintained原件、实际clippy和Windows/Intel/Queue/MacARM失败收口修复；维护已闭合GNU原范围，完整保留所有失败与重试。最终以同一source/base/merge的required资格为准。
2. **打通一条真实正常产品路径。** UI/API→Objective→有界Memory→Agentd→Codex→可观察、可取消、可恢复的效果。Codex负责session/thread/turn与模型工具，Agentd负责装配及生命周期，优化模块不能扩大authority。
3. **再扩规模并测资源。** 64/256/1024/4096首先是逻辑Cells规模；分别测实际活跃数、CPU/RSS、队列年龄、尾延迟、质量、token和完整成本，不以模块数代能力。
4. **学习与可塑性按独立采用门推进。** 固定预算shadow、只读因果验证、模型/参数迁移与可回退采用，B18坚持原D−B。工程可塑性、具身及外部系统后续各有真实consumer接受。

各阶段以实际前置结果推进，不按CI排队时间承诺日期。最先完成的可审交付物是诊断修补与对应原件；完整产品与科学门仍按上表逐项接受。

## 7. 证据入口与历史保留

本轮已登记证据清单当前为1536条路径、1431个不同blob；这个数不含本轮新报告、索引自身、入口指针和后续实际发布回执，也不是测试数。全部payload按其实际Git身份收件；根完整GET了各新增registry，逐payload完整GET由各包实际回执证明，未声称根逐个重新下载全部payload。

- [全量PR元数据](repository-metadata/open-pr-census-20261106T0331/registry.actual.json)、[全量branches](repository-metadata/branches-census-20261106T0342/registry.actual.json)、[旧计数差异窄补审](repository-metadata/open-pr-census-20261106T0331/OLD_SUMMARY_REVIEW.json)。
- [最新七head CI、四次实际发布、cargo完整失败与arg0原Clippy成功](reviews/root-followup-publication-native-20261106/registry.actual.json)、[B23根最终限定接受](reviews/root-followup-publication-native-20261106/ROOT_B23_ACCEPTANCE.json)、[Windows两个cause原生限定包](ci-audit/windows-setup-causes-native-20261106/registry.actual.json)、[arg0源码独审与实际出版](ci-audit/arg0-clippy-independent-20261106/registry.actual.json)。
- [历史92job/六原ZIP完整包](current-head-ci/main67-20261106T0410/registry.actual.json)、[历史85job/Windows原失败完整包](current-head-ci/main67-20261106T0319/registry.actual.json)、[历史58job切点](current-head-ci/main67-20261106T0201/registry.actual.json)、[02:44四run增量](current-head-ci/main67-20261106T0244/registry.actual.json)。
- [Objective原件](ci-audit/objective-owner-main67-terminal-20261106/registry.actual.json)、[Objective根重放](ci-audit/objective-owner-main67-terminal-20261106/ROOT_VERIFICATION.json)。
- [B11 native13根审](generated-evidence/b11-pr4884-ci/terminal/probe-127639593751/ROOT_VERIFICATION.json)、[Intel native1根审](reviews/b21-original-intel-terminal-20261106/ROOT_VERIFICATION.json)。
- [Intel v2完整源码与独审](reviews/b21-full-intel-v2-rebuilt-20261106/registry.actual.json)、[GNU完整候选](ci-audit/b23-linux-full-appserver-candidate-20261106/registry.actual.json)、[两个PR根发布核验](reviews/diagnostic-root-publication-20261106/ROOT_VERIFICATION.json)。
- [Windows原因链独审](ci-audit/windows-setup-error-causes-independent-20261106/registry.actual.json)、[实际发布](ci-audit/windows-setup-error-causes-pr4913-publication-20261106/registry.actual.json)、[首次CI](ci-audit/windows-setup-error-causes-pr4913-ci-initial-20261106T0355/registry.actual.json)。
- [B23原范围独审](reviews/b23-original-scope-closure-independent-20261106/REVIEW.json)、[B21/B23三原ZIP终态](current-head-ci/b21-b23-original-terminal-20261106T0410/registry.actual.json)、[共享收件器修补](reviews/shared-bep-fetch-xml-repair-20261106/registry.actual.json)。
- [Intel历史第二CI切点](reviews/b21-full-intel-native2-secondcut-20261106T0344/registry.actual.json)、[GNU首切](ci-audit/b23-linux-appserver-pr4910-initial-20261106T0327/registry.actual.json)。
- [旧377路径实际恢复清单](recovery/post46fd-remote-inventory-20261106.json)、[固定Chain双端补审](generated-evidence/concurrent-pr-increment-20261106-chain254-addendum/REVIEW.zh-CN.md)。

审计父树的13122个叶中，只有LATEST.md及LATEST.zh-CN.md作为当前入口更新；其原字节分别留作history/LATEST.pre-v10.md和history/LATEST.pre-v10.zh-CN.md。其它13120旧叶及产品代码保持。旧入口副本内部旧相对链接按原样归档，当前导航以上述新入口为准。
