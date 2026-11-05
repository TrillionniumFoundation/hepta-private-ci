"""Root supplement to the actual full archive verification; no product runs."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import xml.etree.ElementTree as ET

ROOT = Path('/workspace/scratch/07dd58cc9630')
P = ROOT / 'ci-audit/b09-original-exit-review-20261105'
REC = ROOT / 'hepta-audit-fifth/recovery-2113'


def dig(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}


def read(path):
    return json.loads(path.read_text())


cases = read(P / 'original-19-case-evidence-v1.json')
bridge = read(P / 'source-leaf-bridge-v1.json')
complete = read(P / 'complete-original-verification-v1.json')
pins = {'original-19-case-evidence-v1.json': 'dced05028fcf9c5c67d9200b6519f9db7567a955',
        'source-leaf-bridge-v1.json': '154ba0fd9a259bd30654d9a8dc6984cd7ffc7c50',
        'complete-original-verification-v1.json': 'e3cf7cc3590d1748df55537398ee3a0af465f8f7'}
for n, pin in pins.items():
    assert dig((P / n).read_bytes())['git_blob'] == pin
assert complete['original_files'] == 42 and complete['original_bytes'] == 60915164
assert complete['full_roster_equal_across_raw_xml_review_catalog'] is True
ledger = read(REC / 'ledger-v6.json')
exit_condition = next(e for e in ledger['items'] if e['id'] == 'B09')['original_exit_condition_zh']
assert cases['original_exit'] == exit_condition
fb9 = read(REC / 'b09-fb9-root-tree.actual.json')
assert fb9['sha'] == cases['source_tree'] == 'fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff'
assert fb9['truncated'] is False
entries = sorted(fb9['tree'], key=lambda e: (e['path'] + ('/' if e['type'] == 'tree' else '')).encode())
raw_tree = b''.join(('40000' if e['type'] == 'tree' else e['mode']).encode() + b' ' + e['path'].encode() + b'\0' + bytes.fromhex(e['sha']) for e in entries)
assert hashlib.sha1(b'tree ' + str(len(raw_tree)).encode() + b'\0' + raw_tree).hexdigest() == fb9['sha']
current_trees = {n: {e['path']: e for e in read(REC / f'trees/{n}.json')['tree']} for n in ['5b', 'e78', 'eed']}
assert len(bridge['complete_source_files']) == 22
for row in bridge['complete_source_files']:
    data = Path(row['identity']['path']).read_bytes()
    assert all(dig(data)[k] == row['identity'][k] for k in ['bytes', 'sha256', 'git_blob'])
    for n, t in current_trees.items():
        assert row['leaves'][n] == {k: t[row['logical_path']][k] for k in ['mode', 'type', 'sha']}
    assert row['leaves']['fb9'] == row['leaves']['eed']

raw_path = P / 'fb9-originals/full-workspace.log'
xml_path = P / 'fb9-originals/full-workspace.junit.xml'
raw = raw_path.read_bytes()
assert len(raw) == 33668423 and dig(raw)['sha256'] == '32a5b36b73badb7b9096759e0faf58aa6acb6679aac90f7dc593118c62f90735'
assert xml_path.stat().st_size == 4147101 and dig(xml_path.read_bytes())['sha256'] == 'a64ad0f88d187caa6dd0fa7c2dedd2f816a8366bedb1a93d026c169a16cf7ac8'
xml_cases = list(ET.parse(xml_path).iter('testcase'))
assert len(xml_cases) == 19506
full_fail = [e for e in xml_cases if e.find('error') is not None or e.find('failure') is not None]
assert len(full_fail) == 16
observations = []
for c in cases['cases']:
    b = c['raw_block']
    block = raw[b['byte_offset']:b['end_byte_offset_exclusive']]
    assert block == Path(b['path']).read_bytes()
    assert all(dig(block)[k] == b[k] for k in ['bytes', 'sha256', 'git_blob'])
    txt = block.decode()
    assert not re.search(r'Skipping\s+test|skipping\s+capability\s+test', txt, re.I), c['name']
    assert len(re.findall(r'^    test ' + re.escape(c['name']) + r' \.\.\. ok\r?$', txt, re.M)) == 1
    matches = [e for e in xml_cases if (e.get('classname'), e.get('name')) == (c['classname'], c['name'])]
    assert len(matches) == 1 and all(matches[0].find(n) is None for n in ['failure', 'error', 'skipped'])
    body = Path(c['source_excerpt']['path']).read_bytes()
    assert all(dig(body)[k] == c['source_excerpt']['identity'][k] for k in ['bytes', 'sha256', 'git_blob'])
    methods = sorted(set(re.findall(r'method: "([^"]+)"', txt)))
    if c['position'] <= 9:
        assert 'initialize' in methods and 'thread/start' in methods
        if c['position'] == 1:
            assert {'thread/inject_items', 'turn/start', 'turn/completed'} <= set(methods)
        else:
            assert 'turn/recover' in methods
        if c['position'] in [2, 4]:
            assert 'thread/resume' in methods and 'thread recovery candidate is no longer valid' in txt
        if c['position'] in [5, 6]:
            assert 'item/commandExecution/requestApproval' in methods and 'not interrupted' in txt
        if c['position'] == 6:
            assert 'is not the interrupted tail' in txt
        if c['position'] in [3, 7, 9]:
            assert 'turn/completed' in methods
        if c['position'] == 9:
            assert {'thread/queue/add', 'thread/queue/list', 'thread/read', 'hook/completed'} <= set(methods)
        if c['position'] == 8:
            assert 'code: -32600' in txt and 'turn/recover requires features.hepta_turn_recovery=true' in txt
    observations.append({'binary': c['classname'], 'name': c['name'], 'seconds': c['seconds'],
                         'raw_block': b, 'all_skip_prefixes_absent': True, 'actual_rpc_methods': methods})
assert len(observations) == 19
result = {'schema': 'hepta-b09-root-original-exit-closure-v1',
          'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'original_exit_condition_zh': exit_condition, 'decision': 'CLOSED_SCOPED',
          'scope': 'The original 19 named controls on native GNU/Linux source tree fb9, with identical 22 reviewed test/production source files and Cargo/lock leaves through 5b/e78/eed. This is not a new eed GNU execution or full-workspace qualification.',
          'native_job': cases['native_job'], 'native_source_tree': cases['source_tree'],
          'ordinary_HEAD': 'cabcb40d36e116beaa65750e1f674c52035da785',
          'original_command': cases['original_command'], 'host': cases['host'],
          'root_reexecuted_frozen_complete_verifier_exit': 0,
          'root_supplement_verifier_history': {'initial_exit': 1, 'reason': 'Directory mode 040000 must serialize as 40000 in a Git tree object.', 'corrected_exit': 0, 'original_evidence_changed': False, 'initial_observation': dig((REC / 'b09-root-verifier-initial-parser-observation.json').read_bytes())},
          'frozen_complete_verifier_identity': dig((P / 'verify_b09_originals.py').read_bytes()),
          'verified_inputs': {n: dig((P / n).read_bytes()) for n in pins},
          'full_original_archive': {'files': 42, 'bytes': 60915164, 'parts': 22,
              'actual_complete_decode_and_guard_verification': True},
          'raw_log': dig(raw), 'junit': dig(xml_path.read_bytes()),
          'complete_source_files': bridge['complete_source_files'],
          'tree_merkle_verification': bridge['trees'],
          'root_fresh_actual_fb9_top_level_GET': dig((REC / 'b09-fb9-root-tree.actual.json').read_bytes()),
          'root_more_inclusive_skip_check': 'Frozen independent v1 regex omitted the remote-environment skip text. Root independently rejects every Skipping test / skipping capability test prefix in all 19 complete raw blocks; all are absent. Nine AppServer cases additionally contain their actual business JSONRPC exchanges.',
          'cases': observations,
          'semantic_review': {
              'recovery': 'Eight original recover cases: 3 real recovery successes, 4 rejection scenarios, 1 feature-disabled negative. Real owned child termination/restart, exact turn/cwd/roots, single logical user input, queue deduplication, deferred resume hook and physical provider request counts are asserted.',
              'injection': 'Real AppServer RPC persists an untagged developer item, excludes it from the earlier request and includes it in the second physical request; exactly two requests.',
              'suspension': 'Original real root/descendant test rejects the currently live descendant, removes it, closes the old writer, observes durable Ready without terminal completion/abort, then reopens the exact turn/environment in a replacement runtime. The unit adapter skips only descendant inventory; the real integration case covers it.',
              'terminalization': 'Session-task panic reaches a terminal event and releases its slot. Cancelled finish/abort/suspend callers leave the detached owner alive. Panic/watchdog in an advanced terminalizer retain the exact fence and do not fabricate idle or terminal success.',
              'steer': 'No active turn and a mismatched expected turn identity are rejected by the original steer-only route.',
              'limits': 'Suspension checks a snapshot of loaded descendants; it is not a concurrent descendant-admission seal. Queued inputs and interactive waiters remain documented best effort. The original controls do not certify normal Root/Current/FinalUse acceptance.'},
          'original_enclosing_full_result': cases['enclosing_full_result'],
          'whole_candidate_qualified': False, 'B15_closed': False, 'new_native_or_product_test_execution': False,
          'exit_condition_changed': False, 'extra_universal_platform_exit_added': False}
out = REC / 'b09-root-original-contract-closure-v1.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(out), **dig(out.read_bytes()), 'decision': result['decision']}))
