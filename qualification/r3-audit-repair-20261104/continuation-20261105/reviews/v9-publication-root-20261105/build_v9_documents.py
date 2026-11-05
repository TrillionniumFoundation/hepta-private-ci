"""Build the current audit documents from fixed evidence and root decisions."""
from pathlib import Path
from collections import Counter
import copy
import datetime
import hashlib
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
REC = ROOT / 'hepta-audit-fifth/recovery-2113'
OUT = ROOT / 'hepta-audit-fifth/v9'
DOCS = OUT / 'documents'
PREFIX = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
DOCS.mkdir(exist_ok=True)


def load(path):
    return json.loads(path.read_text())


def digest(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()}


def section(text, first, following):
    return text[text.index(first):text.index(following)].rstrip() + '\n'


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    baseline = load(REC / 'ledger-v6.json')
    ledger = copy.deepcopy(baseline)
    accepted = load(OUT / 'root-accepted-closures.json')
    transitions = []
    for item in ledger['items']:
        if item['id'] in accepted:
            decision = accepted[item['id']]
            original = copy.deepcopy(item)
            item.update({k: v for k, v in decision.items() if k not in ['root_receipt', 'actual_git_blob']})
            item['closure_class'] = 'CLOSED_SCOPED'
            item['prior_item_before_v9'] = original
            item['root_closure_receipt'] = decision['root_receipt']
            item['root_closure_actual_git_blob'] = decision['actual_git_blob']
            transitions.append({'id': item['id'], 'from': original['closure_class'], 'to': item['closure_class'],
                                'original_exit_unchanged': True, 'root_receipt': decision['root_receipt'], 'actual_git_blob': decision['actual_git_blob']})
    byid = {i['id']: i for i in ledger['items']}
    byid['B02']['latest_continuation_zh'] = '主Draft已实际推进到67cc/3982，10582叶子相对eed仅3路径、相对5b累计15路径；实际merge b7a57d与head同树。新增为原4hunk格式修正及PTY日志保留一行，原锁/工作流/断言/预算不变。旧eed原失败保留，新head全部required及main接受仍OPEN。'
    for item in ledger['items']:
        item['next_closure_gate_zh'] = item['next_closure_gate_zh'].replace('eed', '67cc')
    byid['B11'].update({'current_label_zh': '原whole147/7/2；Git Bash与SDK变量修正已发布，native10待原终态',
        'next_closure_gate_zh': '观察021a59原native10：四项exact阳性、唯一物理负控marker/597/XML101、精确还原、独立setup helper；原whole七失败仍须据真实因果修复，并保strict token/合法I/O/外部写删/后代寿命原合同。',
        'latest_continuation_zh': 'native7交错PASS、native8裸bash进入WSL、native9在实际Git Bash内缺混合大小写SDK变量，三个原失败均保留。021a59将67主候选精确合入，恢复8个继承SDK变量的原拼写并绑定11个源码校验项；原命令/预算/还原不变。native10 run42124355402/job127584591851于22:47:55开始，完整收件前不授予新资格。'})
    byid['B15']['latest_continuation_zh'] = '主候选67cc的22:48:17–22:48:54完整API为19runs/53jobs：3success、17in_progress、31queued、2skipped。父源eed的原格式失败完整保留；67按原4hunk修正已发布，但未将源码补丁或旧成功改称新原fmt/full通过。required/main资格仍开放。'
    byid['B21']['latest_continuation_zh'] = '成功PTY日志保留的一行修正已随必要格式修正发布至67cc；保留已有11个target顺序和全部复制/错误处理。原Intel30例及2/5秒预算不变，旧2.023秒drain失败缺read字节/errno，实际原因和最终原CI仍未证成；B21继续OPEN。'
    if 'B20' not in accepted:
        byid['B20']['next_closure_gate_zh'] = '补齐旧desktop原negative/fixed日志、JUnit与source manifests，核同握手错误因果对照及原19真实关闭/断连；取得完整根审前保持OPEN。'
    original_exits = {i['id']: i['original_exit_condition_zh'] for i in baseline['items']}
    assert original_exits == {i['id']: i['original_exit_condition_zh'] for i in ledger['items']}
    assert list(original_exits) == [f'B{n:02}' for n in range(1, 24)]
    counts = dict(Counter(i['closure_class'] for i in ledger['items']))
    assert sum(counts.values()) == 23
    closed = [i['id'] for i in ledger['items'] if i['closure_class'] == 'CLOSED_SCOPED']
    opened = [i['id'] for i in ledger['items'] if i['closure_class'] == 'OPEN']
    score = f"{counts['CLOSED_SCOPED']}项限定范围闭合、{counts['OPEN']}项开放、1项科学验证暂缓"
    old_ci = load(OUT / 'current-ci-2221/summary.json')
    ci = load(OUT / 'current-ci-67-initial/summary.json')
    main_publication = ROOT / 'hepta-audit-fifth/main-format-retention'
    main_commit = load(main_publication / 'commit-ref-actual.json')['commit_actual']
    main_merge = load(main_publication / 'actual-merge-commits.json')['pr4797']['commit']
    prior_product = copy.deepcopy(ledger['product'])
    ledger['product'] = {'pr': 4797, 'draft': True, 'head': main_commit['sha'], 'tree': main_commit['tree']['sha'],
        'base': main_merge['parents'][0]['sha'], 'merge': main_merge['sha'], 'merge_tree': main_merge['tree']['sha'],
        'parent': main_commit['parents'][0]['sha'], 'exact_changed_paths_from_parent': 3,
        'cumulative_changed_paths_from_5b': 15, 'leaf_count': 10582, 'whole_candidate_qualified': False,
        'root_publication': 'reviews/main-format-retention-publication-20261105/commit-ref-actual.json'}
    publication = ROOT / 'hepta-audit-fifth/b11-env-publication'
    diag = load(publication / 'commit-ref-actual.json')
    merge = load(publication / 'actual-merge-commit.json')['commit_actual']
    current_b11 = {'pr': 4884, 'draft': True, 'head': diag['commit_actual']['sha'], 'tree': diag['commit_actual']['tree']['sha'],
        'parents': [p['sha'] for p in diag['commit_actual']['parents']], 'actual_merge': merge['sha'], 'actual_merge_tree': merge['tree']['sha'],
        'actual_merge_parents': [p['sha'] for p in merge['parents']], 'changed_paths_from_diagnostic_parent_855': 16,
        'changed_paths_from_main_67': 13, 'changed_paths_from_prior_actual_merge_cb5': 5,
        'environment_script_changes': 2, 'all11_source_pins_bound_to_actual_HEAD_and_merge': True,
        'root_publication': 'reviews/b11-env-publication-20261105/commit-ref-actual.json',
        'native8': {'run': 42113095723, 'job': 127545539398, 'head': '2338281bac08ff68b85dc2146c04a35598e6cbb4',
                    'whole': {'passed': 147, 'failed': 7, 'ignored': 2}, 'exact_executed': 0, 'source_mutation_attempted': False,
                    'counterfactual': 'INVALID_OR_NOT_RUN', 'cause': 'bare bash selected a WSL entry point; actual resolved executable path not recorded'},
        'native9': {'run': 42119482548, 'job': 127567774212, 'attempt': 1, 'status': 'completed', 'conclusion': 'failure',
                    'actually_started_at': '2026-11-05T22:22:59Z', 'completed_at': '2026-11-05T22:28:01Z', 'runner_id': 1000005182,
                    'actual_checkout': 'cb5aba57802272d7f535cd6ee2ac3e26334dbff6', 'actual_tree': 'bf1c52a3ed14ca2bd0276ffc693dccf6c1dbbb83',
                    'whole': {'passed': 147, 'failed': 7, 'ignored': 2}, 'counterfactual': 'INVALID_OR_NOT_RUN',
                    'exact_executed': 0, 'negative_executed': 0, 'source_mutation_attempted': False, 'helper': 'skipped',
                    'cause': 'actual Git Bash starts, then original wrapper rejects UniversalCRTSdkDir VCToolsInstallDir WindowsSdkDir before Bazel'},
        'native10': {'run': 42124355402, 'job': 127584591851, 'attempt': 1, 'status_at_first_frozen_snapshot': 'in_progress',
                     'actually_started_at': '2026-11-05T22:47:55Z', 'runner_id': 1000005390, 'source_head': diag['commit_actual']['sha'],
                     'terminal_qualification': 'NOT_YET_OBSERVED_AT_FIXED_SNAPSHOT'}, 'product_B11': 'OPEN'}
    native10_api = load(publication / 'native10-terminal-jobs.original.json')
    native10_job = next(j for j in json.loads(native10_api['content'])['jobs'] if j['id'] == 127584591851)
    assert native10_job['head_sha'] == current_b11['head']
    current_b11['native10']['latest_complete_API_observation'] = {
        'observed_utc': native10_api['observed_utc'], 'status': native10_job['status'], 'conclusion': native10_job['conclusion'],
        'completed_at': native10_job['completed_at'], 'steps': native10_job['steps'],
        'receipt': 'reviews/b11-env-publication-20261105/native10-terminal-jobs.original.json',
        'API_step_success_not_substitute_for_raw_positive_negative_restore_helper_validation': True}
    native10_root = load(ROOT / 'hepta-audit-fifth/b11-native10-root/ROOT_VERIFICATION.json')
    assert native10_root['actual_checkout'] == merge['sha'] and native10_root['B11'] == 'OPEN'
    current_b11['native10']['root_original_verification'] = {
        'receipt': 'reviews/b11-native10-root-20261105/ROOT_VERIFICATION.json',
        'actual_git_blob': 'a113b64b48ed88f1392a4498f3bd18e5caba9c5f',
        'whole': {'passed': 147, 'failed': 7, 'ignored': 2}, 'exact_positive': 4,
        'physical_negative': 1, 'negative_assertion': 'acl_tests.rs:597:9', 'negative_XML_exit': 101,
        'exact_original_source_restore': True, 'helper_actual_cases': 21, 'helper_ignored': 0, 'helper_filtered': 0,
        'all84_members_full_CRC': True, 'all7_compact_logs_fully_parsed': True,
        'actual_local_noncache_test_actions': 7, 'separate_XML_actions': 7,
        'original_target_timeout_millis': 300000, 'B11': 'OPEN'}
    current_b11['native10']['terminal_qualification'] = 'ORIGINAL_CONTROL_RESTORE_AND_HELPER_QUALIFIED_WHOLE_STILL_FAILED'
    byid['B11']['current_label_zh'] = 'native10原whole147/7/2；4正控/物理负控/还原及helper21已核'
    byid['B11']['next_closure_gate_zh'] = '维护已核4个exact阳性、唯一物理负控和精确还原、原21项helper；对原严格外部删除与2个宿主Neither前提取得真实token/文件系统因果证据后修复，再解决4个poison后续错误，保原strict token/合法I/O/外部写删/后代寿命合同。'
    byid['B11']['latest_continuation_zh'] += ' 根审完整84成员ZIP、7份compact及raw/XML后实际exit0：4exact阳性、唯一文件替换负控原597断言/XML101/exit3、完整原源精确还原及helper21项无ignore/无filter均成立。7真实动作local非cache、原300000ms；另7仅XML生成。原whole仍147/7/2，B11不闭合。'
    ledger.update({'schema': 'hepta-continuation-blocker-progress-v7', 'recorded_utc': now, 'counts': counts,
        'prior_progress_record': 'continuation-blocker-progress-v6.json', 'closure_transitions_v9': transitions,
        'original_23_status_exit_and_closure_class_unchanged': False, 'original_23_ids_and_exit_conditions_unchanged': True,
        'all_blockers_closed': False, 'whole_candidate_qualified': False,
        'historical_product_before_v9': prior_product, 'historical_limits_before_v9': copy.deepcopy(ledger['limits']),
        'historical_b11_diagnostic_PR_before_v9': ledger['b11_diagnostic_PR'], 'b11_diagnostic_PR': current_b11,
        'historical_ci_latest_observation_before_v9': ledger['ci_latest_observation'], 'historical_eed_ci_cut2221': old_ci, 'ci_latest_observation': ci,
        'current_v9': {'product': ledger['product'], 'counts': counts, 'closed_ids': closed, 'open_ids': opened,
                       'scientific_hold_ids': ['B18'], 'B11': current_b11, 'main_ci': ci,
                       'closure_root_authority': 'Root actual verification receipts, not subagent recommendations alone',
                       'historical_fields_preserved': 'Earlier version/postcut observations remain dated history, not current-head assertions'}})
    ledger['limits'][0] = '原23项ID与退出条件逐字不变；本版仅按实际根审新增B07/B09/B10/B20四项CLOSED_SCOPED，历史转移分别保留；其余分类不变。'
    (DOCS / 'continuation-blocker-progress-v7.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n')

    progress = f'''# 持续审计与实际修复进度 V8

**23项原blocker现为{score}。B07、B09、B10、B20按原退出条件完成根审闭合；完整产品尚未验收通过。**

本次文档整理时间为{now}；API、测试和源码各保留自己的观察时间，不能视为同一瞬时快照。原23个ID与退出条件逐字不变。主产品[Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)已发布为`{main_commit['sha']}`，tree `{main_commit['tree']['sha']}`，实际merge `{main_merge['sha']}`为相同树。本审计提交只登记证据、账本和计划；实际源码修正已在既有产品/诊断分支留下精确提交。

完整项目方向、阶段依赖及23项逐项计划见[计划V6](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V6.zh-CN.md)；机器可读状态见[ledger V7](continuation-blocker-progress-v7.json)。[前版进度V7](CONTINUATION_PROGRESS_V7.zh-CN.md)与[证据索引V8](evidence-index-v8-registered.json)继续作为历史，原失败没有被覆盖。

## 1. 本轮四项闭合及其边界

| ID | 已核原范围 | 实际证据与语义 | 仍然独立的资格 |
|---|---|---|---|
| B07 | 原Hook executor、MCP、TokenBudget与拒绝控制 | GNU e78原22名及Windows5b实际merge9063原6个MCP binding均PASS；20份完整相关源码三源相同；未配置server、allow/deny、环境错配、陈旧目录、CodeMode原错误路径均审到业务 | 原GNU所属整轮仍3962P/5F/exit100；Windows不适用/ignore不计通过，未授予eed全头资格 |
| B09 | 注入、idle-steer、挂起、8个恢复、panic/cancel/watchdog共19原名 | GNU fb9原full中19名均PASS；8recover包含3成功、4拒绝、1feature关闭负控。9个AppServer原例有实际JSONRPC；22份相关完整源码桥接到5b/e78/eed | 原full仍19490P/16F/exit100；57目录ignore及25其他early-return保留。正常Current/FinalUse及UI入口仍属B16 |
| B10 | 14个冻结连接/预热/压缩integration及另2个身份unit | GNU e78逐例原raw/JUnit全部PASS；Windows5b原14名最终ok，含3名首attempt共17条均ok；18份完整相关源码相同；Windows真实执行环境排除网络禁用早退 | 历史48平台映射保留待验；GNU整轮5F、Windows目标6/21 attempts失败不变；macOS、真实musl、Wine、eed全头没有被补写PASS |
| B20 | 原确定性HTTP/WebSocket握手、EOF及真实AppServer关闭/断连 | 旧GNU负源1P/1F稳定出现同Connection upgrade错误；修后19P，18个已有fn不变。另Windows5b原19名各一次ok、16个local非缓存动作；AppServer252叶子5b/e78/eed/67cc相同 | 旧GNU与当前lib有B23 signal差异，stdio原路径不变且新signal路径对Stdio禁用；原48平台映射、最终Unix及全工作区资格保持独立 |

根审分别实际运行证据验证器，检查完整原件、固定source、测试正文及真实业务断言：[B07根审](reviews/b07-original-exit-root-20261105/ROOT_CLOSURE.json)、[B09根审](reviews/b09-original-exit-root-20261105/ROOT_CLOSURE.json)、[B10根审](reviews/b10-original-exit-root-20261105/ROOT_CLOSURE.json)、[B20根审](reviews/b20-original-exit-root-20261105/ROOT_CLOSURE.json)。各独审建议与root裁决分别保存。

B09成功恢复验证同turn身份、canonical rollout尾部、pending队列及冷重启去重；拒绝控制覆盖cwd/workspace/provider不匹配、busy/completed/cross-thread及feature关闭。panic/watchdog不能伪造TurnComplete：清理未证实完成时保留fence，取消调用者后仍由detached owner完成实际清理。真实root挂起测试关闭后代、flush/关闭旧writer并重建runtime；后代集合是该实现的快照，不扩称并发准入封锁。

B10保留一个已接受的oracle修正：stable总请求从旧3改为**4 = 1次无工具prewarm +3次真实turn请求**，后三请求原turn-state不变，两个工具必须实际exit0并输出one/two。权限变化用例要求两条物理连接且请求分布`[1,3]`，首socket脚本结束仍保持读取；原GNU日志证实第二连接由实际身份改变产生。不能将这写成“全部旧请求数或断言字节不变”。动态模型/工作区/工具元数据仍进入真实wire和完整恢复指纹；provider、sandbox、review、thread来源等敏感变化继续拒绝复用。[逐例合同](reviews/b10-original-contracts-20261105/fourteen-contracts.json)

Windows成功stdout由libtest捕获，单看ok不足以排除早退。根审重开45成员ZIP、21对完整log/XML，并按官方Bazel9.3 schema完整解码30,370,252B compact日志、89,920条记录。42个action实际是21个真实测试和21个XML生成；真实测试均local、非cache、原900000ms预算且无network-disabled环境。XML是外层wrapper，14名来自原libtest正文，没有制造14个XML节点。[完整独审](reviews/b10-original-contracts-20261105/REVIEW.zh-CN.md)

B20旧负源的直接Git GET为404；根审以实际e729源加完整原补丁重建51,810B，字节哈希、原manifest和完整负树全部一致，没有冒称取到了旧Git对象。负树与固定树仅该fixture一叶不同，修后仍使用真实accept_async，重放完整原HTTP字节并保留BufReader预读；模型HTTP必须先完整结束，再发生真实WebSocket初始化。原stdio测试仍真实启动AppServer、发RPC、关闭stdin、等进程成功退出并等后端断连。Windows补证重开54成员ZIP和87,246条完整compact，16次真实测试之外另16次只是XML生成；1对XML有8处ESC替换，其余15对全文一致。原测试10/30秒预算和0重试保留。

## 2. Windows B11：源修正继续推进，原whole仍失败

[诊断Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)当前head为`{current_b11['head']}`，tree `{current_b11['tree']}`；两父是855733和主候选67cc。实际merge `{merge['sha']}`为相同树，两父是67cc和021a59。当前base已精确同步，GitHub实际mergeable=true；required CI仍未全部通过。

根审对5b共同祖先、855诊断源、67主源及旧实际merge做完整三方比较：唯一冲突是两支各自追加的日志保留项。合并同时保留setup helper与PTY，原11项顺序及其余字节不改。新两份Python执行器之外只纳入已审主候选变化；相对旧cb5实际merge恰为5路径。重算10,588叶子、1,571目录Merkle，与实际Git根及其全部root entry一致，11个helper pin全部与该HEAD相同。这里是完整预期叶子经Merkle绑定actual根，并未称新的递归全树GET。[发布原件](reviews/b11-env-publication-20261105/commit-ref-actual.json)、[全树与pin证明](reviews/b11-env-publication-20261105/root-tree-proof.json)、[实际merge](reviews/b11-env-publication-20261105/actual-merge-commit.json)

此前233版已加入正常read ACL同步准备与独立setup helper原目标。修正保持有限read roots、原权限及token；named mutex忙或已存在不等于当前roots已完成，必须走原成功/失败语义。原INFINITE等待及Command.status没有局部deadline的限制继续存在，不能称新增有界就绪。库的156项并不执行setup helper独立binary目标。

前版855733从当前workflow的`$BASH`取得Windows绝对bash.exe、记录完整字节哈希并用于三个subprocess；native9已证明进入实际Git Bash。它随后在Bazel之前被原SDK变量守卫拒绝。021a59共享一个环境构造函数，将8个继承SDK值恢复为原wrapper需要的大小写，原3个必需名称缺失/空值或别名冲突仍拒绝，可选缺席保持，不补造SDK路径。其余参数、120分钟限制、156项、四exact正控、物理负控、source/index/lock检查、finally还原及helper均不改。[Git Bash前修正](native-plan/b11-git-bash-launcher-20261105/full.patch)、[环境修正](native-plan/b11-windows-env-casing-20261105/full.patch)、[独立完整复核](reviews/b11-env-casing-independent-20261105/review.json)

原生PATH含Python3.12.10，但没有记录实际解析后的解释器路径或sys.version。完整CPython标签源码和云端有界对照复现旧映射的同106B错误；随后native10已实际完成四正控、负控、还原及helper。修正后的Windows执行结果成立，仍不把PATH当成精确解释器版本测量。

| 原运行 | 源与实际结果 | 根审判断 |
|---|---|---|
| native6 | 19d2；147P/7F/2I，四项相关阳性通过 | 原严格删除等失败保留，身份修正不能升级为whole通过 |
| native7 | 0f；同样147P/7F/2I，第四个PASS因并发交错未被旧收集条件识别 | 负控未运行，INVALID；完整原件重开后原始行仍保留交错 |
| native8 | 233；147P/7F/2I；第一个exact命令0.047秒exit1，完整UTF-16LE输出为WSL未安装发行版 | 裸bash在Bazel前失败；实际解析exe路径未记录。0 exact、0源修改尝试，helper正确跳过，INVALID_OR_NOT_RUN |
| native9 | 855733实际checkout cb5aba；147P/7F/2I；首exact在0.031秒exit1，完整106B为三个SDK名称缺失 | Git Bash入口有效；仍是Bazel前失败，0 exact/0 negative/0源修改，helper跳过，INVALID_OR_NOT_RUN；22成员原ZIP与日志保全 |
| native10 | 021a59实际checkout5ce734；147P/7F/2I；4个exact正控真实通过、唯一物理负控命中原597断言/XML101、完整原源精确还原；独立helper21P/0I/0filtered | 根审实际exit0，84ZIP成员和7份compact全核。7真实测试均local非cache且原300000ms，另7只是XML生成。整个B11仍OPEN |

[native7根验证](reviews/b11-native7-root-20261105/ROOT_VERIFICATION.json)与[native8根验证](reviews/b11-native8-root-20261105/ROOT_VERIFICATION.json)保完整失败。native8 XML system-out与raw之间正好78个ESC字节被序列化为问号，其余字符相同；两原件均未改写。原前一版57项云端Python检查不扩张为855733或原生通过。

[native9完整原件登记](generated-evidence/b11-pr4884-ci/native9-post-v8-registration.json)保留原106B环境错误及零执行事实；[native10原API终态](reviews/b11-env-publication-20261105/native10-terminal-jobs.original.json)和[根审原件验证](reviews/b11-native10-root-20261105/ROOT_VERIFICATION.json)分别保留。负控实际到达文件替换一例的原断言；没有将尚未到达的目录负控说成运行通过。source/index/test/lock摘要在受控修改之外保持不变，普通完成路径精确恢复；原硬取消无法保证finally运行的限制仍保留。原whole的78处ESC及负控102处ESC在XML中变问号，两份原件均未修改。

## 3. 主候选CI已前进，但仍有真实失败与待执行项

父源eed在22:21:18–22:21:48 UTC的原API覆盖19run/55job：**35成功、3执行中、4排队、1失败、10取消、2跳过**。唯一实际失败job为Supervisor Ubuntu `127372805931`的`cargo +1.95.0 fmt --all -- --check`。五个workflow failure并不等于五个失败测试job。[父源55项摘要](current-head-ci/cut-20261105T2221/summary.json)、[父源23份完整API](current-head-ci/cut-20261105T2221/transport-manifest.json)

67cc已按原完整1,664,686B格式日志的4hunk修正两个测试文件：environment_selection仅空白，control_tests为空白及一个可选tuple尾逗号；调用、字符串、断言和时间预算不改。同一必要发布加入PTY成功日志保留一行，共3路径，10582叶子的完整Merkle绑定实际根，实际main merge为同树。[发布与三路径](reviews/main-format-retention-publication-20261105/root-tree-proof.json)、[原格式证据完整登记](current-head-ci/format-correction-20261105/delivery-v2/registry.actual.json)

新源67cc的22:48:17–22:48:54 UTC完整20份API，覆盖19run/53job：**3成功、17执行中、31排队、2跳过**；run顶层有10queued、5in_progress、2pending、2skipped，不能用顶层queued推断内部job未跑。原格式器输出补丁不等于新源码原生fmt通过，旧结果也不转记新head。API状态不代业务证据，也不构成Linux容量释放依据。B02/B15继续开放。[新源53项摘要](current-head-ci/cut-67cc-20261105T2248/summary.json)、[20份原API无损归档](current-head-ci/cut-67cc-20261105T2248/transport-manifest.json)

此前浏览器等待链与REST状态不一致的观察继续保留。旧architecture后来实际cancelled，不能归因于本轮助手操作；旧blocking仍排队。浏览器授权流程已被用户取消，本轮没有发送取消/重跑或再次请求登录。[原取消观察](current-head-ci/post-v8-recovery-20261105/old-ci-auth-cancel-observation.json)

## 4. Linux完整门、正常入口及其它剩余条件

唯一ca1 firststart `1a1ac90de70-fc05-5557`在任何源码修改、build/catalog/test/hygiene前退出：磁盘139,231,227,904B达到原64GB门，可用RAM25,061,957,632B低于原34,359,738,368B。最后一次已记录容量仍不足；没有新的明确容量证据前不重复启动。原jobs4、193成员/1501节点及19,563目录项（19,506可执行/57原ignore）保持，不能以selected补默认full。

B16旧driver仍为UNKNOWN。完整保留身份查询取得2463/2463个唯一ID，但只有created/execution_mode/host/id/launch_state五字段，没有idempotency key、argv、cwd或fingerprint，不能据此匹配或证明旧driver未启动；两次inventory变更错误也保留。没有重放旧任务。已有Foundation范围通过也不会签发Current/FinalUse或正常UI的执行权。下一步仍需真实Root handoff、protected checkpoint/verifier、Current、三池、issuer、listener custody与真实caller同链接受。SQLx拒绝COMMIT后的donor原红绿已核；本产品两个构造器及真实物理换连接、SQLite531和事务状态仍须原验收。

B20按原合同闭合，边界见上节。B21原Intel30例及2/5秒预算不变，旧2.023秒drain失败缺read字节/errno，原因仍未证明；成功PTY日志保留已随67cc发布，但只保已有日志，不触发额外测试，也不保证成功case stdout一定被libtest释放。B23要求最终原Unix CI，不能只用旧单信号/双drain局部通过闭合。

B19按Bao/Chain/HIA分别取得固定版本及真实consumer接受，DENY_ALL和未签发的安全证书状态保持。B18是科学采用门：必须新的事前冻结2×2、重点D−B、独立数据、充分精度、全部失败及完整成本；已有J−C、五fit和记录重放不替代它。实验未过时继续使用强普通默认。

## 5. 当前工作顺序

1. 维护native10已核四项正控、物理负控、还原与21项helper，继续原whole失败修复。原7失败按1个严格外部删除、2个普通宿主前提和4个poison后续错误分类，先取得真实TokenPrivileges/文件系统与派生token因果对照，不预判SeRestorePrivilege就是原因。
2. 收齐67cc各平台原结果，核原格式门实际结果；源码变动后重新绑定新head/base/merge，不转记父源成功。
3. 维护B07/B09/B10/B20四项新根审的原合同范围，保留所有旧失败、source差异、重建方式及最终平台待验。
4. 有具体新容量证据时续接原Linux完整门；实际测试完成后依次scoped fix、fmt，再核最终required CI和main基线。
5. 按[计划V6](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V6.zh-CN.md)推进正常Root/Current/FinalUse/UI以及外部系统；研究接受保持独立。

已闭合：{' / '.join(closed)}。仍开放：{' / '.join(opened)}。B18科学暂缓。**全部blocker尚未闭合，整个候选也尚未达到可合入main的资格。**
'''
    (DOCS / 'CONTINUATION_PROGRESS_V8.zh-CN.md').write_text(progress)

    old_plan = (REC / 'plan-v5.zh-CN.md').read_text()
    structure = section(old_plan, '## 1. 项目全局结构和实际成熟度', '## 2. 当前阻塞的依赖顺序')
    wiring = section(old_plan, '## 4. 正常产品入口要完成的接线', '## 4A. 其他正在推进的项目线与整合边界')
    parallel = section(old_plan, '## 4A. 其他正在推进的项目线与整合边界', '## 5. 后续发展阶段与优先级')
    stages = section(old_plan, '## 5. 后续发展阶段与优先级', '## 6. 执行纪律、进度汇报与完成定义')
    discipline = section(old_plan, '## 6. 执行纪律、进度汇报与完成定义', '### 固定来源')
    table = '\n'.join(f"| {i['id']} | {i['closure_class']} / {i['name']} | {i['next_closure_gate_zh']} | {i['original_exit_condition_zh']} |" for i in ledger['items'])
    plan = f'''# 项目发展方向与当前执行计划 V6

**项目当前交付主线是一个由真实正常入口驱动、跨平台可验收、权限与效果可追踪的Hepta垂直流程。** 40模块、91工作包的范围已经定义；当前执行重点是固定候选原平台资格、Windows严格权限边界、Root/Current到真实caller的接线。

本计划以主产品67cc/3982为基准，诊断支线B11已推进到021a59/36ca并同步该主源。23项原blocker为**{score}**，本版新增B07/B09/B10/B20四项原范围根审闭合。所有字面退出条件保持；完整运行、平台、正常产品、外部和科学接受分别保留。最新事实见[进度V8](CONTINUATION_PROGRESS_V8.zh-CN.md)及[ledger V7](continuation-blocker-progress-v7.json)。

{structure}
## 2. 当前阻塞的依赖顺序

| 批次 | 当前事实 | 下一动作 | 完成标准 |
|---|---|---|---|
| A 主整合候选 | 67cc新3路径，相对5b累计15；首53job为3成功/17执行/31排队/2跳过 | 原4hunk格式修正已发布，收齐新源真实原结果及required门 | 原required全过，source/base/merge完整；API成功不代业务证据 |
| B Windows严格隔离 | native10 whole147P/7F/2I；4正控/物理负控/精确还原及21helper已根审 | 按1strict外部删除、2宿主Neither前提及4poison后续取得因果证据并修复；不降低原断言 | 原严格token、合法read/write、外部四类写删和后代寿命均达标 |
| C 已完成原合同 | B07/B09/B10/B20新增闭合，B08/B13/B22等保持 | 维护source桥、有效负控、原断言和明确scope；最终平台门继续独立 | 原名/预算/业务边界明确；未取平台仍保未知或OPEN |
| D Linux默认full | 唯一firststart在source/build/test前因RAM不足原32GiB门停止 | 仅凭实际新容量依据续接原prepared目录、七helper、完整catalog及无筛选full | 原64GB/32GiB/jobs4和所有守卫达标，原full实际终态通过 |
| E 最终hygiene/main | 当前full未完成；required与目标main未获得完整资格 | 按原测试→scoped fix→fmt执行；绑定最终head/base/merge并读原required | 所有必需门通过，合成merge与发布树相同，历史失败完整保留 |
| F 正常产品入口 | Foundation限定接受已在；旧driverUNKNOWN，Current/FinalUse/normal UI未全接通 | 确切任务身份→Root checkpoint→Current→三池→FinalUse→listener→normal caller | 同源Root/Session/签名Objective与独立provider/target的任务/取消/丢ACK/重启接受 |
| G 外部与科学 | Bao/Chain/HIA尚未独立接受，D−B原门HOLD | 固定接口/版本/consumer；另行事前冻结新2×2及完整成本 | 外部真实回执；科学未过则强普通默认维持 |

A/B/C/F可并行做可归属的准备和修复；D/E由实际前序完成驱动，不按排队时间承诺完成日期。没有已观察到满足原Linux完整容量门的主机，不重复轮询或降低门槛。具体主机权限不等于产品authority。

## 3. 23项blocker逐项工作清单

下表的退出条件逐字来自前版冻结ledger，仅按根审结果推进分类。限定闭合不自动代表整个Core、全工作区、全部平台或main通过。

| ID | 当前分类 / 范围 | 下一动作或维护重点 | 原退出条件 |
|---|---|---|---|
{table}

{wiring}
{parallel}
{stages}
{discipline}
### 本版可执行顺序与固定来源

先继续B11原whole真实失败修复并收齐67cc原格式/平台终态；维护本版四项原范围闭合及native10原生子范围接受。Linux完整门需先把准备源精确绑定当前67cc，再在新容量依据后续接；完成测试后按原顺序hygiene，再核main资格。正常Root/Current/FinalUse与外部真实接受可并行推进其依赖，科学采用单独按原门判断。

- [全量仓库审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)、[当前进度V8](CONTINUATION_PROGRESS_V8.zh-CN.md)、[当前23项ledger](continuation-blocker-progress-v7.json)
- [canonical五文件同源桥接](reviews/canonical-product-direction-bridge-v1.json)、[原退出选择清单](reviews/original-exit-selection-5b/selection-checklist.json)
- [B07根审](reviews/b07-original-exit-root-20261105/ROOT_CLOSURE.json)、[B09根审](reviews/b09-original-exit-root-20261105/ROOT_CLOSURE.json)、[B10根审](reviews/b10-original-exit-root-20261105/ROOT_CLOSURE.json)、[B20根审](reviews/b20-original-exit-root-20261105/ROOT_CLOSURE.json)
- [当前主候选53job原API](current-head-ci/cut-67cc-20261105T2248/transport-manifest.json)、[B11实际发布](reviews/b11-env-publication-20261105/commit-ref-actual.json)、[native8原失败根审](reviews/b11-native8-root-20261105/ROOT_VERIFICATION.json)
- [SQLx拒绝提交donor独审](reviews/pr4855-refused-commit-reuse/REVIEW.zh-CN.md)、[Intel PTY独审](reviews/b21-intel-current-followup/independent-review.json)
- [主产品Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)、[B11诊断Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)
'''
    (DOCS / 'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V6.zh-CN.md').write_text(plan)
    latest = f'''# 当前审计入口

截至{now}整理：**{score}，完整产品资格仍开放**。

- [全量项目方向与后续执行计划V6](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V6.zh-CN.md)
- [当前实际修复进度V8](CONTINUATION_PROGRESS_V8.zh-CN.md)
- [23项机器可读ledger V7](continuation-blocker-progress-v7.json)
- [本批实际登记证据索引V9](evidence-index-v9-registered.json)
- [上一版证据索引V8](evidence-index-v8-registered.json)

本版新增B07/B09/B10/B20原范围闭合。主产品67cc/3982、B11诊断021a59/36ca均已实际发布。native10原whole147/7/2仍失败；4正控、物理负控、精确还原及21helper已经原件根审，B11保持OPEN。新主候选首53job为3成功、17执行中、31排队、2跳过；各原件时间和失败均保留。原23个退出条件不变，不能将限定闭合数量换算为产品完成百分比。
'''
    (DOCS / 'LATEST.md').write_text(latest)
    rows = []
    for f in sorted(DOCS.iterdir()):
        body = f.read_bytes()
        rows.append({'local_file': str(f), 'path': PREFIX + f.name, 'mode': '100644', **digest(body)})
    (OUT / 'document-upload-plan.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    receipt = {'created_utc': now, 'counts': counts, 'closed_ids': closed, 'open_ids': opened, 'original_23_ids_and_exits_equal': True,
               'root_closure_transitions': transitions, 'files': rows, 'evidence_only': True, 'whole_candidate_qualified': False}
    (OUT / 'document-build-check.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'counts': counts, 'files': [{k: r[k] for k in ['path', 'bytes', 'git_blob']} for r in rows]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
