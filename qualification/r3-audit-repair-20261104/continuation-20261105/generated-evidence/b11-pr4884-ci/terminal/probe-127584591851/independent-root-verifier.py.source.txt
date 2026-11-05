"""Verify original native10 evidence without running any product/native command."""
from pathlib import Path
import datetime
import hashlib
import importlib.machinery
import importlib.util
import json
import re
import xml.etree.ElementTree as ET
import zipfile
import zstandard

ROOT = Path('/workspace/scratch/07dd58cc9630')
P = ROOT / 'architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127584591851'
OUT = ROOT / 'hepta-audit-fifth/b11-native10-root'
HEAD = '021a59ff05ccd963bc087918db823aa86af31bb8'
MERGE = '5ce73498a9e8ee843d156c43593b1bc2fede416f'
TREE = '36ca349de7f4c7c5a2914cf1960a81d8621350fa'
TARGET = '//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests'
HELPER = '//codex-rs/windows-sandbox-rs:codex-windows-sandbox-setup-bin-unit-tests'
CASES = [
    'acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object',
    'acl::tests::existing_native_deny_does_not_require_write_dac',
    'acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write',
    'token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes',
]


def load(path):
    return json.loads(path.read_bytes())


def digest(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def unwrap(value):
    assert not value.get('isError', False)
    result = value.get('structuredContent') or json.loads(next(x['text'] for x in value['content'] if x['type'] == 'text'))
    return json.loads(result['content']) if isinstance(result.get('content'), str) else result


def summaries(text):
    return re.findall(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in ([0-9.]+)s$', text, re.M)


def pair(path, expected_error=None):
    raw = path.read_bytes()
    text = raw.decode()
    xml_raw = path.with_suffix('.xml').read_bytes()
    xml = ET.fromstring(xml_raw)
    assert len(xml.findall('.//testcase')) == 1
    assert [x.get('message') for x in xml.findall('.//error')] == ([] if expected_error is None else [expected_error])
    assert not xml.findall('.//skipped') and not xml.findall('.//failure')
    assert xml.find('.//system-out').text == text.replace('\r\n', '\n').replace('\r', '\n').replace('\x1b', '?')
    return text, {'path': str(path.relative_to(P)), 'raw': digest(raw), 'XML': digest(xml_raw),
                  'original_ESC_count': text.count('\x1b'), 'original_CR_count': text.count('\r'),
                  'XML_entire_system_out_matches_after_only_XML_newline_and_ESC_serialization': True}


def one_log(scope, kind):
    paths = list((scope / 'bazel-execution-logs' / kind).glob('invocation-*/targets/0000/test.log'))
    assert len(paths) == 1
    return paths[0]


def main():
    api = load(P / 'terminal-api-envelopes.json')
    run = unwrap(api['run'])
    jobs = unwrap(api['jobs'])['jobs']
    artifacts = unwrap(api['artifacts'])['artifacts']
    assert run['id'] == 42124355402 and run['run_attempt'] == 1 and run['head_sha'] == HEAD
    assert run['status'] == 'completed' and run['conclusion'] == 'failure'
    job = next(j for j in jobs if j['id'] == 127584591851)
    assert job['status'] == 'completed' and job['conclusion'] == 'failure'
    artifact = next(a for a in artifacts if a['id'] == 13461080955)
    archive = (P / 'artifact.zip').read_bytes()
    assert artifact['size_in_bytes'] == len(archive) == 2291410
    assert artifact['digest'] == 'sha256:' + digest(archive)['sha256']
    verified = load(P / 'artifact-verification.json')
    with zipfile.ZipFile(P / 'artifact.zip') as z:
        assert z.testzip() is None
        infos = [i for i in z.infolist() if not i.is_dir()]
        claimed = {r['path']: r for r in verified['members']}
        assert len(infos) == len(claimed) == 84 and set(claimed) == {i.filename for i in infos}
        for info in infos:
            raw = z.read(info.filename)
            assert raw == (P / 'members' / info.filename).read_bytes()
            assert {k: claimed[info.filename][k] for k in digest(raw)} == digest(raw)
            assert claimed[info.filename]['crc32'] == f'{info.CRC:08x}'
    job_log = (P / 'job.log').read_bytes()
    log_response = api['log'].get('structuredContent') or json.loads(next(x['text'] for x in api['log']['content'] if x['type'] == 'text'))
    assert log_response['content'].encode() == job_log
    assert b'Starting local Bazel server (9.3.0)' in job_log
    base = P / 'members/b11-token-mechanism-probe'
    cf = base / 'acl-identity-counterfactual'
    helper = base / 'read-acl-readiness'
    actual = load(ROOT / 'hepta-audit-fifth/b11-env-publication/intended-full-tree.json')
    actual_root = load(ROOT / 'hepta-audit-fifth/b11-env-publication/actual-tree-root.json')['response']
    assert actual['sha'] == actual_root['sha'] == TREE
    merge = load(ROOT / 'hepta-audit-fifth/b11-env-publication/actual-merge-commit.json')['commit_actual']
    assert merge['sha'] == MERGE and merge['tree']['sha'] == TREE
    assert [p['sha'] for p in merge['parents']] == ['67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed', HEAD]
    leaves = {e['path']: e for e in actual['tree'] if e['type'] != 'tree'}
    assert (base / 'source-head-tree.txt').read_text().splitlines() == [MERGE, TREE]
    selected = []
    for line in (base / 'source-leaves.txt').read_text().splitlines():
        mode, kind, rest = line.split(' ', 2)
        sha, path = rest.split('\t')
        assert [mode, kind, sha] == [leaves[path][k] for k in ['mode', 'type', 'sha']]
        selected.append(path)
    assert len(selected) == len(set(selected)) == 78
    assert not (base / 'source-status-before.txt').read_text().strip() and not (base / 'source-status-after.txt').read_text().strip()
    assert (base / 'original-bazel-exit-code.txt').read_text().strip() == '3'
    assert (base / 'console-copy-exit-code.txt').read_text().strip() == '0'
    manifest_proofs = []
    for manifest_file in sorted((P / 'members').rglob('manifest.json')):
        manifest = load(manifest_file)
        relative = manifest_file.relative_to(P / 'members').as_posix()
        dirty = relative.startswith('b11-token-mechanism-probe/acl-identity-counterfactual/bazel-execution-logs/')
        assert manifest['source'] == {'commit': MERGE, 'tree': TREE, 'tracked_worktree_dirty': dirty}
        assert manifest['complete_for_selected_targets'] is True and not manifest['errors']
        manifest_proofs.append({'path': relative, 'identity': digest(manifest_file.read_bytes()), 'source': manifest['source'], 'listed_file_count': len(manifest['files'])})
    assert len(manifest_proofs) == 9
    whole_log = one_log(P / 'members', 'failed-test-logs')
    whole, whole_pair = pair(whole_log, 'exited with error code 1')
    batches = summaries(whole)
    assert len(batches) == 2 and [sum(int(s[i]) for s in batches) for i in [1, 2, 3]] == [147, 7, 2]
    assert all(sum(int(s[i]) for i in range(1, 6)) == 156 for s in batches)
    failures = re.findall(r'^---- (.+) stdout ----$', whole, re.M)
    assert len(failures) == len(set(failures)) == 7
    terminal = load(cf / 'counterfactual-terminal.json')
    assert terminal['status'] == 'VALID_NEGATIVE_AND_EXACT_RESTORE' and terminal['product_B11'] == 'OPEN'
    for key in ['physical_counterfactual_qualified', 'physical_oracle_reached', 'source_mutated', 'source_mutation_attempted', 'restored_exact_original_bytes', 'original_target_exit_code_unchanged']:
        assert terminal[key] is True
    assert terminal['error'] is None and terminal['restore_error'] is None and terminal['hard_cancellation_restore_guaranteed'] is False
    entry = load(cf / 'source-entry.json')
    assert entry['head'] == MERGE and entry['head_tree'] == TREE and not entry['status']
    assert entry == load(cf / 'source-restored.json')
    positive_bytes = (cf / 'positive-source.original').read_bytes()
    negative_bytes = (cf / 'negative-source.original').read_bytes()
    assert digest(positive_bytes) == entry['source']
    assert digest(positive_bytes.replace(b'\r\n', b'\n'))['git_blob'] == entry['source_canonical_git_blob'] == 'da5346c220c41cf0c83f62b596132c74c02284d8'
    assert digest(negative_bytes.replace(b'\r\n', b'\n'))['git_blob'] == '0baeb6ec2f3bfd0964be6d014fc5d80d890ea3d7'
    check = b'    ensure!(\n        actual == expected,\n        "deny repair path no longer identifies the retained object: {}",\n        path.display()\n    );'
    assert positive_bytes.replace(b'\r\n', b'\n').replace(check, b'    let _ = actual == expected;', 1) == negative_bytes.replace(b'\r\n', b'\n')
    negatives = [load(cf / x) for x in ['source-negative-before.json', 'source-negative-after.json', 'source-before-restore.json']]
    assert all(x == negatives[0] for x in negatives)
    expected_negative = {**entry, 'source': digest(negative_bytes), 'source_canonical_git_blob': '0baeb6ec2f3bfd0964be6d014fc5d80d890ea3d7', 'status': [' M codex-rs/windows-sandbox-rs/src/acl_deny.rs']}
    assert negatives[0] == expected_negative
    positive_evidence = []
    for i, case in enumerate(CASES, 1):
        scope = cf / f'positive-{i:02}'
        assert load(scope / 'source-before.json') == load(scope / 'source-after.json') == entry
        cmd = load(scope / 'command.json')
        assert cmd['source'] == entry and cmd['case'] == case
        assert cmd['argv'][0] == r'C:\Program Files\Git\usr\bin\bash.exe'
        assert '--nocache_test_results' in cmd['argv'] and '--flaky_test_attempts=1' in cmd['argv'] and '--test_arg=--exact' in cmd['argv']
        assert '--test_arg=' + case in cmd['argv'] and cmd['argv'][-1] == TARGET
        assert load(scope / 'command-terminal.json')['exit_code'] == 0
        raw, compared = pair(one_log(scope, 'selected-target-test-logs'))
        assert len(re.findall(r'^test ' + re.escape(case) + r' \.\.\. ok$', raw, re.M)) == 1
        assert len(summaries(raw)) == 1 and summaries(raw)[0][1:6] == ('1', '0', '0', '0', '155')
        assert terminal['positive_scopes'][i - 1] == load(scope / 'qualification.json')
        positive_evidence.append({'case': case, 'pair': compared, 'command': cmd, 'terminal': load(scope / 'command-terminal.json')})
    negative, negative_pair = pair(one_log(cf, 'failed-test-logs'), 'exited with error code 101')
    marker = 'deny_repair_identity: directory=false returned_ok=true replacement_changed=true original_changed=false'
    assert negative.splitlines().count(marker) == 1
    assert 'acl_tests.rs:597:9' in negative and "a replacement object must not receive the queried object's deny" in negative
    assert summaries(negative)[0][0:6] == ('FAILED', '0', '1', '0', '0', '155')
    assert load(cf / 'negative-command-terminal.json')['exit_code'] == 3
    assert load(cf / 'negative-command.json')['source'] == expected_negative
    ht = load(helper / 'terminal.json')
    assert ht['status'] == 'HELPER_TARGET_PASSED' and ht['helper_qualified'] and ht['original_library_result_unchanged']
    assert not ht['full_read_grants_loader_or_descendants_qualified'] and ht['error'] is None and ht['final_guard_error'] is None
    hs = load(helper / 'source-before.json')
    assert hs == load(helper / 'source-after.json') == load(helper / 'source-final.json') and hs['source'] == entry
    assert len(hs['pins']) == 11
    for path, row in hs['pins'].items():
        assert row['canonical_git_blob'] == leaves[path]['sha']
    hc = load(helper / 'command.json')
    assert hc['source'] == hs and hc['argv'][-1] == HELPER and '--nocache_test_results' in hc['argv'] and '--flaky_test_attempts=1' in hc['argv']
    assert not any(a.startswith(('--test_arg', '--test_filter', '--test_timeout')) for a in hc['argv'])
    assert load(helper / 'command-terminal.json')['exit_code'] == 0
    helper_raw, helper_pair = pair(one_log(helper, 'selected-target-test-logs'))
    helper_cases = re.findall(r'^test (\S+) \.\.\. ok$', helper_raw, re.M)
    assert len(helper_cases) == len(set(helper_cases)) == 21
    assert helper_cases == ht['results']['actual_case_names']
    assert summaries(helper_raw)[0][0:6] == ('ok', '21', '0', '0', '0', '0')
    # All compact bytes are parsed, including failed/negative actions; XML wrapper actions are separate.
    parser_file = ROOT / 'ci-audit/b20-original-path-inquiry-20261105/windows/upstream-b10-project-originals.py.source.txt'
    loader = importlib.machinery.SourceFileLoader('native10_compact', str(parser_file))
    parser = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(parser)
    compact_results = []
    for file in sorted((P / 'members').rglob('*.zst')):
        decoder = zstandard.ZstdDecompressor().decompressobj()
        decoded = decoder.decompress(file.read_bytes()) + decoder.flush()
        assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
        pos = count = 0
        actions = []
        while pos < len(decoded):
            size, pos = parser.varint(decoded, pos)
            assert pos + size <= len(decoded)
            fields = parser.fields(decoded[pos:pos + size]); pos += size; count += 1
            if 7 not in fields:
                continue
            spawn = parser.fields(parser.first(fields, 7))
            target = parser.first(spawn, 7, b'').decode()
            if target not in [TARGET, HELPER] or parser.first(spawn, 8, b'') != b'TestRunner':
                continue
            argv = [v.decode() for v in spawn.get(1, [])]
            runner, cached, code = parser.first(spawn, 11, b'').decode(), bool(parser.first(spawn, 12, 0)), parser.first(spawn, 9, 0)
            role = 'XML_wrapper' if argv and argv[0].endswith('xml.exe') else 'actual_test'
            if role == 'actual_test':
                relative = file.relative_to(P / 'members').as_posix()
                expected_exit = 1 if relative.startswith('bazel-execution-logs/') else (101 if '/acl-identity-counterfactual/bazel-execution-logs/' in relative else 0)
                assert runner == 'local' and not cached and code == expected_exit
            actions.append({'role': role, 'target': target, 'argv': argv, 'runner': runner, 'cache_hit': cached, 'exit_code': code, 'timeout_millis': parser.first(spawn, 17, 0)})
        assert pos == len(decoded) and sum(a['role'] == 'actual_test' for a in actions) == 1
        compact_results.append({'file': str(file.relative_to(P)), 'compressed': digest(file.read_bytes()), 'complete_decoded': digest(decoded), 'entries': count, 'actions': actions})
    assert len(compact_results) == 7
    steps = {s['name']: s['conclusion'] for s in job['steps']}
    assert steps['Run the original outer Windows sandbox unit target'] == 'failure'
    for name in ['Check the ACL identity counterfactual and restore its source', 'Run the original setup helper target after exact restoration', 'Check for a clean worktree']:
        assert steps[name] == 'success'
    result = {'schema': 'hepta-b11-native10-root-original-verification-v1', 'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'run': run['id'], 'job': job['id'], 'attempt': 1, 'head': HEAD, 'actual_checkout': MERGE, 'actual_tree': TREE,
              'archive': digest(archive), 'all84_original_members_CRC_full_bytes_verified': True,
              'job_log': digest(job_log), 'actual78_source_leaves_checked': selected,
              'whole': {'passed': 147, 'failed': 7, 'ignored': 2, 'batches': batches, 'failed_headers': failures, 'pair': whole_pair, 'original_bazel_exit': 3},
              'positives': positive_evidence, 'negative_pair': negative_pair, 'physical_negative_marker': marker,
              'negative_assertion': 'acl_tests.rs:597:9', 'negative_XML_exit': 101, 'negative_Bazel_exit': 3,
              'counterfactual_terminal': terminal, 'positive_and_negative_full_original_bytes_checked': True,
              'source_index_test_and_lock_metadata_stable_except_exact_owned_mutation_then_restored': True,
              'full_index_and_lock_bytes_not_archived_here': True, 'helper_terminal': ht, 'helper_pair': helper_pair,
              'helper11_canonical_pins_equal_to_published_merge': hs['pins'], 'complete7_compact_logs': compact_results,
              'all9_collector_source_bindings': manifest_proofs,
              'decision': 'Qualified original four exact positives, one physical negative and exact restoration, plus original unfiltered 21-case setup helper; original 147/7/2 whole failure preserved.',
              'B11': 'OPEN', 'whole_candidate_qualified': False, 'hard_cancellation_restoration_not_guaranteed': True,
              'scope_exclusions': ['Full restricting token, ambient reads, loader and descendant lifetime remain unqualified.', 'Helper INFINITE wait and Command.status were not given new deadlines.', 'This receipt does not convert an original failing target or job into success.']}
    OUT.mkdir(exist_ok=True)
    out = OUT / 'ROOT_VERIFICATION.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(out), **digest(out.read_bytes()), 'whole': [147, 7, 2], 'exact_positive': 4, 'physical_negative': 1, 'helper': 21, 'compact_logs_fully_parsed': 7, 'B11': 'OPEN'}))


if __name__ == '__main__':
    main()
