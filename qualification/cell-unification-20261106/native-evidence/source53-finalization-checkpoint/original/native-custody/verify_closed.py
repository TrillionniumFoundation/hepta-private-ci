"""Offline readback of already closed originals; never executes native tools."""
import hashlib
import json
import re
from pathlib import Path

D = Path(__file__).parent
E = D / 'evidence'
ROOT = D.parents[1]
TESTED = '440d4a8e09af4009e4d9ea067388826308da8803'
FORMATTED = '42c1dd4e1a751c690c2800dfc3868e771dc9c70b'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read_json(name):
    return json.loads((E / name).read_bytes())


def verify_pin(name, expected):
    actual = pin((E / name).read_bytes())
    assert all(actual[k] == expected[k] for k in actual), (name, expected, actual)
    return actual


def write_new(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with (D / name).open('xb') as handle:
        handle.write(raw)
    return {'path': name, **pin(raw)}


def main():
    terminal_raw = (D / 'controller/terminal-process-status-original.json').read_bytes()
    terminal = json.loads(terminal_raw)
    assert terminal['job_id'] == '1a1b2a75955-fc05-7f27'
    assert terminal['state'] == 'succeeded' and terminal['exit_code'] == 0
    assert terminal['output_complete'] and terminal['output_durable'] and terminal['terminal_publication_confirmed']
    assert not terminal['automatic_retry'] and not terminal['timed_out'] and not terminal['cancelled']
    stdout = (D / 'controller/original-stdout.log').read_bytes()
    stderr = (D / 'controller/original-stderr.log').read_bytes()
    assert len(stdout) == terminal['log_bytes']['stdout']['seen'] == terminal['log_bytes']['stdout']['stored'] == 8595
    assert len(stderr) == terminal['log_bytes']['stderr']['seen'] == terminal['log_bytes']['stderr']['stored'] == 0
    events = [json.loads(line) for line in stdout.splitlines()]
    assert len(events) == 7 and events[0]['phase'] == 'fix-start' and events[3]['phase'] == 'format-start'
    assert events[-1]['phase'] == 'finalization-complete'
    authorization = json.loads((D / 'input/ROOT-EXECUTION-AUTHORIZATION.json').read_bytes())
    assert pin((D / 'input/executed.py').read_bytes()) == {key: authorization['script'][key] for key in ('bytes', 'sha256', 'git_blob')}

    complete = read_json('complete.json')
    assert complete['tested_source_tree'] == TESTED and complete['final_formatted_tree'] == FORMATTED
    assert complete['final_formatted_commit'] is None
    assert complete['native_HEAD'] == 'bef6fa7645df9df12b69fda499e97eed25de6c75'
    assert complete['post_fix_or_format_tests_executed'] is False
    assert complete['qualification_transferred_to_mutated_tree'] is False and complete['remote_refs_changed'] is False
    assert complete['diagnostic_only'] is True and complete['behavior_repair_claimed'] is False
    assert complete['original_r29_failure_relabelled_as_pass'] is False
    snapshot_names = [('tested', 'tested-pre-fix-source'), ('after_fix', 'post-fix-source'), ('after_format', 'final-post-format-source')]
    snapshots = {}
    archives = []
    for key, label in snapshot_names:
        row = complete[key]
        verify_pin(label + '-manifest.json', row['manifest'])
        manifest = read_json(label + '-manifest.json')
        assert manifest['source_tree'] == row['tree'] == (FORMATTED if key == 'after_format' else TESTED)
        assert len(manifest['changed_files']) == row['source_paths'] == 197
        assert manifest['source_snapshot_complete'] is True
        assert manifest['post_fix_or_format_tests_executed'] is False and manifest['qualification_transferred_to_mutated_tree'] is False
        assert manifest['cargo_lock_sha256'] == complete['cargo_lock_sha256']
        assert manifest['bazel_lock_sha256'] == complete['bazel_lock_sha256']
        assert manifest['native_head'] == complete['native_HEAD']
        snapshots[key] = {f['path']: f for f in manifest['changed_files']}
        assert len(snapshots[key]) == 197
        info_name = label + '.tar.gz.file-info-original.json'
        info = json.loads((D / 'transport' / info_name).read_bytes())
        assert info['size'] == row['archive']['bytes'] and info['sha256'] == row['archive']['sha256']
        archives.append({'label': label, 'manifest_pin': row['manifest'], 'archive_pin': row['archive'],
                         'actual_file_info': info, 'full_source_archive_downloaded_by_this_reader': False})
    assert snapshots['tested'] == snapshots['after_fix']
    assert set(snapshots['tested']) == set(snapshots['after_format'])
    original_manifest = json.loads((ROOT / 'source53-final-scope-preparation/input/native-candidate-r30-source.json').read_bytes())
    assert {f['path']: f for f in original_manifest['changed_files']} == snapshots['tested']
    changed = sorted(path for path in snapshots['tested'] if snapshots['tested'][path] != snapshots['after_format'][path])
    assert len(changed) == 56 and sum(path.endswith('.rs') for path in changed) == 54
    assert [path for path in changed if path.endswith('.py')] == ['scripts/run-nextest.py', 'scripts/test_run_nextest_helpers.py']

    phases = []
    for label, event_index, expected_after in [('fix', 1, TESTED), ('format', 4, FORMATTED)]:
        raw = read_json(label + '-raw-process-result.json')
        receipt = read_json(label + '-receipt.json')
        post = read_json(label + '-post-command-guard.json')
        verify_pin(label + '-receipt.json', complete[label + '_receipt'])
        for field, name in [('raw_process_result', label + '-raw-process-result.json'), ('log', label + '.log'),
                            ('resources', label + '-resources.txt'), ('phase_only_patch', label + '-only.patch'),
                            ('source_postguard', label + '-post-command-guard.json')]:
            verify_pin(name, receipt[field])
        assert raw['command'] == receipt['command'] == authorization['sequence'][0 if label == 'fix' else 1]
        assert raw['exit_code'] == receipt['exit_code'] == receipt['effective_exit_code'] == 0
        assert raw['wait_exception'] is None and receipt['issues'] == [] and receipt['phase_pass'] is True
        assert receipt['after_tree'] == expected_after and receipt['before_tree'] == TESTED
        assert post['pass'] is True and post['issues'] == [] and post['untracked_paths'] == []
        assert post['native_head'] == complete['native_HEAD']
        assert post['cargo_lock_sha256'] == complete['cargo_lock_sha256'] and post['bazel_lock_sha256'] == complete['bazel_lock_sha256']
        assert post['tracked_changed_paths'] == ([] if label == 'fix' else changed)
        assert set(post['tracked_changed_paths']) <= set(post['allowed_paths'])
        assert {f['path']: f for f in post['working_source_files']} == snapshots['after_fix' if label == 'fix' else 'after_format']
        assert raw['start_unix'] == receipt['start_unix'] and raw['end_unix'] == receipt['end_unix']
        assert raw['elapsed_seconds'] == receipt['elapsed_seconds'] == raw['end_unix'] - raw['start_unix']
        assert re.findall(rb'^\s*Exit status: ([0-9]+)\s*$', (E / (label + '-resources.txt')).read_bytes(), re.M) == [b'0']
        event = dict(events[event_index]); assert event.pop('event') == 'finalization-raw-process-return'; assert event == raw
        assert events[event_index + 1] == receipt
        if label == 'fix':
            assert receipt['exact_stage_raw_result'] is None and (E / 'fix-only.patch').read_bytes() == b''
        else:
            stage = read_json('format-stage-raw-process-result.json'); stage_receipt = read_json('format-stage-receipt.json')
            assert stage['command'] == ['git', 'add', '--', *changed]
            assert stage['exit_code'] == stage_receipt['exit_code'] == 0
            assert stage_receipt['command'] == stage['command']
            verify_pin('format-stage-raw-process-result.json', receipt['exact_stage_raw_result'])
            verify_pin('format-stage-raw-process-result.json', stage_receipt['raw_process_result'])
            verify_pin('format-stage-stdout.txt', stage_receipt['stdout'])
            verify_pin('format-stage-stderr.txt', stage_receipt['stderr'])
            assert not (E / 'format-stage-stdout.txt').read_bytes() and not (E / 'format-stage-stderr.txt').read_bytes()
        phases.append({'phase': label, 'raw_exit': 0, 'effective_exit': 0, 'elapsed_seconds': raw['elapsed_seconds'],
                       'before_tree': TESTED, 'after_tree': expected_after, 'changed_path_count': len(post['tracked_changed_paths']),
                       'postguard_pass': True, 'receipt': complete[label + '_receipt']})
    verify_pin('tested-to-final.patch', complete['tested_to_final_patch'])
    assert (E / 'tested-to-final.patch').read_bytes() == (E / 'format-only.patch').read_bytes()
    for name in ['tested-to-final.patch', 'format-only.patch']:
        info = json.loads((D / 'transport' / (name + '.file-info-original.json')).read_bytes())
        actual = pin((E / name).read_bytes()); assert info['size'] == actual['bytes'] and info['sha256'] == actual['sha256']

    log = (E / 'fix.log').read_bytes(); lines = log.splitlines(keepends=True)
    offsets = [0]
    for line in lines: offsets.append(offsets[-1] + len(line))
    headers = [i for i, line in enumerate(lines) if line.startswith(b'warning:')]
    diagnostics = []
    for number, index in enumerate(headers):
        if lines[index].startswith(b'warning: `'):
            continue
        end = headers[number + 1] if number + 1 < len(headers) else len(lines)
        block = log[offsets[index]:offsets[end]]
        locations = re.findall(rb'^\s*-->\s*(.+)\s*$', block, re.M)
        diagnostics.append({'start_line': index + 1, 'end_line_exclusive': end + 1,
                            'byte_start': offsets[index], 'byte_end_exclusive': offsets[end],
                            'message': lines[index].decode().rstrip('\n'),
                            'locations': [x.decode() for x in locations], **pin(block), 'original_block': block.decode()})
    assert len(diagnostics) == 3
    warnings = {'schema': 'hepta.source53-finalization-residual-warning-readback.v1',
                'source_log': {'path': 'evidence/fix.log', **pin(log)}, 'original_command_exit_code': 0,
                'command_was_strict_deny_warnings': False, 'warning_headers_including_summaries': len(headers),
                'distinct_diagnostic_blocks': len(diagnostics), 'diagnostics': diagnostics,
                'lib_test_duplicate_report_preserved_in_full_log': True,
                'native_source_modified_to_silence_warning': False, 'extra_lint_tests_or_fixes_run': False}
    warnings_pin = write_new('WARNINGS-READBACK.json', warnings)
    originals = [{'path': str(p.relative_to(D)), **pin(p.read_bytes())}
                 for p in sorted(D.rglob('*')) if p.is_file() and p.name != 'verify_closed.py' and p.name != 'WARNINGS-READBACK.json']
    readback = {
        'schema': 'hepta.source53-finalization-original-closure-readback.v1',
        'status': 'ORIGINAL_FIX_FORMAT_AND_OUTER_ZERO_WITH_GUARDS_VERIFIED',
        'original_job_id': terminal['job_id'], 'terminal_pin': pin(terminal_raw),
        'outer_returncode': 0, 'stdout_bytes': len(stdout), 'stderr_bytes': 0,
        'raw_controller_ranges': [[0, 917], [917, 8595]], 'automatic_retry_timeout_cancelled': False,
        'phases': phases, 'tested_source_tree': TESTED, 'after_fix_tree': TESTED, 'final_formatted_tree': FORMATTED,
        'final_formatted_commit_pending_root_registration': True,
        'source_manifest_count_each': 197, 'format_changed_paths': changed, 'format_changed_rust': 54, 'format_changed_python': 2,
        'all_change_paths_within_original_approved_selection': True,
        'fix_stage_not_created_because_no_changes': True, 'format_exact_git_stage_exit_code': 0,
        'source_archives': archives, 'full_source_archive_readback_reserved_for_root_and_independent_reader': True,
        'tested_to_final_raw_bytes_reused_from_identical_format_patch_with_both_full_file_info_pins': True,
        'source_commit_gate_results_remain_bound_to_tested_tree': True,
        'post_fix_or_format_tests_or_metadata_executed': False,
        'scope_and_compiler_warnings_not_automatically_expanded_or_silenced': True,
        'residual_warnings': warnings_pin, 'diagnostic_only': True, 'behavior_repair_claimed': False,
        'originals': originals,
    }
    result = write_new('LOCAL-READBACK.json', readback)
    handoff = write_new('HANDOFF-MANIFEST.json', {
        'schema': 'hepta.source53-finalization-original-closure-handoff.v1',
        'readback': result, 'warnings': warnings_pin,
        'verifier': {'path': 'verify_closed.py', **pin(Path(__file__).read_bytes())},
        'native_evidence_files': len(list(E.iterdir())), 'tar_downloads_by_native_agent': 0,
        'originals': originals,
    })
    print(json.dumps({'readback': result, 'warnings': warnings_pin, 'handoff': handoff,
                      'native_evidence_files': len(list(E.iterdir())), 'format_changed_paths': len(changed)}, indent=2))


if __name__ == '__main__':
    main()
