"""Register only the already-created and independently read-back Git commit."""
from pathlib import Path
import hashlib
import json
import os

P = Path(__file__).parent

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read(name):
    return json.loads((P / name).read_bytes())

def payload(response):
    assert not response.get('isError')
    data = response.get('structuredContent')
    if data is None:
        data = json.loads(next(row['text'] for row in response['content'] if row['type'] == 'text'))
    if isinstance(data.get('content'), str):
        data = json.loads(data['content'])
    return data

def write(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with (P / name).open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    return {'path': str(P / name), **pin(raw)}

plan = read('ROOT-UPLOAD-PLAN.json')
closed = read('BLOB-UPLOAD-CLOSED.json')
assert closed['count'] == closed['actual_creates'] == 56 and closed['actual_reuses'] == 0
tree_create = payload(read('ACTUAL-CREATE-TREE-RESPONSE.json'))
tree_read = payload(read('ACTUAL-FORMATTED-ROOT-TREE.json'))
parent = payload(read('ACTUAL-SOURCE53-PARENT.json'))
created = payload(read('ACTUAL-CREATE-COMMIT-RESPONSE.json'))
commit = payload(read('ACTUAL-COMMIT-API-RESPONSE.json'))
assert tree_create['sha'] == tree_read['sha'] == plan['expected_tree'] == '42c1dd4e1a751c690c2800dfc3868e771dc9c70b'
assert parent['sha'] == plan['parent'] == 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
assert parent['tree']['sha'] == plan['base_tree'] == '440d4a8e09af4009e4d9ea067388826308da8803'
assert commit['sha'] == created['sha'] == 'b5209cfdf509e990f10922197b32540bf8c353a7'
assert commit['tree']['sha'] == plan['expected_tree'] and [p['sha'] for p in commit['parents']] == [plan['parent']]
originals = [{'path': str(P / name), **pin((P / name).read_bytes())} for name in
             ['ROOT-UPLOAD-PLAN.json', 'BLOB-UPLOAD-CLOSED.json', 'ACTUAL-CREATE-TREE-RESPONSE.json',
              'ACTUAL-FORMATTED-ROOT-TREE.json', 'ACTUAL-SOURCE53-PARENT.json',
              'ACTUAL-CREATE-COMMIT-RESPONSE.json', 'ACTUAL-COMMIT-API-RESPONSE.json']]
ledger_path = Path('publication-ledger.json')
before = ledger_path.read_bytes()
assert pin(before)['sha256'] == 'eeb77afef1dab84048648a2adb1cd929cdabacf55d28d04727fa19641a75fe5a'
ledger = json.loads(before)
assert ledger['current_source_commit'] == plan['parent'] and ledger['current_source_tree'] == plan['base_tree']
assert len(ledger['commits']) == 53 and len(ledger['created_blobs']) == 264 and len(ledger['artifact_checkpoints']) == 6
assert not ledger['branch_created'] and not ledger['pull_request_created']
with (P / 'LEDGER-BEFORE-SOURCE54.json').open('xb') as f:
    f.write(before); f.flush(); os.fsync(f.fileno())
ledger['commits'].append({'purpose': 'final_native_26_owner_fix_then_default_formatter_source54',
                          'sha': commit['sha'], 'tree': commit['tree']['sha']})
ledger['current_source_commit'] = commit['sha']
ledger['current_source_tree'] = commit['tree']['sha']
after_pin = write('LEDGER-AFTER-SOURCE54.json', ledger)
after = (P / 'LEDGER-AFTER-SOURCE54.json').read_bytes()
assert ledger_path.read_bytes() == before
temp = ledger_path.with_suffix('.source54-registration.tmp')
with temp.open('xb') as f:
    f.write(after); f.flush(); os.fsync(f.fileno())
os.replace(temp, ledger_path)
result = {'schema': 'hepta.root-source54-actual-registration-readback.v1',
          'status': 'ACTUAL_FORMATTED_CODE_COMMIT_CREATED_AND_READ_BACK', 'stage': 54,
          'source_commit': commit['sha'], 'source_tree': commit['tree']['sha'], 'parents': [plan['parent']],
          'tested_source_commit': plan['parent'], 'tested_source_tree': plan['base_tree'],
          'actual_native_formatted_tree_matched': True, 'exact_changed_blob_count': 56,
          'changed_rust': 54, 'changed_python': 2, 'total_approved_source_paths': 197,
          'native_HEAD_unchanged': 'bef6fa7645df9df12b69fda499e97eed25de6c75',
          'GitData_registration_is_not_native_checkout': True, 'originals': originals,
          'ledger_before': {'path': str(P / 'LEDGER-BEFORE-SOURCE54.json'), **pin(before)},
          'ledger_after': after_pin, 'source_commits': 54, 'binary_paths': 264, 'artifact_checkpoints': 6,
          'branch_created': False, 'pull_request_created': False,
          'post_fix_or_format_tests_executed': False, 'qualification_transferred_to_mutated_tree': False,
          'residual_warning_diagnostics': 3, 'strict_D_warnings_zero_claimed': False,
          'diagnostic_only': True, 'behavior_repair_claimed': False, 'science': 'HOLD', 'authority': 'DENY_ALL'}
proof = write('ROOT-REGISTRATION-READBACK.json', result)
print(json.dumps({'commit': commit['sha'], 'tree': commit['tree']['sha'], 'ledger': after_pin, 'readback': proof}))
