# 持续审计与实际执行进度 V5

**原23项：8项限定范围闭合、14项开放、1项科学HOLD。整体候选与全部blocker尚未闭合。** 本报告登记新通过，也逐项保留失败、取消、排队、早退和未知结果。最新主候选CI观察窗口为2026-11-05 14:55:04–14:55:05 UTC；非原子快照，不把后续观察写回旧时点。

## 1. 三个独立源码状态

| 状态 | 固定身份 | 当前资格 |
|---|---|---|
| 主产品Draft #4797 | head `5b6331250ff459033bd44d1a95daec70131277cc`；tree `b26598d0d97d8d51e723bb5582137315f2174d35`；base `63652be658ebed8d3052eb789b951793384fd5e4` | 新跨平台selected结果通过，但原Windows Core、musl失败；全量/最终平台门未闭合 |
| 下一份Core＋musl候选 | tree `e78c819b8b1f435f8b37bea17b4ffdc724961aa2`，在5b上精确两路径 | ROG编译/metadata/catalog完成；owning和同进程parallel非通过；尚未完成full与hygiene，未推到主产品PR |
| 独立B11诊断Draft #4884 | head `f02b9ae98e8608210c92a3f53646147f5c7dc428`；tree `fc47759c145d33122b3cab70235a617661556db8`；base5b | 实际发布3commits/4paths/+605−0，原Windows target工作流已触发；native结果待验 |

两个Draft的用途与资格分开。诊断PR只新增测试观察与独立job，生产token权限、原严格断言和原预算未修改。e78和B11没有互相拼接成一个已通过候选。[源码与发布核验](reviews/b11-diagnostic-draft-publication-v1.json)

## 2. 主候选CI：新增实际结果

本次完整快照包含19个workflow run、59个job：**40 success、2 failure、2 skipped、1 cancelled、14 queued**。run顶层仍有4 queued；内部job可以已执行或终态，不能从run状态推断内部状态。主blocking的scope/blob初始job仍排队，Codespell已成功。此前完整branch-run分页和DAG/labels检查未证实并发死锁、environment等待或其它具体队列根因，没有取消或重跑来替换原记录。[完整原API观察及根审重算](generated-evidence/current-outcomes-cut0063-v6/scope-summary.json)

| 已取得实际正文的范围 | 原始结果 | 不能据此扩张的资格 |
|---|---|---|
| Windows recovery source5b / merge9063 | 每份13resume＋121rollout＋254exec-server＝388不同名字PASS；resume原范围排除35项单列 | 不代替Windows strict token或全部平台；该范围与冻结142退出名交集0 |
| GNU recovery source5b / merge9063 | 每份13＋125＋379＝517不同名字PASS；62项范围排除；实际proxy CONNECT通过 | 不是unfiltered full；与142交集0 |
| macOS ARM recovery source5b / merge9063 | 每份13＋125＋383＝521不同名字PASS；76项范围排除；实际CONNECT通过 | 是ARM，不能替代Intel PTY；与142交集0 |
| Windows Git/Queue source与merge | 每份35Gitutils＋1次重复嵌套执行＋36Queue＝72次执行、71不同名字；原B13 Queue八名PASS | 第九个Agentd qualification未被选择；不能把两份结果相加成独立测试总数 |
| Windows private directory | 原53名PASS、两项有效冻结负控与精确恢复 | 补B12原范围，不能补B11外部delete拒绝 |
| Objective source5b | Memory327、Agentd default242、desktop feature247＝816次配置内出现、574个不同名字；选中JUnit无失败/跳过 | 默认与desktop重复242名；缺qualification-cognitive-write、真实生产caller、独立Root/provider；控制台另有未具名早退/跳过限制 |
| UI native source/merge | 28＋31＝59次配置内出现、31定义；Python原JUnit门12 | 不是实际桌面GPU、真实IME或Root/provider验收 |
| UI browser source/merge | Playwright6/9/1、status7、HTTP60/36、gateway2/5/12/9等按原组保留 | 1745引用文件中只回读12份，1733未下载；synthetic WASM/CPU/CJK/IME明确appQualified=false |
| Intel V8 release/sandbox | 各6项smoke实际通过；no-default-features、无Skipping | 大型发布资产未独立回读，不替代其它平台 |
| Windows x86 V8 | 上游release build与产品`cargo test --no-run`链接成功 | **0个产品Rust用例执行**；artifact ZIP尚未独立回读 |

以上每份source/merge的实际checkout分别绑定；UI native/browser merge有各自合成commit但相同b265树，不能一律写成9063。原失效、额外attempt、cache、skip/early-return分别保留。根审独立打开五份GNU/macOS ARM/Objective ZIP、96个内部文件并逐个复算JUnit名字；完整归档验证不等于已取得归档之外的资产。[根审JUnit结果](reviews/v6-unix-objective-root-review.json)；[recovery/UI范围](generated-evidence/ci-5b633-recovery-ui-v6/scope-summary.json)；[GNU/ARM/Objective范围](generated-evidence/ci-5b633-unix-recovery-objective-v6/scope-summary.json)

### 保留的失败与取消

5b原Windows Core正常8分片共2343不同用例＝2339PASS＋1FAIL＋3ignored，唯一失败是blocking snapshot原父子span断言；更早isolated四例全过不能覆盖此失败。musl原任务在`parent_lifecycle.rs`比较`f_type`的u64和`PROC_SUPER_MAGIC`的i64时编译失败，未到ELF/CLI/smoke。

Windows ARM V8 job127251874931在上游`cargo +1.91.0 build --locked --release --target aarch64-pc-windows-msvc --features v8_enable_sandbox`阶段取消，原正文只有“The operation was canceled.”。stage、产品Cargo smoke、upload均SKIP，0产品测试。约120分钟与预算相邻只是时间关系，尚无原文证明取消actor或根因；没有把取消改称编译成功或主动重跑。[完整观察原件](generated-evidence/current-outcomes-cut0063-v6/transport-manifest.json)

## 3. Core隔离与musl修复：已实际推进到失败边界

Core候选保留原3621字节测试主体与全部三条日志链断言，原5秒inner预算不变；原父测试仍在正常测试清单中，用本binary的精确单例owned child隔离进程级tracing状态，增加5秒父总预算、完整原输出、精确单例/结果校验和自有子进程清理。此前六行Dispatch方案因仍有interest-cache竞态已拒绝晋升。固定tracing机制的实际负控exit101、正控exit0证明机制可达；原Windows失败的具体调度交错仍未被直接观察。

musl候选只把两侧转换到i128作无损比较，GNU的i64与musl的u64均完整保留；未改procfs校验语义、权限或失败处理。GNU通过不能代替实际musl编译与smoke。[候选源码绑定](candidate-next/core-musl-initial-source-binding.json)

ROG原任务`1a1ac0281fa-fc05-519e`已终态failed1、output_complete；不存在timeout或自动重试。实际顺序和结果：

| 阶段 | 原结果 |
|---|---|
| 七个原normal helper构建 | exit0，191.735秒 |
| 完整metadata与原project catalog | 分别exit0；catalog 3977项 |
| owning项目原运行 | 3967执行＝3962JUnit PASS＋5FAIL；10ignored；exit100，42.981秒 |
| Core同进程原并行libtest | 2432PASS＋1FAIL＋1ignored，0filtered；exit101，26.300秒 |
| full / fix / fmt | full OPEN；hygiene NOT_STARTED |

隔离的原snapshot用例在project JUnit实际PASS0.078秒，原raw含完整parent/wait链、child与parent各1PASS、start/pass marker各一次；同进程parallel也有child与parent同名ok及两marker。**这是该用例的实际局部通过，整体project和parallel仍失败。** 当前已完整回收原投影、原状态、完整stderr和相关raw范围；29完整原件压缩归档正在回收，此处不把投影当成全raw。[当前完整观察与限制](generated-evidence/current-outcomes-cut0063-v6/scope-summary.json)

五个owning失败全部是原审批/权限用例，和旧fb9失败名单相交：一个审批持久化、四个request_permissions。当前原断言都收到连续三行`Failed to create stream fd: Operation not permitted`；四个业务输出尾分别是`partial-grant-ok`、`sticky-grant-ok`、`sticky-shell-feature-independent-ok`、`sticky-explicit-grant-ok`。未过滤输出或放宽断言。宿主login-profile/im-config链是待验证线索，新的host完整因果证据尚未齐全。

parallel唯一失败是`resume_agent_from_rollout_skips_descendants_when_parent_resume_fails`，在原5秒用户消息记录等待中只见MCP完成和TurnStarted。其默认provider/prewarm静态依赖正在审查；既无thread/needle阶段证据，也不能把邻近401日志当作这次失败的因果。将准备受限于恢复树fixture的本地provider候选，保留真实用户ItemCompleted、原5秒和完整树恢复断言。

最终source guard仍为e78/10580 leaves，原ordinary HEAD/index、双锁、工具和V8输入一致，`final_source_guard_error=null`。ROG终态剩余20,609,298,432B，不满足此前full空间条件；没有删除缓存或降低门槛。

## 4. 独立冷节点：准备完成，编译未开始

ai395只读readiness任务实际succeeded0，171文件/147链接全部按固定输入核验；初始容量充足。这份readiness只做读取，不含构建/测试。

随后独立C0/C1任务`1a1ac1b40d7-fc05-5242`在新owned目录完成固定输入和5b fetch、checkout、两后像应用和整树/工具检查。C1首个helper之前实测MemAvailable＝29,914,468,352B，小于原32GiB＝34,359,738,368B门槛；free237,601,075,200B仍满足64GB空间余量。任务因此failed1，**build_commands为空，0Cargo、0metadata、0catalog、0tests、0hygiene**。

最终源码e78、ordinary HEAD5b、fresh index `b488256c…`、双锁、工具/V8与untracked检查均通过。此结果应记为资源前置阻塞，不能记成源代码或编译失败。后续先做一次只读容量/身份复核，再审具体C1-only续接；不得重跑C0、降低32GiB门槛、清缓存或干预未知进程。C2全量和Agentd三个qualification_原例计划仍disabled。[原终态](native/ai395-core-c0-c1-v1/preparation-terminal.json)

## 5. B11独立物理机制诊断

[Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)只在固定5b上增加三个test路径和一个Windows工作流。完整10583leaf逐项核对，仅1个既有文件追加78字节cfg(test)挂接、3个新增；原生产token全文、strict三例与四格两例保持。原外层Bazel Windows sandbox unit target与120分钟预算保留，原失败exit透传；工作流实际触发run42049112832。

探针对四token主体×Medium/Low outside cohort，记录有效线程token、原对象SD上的DELETE/DELETE_CHILD AccessCheck、真实read/overwrite/create/file-delete/directory-delete。所有对象在新TempDir内，label捕获/修改/核验/恢复使用同一持有handle；恢复、正向控制和八行完整性是fixture有效条件。没有新增outside必须拒绝的假定，也没有用probe PASS替代原严格合同。它不创建子进程，loader、IPC/backend、Job后代与实际产品隔离仍待各自验收。[实际发布复核](reviews/b11-diagnostic-draft-publication-v1.json)

## 6. 原23项与后续顺序

8项限定闭合为B01/B03/B04/B05/B06/B12/B14/B17；14项OPEN为B02/B07/B08/B09/B10/B11/B13/B15/B16/B19/B20/B21/B22/B23；B18保持SCIENTIFIC_HOLD。没有改写任何原退出条件或closure_class。[逐项最新ledger](continuation-blocker-progress-v4.json)

当前执行顺序是：定位并修复真实失败 → owning与原parallel通过 → 满足资源门禁的原full → 需要feature的原Agentd三例 → 原fix/fmt及最终source绑定 → 同一发布head/base/merge的原平台CI → main资格。Windows严格删除机制和B16正常入口接线并行推进，各自保留原接受门。

B16 Foundation已QUALIFIED的24不同正向/27执行、9不同有效负控/10执行、4次精确恢复不变；旧driver三次同key请求后仍START_OUTCOME_UNKNOWN，没有第四次重放。新Core节点任务不解决旧driver身份。Root checkpoint和Memory连接复用候选只有静态资格；真实Root/Current、独立issuer/signed objective、normal UI caller、provider/target仍是具体接受缺口。B18未通过的D−B科学门及B19外部接受也不能用工程绿色替代。[项目方向与具体计划V3](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V3.zh-CN.md)

## B11原生编译增量与已发布纠错

初始诊断headf02b9ae的真实Windows job127320081049于14:56:49结束failure：既有`unified_exec/delete_permission_tests.rs`有8处`assert_eq!`宏导入歧义E0659，测试尚未开始。原完整log和11成员ZIP保留。修复只新增同一`pretty_assertions::assert_eq`显式导入，删除该34字节行即逐字恢复原文件；八条断言、生产权限与预算不变。workflow另增加该既有文件的触发路径，保证纠错实际进入同一原目标。

纠错已发布至同一Draft #4884，第4commit **`0d65de9bf1e28a7b313a344ebba71ba8378d0f5a`**，tree **`f13680916b9a7f773dcc95e4ce6ee6785021ead4`**，相对5b总5路径/+607−0。fresh PR/ref读取已确认，主#4797未变；新的原Windows结果待取得。上文初始4路径/3commit/排队状态均为其明确历史阶段，不代表最新head已通过。[纠错精确发布收据](reviews/b11-macro-correction-publication-v1.json)
