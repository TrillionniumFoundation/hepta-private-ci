"""Reopen the original B07 records; never execute or rewrite product tests."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path('/workspace/scratch/07dd58cc9630')
PKG = ROOT / 'ci-audit/published-eed4d6-ci-20261105/b07-source-review-v1'
OUT = ROOT / 'hepta-audit-fifth/recovery-2113/b07-root-original-contract-closure-v1.json'


def digest(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()}


def checked(record):
    body = Path(record['path']).read_bytes()
    actual = digest(body)
    assert all(actual[k] == record[k] for k in actual), (record['path'], actual)
    return body


def read(name):
    return json.loads((PKG / 'review-v1' / name).read_text())


review = read('independent-review.json')
gnu = read('gnu-22-case-evidence.json')
win = read('windows-6-binding-evidence.json')
bridge = read('source-leaf-bridge.json')
actual_tree = json.loads((ROOT / 'hepta-audit-fifth/recovery-2113/actual-tree-source-bridge.json').read_text())
ledger = json.loads((ROOT / 'hepta-audit-fifth/recovery-2113/ledger-v6.json').read_text())
exit_text = next(x for x in ledger['items'] if x['id'] == 'B07')['original_exit_condition_zh']
assert exit_text == review['original_exit']['frozen_ledger_exit_condition_zh']
assert len(set(review['frozen_exact_names'])) == 28

for record in review['evidence'].values():
    checked(record)
assert len(bridge['sources']) == len(actual_tree['source_rows']) == 20
source_rows = {r['path']: r for r in actual_tree['source_rows']}
source_proof = []
for row in bridge['sources']:
    checked(row['complete_source'])
    current = source_rows[row['logical_source_path']]
    for label in ('5b', 'e78', 'eed'):
        assert current[label]['sha'] == row['complete_source']['git_blob']
        assert current[label]['mode'] == row['mode']
        assert current[label]['type'] == 'blob'
    source_proof.append({'path': row['logical_source_path'], **digest(Path(row['complete_source']['path']).read_bytes())})

raw = checked(gnu['full_raw'])
xml_bytes = checked(gnu['full_xml'])
xml = ET.fromstring(xml_bytes)
all_cases = xml.findall('.//testcase')
assert len(all_cases) == 3967
assert len([c for c in all_cases if c.find('failure') is not None or c.find('error') is not None]) == 5
inputs = {Path(r['path']).name: json.loads(checked(r)) for r in gnu['input_records']}
before = inputs['original-owning-projects-before-source-guard.json']
after = inputs['original-owning-projects-after-source-guard.json']
for key in ('source_tree', 'leaf_count', 'ordinary_head', 'ordinary_index', 'locks',
            'untracked_relative_to_ordinary_index', 'unexpected_untracked', 'tool_pins_equal'):
    assert before[key] == after[key], key
assert before['source_tree'] == 'e78c819b8b1f435f8b37bea17b4ffdc724961aa2'
assert before['ordinary_head'] == 'cabcb40d36e116beaa65750e1f674c52035da785'
assert before['tool_pins_equal'] is True and before['unexpected_untracked'] == []
status = inputs['original-owning-projects-status.json']
command = inputs['original-owning-projects-command.json']
assert status['exit_code'] == 100 and command['attempt'] == 1
assert command['argv'] == gnu['command']['argv'] == status['argv']
assert command['retries'] == 0
assert inputs['metadata-binding.json']['complete_graph_equal'] is True
gnu_results = []
assert len(gnu['cases']) == 22
for row in gnu['cases']:
    name = row['test']
    block = checked(row['raw_block'])
    assert raw[row['raw_byte_start']:row['raw_byte_end_exclusive']] == block
    text = block.decode('utf-8')
    assert re.search(r'^        PASS \[\s+[0-9.]+s\] codex-core::all ' + re.escape(name) + r'$', text, re.M)
    assert text.splitlines().count('    test ' + name + ' ... ok') == 1
    assert len(re.findall(r'^    test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out; finished in [0-9.]+s$', text, re.M)) == 1
    assert not any(message in text for message in row['early_messages_checked'])
    cases = [c for c in all_cases if c.get('name') == name and c.get('classname') == 'codex-core::all']
    assert len(cases) == 1 and not any(cases[0].find(k) is not None for k in ('failure', 'error', 'skipped'))
    assert cases[0].attrib == row['junit_attributes']
    gnu_results.append({'name': name, 'result': 'PASS_NO_OBSERVED_EARLY_RETURN', 'raw_range': [row['raw_byte_start'], row['raw_byte_end_exclusive']], 'seconds': cases[0].get('time')})

log = checked(win['complete_target_log'])
win_xml_bytes = checked(win['complete_target_xml'])
collector_bytes = checked(win['collector'])
collector = json.loads(collector_bytes)
assert collector['source'] == win['source']
assert win['source']['tree'] == 'b26598d0d97d8d51e723bb5582137315f2174d35'
assert win['source']['tracked_worktree_dirty'] is False
win_xml = ET.fromstring(win_xml_bytes)
outer = win_xml.findall('.//testcase')
assert len(outer) == 1 and outer[0].get('status') == 'run'
assert not any(win_xml.findall('.//' + k) for k in ('failure', 'error', 'skipped'))
assert win_xml.find('.//system-out').text.encode('utf-8') == log
win_text = log.decode('utf-8')
names = re.findall(r'^test (\S+) \.\.\. ok$', win_text, re.M)
assert len(names) == len(set(names)) == 193
summaries = re.findall(r'^test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; (\d+) filtered out; finished in ([0-9.]+)s$', win_text, re.M)
assert len(summaries) == 3 and sum(int(s[0]) for s in summaries) == 193
assert all(int(s[0]) + int(s[1]) == 193 for s in summaries)
assert len(win['binding_cases']) == 6
for row in win['binding_cases']:
    assert win_text.splitlines().count('test ' + row['test'] + ' ... ok') == 1
union = [r['name'] for r in gnu_results] + [r['test'] for r in win['binding_cases']]
assert len(union) == len(set(union)) == 28 and set(union) == set(review['frozen_exact_names'])

archive_bytes = checked(win['full_archive'])
job = checked(win['complete_job_log'])
command_block = checked(win['original_command_block'])
assert command_block in job
assert not any(x in command_block for x in (b'--test_filter', b'--test_arg=', b'--test_arg '))
target_summary = win['original_target_summary'][0]['text'].encode('utf-8')
assert target_summary in job
assert b'9063c52a063b6f26c48e9418f6d8dbd14e9e06ff' in job
archive = zipfile.ZipFile(win['full_archive']['path'])
assert archive.testzip() is None
original_match = {label: [] for label in ('log', 'xml', 'collector')}
archive_members = []
for info in archive.infolist():
    if info.is_dir():
        continue
    body = archive.read(info)
    archive_members.append({'name': info.filename, **digest(body)})
    for label, target in (('log', log), ('xml', win_xml_bytes), ('collector', collector_bytes)):
        if body == target:
            original_match[label].append(info.filename)
assert all(len(v) == 1 for v in original_match.values()), original_match

result = {
    'schema': 'b07-root-original-contract-closure-v1',
    'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'decision': 'CLOSED_SCOPED',
    'original_exit_condition_zh': exit_text,
    'frozen_28_names_exactly_covered': True,
    'source_equality': {'complete_files': source_proof, 'actual_tree_proof': actual_tree['proof']},
    'gnu': {'complete_raw': gnu['full_raw'], 'complete_xml': gnu['full_xml'], 'command': gnu['command'],
            'cases': gnu_results, 'original_whole_scope': gnu['overall_actual_scope'],
            'source_index_locks_guard_equal': True, 'ordinary_head_actual': before['ordinary_head']},
    'windows': {'run': win['run_id'], 'job': win['job_id'], 'artifact': win['artifact_id'],
                'source': win['source'], 'complete_archive': win['full_archive'],
                'complete_job': win['complete_job_log'], 'all_archive_members_crc_verified': True,
                'archive_member_count': len(archive_members), 'target_member_exact_matches': original_match,
                'complete_target_roster': 193, 'binding_cases': [r['test'] for r in win['binding_cases']],
                'outer_xml_is_not_per_Rust_case_xml': True, 'collector_limits_verbatim': win['collector_retention']['limitations']},
    'manual_source_review': [
        'Original six binding bodies and helper: hidden model tool excluded; unconfigured server/unlisted tool/environment mismatch rejected; captured client/config/lifetime preserved; stale catalog rejected before preparation; revision read lock held through preparation.',
        'Original Hook executor bodies: before-attach zero actual calls; attached exact metadata; disconnect and mismatched ready environment leave call count unchanged, original5s/10s budgets.',
        'Original Hook MCP and TokenBudget negative bodies: actual ready server, allowlist/denylist and active policy reject before the transport marker and inject no output. Missing-server hook failure deliberately permits the normal user turn to continue.',
        'Original CodeMode handler-error body: actual exception text and attempted call metadata checked, no-exception success absent; original Windows ignore remains.'
    ],
    'limits': [
        'This closes only the unchanged B07 original contract; Q01 historical collection planning is not a new exit.',
        'No new eed GNU or new Windows binding execution. Byte-identical relevant20files bridge the two historical native sources to current eed.',
        'The original GNU owning-project scope has5FAIL/exit100; B15 whole-candidate/platform gates remain open.',
        'Windows18Hook cfg exclusion and CodeMode original ignore are not Windows passes.',
        'No new native command, test retry, product change, capacity poll or original-record edit.'
    ]
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(OUT), **digest(OUT.read_bytes()), 'decision': result['decision'], 'GNU': 22, 'Windows': 6}))
