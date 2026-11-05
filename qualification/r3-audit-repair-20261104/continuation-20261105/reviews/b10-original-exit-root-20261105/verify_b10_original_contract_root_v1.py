"""Verify archived B10 source and execution evidence; no product/native runs."""
from pathlib import Path
from collections import Counter
import datetime
import hashlib
import importlib.util
import json
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import zstandard

from verify_b11_launcher_publication import verify_merkle

ROOT = Path('/workspace/scratch/07dd58cc9630')
BASE = ROOT / 'research-audit/b10-original-contracts-20261105'
OUT = ROOT / 'hepta-audit-fifth/b10-root'
GNU = ROOT / 'ci-audit/core-wait-span-20261105/project-nonpass-complete-v1/decoded-verified-v1'


def load(path):
    return json.loads(path.read_bytes())


def ident(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()}


def checked(path, expected):
    body = Path(path).read_bytes()
    actual = ident(body)
    assert all(actual[k] == expected[k] for k in actual), (str(path), actual, expected)
    return body


def main():
    original_exit = next(x for x in load(ROOT / 'hepta-audit-fifth/recovery-2113/ledger-v6.json')['items'] if x['id'] == 'B10')['original_exit_condition_zh']
    review = load(BASE / 'independent-review.json')
    assert original_exit == review['original_exit_condition_zh']
    cases = load(BASE / 'fourteen-contracts.json')
    assert len(cases) == len({x['test'] for x in cases}) == 14
    assert Counter(x['origin'] for x in cases) == {'original_failure_snapshot': 10, 'original_turn_state_regression': 3, 'new_reconnection_control': 1}
    projection = load(BASE / 'case-result-projection.json')
    assert {x['test'] for x in cases} == {x['test'] for x in projection['frozen_14_cases']}

    trees = {label: load(ROOT / f'hepta-audit-fifth/recovery-2113/trees/{label}.json') for label in ['5b', 'e78', 'eed']}
    merkle = {label: verify_merkle(tree) for label, tree in trees.items()}
    leafmaps = {label: {e['path']: e for e in tree['tree'] if e['type'] != 'tree'} for label, tree in trees.items()}
    sources = load(BASE / 'complete-source-bridge.json')['fixed_current_sources']
    assert len(sources) == 18
    for source in sources:
        checked(source['local_file'], source)
        for label, leaves in leafmaps.items():
            assert leaves[source['logical_source_path']]['sha'] == source['git_blob']
            assert source['fixed_leaf_matches'][label] == leaves[source['logical_source_path']]
    for case in cases:
        source = next(s for s in sources if s['logical_source_path'] == case['logical_source_path'])
        body = Path(source['local_file']).read_text()
        lines = body.splitlines(keepends=True)
        excerpt = ''.join(lines[case['start_line'] - 1:case['end_line']]).encode()
        assert excerpt == checked(case['excerpt']['local_file'], case['excerpt'])
        assert '#[ignore' not in case['attributes_context'] and '#[cfg' not in case['attributes_context']
        assert b'skip_if_no_network!(Ok(()));' in excerpt
        assert not re.search(rb'\breturn\s+Ok\(\(\)\)', excerpt)

    raw = checked(GNU / 'original-owning-projects.stdout', projection['gnu_complete_stdout_identity'])
    xml = checked(GNU / 'original-owning-projects.junit.xml', projection['gnu_complete_xml_identity'])
    junit = ET.fromstring(xml)
    all_cases = list(junit.iter('testcase'))
    assert len(all_cases) == 3967
    assert Counter(c.tag for t in all_cases for c in t if c.tag in ['failure', 'error', 'skipped']) == {'failure': 5}
    assert projection['gnu_original_command']['retries'] == 0
    assert projection['gnu_original_command']['source_tree'] == trees['e78']['sha']
    selected = []
    for name, row in projection['gnu_cases'].items():
        block = raw[row['raw_start_byte']:row['raw_end_byte']]
        assert block == checked(row['local_file'], row)
        assert row['result'] == 'PASS'
        assert not re.search(rb'Skipping\s+test|skipping\s+capability\s+test', block, re.I)
        assert sum(line.strip() == ('test ' + name + ' ... ok').encode() for line in block.splitlines()) == 1
        assert b'test result: ok. 1 passed; 0 failed; 0 ignored;' in block
        nodes = [t for t in all_cases if t.get('name') == name]
        assert len(nodes) == 1
        assert not any(c.tag in ['failure', 'error', 'skipped', 'rerunFailure', 'rerunError', 'flakyFailure', 'flakyError'] for c in nodes[0])
        assert ET.tostring(nodes[0], encoding='utf-8') == checked(row['junit']['local_file'], row['junit'])
        selected.append({'name': name, 'result': 'PASS', 'seconds': nodes[0].get('time'), 'raw': ident(block), 'junit_attributes': nodes[0].attrib})
    assert len(selected) == 16
    reconnect = (BASE / 'gnu-exact-blocks/suite__turn_state__websocket_turn_state_survives_permission_change_by_reconnecting.log.txt').read_text()
    assert re.findall(r'connection=(\d+) received request=(\d+)', reconnect) == [('0', '0'), ('1', '0'), ('1', '1'), ('1', '2')]

    merge = json.loads(load(OUT / 'windows-merge-root.actual.json')['result']['content'])
    assert merge['sha'] == '9063c52a063b6f26c48e9418f6d8dbd14e9e06ff'
    assert merge['tree']['sha'] == trees['5b']['sha']
    assert [p['sha'] for p in merge['parents']] == ['63652be658ebed8d3052eb789b951793384fd5e4', '5b6331250ff459033bd44d1a95daec70131277cc']
    zipbody = checked(BASE / 'windows-originals/artifact-13430354553/artifact.zip', review['Windows_exact_scope']['ZIP'])
    reopen = load(BASE / 'windows-reopen-receipt.json')
    with zipfile.ZipFile(BASE / 'windows-originals/artifact-13430354553/artifact.zip') as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(set(z.namelist())) == 45
        assert set(z.namelist()) == {r['member'] for r in reopen['zip_members']}
        for r in reopen['zip_members']:
            assert z.read(r['member']) == checked(r['local_file'], r)
    pairs = load(BASE / 'windows-XML-original-log-consistency.json')
    assert len(pairs) == 21
    for pair in pairs:
        original_xml = checked(pair['xml']['local_file'], pair['xml'])
        log = checked(pair['test_log']['local_file'], pair['test_log'])
        outer = ET.fromstring(original_xml)
        assert len(list(outer.iter('testcase'))) == 1
        stdout = list(outer.iter('system-out'))
        assert len(stdout) == 1 and stdout[0].text.encode() == log
    assert set(projection['windows_original_attempts_including_retry']) == {c['test'] for c in cases}
    for name, observations in projection['windows_original_attempts_including_retry'].items():
        assert sum(o['role'] == 'final' for o in observations) == 1
        for o in observations:
            path = BASE / 'windows-originals/zip-members' / o['member']
            log = checked(path, o['source_member_identity'])
            assert log.decode().splitlines()[o['line'] - 1] == o['physical_line'] == f'test {name} ... ok'
    assert sum(len(rows) for rows in projection['windows_original_attempts_including_retry'].values()) == 17

    primary = (BASE / 'primary/bazel-9.3.0-spawn.proto.source.txt').read_bytes()
    assert load(OUT / 'primary-schema-root.actual.json')['result']['content'].encode() == primary
    assert ident(primary)['git_blob'] == '19f68f22a4d62c4fd1aa28fd1c7c0217aa6a7cb0'
    compressed = (BASE / 'windows-originals/zip-members/execution-log-test-test-windows-shard-3207.zst').read_bytes()
    decoder = zstandard.ZstdDecompressor().decompressobj()
    compact = decoder.decompress(compressed) + decoder.flush()
    assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
    assert compact == (BASE / 'windows-originals/zip-members/execution-log.compact.original').read_bytes()
    action_projection = load(BASE / 'windows-original-test-action-projection.json')
    assert ident(compact) == action_projection['full_decompressed_identity']
    spec = importlib.util.spec_from_file_location('b10_parser', BASE / 'project_originals.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    pos = count = 0
    actions = []
    while pos < len(compact):
        start = pos
        size, pos = parser.varint(compact, pos)
        message = parser.fields(compact[pos:pos + size])
        pos += size
        count += 1
        if 7 not in message:
            continue
        spawn = parser.fields(parser.first(message, 7))
        if parser.first(spawn, 7) != b'//codex-rs/core:core-all-test' or parser.first(spawn, 8) != b'TestRunner':
            continue
        row = action_projection['selected_test_actions'][len(actions)]
        assert (count, start, pos) == (row['entry_number'], row['original_start_byte'], row['original_end_byte'])
        assert ident(compact[start:pos]) == row['frame_identity']
        assert compact[start:pos] == Path(row['frame_local_file']).read_bytes()
        args = [a.decode() for a in spawn.get(1, [])]
        assert args == row['args']
        env = {parser.first(parser.fields(v), 1).decode(): parser.first(parser.fields(v), 2).decode() for v in spawn.get(2, [])}
        assert not any(k.upper() == 'CODEX_SANDBOX_NETWORK_DISABLED' for k in env)
        assert parser.first(spawn, 11) == b'local' and not parser.first(spawn, 12, 0)
        binary = args[0].replace('\\', '/').rsplit('/', 1)[-1]
        assert binary in ['tw.exe', 'xml.exe']
        if binary == 'tw.exe':
            assert parser.first(spawn, 17, 0) == 900000
        actions.append({'binary': binary, 'frame': ident(compact[start:pos]), 'shard': env.get('TEST_SHARD_INDEX'),
                        'runner': 'local', 'cache_hit': False, 'network_disabled_key_absent': True,
                        'timeout_millis': parser.first(spawn, 17, 0), 'exit_code': parser.first(spawn, 9, 0)})
    assert pos == len(compact) == 30370252 and count == 89920
    assert Counter(a['binary'] for a in actions) == {'tw.exe': 21, 'xml.exe': 21}
    assert {int(a['shard']) for a in actions if a['binary'] == 'tw.exe'} == set(range(16))
    assert 'CODEX_SANDBOX_NETWORK_DISABLED' not in (BASE / 'source/defs.bzl.source.txt').read_text()
    assert 'CODEX_SANDBOX_NETWORK_DISABLED' not in (BASE / 'source/workspace_root_test_launcher.bat.tpl.source.txt').read_text()

    argv = ['python3', str(BASE / 'delivery/verify_bundle.py.source.txt'), '--manifest', str(BASE / 'delivery/transport-manifest.json'),
            '--parts', str(BASE / 'delivery/parts'), '--output', str(OUT / 'restored-v1')]
    bundle = subprocess.run(argv, capture_output=True, text=True)
    assert bundle.returncode == 0, (bundle.stdout, bundle.stderr)
    bundle_result = json.loads(bundle.stdout)
    assert bundle_result['member_count'] == 191
    result = {'schema': 'B10-original-contract-root-verification/v1', 'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'decision': 'CLOSED_SCOPED', 'original_exit_condition_zh': original_exit, 'original_exit_unchanged': True,
              'catalog_composition': dict(Counter(c['origin'] for c in cases)), 'source_merkle': merkle,
              'eighteen_complete_source_blobs_equal': [{k: s[k] for k in ['logical_source_path', 'bytes', 'sha256', 'git_blob']} for s in sources],
              'GNU': {'command': projection['gnu_original_command'], 'raw': ident(raw), 'xml': ident(xml), 'selected': selected,
                      'selected_integration_cases': 14, 'supplemental_identity_cases': 2, 'selected_early_returns': 0,
                      'whole': {'passed': 3962, 'failed': 5, 'exit_code': 100, 'ignored_catalog': 10},
                      'reconnect_physical_request_pairs': [[0, 0], [1, 0], [1, 1], [1, 2]]},
              'Windows': {'run': 41999114842, 'job': 127339256056, 'attempt': 1, 'artifact': 13430354553,
                          'actual_merge': merge['sha'], 'actual_tree': merge['tree']['sha'], 'zip': ident(zipbody),
                          'all45_members_CRC_and_hash_verified': True, 'all21_outer_XML_complete_stdout_equals_original_log': True,
                          'final_cases': 14, 'attempt_inclusive_pass_observations': 17,
                          'whole_target_nonpass_preserved': 'FAILED in 6 of 21 attempts; does not qualify whole target',
                          'complete_compact': ident(compact), 'decoded_entries': count, 'actions': actions},
              'human_source_review': {'complete_integration_function_bodies': 13, 'generated_case_names': 14, 'complete_identity_unit_function_bodies': 2,
                  'production_and_helpers': ['provider identity comparison', 'websocket reconnect/reset', 'entire concurrent fixture', 'network skip macro', 'Windows launcher', 'defs environment and sharding', 'turn submission and request waiters', 'all exact GNU case blocks'],
                  'semantic_findings_zh': ['模型与工具元数据随实际请求更新而可复用连接；身份敏感字段仍隔离，动态字段仍进入wire与恢复指纹。',
                    '工作区用例观察真实预热后改写实际Git状态，后续请求准确反映origin、HEAD与脏文件。',
                    '压缩原历史、完整前缀与创建时间断言保留；wire有意去除私有metadata，durable副本仍保留。',
                    'stable总请求旧3→4为已接受oracle修正：1无工具prewarm+3真实turn；两个工具输出和原turn-state均验证。',
                    '同权限场景严格1连接；read-only→full原权限向量在新增keep-alive双socket控制中严格[1,3]，不是EOF制造的重连。']},
              'evidence_only_replay': load(OUT / 'replayed-evidence-verifiers.json'),
              'bundle_verification': {'argv': argv, 'exit_code': bundle.returncode, 'stderr': bundle.stderr, 'result': bundle_result},
              'limits': ['Only the literal B10 semantic contract is closed in the demonstrated GNU and Windows scopes.',
                         'Historical 48-platform failure mapping is retained; this is not macOS/musl/Wine or current eed whole-head qualification.',
                         'Windows XML contains outer wrapper cases, not fourteen invented per-case XML nodes.',
                         'The existing original flaky shard attempts are retained, including three selected names passing both times.',
                         'No new native execution, product test, CI retry, source/budget/skip change or main product ref movement.']}
    target = OUT / 'ROOT_CLOSURE.json'
    assert not target.exists()
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'decision': result['decision'], 'path': str(target), **ident(target.read_bytes()), 'integration': 14, 'identity': 2, 'windows_pass_occurrences': 17, 'archive_members': 191}))


if __name__ == '__main__':
    main()
