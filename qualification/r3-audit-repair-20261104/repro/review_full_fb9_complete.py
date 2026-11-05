import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path('/workspace/scratch/07dd58cc9630')
WORK = ROOT / 'hepta-audit-fourth'
ARCHIVE = ROOT / 'ci-audit/recovered-20261105/full-fb9-complete-archive'
DECODED = ARCHIVE / 'decoded-verified-v1'
SOURCE = 'fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff'


def ident(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}


def check(b, wanted):
    actual = ident(b)
    assert all(actual[k] == wanted[k] for k in ('bytes', 'sha256')), (actual, wanted)
    return actual


def load(name):
    return json.loads((DECODED / name).read_bytes())


transport = json.loads((ARCHIVE / 'transport-manifest-v1.json').read_bytes())
native = json.loads((ARCHIVE / 'native-export-manifest-v1.json').read_bytes())
assert native == transport['native_export']
native_assets = {a['name']: a for a in native['assets']}
assets, originals, chunk_rows = [], [], []
exact_dir = WORK / 'inputs/full-fb9-exact-git-chunks'
exact_dir.mkdir(exist_ok=True)
for asset in transport['assets']:
    parts = []
    offset = 0
    for part in asset['chunks']:
        assert part['offset'] == offset
        saved = (ARCHIVE / part['path']).read_bytes()
        if len(saved) == part['bytes'] + 1 and saved.endswith(b'\n'):
            b = saved[:-1]
            transport_lf = True
        else:
            b, transport_lf = saved, False
        actual = check(b, part)
        (exact_dir / (actual['blob'] + '.b64.txt')).write_bytes(b)
        chunk_rows.append({'asset': asset['name'], 'offset': offset,
                           'local_transport_terminal_lf_separately_excluded': transport_lf, **actual})
        offset += len(b)
        parts.append(b)
    encoded = b''.join(parts)
    na = native_assets[asset['name']]
    assert len(encoded) == na['base64_bytes'] and hashlib.sha256(encoded).hexdigest() == na['base64_sha256']
    for part in na['parts']:
        check(encoded[part['offset']:part['offset'] + part['bytes']], part)
    zipped = base64.b64decode(encoded, validate=True)
    check(zipped, asset['gzip'])
    assert zipped[:3] == b'\x1f\x8b\x08' and int.from_bytes(zipped[4:8], 'little') == 0
    b = gzip.decompress(zipped)
    actual = check(b, asset['original'])
    assert (DECODED / asset['name']).read_bytes() == b
    assets.append({'name': asset['name'], **actual, 'strict_base64_gzip_crc_reopened': True})
    if asset['name'] == 'complete-small-originals.json':
        small = json.loads(b)
        for original in small['files']:
            raw = original['content'].encode()
            one = check(raw, original)
            assert (DECODED / 'small' / original['name']).read_bytes() == raw
            originals.append({'name': original['name'], **one})
    else:
        originals.append({'name': asset['name'], **actual})
assert len(originals) == 42 and sum(x['bytes'] for x in originals) == 60915164
assert len({x['name'] for x in originals}) == 42

review = load('full-workspace-review.json')
selection = load('full-workspace-selection.json')
catalog = load('full-workspace-catalog.stdout')
metadata = load('workspace-metadata.stdout')
terminal = load('terminal.json')
status = load('full-workspace-status.json')
command = load('small/full-workspace-command.json')
xml = ET.parse(DECODED / 'full-workspace.junit.xml').getroot()
cases = list(xml.iter('testcase'))
keys = lambda rows: Counter((x['classname'], x['name']) for x in rows)
xml_keys = Counter((c.get('classname'), c.get('name')) for c in cases)
assert xml_keys == keys(review['cases']) == keys(selection['expected_selected'])
assert len(cases) == 19506
result = Counter()
terminals = Counter()
xml_by_key = {}
for case in cases:
    elements = [c for c in case if c.tag in ('failure', 'error', 'skipped')]
    assert not any('rerun' in c.tag.lower() or 'flaky' in c.tag.lower() for c in case)
    outcome = 'PASS' if not elements else 'FAIL' if elements[0].tag == 'failure' else elements[0].tag.upper()
    if elements:
        assert len(elements) == 1
        terminals[(elements[0].tag, elements[0].get('type'))] += 1
    result[outcome] += 1
    xml_by_key[(case.get('classname'), case.get('name'))] = case
assert dict(result) == review['counts'] == terminal['full_counts'] == {'PASS': 19490, 'FAIL': 16}
assert terminals == {('failure', 'test failure with exit code 101'): 16}
for c in review['cases']:
    original = xml_by_key[(c['classname'], c['name'])]
    assert c['seconds'] == original.get('time')
    failure = original.find('failure')
    assert c['failure'] == (failure.text or '' if failure is not None else '')


def roster(c):
    return Counter((bid, name, bool(test['ignored']))
                   for bid, suite in c['rust-suites'].items()
                   for name, test in suite['testcases'].items())


current_roster = roster(catalog)
assert sum(current_roster.values()) == 19563
assert sum(v for (_, _, ignored), v in current_roster.items() if ignored) == 57
assert Counter({(a, b): v for (a, b, ignored), v in current_roster.items() if not ignored}) == xml_keys
reference_binding = load('small/full-frozen-App-roster-binding.json')
reference_path = ROOT / 'ci-audit/recovered-20261105/app-parent-liveness-v2-complete-archive/decoded-verified-v1/parent-liveness-final-eight-catalog.stdout'
reference_raw = reference_path.read_bytes()
check(reference_raw, reference_binding['reference'])
assert reference_binding['reference']['source'] == 'c6fbcfa0d1ba3b1556f601dc4ca3a7734328b9f7'
assert roster(json.loads(reference_raw)) == current_roster
assert len(metadata['workspace_members']) == 193 and len(metadata['resolve']['nodes']) == 1501
assert hashlib.sha256((DECODED / 'workspace-metadata.stdout').read_bytes()).hexdigest() == '3a53323eae920e2e53dcb3e334128a4aff63cfb51840793e9150d617d2c9ba18'
assert review['binary_before'] == review['binary_after'] == selection['test_binaries_after_catalog_before_just']
assert review['helpers_before'] == review['helpers_after'] == selection['helpers_after_catalog_before_just']
assert len(review['binary_before']) == 321 and len(review['helpers_before']) == 33
assert command['argv'] == ['just', 'test', '--locked', '--cargo-profile', 'dev-small', '--no-tests', 'fail', '--retries', '0', '--success-output', 'immediate']
assert status['argv'] == command['argv'] and status['exit_code'] == review['exit_code'] == terminal['full_original_command_exit_code'] == 100
assert status['source_before'] == status['source_after'] == review['source'] == selection['source'] == terminal['source'] == SOURCE
assert review['retries'] == 0 and not review['passed'] and not terminal['full_passed']
assert not selection['existing_unmatched'] and len(selection['existing_ignored']) == 57

guards = []
for p in sorted((DECODED / 'small').glob('*-source-guard.json')):
    guard = json.loads(p.read_bytes())
    assert guard['expected_source'] == guard['actual_source'] == SOURCE
    assert guard['head'] == 'cabcb40d36e116beaa65750e1f674c52035da785'
    assert guard['ordinary_index']['bytes'] == 1222758 and guard['ordinary_index']['sha256'] == 'c41b4d7645b2b88431ed024e9cc683e31d43fafe7290280eaf0bae656fd6a922'
    assert not guard['untracked_source_paths'] and not guard['allowed_untracked_source_paths']
    assert guard['locks']['codex-rs/Cargo.lock']['sha256'] == '4a7a5535cf045089458468411e126b5f59bc6bbf34fc0deead9b0c1b8d84000a'
    assert guard['locks']['MODULE.bazel.lock']['sha256'] == '11f8a421224b9b05f32c4c14054e8868083d989fc497310c8d51e1156f189ca3'
    guards.append(p.name)
assert len(guards) == 10

raw_bytes = (DECODED / 'full-workspace.log').read_bytes()
raw = raw_bytes.decode()
ansi = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
plain = ansi.sub('', raw)
raw_cases = defaultdict(list)
for match in re.finditer(r'^\s*(PASS|FAIL|TIMEOUT|SKIP)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+([^\r\n]+?)\s*$', plain, re.M):
    key = (match[3], match[4])
    if key in xml_keys:
        raw_cases[key].append({'result': match[1], 'seconds': match[2]})
assert set(raw_cases) == set(xml_keys)
for key, found in raw_cases.items():
    expected = 'FAIL' if xml_by_key[key].find('failure') is not None else 'PASS'
    assert {f['result'] for f in found} == {expected}, (key, found)
summaries = re.findall(r'^\s*Summary\s+\[[^\r\n]+$', plain, re.M)
assert len(summaries) == 1 and '19506 tests run: 19490 passed' in summaries[0] and '16 failed, 57 skipped' in summaries[0]
early = review['early_return_case_observations']
assert len(early) == 25 and not review['unbound_early_return_notices']
for row in early:
    block = row['original_raw_block']
    actual = raw_bytes[block['byte_offset']:block['byte_offset'] + block['bytes']]
    check(actual, block)
    assert actual.decode() == block['content']
    assert xml_by_key[(row['classname'], row['name'])].find('failure') is None
remote_notices = re.findall(r'^\s*Skipping test because it requires a remote test environment\.\s*$', plain, re.M)
cap_notices = re.findall(r'^\s*skipping capability test: unprivileged user namespaces are unavailable\s*$', plain, re.M)
assert len(remote_notices) == 24 and len(cap_notices) == 1

comparison = json.loads((ROOT / 'ci-audit/recovered-20261105/full-f825-to-fb9-exact-case-comparison-v1.json').read_bytes())
repaired = []
for row in comparison['four_repaired_original_cases_now_exact_pass']:
    key = row['classname'], row['name']
    case = xml_by_key[key]
    assert case.find('failure') is None and ET.tostring(case, encoding='unicode') == row['new_xml']
    assert not any((e['classname'], e['name']) == key for e in early)
    repaired.append({'classname': key[0], 'name': key[1], 'seconds': case.get('time'),
                     'raw_headers': raw_cases[key], 'observed_early_return': False})

report = {
    'schema': 'hepta-fourth-full-fb9-complete-root-review-v1',
    'observed_at_utc': datetime.now(timezone.utc).isoformat(),
    'source_tree': SOURCE,
    'original_job': native['original_job'],
    'native_export_manifest': ident((ARCHIVE / 'native-export-manifest-v1.json').read_bytes()),
    'complete_git_archive': {'blob': '87873969544e952a8fcff9ad771f834ffc856537', 'path': 'native-evidence/full-fb9-complete-archive/archive.json'},
    'root_independent_strict_base64_gzip_crc_and_all_original_reopen': True,
    'original_count': len(originals), 'original_bytes': sum(x['bytes'] for x in originals),
    'assets': assets, 'transport_chunks': chunk_rows, 'originals': originals,
    'complete_full_command': command,
    'actual_result': {'selected': 19506, 'junit_pass': 19490, 'fail': 16, 'ordinary_exit101_failure_nodes': 16,
                      'original_ignored': 57, 'unmatched': 0, 'retries': 0, 'original_just_exit': 100,
                      'controller_exit_preserved': 1, 'command_seconds': status['duration_seconds'],
                      'native_nextest_summary': summaries[0].strip(), 'strict_pass': False},
    'catalog': {'original_full_binaries': len(catalog['rust-suites']), 'eligible': 19506, 'ignored': 57,
                'full_case_counter_exact_frozen_c6': True, 'junit_and_raw_case_keys_exact': True,
                'raw_header_occurrences': sum(len(v) for v in raw_cases.values()),
                'raw_header_occurrences_do_not_replace_junit_execution_or_retry_counts': True},
    'metadata': {'workspace_members': 193, 'resolved_nodes': 1501, 'entire_original_metadata_bytes_equal_prior_7d_and_c6': True},
    'programs': {'selected': 321, 'helpers': 33, 'selection_before_after_complete_records_equal': True,
                 'last_tested_artifacts': ident((DECODED / 'full-workspace-selection.json').read_bytes()),
                 'helper_basename_roster': [Path(x['path']).name for x in review['helpers_after']]},
    'all10_source_guards_match_actual_fb9_head_cabc_new_c41_index_and_original_locks': guards,
    'source_map': load('small/final-source-map.json'),
    'actual_free_bytes_after_full': status['disk_after']['free'],
    'four_repaired_original_cases_exact_pass': repaired,
    'early_returns': {'requires_remote': 24, 'capability': 1, 'all25_original_raw_offsets_and_junit_keys_reconciled': True,
                      'all25_are_omitted_behavior_not_qualified_passes': True},
    'remaining_nonpass_triage': 'fourth-full-fb9-nonpass-root-review.json',
    'new_two_causes': 'OPEN; existing raw alone does not establish host/load, thread-registration or DNS cause.',
    'hygiene_executed_at_review': False,
    'whole_candidate_qualified': False, 'all_blockers_closed': False,
}
destination = WORK / 'deliverables/fourth-full-fb9-complete-root-review.json'
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'review': ident(destination.read_bytes()), 'originals': len(originals),
                  'original_bytes': report['original_bytes'], 'raw_headers': report['catalog']['raw_header_occurrences'],
                  'results': report['actual_result'], 'free_bytes': report['actual_free_bytes_after_full']}, ensure_ascii=False))
