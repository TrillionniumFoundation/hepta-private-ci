"""Root readback of immutable finalizer originals and complete source archives."""
import hashlib
import json
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOSED = ROOT / 'native-validation-results/source53-finalization-closed'
E = CLOSED / 'evidence'
A = ROOT / 'native-validation-results/source53-finalization-archives'

def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

def check(path, expected):
    raw = path.read_bytes()
    got = pin(raw)
    assert all(got[k] == expected[k] for k in got), (str(path), got, expected)
    return raw

def j(path):
    return json.loads(path.read_bytes())

def main():
    handoff = j(CLOSED / 'HANDOFF-MANIFEST.json')
    original_rows = handoff['originals'] + [handoff[k] for k in ['readback', 'warnings', 'verifier']]
    for row in original_rows:
        check(CLOSED / row['path'], row)
    complete = j(E / 'complete.json')
    snapshots = {}
    checked = []
    for key, label in [('tested', 'tested-pre-fix-source'), ('after_fix', 'post-fix-source'), ('after_format', 'final-post-format-source')]:
        ar = A / label / (label + '.tar.gz')
        check(ar, complete[key]['archive'])
        manifest_raw = check(E / (label + '-manifest.json'), complete[key]['manifest'])
        manifest = json.loads(manifest_raw)
        rows = {row['path']: row for row in manifest['changed_files']}
        assert len(rows) == complete[key]['source_paths'] == 197
        assert manifest['source_snapshot_complete'] and not manifest['post_fix_or_format_tests_executed']
        assert not manifest['qualification_transferred_to_mutated_tree']
        assert manifest['native_head'] == complete['native_HEAD']
        for lock in ['cargo_lock_sha256', 'bazel_lock_sha256']:
            assert manifest[lock] == complete[lock]
        expected = {'source-manifest.json', *('source/' + path for path in rows)}
        source_bytes = {}
        with tarfile.open(ar, 'r:gz') as tf:
            members = tf.getmembers()
            assert len(members) == 198 and {m.name for m in members} == expected
            for member in members:
                assert member.isfile()
                raw = tf.extractfile(member).read()
                assert raw == (A / label / 'original' / member.name).read_bytes()
                if member.name == 'source-manifest.json':
                    assert raw == manifest_raw
                    continue
                path = member.name.removeprefix('source/')
                row = rows[path]
                assert pin(raw) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
                assert member.mode == (int(row['mode'], 8) & 0o777)
                source_bytes[path] = raw
        snapshots[key] = source_bytes
        checked.append({'label': label, 'archive': pin(ar.read_bytes()), 'source_files': 197, 'manifest': pin(manifest_raw), 'tar_member_modes_equal_git_modes': True})
    assert snapshots['tested'] == snapshots['after_fix']
    for path, raw in snapshots['tested'].items():
        assert raw == (ROOT / 'native-validation-results/r31-archive-closed/original/source' / path).read_bytes(), path
    assert snapshots['tested'].keys() == snapshots['after_format'].keys()
    changed = sorted(path for path in snapshots['tested'] if snapshots['tested'][path] != snapshots['after_format'][path])
    assert len(changed) == 56
    assert sum(path.endswith('.rs') for path in changed) == 54
    assert [path for path in changed if path.endswith('.py')] == ['scripts/run-nextest.py', 'scripts/test_run_nextest_helpers.py']
    assert (E / 'fix-only.patch').read_bytes() == b''
    patch = check(E / 'tested-to-final.patch', complete['tested_to_final_patch'])
    assert patch == (E / 'format-only.patch').read_bytes()
    patch_paths = re.findall(rb'^diff --git a/(\S+) b/\1$', patch, re.M)
    assert sorted(p.decode() for p in patch_paths) == changed

    terminal = j(CLOSED / 'controller/terminal-process-status-original.json')
    assert terminal['job_id'] == '1a1b2a75955-fc05-7f27'
    assert terminal['state'] == 'succeeded' and terminal['exit_code'] == 0
    assert terminal['output_complete'] and terminal['output_durable'] and terminal['terminal_publication_confirmed']
    assert not any(terminal[k] for k in ['automatic_retry', 'timed_out', 'cancelled'])
    stdout = (CLOSED / 'controller/original-stdout.log').read_bytes()
    stderr = (CLOSED / 'controller/original-stderr.log').read_bytes()
    assert len(stdout) == terminal['log_bytes']['stdout']['seen'] == terminal['log_bytes']['stdout']['stored'] == 8595
    assert len(stderr) == terminal['log_bytes']['stderr']['seen'] == terminal['log_bytes']['stderr']['stored'] == 0
    events = [json.loads(line) for line in stdout.splitlines()]
    auth = j(CLOSED / 'input/ROOT-EXECUTION-AUTHORIZATION.json')
    check(CLOSED / 'input/executed.py', auth['script'])
    phases = []
    for n, label in enumerate(['fix', 'format']):
        raw = j(E / (label + '-raw-process-result.json'))
        rec = j(E / (label + '-receipt.json'))
        guard = j(E / (label + '-post-command-guard.json'))
        check(E / (label + '-receipt.json'), complete[label + '_receipt'])
        for key, suffix in [('log', '.log'), ('raw_process_result', '-raw-process-result.json'), ('resources', '-resources.txt'), ('source_postguard', '-post-command-guard.json'), ('phase_only_patch', '-only.patch')]:
            check(E / (label + suffix), rec[key])
        assert raw['command'] == rec['command'] == auth['sequence'][n]
        assert raw['exit_code'] == rec['exit_code'] == rec['effective_exit_code'] == 0
        assert rec['issues'] == [] and rec['phase_pass'] is True
        assert raw['wait_exception'] is None
        assert raw['elapsed_seconds'] == rec['elapsed_seconds'] == raw['end_unix'] - raw['start_unix']
        assert guard['pass'] and guard['issues'] == [] and guard['untracked_paths'] == []
        assert guard['tracked_changed_paths'] == ([] if n == 0 else changed)
        assert set(guard['tracked_changed_paths']) <= set(guard['allowed_paths'])
        assert guard['native_head'] == complete['native_HEAD']
        for lock in ['cargo_lock_sha256', 'bazel_lock_sha256']:
            assert guard[lock] == complete[lock]
        assert re.findall(rb'^\s*Exit status: (\d+)\s*$', (E / (label + '-resources.txt')).read_bytes(), re.M) == [b'0']
        event = dict(events[1 + 3 * n]); assert event.pop('event') == 'finalization-raw-process-return'; assert event == raw
        assert events[2 + 3 * n] == rec
        phases.append({'phase': label, 'command': raw['command'], 'raw_exit': 0, 'effective_exit': 0, 'elapsed_seconds': raw['elapsed_seconds']})
    assert auth['sequence'][0][:3] == ['just', 'fix', '--locked']
    assert len(auth['sequence'][0][3:]) == 52 and auth['sequence'][0][3::2] == ['-p'] * 26
    assert auth['sequence'][1] == ['just', 'fmt']
    warnings = j(CLOSED / 'WARNINGS-READBACK.json')
    log = (E / 'fix.log').read_bytes()
    assert warnings['distinct_diagnostic_blocks'] == 3
    for row in warnings['diagnostics']:
        raw = log[row['byte_start']:row['byte_end_exclusive']]
        assert pin(raw) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
        assert raw.decode() == row['original_block']
    assert not complete['post_fix_or_format_tests_executed'] and not complete['qualification_transferred_to_mutated_tree']
    assert complete['diagnostic_only'] and not complete['behavior_repair_claimed']
    result = {'schema': 'hepta.root-full-finalization-readback.v1', 'status': 'FULL_ORIGINALS_AND_THREE_SOURCE_ARCHIVES_VERIFIED',
              'original_pins_checked': len(original_rows), 'archives': checked, 'phases': phases,
              'tested_source_commit': complete['tested_source_commit'], 'tested_source_tree': complete['tested_source_tree'],
              'after_fix_tree': complete['after_fix']['tree'], 'final_formatted_tree': complete['final_formatted_tree'],
              'native_HEAD': complete['native_HEAD'], 'formatted_paths': changed,
              'all197_tested_source_files_equal_full_R31_archive': True,
              'actual_format_patch_pathset_equals56_changed_sources': True,
              'residual_independent_warning_diagnostics': 3, 'original_fix_zero_is_not_strict_D_warnings_clean': True,
              'post_format_test_qualification_transferred': False, 'extra_tests_or_metadata_invoked': False,
              'static_semantic_and_patch_application_review_delegated_to_independent_reader': True,
              'source_registration_pending_actual_Git_API': True, 'science': 'HOLD', 'authority': 'DENY_ALL'}
    target = Path(__file__).parent / 'ROOT-COMPLETE-READBACK.json'
    data = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()
    with target.open('xb') as handle: handle.write(data)
    print(json.dumps({'path': str(target.relative_to(ROOT)), **pin(data), 'source_snapshots': 3, 'formatted_paths': len(changed), 'original_pins_checked': len(original_rows)}, indent=2))

if __name__ == '__main__':
    main()
