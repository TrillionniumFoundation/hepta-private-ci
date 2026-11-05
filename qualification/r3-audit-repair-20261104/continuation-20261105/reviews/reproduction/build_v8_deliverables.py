"""Register the B08 original-contract closure without rewriting earlier cuts."""
from pathlib import Path
import copy
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
OLD = ROOT / 'hepta-audit-fifth/v7-deliverables'
OUT = ROOT / 'hepta-audit-fifth/v8-deliverables'
OUT.mkdir(exist_ok=True)
CUT = '2026-11-05T17:53:52Z'

def read(path):
    return json.loads(Path(path).read_text())

def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

old = read(OLD / 'continuation-blocker-progress-v5.json')
ledger = copy.deepcopy(old)
closure = read(ROOT / 'hepta-audit-fifth/inputs/b08-original-contract-root-closure-v1.json')
assert closure['decision'] == 'CLOSED_SCOPED'
ledger.update(schema='hepta-continuation-blocker-progress-v6', recorded_utc=CUT,
              prior_progress_record='continuation-blocker-progress-v5.json',
              counts={'CLOSED_SCOPED': 11, 'OPEN': 11, 'SCIENTIFIC_HOLD': 1},
              all_blockers_closed=False, whole_candidate_qualified=False)
ledger['closure_transitions_v8'] = [{
    'id': 'B08', 'from': 'OPEN', 'to': 'CLOSED_SCOPED',
    'scope': closure['scope'],
    'root_receipt': 'reviews/b08-original-contract-root-closure-v1.json',
    'content_git_blob': '652e5013c96b62c5fd3e0dc27b49e02af89afb00',
    'original_exit_unchanged': True,
    'overall_original_owning_scope': '3962 PASS / 5 FAIL / exit100, retained',
    'not_an_eed_GNU_or_full_workspace_pass': True,
}]
by_id = {row['id']: row for row in ledger['items']}
b08 = by_id['B08']
assert b08['original_exit_condition_zh'] == closure['original_exit_condition_zh']
b08['prior_v5_state'] = copy.deepcopy(b08)
b08.update(
    status='CLOSED_ORIGINAL_RETAINED_WIRE_AND_REPLAY_SCOPE',
    closure_class='CLOSED_SCOPED',
    current_label_zh='B08原四例与真实prompt/重放/端点矩阵范围闭合',
    evidence_scope_zh='完整ROG原始日志11,059,831B及JUnit839,106B逐名对应四个原PASS；本地源码树e78，普通HEAD为cabc；15个相关完整源码文件跨5b/e78/eed逐blob绑定。原完整所属范围仍3962PASS/5FAIL/exit100。',
    latest_continuation_zh='根审已实际执行退出0；验证实际prompt先附加、真实输出与exact calls、序列化字节上限、溢出/保留/重放/compaction和16格endpoint/name/format/feature矩阵。只读getter不制造附加，不改变生产持久化；first-party OpenAI合法保留元数据，非官方端点剥离。',
    next_closure_gate_zh='维护已闭合的原四例范围；若相关源码改变则按影响重验。新eed全平台与完整工作区仍由B15验收，不把先前Q02收件计划追加为B08原退出条件。',
)
by_id['B11']['prior_latest_continuation_v5_zh'] = by_id['B11'].get('latest_continuation_zh')
by_id['B11']['latest_continuation_zh'] = '诊断Draft已实际7e→19d2，完整树17ac，实际merge6904/tree7518保主产品14路径。仅两个Rust路径265新增/36删除：新句柄验证128位FileId与volume、拒绝reparse/路径替换，并建立真实无WRITE_DAC线程令牌控制。原native6任务42077117788/127420172838已启动，17:49仍执行中，原156项尚无终态。native5历史143PASS/10FAIL/2ignored保留；严格外删仍OPEN。'
by_id['B11']['next_closure_gate_zh'] = '先取得19d2原完整Windows156项的实际结果与完整工件；四个相关阳性原例实际PASS后才进入已独审的精确物理反事实。继续正常有限read根的同步完成、严格外删、后代寿命及真实loader/合法I/O接受。'
by_id['B21']['latest_continuation_zh'] = '当前eed的PTY完整源码与原30例/新增1诊断收集例已独审；2/5秒预算和drain/child/FD断言保留。0e Intel drain仍2.023秒失败且无read字节/errno，不能归因为已证Tokio调度问题。成功日志保留脚本只增加原PTY目标的一行候选已静态验收，未应用、不扩测试范围；待下一必要产品发布一并处理。'
ledger['historical_b11_diagnostic_PR_v7'] = copy.deepcopy(ledger['b11_diagnostic_PR'])
ledger['b11_diagnostic_PR'] = read(ROOT / 'hepta-audit-fifth/inputs/b11-identity-two-path-publication-v1.json')
ledger['b11_diagnostic_PR']['native6'] = {
    'run_id': 42077117788, 'job_id': 127420172838, 'attempt': 1,
    'last_observed_utc': '2026-11-05T17:49:33Z', 'status': 'in_progress',
    'test_result': 'NOT_YET_OBSERVED', 'expected_original_roster': 156,
    'original_first_snapshot': 'ci/b11-native6/first-snapshot-1743.json',
    'original_latest_snapshot': 'ci/b11-native6/snapshot-1749.json',
}
ledger['ci_waiting_chain_v8'] = {
    'root_observation': 'reviews/post-v7-ci-waiting-ui-and-api-v1.json',
    'api_review': 'ci/queue-followup-v2/review.json',
    'UI': 'eed blocking42063948117 -> 5b41999114842 -> older41975255726; eed architecture42063947919 -> 5b41999114801',
    'older_rest_result': '41975255726 completed/cancelled since09:42:55Z;37/37 jobs terminal',
    'causal_limit': 'The visible UI wait chain is not proof that the older terminal run consumes a runner. Underlying cause remains unresolved.',
    'old_5b_remaining': 'Three queued unassigned aggregate jobs only; no product test currently executing in these three jobs',
    'cancel_performed': False, 'rerun_performed': False, 'browser_signed_in': False,
    'failure_log_gap': '6/7 old failed job logs complete; cargo-deny log transport failed; no fabricated cause',
}
ledger['b21_retention_candidate_v8'] = {
    'review': 'reviews/b21-intel-current-followup/independent-review.json',
    'patch': 'reviews/b21-intel-current-followup/retention-candidate-v1/retention.patch',
    'applied': False, 'test_execution_expanded': False,
    'purpose': 'Retain the existing original PTY target success log on the next necessary product publication; original11 target order remains intact.',
}
assert [r['id'] for r in old['items']] == [r['id'] for r in ledger['items']]
assert [r['original_exit_condition_zh'] for r in old['items']] == [r['original_exit_condition_zh'] for r in ledger['items']]
counts = {s: sum(r['closure_class'] == s for r in ledger['items']) for s in ledger['counts']}
assert counts == ledger['counts'], counts
assert [a['id'] for a, b in zip(old['items'], ledger['items']) if a['closure_class'] != b['closure_class']] == ['B08']
write(OUT / 'continuation-blocker-progress-v6.json', ledger)

ui = {
    'schema': 'root-post-v7-ci-waiting-ui-and-api-observation-v1',
    'recorded_utc': CUT,
    'browser_observation_window_utc': ['2026-11-05T17:29:14Z', '2026-11-05T17:35:42Z'],
    'source': 'Root direct browser accessibility-state observations during authorized CI queue management; selected observations transcribed, not a full HTML/AX archive.',
    'observations': [
        {'url': 'https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41999114842', 'visible_wait_target_run': 41975255726, 'visible_wait_target_label': 'blocking-ci #33534'},
        {'url': 'https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42063948117', 'visible_wait_target_run': 41999114842, 'visible_wait_target_label': 'blocking-ci #33590'},
        {'url': 'https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42063947919', 'visible_wait_target_run': 41999114801, 'visible_wait_target_label': 'Hepta architecture convergence #20399'},
    ],
    'independent_complete_REST_records': ['ci/queue-followup-v2/older-blocking-run.original.json', 'ci/queue-followup-v2/older-blocking-jobs.original.json'],
    'REST_facts': {'id': 41975255726, 'head': '0e139b599f0fe451f80fb7db4b2913bb9c679dce', 'status': 'completed', 'conclusion': 'cancelled', 'updated_at': '2026-11-05T09:42:55Z', 'jobs_total': 37, 'terminal_jobs': 37, 'counts': {'success': 8, 'failure': 5, 'cancelled': 20, 'skipped': 4}},
    'interpretation': 'Retain both the UI waiting links and REST terminal status. This is an observation mismatch, not proof of active older execution, stale-lock root cause, or sole runner capacity cause.',
    'cancel_capability': 'Installed connector exposed rerun but no cancel tool; browser signed out. This does not mean GitHub create/ref/PR write capabilities are unavailable.',
    'mutations': {'cancel': False, 'rerun': False, 'login_started': False, 'workflow_changed': False},
}
write(ROOT / 'hepta-audit-fifth/inputs/post-v7-ci-waiting-ui-and-api-v1.json', ui)

progress = '''# 持续审计与实际修复进度 V7

**23项原blocker现在为11项限定范围闭合、11项开放、B18科学验证暂缓。B08本轮按原退出条件闭合；整个候选尚未完成验收。**

本报告截至2026-11-05 17:53:52 UTC整理；每个原件保留自己的实际观察时间。此前10/12/1的[进度V6](CONTINUATION_PROGRESS_V6.zh-CN.md)和[证据索引V7](evidence-index-v7-registered.json)保留为历史。新[ledger V6](continuation-blocker-progress-v6.json)只改变B08的闭合分类，原23个ID及退出条件逐字不变。发展方向及后续完整工作计划见[计划V5](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md)。

## 1. B08已满足原退出条件

根审实际运行验证器并返回0，核对完整11,059,831字节原始日志、839,106字节JUnit、四个原测试正文、15个相关完整源码文件及5b/e78/eed的完整Git树。该原运行在ROG工作区的源码树为e78；工作区普通HEAD仍是cabc，不能将其写成5b。[根审闭合回执](reviews/b08-original-contract-root-closure-v1.json)和[独立四例检查](reviews/b08-original-exit-20261105/review-v1/four-case-evidence.json)保留逐名、字节位置与来源。

| 原用例 | 实际覆盖 | GNU原执行 |
|---|---|---:|
| recorder bounds pending calls and preserves overflow | 真实附加前后的None/Some、pending条数上限与溢出、exact replay及compaction清理 | PASS，0.014秒 |
| recorder bounds retained history and reports omissions | 512次真实记录与附加、32KiB保留上限及omission统计 | PASS，2.379秒 |
| chatgpt codex wire strips local metadata but openai wire keeps it | 端点/名称、格式和feature的16格矩阵 | PASS，0.012秒 |
| namespaced custom tool call preserves namespace through dispatch and replay | 实际SSE请求、原exact calls、flush rollout/load history、真实输出与namespace回放、escaped输入原序列化字节上限 | PASS，0.602秒 |

生产路径在构建prompt及发出真实请求之前附加pending calls；只读getter只读取已保留记录，没有制造“已附加”状态。原生产持久化协议未改变。端点矩阵的正确合同是ChatGPT Codex及非官方端点剥离本地私有字段，first-party OpenAI的原合法保留行为仍成立；不能概括成“所有provider都剥离”。原跳过网络宏的固定早退输出未出现。

这四例来自一次原所属范围的运行；该完整范围仍是3962通过、5失败、exit100。Windows三个原单元的各自固定源结果作为补充保留；Unix namespaced用例在Windows不适用。本次没有执行eed的GNU全范围，也没有将四例的通过升级成B15通过。此前Q02的收件计划不是额外原退出条件，不再以它无依据阻止B08闭合。

## 2. Windows ACL修复已发布，等待原156项终态

[Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)已发布`19d2fdfcaefbb41cdf2a72754d695d4b47cb3f14`，tree为`17ac791ce156d05d4d1cd13cddf9184e528293a1`。相对7e仅两个Rust路径变化，265行新增、36行删除；实际merge `69040075a846c7032a3bafc7a0b623e7c0257619`的tree为`75181bf7e4f119d08945003339b32aa0782ef41c`，两父源为eed和19d2，主产品14路径均保留。[精确发布回执](reviews/b11-identity-two-path-publication-v1.json)

原READ_CONTROL查询、完整ACL时直接返回及最终setter保留；只有需要修复时，持有旧句柄并读取完整非零128位FileId和volume，重新以既存对象方式打开具WRITE_DAC的新句柄，拒绝最终reparse并核对同一对象后写DACL。原无WRITE_DAC控制使用自有文件及当前同步测试线程的受限令牌，先证明查询仍可达，再要求生产修复在实际写权限打开阶段返回OS5；还原令牌发生在还原文件DACL之前。

新增物理控制分别使用真实文件和目录：持有旧对象、rename后重建原路径，要求替代对象和原对象DACL都不被误改，并证明原对象在新名字下仍可正常修复。其兼容范围明确：修复需要FileId/属性支持，最终reparse被拒绝；没有宣称祖先路径托管或并发ACL写入序列化已解决。[独立静态审查](reviews/b11-identity-v3-independent/independent-review.json)

原工作流未变。native6为run `42077117788` / job `127420172838` / attempt1；17:49的完整原API记录显示checkout及MSVC准备完成、原目标正在执行，尚无测试终态。原名单为156项，即旧155项加一项物理替换控制。此前native5的143通过、10失败、2忽略完整保留；新源不能继承这些结果。[首次快照](ci/b11-native6/first-snapshot-1743.json)、[17:49快照](ci/b11-native6/snapshot-1749.json)

精确反事实执行脚本V2已完成独审，当前仍DISABLED、NOT_RUN。它要求完整、非cache的原日志中四个相关阳性用例各自真实PASS，才移除唯一身份相等强制；只有实际替换对象被误改的固定marker、原597行断言、单一1FAIL/0ignored及XML101同时成立，才算有效负控。finally写回前重新验证完整源码、索引及锁，未知漂移保留不覆盖。原whole-target错误继续保持错误；反事实成功不能把整个B11变绿。[执行候选manifest](native-plan/b11-identity-counterfactual/counterfactual-workflow-v2/manifest-DISABLED.json)、[独审](reviews/b11-counterfactual-wrapper-independent.json)

## 3. CI等待链与资源边界

浏览器实际显示新blocking等待旧5b，旧5b又指向更早0e任务；但对应REST确认更早任务自09:42:55已取消，37个job全部终态。这只能证明显示状态之间存在差异，不能证明旧0e当前占用runner，也不能据此断定唯一根因为runner容量或一个已证实的锁故障。旧5b剩余三个未分配runner的job均为汇总，不执行产品测试。[直接UI观察及原API对照](reviews/post-v7-ci-waiting-ui-and-api-v1.json)、[完整跟进](ci/queue-followup-v2/review.json)

当前GitHub连接没有暴露取消工作流的操作，浏览器尚未登录；本轮未取消、重跑或改变这些任务。旧七个失败job中六个完整日志和四份Windows原ZIP已保留；cargo-deny日志接口仍失败，这一缺口没有被补成推断原因。

Linux完整门仍RESOURCE_PENDING。唯一ca1 firststart在任何源码修改、build/catalog/test之前因可用RAM低于原32GiB门停止；64GB磁盘、32GiB可用内存、jobs4不变。现有五台主机的已记录观察没有一台达该门，不代表它们永久不可用。没有具体新容量释放依据前，不重复启动或降低门槛。原完整目录、七个helper、源码/索引/锁/SDK守卫均已准备；真正测试完成后才按原顺序进行scoped fix和fmt。

## 4. Intel PTY与其它开放工作

当前eed的PTY源码、原30例及新增一个诊断收集控制已逐文件复核。原2/5秒预算、完整drain、child退出与FD断言保留；旧0e的Intel drain在2.023秒失败，只观察到Python启动，缺少read字节/errno，尚不足以证明Tokio调度根因。现有诊断适合下一次真实原失败取证，不能把测试诊断变化写成生产drain已修复。[B21独审](reviews/b21-intel-current-followup/independent-review.json)

成功日志保留脚本有一个必要的小补充：现有11目标名单没有PTY目标。新增一行保留原PTY成功日志的候选已静态验证，原11项顺序、复制及错误行为不变，也不增加测试执行；为保留当前eed原CI，暂未另推主ref，下一次必要产品发布时一并纳入。[精确patch](reviews/b21-intel-current-followup/retention-candidate-v1/retention.patch)

B02/B07/B09/B10/B11/B15/B16/B19/B20/B21/B23仍开放。工作依次推进原平台及严格权限边界、正常Root/Current/FinalUse/真实caller、外部系统独立接受；B18继续要求新的预注册2×2与D−B原采用门。研究分数、源代码存在、已有donor局部通过和CI任务成功都不能替代这些产品接受。

## 5. 当前可交付与下一执行批

主产品仍为[Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)的eed/ca1；本次审计提交只更新证据和计划，不修改产品源码或CI规则。已闭合范围为B01/B03/B04/B05/B06/B08/B12/B13/B14/B17/B22。

下一批先收齐19d2原156项完整结果，按实际失败修复并取得身份反事实；同步准备read ACL完成语义的小片及它独立的setup helper原目标，不能借库测试结果给helper授予资格。主平台CI取得终态后继续逐原范围收敛；只有新容量证据出现才启动Linux完整门。完整依赖顺序、23个原退出条件和各模块后续交付均在[计划V5](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md)。
'''
(OUT / 'CONTINUATION_PROGRESS_V7.zh-CN.md').write_text(progress)

plan = (OLD / 'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V4.zh-CN.md').read_text()
plan = plan.replace('执行计划 V4', '执行计划 V5', 1)
plan = plan.replace('10限定闭合、12OPEN、1科学HOLD', '11限定闭合、11OPEN、1科学HOLD')
plan = plan.replace('B13/B22的新增闭合由完整原平台证据支持。', 'B08新增闭合由原四例、完整原件及生产语义复核支持；此前B13/B22闭合保持。')
plan = plan.replace('CONTINUATION_PROGRESS_V6.zh-CN.md', 'CONTINUATION_PROGRESS_V7.zh-CN.md').replace('进度V6', '进度V7').replace('进度第7节', '进度V7及其历史来源')
plan = plan.replace('continuation-blocker-progress-v5.json', 'continuation-blocker-progress-v6.json').replace('ledger V5', 'ledger V6')
plan = plan.replace('十个限定闭合范围保留其证据；十二个开放项', '十一个限定闭合范围保留其证据；十一个开放项')
plan = plan.replace('| B08 | OPEN / 私有 attempted tool 元数据 | 在新固定head及merge的原平台执行新增namespaced原例与保留的wire/retained边界；不借B09/B10通过计数。 |', '| B08 | CLOSED_SCOPED / 私有 attempted tool 元数据 | 原四例、真实prompt附加/输出、exact calls、持久化与端点矩阵已按原条件闭合；维护原范围，新整合全平台归B15。 |')
plan = plan.replace('先读取7e原完整Windows目标，逐个原失败判定；', '先读取19d2原完整Windows156项终态；四项阳性原例通过后执行精确身份反事实；')
plan = plan.replace('| C：已补原平台证据 | B13九例与B22十三例已正式CLOSED_SCOPED |', '| C：已补原范围证据 | B08四例、B13九例与B22十三例已正式CLOSED_SCOPED |')
plan = plan.replace('| F：Windows严格隔离 | native5原目标143PASS/10FAIL/2ignored，目录与host控制待修，真实strict外删仍在 | 先修目录ACL同对象句柄及真实无WRITE_DAC控制；', '| F：Windows严格隔离 | 新19d2身份/权限修复已发布，原156项执行中；native5历史143PASS/10FAIL/2ignored，真实strict外删仍在 | 先收齐19d2原终态及物理身份反事实；')
old_tail = plan[plan.index('## B11最新发布与历史结果'):plan.index('## 新增可复用依据与仍需完成的门')]
new_tail = '''## B11最新发布与历史结果

初始编译失败、后续物理机制结果及native5的143PASS/10FAIL/2ignored均保留。当前最新为19d2两路径身份与真实权限控制候选，主产品仍eed，实际merge6904/tree7518已核正确父源并保留主产品14路径。原156项native6在17:49仍执行中；静态接受与已发布均不算原生通过。详细范围见[进度V7](CONTINUATION_PROGRESS_V7.zh-CN.md)及[精确发布回执](reviews/b11-identity-two-path-publication-v1.json)。

正常read ACL准备另按setup helper原binary测试目标验收，当前专用库目标不会执行它；named mutex忙或Full进程成功不能独自证明当前read roots完成。最小修复保持原rootset、权限及token行为；原外层没有局部deadline的限制应显式保留，不得将同步等待描述为新增有界就绪。

'''
plan = plan.replace(old_tail, new_tail)
plan += '''
## 本轮收敛后的立即执行顺序

1. 取得19d2原156项完整日志与工件，区分真实失败、前提失败和后续mutex poison。相关四项阳性实际PASS后进入已独审的精确身份反事实；任何来源/索引/锁漂移不覆盖。
2. 同步收敛正常read ACL完成语义，使用原setup helper独立目标；保有限rootset与原权限，不递归授权全盘，不以mutex存在冒充完成。
3. 主eed取得原GNU/musl/Darwin ARM/Intel/Windows终态后，按原名单和原失败逐项关闭；成功PTY原日志保留的一行小片在下一必要发布纳入，原30例与2/5秒预算不变。
4. Linux完整门只在具体新资源条件成立后续接，保64GB/32GiB/jobs4及原完整范围；完成后scoped fix→fmt，随后核最终head/base/merge原required门。
5. 按第4节接通真实Root/Current、三池、FinalUse及正常UI caller；有证据的donor按路径复用，外部消费者和B18独立新实验继续各守原接受门。

最新队列显示链与REST终态不一致的事实已归档；当前没有已证实的唯一排队根因，亦没有执行取消或重跑。全部闭合仍以每项原条件的实际证据为准。
'''
for row in ledger['items']:
    assert row['original_exit_condition_zh'] in plan, row['id']
assert '| B08 | CLOSED_SCOPED' in plan
(OUT / 'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md').write_text(plan)

(OUT / 'LATEST.zh-CN.md').write_text('''# 当前审计与执行入口

**当前23项：11项限定范围闭合、11项开放、B18科学验证暂缓。尚未全量闭合。**

- [当前进度 V7](CONTINUATION_PROGRESS_V7.zh-CN.md)：B08原条件正式闭合、Windows身份与权限修复已发布、原156项执行中、CI等待链与REST终态差异。
- [项目方向及后续工作计划 V5](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md)：40模块/91工作包、23项原退出条件、正常产品接线与逐批交付。
- [机器可读ledger V6](continuation-blocker-progress-v6.json)：仅B08本轮由OPEN转为CLOSED_SCOPED，原ID及退出条件不变。
- [本批实际证据索引 V8](evidence-index-v8-registered.json)与[此前完整证据索引 V7](evidence-index-v7-registered.json)：实际Git对象、完整原件及失败/缺口历史。

主产品[Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)保持head `eed4d6bb61b789b19f60facc79f9e031765fa4c9`、tree `ca1c4671ef6b2773280d01b5d76c6166252f5856`。B11 [Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)为head `19d2fdfcaefbb41cdf2a72754d695d4b47cb3f14`，原156项尚无终态，B11仍开放。

本批整理截至2026-11-05 17:53:52 UTC，各原件保留独立观察时间；全库1103 PR / 5193分支只属于03:16–03:24原完整快照。此审计提交仅保存证据与计划，不改变产品源码或CI规则。
''')
print(json.dumps({'counts': counts, 'changed_closure_ids': ['B08'], 'files': [p.name for p in OUT.iterdir()]}, ensure_ascii=False))
