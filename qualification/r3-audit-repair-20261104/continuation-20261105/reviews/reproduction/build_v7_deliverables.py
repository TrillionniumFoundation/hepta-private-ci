from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import copy
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'hepta-audit-fifth/v7-deliverables'
OUT.mkdir(exist_ok=True)
V6 = ROOT / 'hepta-audit-fifth/v6-deliverables'
HEAD = 'eed4d6bb61b789b19f60facc79f9e031765fa4c9'
TREE = 'ca1c4671ef6b2773280d01b5d76c6166252f5856'
MERGE = '3476a8c535f7090c4c868ac85148491b3fdfd983'
BASE = '63652be658ebed8d3052eb789b951793384fd5e4'
PREFIX = 'https://github.com/TrillionniumFoundation/hepta-private-ci'
old = json.loads((V6/'continuation-blocker-progress-v4.json').read_text())
ledger = copy.deepcopy(old)
ledger.update(schema='hepta-continuation-blocker-progress-v5', recorded_utc=datetime.now(timezone.utc).isoformat(),
              original_23_status_exit_and_closure_class_unchanged=False,
              original_23_ids_and_exit_conditions_unchanged=True,
              all_blockers_closed=False, whole_candidate_qualified=False,
              counts={'CLOSED_SCOPED':10,'OPEN':12,'SCIENTIFIC_HOLD':1})
ledger['prior_product_v6'] = ledger['product']
ledger['product'] = {'pr':4797,'draft':True,'head':HEAD,'tree':TREE,'base':BASE,'merge':MERGE,
                     'merge_tree':TREE,'parent':'5b6331250ff459033bd44d1a95daec70131277cc',
                     'exact_changed_paths':14,'leaf_count':10582,'whole_candidate_qualified':False}
ledger['closure_transitions_v7'] = [
 {'id':'B22','from':'OPEN','to':'CLOSED_SCOPED','scope':'Original Windows TUI13 on5b/merge9063',
  'root_receipt':'reviews/b22-original-windows-closure-root-verification-v1.json','actual_git_blob':'0e60a44c0bd703461de322e80464f9969c71602c'},
 {'id':'B13','from':'OPEN','to':'CLOSED_SCOPED','scope':'Original Windows Lease/Queue9 on5b/merge9063',
  'root_receipt':'reviews/b13-original-windows-closure-root-verification-v1.json','content_git_blob':'1477f09e7d1d4fb8f73910252b4c91fa55193164'}]
for item in ledger['items']:
    item['prior_latest_continuation_v4_zh'] = item.get('latest_continuation_zh')
    if item['id']=='B13':
        item.update(status='CLOSED_ORIGINAL_WINDOWS_LEASE_QUEUE_CONTRACT',closure_class='CLOSED_SCOPED',
                    current_label_zh='原Windows九例合同已闭合；新整合树资格另验',
                    latest_continuation_zh='根独核三个完整ZIP共74成员、7固定源、原九名完整正文和负控。Queue source/merge各8名PASS；原Bazel Agentd qualification目标3PASS，含精确第九quarantine原例。真实30秒lease/guardian/release0/单发送/恢复不重放不变。默认Cargo缺feature不否定显式Bazel原执行。',
                    next_closure_gate_zh='保留该原Windows固定源scope；新eed全平台/B15及真实产品入口分别验收，不重复旧三例凑数。')
    elif item['id']=='B22':
        item.update(status='CLOSED_ORIGINAL_WINDOWS_TUI_13_CONTRACT',closure_class='CLOSED_SCOPED',
                    current_label_zh='原Windows13例TUI/interrupt/shutdown合同已闭合',
                    latest_continuation_zh='根独核原20成员ZIP、13名各一次PASS、6固定源、真实stdout就绪/同turn顺序/5秒与历史有效负控。完整TUI3775PASS6原ignored、Queue36PASS；B22所选13无ignore。原Bazel重试策略保留，不冒称retries0。',
                    next_closure_gate_zh='维护该已达scope；最终eed完整平台与main资格继续归B15。')
    elif item['id']=='B02':
        item['latest_continuation_zh']='主Draft已实际推进5b→eed，完整10582leaf仅14path变化；实际merge3476与head同ca1tree。7Rust路径修复与7库存包装路径逐项审核，锁和原工作流不变。全部required及main接受仍OPEN。'
    elif item['id']=='B11':
        item['latest_continuation_zh']='原native4真实140PASS13FAIL2ignored、8完整机制行；strict仍可外删，Low对另一Low对象仍可删。4ACL/1strict/1host前提/1旧错误文字/6mutex poison分类保留。4路径ACL候选已发布7e/tree3de，实际merge582f/tree1718含主eed14path，待原Windows目标；B11仍OPEN。'
        item['next_closure_gate_zh']='先读取7e原完整Windows目标，逐个原失败判定；完整限制令牌还须正常有限read根、同步授权完成与全部后代资源寿命，真实loader/合法I/O/外部四种写删/取消接受。'
    elif item['id']=='B15':
        item['latest_continuation_zh']='新eed19workflows已触发；固定0004快照53jobs=9S2skip36Q6running，另更新另记。原生ca1 full唯一firststart在原32GiB内存门前拒绝，0sourcechange/0build/0test；全量/hygiene未完成。旧5b失败、取消与新head状态分开。'
    elif item['id']=='B16':
        item['latest_continuation_zh']='Foundation既有限定scope保持；旧driver三次相同start超时仍无可归属ID，UNKNOWN且不重放。R1首16metadata不含key/argv不能解身份。R2f1/Memory候选与Current/FinalUse/normalUI缺口保留；新并行#4855材料只作可核donor，未转授本候选资格。'

assert Counter(x['closure_class'] for x in ledger['items']) == ledger['counts']
assert [(x['id'],x['original_exit_condition_zh']) for x in ledger['items']] == [(x['id'],x['original_exit_condition_zh']) for x in old['items']]
ledger['historical_ci_latest_observation_v6'] = ledger['ci_latest_observation']
fresh = json.loads((ROOT/'research-audit/published-eed4d6-ci-20261105/snapshot-0004/summary.json').read_text())
ledger['ci_latest_observation']={k:fresh[k] for k in ['collected_from','collected_to','run_count','run_status','job_count','job_status','head','base','draft']}
ledger['ci_latest_observation'].update(snapshot='0004',non_atomic=True,job_total_can_expand_after_predecessors=True,
    business_qualification_not_inferred_from_job_success=True,
    original_archive='generated-evidence/v7-main-windows-publication-cut0004/transport-manifest.json')
ledger['historical_b11_diagnostic_PR_v6']=ledger['b11_diagnostic_PR']
ledger['b11_diagnostic_PR']={
 'number':4884,'draft':True,'head':'7e0b2303ed0242d83bf56202e8ffb17f5c856186','tree':'3de59a6aa185b13c8758bff3e8fbc530edcef307',
 'actual_base':HEAD,'actual_merge':'582f5315f4f632444ae3782d9381f69ed1ae555d','actual_merge_tree':'1718e3e2235b875320f366d03cf796e2a4e92281',
 'parent':'3a407dde2727de2176b02d3cb2c3883fbb771f60','new_changed_paths':4,'additions':15,'deletions':8,
 'whole_target_run':42066891449,'whole_target_job':127383345954,'initial_status':'queued',
 'status':'B11_OPEN_PENDING_ORIGINAL_WINDOWS_VALIDATION','source_receipt':'reviews/b11-acl-four-path-publication-v1.json',
 'native4':{'run':42058186727,'job':127352234293,'PASS':140,'FAIL':13,'ignored':2,'probe_rows':8,
            'classification':{'ACL_API':4,'strict_outside_delete':1,'ordinary_host_prerequisite_before_token':1,'legacy_error_text':1,'mutex_poison_followons':6}}}
ledger['current_core_musl_candidate']['historical_source_scope_only']=True
ledger['current_core_musl_candidate']['full29_original_transfer_complete_at_cut']=True
ledger['current_core_musl_candidate']['full29_original_bytes']=33420419
ledger['current_core_musl_candidate']['root_review']='reviews/rog-complete29-root-verification-v2.json'
ledger['current_core_musl_candidate']['actual_early_return_cases']=25
ledger['current_core_musl_candidate']['actual_original_remaining54_pass']=38
ledger['current_core_musl_candidate']['38_pass_intersection_with_25_early_returns']=0
ledger['native_ca1_firststart']={
 'key':'hepta-ai395-core-candidate-ca1-full-20261105-v1','job':'1a1ac90de70-fc05-5557','host':'ai395',
 'launch_ok':True,'reused':False,'status':'failed','exit_code':1,'output_complete':True,
 'entry_time':'2026-11-05T16:35:47Z','entry_free_bytes':139231227904,'entry_MemAvailable_bytes':25061957632,
 'minimum_free_bytes':64000000000,'minimum_MemAvailable_bytes':34359738368,
 'source_mutations':0,'build_commands':0,'tests':0,'hygiene':0,
 'source_before_and_after':'e78c819b8b1f435f8b37bea17b4ffdc724961aa2','ordinary_HEAD':'5b6331250ff459033bd44d1a95daec70131277cc',
 'ordinary_index_sha256':'b488256c0552f9ff6d6030b3a1738721dec54ffb5d2a2b56d99100943f04ed19',
 'sdk_complete_originals':{'count':3,'bytes_each':151134,'files':171,'symlinks':147,'only_observation_time_differs':True},
 'result_scope':'RESOURCE_PREREQUISITE_REFUSAL_NOT_PRODUCT_TEST_RESULT',
 'delivery_actual_git_map':'5a1a5006f39db00a8bdf8e3185a38e8850752874',
 'next_trigger':'Fresh same-root memory>=32GiB and disk>=64GB plus all original source/index/locks/SDK guards; explicit new continuation identity, never replay the failed key or old unknown B16 driver.'}
ledger['linux_capacity']={'scope':'Five configured Linux hosts at distinct recorded times, not an atomic or permanent availability claim',
 'desktop':'free27,535,761,408B<64GB','rog':'free18,676,203,520B<64GB','ai395':'latest entry MemAvailable25,061,957,632B<32GiB',
 'pocket4':'MemTotal25,739,556kB<32GiB','x230':'MemTotal7,824,912kB<32GiB','available_host_passing_original_gate':None}
ledger['concurrent_project_increment']={'search_cut':'2026-11-05T16:29:33Z','fresh_metadata_window':'2026-11-05T16:40:42Z..16:45:44Z',
 'search_results':18,'own_prs':2,'other_prs_read':16,'scope':'bounded search discovery then exact-head metadata; PR-body claims are not independent native qualification',
 'artifact':'generated-evidence/concurrent-pr-increment-1644-v7/manifest.json'}
ledger['prior_progress_record']='continuation-blocker-progress-v4.json'
ledger['limits'][0]='原23项ID与退出条件逐字不变；B13与B22按新完整原件正式由OPEN转CLOSED_SCOPED，其余closure_class不变。'
ledger['limits']+=['原库存1103openPR/5193branches仅属于03:16–03:24固定时间，不由18条搜索增量改写实时总数。',
 '历史最大211指标为ref名层级/stack-depth，不是已核实commit祖先跨度。',
 '新原Memory真实时钟fixture明确改setup lease为10秒、到期等待上限12秒；不能称所有内部fixture时间预算未变。生产过期规则与原外层目标预算不变。']
(OUT/'continuation-blocker-progress-v5.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')

progress = '''# 全量审计与阻塞推进记录 V6

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
'''
(OUT/'CONTINUATION_PROGRESS_V6.zh-CN.md').write_text(progress)

plan=(V6/'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V3.zh-CN.md').read_text()
plan=plan.replace('项目发展方向与当前执行计划 V3','项目发展方向与当前执行计划 V4',1)
start=plan.index('本计划以主产品5b')
end=plan.index('\n\n## 1.',start)
plan=plan[:start]+'''本计划以已发布主候选 **eed4d6 / ca1** 为执行基准；原canonical五文件仍沿已核固定源逐blob一致。当前23项原blocker为 **10限定闭合、12OPEN、1科学HOLD**，B13/B22的新增闭合由完整原平台证据支持。完整本轮事实见[进度V6](CONTINUATION_PROGRESS_V6.zh-CN.md)和[ledger V5](continuation-blocker-progress-v5.json)。本计划保留原退出条件，并纳入16:40:42–16:45:44读取的其他16条活跃PR来源。''' + plan[end:]
plan=plan.replace('最大祖先跨度211','ref名称层级/stack-depth指标211（不是已核commit祖先跨度）')
start=plan.index('## 2. 当前阻塞的依赖顺序')
end=plan.index('## 3. 23项blocker逐项工作清单',start)
plan=plan[:start]+'''## 2. 当前阻塞的依赖顺序

| 批次 | 当前实际状态 | 下一具体动作 | 完成标准 |
|---|---|---|---|
| A：已发布14路径 | eed已发布、原Windows分支任务有成功，完整门未终态 | 读每个原失败的当前正文，保source/head/merge和原负控；若再失败仅修已证根因 | 同候选原assertion通过，真实到达业务，错误/skip/retry与早退分别可追 |
| B：Linux完整门 | ai395唯一firststart因可用内存不足32GiB停于源码修改前 | 原64GB磁盘/32GiB内存和全部守卫fresh通过后，对同prepared目录明确启用续接；七helper→完整catalog→无筛选full | 原193成员/1501节点、19563目录项一致；原full实际通过、终态源/锁/SDK一致 |
| C：已补原平台证据 | B13九例与B22十三例已正式CLOSED_SCOPED | 保闭合来源与有效负控；新eed资格继续独立收齐 | 不为旧feature缺证再重复3例，不借旧5b结果给新eed |
| D：最终hygiene | 新组合的full未完成，scoped fix/fmt尚未执行 | 所需原测试门完成后scoped fix→fmt；不在hygiene后追加本地测试 | 真实执行回执、最终源/锁/树与原CI一致 |
| E：原平台和main | 19新workflows已触发，required尚未全绿；仍为Draft | GNU、musl、Darwin/Intel、Windows逐原范围取终态；当前main单独重新绑定及审merge | 必需门全通过；目标base、merge、发布commit身份完整；不跳过当前失败 |
| F：Windows严格隔离 | native4证明真实外删；ACL四路径7e已发布待原目标 | 先判ACL实际结果；同步read授权/owner/后代寿命与真实loader能力逐项接线 | 原严格token、合法read/write及外部四种写删拒绝全部通过；原host前提独立成立 |
| G：正常产品入口 | Foundation限定范围达标，旧driverUNKNOWN；Current/FinalUse等未闭合 | 按确切任务身份解决driver；复核donor有用源码/物理控制；继续checkpoint→Current→三池→normalUI | 同源真实Root/Session/签名Objective/provider/target完成、取消、丢ACK、重启一致 |

这些批次以实际前序终态推进。A/F/G可并行准备；B/D/E保留严格前置，资源和runner排队不预报完成时间。现有五台Linux没有已确认满足本批原容量门的主机。主机可用权限不等于产品Current/FinalUse授权。

''' + plan[end:]
start=plan.index('以下原退出条件从冻结ledger')
end=plan.index('## 4. 正常产品入口要完成的接线',start)
table='以下原退出条件从冻结ledger逐字带入。十个限定闭合范围保留其证据；十二个开放项和科学HOLD按明确门推进。\n\n| ID | 当前分类 / 范围 | 下一动作或维护重点 | 原退出条件 |\n|---|---|---|---|\n'
for item in ledger['items']:
    table+=f"| {item['id']} | {item['closure_class']} / {item['name']} | {item['next_closure_gate_zh']} | {item['original_exit_condition_zh']} |\n"
plan=plan[:start]+table+'\n'+plan[end:]
insert=plan.index('## 5. 后续发展阶段与优先级')
newdev='''## 4A. 其他正在推进的项目线与整合边界

下表来自16:29搜索及16:40:42–16:45:44的fresh PR元数据。源码head是实际读取值；正文中的native数字在本表仅作为**作者已记录的进展**，本轮没有独立复核其全部原件，也不转授主候选资格。16条非本轮PR及原搜索响应完整保存，不能用这批结果改写03:16全库人口统计。

| 项目线 / 固定PR | 实际读取head | 发展方向与下一动作 |
|---|---|---|
| W0–W7整合 [#4855](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4855) | `3a39c799a3f776b0aeedfce350341d865d3cc1c4` | 已发展到50个按序source stages，涉及SQLx拒绝提交后的连接复用、issuer-parent、恢复和Windows原CI。正文仍列完整owner/真实UI/外部效果OPEN。按文件和依赖复核可用donor，不整包替换当前主候选。 |
| P0/P1与原CI [#4853](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4853)、[#4843](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4843) | `a3182a76…` / `7504ab32…` | 保其原44失败与图像、OpenSSH、WebSocket、恢复的实际来源；full原平台和干净镜像消费未全部通过。当前#4797只是其部分donor，不能循环借证。 |
| 40模块恢复 [#4869](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4869) → [#4888](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4888) → [#4891](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4891) | `f5813506…` → `bb55b0d7…` → `797116d6…` | 从实际1217P/1F/1timeout到作者记录的后继1219P/78skip，再修真实Codespell三字节fixture。最终797尚待自己全scope；40生产旗标仍false、拓扑DENY_ALL，371导航操作不等于371生产能力。 |
| Native Cell / Circuit V2 [#4887](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4887) | `b3d015f92166ee210fdab70a6c172cffc9cf9e61` | 准备/编码、共享模型receipt、合法masked决策、有界反馈和七阶段学习协调。正文明确尚未编译/测试，join物化、无进展与真实训练接线未完；先过原native与生命周期owner，再谈生产采用。 |
| Cell角色与分化 [#4890](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4890) | `caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b` | 七功能角色与两支持类别，分别统计能力类型、expert版本、状态owner、活跃instance；六arm公平对照及迁移。30Rust/24Python是已编写控制，不是通过数；保持独立接受。 |
| Memory V15 [#4885](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4885) / 标识符活性 [#4889](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4889) | `f88b826d…` / `31880a58…` | 固定真实成本/预算、隔离executor、拒绝事后协议改写；后者处理NULL/UTF8标识符使prepared不可恢复的真实缺陷。作者记录33/33及1600/1600对照；生产Control、持久实验预留、完整模型迁移和poisoned DB恢复仍需独立方案。 |
| 普通PQ外部效果 [#4877](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4877) | `9e9eaad62463f78882f986c8e90981986b4cdb89` | 170局部通过与1个真实Chain失败同时保留。正文指出最小包49,508B已超过原24,576B入口，hex99,016B超过65,536B控制帧；先做有界版本化大payload接口与双端接受，不能只抬阈值或裁包使门绿。 |
| R6观察终止 [#4870](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4870) | `bfdf51e19efdfd38f6f6825372e81a790ed40c90` | 有界真实进程终止、同manager清理、writer handoff与原CI输入；局部Operator33通过不替代被取消的完整Windows或legacy外删/LEAK缺口。 |
| HIA/NDU重复JSON [#4882](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4882) | `b8aaa6cca885b3022d0a647a9a878d211b49fe5b` | 拒绝顶层/嵌套重复字段并保收费/拒绝回执，原14+新3控制待同head CI；raw PIPE无界、真实模型/独立评价仍OPEN，DENY_ALL保持。 |
| HCSN研究 [#4873](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4873) | 当前`fe1def4a…`；正文结果源`28a61d14…` | 必须先解释最新head与正文旧源差异。CPU严格95例和45/48完成smoke不代170个CUDA任务；原弱B结果、分辨率误差、缺物理能耗继续公开。与原B18的D−B采用门分别评价。 |

还读取了[#4883](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4883)的精确60处Windows格式修补和[#4881](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4881)的ConPTY错误修补，它们仍HOLD；格式或编译前置通过不改变产品权限合同。所有整合按固定source、真实依赖和原测试逐路径进行。

'''
plan=plan[:insert]+newdev+plan[insert:]
plan=plan.replace('[当前23项ledger](continuation-blocker-progress-v4.json)','[当前23项ledger](continuation-blocker-progress-v5.json)')
plan=plan.replace('[当前执行进度V5](CONTINUATION_PROGRESS_V5.zh-CN.md)','[当前执行进度V6](CONTINUATION_PROGRESS_V6.zh-CN.md)')
start=plan.index('## B11原生编译增量与已发布纠错')
plan=plan[:start]+'''## B11最新发布与历史结果

初始f02编译8E0659、后继0d65/c05的真实测试失败与label观察、3a407的8行物理机制结果均保留。当前最新为7e四路径ACL候选；主产品已经eed，实际merge582f具有两条正确父源。原Windows结果尚未验收。详细原始计数、分类与边界见[进度V6](CONTINUATION_PROGRESS_V6.zh-CN.md)及[精确发布回执](reviews/b11-acl-four-path-publication-v1.json)。
'''
(OUT/'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V4.zh-CN.md').write_text(plan)
latest='''# 当前审计与执行入口

**当前23项：10项限定范围闭合、12项开放、1项科学验证保留。尚未全量闭合。**

- [全量进度与实际修复 V6](CONTINUATION_PROGRESS_V6.zh-CN.md)：已发布14路径、B13/B22正式闭合、Windows原始失败、Linux资源门与新CI。
- [项目方向及后续工作计划 V4](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V4.zh-CN.md)：40模块/91工作包、逐项原退出条件、正常产品接线、最新16条外部工作分支与依赖。
- [机器可读23项ledger V5](continuation-blocker-progress-v5.json)：原ID/退出条件不变；逐项状态、限定来源和下一门。
- [本批证据索引 V7](evidence-index-v7-registered.json)：实际Git对象与无损原件运输；历史失败/缺失/取消均保留。

主产品[Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)当前head `eed4d6bb61b789b19f60facc79f9e031765fa4c9`、tree `ca1c4671ef6b2773280d01b5d76c6166252f5856`。B11 [Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)当前head `7e0b2303ed0242d83bf56202e8ffb17f5c856186`，四路径修复等待原Windows结果。

固定新CI快照截至2026-11-05 16:39:48 UTC；B13根审、B11发布、资源终态及16:40:42–16:45:44分支观察各有独立时间。后续状态在后续增量记录，不倒改本快照。原全量人口统计仅属于03:16–03:24时点。
'''
(OUT/'LATEST.zh-CN.md').write_text(latest)
print(json.dumps({'counts':ledger['counts'],'files':[{'name':p.name,'bytes':p.stat().st_size} for p in OUT.iterdir() if p.is_file()]},ensure_ascii=False))
