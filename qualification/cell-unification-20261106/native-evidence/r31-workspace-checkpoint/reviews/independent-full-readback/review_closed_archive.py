#!/usr/bin/env python3
"""Independent, local-only R31 archive reader; no runner import or subprocess."""
import argparse
import collections
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile

P = 'native-workspace-r31'
JOB = '1a1b275ba33-fc05-7e17'
KEY = 'cell-source53-workspace-r31-20261106-v1'
COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
TREE = '440d4a8e09af4009e4d9ea067388826308da8803'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
OLD_COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
OLD_TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'
T = '/home/alex/work/hepta-cell-unified-20261106-a'
CWD = T + '/source/codex-rs'
COMMAND = ['just', 'test', '--locked', '--retries', '0']
METADATA_COMMAND = ['cargo', 'metadata', '--locked', '--no-deps', '--format-version', '1']
LOCKS = {'codex-rs/Cargo.lock': '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c',
         'MODULE.bazel.lock': 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'}
SOURCE_SHA = '9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda'
RUNNER_SHA = '2dc7b84b7dad0d6e150817e0dfc4105c4bb4d343103aacef0fb932eab698a6f9'
AUTH_SHA = 'f97eda581ff5bb65797e2c483466305d8f881de51ac18256777e7f71ba0455ad'
OLD_PINS = {
    'native-workspace-r29-tests.log': (2499408, '3a95dcc8f0c486594fe3ff41c50fcaaa363bf00533f3ab7d37330e1c757a8559'),
    'native-workspace-r29-test-results.json': (4586810, '2070a63e9b17a64f75f447c39bb3a7d00a91c0273810fdb86ded4656318b9930'),
    'native-workspace-r29-result-review.json': (1775, '6cd91d2003e8fcd5eb576b5db22559683dfa5a4f0259e7a545f07d4580cb9004'),
    'native-workspace-r29-metadata.json': (937659, 'b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d')}
SUCCESS_SUFFIXES = (
    '-source-pre-verification.json', '-environment.json', '-preconditions.json',
    '-metadata.json', '-metadata-stderr.log', '-metadata-raw-process-result.json',
    '-metadata-source-post-verification.json', '-metadata-receipt.json', '-scope.json',
    '-tests-source-pre-verification.json', '-tests.log', '-tests-resources.txt',
    '-tests-raw-process-result.json', '-source-post-test-verification.json',
    '-tests-receipt.json', '-test-results.json', '-result-review.json', '-complete.json')
ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
ROW = re.compile(r'^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$')
START = re.compile(r'^\s*Starting (\d+) tests?\b')
SUMMARY = re.compile(r'^\s*Summary\s+\[\s*([0-9.]+)s\]\s+(\d+) tests? run:\s*(.*)$')


def require(value, message):
    if not value:
        raise AssertionError(message)


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def checked_pin(raw, expected, label):
    value = pin(raw)
    for key in ('bytes', 'sha256', 'git_blob'):
        if key in expected:
            require(value[key] == expected[key], label + ': ' + key)
    return value


def parse_log(raw):
    """Independent scan of original byte lines, separating execution and footer."""
    starts, summaries, result_lines = [], [], []
    offset = 0
    for number, original in enumerate(raw.splitlines(keepends=True), 1):
        text = ANSI.sub(b'', original).decode('utf-8', errors='replace').rstrip('\r\n')
        if match := START.match(text):
            starts.append({'line': number, 'byte_offset': offset, 'text': text, 'tests': int(match[1])})
        if match := SUMMARY.match(text):
            counts = {}
            for key, label in (('PASS', 'passed'), ('FAIL', 'failed'), ('TIMEOUT', 'timed out'), ('skipped', 'skipped')):
                found = re.search(r'\b(\d+) ' + label + r'\b', match[3])
                counts[key] = int(found[1]) if found else 0
            summaries.append({'line': number, 'byte_offset': offset, 'text': text,
                              'tests': int(match[2]), 'seconds': float(match[1]), 'counts': counts})
        if match := ROW.match(text):
            result_lines.append({'status': match[1], 'seconds': float(match[2]),
                                 'binary': match[3], 'name': match[4].strip(),
                                 'line': number, 'byte_offset': offset})
        offset += len(original)
    require(offset == len(raw), 'line scanner byte coverage')
    require(len(starts) <= 1 and len(summaries) <= 1, 'multiple nextest invocations in original log')
    start = starts[0] if starts else None
    summary = summaries[0] if summaries else None
    require(not summary or start and start['line'] < summary['line'], 'Summary before Starting')
    rows = [row for row in result_lines if start and start['line'] < row['line']
            and (summary is None or row['line'] < summary['line'])]
    footer = [row for row in result_lines if summary and row['line'] > summary['line']]
    require(len(rows) + len(footer) == len(result_lines), 'result-shaped line outside declared execution')
    identities = [(row['binary'], row['name']) for row in rows]
    duplicates = [identity for identity, count in collections.Counter(identities).items() if count != 1]
    require(not duplicates, 'duplicate executed IDs before Summary')
    counts = {status: sum(row['status'] == status for row in rows) for status in ('PASS', 'FAIL', 'TIMEOUT')}
    complete = start is not None and summary is not None
    if complete:
        require(start['tests'] == summary['tests'] == len(rows), 'Starting/Summary/unique row total differs')
        require(counts == {key: summary['counts'][key] for key in counts}, 'Summary count differs from original rows')
        require(len(footer) == counts['FAIL'] + counts['TIMEOUT'], 'footer failure repetition count differs')
        require({(r['binary'], r['name'], r['status']) for r in footer}
                == {(r['binary'], r['name'], r['status']) for r in rows if r['status'] != 'PASS'},
                'footer failure IDs differ from real execution failures')
    groups = {}
    for row in rows:
        group = groups.setdefault(row['binary'], {'PASS': 0, 'FAIL': 0, 'TIMEOUT': 0})
        group[row['status']] += 1
    failures = []
    for i, row in enumerate(rows):
        if row['status'] == 'PASS':
            continue
        end = rows[i + 1]['byte_offset'] if i + 1 < len(rows) else (summary['byte_offset'] if summary else len(raw))
        failures.append({**row, 'byte_end': end, **pin(raw[row['byte_offset']:end])})
    announcement = None
    if start:
        match = re.fullmatch(r'\s*Starting (\d+) tests? across (\d+) binar(?:y|ies) \((\d+) tests? skipped\)', start['text'])
        if match:
            announcement = {'tests': int(match[1]), 'binary_count': int(match[2]), 'reported_skipped': int(match[3])}
            if complete:
                require(announcement['reported_skipped'] == summary['counts']['skipped'], 'Starting/Summary skip count differs')
    return rows, {'starting': start, 'summary': summary, 'nextest_started': start is not None,
                  'complete_execution_accounting': complete, 'execution_rows_observed': len(rows),
                  'terminal_unique_test_count': len(rows) if complete else None,
                  'terminal_counts': counts if complete else None,
                  'partial_observed_counts': None if complete else counts,
                  'reported_skipped': summary['counts']['skipped'] if complete else None,
                  'skip_identities_inferred': False, 'footer_rows_excluded': footer,
                  'duplicate_execution_ids': duplicates, 'announced': announcement,
                  'binary_groups_with_execution_rows': len(groups), 'per_binary': groups, 'failure_spans': failures}


def read_archive(path, expected_sha):
    archive = path.read_bytes()
    require(pin(archive)['sha256'] == expected_sha, 'archive external SHA differs')
    contents, modes = {}, {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tf:
        for member in tf.getmembers():
            rel = PurePosixPath(member.name)
            require(member.isfile() and not member.issym() and not member.islnk()
                    and not rel.is_absolute() and '..' not in rel.parts and member.name not in contents,
                    'unsafe or duplicate archive member')
            data = tf.extractfile(member).read()
            require(len(data) == member.size, 'short archive member')
            contents[member.name], modes[member.name] = data, member.mode
    index = json.loads(contents['INDEX.json'])
    entries = {row['path']: row for row in index['files']}
    require(len(entries) == len(index['files']) and set(entries) == set(contents) - {'INDEX.json'}, 'INDEX membership differs')
    rows = []
    for name, declared in sorted(entries.items()):
        value = checked_pin(contents[name], declared, 'archive:' + name)
        declared_mode = declared['mode']
        if isinstance(declared_mode, str):
            declared_mode = int(declared_mode, 8)
        require(declared_mode & 0o7777 == modes[name] & 0o7777, 'INDEX/tar permission differs')
        rows.append({'path': name, **value, 'tar_mode': modes[name], 'declared_mode': declared['mode']})
    return archive, contents, modes, index, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--archive', type=Path, required=True)
    ap.add_argument('--archive-sha256', required=True)
    ap.add_argument('--tests-log-sha256', required=True)
    ap.add_argument('--terminal-sha256', required=True)
    ap.add_argument('--root-authorization', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    require(not args.output.exists(), 'create-only report directory already exists')
    archive_raw, contents, modes, index, archive_members = read_archive(args.archive, args.archive_sha256)
    originals = {name[len('evidence/'):]: raw for name, raw in contents.items() if name.startswith('evidence/')}
    def original(suffix):
        return originals[P + suffix]
    def document(suffix):
        return json.loads(original(suffix))
    errors = []
    def check(ok, label):
        if not ok:
            errors.append(label)
    def pointer(value, suffix):
        check(value == {'path': P + suffix, **pin(original(suffix))}, 'pointer differs: ' + suffix)
    def guard(suffix):
        value = document(suffix)
        expected = {'expected_tree': TREE, 'source_commit': COMMIT, 'changed_file_count': 197,
                    'pass': True, 'actual_tree': TREE, 'native_head': HEAD, 'unstaged_paths': [],
                    'untracked_paths': [], 'changed_path_set_matches': True, 'file_mismatches': [],
                    'cargo_lock_sha256': LOCKS['codex-rs/Cargo.lock'], 'bazel_lock_sha256': LOCKS['MODULE.bazel.lock']}
        for key, item in expected.items():
            check(value.get(key) == item, 'source guard ' + suffix + ': ' + key)
        return value

    source_raw = contents['input/native-candidate-r30-source.json']
    require(len(source_raw) == 56747 and pin(source_raw)['sha256'] == SOURCE_SHA, 'registered source manifest changed')
    source = json.loads(source_raw)
    require(source['source_commit'] == COMMIT and source['source_tree'] == TREE, 'wrong source53 identity')
    files = {row['path']: row for row in source['changed_files']}
    require(len(files) == len(source['changed_files']) == source['changed_file_count'] == 197, 'source count differs')
    require(sum(path.endswith('.rs') for path in files) == 183, 'Rust path count differs')
    require({name[7:] for name in contents if name.startswith('source/')} == set(files), 'archive source path set differs')
    source_rows = []
    for path, expected in sorted(files.items()):
        member = 'source/' + path
        value = checked_pin(contents[member], expected, member)
        check(expected['mode'] in ('100644', '100755'), 'source is not a Git regular file')
        check(('100755' if modes[member] & 0o111 else '100644') == expected['mode'], 'source execute mode differs: ' + path)
        source_rows.append({'path': path, **value, 'git_mode': expected['mode'], 'tar_permissions': modes[member]})
    for path, digest in LOCKS.items():
        check(pin(contents['locks/' + path])['sha256'] == digest, 'raw lock differs: ' + path)

    terminal_raw = original('-terminal-process-status.json')
    require(pin(terminal_raw)['sha256'] == args.terminal_sha256, 'terminal external pin differs')
    terminal = json.loads(terminal_raw)
    require(terminal['job_id'] == JOB and isinstance(terminal['exit_code'], int), 'wrong terminal job')
    check(terminal['state'] == ('succeeded' if terminal['exit_code'] == 0 else 'failed'), 'terminal state/exit differs')
    for key in ('output_complete', 'output_durable', 'terminal_publication_confirmed'):
        check(terminal[key] is True, 'terminal incomplete: ' + key)
    for key in ('timed_out', 'cancelled', 'automatic_retry'):
        check(terminal[key] is False, 'terminal not natural: ' + key)
    check(not any(terminal['log_truncated'].values()) and all(value is None for value in terminal['log_errors'].values()),
          'controller terminal output truncated/unavailable')

    env, pre = document('-environment.json'), document('-preconditions.json')
    for label, value in (('env', env), ('preconditions', pre)):
        check(value['source_commit'] == COMMIT and value['source_tree'] == TREE, label + ' source identity')
        check(value['diagnostic_only'] is True and value['behavior_repair_claimed'] is False, label + ' diagnostic classification')
    check(pre['source_manifest'] == {'path': 'native-candidate-r30-source.json', **pin(source_raw)}, 'precondition manifest pointer')
    check(pre['actual_changed_file_count'] == 197 and pre['workspace_test_command'] == COMMAND, 'precondition selection')
    for key in ('patch_application_performed', 'lock_update_performed', 'python_suite_reexecuted', 'fix_fmt_executed',
                'workspace_baseline_used_as_filter', 'historical_project_pass_substitutes_for_r30'):
        check(pre[key] is False, 'precondition scope differs: ' + key)
    check(pre['prior_source52_workspace'] == 'FAILED_100_20227_PASS_1_FAIL_0_TIMEOUT_130_REPORTED_SKIP', 'R29 failure relabelled')
    parent_pointer = pre['source52_parent_manifest']
    parent_raw = contents['input/ancestor-manifests/' + parent_pointer['path']]
    checked_pin(parent_raw, parent_pointer, 'original source52 manifest')
    parent = json.loads(parent_raw)
    parent_files = {row['path']: row for row in parent['changed_files']}
    additions = {'codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs',
                 'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs'}
    check(parent['source_commit'] == OLD_COMMIT and parent['source_tree'] == OLD_TREE
          and len(parent_files) == 195 and set(files) == set(parent_files) | additions,
          '197 = unchanged parent195 plus two diagnostic leaves')
    check(all(files.get(path) == row for path, row in parent_files.items()), 'original parent195 rows changed')
    check(env['original_default_workspace_selection'] and env['fresh_current_source_metadata_required']
          and env['test_deadlines_features_filters_retries_unchanged'], 'environment selection guarantees')
    check(env['sandbox_or_network_protection_environment_overridden'] is False
          and env['outer_timeout_seconds_contract'] == 9600, 'environment boundary')
    for key, expected in {'RUSTUP_TOOLCHAIN': '1.96.0', 'CARGO_BUILD_JOBS': '2', 'NEXTEST_TEST_THREADS': '2',
                          'CARGO_TARGET_DIR': T + '/target', 'CARGO_PROFILE_TEST_DEBUG': '0', 'CARGO_PROFILE_DEV_DEBUG': '0',
                          'NEXTEST_PROFILE': None, 'HEPTA_NEXTTEST_FULL_METADATA': None, 'CARGO_INCREMENTAL': None,
                          'CARGO_BUILD_TARGET': None, 'RUSTFLAGS': None, 'PYTHONOPTIMIZE': None}.items():
        check(env['selection'][key] == expected, 'environment: ' + key)
    pointer(pre['initial_source_guard'], '-source-pre-verification.json')
    guard('-source-pre-verification.json')

    previous = {}
    for kind, key, directory, expected_count, commit, tree in (
        ('R30', 'r30_closed_gate_readback', 'input/r30-prerequisites/', 19, COMMIT, TREE),
        ('R28', 'source52_r28_historical_project_gate', 'input/r28-prerequisites/', 26, OLD_COMMIT, OLD_TREE)):
        proof = pre[key]
        check(proof['source_commit'] == commit and proof['source_tree'] == tree, kind + ' historical/current identity')
        require(len(proof['originals']) == expected_count, kind + ' original list differs')
        for row in proof['originals']:
            checked_pin(contents[directory + row['path']], row, kind + ':' + row['path'])
        terminal_pointer = proof['outer_terminal']
        prior_terminal_raw = contents[directory + terminal_pointer['path']]
        checked_pin(prior_terminal_raw, terminal_pointer, kind + ':terminal')
        prior_terminal = json.loads(prior_terminal_raw)
        check(prior_terminal['state'] == 'succeeded' and prior_terminal['exit_code'] == 0
              and prior_terminal['output_complete'] and prior_terminal['output_durable']
              and not prior_terminal['timed_out'] and not prior_terminal['cancelled'], kind + ' prior terminal')
        prefix = 'native-source53-project-r30' if kind == 'R30' else 'native-source52-project-r28'
        prior_env = json.loads(contents[directory + prefix + '-environment.json'])
        check(prior_env['selection'] == env['selection'] and prior_env['approved_prerequisite_env_pin'] == env['approved_prerequisite_env_pin'],
              kind + ' environment selection differs')
        previous[kind] = {'source_commit': commit, 'source_tree': tree, 'original_count': expected_count,
                          'all_original_pins_rehashed': True, 'outer': prior_terminal,
                          'does_not_substitute_for_current_workspace': True}

    baseline_originals = {}
    for name, (size, digest) in OLD_PINS.items():
        value = contents['input/r29-original-workspace-baseline/' + name]
        require(len(value) == size and pin(value)['sha256'] == digest, 'original R29 baseline changed: ' + name)
        baseline_originals[name] = value
    old_rows, old_parsed = parse_log(baseline_originals['native-workspace-r29-tests.log'])
    require(old_rows == json.loads(baseline_originals['native-workspace-r29-test-results.json']), 'original R29 rows differ from full log')
    require(old_parsed['terminal_unique_test_count'] == 20228
            and old_parsed['terminal_counts'] == {'PASS': 20227, 'FAIL': 1, 'TIMEOUT': 0}
            and old_parsed['reported_skipped'] == 130, 'original failed R29 population differs')
    baseline = {(row['binary'], row['name']) for row in old_rows}
    old_failed_records = {}
    for row in pre['original_r29_failed_100_provenance']:
        data = contents['input/r29-failed-provenance/' + row['path']]
        checked_pin(data, row, 'original R29 failed provenance')
        old_failed_records[row['path']] = json.loads(data)
    old_terminal = old_failed_records['native-workspace-r29-terminal-process-status.json']
    old_return = old_failed_records['native-workspace-r29-tests-raw-process-result.json']
    old_receipt = old_failed_records['native-workspace-r29-tests-receipt.json']
    check(old_terminal['exit_code'] == old_return['exit_code'] == old_receipt['effective_exit_code'] == 100
          and old_terminal['state'] == 'failed' and old_return['source_commit'] == OLD_COMMIT
          and old_return['source_tree'] == OLD_TREE, 'original R29 100 identity/exit changed')
    check(old_receipt['log_sha256'] == OLD_PINS['native-workspace-r29-tests.log'][1], 'original R29 log/receipt binding')

    metadata_raw, metadata_stderr = original('-metadata.json'), original('-metadata-stderr.log')
    metadata = json.loads(metadata_raw)
    metadata_return, metadata_receipt = document('-metadata-raw-process-result.json'), document('-metadata-receipt.json')
    for key in ('source_commit', 'source_tree', 'command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
        check(metadata_return[key] == metadata_receipt[key], 'metadata raw/receipt: ' + key)
    check(metadata_return['schema'] == 'hepta.native-raw-process-result.v1'
          and metadata_return['phase'] == 'workspace-metadata'
          and metadata_return['source_commit'] == COMMIT and metadata_return['source_tree'] == TREE
          and metadata_return['command'] == METADATA_COMMAND and metadata_return['cwd'] == CWD, 'fresh metadata command/source')
    check(metadata_return['exit_code'] == 0 and metadata_receipt['source_guards_pass'], 'fresh metadata original result')
    check(metadata_return['start_unix'] >= previous['R30']['outer']['at_unix_ms'] / 1000, 'metadata predates same-source R30 pass')
    check(abs(metadata_receipt['elapsed_seconds'] - (metadata_return['end_unix'] - metadata_return['start_unix'])) < 1e-6,
          'metadata elapsed accounting')
    pointer(metadata_receipt['raw_process_result'], '-metadata-raw-process-result.json')
    pointer(metadata_receipt['source_postguard'], '-metadata-source-post-verification.json')
    check(metadata_receipt['stdout'] == pin(metadata_raw) and metadata_receipt['stderr'] == pin(metadata_stderr), 'metadata output pins')
    guard('-metadata-source-post-verification.json')
    members, defaults = metadata['workspace_members'], metadata['workspace_default_members']
    require(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == 193
            and set(members) == set(defaults), 'fresh metadata is not the full default193')
    packages = {package['id']: package for package in metadata['packages']}
    require(len(packages) == len(metadata['packages']) and set(members) <= set(packages), 'ambiguous metadata packages')
    check(metadata['workspace_root'] == CWD and metadata['target_directory'] == T + '/target', 'metadata source/target root')
    scope = document('-scope.json')
    check(scope['workspace_members'] == [{'id': identifier, 'name': packages[identifier]['name'],
                                        'manifest_path': packages[identifier]['manifest_path']} for identifier in members],
          'scope member order/fields differ from original metadata')
    check(scope['workspace_default_members'] == [{'id': identifier, 'name': packages[identifier]['name']} for identifier in defaults],
          'scope default-member order/fields differ')
    for key, expected in {'source_commit': COMMIT, 'source_tree': TREE, 'metadata_generated_on_current_source': True,
                          'old_metadata_reused_as_current': False, 'workspace_member_count': 193,
                          'workspace_default_member_count': 193, 'command': COMMAND, 'metadata_command': METADATA_COMMAND,
                          'features': 'unchanged_defaults', 'filters': 'no_additions', 'diagnostic_only': True,
                          'behavior_repair_claimed': False}.items():
        check(scope[key] == expected, 'scope field: ' + key)
    pointer(scope['metadata'], '-metadata.json')

    raw, receipt = document('-tests-raw-process-result.json'), document('-tests-receipt.json')
    for key in ('phase', 'source_commit', 'source_tree', 'command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
        check(raw[key] == receipt[key], 'workspace raw/receipt: ' + key)
    check(raw['schema'] == 'hepta.native-raw-process-result.v1' and raw['phase'] == 'workspace-tests'
          and receipt['schema'] == 'hepta.native-workspace-gate-receipt.v2', 'workspace raw/receipt schemas')
    check(raw['source_commit'] == COMMIT and raw['source_tree'] == TREE and raw['command'] == COMMAND
          and raw['cwd'] == CWD, 'workspace actual command/source')
    check(raw['start_unix'] >= metadata_return['end_unix'] and raw['end_unix'] >= raw['start_unix'], 'phase order')
    check(abs(receipt['elapsed_seconds'] - (raw['end_unix'] - raw['start_unix'])) < 1e-6, 'workspace elapsed accounting')
    pointer(receipt['raw_process_result'], '-tests-raw-process-result.json')
    pointer(receipt['source_preguard'], '-tests-source-pre-verification.json')
    pointer(receipt['source_postguard'], '-source-post-test-verification.json')
    pointer(receipt['scope'], '-scope.json')
    guard('-tests-source-pre-verification.json')
    post = guard('-source-post-test-verification.json')
    check(post['phase'] == 'workspace-tests' and post['gate_exit_code'] == raw['exit_code'], 'postguard original return')
    log, resources = original('-tests.log'), original('-tests-resources.txt')
    require(pin(log)['sha256'] == args.tests_log_sha256, 'tests log external pin differs')
    check(receipt['log_sha256'] == pin(log)['sha256'] and receipt['resources_sha256'] == pin(resources)['sha256'], 'original output hashes')
    check(re.findall(rb'^\s*Exit status: (\d+)\s*$', resources, re.M) == [str(raw['exit_code']).encode()], 'resource/raw exit differs')
    effective = raw['exit_code'] if raw['exit_code'] else (1 if receipt['issues'] else 0)
    check(receipt['effective_exit_code'] == effective and receipt['phase_pass'] == (effective == 0), 'raw/effective semantics')
    check(terminal['exit_code'] == effective and terminal['at_unix_ms'] / 1000 >= raw['end_unix'], 'outer/final phase timing or exit')
    for key, expected in {'source_manifest_sha256': SOURCE_SHA, 'test_scope': 'original_default_workspace',
                          'packages_argument': None, 'workspace_member_count': 193, 'workspace_default_member_count': 193,
                          'retries': 0, 'features': 'unchanged_defaults', 'filters': 'no_additions',
                          'fix_fmt_executed': False, 'outer_timeout_seconds_contract': 9600,
                          'test_ids_used_as_filter': False, 'exact_old_test_id_set_required': True,
                          'diagnostic_only': True, 'behavior_repair_claimed': False}.items():
        check(receipt[key] == expected, 'receipt scope: ' + key)
    rows, parsed = parse_log(log)
    require(rows == document('-test-results.json'), 'current derived rows differ from independent whole original log')
    identities = {(row['binary'], row['name']) for row in rows}
    missing, additional = sorted(baseline - identities), sorted(identities - baseline)
    names = {packages[identifier]['name'] for identifier in members}
    unknown = sorted({row['binary'].split('::', 1)[0] for row in rows} - names)
    check(not unknown, 'execution contains package outside actual default193')
    parsed.update(exact_original20228_identity_set=parsed['complete_execution_accounting'] and not missing and not additional,
                  baseline_missing=[{'binary': b, 'name': n} for b, n in missing],
                  additional_test_ids=[{'binary': b, 'name': n} for b, n in additional],
                  unknown_workspace_packages=unknown)
    derived = document('-result-review.json')
    for key in ('nextest_started', 'complete_execution_accounting', 'execution_rows_observed',
                'terminal_unique_test_count', 'terminal_counts', 'reported_skipped', 'footer_rows_excluded',
                'baseline_missing', 'additional_test_ids', 'unknown_workspace_packages'):
        check(derived[key] == parsed[key], 'original derived review differs: ' + key)
    check(derived['log'] == pin(log) and derived['source_commit'] == COMMIT and derived['source_tree'] == TREE,
          'original review source/log')
    pointer(receipt['acceptance_readback'], '-result-review.json')
    check(receipt['original_r29_workspace_baseline'] == pre['original_r29_workspace_baseline'],
          'receipt original R29 baseline proof differs')
    all_pass = (parsed['complete_execution_accounting'] and not missing and not additional
                and parsed['terminal_counts']['FAIL'] == parsed['terminal_counts']['TIMEOUT'] == 0)
    check(derived['pass'] == all_pass, 'derived pass differs from complete original accounting')
    if terminal['exit_code'] == 0:
        check(all_pass and not receipt['issues'] and receipt['source_guards_pass'], 'successful outer without complete exact PASS')
        require(all(P + suffix in originals for suffix in SUCCESS_SUFFIXES), 'missing successful original')
        complete = document('-complete.json')
        for key, expected in {'source_commit': COMMIT, 'source_tree': TREE, 'source_manifest_sha256': SOURCE_SHA,
                              'workspace_exit': raw['exit_code'], 'effective_exit_code': effective, 'source_guards_pass': True,
                              'command': COMMAND, 'workspace_member_count': 193, 'workspace_default_member_count': 193,
                              'unique_test_count': parsed['terminal_unique_test_count'], 'counts': parsed['terminal_counts'],
                              'reported_skipped': parsed['reported_skipped'], 'fix_fmt_executed': False,
                              'all_platforms_features_external_services_qualified': False, 'exact_old_test_id_set_observed_pass': True,
                              'original_r29_failure_relabelled_as_pass': False, 'test_ids_used_as_filter': False,
                              'diagnostic_only': True, 'behavior_repair_claimed': False}.items():
            check(complete[key] == expected, 'complete field: ' + key)
        pointer(complete['receipt'], '-tests-receipt.json')
        pointer(complete['readback'], '-result-review.json')
        pointer(complete['scope'], '-scope.json')
        check(complete['original_r29_workspace_baseline'] == pre['original_r29_workspace_baseline'],
              'complete original R29 baseline proof differs')
    else:
        check(P + '-complete.json' not in originals, 'failed gate incorrectly has complete')

    controller = {name[len('controller/'):]: data for name, data in contents.items() if name.startswith('controller/')}
    require(controller['terminal-process-status.json'] == terminal_raw, 'controller terminal differs from gate terminal')
    launch = json.loads(controller['launch.json'])
    job = launch['job']
    check(job['id'] == JOB and job['launch_state'] == 'launched' and launch['launch']['ok']
          and launch['reused'] is False and launch['local_record_pending'] is False, 'launch identity/state')
    check(job['host'] == 'pocket4' and job['executable'] == '/usr/bin/python3'
          and job['args'] == [T + '/native-run-r31.py'] and job['cwd'] == T
          and job['idempotency_key'] == KEY and job['env_keys'] == [], 'direct-file argv/key/environment')
    auth_raw = args.root_authorization.read_bytes()
    require(pin(auth_raw)['sha256'] == AUTH_SHA, 'root launch authorization differs')
    authority = json.loads(auth_raw)
    runner = contents['input/native-run-r31.py']
    require(len(runner) == 128291 and pin(runner)['sha256'] == RUNNER_SHA == authority['runner']['sha256'], 'actual runner/authority differs')
    check(authority['unique_launch_key'] == KEY and authority['workspace_command'] == COMMAND
          and authority['fix_fmt_authorized'] is False, 'root authorization scope')
    streams, controller_rows = {}, []
    reads = [(name, json.loads(data)) for name, data in controller.items() if name.startswith('read-') and name.endswith('.json')]
    for stream in ('stdout', 'stderr'):
        parts = []
        for name, value in reads:
            require(value['job_id'] == JOB, 'controller read wrong job')
            item = value[stream]
            data = bytes.fromhex(item['bytes_hex'])
            require(item['text'].encode() == data and len(data) == item['next_offset'] - item['offset']
                    and item['size'] >= item['next_offset'], 'controller range/text/hex mismatch')
            parts.append((item['offset'], data))
            controller_rows.append({'file': name, 'stream': stream, 'offset': item['offset'],
                                    'next_offset': item['next_offset'], 'size': item['size'], 'eof': item['eof'], **pin(data)})
        end, chunks = 0, []
        for offset, data in sorted(parts, key=lambda item: item[0]):
            if not data:
                require(offset <= end, 'empty read beyond reconstructed stream')
                continue
            require(offset == end, 'controller gap or overlap')
            chunks.append(data); end += len(data)
        streams[stream] = b''.join(chunks)
        check(streams[stream] == controller['original-' + stream + '.txt'], 'derived controller stream differs')
        check(end == terminal['log_bytes'][stream]['seen'] == terminal['log_bytes'][stream]['stored'], 'terminal stream length differs')
    events = [json.loads(line) for line in streams['stdout'].splitlines()]
    check(len(events) == 3, 'unexpected number of original workspace announcements')
    if len(events) == 3:
        start, raw_event, receipt_event = events
        check(start['phase'] == 'original-default-workspace-start' and start['command'] == COMMAND
              and start['source_tree'] == TREE and start['source_commit'] == COMMIT
              and start['workspace_member_count'] == start['workspace_default_member_count'] == 193, 'start event differs')
        check(raw_event == {**raw, 'event': 'workspace-raw-process-return'}, 'raw announcement differs')
        check(receipt_event == receipt, 'original receipt announcement differs')
    check(job['created_unix_ms'] / 1000 <= metadata_return['start_unix'], 'launch after metadata start')

    current_by_id = {(row['binary'], row['name']): row for row in rows}
    old_failed = [{'source52_R29_failed_observation': row,
                   'source53_R31_observation': current_by_id.get((row['binary'], row['name']))}
                  for row in old_rows if row['status'] != 'PASS']
    archive_derived = document('-closed-result-review.json')
    check(archive_derived['original_outer_exit'] == terminal['exit_code']
          and archive_derived['counts'] == parsed['terminal_counts']
          and archive_derived['reported_skipped'] == parsed['reported_skipped'], 'export-derived result differs')
    check(archive_derived['readback_errors'] == [], 'exporter recorded readback errors')
    if terminal['exit_code'] == 0:
        check(archive_derived['actual_original_filenames'] == sorted(P + suffix for suffix in SUCCESS_SUFFIXES),
              'successful actual-original set is not exactly18')
    if P + '-closed-test-results.json' in originals:
        check(document('-closed-test-results.json') == rows, 'export-derived rows differ')
    failure_index = json.loads(contents['failure-blocks/INDEX.json'])
    check(len(failure_index['failures']) == len(parsed['failure_spans']), 'export failure block count differs')
    for i, block in enumerate(parsed['failure_spans'], 1):
        check(contents['failure-blocks/failure-' + str(i) + '.txt'] == log[block['byte_offset']:block['byte_end']],
              'export raw failure block differs')
    actual_pass = terminal['exit_code'] == effective == raw['exit_code'] == 0 and all_pass
    report = {
        'schema': 'hepta.source53-r31-independent-complete-readback.v1',
        'classification': 'EVIDENCE_INCONSISTENCY' if errors else ('CLOSED_DEFAULT_WORKSPACE_PASS' if actual_pass else 'CLOSED_DEFAULT_WORKSPACE_FAILED'),
        'integrity_errors': errors, 'source_commit': COMMIT, 'source_tree': TREE, 'native_HEAD': HEAD,
        'archive': {'path': str(args.archive), **pin(archive_raw), 'regular_members': len(contents), 'indexed_members': len(archive_members),
                    'all_member_raw_sha_gitblob_modes_verified': True},
        'source': {'manifest': pin(source_raw), 'raw_files_independently_verified': 197, 'rust_paths': 183,
                   'other_paths': 14, 'dual_locks': LOCKS, 'native_closed_guards_verified': True,
                   'independent_full_Git_tree_reconstruction_performed': False,
                   'parent_source52_original195_rows_preserved_plus_two_diagnostic_leaves': True,
                   'Git_modes_not_confused_with_tar_permission_bits': True},
        'fresh_metadata': {'original': pin(metadata_raw), 'raw': pin(original('-metadata-raw-process-result.json')),
                           'receipt': pin(original('-metadata-receipt.json')), 'raw_exit': metadata_return['exit_code'],
                           'receipt_exit': metadata_receipt['exit_code'], 'elapsed_seconds': metadata_receipt['elapsed_seconds'],
                           'members': len(members), 'default_members': len(defaults), 'scope': pin(original('-scope.json')),
                           'original_order_and_package_records_verified': True,
                           'metadata_command_executed_by_this_reader': False,
                           'equal_raw_bytes_to_historical_metadata_do_not_change_original_invocation_identity': True},
        'execution': parsed,
        'phase': {'command': raw['command'], 'cwd': raw['cwd'], 'raw_exit': raw['exit_code'],
                  'effective_exit': effective, 'wall_seconds_including_build': receipt['elapsed_seconds'],
                  'raw': pin(original('-tests-raw-process-result.json')), 'receipt': pin(original('-tests-receipt.json')),
                  'log': pin(log), 'resources': pin(resources), 'source_guards_pass': receipt['source_guards_pass']},
        'outer': {'job': JOB, 'original': pin(terminal_raw), 'state': terminal['state'], 'exit_code': terminal['exit_code'],
                   'at_unix_ms': terminal['at_unix_ms'], 'natural': True, 'complete_durable_output': True},
        'controller': {'launch': pin(controller['launch.json']), 'read_count': len(reads), 'ranges': controller_rows,
                       'stdout': pin(streams['stdout']), 'stderr': pin(streams['stderr']),
                       'raw_return_and_receipt_events_equal_original_files': True,
                       'stream_size_is_total_at_read_not_chunk_length': True, 'root_authorization': pin(auth_raw),
                       'actual_runner': pin(runner)},
        'prior_source_gate_pins': previous,
        'original_R29_failed_population': {'source_commit': OLD_COMMIT, 'source_tree': OLD_TREE,
                                          'counts': old_parsed['terminal_counts'], 'reported_skipped': old_parsed['reported_skipped'],
                                          'unique_ids': len(baseline), 'original_exit': 100,
                                          'full_log_reparsed_and_rows_byte_identity_fields_matched': True,
                                          'old_failed_to_current_observations': old_failed, 'original_failure_relabelled': False},
        'all18_originals_plus_outer_rehashed': all(P + suffix in originals for suffix in SUCCESS_SUFFIXES),
        'diagnostic_only': True, 'behavior_repair_claimed': False,
        'identity_baseline_used_as_filter': False, 'skip_identities_inferred': False,
        'all_platforms_features_external_services_qualified': False,
        'finalizer_executed_or_authorized_by_this_reader': False, 'science_qualification': False,
        'shared_filesystem_free_samples_are_not_exclusive_gate_cost': True,
        'runner_imported_or_executed': False, 'native_Rust_metadata_fix_fmt_or_git_commands_executed': False}
    args.output.mkdir(parents=True, exist_ok=False)
    def save(name, value, compress=False):
        data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
        stored = gzip.compress(data, mtime=0) if compress else data
        if compress:
            require(gzip.decompress(stored) == data, 'local report gzip roundtrip')
        with (args.output / name).open('xb') as stream:
            stream.write(stored); stream.flush(); os.fsync(stream.fileno())
        return {'path': name, **pin(stored), 'uncompressed': pin(data) if compress else None}
    report['independent_rows'] = save('EXECUTED-ROWS.json.gz', rows, True)
    report['archive_members_readback'] = save('ARCHIVE-MEMBERS.json', archive_members)
    report['source_file_readback'] = save('SOURCE-FILES.json', source_rows)
    report['original_pins'] = save('ORIGINAL-PINS.json', [{'path': 'evidence/' + P + suffix, **pin(original(suffix))}
                                                        for suffix in (*SUCCESS_SUFFIXES, '-terminal-process-status.json')
                                                        if P + suffix in originals])
    report_pin = save('INDEPENDENT-READBACK.json', report)
    print(json.dumps({'report': report_pin, 'classification': report['classification'],
                      'unique_ids': parsed['terminal_unique_test_count'], 'counts': parsed['terminal_counts'],
                      'reported_skipped': parsed['reported_skipped'], 'integrity_errors': errors}))
    return 2 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
