import collections
import hashlib
import json
import os
import pathlib
import re
import tarfile

ROOT = pathlib.Path('native-validation-results/r29-archive-closed')
SMALL = pathlib.Path('native-validation-results/r29-closed-input')
COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
PREFIX = 'evidence/native-workspace-r29'
COMMAND = ['just', 'test', '--locked', '--retries', '0']


def pin(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
    }


expected = json.loads((ROOT / 'ARCHIVE-EXPECTED.json').read_bytes())
archive = ROOT / 'checkpoint-r29-closed.tar.gz'
archive_raw = archive.read_bytes()
assert pin(archive_raw) == {k: expected[k] for k in ('bytes', 'sha256', 'git_blob')}
contents, modes = {}, {}
with tarfile.open(archive, 'r:gz') as packed:
    for member in packed.getmembers():
        name = pathlib.PurePosixPath(member.name)
        assert member.isfile() and not name.is_absolute() and '..' not in name.parts
        assert member.name == str(name) and member.name not in contents
        raw = packed.extractfile(member).read()
        assert len(raw) == member.size
        contents[member.name], modes[member.name] = raw, member.mode
assert len(contents) == 315
index = json.loads(contents['INDEX.json'])
assert index['source_commit'] == COMMIT and index['source_tree'] == TREE
assert index['source_count'] == 195 and index['classification'] == 'original_default_workspace_failed'
assert index['original_workspace_exit'] == index['effective_workspace_exit'] == index['original_outer_exit'] == 100
indexed = {row['path']: row for row in index['files']}
assert len(indexed) == len(index['files']) == 314 and set(indexed) == set(contents) - {'INDEX.json'}
for name, row in indexed.items():
    assert pin(contents[name]) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}, name
    assert modes[name] == row['mode'], name

manifest_raw = contents['input/native-candidate-r28-source.json']
manifest = json.loads(manifest_raw)
assert manifest_raw == pathlib.Path('source52-preparation/native-candidate-r28-source.json').read_bytes()
assert manifest['source_commit'] == COMMIT and manifest['source_tree'] == TREE
assert len(manifest['changed_files']) == manifest['changed_file_count'] == 195
source_names = {'source/' + row['path'] for row in manifest['changed_files']}
assert source_names == {name for name in contents if name.startswith('source/')}
for row in manifest['changed_files']:
    name = 'source/' + row['path']
    assert pin(contents[name]) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}, name
    assert ('100755' if modes[name] & 0o111 else '100644') == row['mode'], name

bindings = json.loads((SMALL / 'PROPOSED-EXPORT-BINDINGS.json').read_bytes())
assert len(bindings['CLOSED_ORIGINAL_PINS']) == 18
for name, bound in bindings['CLOSED_ORIGINAL_PINS'].items():
    raw = contents['evidence/' + name]
    assert {k: pin(raw)[k] for k in ('bytes', 'sha256')} == bound, name
    local = SMALL / 'evidence' / name
    if local.is_file():
        assert raw == local.read_bytes(), name
for name, bound in bindings['CONTROLLER_ORIGINAL_PINS'].items():
    local_name = name.removeprefix('r29-controller-closed-')
    raw = contents['controller/' + local_name]
    assert raw == (SMALL / 'controller' / local_name).read_bytes()
    assert {k: pin(raw)[k] for k in ('bytes', 'sha256')} == bound
assert contents[PREFIX + '-terminal-process-status.json'] == contents['controller/terminal-process-status.json']
prior_count = 0
for name, raw in contents.items():
    if name.startswith('input/r28-prerequisites/'):
        basename = pathlib.PurePosixPath(name).name
        old = pathlib.Path('native-validation-results/r28-archive-closed/original/evidence') / basename
        assert raw == old.read_bytes(), name
        prior_count += 1
assert prior_count == 27

metadata = json.loads(contents[PREFIX + '-metadata.json'])
scope = json.loads(contents[PREFIX + '-scope.json'])
members, defaults = metadata['workspace_members'], metadata['workspace_default_members']
assert len(members) == len(defaults) == len(set(members)) == len(set(defaults)) == 193
assert set(members) == set(defaults)
packages = {row['id']: row for row in metadata['packages']}
assert all(member in packages for member in members)
expected_members = sorted(({'id': x, 'name': packages[x]['name'], 'manifest_path': packages[x]['manifest_path']} for x in members), key=lambda x: x['id'])
expected_defaults = sorted(({'id': x, 'name': packages[x]['name']} for x in defaults), key=lambda x: x['id'])
assert scope['workspace_members'] == expected_members and scope['workspace_default_members'] == expected_defaults
assert scope['source_commit'] == COMMIT and scope['source_tree'] == TREE
assert scope['command'] == COMMAND and scope['metadata_generated_on_current_source'] and not scope['old_metadata_reused_as_current']
workspace_names = {packages[x]['name'] for x in members}

log = contents[PREFIX + '-tests.log']
ansi = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
row_pattern = re.compile(r'^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$')
starts, summaries, rows, footer = [], [], [], []
offset, after_summary = 0, False
for line_number, raw_line in enumerate(log.splitlines(keepends=True), 1):
    line = ansi.sub(b'', raw_line).decode('utf-8').rstrip('\r\n')
    start = re.match(r'^\s*Starting (\d+) tests across (\d+) binaries \((\d+) tests skipped\)\s*$', line)
    if start:
        starts.append((line_number, offset, tuple(map(int, start.groups()))))
    if re.match(r'^\s*Summary\s+\[', line):
        summaries.append((line_number, offset, line))
        after_summary = True
    match = row_pattern.match(line)
    if match:
        status, seconds, binary, name = match.groups()
        row = {'status': status, 'seconds': float(seconds), 'binary': binary, 'name': name, 'line': line_number, 'byte_offset': offset}
        (footer if after_summary else rows).append(row)
    offset += len(raw_line)
assert offset == len(log) and len(starts) == len(summaries) == 1
assert starts[0][2] == (20228, 366, 130)
assert starts[0][0] < rows[0]['line'] <= rows[-1]['line'] < summaries[0][0]
assert len(rows) == len({(row['binary'], row['name']) for row in rows}) == 20228
assert all(row['binary'].split('::')[0] in workspace_names for row in rows)
counts = {name: sum(row['status'] == name for row in rows) for name in ('PASS', 'FAIL', 'TIMEOUT')}
assert counts == {'PASS': 20227, 'FAIL': 1, 'TIMEOUT': 0}
summary = summaries[0][2]
assert re.search(r'20228 tests run: 20227 passed \(4 slow\), 1 failed, 130 skipped\s*$', summary)
assert rows == json.loads(contents[PREFIX + '-test-results.json'])
assert rows == json.loads(contents[PREFIX + '-closed-test-results.json'])
bad = [row for row in rows if row['status'] != 'PASS']
assert len(bad) == len(footer) == 1
assert bad[0]['binary'] == footer[0]['binary'] == 'codex-app-server::all'
assert bad[0]['name'] == footer[0]['name'] == 'suite::v2::bedrock_setup::setup_bedrock_profile_and_environment'
assert bad[0]['status'] == footer[0]['status'] == 'FAIL'
review = json.loads(contents[PREFIX + '-result-review.json'])
assert review['complete_execution_accounting'] and review['terminal_counts'] == counts
assert review['reported_skipped'] == 130 and not review['pass'] and review['footer_rows_excluded'] == footer
assert index['original_counts'] == counts and index['reported_skipped'] == 130
failure_index = json.loads(contents['failure-blocks/INDEX.json'])
failure = failure_index['failures'][0]
next_row = rows[rows.index(bad[0]) + 1]
block = log[bad[0]['byte_offset']:next_row['byte_offset']]
assert block == contents['failure-blocks/failure-1.txt'] == (SMALL / 'failure-blocks/failure-1.txt').read_bytes()
assert pin(block) == {k: failure[k] for k in ('bytes', 'sha256', 'git_blob')}
assert bad[0]['byte_offset'] == 130233 and next_row['byte_offset'] == failure['end_byte_offset'] == 132164

receipt = json.loads(contents[PREFIX + '-tests-receipt.json'])
raw_result = json.loads(contents[PREFIX + '-tests-raw-process-result.json'])
terminal = json.loads(contents['controller/terminal-process-status.json'])
assert receipt['exit_code'] == receipt['effective_exit_code'] == raw_result['exit_code'] == terminal['exit_code'] == 100
assert raw_result['command'] == receipt['command'] == COMMAND and receipt['packages_argument'] is None
assert not receipt['phase_pass'] and not receipt['fix_fmt_executed'] and receipt['source_guards_pass']
assert terminal['state'] == 'failed' and terminal['output_complete'] and terminal['output_durable']
assert not terminal['timed_out'] and not terminal['cancelled'] and not terminal['automatic_retry']
assert not any(terminal['log_truncated'].values()) and not any(terminal['log_errors'].values())
assert all(terminal['log_synced'].values())
assert re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$', contents[PREFIX + '-tests-resources.txt'], re.M) == [b'100']
for name in ('-source-pre-verification.json', '-metadata-source-post-verification.json', '-tests-source-pre-verification.json', '-source-post-test-verification.json'):
    guard = json.loads(contents[PREFIX + name])
    assert guard['pass'] and guard['changed_file_count'] == 195
    assert guard['source_commit'] == COMMIT and guard['actual_tree'] == guard['expected_tree'] == TREE and guard['native_head'] == HEAD
    assert not guard['unstaged_paths'] and not guard['untracked_paths'] and not guard['file_mismatches'] and guard['changed_path_set_matches']
    assert guard['cargo_lock_sha256'] == manifest['cargo_lock_sha256'] and guard['bazel_lock_sha256'] == manifest['bazel_lock_sha256']
proof = json.loads(contents[PREFIX + '-export-source-verification.json'])
assert proof['source_guard_before'] == proof['source_guard_after']
assert not proof['export_modifies_source'] and not proof['rust_rerun'] and not proof['metadata_rerun'] and not proof['fix_fmt_executed_by_exporter']
for stream in ('stdout', 'stderr'):
    raw = contents['controller/original-' + stream + '.txt']
    assert raw == (SMALL / ('controller/original-' + stream + '.txt')).read_bytes()
    assert len(raw) == terminal['log_bytes'][stream]['seen'] == terminal['log_bytes'][stream]['stored']

destination = ROOT / 'original'
destination.mkdir(exist_ok=False)
for name, raw in contents.items():
    path = destination / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(raw)
    os.chmod(path, modes[name])

result = {
    'schema': 'hepta.root-r29-archive-independent-readback.v1',
    'archive': {'path': str(archive), **pin(archive_raw)},
    'members': len(contents), 'index_rows_all_raw_rehashed': len(indexed),
    'total_member_bytes': sum(map(len, contents.values())), 'index': pin(contents['INDEX.json']),
    'source_commit': COMMIT, 'source_tree': TREE, 'source_count': 195,
    'source195_exact_raw_sha_git_blob_and_Git_mode': True,
    'all18_originals_and_original_terminal_exact': True,
    'prior_r28_originals_exact': prior_count,
    'fresh_metadata_default_members_equal': 193,
    'raw_log': pin(log), 'raw_unique_count': len(rows), 'counts': counts, 'reported_skipped': 130,
    'native_original_and_exported_rows_equal_independent_raw_log_parser': True,
    'excluded_footer_duplicate_count': len(footer), 'failure_ids': [{k: row[k] for k in ('binary', 'name', 'status')} for row in bad],
    'failure_block': {'start_byte_offset': bad[0]['byte_offset'], 'end_byte_offset': next_row['byte_offset'], **pin(block)},
    'controller_stdout_bytes': 3462, 'controller_stderr_bytes': 0,
    'original_workspace_exit': 100, 'effective_workspace_exit': 100, 'original_outer_exit': 100,
    'source_before_after_equal': True, 'archive_export_is_not_a_new_gate': True,
    'engineering_default_workspace_gate': 'FAIL', 'finalizer_qualified': False,
    'fix_fmt_executed': False, 'science': 'HOLD', 'authority': 'DENY_ALL',
}
raw = (json.dumps(result, indent=2) + '\n').encode()
with (ROOT / 'ROOT-ARCHIVE-READBACK.json').open('xb') as output:
    output.write(raw)
    output.flush()
    os.fsync(output.fileno())
print(json.dumps({'path': str(ROOT / 'ROOT-ARCHIVE-READBACK.json'), **pin(raw), 'counts': counts, 'members': len(contents)}))
