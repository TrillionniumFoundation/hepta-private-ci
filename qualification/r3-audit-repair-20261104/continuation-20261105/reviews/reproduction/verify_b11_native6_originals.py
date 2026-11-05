from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path('/workspace/scratch/07dd58cc9630')
D = ROOT / 'architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127420172838'
OUT = ROOT / 'hepta-audit-fifth/inputs/b11-native6-root-original-verification-v1.json'
HEAD = '19d2fdfcaefbb41cdf2a72754d695d4b47cb3f14'
MERGE = '69040075a846c7032a3bafc7a0b623e7c0257619'
TREE = '75181bf7e4f119d08945003339b32aa0782ef41c'
TARGET = '//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests'

def read(p):
    return json.loads(Path(p).read_text())

def ident(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'computed_git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

def fid(p):
    return {'local_file': str(p), **ident(Path(p).read_bytes())}

api = read(ROOT / 'hepta-audit-fifth/inputs/b11-native6-artifacts-api.json')
artifact = next(x for x in api['structuredContent']['artifacts'] if x['id'] == 13438699284)
assert artifact['workflow_run']['id'] == 42077117788
assert artifact['workflow_run']['head_sha'] == HEAD
verify = read(D / 'artifact-verification.json')
zp = D / 'artifact-13438699284.zip'
zb = zp.read_bytes()
assert len(zb) == artifact['size_in_bytes'] == 2045739
assert hashlib.sha256(zb).hexdigest() == artifact['digest'].removeprefix('sha256:') == '341e7b854d79329ee0c42113957f1d8c86bd6b74229fb6b4b2f1562c25ca8285'
members = []
leaves = read(ROOT / 'hepta-audit-fifth/inputs/b11-native6-actual-merge-leaves.json')
assert leaves['tree'] == TREE and len(leaves['leaves']) == 77
with zipfile.ZipFile(zp) as z:
    assert z.testzip() is None
    assert len(z.namelist()) == len(set(z.namelist())) == len(verify['members']) == 14
    for row in verify['members']:
        name = row['name']
        b = z.read(name)
        i = ident(b)
        assert i['bytes'] == row['bytes'] and i['sha256'] == row['sha256'] and i['computed_git_blob'] == row['git_blob']
        assert z.getinfo(name).CRC == int(row['crc32'], 16)
        assert b == (D / 'members' / name).read_bytes()
        members.append({'path': name, **i})
    source = z.read('b11-token-mechanism-probe/source-head-tree.txt').decode().splitlines()
    assert source == [MERGE, TREE]
    assert not z.read('b11-token-mechanism-probe/source-status-before.txt').strip()
    assert not z.read('b11-token-mechanism-probe/source-status-after.txt').strip()
    assert z.read('b11-token-mechanism-probe/original-bazel-exit-code.txt').strip() == b'3'
    assert z.read('b11-token-mechanism-probe/console-copy-exit-code.txt').strip() == b'0'
    leaf_lines = z.read('b11-token-mechanism-probe/source-leaves.txt').decode().splitlines()
    expected = [f"{r['mode']} {r['type']} {r['sha']}\t{r['path']}" for r in leaves['leaves']]
    assert sorted(leaf_lines) == sorted(expected)
    manifest_name = 'bazel-execution-logs/failed-test-logs/invocation-zojxmwj2/manifest.json'
    manifest = json.loads(z.read(manifest_name))
    assert manifest['source'] == {'commit': MERGE, 'tree': TREE, 'tracked_worktree_dirty': False}
    assert manifest['complete_for_selected_targets'] is True and not manifest['errors']
    raw = z.read('bazel-execution-logs/failed-test-logs/invocation-zojxmwj2/targets/0000/test.log')
    xml_raw = z.read('bazel-execution-logs/failed-test-logs/invocation-zojxmwj2/targets/0000/test.xml')
    for row in manifest['files']:
        if row['target'] != TARGET:
            continue
        b = z.read(str(Path(manifest_name).parent / row['archive_relative_path']))
        assert len(b) == row['bytes'] and hashlib.sha256(b).hexdigest() == row['sha256']
    console = z.read('b11-token-mechanism-probe/bazel-console.log').decode()

ansi = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
text = raw.decode()
lines = text.splitlines()
clean_console = ansi.sub('', console).replace('\r', '')
terminal = [line.strip() for line in clean_console.splitlines() if line.startswith(TARGET + ' ')]
assert len(terminal) == 1 and 'cached' not in terminal[0].lower() and 'FLAKY' not in terminal[0]
assert re.fullmatch(re.escape(TARGET) + r'\s+FAILED in [0-9.]+s', terminal[0])
summaries = []
for number, line in enumerate(lines, 1):
    match = re.fullmatch(r'test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in (.+)s', line)
    if match:
        summaries.append({'line': number, 'original': line, 'counts': list(map(int, match.groups()[:5])), 'seconds': match[6]})
assert [row['counts'] for row in summaries] == [[92, 0, 0, 0, 64], [55, 7, 2, 0, 92]]
positive_names = [
    'acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object',
    'acl::tests::existing_native_deny_does_not_require_write_dac',
    'acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write',
    'token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes',
]
positive = []
for name in positive_names:
    matches = [(i, line) for i, line in enumerate(lines, 1) if line == f'test {name} ... ok']
    assert len(matches) == 1, (name, matches)
    positive.append({'name': name, 'line': matches[0][0], 'original': matches[0][1]})
physical_markers = []
for directory in ['false', 'true']:
    marker = f'deny_repair_identity: directory={directory} returned_ok=false replacement_changed=false original_changed=false'
    matches = [(i, line) for i, line in enumerate(lines, 1) if line == marker]
    assert len(matches) == 1
    physical_markers.append({'line': matches[0][0], 'original': matches[0][1]})

headers = list(re.finditer(r'(?m)^---- (.+) stdout ----\r?$', text))
assert len(headers) == 7
failures = []
for index, match in enumerate(headers):
    end = headers[index + 1].start() if index + 1 < len(headers) else text.index('\nfailures:\n', match.end())
    block = text[match.start():end]
    name = match[1]
    if name == 'token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces':
        category = 'ACTUAL_STRICT_TOKEN_OUTSIDE_DELETE_ESCAPE'
        assert 'token_tests.rs:434:5:' in block and '<    None,' in ansi.sub('', block)
    elif name in {
        'token::tests::workspace_capability_delete_routes_require_the_capability_in_all_four_cells',
        'unified_exec::tests::delete_permission_tests::legacy_delete_routes_require_workspace_capability_in_all_four_cells',
    }:
        category = 'ORDINARY_HOST_NEITHER_PRECONDITION_FAILED_BEFORE_RESTRICTED_SUBJECT'
        assert 'ordinary-host' in block and 'Neither' in block and 'pending=1 links=0' in block
    else:
        category = 'SHARED_TEST_MUTEX_POISON_NOT_INDEPENDENT_BUSINESS_ORACLE'
        assert 'PoisonError' in block
    failures.append({'name': name, 'classification': category, 'line': text.count('\n', 0, match.start()) + 1, 'original_block': block})
assert [r['classification'] for r in failures].count('ACTUAL_STRICT_TOKEN_OUTSIDE_DELETE_ESCAPE') == 1
assert [r['classification'] for r in failures].count('ORDINARY_HOST_NEITHER_PRECONDITION_FAILED_BEFORE_RESTRICTED_SUBJECT') == 2
assert [r['classification'] for r in failures].count('SHARED_TEST_MUTEX_POISON_NOT_INDEPENDENT_BUSINESS_ORACLE') == 4
xml = ET.fromstring(xml_raw)
cases = xml.findall('.//testcase')
assert len(cases) == 1 and cases[0].get('status') == 'run'
errors = cases[0].findall('error')
assert len(errors) == 1 and errors[0].get('message') == 'exited with error code 1'
assert not cases[0].findall('skipped')

result = {
    'schema': 'hepta-b11-native6-root-original-verification-v1',
    'verified_utc': datetime.now(timezone.utc).isoformat(),
    'head': HEAD, 'actual_checkout': MERGE, 'actual_tree': TREE,
    'run': 42077117788, 'job': 127420172838, 'attempt': 1,
    'decision': 'ORIGINAL_FOUR_POSITIVES_REACHED; B11_REMAINS_OPEN',
    'official_artifact': artifact, 'complete_archive': fid(zp),
    'all14_crc_sha_and_complete_local_originals_verified': True, 'members': members,
    'actual_77_source_leaves_equal_root_complete_merge_GET': True,
    'actual_source_leaves': leaves['leaves'], 'source_before_after_clean': True,
    'ordinary_exit_codes': {'bazel': 3, 'tee': 0, 'original_batched_outer_XML': 1},
    'original_target_terminal': terminal[0], 'original_summaries': summaries,
    'combined_disjoint_counts': {'total': 156, 'passed': 147, 'failed': 7, 'ignored': 2},
    'four_required_positive_cases': positive, 'file_and_directory_physical_markers': physical_markers,
    'original_failures': failures, 'raw': ident(raw), 'XML': ident(xml_raw), 'job_log': fid(D / 'job.log'),
    'counterfactual_enable_precondition': 'Satisfied for reviewed V2 source pins. Each future invocation must independently recheck its original full target and four positives before mutation.',
    'counterfactual_executed': False, 'counterfactual_qualified': False,
    'limits': [
        'No native rerun by this verifier; it reads only complete existing originals.',
        'Original whole target remains FAILED; new partial fixes do not close strict deletion or B11.',
        'Two disjoint harnesses are not retries. Interleaved individual result lines do not become invented unique outcomes.',
        'The original batch XML1 is not the planned direct exact-argument libtest101 negative endpoint.',
        'Four poisoned mutex failures do not reach independent business assertions.',
        'New exact counterfactual still requires physical marker, original assertion, single failure, exact fresh source and verified restoration.',
    ],
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'receipt': fid(OUT), 'counts': result['combined_disjoint_counts'], 'four_positives': True, 'B11': 'OPEN'}, ensure_ascii=False))
