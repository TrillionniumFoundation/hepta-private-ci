"""Create-only export of closed r23 originals and the exact tested source49 tree."""
from pathlib import Path
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile

FROZEN = True
T = Path('/home/alex/work/hepta-cell-unified-20261106-a')
S = T / 'source'
E = T / 'evidence'
TREE = 'be34ab1afe622ad3b8f030c8c5018f4f54fbc304'
COMMIT = '50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a'
PREFIX = 'native-workspace-r23'
JOB = '1a1b0f18be6-fc05-7441'
SOURCE_NAME = 'native-candidate-r22-source.json'
SOURCE_SHA = '8cd1ec59c95d6c777d887f3302b257dc5230a7bfa5570fe9df0f0b2ef361aba5'
LOCK_SHA = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
RUNNER_SHA = '2911377daa62a5ceab83a18d4258edf9d2224219605e473b8e9e4e74ae9754f8'
COMMAND = ['just', 'test', '--locked', '--retries', '0']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    raw = (json.dumps(value, indent=2) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def git(*args):
    return subprocess.check_output(['git', *args], cwd=S)


def source_guard():
    assert git('write-tree').decode().strip() == TREE
    assert git('diff', '--name-only') == b''
    assert git('ls-files', '--others', '--exclude-standard') == b''
    assert sha((S / 'codex-rs/Cargo.lock').read_bytes()) == LOCK_SHA


def result_readback(raw, receipt, terminal):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    summary_index = next((i for i, line in enumerate(lines)
                          if re.match(r'^\s*Summary\s+\[', line)), len(lines))
    rows = []
    offset = 0
    starts = []
    row_pattern = re.compile(
        r'^\s*(PASS|FAIL|TIMEOUT|CRASH|LEAK|EXECFAIL|XFAIL|XPASS)\s+'
        r'\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$')
    start_pattern = re.compile(
        r'^\s*Starting\s+(\d+)\s+tests?\s+across\s+(\d+)\s+binar(?:y|ies)\b')
    for index, line in enumerate(lines):
        start = start_pattern.match(line)
        if start:
            starts.append({'line': index + 1, 'byte_offset': offset,
                           'test_count': int(start.group(1)),
                           'binary_count': int(start.group(2)), 'text': line.rstrip('\n')})
        match = row_pattern.match(line) if index < summary_index else None
        if match:
            status, seconds, binary, name = match.groups()
            rows.append({'status': status, 'seconds': float(seconds), 'binary': binary,
                         'name': name, 'line': index + 1, 'byte_offset': offset})
        offset += len(line.encode())
    summaries = [{'line': i + 1, 'text': line.rstrip('\n')}
                 for i, line in enumerate(lines) if re.match(r'^\s*Summary\s+\[', line)]
    keyed = {}
    duplicates = []
    for item in rows:
        key = (item['binary'], item['name'])
        if key in keyed:
            duplicates.append({'binary': key[0], 'name': key[1],
                               'lines': [keyed[key]['line'], item['line']]})
        else:
            keyed[key] = item
    counts = {status: sum(row['status'] == status for row in rows)
              for status in sorted({row['status'] for row in rows})}
    packages = sorted({row['binary'].split('::', 1)[0] for row in rows})
    per_package = {package: {
        status: sum(row['status'] == status and row['binary'].split('::', 1)[0] == package
                    for row in rows)
        for status in sorted(counts)}
        for package in packages}
    skipped = [int(value) for item in summaries
               for value in re.findall(r'\b(\d+)\s+(?:tests?\s+)?skipped\b', item['text'])]
    errors = []
    execution_started = bool(starts or rows)
    if execution_started:
        if len(starts) != 1:
            errors.append('Expected one original Starting line.')
        if len(summaries) != 1:
            errors.append('Expected one original Summary line.')
        if len(starts) == 1 and starts[0]['test_count'] != len(rows):
            errors.append('Starting count does not equal parsed pre-footer execution rows.')
        if duplicates:
            errors.append('Duplicate pre-footer binary/name execution identities.')
        if len(summaries) == 1:
            totals = re.search(r'\b(\d+)(?:/(\d+))?\s+tests?\s+run\b', summaries[0]['text'])
            if totals and int(totals.group(1)) != len(rows):
                errors.append('Summary run count does not equal parsed execution rows.')
            passed = re.search(r'\b(\d+)\s+passed\b', summaries[0]['text'])
            if passed and int(passed.group(1)) != counts.get('PASS', 0):
                errors.append('Summary passed count does not equal parsed PASS rows.')
    if receipt['exit_code'] == 0:
        if not execution_started or not rows:
            errors.append('Exit zero without parsed original test execution.')
        if any(row['status'] != 'PASS' for row in rows):
            errors.append('Exit zero contains a non-PASS execution row.')
        if terminal['exit_code'] != 0 or terminal['state'] != 'succeeded':
            errors.append('Original command exit zero but wrapper is not succeeded zero.')
    blocks = []
    for index, row in enumerate(rows):
        if row['status'] == 'PASS':
            continue
        end = rows[index + 1]['byte_offset'] if index + 1 < len(rows) else len(
            ''.join(lines[:summary_index]).encode())
        block = raw[row['byte_offset']:end]
        blocks.append({'binary': row['binary'], 'name': row['name'], 'status': row['status'],
                       'start_byte': row['byte_offset'], 'end_byte': end,
                       'sha256': sha(block), 'text': block.decode(),
                       'boundary': 'Original result row through next execution row or Summary; raw full log is authoritative.'})
    review = {
        'schema': 'hepta.r23-closed-workspace-readback.v1',
        'source_tree': TREE, 'source_commit': COMMIT, 'source_manifest_sha256': SOURCE_SHA,
        'log_sha256': sha(raw), 'original_command': COMMAND,
        'original_exit_code': receipt['exit_code'], 'outer_exit_code': terminal['exit_code'],
        'elapsed_seconds': receipt['elapsed_seconds'],
        'test_execution_started': execution_started,
        'unique_execution_id_count': len(keyed) if execution_started else None,
        'execution_row_count': len(rows) if execution_started else None,
        'counts': counts if execution_started else None,
        'per_package': per_package if execution_started else None,
        'reported_skips': skipped, 'starting_lines': starts, 'summary_lines': summaries,
        'duplicate_execution_ids': duplicates, 'readback_errors': errors,
        'readback_pass': not errors,
        'all_parsed_execution_rows_pass': bool(rows) and all(row['status'] == 'PASS' for row in rows),
        'compiler_error_headings': re.findall(r'^error(?:\[[^\]]+\])?:.*$', text, re.M),
        'workspace_member_count': 193, 'workspace_default_member_count': 193,
        'features_filters_deadlines_retries_ignored_attributes_changed_by_export': False,
        'fix_fmt_executed': False,
        'scope_limit': 'Counts are this original r23 invocation only; previous gates are not added. Skips are original reported counts, not newly run tests.'
    }
    return review, rows, blocks


def run():
    assert FROZEN, 'Preparation must not execute'
    terminal_raw = (E / (PREFIX + '-terminal-process-status.json')).read_bytes()
    terminal = json.loads(terminal_raw)
    assert terminal['job_id'] == JOB and terminal['state'] in ('succeeded', 'failed')
    assert terminal['output_complete'] and terminal['output_durable']
    assert terminal['terminal_publication_confirmed']
    assert not terminal['timed_out'] and not terminal['cancelled'] and not terminal['automatic_retry']
    source_raw = (E / SOURCE_NAME).read_bytes()
    assert sha(source_raw) == SOURCE_SHA
    source = json.loads(source_raw)
    assert source['source_tree'] == TREE and source['source_commit'] == COMMIT
    assert len(source['changed_files']) == 188
    source_guard()
    names = [
        SOURCE_NAME, PREFIX + '-terminal-process-status.json',
        PREFIX + '-process.stdout.txt', PREFIX + '-process.stderr.txt',
        PREFIX + '-metadata.json', PREFIX + '-scope.json',
        PREFIX + '-environment.json', PREFIX + '-source-pre-verification.json',
        PREFIX + '-tests.log', PREFIX + '-tests-receipt.json',
        PREFIX + '-tests-raw-process-result.json', PREFIX + '-tests-resources.txt',
        PREFIX + '-source-post-test-verification.json']
    originals = {name: (E / name).read_bytes() for name in names}
    for stream in ('stdout', 'stderr'):
        raw = originals[PREFIX + '-process.' + stream + '.txt']
        assert len(raw) == terminal['log_bytes'][stream]['stored']
        assert terminal['log_bytes'][stream]['stored'] == terminal['log_bytes'][stream]['seen']
        assert not terminal['log_truncated'][stream]
    receipt = json.loads(originals[PREFIX + '-tests-receipt.json'])
    process = json.loads(originals[PREFIX + '-tests-raw-process-result.json'])
    for item in (receipt, process):
        assert item['source_tree'] == TREE and item['source_commit'] == COMMIT
        assert item['command'] == COMMAND and item['cwd'] == str(S / 'codex-rs')
    assert receipt['exit_code'] == process['exit_code']
    assert receipt['start_unix'] == process['start_unix'] and receipt['end_unix'] == process['end_unix']
    assert sha(originals[PREFIX + '-tests.log']) == receipt['log_sha256']
    assert sha(originals[PREFIX + '-tests-resources.txt']) == receipt['resources_sha256']
    assert re.search(rb'Exit status:\s*' + str(receipt['exit_code']).encode() + rb'\s*$',
                     originals[PREFIX + '-tests-resources.txt'], re.M)
    for suffix in ('-source-pre-verification.json', '-source-post-test-verification.json'):
        guard = json.loads(originals[PREFIX + suffix])
        assert guard['pass'] and guard['actual_tree'] == TREE and guard['changed_file_count'] == 188
        assert guard['lock_sha256'] == LOCK_SHA
        assert not guard['file_mismatches'] and not guard['unstaged_paths'] and not guard['untracked_paths']
    metadata_raw = originals[PREFIX + '-metadata.json']
    metadata = json.loads(metadata_raw)
    scope = json.loads(originals[PREFIX + '-scope.json'])
    assert scope['metadata_sha256'] == sha(metadata_raw)
    assert len(metadata['workspace_members']) == len(metadata['workspace_default_members']) == 193
    assert set(metadata['workspace_members']) == set(metadata['workspace_default_members'])
    assert [item['id'] for item in scope['workspace_members']] == metadata['workspace_members']
    assert [item['id'] for item in scope['workspace_default_members']] == metadata['workspace_default_members']
    environment = json.loads(originals[PREFIX + '-environment.json'])
    assert environment['source_tree'] == TREE and environment['source_commit'] == COMMIT
    assert environment['source_manifest_sha256'] == SOURCE_SHA
    assert environment['original_default_workspace_selection']
    if receipt['exit_code'] == 0:
        name = PREFIX + '-complete.json'
        originals[name] = (E / name).read_bytes()
        complete = json.loads(originals[name])
        assert complete['source_tree'] == TREE and complete['source_commit'] == COMMIT
        assert complete['workspace_exit'] == 0 and complete['command'] == COMMAND
        assert complete['source_guards_pass'] and complete['fix_fmt_executed'] is False
    review, rows, blocks = result_readback(originals[PREFIX + '-tests.log'], receipt, terminal)
    for suffix, value in (('-closed-result-review.json', review),
                          ('-closed-test-results.json', rows),
                          ('-closed-failure-blocks.json', blocks)):
        name = PREFIX + suffix
        write(E / name, value)
        originals[name] = (E / name).read_bytes()
    blobs = {'evidence/' + name: (raw, 0o644) for name, raw in originals.items()}
    for item in source['changed_files']:
        raw = git('show', TREE + ':' + item['path'])
        mode, kind, blob = git('ls-tree', TREE, '--', item['path']).decode().split('\t')[0].split()
        assert kind == 'blob' and mode == item['mode'] and blob == item['git_blob']
        assert len(raw) == item['bytes'] and sha(raw) == item['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob
        assert (S / item['path']).read_bytes() == raw
        actual_mode = '100755' if (S / item['path']).stat().st_mode & 0o111 else '100644'
        assert actual_mode == mode
        blobs['source/' + item['path']] = (raw, int(mode, 8) & 0o777)
    runner = (T / 'native-run-r23.py').read_bytes()
    assert sha(runner) == RUNNER_SHA
    blobs['input/native-run-r23.py'] = (runner, 0o644)
    blobs['input/Cargo.lock'] = ((S / 'codex-rs/Cargo.lock').read_bytes(), 0o644)
    for name in ('native-app-server-client-r22-strict-receipt.json',
                 'native-app-server-client-r22-tests-receipt.json',
                 'native-app-server-client-r22-complete.json',
                 'native-app-server-client-r22-result-review.json'):
        blobs['input/' + name] = ((E / name).read_bytes(), 0o644)
    source_guard()
    index = [{'path': name, 'bytes': len(raw), 'sha256': sha(raw), 'mode': f'{mode:04o}'}
             for name, (raw, mode) in sorted(blobs.items())]
    blobs['INDEX.json'] = ((json.dumps(index, indent=2) + '\n').encode(), 0o644)
    archive_path = E / 'checkpoint-r23-closed.tar.gz'
    with archive_path.open('xb') as output, gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|') as archive:
            for name, (raw, mode) in sorted(blobs.items()):
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                info.mode = mode
                info.mtime = 0
                archive.addfile(info, io.BytesIO(raw))
    archive_raw = archive_path.read_bytes()
    result = {'path': str(archive_path), 'bytes': len(archive_raw), 'sha256': sha(archive_raw),
              'members': len(blobs), 'source_files': 188, 'source_tree': TREE, 'source_commit': COMMIT,
              'original_exit_code': receipt['exit_code'], 'outer_exit_code': terminal['exit_code'],
              'counts': review['counts'], 'reported_skips': review['reported_skips'],
              'readback_pass': review['readback_pass'], 'readback_errors': review['readback_errors'],
              'test_execution_started': review['test_execution_started'],
              'source_modified_by_export': False, 'rust_executed_by_export': False,
              'final_fix_fmt_executed': False}
    write(E / 'checkpoint-r23-export.json', result)
    try:
        print(json.dumps(result), flush=True)
    except OSError:
        pass


if __name__ == '__main__':
    run()
