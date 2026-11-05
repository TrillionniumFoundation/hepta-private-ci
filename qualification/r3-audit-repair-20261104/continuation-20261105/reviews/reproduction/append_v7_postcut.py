"""Append bounded later observations without rewriting the frozen cut0004 archive."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'hepta-audit-fifth/v7-deliverables'
ledger_path = OUT / 'continuation-blocker-progress-v5.json'
ledger = json.loads(ledger_path.read_text())
native = json.loads((ROOT / 'hepta-audit-fifth/inputs/b11-native5-root-original-verification-v1.json').read_text())
donor = json.loads((ROOT / 'research-audit/pr4855-pool-reuse-delta-20261105/registry-plan.json').read_text())
snapshot = json.loads((ROOT / 'ci-audit/published-eed4d6-ci-20261105/snapshot-0002/summary.json').read_text())
ledger['postcut_appended_utc'] = datetime.now(timezone.utc).isoformat()
ledger['postcut_does_not_rewrite_fixed_cut0004_archive'] = True
ledger['b11_diagnostic_PR'].update(
    status='B11_OPEN_ORIGINAL_WINDOWS_TARGET_FAILED',
    native5={'run': native['run'], 'job': native['job'], 'actual_checkout': native['actual_checkout'],
             'actual_tree': native['actual_tree'], 'PASS':143, 'FAIL':10, 'ignored':2,
             'disjoint_harnesses':2, 'whole_target_retries_inferred':False,
             'category_counts':native['failure_category_counts'],
             'root_receipt':'reviews/b11-native5-root-original-verification-v1.json',
             'complete_JSON_rows':6, 'interleaved_rows_unrepaired':['host/medium','current_strict/medium'],
             'restore_rows':8, 'finalized_rows':8, 'objects':80, 'restoration_errors':0,
             'descendants_spawned':0})
ledger['postcut_ci_observation'] = {
    'collected_from':'2026-11-05T17:07:23Z','collected_to':'2026-11-05T17:07:24Z',
    'non_atomic':True, 'head':snapshot['head'], 'run_count':snapshot['run_count'],
    'job_count':snapshot['job_count'], 'job_status_counts':snapshot['job_status_counts'],
    'scope':'Later independent observation; cut0004 remains immutable',
    'success_review':'reviews/eed-windows-success-review-v2.json',
    'scope_results':{'core':{'outer_PASS':2340,'original_ignored':3,'unique_outer_names':2343},
                     'retained_three_libraries':{'PASS':532,'suite_counts':[299,209,24]},
                     'gitqueue_source':{'git_utils_outer_PASS':35,'queue_outer_PASS':36},
                     'gitqueue_merge':{'git_utils_outer_PASS':35,'queue_outer_PASS':36}},
    'no_transfer_to_unexecuted_platforms_or_full_workspace':True,
    'further_four_success_jobs':'API-only at this cut; no original-case acceptance inferred'}
ledger['postcut_pr4855_sqlx_donor'] = {
    'source_head':donor['source_head'], 'actual_registry_blob':'c3e54fc2b23f73870ab394f076c3fde14fa57327',
    'review':'generated-evidence/pr4855-refused-commit-reuse-20261105/independent-review.json',
    'native_commands_started':0, 'original_zip_members':20,
    'red':'One distinct original State case failed in two attempts: InvalidSavePointStatement; recipe exit100',
    'green':'Same case and exact argv/profile PASS;216 unselected',
    'nine_package_scope':'1312 catalog identities=1288PASS+24original ignored; not a substitute for matched single-package red/green',
    'reuse':'Donor stale-depth mechanism, connection-discard repair, exact unchanged donor source and original controls',
    'remaining_original_current_candidate_gates':['two independent constructors','TEMP physical-connection replacement',
         'precise SQLite531 and callback counts','autocommit and tracked-depth observations','checkout counts','native owner custody'],
    'B16_status':'OPEN'}
for item in ledger['items']:
    if item['id']=='B11':
        item['latest_continuation_zh']='已发布7e在实际merge582f/tree1718原Windows完整目标143PASS/10FAIL/2ignored；partial-read和两个legacy预启动拒绝原例恢复。仍有2目录reopen错误5、1无WRITE_DAC控制前提未成立、1真实strict外删、2普通host前提及4mutex poison。六行JSON可解析，host/medium与strict/medium交织未补造；B11仍OPEN。'
        item['next_closure_gate_zh']='先修目录ACL同对象修补和真实无WRITE_DAC控制；保原完整目标与断言。完整限制令牌继续补正常有限read、同步授权、loader与全部后代寿命，再验合法I/O和外部四种写删拒绝。'
    elif item['id']=='B15':
        item['latest_continuation_zh']='原0004固定快照保留；17:07:23–24另读19runs/53jobs=17S2skip31Q2running1cancel，0F。新eed原Windows Core2340P3I、retained三库532P、GitQueue各source/merge35+36P由五完整ZIP和逐名原件复核。其他新success仅API未转资格；Linuxfull仍因原资源门停于编译前。'
    elif item['id']=='B16':
        item['latest_continuation_zh']='Foundation限定资格及旧driverUNKNOWN保持。#4855两个明确既存native任务只读回收完整原件，独审恢复SQLx同argv/profile真实红绿和九包1288P24ignored，可复用该donor机制。当前两个独立pool入口、TEMP物理replacement、精确531/回调及native custody仍需原控制；Current/FinalUse/normalUI仍开放。'
assert Counter(x['closure_class'] for x in ledger['items']) == ledger['counts']
ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')

extra = '''## 7. 固定快照之后的实际执行增量

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
'''
p=OUT/'CONTINUATION_PROGRESS_V6.zh-CN.md'
text=p.read_text(); marker='## 7. 固定快照之后的实际执行增量'
text=text.split(marker)[0].rstrip()+'\n\n'+extra
p.write_text(text)

p=OUT/'LATEST.zh-CN.md';text=p.read_text()
text=text.replace('四路径修复等待原Windows结果。','四路径修复的原Windows完整目标现为143通过、10失败、2原忽略，B11仍开放。')
text=text.replace('后续状态在后续增量记录，不倒改本快照。','其后native5终态、17:07新CI快照与SQLx donor原件另列进度第7节，不倒改本快照。')
p.write_text(text)

p=OUT/'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V4.zh-CN.md';text=p.read_text()
text=text.replace('native4证明真实外删；ACL四路径7e已发布待原目标','native5原目标143PASS/10FAIL/2ignored，目录与host控制待修，真实strict外删仍在')
text=text.replace('先判ACL实际结果；同步read授权/owner/后代寿命与真实loader能力逐项接线','先修目录ACL同对象句柄及真实无WRITE_DAC控制；同步read授权/owner/后代寿命与真实loader逐项接线')
text=text.replace('原Windows结果尚未验收。','原Windows目标已实际143PASS/10FAIL/2ignored；两个目录错误5、host权限前提和真实strict外删继续推进。')
text+='''\n## 新增可复用依据与仍需完成的门\n\nSQLx拒绝提交后连接复用的donor现在已有完整既存native红绿原件，由[独审](reviews/pr4855-refused-commit-reuse/REVIEW.zh-CN.md)核过；可复用机制与该范围原控制。本候选的两个独立构造器、物理换连接、精确531与native custody仍按原门执行。新eed Windows Core完整库2,340PASS/3ignored、retained三库532PASS以及GitQueue source/merge的逐名范围已由原件验证。它们缩小剩余验证范围，但不代替未执行的Unix integration、Intel PTY或默认全工作区；具体后续结果见[进度第7节](CONTINUATION_PROGRESS_V6.zh-CN.md)。\n'''
p.write_text(text)
print(json.dumps({'counts':ledger['counts'],'postcut':True,'outputs':{p.name:p.stat().st_size for p in OUT.iterdir() if p.is_file()}},ensure_ascii=False))
