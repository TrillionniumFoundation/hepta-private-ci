"""Apply the separately timed native6 and published counterfactual increment.

Run build_v8_deliverables.py first. The original17:53:52 cut and each original
observation timestamp remain explicit; the publication increment is not a test.
"""
from pathlib import Path
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'hepta-audit-fifth/v8-deliverables'

def read(p):
    return json.loads(Path(p).read_text())

def write(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

ledger = read(OUT / 'continuation-blocker-progress-v6.json')
native = read(ROOT / 'hepta-audit-fifth/inputs/b11-native6-root-original-verification-v1.json')
publication = read(ROOT / 'hepta-audit-fifth/inputs/b11-identity-counterfactual-publication-v1.json')
assert native['combined_disjoint_counts'] == {'total': 156, 'passed': 147, 'failed': 7, 'ignored': 2}
ledger['postcut_appended_v8_utc'] = '2026-11-05T18:00:25Z'
ledger['v8_fixed_cut_not_rewritten'] = '2026-11-05T17:53:52Z'
ledger['historical_b11_diagnostic_at_v8_fixed_cut'] = ledger['b11_diagnostic_PR']
ledger['b11_diagnostic_PR'] = publication
ledger['b11_native7_first_snapshot_v8'] = {
    'head': publication['head'], 'run': 42079845181, 'job': 127429723742, 'attempt': 1,
    'status': 'queued', 'observation_window': '2026-11-05T18:00–18:01Z',
    'original': 'ci/b11-native7/first-snapshot-1800.json',
    'actual_job_checkout': 'NOT_YET_OBSERVED', 'counterfactual_result': 'NOT_RUN',
}
ledger['b11_native6_terminal_v8'] = {
    'receipt': 'reviews/b11-native6-root-original-verification-v1.json',
    'content_git_blob': '847bd07e56339e87484891e6f67273be2c97aefe',
    'head': native['head'], 'actual_checkout': native['actual_checkout'], 'actual_tree': native['actual_tree'],
    'run': native['run'], 'job': native['job'], 'attempt': 1, 'decision': native['decision'],
    'combined_disjoint_counts': native['combined_disjoint_counts'],
    'four_required_positives_actual': True, 'file_and_directory_physical_rejection_actual': True,
    'ordinary_exit_codes': native['ordinary_exit_codes'],
    'remaining_failure_classes': {'strict_outside_delete': 1, 'ordinary_host_Neither_preconditions': 2, 'downstream_mutex_poison': 4},
    'whole_target': 'FAILED', 'B11': 'OPEN',
}
ledger['postcut_ci_observation_v8'] = {
    'from': '2026-11-05T17:53:59.956Z', 'to': '2026-11-05T17:54:00.870Z',
    'runs': 19, 'jobs': 53, 'counts': {'success': 18, 'queued': 31, 'running': 1, 'skipped': 2, 'cancelled': 1, 'failure': 0},
    'only_new_terminal_since1707': {'id': 127378840922, 'result': 'success', 'scope': 'V8 x86_64 Windows ptrcomp-sandbox; API status only'},
    'blocking_and_architecture': 'Still pending,0 jobs each; no cancellation or rerun',
    'originals_registry': 'ci/eed-status-1754-20261105/registry.actual-v1.json',
    'original_records': 23, 'original_bytes': 1020501,
}
b11 = next(row for row in ledger['items'] if row['id'] == 'B11')
b11['latest_continuation_zh'] = '19d2原native6完整ZIP与原log/XML根审：实际merge6904/tree7518，原156=147PASS/7FAIL/2ignored；四阳性及文件/目录物理身份拒绝通过，严格外删1、ordinary-host Neither2与下游mutex poison4保留。其后仅追加workflow+script两路径为0f6148/treef717，actual mergeb5c23/tree29316父源eed+0f、10586叶逐一核。精确反事实已发布，尚未执行或取得资格；B11仍OPEN。'
b11['next_closure_gate_zh'] = '取得0f原工作流完整终态；每次执行先重新验证四个原阳性，负控须固定物理marker+597原断言+XML101+精确恢复全守卫。继续正常有限read roots同步完成、严格外删、后代寿命和真实loader/合法I/O接受。'
assert ledger['counts'] == {'CLOSED_SCOPED': 11, 'OPEN': 11, 'SCIENTIFIC_HOLD': 1}
write(OUT / 'continuation-blocker-progress-v6.json', ledger)

p = OUT / 'CONTINUATION_PROGRESS_V7.zh-CN.md'
s = p.read_text().replace('## 2. Windows ACL修复已发布，等待原156项终态', '## 2. 17:53固定观察：Windows ACL修复已发布，原156项尚在执行')
s = s.replace('## 5. 当前可交付与下一执行批', '## 5. 17:53固定观察时的可交付与下一执行批')
s += '''
## 6. 17:54–17:58后续增量：147/7/2与精确反事实发布

原native6于17:54后取得失败终态，完整官方artifact `13438699284`已重建：2,045,739字节、14成员全部CRC/哈希/原字节一致，官方SHA256为`341e7b854d79329ee0c42113957f1d8c86bd6b74229fb6b4b2f1562c25ca8285`。根审还逐一核对实际merge6904/tree7518的77个原源码叶、原完整log/XML及两次互斥选择的harness摘要。**真实总数为147通过、7失败、2忽略，原whole-target仍失败，Bazel exit3。**[根审原件验证](reviews/b11-native6-root-original-verification-v1.json)

四个相关原阳性全部实际PASS。物理替换例分别对真实文件和目录输出`returned_ok=false`、两个对象均未被误改。剩余七项分为一项真实strict外部删除越界、两项ordinary-host Neither前提失败、四项共享mutex被污染后的下游未到业务断言；不能把后四项当四个独立隔离失败，也不能删除它们。

在该阳性前提和独审成立后，17:58:50实际发布反事实追加head `0f6148ea3fbe9d1263354791d5cc63c7e66d4628` / tree `f717a84a856413d87a3b718b0bcae3adbd16b643`。仅新增脚本并修改原workflow，301新增、0删除、0Rust变化。实际merge `b5c23d8943a0a36a14a962175cb2ec75d22d5553` / tree `29316e75554590382268dafa77869fab0394a264`的两个父源是eed和0f，完整10,586叶核对无意外变化。PR REST曾返回旧base.sha5b；实际Git对象确认eed父源，两类观察分别保留。[发布回执](reviews/b11-identity-counterfactual-publication-v1.json)

新反事实尚无实际执行结果。每次新运行还必须重新验证四个原阳性及源码、索引、锁；唯一负控须原固定物理marker、597断言、一个失败/零忽略、XML101和精确恢复全部成立。新流程不能把原full失败变成成功。第2节的DISABLED manifest保留准备时身份，本段发布回执明确其后实际使能状态；不能把准备状态或发布状态写成已通过。

主eed完整API快照17:53:59–17:54:00为19 workflows / 53 jobs：18成功、31排队、1执行中、2跳过、1取消、0失败。相比17:07只增加一个V8 x86_64 Windows ptrcomp-sandbox成功，仍只是API状态，未授予业务用例资格。blocking及architecture仍pending且各0jobs。23份完整原件无损保留，不倒改17:53:52的固定cut。[新快照](ci/eed-status-1754-20261105/summary.json)

当前立即动作是取得0f的原终态和精确负控，同时独立审查正常read ACL同步准备小片；后者使用setup helper原binary目标，库156项不会代它验收。正式blocker仍11/11/1。
'''
p.write_text(s)

p = OUT / 'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md'
s = p.read_text()
s = s.replace('新19d2身份/权限修复已发布，原156项执行中；native5历史143PASS/10FAIL/2ignored，真实strict外删仍在', '19d2原156为147PASS/7FAIL/2ignored；精确反事实0f已发布待执行，真实strict外删仍在')
s = s.replace('先收齐19d2原终态及物理身份反事实；', '取得0f原终态、四阳性再验证及精确物理身份反事实；')
s = s.replace('先读取19d2原完整Windows156项终态；四项阳性原例通过后执行精确身份反事实；', '19d2四项阳性已实际通过；读取0f原完整Windows156项及精确身份反事实终态，保持原7失败；')
s = s.replace('当前最新为19d2两路径身份与真实权限控制候选，主产品仍eed，实际merge6904/tree7518已核正确父源并保留主产品14路径。原156项native6在17:49仍执行中；静态接受与已发布均不算原生通过。', '19d2两路径身份与真实权限控制候选已实际执行原156项：147PASS/7FAIL/2ignored，四项阳性通过；主产品仍eed。其后已发布0f精确反事实两路径追加，actual mergeb5c23/tree29316已核正确eed+0f父源并保留主产品14路径。反事实尚未实际执行，原strict删除等7失败继续保留。')
s = s.replace('1. 取得19d2原156项完整日志与工件，区分真实失败、前提失败和后续mutex poison。相关四项阳性实际PASS后进入已独审的精确身份反事实；任何来源/索引/锁漂移不覆盖。', '1. 19d2原156项完整原件及四项阳性已经根审通过，整体147PASS/7FAIL/2ignored保持失败；下一步取得0f原运行及精确身份反事实。任何来源/索引/锁漂移不覆盖，负控异常或恢复失败一律不算有效。')
s += '\n本计划还纳入17:54主eed的18成功/31排队/1执行/2跳过/1取消原API快照；新增成功仅为API状态，不冒充原业务日志或新容量证据。\n'
p.write_text(s)

p = OUT / 'LATEST.zh-CN.md'
s = p.read_text()
s = s.replace('Windows身份与权限修复已发布、原156项执行中', 'Windows原156项147通过/7失败/2忽略、精确反事实已发布待执行')
s = s.replace('head `19d2fdfcaefbb41cdf2a72754d695d4b47cb3f14`，原156项尚无终态，B11仍开放。', 'head `0f6148ea3fbe9d1263354791d5cc63c7e66d4628`，前一19d2原156项为147通过/7失败/2忽略；精确反事实尚无结果，B11仍开放。')
s = s.replace('本批整理截至2026-11-05 17:53:52 UTC，各原件保留独立观察时间；', '本批保留17:53:52 UTC固定cut，并单列17:54–17:58后续原终态及发布增量，各原件保留独立观察时间；')
p.write_text(s)
print(json.dumps({'counts': ledger['counts'], 'native6': native['combined_disjoint_counts'], 'counterfactual_head': publication['head'], 'counterfactual_executed': False}))
